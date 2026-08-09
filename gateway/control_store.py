"""Durable transactional control state for the harness gateway (HR-INF-010/011/012/013).

Hot control state (idempotency reservations, per-session execution leases with
fencing tokens, and monotonic response/cancellation state) lives here in a
dedicated Cosmos NoSQL container — NOT on the shared Gremlin partition, and NOT
in per-process dicts that don't survive a replica or coordinate across replicas.

Why Cosmos NoSQL: point reads, atomic create (409 on duplicate id → race-safe
reservation), ETag optimistic concurrency (if_match CAS), per-item TTL, and a
partition key so one org can't be a global hot spot. Auth is AAD via the
gateway's managed identity (no key on the hot path).

Design contract:
- Every item has `pk` (partition key) = f"org::{org}" so all of an org's control
  state co-locates and no cross-org scan is ever needed.
- Idempotency: id=f"idem::{org}::{sha}". reserve() does create_item; a 409 means
  another request already reserved it — the caller reads the winner and replays.
- Lease: id=f"lease::{org}::{sid}". A monotonic integer `fence` is bumped once per
  turn; the turn carries its fence and only commits a checkpoint if the lease
  fence still equals it (a newer turn would have advanced it → stale writer skips).
- Response control: id=f"resp::{org}::{rid}". `terminal` is a one-way latch — once
  a terminal status (cancelled/completed/failed/incomplete) is set, no later write
  may move it back to a live status. This makes cancellation monotonic.

FAIL-CLOSED where correctness demands it (idempotency reserve), best-effort where
it only optimizes (lease/heartbeat) — each call site decides. When COSMOS_ENDPOINT
is unset (local dev), enabled() is False and callers fall back to prior behavior.
"""
from __future__ import annotations

import os
import time

_ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "").strip()
_DB = os.environ.get("HR_CONTROL_DB", "agentstudio")
_CONTAINER = os.environ.get("HR_CONTROL_CONTAINER", "hr_control")
# Optional master key (fallback); AAD via managed identity is preferred.
_KEY = os.environ.get("COSMOS_KEY", "").strip()

_client = None          # CosmosClient (aio)
_cont = None            # ContainerProxy


def _local_mode() -> bool:
    """Self-hosted: no hosted document store configured, so use the SQLite container.
    Mirrors how backing.py chooses its storage, so one env var story covers both."""
    if _ENDPOINT:
        return False
    return (os.environ.get("HR_BACKING", "").strip().lower() or "local") == "local"


def _exceptions():
    """The error namespace matching the ACTIVE container.

    Both namespaces expose the same class names, so every `except cex.CosmosX` below is
    correct under either backing and none of the control-store logic needs a conditional."""
    if _local_mode():
        import control_sqlite
        return control_sqlite
    from azure.cosmos import exceptions as cex
    return cex


def enabled() -> bool:
    """True when a control plane is available. Self-hosted always has one (SQLite), so
    idempotency and leases work there instead of failing closed with a 503."""
    return bool(_ENDPOINT) or _local_mode()


def _pk(org: str) -> str:
    return f"org::{org}"


async def _retryable(coro_factory, attempts: int = 3):
    """Run a Cosmos coroutine with a tiny backoff on TRANSIENT errors (429/503/408/
    network) so a momentary hiccup doesn't turn a keyed request into a hard 503.
    Non-transient errors (409/404/412) propagate immediately — the caller handles
    them as control-flow. coro_factory must return a FRESH awaitable each call."""
    import asyncio as _a
    cex = _exceptions()
    last = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except cex.CosmosHttpResponseError as e:
            if getattr(e, "status_code", None) not in (408, 429, 449, 503):
                raise
            last = e
        except Exception as e:  # azure.core ServiceRequestError/ServiceResponseError (network)
            name = type(e).__name__
            if "ServiceRequest" not in name and "ServiceResponse" not in name:
                raise
            last = e
        await _a.sleep(0.2 * (i + 1))
    raise last  # exhausted transient retries — caller fails closed


async def _container():
    """Lazily build the async Cosmos container proxy. Raises on misconfig so
    fail-closed call sites surface a retryable error instead of running open."""
    global _client, _cont
    if _cont is not None:
        return _cont
    if _local_mode():
        # Self-hosted: one SQLite file beside the rest of the local data.
        import control_sqlite
        root = os.environ.get("HR_DATA_DIR", ".hr-data")
        _cont = control_sqlite.SqliteContainer(os.path.join(root, "control.db"))
        return _cont
    if not _ENDPOINT:
        raise RuntimeError("control store not configured (COSMOS_ENDPOINT unset)")
    from azure.cosmos.aio import CosmosClient
    if _KEY:
        _client = CosmosClient(_ENDPOINT, credential=_KEY)
    else:
        # Managed identity — same UAMI the gateway uses for the session pool.
        from azure.identity.aio import DefaultAzureCredential
        cred = DefaultAzureCredential(
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID") or None)
        _client = CosmosClient(_ENDPOINT, credential=cred)
    db = _client.get_database_client(_DB)
    _cont = db.get_container_client(_CONTAINER)
    return _cont


# ── idempotency ───────────────────────────────────────────────────────────────
async def idem_reserve(org: str, sha: str, resp_id: str, req_hash: str,
                       ttl_s: int) -> dict | None:
    """Atomically reserve (org, sha) for resp_id. Returns None if WE won the race
    (caller proceeds to execute). Returns the EXISTING record if someone else
    already reserved it (caller replays that resp_id). Raises on store failure so
    the caller can fail closed with a retryable 503."""
    cont = await _container()
    item = {"id": f"idem::{org}::{sha}", "pk": _pk(org), "kind": "idem",
            "resp_id": resp_id, "req_hash": req_hash, "state": "reserved",
            "ts": time.time(), "ttl": int(ttl_s)}
    cex = _exceptions()
    try:
        await _retryable(lambda: cont.create_item(item))
        return None                      # we won
    except cex.CosmosResourceExistsError:
        try:
            return await _retryable(lambda: cont.read_item(item["id"], partition_key=_pk(org)))
        except cex.CosmosResourceNotFoundError:
            # The item existed at create time but is gone now — a TTL expiry between the
            # 409 and this read. Genuinely nobody holds it → treat as won. Any OTHER error
            # (network/transient) must PROPAGATE so the caller fails closed; swallowing it
            # here would let BOTH racers execute and map the key to the wrong resp_id.
            return None


async def idem_get(org: str, sha: str) -> dict | None:
    cont = await _container()
    cex = _exceptions()
    try:
        return await _retryable(lambda: cont.read_item(f"idem::{org}::{sha}", partition_key=_pk(org)))
    except cex.CosmosResourceNotFoundError:
        return None


async def idem_release(org: str, sha: str, resp_id: str) -> None:
    """Best-effort release of a reservation whose request failed BEFORE it
    persisted any response record — otherwise a retry would replay a resp_id that
    never produced a result (a 'poisoned' key). Only deletes the item if it still
    points at OUR resp_id (never clobber a reservation that a retry already reused)."""
    cex = _exceptions()
    try:
        cont = await _container()
        cur = await cont.read_item(f"idem::{org}::{sha}", partition_key=_pk(org))
        if str(cur.get("resp_id") or "") == resp_id:
            await cont.delete_item(f"idem::{org}::{sha}", partition_key=_pk(org))
    except cex.CosmosResourceNotFoundError:
        return
    except Exception:  # noqa: BLE001
        return


# ── per-session execution lease (fencing) ──────────────────────────────────────
async def lease_acquire(org: str, sid: str, owner: str, ttl_s: int) -> int:
    """Bump and take the session lease; returns THIS turn's fence token (monotonic
    int). A newer turn will get a higher fence, so a stale turn detects it lost the
    workspace at checkpoint time. Best-effort: returns 0 on contention exhaustion OR
    any store error (the caller then behaves as today — no fencing, but the turn
    still runs). NOTE: fencing is not yet wired into the turn path (deferred)."""
    cex = _exceptions()
    try:
        cont = await _container()
        doc_id = f"lease::{org}::{sid}"
        for _ in range(5):                   # bounded CAS retry
            try:
                cur = await cont.read_item(doc_id, partition_key=_pk(org))
                fence = int(cur.get("fence", 0)) + 1
                cur.update(fence=fence, owner=owner, expires=time.time() + ttl_s,
                           ts=time.time(), ttl=max(int(ttl_s) * 4, 3600))
                await cont.replace_item(doc_id, cur,
                                        etag=cur["_etag"], match_condition=_IF_MATCH)
                return fence
            except cex.CosmosResourceNotFoundError:
                try:
                    await cont.create_item({"id": doc_id, "pk": _pk(org), "kind": "lease",
                                            "fence": 1, "owner": owner,
                                            "expires": time.time() + ttl_s,
                                            "ts": time.time(), "ttl": max(int(ttl_s) * 4, 3600)})
                    return 1
                except cex.CosmosResourceExistsError:
                    continue                 # someone created it first — retry the read/bump
            except cex.CosmosAccessConditionFailedError:
                continue                     # ETag moved under us — retry
        return 0                             # gave up (contention) → unfenced fallback
    except Exception:                        # noqa: BLE001 — store down: fail open per docstring
        return 0


async def lease_admit(org: str, sid: str, owner: str, ttl_s: int, *,
                      reject_on_conflict: bool = False, fresh_s: float = 75.0) -> dict:
    """Admission gate at turn start. Reads the session lease and classifies the incumbent:
    a DIFFERENT owner counts as an ACTIVE conflict only if its lease is BOTH live (expires in
    the future) AND fresh (heartbeated within `fresh_s`) — so a crashed/completed-but-unreleased
    lease (which stops renewing) does NOT falsely reject a legitimate follow-up.

    Returns {fence, conflict, rejected, holder}.
    - reject_on_conflict=False (observe): ALWAYS take ownership (bump fence) and just report the
      conflict — the turn proceeds; fence identifies it for checkpoint/heartbeat.
    - reject_on_conflict=True (enforce): on an ACTIVE conflict, DO NOT touch the lease (never steal
      the running turn's fence — that would make ITS checkpoint stale) and return rejected=True so
      the caller refuses the duplicate. Otherwise take ownership.
    Best-effort: on any store error returns {fence:0, conflict:False, rejected:False} → fail OPEN."""
    cex = _exceptions()
    doc_id = f"lease::{org}::{sid}"
    now = time.time()
    try:
        cont = await _container()
        for _ in range(5):
            try:
                cur = await cont.read_item(doc_id, partition_key=_pk(org))
                held_by = str(cur.get("owner") or "")
                live = float(cur.get("expires") or 0) > now
                fresh = (now - float(cur.get("ts") or 0)) < fresh_s
                other = bool(held_by and held_by != owner)
                conflict = bool(live and other)
                active_conflict = bool(conflict and fresh)
                if reject_on_conflict and active_conflict:
                    # Refuse WITHOUT modifying the lease — the incumbent keeps its fence.
                    return {"fence": 0, "conflict": True, "rejected": True, "holder": held_by}
                fence = int(cur.get("fence", 0)) + 1
                cur.update(fence=fence, owner=owner, expires=now + ttl_s, ts=now,
                           ttl=max(int(ttl_s) * 4, 3600))
                try:
                    await cont.replace_item(doc_id, cur, etag=cur["_etag"], match_condition=_IF_MATCH)
                    return {"fence": fence, "conflict": conflict, "rejected": False, "holder": held_by}
                except cex.CosmosAccessConditionFailedError:
                    continue                 # another writer moved it — re-read
            except cex.CosmosResourceNotFoundError:
                try:
                    await cont.create_item({"id": doc_id, "pk": _pk(org), "kind": "lease",
                                            "fence": 1, "owner": owner, "expires": now + ttl_s,
                                            "ts": now, "ttl": max(int(ttl_s) * 4, 3600)})
                    return {"fence": 1, "conflict": False, "rejected": False, "holder": ""}
                except cex.CosmosResourceExistsError:
                    continue
        return {"fence": 0, "conflict": False, "rejected": False, "holder": ""}
    except Exception:  # noqa: BLE001 — store down: fail open (turn runs unfenced)
        return {"fence": 0, "conflict": False, "rejected": False, "holder": ""}


async def lease_renew(org: str, sid: str, owner: str, fence: int, ttl_s: int) -> bool:
    """Heartbeat: extend the lease expiry while WE still hold `fence`. Without this a long turn's
    lease would expire and a follow-up could steal it and wipe the live workspace. Best-effort."""
    if fence <= 0:
        return False
    cex = _exceptions()
    doc_id = f"lease::{org}::{sid}"
    try:
        cont = await _container()
        cur = await cont.read_item(doc_id, partition_key=_pk(org))
        if int(cur.get("fence", 0)) != fence or str(cur.get("owner") or "") != owner:
            return False                     # superseded — we no longer hold it
        cur.update(expires=time.time() + ttl_s, ts=time.time())
        try:
            await cont.replace_item(doc_id, cur, etag=cur["_etag"], match_condition=_IF_MATCH)
            return True
        except cex.CosmosAccessConditionFailedError:
            return False
    except Exception:  # noqa: BLE001
        return False


async def lease_release(org: str, sid: str, owner: str, fence: int) -> None:
    """Turn end: relinquish the lease (expire it now) if we still hold `fence`, so a follow-up
    turn admits without waiting out the TTL. Best-effort; never blocks turn completion."""
    if fence <= 0:
        return
    cex = _exceptions()
    doc_id = f"lease::{org}::{sid}"
    try:
        cont = await _container()
        cur = await cont.read_item(doc_id, partition_key=_pk(org))
        if int(cur.get("fence", 0)) != fence or str(cur.get("owner") or "") != owner:
            return
        cur.update(expires=0, ts=time.time())
        try:
            await cont.replace_item(doc_id, cur, etag=cur["_etag"], match_condition=_IF_MATCH)
        except cex.CosmosAccessConditionFailedError:
            return
    except Exception:  # noqa: BLE001
        return


async def lease_still_held(org: str, sid: str, fence: int) -> bool:
    """True iff the lease fence is UNCHANGED since this turn acquired it. Used to
    gate the checkpoint write so a superseded turn never clobbers newer work.
    Fail-safe: if the store is unreadable we return True (write proceeds) rather
    than silently drop a checkpoint — availability over the rare stale-write race,
    since a single-turn session never advances its own fence."""
    if fence <= 0:
        return True                      # unfenced (store was down at acquire) — don't block
    try:
        cont = await _container()
        cur = await cont.read_item(f"lease::{org}::{sid}", partition_key=_pk(org))
        return int(cur.get("fence", 0)) == fence
    except Exception:
        return True


# ── response control (monotonic cancellation) ──────────────────────────────────
_TERMINAL = {"cancelled", "completed", "failed", "incomplete"}


async def resp_put_running(org: str, rid: str, sid: str, runner_turn_id: str,
                           ttl_s: int) -> None:
    """Upsert a response-control record as live. NEVER downgrades a terminal record
    back to running (monotonic latch) — a cancel that already landed wins."""
    cont = await _container()
    cex = _exceptions()
    doc_id = f"resp::{org}::{rid}"
    try:
        cur = await cont.read_item(doc_id, partition_key=_pk(org))
        if str(cur.get("status")) in _TERMINAL:
            return                       # already terminal — do not revive
        cur.update(status="running", sid=sid, runner_turn_id=runner_turn_id, ts=time.time())
        try:
            await cont.replace_item(doc_id, cur, etag=cur["_etag"], match_condition=_IF_MATCH)
        except cex.CosmosAccessConditionFailedError:
            pass                         # a terminal write raced in — leave it terminal
    except cex.CosmosResourceNotFoundError:
        try:
            await cont.create_item({"id": doc_id, "pk": _pk(org), "kind": "resp",
                                    "status": "running", "sid": sid,
                                    "runner_turn_id": runner_turn_id,
                                    "ts": time.time(), "ttl": int(ttl_s)})
        except cex.CosmosResourceExistsError:
            pass


async def resp_set_cursor(org: str, rid: str, cursor: int) -> None:
    """Persist the turn's harvest cursor — how many of THIS turn's events (sandbox per-turn index)
    have been durably flushed to the trace. This is the resume point if the owning replica dies and
    another adopts the turn: it polls the sandbox with since=cursor, so no already-flushed event is
    re-written or re-emitted. Monotonic (never moves backward); best-effort; never revives a terminal
    record. Cheap single-field patch on the existing resp:: control doc."""
    cont = await _container()
    cex = _exceptions()
    doc_id = f"resp::{org}::{rid}"
    try:
        curr = await cont.read_item(doc_id, partition_key=_pk(org))
    except cex.CosmosResourceNotFoundError:
        return                               # turn not registered yet — nothing to update
    if str(curr.get("status")) in _TERMINAL:
        return                               # already settled — cursor is moot
    if int(cursor) <= int(curr.get("harvest_cursor", 0) or 0):
        return                               # monotonic: never move the resume point backward
    curr["harvest_cursor"] = int(cursor)
    curr["ts"] = time.time()
    try:
        await cont.replace_item(doc_id, curr, etag=curr["_etag"], match_condition=_IF_MATCH)
    except cex.CosmosAccessConditionFailedError:
        pass                                 # a concurrent write won — fine, cursor is advisory


async def resp_get_cursor(org: str, rid: str) -> int:
    """The durable harvest cursor for a turn (0 if none / unreadable). See resp_set_cursor."""
    cont = await _container()
    cex = _exceptions()
    try:
        curr = await cont.read_item(f"resp::{org}::{rid}", partition_key=_pk(org))
        return int(curr.get("harvest_cursor", 0) or 0)
    except cex.CosmosResourceNotFoundError:
        return 0
    except Exception:  # noqa: BLE001
        return 0


async def resp_mark_terminal(org: str, rid: str, status: str, ttl_s: int) -> dict:
    """One-way transition to a terminal status. Returns the record (with sid +
    runner_turn_id) so the caller can propagate cancellation to the runner.
    Idempotent: re-marking an already-terminal record just returns it."""
    cont = await _container()
    cex = _exceptions()
    doc_id = f"resp::{org}::{rid}"
    for _ in range(5):
        try:
            cur = await cont.read_item(doc_id, partition_key=_pk(org))
            if str(cur.get("status")) in _TERMINAL:
                return cur
            cur.update(status=status, ts=time.time())
            try:
                await cont.replace_item(doc_id, cur, etag=cur["_etag"], match_condition=_IF_MATCH)
                return cur
            except cex.CosmosAccessConditionFailedError:
                continue
        except cex.CosmosResourceNotFoundError:
            rec = {"id": doc_id, "pk": _pk(org), "kind": "resp", "status": status,
                   "sid": "", "runner_turn_id": "", "ts": time.time(), "ttl": int(ttl_s)}
            try:
                await cont.create_item(rec)
                return rec
            except cex.CosmosResourceExistsError:
                continue
    return {}


async def resp_is_cancelled(org: str, rid: str) -> bool:
    try:
        cont = await _container()
        cex = _exceptions()
        try:
            cur = await cont.read_item(f"resp::{org}::{rid}", partition_key=_pk(org))
        except cex.CosmosResourceNotFoundError:
            return False
        return str(cur.get("status")) == "cancelled"
    except Exception:
        return False


async def try_lock(name: str, ttl_s: int) -> bool:
    """One-shot distributed mutex via atomic create_item: returns True iff WE created the lock doc
    (nobody else holds it), False if it already exists (another holder — skip this cycle). Per-item
    TTL auto-expires the lock, so a holder that dies never wedges it. RAISES on a store error so the
    caller can distinguish 'someone else has it' (skip) from 'store unavailable' (the caller's choice
    to fall back). Used for single-flight periodic work (the winner runs it, losers skip)."""
    cex = _exceptions()
    try:
        cont = await _container()
        await cont.create_item({"id": f"lock::{name}", "pk": "org::_system", "kind": "lock",
                                "ts": time.time(), "ttl": int(ttl_s)})
        return True
    except cex.CosmosResourceExistsError:
        return False


# ── API-key hot-read cache (HR-INF-010) ────────────────────────────────────────────────
# The public Bearer auth read (_apikey_resolve) hit the shared Gremlin partition on EVERY public
# request. These make the control store the hot-path read: a SELF-KEYED doc (pk == id == the token
# hash — the org is unknown pre-auth, so an org partition can't serve it) that is a write-through
# cache of the graph key record. The graph stays the source of truth (list/durable); dual-writes on
# mint/revoke keep this in sync (instant revocation, no TTL lag), and a lazy backfill on first
# resolve migrates pre-existing keys so Gremlin is never hit on the hot path afterward.
def _apikey_id(sha: str) -> str:
    return f"apikey::{sha}"


# Per-item TTL on key docs: NOT the revocation mechanism (dual-write on revoke is, giving instant
# revocation) — it's a STALENESS BOUND. If a revoke's dual-write ever fails, the stale-valid cache
# doc expires within this window and the next resolve falls back to the authoritative graph
# (revoked). An active key is re-backfilled at most once per TTL (one Gremlin read/hour), negligible.
_APIKEY_TTL_S = int(os.environ.get("HR_APIKEY_TTL_S", "3600"))


async def apikey_get(sha: str) -> dict | None:
    """Point-read a key doc by hash. Returns None on miss OR on ANY error (incl. a missing SDK /
    misconfig) — the caller falls back to the graph (the source of truth), so nothing here can
    ever fail-close public auth."""
    try:
        cex = _exceptions()
        cont = await _container()
        try:
            return await _retryable(lambda: cont.read_item(_apikey_id(sha), partition_key=_apikey_id(sha)))
        except cex.CosmosResourceNotFoundError:
            return None
    except Exception:  # noqa: BLE001 — store down / SDK missing → graph fallback
        return None


async def apikey_put(sha: str, org: str, member: str, workspace: str,
                     workspace_default: bool, revoked: bool = False,
                     create_only: bool = False) -> None:
    """Write the key doc, TTL-bounded. mint uses upsert (authoritative fresh key). The lazy
    BACKFILL uses create_only=True: a create_item that 409s (a doc already exists — possibly a
    revoke tombstone written in the race window) leaves it untouched. A plain upsert here would
    resurrect a just-revoked key for up to a TTL (HR-INF-010 review #1)."""
    cont = await _container()
    item = {"id": _apikey_id(sha), "pk": _apikey_id(sha), "kind": "apikey",
            "org": org, "member": member, "workspace": workspace,
            "workspace_default": bool(workspace_default), "revoked": bool(revoked),
            "ts": time.time(), "ttl": _APIKEY_TTL_S}
    if create_only:
        cex = _exceptions()
        try:
            await _retryable(lambda: cont.create_item(item))
        except cex.CosmosResourceExistsError:
            return                              # a doc (maybe a tombstone) already exists — never clobber
    else:
        await _retryable(lambda: cont.upsert_item(item))


async def apikey_revoke(sha: str) -> None:
    """Mark a key revoked (dual-write on revoke). Upserts a revoked marker even for a key never
    backfilled, so the hot read returns None immediately without consulting the graph. The revoked
    marker gets a LONGER TTL than a live doc so it can't expire back to a graph re-read before the
    graph revocation is certain to be visible."""
    cont = await _container()
    cex = _exceptions()
    ttl = max(_APIKEY_TTL_S * 24, 86400)   # keep the tombstone well past a live doc's lifetime
    try:
        cur = await _retryable(lambda: cont.read_item(_apikey_id(sha), partition_key=_apikey_id(sha)))
        cur["revoked"] = True
        cur["ttl"] = ttl
        await _retryable(lambda: cont.upsert_item(cur))
    except cex.CosmosResourceNotFoundError:
        await _retryable(lambda: cont.upsert_item({
            "id": _apikey_id(sha), "pk": _apikey_id(sha), "kind": "apikey", "revoked": True,
            "ts": time.time(), "ttl": ttl}))


async def healthcheck() -> bool:
    """Readiness probe: can we actually reach the control store? Cheap point read
    of a sentinel id (404 is a healthy answer — the store responded)."""
    cont = await _container()
    cex = _exceptions()
    try:
        await cont.read_item("health::probe", partition_key="org::_health")
    except cex.CosmosResourceNotFoundError:
        return True
    return True


# azure-cosmos uses azure.core.MatchConditions for optimistic concurrency.
try:  # imported lazily-safe so module import never fails when the SDK is absent
    from azure.core import MatchConditions as _MC
    _IF_MATCH = _MC.IfNotModified
except Exception:  # pragma: no cover
    _IF_MATCH = None
