"""harness-gateway — thin, stateless control plane for Harness-as-a-Service.

Responsibilities (see docs/technical/HARNESS_AS_A_SERVICE_DESIGN.md):
  - Allocate an isolated sandbox per session from the ACA Dynamic Sessions pool and proxy
    turns into the in-sandbox runner (`{POOL}/turn?identifier=<session_id>`, Entra token
    aud `dynamicsessions.io` via the gateway's managed identity).
  - Credential BROKER over the existing Vault service: resolve a provider *connection*
    (org-own first, a shared `global` pool as fallback) and try an ordered fallback chain.
  - Concurrency gating (global + per-tenant); session state externalized to VectorGraph
    (`HarnessSession` vertex) so any replica serves any session.

State lives in VectorGraph + git + Blob, never in-process — this service is replaceable.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import time
import uuid
import zipfile

import base64
import functools
import hashlib
import mimetypes
import pathlib
import shutil
import subprocess
import tarfile
import tempfile

import httpx
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel

import backing               # pluggable graph/blob/secret stores (vg | local)
import control_store  # durable transactional control state (idempotency / lease / monotonic cancel)

POOL_ENDPOINT = os.environ.get("POOL_MGMT_ENDPOINT", "").rstrip("/")
VAULT_URL = os.environ.get("VAULT_URL", "").rstrip("/")
VAULT_INTERNAL_KEY = os.environ.get("VAULT_INTERNAL_KEY", "")
VG_GATEWAY_URL = os.environ.get("VG_GATEWAY_URL", "").rstrip("/")
VG_GATEWAY_KEY = os.environ.get("VG_GATEWAY_KEY", "")
VG_TENANT_DEFAULT = os.environ.get("VG_TENANT_DEFAULT", "")   # hosted-backing only; unused locally
GLOBAL_TENANT = os.environ.get("HARNESS_GLOBAL_TENANT", "global")
BILLING_HARVEST_URL = os.environ.get("BILLING_HARVEST_URL", "").rstrip("/")
BILLING_INTERNAL_KEY = os.environ.get("BILLING_INTERNAL_KEY", "")
# Engine base URL (same engine the console BFF proxies) — used to fetch the pricing table so the
# gateway can stamp a concise per-run credit total on each finished trace. Optional: if unset,
# credits are simply not computed (usage still metered via the harvest as before).
ENGINE_URL = os.environ.get("ENGINE_URL", "").rstrip("/")

# ── backing stores (graph / blob / secrets) ───────────────────────────────────────
# THE seam between this gateway and everything it persists to. Production ("vg") is the
# AgentStudio infra — vg-gateway's Cosmos graph + Azure blob, and the vault service. Local
# ("local") is SQLite + filesystem + env vars, so a clone runs with no cloud at all. Selected by
# HR_BACKING; unset ⇒ vg when VG_GATEWAY_URL is configured, local otherwise. Call sites below use
# only the semantic interface (get/upsert/find/add_edge, blob get/put/list) and never build
# backend queries — that is what makes the two interchangeable.
BACKING = backing.make_backing(
    client_getter=lambda: _client(), vg_url=VG_GATEWAY_URL, vg_key=VG_GATEWAY_KEY,
    vg_tenant=VG_TENANT_DEFAULT, vault_url=VAULT_URL, vault_key=VAULT_INTERNAL_KEY)


# HR-INF-023: billing-report failures were SILENT (every exception + non-2xx swallowed) — metering
# could be lost indefinitely with zero operator signal. Count them (surfaced on /readyz +
# rate-logged like bus_drops) so revenue-affecting loss is observable. Delivery stays
# fire-and-forget by design: metering must never block or fail a turn.
class _OpsDrops:
    """Cumulative drop counter with rate-limited logging — THE visibility mechanism for
    by-design-lossy paths (bus backpressure, billing delivery). Surfaced on /readyz."""

    def __init__(self, name: str, log_every_s: float, kinds: tuple[str, ...]):
        self.name, self._every, self._last = name, log_every_s, 0.0
        self.counts: dict[str, int] = {k: 0 for k in kinds}

    def bump(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        now = time.time()
        if now - self._last > self._every:
            self._last = now
            print(f"[{self.name}] drops (cumulative): {self.counts}", flush=True)


_billing_drops = _OpsDrops("billing", 60, ("errors", "rejects"))


def _report_usage(org: str, metric: str, amount: float) -> None:
    """Fire-and-forget metering to the billing harvest service. Never blocks or
    fails a turn: 3s timeout; failures are COUNTED (never raised)."""
    if not BILLING_HARVEST_URL or not org or amount <= 0:
        return
    async def _post():
        try:
            async with httpx.AsyncClient() as _c:
                r = await _c.post(f"{BILLING_HARVEST_URL}/usage",
                                  json={"org_id": org, "app": "harnessrouter",
                                        "metric": metric, "amount": round(amount, 9)},
                                  headers={"x-internal-key": BILLING_INTERNAL_KEY}, timeout=3)
            if r.status_code >= 400:
                _billing_drops.bump("rejects")   # auth/validation failure — misconfig, not transient
        except Exception:  # noqa: BLE001
            _billing_drops.bump("errors")        # network/timeout — usage event lost
    try:
        asyncio.get_running_loop().create_task(_post())
    except RuntimeError:
        pass


# ── per-run credit costing ────────────────────────────────────────────────────────
# The trace/session card should show a concise per-run CREDIT total so no one has to diff token
# counts by hand. The harvest owns pricing; the gateway fetches the same {app:{metric:rate}} table
# (cached) and computes the run's credits from its usage + elapsed at finalize. Pricing changes
# rarely, so a stale table for a few minutes only shifts a run's shown credits by a rounding-level
# amount — and the AUTHORITATIVE charge still flows through the harvest's own priced consume.
_pricing_table: dict[str, dict[str, float]] = {}
_pricing_fetched_at = 0.0
_PRICING_TTL_S = 300.0


async def _refresh_pricing_table() -> None:
    global _pricing_table, _pricing_fetched_at
    if not ENGINE_URL or not BILLING_INTERNAL_KEY:
        return
    if time.time() - _pricing_fetched_at < _PRICING_TTL_S and _pricing_table:
        return
    try:
        r = await _client().get(f"{ENGINE_URL}/v1/billing/pricing/table",
                                headers={"x-internal-key": BILLING_INTERNAL_KEY}, timeout=10)
        if r.status_code < 400:
            _pricing_table = (r.json() or {}).get("table") or {}
            _pricing_fetched_at = time.time()
    except Exception:  # noqa: BLE001 — keep the stale table; credits are advisory, not the charge
        pass


def _price_of(metric: str) -> float:
    """Credits-per-unit for a metric: harnessrouter-scoped row wins, else the system table
    (same fallback the harvest's price() uses)."""
    hr = _pricing_table.get("harnessrouter", {})
    if metric in hr:
        return float(hr[metric])
    return float(_pricing_table.get("system", {}).get(metric, 0.0))


def _run_credits(model: str, usage: dict, elapsed_s: float) -> float:
    """Concise per-run credit total: Σ token metrics + session-minute, priced by the cached table.
    Mirrors _trace_finalize's metering exactly so the shown figure equals what the harvest bills."""
    total = 0.0
    if elapsed_s:
        total += (elapsed_s / 60.0) * _price_of("harness.session_minute")
    m = model.replace(".", "-") if model.startswith("claude-") else model
    if m:
        for kind, key in (("input_1k", "input_tokens"), ("output_1k", "output_tokens"),
                          ("cache_read_1k", "cache_read_tokens"), ("cache_write_1k", "cache_write_tokens")):
            n = float((usage or {}).get(key) or 0)
            if n > 0:
                total += (n / 1000.0) * _price_of(f"llm.{m}.{kind}")
    return round(total, 6)


# HR-INF-019: how long a draining replica waits for detached turns to finish before it settles the
# stragglers 'failed' and lets the process exit. Must stay under ACA's terminationGracePeriodSeconds
# (600s) so the settle writes land before SIGKILL.
_DRAIN_S = int(os.environ.get("HR_DRAIN_S", "570"))


async def _settle_drained(persist, tr, emit) -> None:
    """Settle a turn cancelled by shutdown drain: emit a terminal failure to the bus (so an open
    Workbench stops showing 'running') and persist 'failed'. Best-effort; never raises."""
    try:
        for ev in tr.fail("gateway draining for redeploy"):
            await emit(ev)
    except Exception:  # noqa: BLE001
        pass
    try:
        await persist("failed")
    except Exception:  # noqa: BLE001
        pass


# HR-INF-023: pre-turn credit admission. The gateway metered usage (above) but never checked
# balance, so a deficit org kept running turns for free — the audit's core gap. The authoritative
# ledger already exists (per-org credit lots + a negative deficit lot in the graph) and is already
# reachable: the harvest service exposes GET /guard/{org} built for exactly this ("402 semantics for
# callers"), server-side cached, that folds the org's lots and returns is_deficit. Four sibling apps
# already gate pre-turn through it. Modes mirror the two existing observe->enforce gates
# (HR_SESSION_LEASE, HR_IDENTITY_MODE):
#   off      — skip entirely.
#   observe  — check + count, but ADMIT (surfaces which orgs WOULD be blocked before flipping).
#   enforce  — a DEFINITIVE deficit is rejected with 402.
# Fail-OPEN on guard trouble (unreachable/unconfigured): the harvest is a single systemd unit, so
# hard-blocking every turn on its availability manufactures a platform-wide SPOF strictly worse than
# the leak — and outage-window usage still WALs on the emitter->harvest path and consolidates into
# the org's deficit lot on recovery, so exposure is bounded, auto-collected debt, not lost revenue.
# This matches every billing touchpoint's explicit fail-open and the lease gate's fail-open-on-store.
HR_CREDIT_GATE = os.environ.get("HR_CREDIT_GATE", "observe").strip().lower()  # off | observe | enforce
_credit_obs = _OpsDrops("credit", 60, ("admitted", "deficit", "rejected", "guard_errors"))
_OUT_OF_CREDITS_DETAIL = ("You are out of credits. Top up in Billing to keep "
                          "running tasks; your workspaces and data stay untouched.")


async def _credit_gate(org: str) -> None:
    """Admit or reject a NEW turn by the org's credit balance. Raises HTTPException(402) in
    enforce mode on a definitive deficit; fails OPEN (counted) on any guard trouble. Must run
    before any idempotency reserve / harness read / lease / hydrate so a rejection unwinds nothing."""
    if HR_CREDIT_GATE == "off" or not org or not BILLING_HARVEST_URL:
        return
    try:
        async with httpx.AsyncClient() as _c:
            # timeout must EXCEED the harvest's own upstream engine-lookup ceiling (8s,
            # billing_harvest/app.py) — a deficit org is never positive-cached there, so its verdict
            # comes from that lookup every turn. A shorter timeout would abandon a slow-but-definitive
            # "is_deficit=true" and silently fail OPEN, defeating enforce for exactly the orgs to block.
            # Healthy orgs are cached 900s (answer instant), so this ceiling only bites cold/hung cases.
            r = await _c.get(f"{BILLING_HARVEST_URL}/guard/{org}",
                             headers={"x-internal-key": BILLING_INTERNAL_KEY}, timeout=10)
            r.raise_for_status()
            deficit = bool(r.json().get("is_deficit"))
    except Exception:  # noqa: BLE001 — guard unreachable → fail OPEN (billing never blocks the product)
        _credit_obs.bump("guard_errors")
        return
    if not deficit:
        _credit_obs.bump("admitted")
        return
    _credit_obs.bump("deficit")
    if HR_CREDIT_GATE == "enforce":
        _credit_obs.bump("rejected")
        raise HTTPException(402, _OUT_OF_CREDITS_DETAIL)
    print(f"[credit] deficit org={org} (observe; would 402 in enforce)", flush=True)
AZURE_CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "")        # UAMI client id for the pool token
DEFAULT_BACKEND = os.environ.get("HARNESS_DEFAULT_BACKEND", "claude")
# Concurrency: gate turns so we never exceed the session pool's sandbox ceiling, but allow many
# sessions per org to run at once (a single user routinely fires off several tasks in parallel).
# Concurrency caps are a back-pressure ceiling, not the scaling limit — the Dynamic Sessions pool
# scales sandboxes on demand (maxConcurrentSessions). Keep these high so a burst of turns runs
# concurrently and waits for the pool to scale, rather than being queued/starved in-process.
# Self-hosted, the ceiling is this ONE machine rather than a pool that scales on demand, so 512
# would just be 512 agent CLIs contending for the same cores. The limit is therefore resolved at
# first use — _pool_is_local() is defined further down, and an env var still overrides either way.
_CONC_ENV_GLOBAL = os.environ.get("HARNESS_GLOBAL_CONCURRENCY", "").strip()
_CONC_ENV_TENANT = os.environ.get("HARNESS_TENANT_CONCURRENCY", "").strip()
# OpenAI Responses-compatible /v1 surface. The web app's BFF (already behind the engine JWT) calls
# /v1/responses with X-Harness-Internal == this key + X-Harness-Org/X-Harness-Member, so it doesn't
# need a user-minted API key. Public callers use Authorization: Bearer sk-hr-... (per-org API keys).
INTERNAL_KEY = os.environ.get("HARNESS_INTERNAL_KEY", "")
# LIVE-B: verified identity on the internal path. The org/member headers used to be TRUSTED
# verbatim behind the internal key — but the BFF forwards them from the BROWSER, so any caller of
# the web app could self-assert another org's identity. Fix: when a platform login JWT (engine-
# minted HS256, the SAME auth-jwt-secret the whole platform verifies with) accompanies the internal
# key, the gateway verifies it and derives org/member FROM ITS CLAIMS (the org claim was already
# membership-checked server-side at switch-org). Calls with the key and NO Authorization header are
# service-to-service (the engine executor) and keep header trust — key possession is the service
# credential. Modes: observe (count/log, keep header trust) -> enforce (claims are authoritative;
# key + a present-but-invalid Authorization is REJECTED).
HR_IDENTITY_MODE = os.environ.get("HR_IDENTITY_MODE", "observe")
AUTH_JWT_SECRET = os.environ.get("AUTH_JWT_SECRET", "")
# Deploy fingerprint (baked at image build via the GIT_SHA build-arg, see Dockerfile) — lets
# release verification bind this running instance to the exact source commit it was built from.
HR_BUILD_SHA = os.environ.get("HR_BUILD_SHA", "unknown")
# Per-replica trace-chunk nonce. Trace event chunks are named by a globally-unique, time-ordered
# key (ms timestamp + this nonce + a per-session flush seq) so that NO two writes — across turns,
# across replicas, or under concurrent follow-ups — can ever collide on a chunk filename. This
# replaces the old per-replica monotonic integer counter, which went stale across turn/replica
# boundaries and silently OVERWROTE a prior turn's chunk (lost events on multi-turn conversations).
_TRACE_NONCE = uuid.uuid4().hex[:8]
# Streaming poll cadence for the /v1/responses path — much faster than the background driver's 30s
# because an open SSE connection wants timely deltas (and the fast poll also keeps the sandbox warm).
RESP_POLL_S = float(os.environ.get("HARNESS_RESP_POLL_S", "1.2"))
# Output (container) files produced by a turn are capped to keep a single response bounded.
RESP_MAX_FILES = int(os.environ.get("HARNESS_RESP_MAX_FILES", "25"))
RESP_MAX_FILE_BYTES = int(os.environ.get("HARNESS_RESP_MAX_FILE_BYTES", str(25 * 1024 * 1024)))
# /v1/files upload cap (HR-INF-015): the route had NO cap — a huge upload buffered whole in the
# gateway AND ballooned again as base64 in the runner turn body. 25 MiB matches the engine's
# attachment cap and RESP_MAX_FILE_BYTES, bounding the inline-b64 turn payload to ~33 MB.
_UPLOAD_MAX_BYTES = int(os.environ.get("HARNESS_UPLOAD_MAX_BYTES", str(25 * 1024 * 1024)))
RESP_BLOB_KB = os.environ.get("HARNESS_RESP_BLOB_KB", "harness-responses")  # response records + container files
# Durable session-workspace store (git checkpoint tarball per session) lives in vg-gateway blob
# storage under this "graph" namespace: <KB>/sessions/<sid>/workspace.tgz.
BLOB_KB = os.environ.get("HARNESS_BLOB_KB", "harness-sessions")
# Realtime blackboard: the Company Brain Hocuspocus wss endpoint the in-sandbox sidecar connects to.
# At session-create the gateway mints a Brain doc (under the DEFAULT tenant, so the studio editor —
# which opens by bare ULID — resolves the SAME room) and uses its ULID as the room. Empty = disabled.
COLLAB_URL = os.environ.get("COLLAB_URL", "").rstrip("/")        # wss://<company-brain-fqdn>
# Public base for URLs we hand back to clients (annotations, files listings). The content
# proxy stays header-authenticated; this only makes the returned links resolvable OUTSIDE
# the backend host (set it to your public base URL). Empty -> host-relative.
PUBLIC_BASE_URL = os.environ.get("HARNESS_PUBLIC_BASE_URL", "").rstrip("/")
# Default per-turn wall-clock cap when neither the request nor the harness sets one.
# The runner's MAX_TURN_SECONDS (6h) remains the hard ceiling either way.
DEFAULT_TIMEOUT_S = int(os.environ.get("HARNESS_DEFAULT_TIMEOUT_S", "7200"))


def _file_url(container_id: str, file_id: str) -> str:
    return f"{PUBLIC_BASE_URL}/v1/containers/{container_id}/files/{file_id}/content"
COLLAB_TOKEN = os.environ.get("COLLAB_TOKEN", "")
BRAIN_INTERNAL_KEY = os.environ.get("BRAIN_INTERNAL_KEY", "")   # brain REST is internal-key gated
BRAIN_HTTP = COLLAB_URL.replace("wss://", "https://", 1).replace("ws://", "http://", 1)  # mint via REST
# Traces: full session transcripts persist to a dedicated blob KB, keyed for native per-org
# reverse-chronological pagination (the Traces app's source of truth). Key = <org>/<inv_ts>_<sid>/...
# where inv_ts = (TS_MAX - created_ms) zero-padded — ABS lists ASCENDING-lexical, so inverted == newest-first.
TRACE_KB = os.environ.get("HARNESS_TRACE_KB", "traces")
TRACE_TS_MAX = 99999999999999  # 14 digits; epoch-ms inversion pivot (past year 5000)

# docs_url/redoc/openapi OFF: the auto-docs expose the full route map. They were unreachable behind
# the public nginx (which only proxies /v1 /a /w /share), but api. going straight to this ACA app
# (HR-INF-016) would otherwise publish them — keep the surface to the intended routes only.
app = FastAPI(title="harness-gateway", docs_url=None, redoc_url=None, openapi_url=None)

# Serve the public per-harness API shape NATIVELY, so a deployment does not need a front proxy
# rewriting {harness_id}/v1/* -> /v1/* and setting X-Harness-Id. Handling it here lets the public
# hostname bind straight onto this app
# (managed cert + custom domain) and retire the VM hop. Strictly a harness-id first segment followed
# by /v1/ is rewritten — every real route (/v1, /a, /w, /share, /healthz, /readyz, /internal) has a
# reserved first segment that cannot match a chrn_<32hex> / builtin slug, so this is a NO-OP behind
# today's nginx (paths already arrive stripped to /v1/*) and only activates once api. targets ACA.
_HID_PREFIX_RE = re.compile(r"^/(chrn_[0-9a-f]{32}|codex|claude-code|pi|hermes)(/v1/.*)$")


@app.middleware("http")
async def _harness_path_prefix(request: Request, call_next):
    m = _HID_PREFIX_RE.match(request.scope.get("path", ""))
    if m:
        hid, rest = m.group(1), m.group(2)
        request.scope["path"] = rest
        request.scope["raw_path"] = rest.encode()
        # Set X-Harness-Id from the URL prefix (drop any client-sent one — the path is authoritative).
        hdrs = [(k, v) for (k, v) in request.scope["headers"] if k != b"x-harness-id"]
        hdrs.append((b"x-harness-id", hid.encode()))
        request.scope["headers"] = hdrs
    resp = await call_next(request)
    # V1C02-007: baseline browser security headers on EVERY response (the gateway serves HTML
    # artifact pages that must never be framable). frame-ancestors 'none' + X-Frame-Options DENY
    # kill clickjacking; the rest are cheap hardening. Does not touch SSE bodies.
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp
# NOTE: do NOT add GZipMiddleware globally — it buffers StreamingResponse to compress, which kills
# the /v1/responses SSE (no live progress reaches the browser until the turn ends). Trace payloads
# are kept small by the compact transcript (?compact=1), so global gzip isn't needed; if a specific
# non-streaming endpoint ever needs compression, gzip that Response explicitly.
_http: httpx.AsyncClient | None = None
_sems: dict[str, asyncio.Semaphore] = {}


def _conc_limit(scope: str) -> int:
    """Turn concurrency for this deployment. Cloud pools scale sandboxes on demand, so the cap is
    just back-pressure; one container cannot scale, so its cap is what the box can actually run."""
    env = _CONC_ENV_GLOBAL if scope == "global" else (_CONC_ENV_TENANT or _CONC_ENV_GLOBAL)
    if env.isdigit() and int(env) > 0:
        return int(env)
    if _pool_is_local():
        return max(2, os.cpu_count() or 2)
    return 512 if scope == "global" else 256


def _global_sem() -> asyncio.Semaphore:
    s = _sems.get("_global")
    if s is None:
        s = _sems["_global"] = asyncio.Semaphore(_conc_limit("global"))
    return s
_tenant_sems: dict[str, asyncio.Semaphore] = {}
_tok: dict = {"v": None, "exp": 0.0}
_cred = None  # lazy azure credential
_session_trace: dict[str, dict] = {}  # sid -> {prefix, org, since, chunk, count} for trace capture/persist
_inflight: set = set()  # detached turn tasks kept alive across client disconnects (no GC, no cancel)
_adopting: set = set()  # session ids with a detached orphan-adoption harvest in flight on THIS replica
# Stop requests. A turn task must observe cancellation at EVERY stage — including the startup
# window before the sandbox exists (no runner_turn_id to kill yet) — otherwise its next status
# upsert silently un-cancels the session and the CLI runs the whole task anyway. ONE signal, two
# tiers: this in-process flag (instant, same-replica) + the durable per-response cancel latch
# (cross-replica). _stop_session always sets both, so the turn loop no longer reads the vertex
# status to catch a cross-replica session cancel (HR-INF-010 — that Gremlin read is gone).
_cancel_req: dict[str, float] = {}  # sid -> when Stop was requested
# Artifact-serving hot caches (per replica). The workspace tar is downloaded ONCE per session
# and reused for every file open on that session (a share page opening 20 files used to pull
# the whole checkpoint 20 times); invalidated when a turn checkpoints new work. The shared
# flag is one cached vertex-prop check — no traversal — so public opens are as fast as the
# chat UI's own file loads.
# Workspace tarball cache lives on LOCAL DISK, not RAM (HR-INF-015): entries used to be the whole
# tar.gz as bytes — 6 × up-to-GB workspaces = multi-GiB of gateway RAM in the worst case. Now each
# entry is a path to a spooled file on the container's ephemeral disk (wiped on replica restart);
# tarfile reads/decompresses from disk so extraction RAM is O(member).
_WS_TAR_DIR = os.environ.get("HARNESS_WS_CACHE_DIR", "/var/tmp/hr-ws-cache")
try:
    os.makedirs(_WS_TAR_DIR, exist_ok=True)
except OSError:
    _WS_TAR_DIR = tempfile.gettempdir()
_WS_TAR_CACHE: dict[str, tuple[float, str]] = {}   # sid -> (ts, tar.gz path on disk)
_WS_TAR_TTL, _WS_TAR_MAX = 300.0, 6


_WS_TAR_LOCKS: dict[str, asyncio.Lock] = {}   # per-sid download single-flight


def _ws_tar_evict(sid: str) -> None:
    """Drop a session's cached tar AND its disk file (POSIX unlink is safe while open readers
    hold the fd — the data persists for them until close)."""
    hit = _WS_TAR_CACHE.pop(sid, None)
    if hit:
        try:
            os.unlink(hit[1])
        except OSError:
            pass
    lk = _WS_TAR_LOCKS.get(sid)
    if lk is not None and not lk.locked():     # keep the locks dict bounded (HR-INF-028 pattern)
        _WS_TAR_LOCKS.pop(sid, None)


def _reap_spool_dir() -> None:
    """Best-effort sweep of _WS_TAR_DIR: remove spool files (>1h old) that are not live cache
    entries — covers ZIP temps whose BackgroundTask cleanup was skipped (replica kill mid-response)
    and tar downloads orphaned by a crash. Never raises."""
    import glob as _glob
    live = {p for _, p in _WS_TAR_CACHE.values()}
    now = time.time()
    for f in _glob.glob(os.path.join(_WS_TAR_DIR, "*")):
        try:
            if f not in live and now - os.path.getmtime(f) > 3600:
                os.unlink(f)
        except OSError:
            pass
_SHARE_STATE_CACHE: dict[str, tuple[float, bool]] = {}  # sid -> (ts, shared)
_SHARE_TOKEN_CACHE: dict[str, tuple[float, str]] = {}   # token -> (ts, sid)
_SHARE_TTL = 10.0                                        # revocation latency ceiling
# Extracting one member from a tar.gz means decompressing the archive up to that member —
# ~seconds of CPU on a big checkpoint, paid PER CLICK before this cache. One pass now
# extracts every user-visible file (node_modules etc. are already hidden, so this is the
# deliverable set, not the whole workspace) and every later open is a dict hit.
_WS_FILES_CACHE: dict[str, tuple[float, dict[str, bytes]]] = {}
_WS_FILES_TTL, _WS_FILES_MAX = 300.0, 4
_WS_FILE_CAP, _WS_TOTAL_CAP = 32 * 1024 * 1024, 192 * 1024 * 1024
# Request idempotency: a repeated request with the same Idempotency-Key returns the FIRST
# request's response instead of starting a second run. The durable control store (Cosmos) is the
# SINGLE authority (create_item = atomic reservation) — there is no in-process/blob/Redis mirror.
_IDEM_TTL = 3600.0


def _idem_sha(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _req_hash(body: "CreateResponseBody") -> str:
    """Stable hash of the semantically-meaningful request fields (used to detect a
    reused idempotency key carrying a DIFFERENT request → 409). Excludes `stream`
    (a streaming vs non-streaming retry is the same request) and the idempotency
    key itself inside metadata."""
    meta = dict(body.metadata or {})
    meta.pop("idempotency_key", None)
    canon = {"model": body.model, "input": body.input, "instructions": body.instructions,
             "previous_response_id": body.previous_response_id, "backend": body.backend,
             "tools": body.tools, "max_output_tokens": body.max_output_tokens,
             "max_step": body.max_step, "metadata": meta}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()

REDIS_URL = os.environ.get("HARNESS_REDIS_URL", "")
# Per-session execution lease (HR-INF-012). Modes: off | observe | enforce.
#   observe (default) — acquire the lease + detect overlapping turns and LOG them, but never
#     block: zero behavior change, real signal on how often concurrent same-session turns happen.
#   enforce — reject an overlapping turn (a live lease held by another turn) with 409, and skip a
#     superseded turn's checkpoint (fence CAS). Flip to enforce only after observe shows it's safe.
# The lease is heartbeat-renewed during the turn and released at the end; a crashed turn's lease
# frees within HR_LEASE_TTL_S. Store-read failures fail OPEN (turn runs unfenced).
LEASE_MODE = os.environ.get("HR_SESSION_LEASE", "observe").strip().lower()
LEASE_TTL_S = int(os.environ.get("HR_LEASE_TTL_S", "90"))
LEASE_RENEW_EVERY = int(os.environ.get("HR_LEASE_RENEW_EVERY_POLLS", "20"))
# enforce mode only rejects a duplicate when the incumbent lease was heartbeated within this
# window — so a crashed/completed-but-unreleased lease never falsely rejects a real follow-up.
# Must exceed the renew interval (RENEW_EVERY × RESP_POLL_S ≈ 24s) with margin.
LEASE_FRESH_S = float(os.environ.get("HR_LEASE_FRESH_S", "75"))

# ── realtime broadcast bus ────────────────────────────────────────────────────────
# Source of truth for live UI updates: every /v1/responses turn publishes each native event to a
# per-(org,harness) topic. Any client subscribed to GET /v1/harnesses/{hid}/events receives ALL
# events for ALL of that harness's sessions (its own, per-user filtered), tagged with session_id.
# This decouples live rendering from the POST stream that started the turn — so switching
# conversations, opening a session started in another tab, or reconnecting never misses an update
# (no per-request replay patches). In-process fan-out covers the common single-replica case; under
# multi-replica scale-out the client also reconciles via GET /v1/sessions/{sid}/turns on (re)open.
_bus: dict[str, set[asyncio.Queue]] = {}   # topic -> subscriber queues
_BUS_Q_MAX = 4000
# HR-INF-018: the bus drops live events on backpressure by design (the client reconciles via
# /turns). Those drops were SILENT — invisible to operators. Count them (surfaced on /readyz +
# rate-logged) so a real drop storm is observable instead of a mystery gap. Not correctness state.
_bus_drops = _OpsDrops("bus", 30, ("subscriber_q", "pump_q", "sse_q"))
# Per-session replay buffer of the CURRENT turn's native events, so a client that connects/refreshes
# MID-TURN gets the in-flight turn immediately (completed turns load via /v1/sessions/{sid}/turns; this
# covers the running one). Reset on each turn start; capped. In-memory per replica — at the common
# single-replica load this fully covers "open/refresh a running session and see it", and the live tail
# continues from there. (Cross-replica scale-out degrades to live-tail-only until the next event.)
_turn_buffers: dict[str, dict] = {}   # sid -> {"org","harness","member","rid","events":[...]}
_BUF_MAX = 6000


def _bus_topic(org: str, harness_id: str) -> str:
    return f"{org}\x1f{harness_id}"


# Cross-replica delivery (the ROOT fix for lost SSE events under scale-out): every publish goes
# through Redis pub/sub, and EVERY replica's subscriber loop runs _bus_deliver — so all replicas
# hold identical mid-turn replay buffers and fan out to their own SSE subscribers, no matter which
# replica runs the turn. Without Redis (dev / outage) publishes deliver locally, which is exactly
# correct at one replica and best-effort during a Redis outage.
_BUS_CHANNEL = "hrbus"
_redis: aioredis.Redis | None = None
_redis_out: asyncio.Queue | None = None


def _bus_deliver(org: str, harness_id: str, member: str, sid: str, rid: str, ev) -> None:
    """Update this replica's replay buffer and fan out to ITS local SSE subscribers."""
    if isinstance(ev, dict) and ev.get("type") == "hr.ctrl.ws_invalidate":
        # control message: a checkpoint changed this session's workspace — EVERY replica must
        # drop its cached tar/files or it serves stale artifact bytes for the cache TTL.
        _ws_tar_evict(sid)
        _WS_FILES_CACHE.pop(sid, None)
        return
    # buffer for mid-turn join: reset on turn start, accumulate this turn's events, and DROP it on a
    # terminal event. A completed turn loads via /v1/sessions/{sid}/turns; if we also replayed it from
    # the buffer, a connecting client would render the turn twice. So the buffer only ever holds the
    # one IN-FLIGHT turn.
    t = ev.get("type") if isinstance(ev, dict) else None
    if t == "harness.turn.started":
        _turn_buffers[sid] = {"org": org, "harness": harness_id, "member": member, "rid": rid, "events": [ev]}
    elif t in ("response.completed", "response.failed", "response.incomplete"):
        _turn_buffers.pop(sid, None)
    else:
        buf = _turn_buffers.get(sid)
        if buf is not None and len(buf["events"]) < _BUF_MAX:
            buf["events"].append(ev)
            buf["rid"] = rid
    subs = _bus.get(_bus_topic(org, harness_id))
    if not subs:
        return
    msg = {"session_id": sid, "response_id": rid, "member": member, "event": ev}
    for q in list(subs):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            _bus_drops.bump("subscriber_q")   # slow local subscriber; it recovers via /turns reconcile


def _bus_publish(org: str, harness_id: str, member: str, sid: str, rid: str, ev) -> None:
    """Publish an event to ALL replicas (via Redis) or locally when Redis is off. Non-blocking;
    a slow/full consumer drops the live event and recovers via the turns reconciliation."""
    if not harness_id:
        return
    if _redis_out is not None:
        try:
            _redis_out.put_nowait({"org": org, "harness": harness_id, "member": member,
                                   "sid": sid, "rid": rid, "ev": ev})
            return                      # the pump (or its failure fallback) delivers
        except asyncio.QueueFull:
            _bus_drops.bump("pump_q")         # overloaded pump: deliver locally, don't block the turn
    _bus_deliver(org, harness_id, member, sid, rid, ev)


# pub starts OPTIMISTIC: it only flips on a real publish outcome. Pessimistic-until-first-publish
# made every viewer-only replica (which never publishes) run the expensive durable-trace tail
# forever; a genuinely broken pub flips this False on its first failure — within the same turn —
# and the tail starts from cursor "" so nothing is lost.
_redis_ok = {"pub": True, "sub": False}


async def _redis_pump() -> None:
    """Drain the publish queue into Redis PUBLISH; on failure deliver locally so a Redis outage
    degrades to single-replica behavior instead of silence."""
    global _redis
    while True:
        m = await _redis_out.get()
        payload = None
        try:
            payload = json.dumps(m, default=str)
            if _redis is None:
                _redis = aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3,
                                     socket_timeout=10, health_check_interval=30)
            await _redis.publish(_BUS_CHANNEL, payload)
            _redis_ok["pub"] = True
        except Exception:  # noqa: BLE001
            _redis = None               # reconnect next message
            _redis_ok["pub"] = False
            _bus_deliver(m["org"], m["harness"], m["member"], m["sid"], m["rid"], m["ev"])


async def _redis_listen() -> None:
    """Every replica tails the shared channel and delivers into its own buffers + subscribers."""
    while True:
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3,
                                  health_check_interval=30)
            ps = r.pubsub(ignore_subscribe_messages=True)
            await ps.subscribe(_BUS_CHANNEL)
            _redis_ok["sub"] = True
            async for m in ps.listen():
                if m.get("type") != "message":
                    continue
                try:
                    d = json.loads(m["data"])
                    _bus_deliver(d["org"], d["harness"], d["member"], d["sid"], d["rid"], d["ev"])
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            _redis_ok["sub"] = False
            await asyncio.sleep(1.5)    # reconnect with backoff


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        # Built for elastic concurrency: a burst of turns must WAIT for cold sandboxes to come up,
        # never be cut off. So generous timeouts (read = a long agent turn; pool = wait for a free
        # connection under load) and a large connection pool so concurrent SSE streams don't starve.
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30, read=3600, write=120, pool=300),
            limits=httpx.Limits(max_connections=2000, max_keepalive_connections=400),
        )
    return _http


_relay_http: httpx.AsyncClient | None = None


def _relay_client() -> httpx.AsyncClient:
    """A SEPARATE pool for the checkpoint/hydrate tar relays. Each relay holds TWO connections at
    once (the PUT/POST body-generator opens a nested GET), so sharing the main pool with long-lived
    SSE streams could starve into PoolTimeout under load and LOSE a checkpoint. Isolating them means
    the relay's 2-at-a-time pattern can never be starved by SSE traffic and vice-versa."""
    global _relay_http
    if _relay_http is None:
        _relay_http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30, read=3600, write=600, pool=60),
            limits=httpx.Limits(max_connections=400, max_keepalive_connections=100),
        )
    return _relay_http


def _tenant_sem(t: str) -> asyncio.Semaphore:
    return _tenant_sems.setdefault(t or "_", asyncio.Semaphore(_conc_limit("tenant")))


def _pool_is_local() -> bool:
    """True when the runner is reachable directly rather than through a cloud session pool.

    Self-hosted runs the runner beside the gateway (same container / compose network), so
    there is no cloud identity to present and no pool to authenticate to. Explicit override
    is HR_POOL_AUTH=none|cloud; otherwise a loopback or compose-service host is taken as
    local, because a cloud pool is never reachable on one."""
    mode = os.environ.get("HR_POOL_AUTH", "").strip().lower()
    if mode in ("none", "off", "local"):
        return True
    if mode in ("cloud", "entra", "azure"):
        return False
    from urllib.parse import urlparse
    host = (urlparse(POOL_ENDPOINT).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1", "runner", "harnessrouter-runner")


def _pool_token() -> str:
    """Cloud identity token for the hosted session pool, cached.

    Returns "" when the runner is local — callers then send no Authorization header, which
    is what lets the whole turn path run with no cloud identity at all."""
    if _pool_is_local():
        return ""
    global _cred
    if _tok["v"] and time.time() < _tok["exp"] - 120:
        return _tok["v"]
    if _cred is None:
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
        _cred = (ManagedIdentityCredential(client_id=AZURE_CLIENT_ID) if AZURE_CLIENT_ID
                 else DefaultAzureCredential())
    t = _cred.get_token("https://dynamicsessions.io/.default")
    _tok["v"], _tok["exp"] = t.token, float(t.expires_on)
    return _tok["v"]


# (the old optional require_caller / HARNESS_GATEWAY_KEY shared-key gate is gone: with the key
# unset in prod it no-oped, leaving /v1/traces and the connection/policy writers OPEN. Every
# route now authenticates via _principal (API key / internal trust + verified JWT) or
# _internal_only — auth that fails closed.)
def _internal_only(x_harness_internal: str = Header(default="")) -> dict:
    if not INTERNAL_KEY or x_harness_internal != INTERNAL_KEY:
        raise HTTPException(401, "internal key required")
    return {"internal": True}


# ── Vault: connection registry + org→global fallback ─────────────────────────────
# Backed by SecretStore (backing.py): the vault service in production, env/file locally so an
# open clone can supply provider keys without any vault.
async def _vault_get(tenant: str, name: str) -> str | None:
    return await BACKING.secrets.get(tenant, name)


async def _vault_put(tenant: str, name: str, value: str) -> None:
    await BACKING.secrets.put(tenant, name, value)


_VAULT_TENANT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
def _vault_tenant_ok(org: str | None) -> bool:
    # secret-store tenants must be [a-z0-9-], no '--', start/end alnum -> dotted org ids are invalid
    return bool(org) and org != GLOBAL_TENANT and "--" not in org and bool(_VAULT_TENANT_RE.match(org))


def _tenants_for(org: str | None) -> list[str]:
    """Resolution order: the org's own keys first (bill to the org), then the shared pool.
    Skip the org tenant if it isn't a valid vault tenant (e.g. dotted ids) -> straight to global."""
    return ([org] if _vault_tenant_ok(org) else []) + [GLOBAL_TENANT]


async def _get_connection(org: str | None, name: str) -> tuple[dict | None, str | None]:
    for tenant in _tenants_for(org):
        v = await _vault_get(tenant, f"harness-conn-{name}")
        if v:
            try:
                return json.loads(v), tenant
            except Exception:  # noqa: BLE001
                return None, None
    return None, None


async def _resolve_chain(org: str | None, backend: str, explicit: str | None) -> list[str]:
    """Ordered connection names to try (fallback chain). Explicit > org policy > global policy."""
    if explicit:
        return [explicit]
    for tenant in _tenants_for(org):
        v = await _vault_get(tenant, f"harness-policy-{backend}")
        if v:
            try:
                names = json.loads(v)
                if isinstance(names, list) and names:
                    return [str(n) for n in names]
            except Exception:  # noqa: BLE001
                pass
    return []


_AUTH_FIELDS = ("api_key", "base_url", "aws_region", "aws_access_key_id", "aws_secret_access_key",
                "aws_session_token", "aws_bearer_token", "gcp_project", "gcp_region",
                "gcp_sa_json", "wire_api")


# ── LLM egress broker ────────────────────────────────────────────────────────────────────────
# The sandbox runs the CUSTOMER'S agent with real bash and network access, so anything handed to
# it must be assumed public. Shipping the shared provider key there meant one `printenv` bought
# unlimited spend on our account, off-platform and invisible — which is exactly what happened on
# 2026-07-25 (ROUTER_API_KEY exfiltrated, ~$6/hr billed to us for six days).
#
# So the sandbox never receives a provider credential. It gets a per-turn token and OUR base_url;
# the CLI talks to the broker below, which swaps in the real key server-side. A stolen token is
# worth one session, expires with it, and is useless anywhere else.
#
# Not a second auth mechanism: the token is the SAME HMAC construction as the session token
# (auth.py), signed with HARNESS_INTERNAL_KEY, verifiable on any replica with no shared state.
_BROKER_TTL_S = int(os.environ.get("HR_LLM_BROKER_TTL_S", str(6 * 3600)))   # > max turn wall-clock
# Providers whose wire protocol is plain HTTP + a bearer/api-key header, so a base_url swap is
# transparent to the CLI. bedrock/vertex sign with the cloud SDK and are handled separately
# (see _auth_from_conn) — they keep their own credential until their signing path is brokered.
_BROKERABLE_PROVIDERS = {"anthropic", "tokenrouter", "openai", "azure", "azure-foundry",
                         "openrouter", "openai-api"}


def _mint_turn_cred(sid: str, conn_name: str) -> str:
    """Per-turn credential: sid.conn.exp.hmac — resolvable back to exactly one connection."""
    exp = str(int(time.time()) + _BROKER_TTL_S)
    body = f"{sid}|{conn_name}|{exp}"
    sig = hmac.new((INTERNAL_KEY or "dev-insecure").encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"hrt_{base64.urlsafe_b64encode(body.encode()).decode().rstrip('=')}.{sig}"


def _verify_turn_cred(tok: str) -> tuple[str, str] | None:
    """(session_id, connection_name) for a valid unexpired token, else None."""
    if not tok or not tok.startswith("hrt_"):
        return None
    try:
        b64, sig = tok[4:].rsplit(".", 1)
        body = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()
        sid, conn_name, exp = body.split("|")
    except Exception:  # noqa: BLE001 — malformed token is simply invalid
        return None
    good = hmac.new((INTERNAL_KEY or "dev-insecure").encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good) or int(exp) < int(time.time()):
        return None
    return sid, conn_name


# Every field in _AUTH_FIELDS that carries a credential. Removal is driven off THIS list, not off
# the branch that decides brokering, so a secret can never survive because a condition was wrong.
_SECRET_AUTH_FIELDS = ("api_key", "aws_access_key_id", "aws_secret_access_key",
                       "aws_session_token", "aws_bearer_token", "gcp_sa_json")

# "owner" = the sandbox is the operator's own (single-tenant self-host), so provider keys may
# be handed to it directly. Anything else (including unset) keeps the fail-closed broker path.
SANDBOX_TRUST = os.environ.get("HR_SANDBOX_TRUST", "").strip().lower()


def _auth_from_conn(conn: dict, sid: str = "") -> dict | None:
    """What the SANDBOX is allowed to see, or None if it cannot be given anything safely.

    The sandbox runs the customer's agent with real bash and network egress, so a provider
    credential placed there is published. The previous shape stripped secrets only INSIDE the
    "can we broker this?" branch, which meant every way that branch could be false — a provider
    name with different casing, an empty sid, an unset HARNESS_PUBLIC_BASE_URL — silently shipped
    the real key instead. That is a fail-OPEN on the worst secret in the system.

    So the order is inverted: remove every credential first, unconditionally, then hand back the
    brokered token. If we cannot broker, there is nothing safe to return and the caller skips this
    connection (same as any other unusable one) rather than falling back to the raw key."""
    out = {k: conn[k] for k in _AUTH_FIELDS if conn.get(k) is not None}
    for secret in _SECRET_AUTH_FIELDS:
        out.pop(secret, None)

    # Self-hosted bring-your-own-key. Brokering exists because a MULTI-TENANT sandbox runs
    # someone else's agent against OUR key, so the key must never enter it. Self-hosted inverts
    # every term: the operator owns the box, the agent and the key, so there is no party to
    # protect the key from and a broker hop would only add a failure mode.
    #
    # This is deliberately an EXPLICIT opt-in (HR_SANDBOX_TRUST=owner) and deliberately NOT a
    # fallback for "brokering did not work". The bug this function was rewritten to kill was
    # exactly that shape: any condition that made brokering fail silently shipped the raw key.
    # Keeping pass-through as its own declared mode means a hosted deployment that leaves the
    # variable unset still fails CLOSED on every broker failure, as before.
    if SANDBOX_TRUST == "owner":
        for field in _SECRET_AUTH_FIELDS:
            if conn.get(field) is not None:
                out[field] = conn[field]
        return out

    # Normalised: a connection saved as "TokenRouter" must not skip brokering on a casing mismatch.
    provider = str(conn.get("provider") or "").strip().lower()
    if provider not in _BROKERABLE_PROVIDERS or not sid or not PUBLIC_BASE_URL:
        log_reason = ("provider not brokerable" if provider not in _BROKERABLE_PROVIDERS
                      else "no session id" if not sid else "HARNESS_PUBLIC_BASE_URL unset")
        print(f"[broker] refusing to build sandbox auth for provider={provider!r}: {log_reason}",
              flush=True)
        return None
    out["api_key"] = _mint_turn_cred(sid, str(conn.get("name") or ""))
    out["base_url"] = f"{PUBLIC_BASE_URL}/v1/llm"
    return out


def _conn_public(conn: dict) -> dict:
    """Connection metadata with secret fields stripped (for admin listing)."""
    secret = {"api_key", "aws_secret_access_key", "aws_session_token", "aws_bearer_token", "gcp_sa_json"}
    return {k: v for k, v in conn.items() if k not in secret}


# ── token-provider integrations (global model→provider routing) ──────────────────────
# A named integration = provider type + credentials + its supported-model list, where each
# model has a CANONICAL name (what users pick in dropdowns) and the provider_id the provider's
# API actually needs. `harness-model-map` (canonical -> integration name) decides which
# integration serves a model, globally for all harnesses; the per-backend policy chains stay
# as the fallback when a model has no mapping (or the mapped integration can't serve the
# running backend). Both docs live in the vault's global tenant. Configured today by the
# platform org only; customer BYOK rides the same schema later (org-tenant copies).
_INTEGRATIONS_KEY = "harness-integrations"
_MODEL_MAP_KEY = "harness-model-map"
# The document as it was before the most recent write. See admin_integrations_put.
_INTEGRATIONS_PREV_KEY = "harness-integrations.prev"
_MODEL_MAP_PREV_KEY = "harness-model-map.prev"
# Images get their OWN map. Sharing the chat map would put image models in the chat pickers,
# where picking one is a broken choice; and the two route independently — the integration that
# serves your chat models is often not the one that serves images.
_IMAGE_MODEL_MAP_KEY = "harness-image-model-map"
_IMAGE_MODEL_MAP_PREV_KEY = "harness-image-model-map.prev"
_INTEGRATION_SECRET_FIELDS = ("api_key", "aws_bearer_token", "aws_secret_access_key", "aws_session_token")
# integration provider type × runner backend -> the runner-side provider that carries it.
# Absent pair = that backend can't use the integration (mapping falls through to the chain).
_INTEGRATION_WIRING: dict[tuple[str, str], str] = {
    ("azure-foundry", "codex"): "azure",       ("azure-foundry", "hermes"): "azure-foundry",
    ("bedrock", "claude"): "bedrock",          ("bedrock", "hermes"): "bedrock",
    ("openrouter", "codex"): "tokenrouter",    ("openrouter", "hermes"): "openrouter",
    ("tokenrouter", "claude"): "tokenrouter",  ("tokenrouter", "codex"): "tokenrouter",
    ("tokenrouter", "hermes"): "openai-api",
    ("openai", "codex"): "openai",             ("openai", "hermes"): "openai-api",
    ("anthropic", "claude"): "anthropic",      ("anthropic", "hermes"): "anthropic",
}


async def _integrations_doc() -> list[dict]:
    v = await _vault_get(GLOBAL_TENANT, _INTEGRATIONS_KEY)
    try:
        doc = json.loads(v) if v else []
        return doc if isinstance(doc, list) else []
    except Exception:  # noqa: BLE001
        return []


async def _model_map_doc() -> dict:
    v = await _vault_get(GLOBAL_TENANT, _MODEL_MAP_KEY)
    try:
        doc = json.loads(v) if v else {}
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


async def _image_model_map_doc() -> dict:
    v = await _vault_get(GLOBAL_TENANT, _IMAGE_MODEL_MAP_KEY)
    try:
        doc = json.loads(v) if v else {}
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _integration_image_models(integ: dict) -> dict[str, str]:
    """Canonical → provider-native id for one integration's IMAGE models.

    Same contract as _integration_models: the vendor table in source is the authority on what a
    vendor can reach, and a stored entry may only CHANGE an id, never add a model. Deriving on
    read is what keeps a shipped catalog change visible on instances that saved a form months ago.
    """
    models = dict(_IMAGE_VENDOR_MODELS.get(str(integ.get("provider") or "").lower(), {}))
    for m in (integ.get("image_models") or []):
        canonical = str(m.get("canonical") or "").strip()
        pid = str(m.get("provider_id") or "").strip()
        if canonical in models and pid:
            models[canonical] = pid
    return models


async def _effective_image_model_map() -> dict[str, str]:
    """Canonical image model → integration name. Explicit routes win; anything else is claimed by
    the first integration that can serve it. A stored route to a model its integration cannot
    serve is dropped, not honoured — same rule as chat, for the same reason."""
    integrations = await _integrations_doc()
    servable = {str(i.get("name") or ""): _integration_image_models(i) for i in integrations}
    mm = {k: v for k, v in (await _image_model_map_doc()).items() if k in servable.get(v, {})}
    for name, models in servable.items():
        for canonical in models:
            mm.setdefault(canonical, name)
    return mm


def _integration_models(integ: dict) -> dict[str, str]:
    """Canonical → provider-native id for one integration.

    The vendor table in source is the base; anything stored on the integration overlays it. Only
    genuine overrides are stored (see admin_integrations_put), so this is "what the source says
    today, unless this instance was told otherwise".

    Derived on read, never frozen on write. A stored copy of this list is a snapshot of the
    catalog on the day someone last pressed Save: ship a release that adds nine models and every
    existing instance keeps serving the old set, with no signal that anything is stale. That is
    exactly what happened — models restored to the source table stayed dark in the picker.

    An override may CHANGE the id used for a model this vendor serves; it may not ADD one the
    vendor's table doesn't list. That keeps the table the sole authority on what a vendor can
    reach — and it makes documents written by older versions harmless, because those stored the
    whole derived list, which would otherwise re-add exactly the models later found unreachable
    (a stale snapshot is indistinguishable from a deliberate override, so it cannot be trusted
    to introduce models). Nothing is lost: only canonicals in the catalog can be requested.
    """
    models = dict(_vendor_models(str(integ.get("provider") or "").lower()))
    for m in (integ.get("models") or []):
        canonical = str(m.get("canonical") or "").strip()
        pid = str(m.get("provider_id") or "").strip()
        if canonical in models and pid:
            models[canonical] = pid
    return models


async def _effective_model_map() -> dict[str, str]:
    """Canonical → integration name: which connection serves each model, right now.

    Explicit routes win; every other model an integration can serve is claimed by the first
    integration that can serve it. Both halves are computed here rather than baked into the
    stored document, so adding a key or upgrading the image changes what runs without anyone
    re-saving a form.

    "Can serve" is decided by the vendor tables and nothing else. When a model goes to the wrong
    integration, the fix belongs in that vendor's table — stop listing it there — rather than in
    a preference order here, which would then apply to every other model too.

    A stored route to a model its integration cannot serve is dropped, not honoured — that is a
    dead route left behind by an edit, and following it would fail at the point of no return.
    """
    integrations = await _integrations_doc()
    servable = {str(i.get("name") or ""): _integration_models(i) for i in integrations}
    mm = {k: v for k, v in (await _model_map_doc()).items() if k in servable.get(v, {})}
    for name, models in servable.items():
        for canonical in models:
            mm.setdefault(canonical, name)
    return mm


async def _image_auth(sid: str, backend: str) -> dict | None:
    """Broker credentials for image generation, or None when nothing can serve an image model.

    Same shape as the chat auth: a per-turn credential and a base_url, never a provider key
    (self-hosted owner mode is the declared exception, where the operator's own key is the point).

    Resolved from the IMAGE model map, independently of the turn's chat connection, because they
    are usually different providers: a Claude Code harness runs on Anthropic, which has no image
    API, so reusing the turn's credential would relay /images/generations there and 404.
    """
    if not sid or (SANDBOX_TRUST != "owner" and not HR_BROKER_IMAGES):
        return None
    mm = await _effective_image_model_map()
    if not mm:
        return None
    by_name = {str(i.get("name") or ""): i for i in await _integrations_doc()}
    # Deterministic: sorted, so which model serves a turn never depends on dict insertion order.
    # An operator who wants a specific one routes it in Integrations.
    for canonical in sorted(mm):
        integ = by_name.get(mm[canonical])
        if not integ:
            continue
        vendor = (integ.get("provider") or "").strip().lower()
        provider = _INTEGRATION_WIRING.get((vendor, backend)) or vendor
        conn = {"name": f"integration:{integ.get('name') or ''}", "backend": backend,
                "provider": provider,
                **{k: v for k, v in (integ.get("config") or {}).items() if v not in (None, "")}}
        auth = _auth_from_conn(conn, sid)
        if auth and auth.get("base_url") and auth.get("api_key"):
            pid = _integration_image_models(integ).get(canonical) or canonical
            return {"base_url": auth["base_url"], "api_key": auth["api_key"], "model": pid,
                    "models": sorted(m for m in mm if mm[m] == mm[canonical])}
    return None


async def _mapped_integration_conn(backend: str, canonical: str) -> dict | None:
    """The synthetic connection for a model→integration mapping, or None when unmapped /
    unusable by this backend. Shaped exactly like a vault connection so the turn loop treats
    it uniformly; `model` is pre-resolved to the integration's provider_id for the canonical."""
    canon = (canonical or "").strip()
    if not canon:
        return None
    mm = await _effective_model_map()
    iname = mm.get(canon) or mm.get(canon.lower())
    if not iname:
        return None
    integ = next((i for i in await _integrations_doc() if (i.get("name") or "") == iname), None)
    if not integ:
        return None
    provider = _INTEGRATION_WIRING.get(((integ.get("provider") or "").lower(), backend))
    if not provider:
        return None
    models = _integration_models(integ)
    pid = models.get(canon) or models.get(canon.lower()) or ""
    conn = {"name": f"integration:{iname}", "backend": backend, "provider": provider,
            **{k: v for k, v in (integ.get("config") or {}).items() if v not in (None, "")}}
    if pid:
        conn["model"] = pid
        conn["_model_resolved"] = True   # skip _map_model — the id is already provider-native
    return conn


# ── pool proxy ───────────────────────────────────────────────────────────────────
def _pool_headers() -> dict:
    """Auth headers for the runner. Empty when local — no cloud identity exists or is needed."""
    tok = _pool_token()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


async def _sandbox(path: str, sid: str, method: str = "POST", body: dict | None = None,
                   params: dict | None = None, content: bytes | None = None) -> httpx.Response:
    q = {"identifier": sid, **(params or {})}
    kw: dict = {"content": content} if content is not None else ({"json": body} if body is not None else {})
    return await _client().request(method, f"{POOL_ENDPOINT}{path}", params=q,
                                   headers=_pool_headers(), **kw)


async def _sandbox_json(path: str, sid: str, method: str = "POST", body: dict | None = None,
                        params: dict | None = None, *, attempts: int = 28, base: float = 0.75) -> dict:
    """Call the sandbox and parse JSON, retrying transient failures with exponential backoff.

    Under a burst of concurrent sessions the Dynamic Sessions pool allocates cold sandboxes on demand
    and can briefly return an empty / non-JSON body or a 429/5xx while one spins up (and a follow-up
    must additionally rehydrate a possibly-large workspace). WAIT for that scale-up rather than fail —
    treating a cold start as a hard error was the dominant concurrency failure.

    The ladder starts FAST (sub-second) so a warm-standby handout or a quick cold start is noticed
    the moment it's ready — a 3s first step used to inflate every observed start by seconds — then
    backs off toward 15s steps; 28 tries still cover a multi-minute cold start + hydrate."""
    last = ""
    for i in range(attempts):
        try:
            r = await _sandbox(path, sid, method, body=body, params=params)
            raw = (r.content or b"").strip()
            if r.status_code < 400 and raw:
                return r.json()
            last = f"HTTP {r.status_code}, {len(raw)}B body"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:120]}"
        if i < attempts - 1:
            await asyncio.sleep(min(base * (1.5 ** i), 15.0))
    raise RuntimeError(f"sandbox {path} unavailable after {attempts} tries ({last})")


# ── durable session workspace (git checkpoint tarball in vg-gateway blob storage) ──
def _ws_blob(sid: str) -> str:
    return f"sessions/{sid}/workspace.tgz"


def _blob_url(file_id: str, kb: str = BLOB_KB) -> str:
    """THE one place the VG blob object URL is built (it was hand-assembled at 9 sites).
    Only meaningful for the VG backing — the streaming checkpoint/hydrate relays below pipe bytes
    through raw URLs rather than buffering a whole workspace tarball in memory."""
    return BACKING.blob.url_for(kb, file_id)


def _blob_headers(content_type: str | None = None) -> dict:
    return BACKING.blob.headers(content_type)


def _blob_streaming() -> bool:
    """Whether the blob backing supports the raw-URL streaming relays (VG only). The local
    filesystem backing has no HTTP surface, so the relays fall back to buffered put/get —
    correct, and a laptop workspace is not a GB tarball."""
    return BACKING.mode == "vg" and bool(VG_GATEWAY_URL)


async def _blob_open_stream(file_id: str, kb: str = BLOB_KB,
                            client: httpx.AsyncClient | None = None) -> httpx.Response:
    """Open a streamed GET of a blob (caller owns aclose). THE one streamed-read opener —
    used by the hydrate relay and the workspace-tar disk cache."""
    c = client or _client()
    req = c.build_request("GET", _blob_url(file_id, kb), headers=_blob_headers())
    return await c.send(req, stream=True)


async def _blob_get(file_id: str, kb: str = BLOB_KB) -> bytes | None:
    return await BACKING.blob.get(kb, file_id)


async def _blob_put(file_id: str, data: bytes, kb: str = BLOB_KB) -> bool:
    return await BACKING.blob.put(kb, file_id, data)


async def _checkpoint_relay(sid: str) -> tuple[bool, int, str, str]:
    """Stream the workspace tar from the runner /checkpoint straight into the VG blob PUT without
    ever holding the whole tarball in gateway memory (HR-INF-015). Folds sha256 + byte count over
    the stream as it flows. Returns (ok, nbytes, ws_sha, git_head). A 1 GiB workspace no longer
    materializes a full copy in the gateway (it did on every turn end, for every session).

    Safety (verified): the runner sends a fixed Content-Length, so a short read makes aiter_bytes
    raise → the PUT body generator raises → put() raises (never a 2xx) → the caller's except leaves
    ws_sha unadvanced. VG streams the body into STAGED blocks and commits them only after the full
    stream (Azure Put Block List last) — an aborted stream never commits, so a truncated PUT never
    overwrites the existing good blob. Uses the DEDICATED relay pool so nested GET+PUT can't starve SSE."""
    if not _blob_streaming():
        # Local backing (no HTTP blob surface): buffer the tar, then hand it to the store. A
        # laptop workspace is not the GB-scale tarball the streaming path exists for.
        try:
            rc0 = _relay_client()
            r0 = await rc0.get(f"{POOL_ENDPOINT}/checkpoint", params={"identifier": sid},
                               headers=_pool_headers())
            if r0.status_code >= 400 or not r0.content:
                return False, 0, "", ""
            ok0 = await BACKING.blob.put(BLOB_KB, _ws_blob(sid), r0.content)
            return (ok0, len(r0.content), hashlib.sha256(r0.content).hexdigest() if ok0 else "",
                    r0.headers.get("X-Git-Head", ""))
        except Exception:  # noqa: BLE001 — same contract as the streaming path: failure = no advance
            return False, 0, "", ""
    h = hashlib.sha256()
    nbytes = 0
    git_head = ""
    rc = _relay_client()

    async def _pipe():
        nonlocal nbytes, git_head
        req = rc.build_request("GET", f"{POOL_ENDPOINT}/checkpoint", params={"identifier": sid},
                               headers=_pool_headers())
        resp = await rc.send(req, stream=True)
        try:
            resp.raise_for_status()
            git_head = resp.headers.get("X-Git-Head", "")
            async for chunk in resp.aiter_bytes():
                nbytes += len(chunk)
                h.update(chunk)
                yield chunk
        finally:
            await resp.aclose()

    put = await rc.put(_blob_url(_ws_blob(sid)),
                       headers=_blob_headers("application/octet-stream"), content=_pipe())
    ok = put.status_code < 400 and nbytes > 0
    return ok, nbytes, (h.hexdigest() if nbytes else ""), git_head


async def _hydrate_relay(sid: str, params: dict | None) -> httpx.Response:
    """Stream the workspace tar from VG blob storage straight into the runner /hydrate POST body
    (HR-INF-015 reverse path) — no full-tarball buffer in the gateway. Uses the dedicated relay pool.

    Distinguishes a genuine 404 (no checkpoint yet → send an empty body → runner starts fresh) from
    a TRANSIENT error (5xx / network): a transient failure RAISES so the caller aborts the turn
    rather than silently hydrating an empty workspace and then checkpointing over the good blob."""
    if not _blob_streaming():
        # Local backing: read the checkpoint (absent → empty body → runner starts fresh, the same
        # meaning a 404 carries on the streaming path) and post it buffered.
        tar = await BACKING.blob.get(BLOB_KB, _ws_blob(sid))
        return await _relay_client().request(
            "POST", f"{POOL_ENDPOINT}/hydrate", params={"identifier": sid, **(params or {})},
            headers=_pool_headers(), content=tar or b"")
    rc = _relay_client()

    async def _pipe():
        resp = await _blob_open_stream(_ws_blob(sid), client=rc)
        try:
            if resp.status_code == 404:
                return                       # genuine no-checkpoint → empty body → fresh workspace
            if resp.status_code >= 400:
                # Transient upstream error — do NOT masquerade as "empty" (that would wipe + then
                # overwrite the good checkpoint). Raise so _hydrate aborts this turn's hydrate.
                raise RuntimeError(f"hydrate blob GET failed: HTTP {resp.status_code}")
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()

    return await rc.request("POST", f"{POOL_ENDPOINT}/hydrate",
                            params={"identifier": sid, **(params or {})},
                            headers=_pool_headers(),
                            content=_pipe())


async def _blob_delete(file_id: str, kb: str = BLOB_KB) -> bool:
    return await BACKING.blob.delete(kb, file_id)


def _inv_ts(created: float) -> str:
    """Inverted, zero-padded epoch-ms so an ASCENDING-lexical ABS LIST yields newest-first."""
    return str(TRACE_TS_MAX - int(created * 1000)).zfill(14)


def _manifest_key(base: str) -> str:
    """Trace base '{org}/{inv}_{sid}' -> the FLAT manifest key '{org}/idx/{inv}_{sid}.json'. The
    `idx/` namespace holds exactly one object per session, so a prefix-LIST of '{org}/idx/' paginates
    sessions cleanly (event chunks live under '{org}/{inv}_{sid}/events/' and never interleave).
    This flat index is the READ SOURCE for unfiltered Recents and the CANONICAL copy every mutation
    writes; the narrow per-harness/per-member indexes below are mirrors of it."""
    org, rest = base.split("/", 1)
    return f"{org}/idx/{rest}.json"


def _idx_seg(s: str) -> str:
    """Blob-path-safe segment for a harness/member id used as an index prefix (ids are already
    tame — 'codex', 'chrn_...', member emails — but sanitize defensively so a stray character can't
    fork one logical slice across two prefixes)."""
    return re.sub(r"[^A-Za-z0-9._@-]", "_", s or "")[:200]


def _manifest_index_keys(base: str, harness_id: str, member_id: str, workspace: str = "") -> list[str]:
    """Every key a session manifest is mirrored to: the flat org index (unfiltered lists + fallback)
    PLUS a narrow per-harness, per-member, and per-workspace index. A filtered LIST then hits exactly
    that slice, so `limit=k` returns k FOR THAT HARNESS (never k mixed across the org, post-filtered
    down to a few), and an empty harness costs one empty LIST instead of an org-wide scan. The
    `inv_sid.json` leaf is identical across all mirrors, so `_card` reads a mirror directly."""
    org, rest = base.split("/", 1)
    keys = [f"{org}/idx/{rest}.json"]
    if harness_id:
        keys.append(f"{org}/idxh/{_idx_seg(harness_id)}/{rest}.json")
    if member_id:
        keys.append(f"{org}/idxm/{_idx_seg(member_id)}/{rest}.json")
    if workspace:
        keys.append(f"{org}/idxw/{_idx_seg(workspace)}/{rest}.json")
    return keys


async def _index_manifest(base: str, manifest: dict) -> None:
    """Persist a manifest to the flat index and its narrow per-harness/per-member/per-workspace
    mirrors, so all read surfaces (unfiltered Recents, per-harness Traces, per-member 'my
    sessions', per-workspace console views) agree."""
    data = json.dumps(manifest, default=str).encode()
    keys = _manifest_index_keys(base, str(manifest.get("harness_id") or ""),
                                str(manifest.get("member_id") or ""),
                                str(manifest.get("workspace") or ""))
    await asyncio.gather(*[_trace_put(k, data) for k in keys])


async def _prior_session_totals(prefix: str) -> tuple[float, dict]:
    """The session's credits/usage totals as of the CURRENT manifest — the one durable source both
    the turn-accept placeholder write and _trace_finalize must agree on. Whichever one omits these
    fields (rather than reading + carrying them forward) resets the session total to zero for every
    other reader until the next finalize — this is the ONE place either write path may read from,
    so there's no second copy of "what's the total so far" to drift out of sync."""
    if not prefix:
        return 0.0, {}
    try:
        pm = await _blob_get(_manifest_key(prefix), kb=TRACE_KB)
        if not pm:
            return 0.0, {}
        prior = json.loads(pm)
        return float(prior.get("credits") or 0.0), (prior.get("usage") or {})
    except Exception:  # noqa: BLE001
        return 0.0, {}


async def _write_running_card(tr: dict, *, sid: str, org: str, member: str, harness_id: str,
                              backend: str, model: str, user_text: str) -> None:
    """Interim 'running' session card written at turn ACCEPT (before this turn has produced any
    cost of its own), so Recents/Traces shows the chat the moment it starts. PURELY a display
    write — no billing call lives here or is implied by it; the turn's own charge is metered once,
    later, by _trace_finalize's _report_usage calls, gated by the fence/lease. Must carry the
    session's credits/usage totals SO FAR forward (via _prior_session_totals) rather than omit
    them: an omitted field here is exactly what _trace_finalize's own accumulate would read back as
    "0 prior" at this turn's finalize, silently resetting the running total on every new turn."""
    prior_credits, prior_usage = await _prior_session_totals(tr.get("prefix") or "")
    await _index_manifest(tr["prefix"], {
        "session_id": sid, "org_id": org, "tenant": org,
        "member_id": tr.get("member") or member or "",
        "harness_id": tr.get("harness_id") or harness_id or "",
        "workspace": tr.get("workspace") or "",
        "harness_name": tr.get("harness_name") or "",
        "backend": backend, "model": model,
        "title": (user_text.strip().splitlines()[0][:120] if user_text.strip() else sid[:16]),
        "user_prompt": user_text[:1500], "status": "running",
        "trace_blob": tr.get("prefix"), "chunks": [],
        "finished_at": time.time(), "schema_version": 1,
        "credits": prior_credits, "usage": prior_usage,
    })


async def _deindex_manifest(base: str, manifest: dict) -> None:
    """Remove a manifest from the flat index and its narrow mirrors (session delete)."""
    keys = _manifest_index_keys(base, str(manifest.get("harness_id") or ""),
                                str(manifest.get("member_id") or ""),
                                str(manifest.get("workspace") or ""))
    await asyncio.gather(*[_blob_delete(k, kb=TRACE_KB) for k in keys])


async def _trace_put(file_id: str, data: bytes) -> bool:
    return await _blob_put(file_id, data, kb=TRACE_KB)


async def _blob_list(prefix: str, limit: int = 20, cursor: str | None = None, kb: str = TRACE_KB) -> dict:
    return await BACKING.blob.list(kb, prefix, limit, cursor)


async def _blob_list_all(prefix: str, kb: str = TRACE_KB, hard_cap: int = 200000) -> list[dict]:
    """List EVERY object under `prefix` by FOLLOWING the VG continuation cursor (HR-INF-020).
    VG clamps each page to 1000, so callers that requested `limit=10000` and read only `items`
    silently lost every chunk past the first 1000 — dropping later events from consolidated
    history, event counts, reconciliation, and deletion. This pages to completion. `hard_cap`
    bounds a pathological listing; if hit we LOG it rather than silently truncate."""
    items: list[dict] = []
    cursor: str | None = None
    while True:
        page = await _blob_list(prefix, limit=1000, cursor=cursor, kb=kb)
        items.extend(page.get("items") or [])
        cursor = page.get("cursor")
        if not cursor:
            break
        if len(items) >= hard_cap:
            print(f"[trace] listing hit hard_cap={hard_cap} prefix={prefix} — raise the cap", flush=True)
            break
    return items


def _chunk_event_count(chunk_id: str) -> int | None:
    """Parse the per-chunk event count from a '{ms}-{nonce}-{seq}-{n}.jsonl' key.
    Returns None for legacy keys without the count suffix ('{ms}-{nonce}-{seq}.jsonl'
    or the ancient '{i:06d}.jsonl')."""
    stem = chunk_id.rsplit("/", 1)[-1].removesuffix(".jsonl")
    parts = stem.split("-")
    if len(parts) == 4 and parts[3].isdigit():
        return int(parts[3])
    return None


def _chunk_ms(chunk_id: str) -> int | None:
    """Parse the leading epoch-millis timestamp from a '{ms}-{nonce}-{seq}-{n}.jsonl' key.
    Chunk names are globally time-ordered (see _trace_flush), so this is the only signal the
    durable event log carries for WHICH TURN wrote a chunk — there is no resp_id in the key, the
    events/ directory is one flat, cross-turn stream for the whole session."""
    stem = chunk_id.rsplit("/", 1)[-1].removesuffix(".jsonl")
    head = stem.split("-", 1)[0]
    return int(head) if head.isdigit() else None


async def _trace_flush(tr: dict, s: dict) -> bool:
    """Persist newly-arrived events as a NEW ABS chunk (append-as-new-blob bounds each PUT; azure
    upload overwrites + loads the whole blob, so a monolithic re-PUT would be O(n^2)).

    Chunk filenames are globally unique and time-ordered: '{ms:013d}-{nonce}-{seq:06d}-{n:05d}.jsonl'.
    - ms (zero-padded epoch millis) makes a lexical sort equal a chronological sort, so the
      all-listing reassembles turns in order without tracking any index.
    - _TRACE_NONCE (per-replica) + seq (per-session monotonic) guarantee no two writes ever land on
      the same name — across turns, across replicas, or under concurrent follow-ups. This is what
      eliminates the old counter-collision that silently overwrote a prior turn's events.
    - n (event count in this chunk) lets finalize compute the manifest's total event_count from a
      key LISTING alone — no chunk downloads (HR-INF-015: the old finalize re-downloaded and
      re-joined the whole session transcript on EVERY turn's tail, O(n^2) per session)."""
    evs = s.get("events") or []
    put_ok = True
    if evs and tr.get("prefix"):
        body = ("\n".join(json.dumps(e, default=str) for e in evs) + "\n").encode()
        seq = tr.get("seq", 0)
        # Monotonic per session: an NTP step-back must not mint a key that sorts BEFORE an
        # already-written one (the last-chunk terminal probe and the chunk-key tail cursor both
        # rely on key order == write order).
        ms = max(int(time.time() * 1000), tr.get("last_ms", 0) + 1)
        tr["last_ms"] = ms
        key = f"{tr['prefix']}/events/{ms:013d}-{_TRACE_NONCE}-{seq:06d}-{len(evs):05d}.jsonl"
        put_ok = await _trace_put(key, body)
        if put_ok:
            tr["seq"] = seq + 1
            tr["count"] += len(evs)
    # HR-INF-014: advance the runner cursor ONLY after the durable chunk is
    # acknowledged. Advancing on a failed PUT (the old behavior) permanently
    # dropped those events — the runner never re-serves an acked offset. On a
    # failed write we leave `since` put, so the SAME events are re-fetched and
    # re-persisted on the next poll instead of being lost. Returns whether the
    # durable write succeeded so the primary poll loop can gate ITS cursor too.
    if put_ok and s.get("n_total") is not None:
        tr["since"] = s["n_total"]
    return put_ok


# ── compact transcript ────────────────────────────────────────────────────────
# Long-horizon traces embed huge tool-results/file-contents (tens of MB) into events.
# Shipping that whole transcript to the browser is what made loads take 30s. The
# viewer only needs SHORT previews in the timeline; full content is fetched lazily
# when one event is opened. So we serve a "compact" transcript: every long string
# truncated to a cap, structure otherwise identical (so the client's flatten() yields
# positionally-identical rows and can swap in full text by row index on demand).
_TRACE_CLIP = int(os.environ.get("HARNESS_TRACE_CLIP", "4000"))


def _clip_obj(o, cap: int):
    """Recursively truncate any string longer than `cap`. Returns (obj, clipped?)."""
    if isinstance(o, str):
        return (o[:cap] + f"\n…[clipped {len(o) - cap} chars — open to load full]", True) if len(o) > cap else (o, False)
    if isinstance(o, list):
        clipped = False
        out = []
        for v in o:
            nv, c = _clip_obj(v, cap)
            out.append(nv); clipped = clipped or c
        return out, clipped
    if isinstance(o, dict):
        clipped = False
        out = {}
        for k, v in o.items():
            nv, c = _clip_obj(v, cap)
            out[k] = nv; clipped = clipped or c
        return out, clipped
    return o, False


def _compact_ndjson(full: bytes, cap: int = _TRACE_CLIP) -> bytes:
    """Clip every event's long strings; mark clipped events with _clipped so the client knows to
    lazy-load the full event. Preserves event order/structure (positional row alignment)."""
    out = []
    for ln in full.split(b"\n"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            ev = json.loads(ln)
        except Exception:  # noqa: BLE001
            out.append(ln); continue
        ev, clipped = _clip_obj(ev, cap)
        if clipped:
            ev["_clipped"] = True
        out.append(json.dumps(ev, default=str).encode())
    return (b"\n".join(out) + b"\n") if out else b""


async def _recover_trace_cursor(tr: dict) -> None:
    """No-op. Chunk filenames are now globally-unique time-ordered keys (see _trace_flush), so a
    follow-up turn never needs to discover "the next index" — there is no index to collide on. Kept
    as a no-op so existing call sites stay valid; the old count-based cursor recovery (which still
    raced under concurrent follow-ups and broke if chunks weren't contiguous from 0) is gone."""
    return


async def _trace_finalize(sid: str, rec: dict) -> None:
    """Write session.json (card record + chunk index) once the turn is terminal. ABS is the
    Traces app's source of truth; the per-org/inverted-ts key gives reverse-chron LIST for free."""
    tr = _session_trace.get(sid)
    if not tr or not tr.get("prefix"):
        return
    # Manifest from a key LISTING alone (HR-INF-015): chunk names are time-ordered and carry their
    # event count ('{ms}-{nonce}-{seq}-{n}.jsonl'), so the total is the sum of the parsed suffixes —
    # across ALL turns and replicas — with ZERO chunk downloads. The old finalize downloaded and
    # re-joined the entire session transcript on every turn's tail (O(session) reads + RAM + 2
    # uploads, cumulatively O(n^2)); the consolidated all.jsonl is now built LAZILY on first read
    # of a finished trace (get_trace_all) instead of eagerly on every turn.
    try:
        _items = await _blob_list_all(f"{tr['prefix']}/events/", kb=TRACE_KB)
        _chunk_ids = sorted(it["file_id"] for it in _items if str(it.get("file_id", "")).endswith(".jsonl"))
    except Exception:  # noqa: BLE001
        _chunk_ids = []
    real_count = 0
    _legacy_ids: list[str] = []
    for cid in _chunk_ids:
        n = _chunk_event_count(cid)
        if n is None:
            _legacy_ids.append(cid)
        else:
            real_count += n
    if _legacy_ids:
        # Pre-suffix chunks (sessions started before the count-in-key scheme): count their lines by
        # downloading ONLY those chunks — exact and stateless (the prior-manifest field can't be
        # trusted: turn-start overwrites it without event_count). This cohort shrinks to zero as
        # legacy sessions age out; new sessions never enter this branch.
        try:
            parts = await asyncio.gather(*[_blob_get(c, kb=TRACE_KB) for c in _legacy_ids])
            real_count += sum(p.count(b"\n") for p in parts if p)
        except Exception:  # noqa: BLE001
            pass
    if not real_count:
        real_count = tr.get("count", 0)
    # Card title/user_prompt come from the RAW user message; rec["prompt"] carries runtime
    # prepends ("[Attached files saved in ...]", instructions) that must not leak into UI.
    prompt = rec.get("user_text") or rec.get("prompt") or ""
    manifest = {
        "session_id": sid, "org_id": tr.get("org"), "tenant": tr.get("org"),
        "billing_org": tr.get("billing_org") or tr.get("org"),
        "member_id": tr.get("member") or "", "harness_id": tr.get("harness_id") or "",
        "workspace": tr.get("workspace") or "",
        "harness_name": tr.get("harness_name") or "", "last_response_id": tr.get("last_response_id") or "",
        "backend": rec.get("backend"), "model": rec.get("model") or "",
        "title": (prompt.strip().splitlines()[0][:120] if prompt.strip() else sid[:16]),
        "user_prompt": prompt[:1500], "status": rec.get("status"),
        "connection": rec.get("connection"), "cli_session_id": rec.get("cli_session_id"),
        "result": (rec.get("result") or "")[:4000],
        "elapsed": rec.get("elapsed") or (round(time.time() - rec["started"], 1) if rec.get("started") else None),
        "event_count": real_count, "trace_blob": tr.get("prefix"),
        "chunks": [f"events/{cid.rsplit('/', 1)[-1]}" for cid in _chunk_ids],
        "finished_at": time.time(), "schema_version": 1,
    }
    _elapsed_s = manifest.get("elapsed") or 0
    _borg = str(manifest.get("billing_org") or "")
    # Fence the METERING so a turn is billed EXACTLY once even if two replicas both reach finalize
    # (the original owner resurrecting after adoption stole its fence). The trace/manifest write
    # below stays unconditional — it's an idempotent card overwrite, safe to repeat — but the
    # fire-and-forget usage reports are NOT idempotent, so only the current fence-holder emits them.
    # No fence recorded (LEASE off / store trouble → ran unfenced) meters as before (fail-open).
    _fence = rec.get("lease_fence") or 0
    _may_meter = True
    if _fence and LEASE_MODE != "off" and control_store.enabled():
        try:
            # The lease is keyed by the SESSION org (tenant), the same org it was acquired under —
            # NOT the billing org.
            _may_meter = await control_store.lease_still_held(str(tr.get("org") or ""), sid, _fence)
        except Exception:  # noqa: BLE001
            _may_meter = True   # store hiccup → don't silently drop billing
        if not _may_meter:
            print(f"[bill] skip metering sid={sid} fence={_fence} — superseded (adopted elsewhere)", flush=True)
    if _elapsed_s and _may_meter:
        # Meter the BILLING org (the harness owner's — the same org the credit gate admitted),
        # not the caller's: the Developer who built the harness pays for its infra consumption.
        _report_usage(_borg, "harness.session_minute", float(_elapsed_s) / 60.0)
    # LLM tokens: the turn's usage (the CLI's own report) bills against the model's priced
    # llm.{model}.{input,output}_1k rows. Pricing rows name claude versions with DASHES
    # (claude-opus-4-8) while the catalog's friendly name uses dots (claude-opus-4.8) —
    # normalize so the meter hits the priced row, not a silent 0-price miss.
    _usage = rec.get("usage") or {}
    _model = str(rec.get("model") or "")
    if _model.startswith("claude-"):
        _model = _model.replace(".", "-")
    if _model and _may_meter:
        for _kind, _key in (("input_1k", "input_tokens"), ("output_1k", "output_tokens"),
                            ("cache_read_1k", "cache_read_tokens"),
                            ("cache_write_1k", "cache_write_tokens")):
            _n = float(_usage.get(_key) or 0)
            if _n > 0:
                _report_usage(_borg, f"llm.{_model}.{_kind}", _n / 1000.0)
    # Stamp a concise SESSION-TOTAL credit figure + token usage onto the card (not just this turn's),
    # so the console chip shows what the whole task has cost, not whichever turn finalized last. The
    # manifest is the one card per session (_manifest_key), and turns finalize strictly sequentially
    # (the session execution lease serializes them — accept can't re-acquire it until this finalize
    # + release complete), so reading the prior manifest here and adding this turn's own contribution
    # is race-free: no separate accumulator state to keep in sync or drift from the truth.
    try:
        await _refresh_pricing_table()
        _this_credits = _run_credits(str(rec.get("model") or ""), _usage, float(_elapsed_s or 0))
        _prior_credits, _prior_usage = await _prior_session_totals(tr["prefix"])
        _summed_usage = dict(_prior_usage)
        for _k, _v in _usage.items():
            try:
                _summed_usage[_k] = float(_summed_usage.get(_k) or 0) + float(_v or 0)
            except (TypeError, ValueError):
                _summed_usage[_k] = _v
        manifest["usage"] = _summed_usage
        manifest["credits"] = _prior_credits + _this_credits
    except Exception:  # noqa: BLE001 — never let costing break finalize
        pass
    # NOTE (HR-INF-015): no consolidation here anymore. The single-blob transcript caches
    # (all.jsonl / all.compact.jsonl) are built lazily by get_trace_all on the FIRST read of a
    # finished trace. INVALIDATE them BEFORE writing the terminal manifest — ordering matters:
    # if the deletes ran after, a viewer (or a delete failure) could pin a PRIOR turn's cache as
    # authoritative against the NEW terminal manifest forever. Each delete individually guarded.
    for _cache in (f"{tr['prefix']}/all.jsonl", f"{tr['prefix']}/all.compact.jsonl"):
        try:
            await _blob_delete(_cache, kb=TRACE_KB)
        except Exception:  # noqa: BLE001
            pass
    try:
        await _index_manifest(tr["prefix"], manifest)
    except Exception:  # noqa: BLE001
        pass


async def _brain_mint_room(sid: str) -> str | None:
    """Mint a Company Brain doc for the session's blackboard and return its ULID (the Hocuspocus
    room). Minted under the DEFAULT tenant (no ?tenant) so the room is a BARE ULID — which is what
    the studio CollaborativeMarkdownEditor opens. Best-effort; never blocks session create."""
    if not BRAIN_HTTP:
        return None
    try:
        r = await _client().put(f"{BRAIN_HTTP}/v1/doc",
                                json={"relpath": f"sessions/{sid}/BLACKBOARD.md",
                                      "title": f"Harness session {sid[:12]}", "kind": "doc", "body": ""},
                                headers={"x-internal-key": BRAIN_INTERNAL_KEY}, timeout=20)
        if r.status_code < 400:
            return (r.json() or {}).get("id")
    except Exception:  # noqa: BLE001
        pass
    return None


async def _hydrate(sid: str, rec: dict) -> None:
    """Restore the session's last checkpoint into the sandbox /workspace before the turn runs, and
    pass the blackboard room so the runner (re)starts the realtime sidecar for this session."""
    params = {}
    v = await _vertex_get(sid) or {}          # single durable read: blackboard room + checkpoint sha
    room = (v.get("brain_room") or None) if COLLAB_URL else None
    if COLLAB_URL and room:
        params = {"collab_url": COLLAB_URL, "room": room, "collab_token": COLLAB_TOKEN}
    try:
        # Instant resume on a warm sandbox: if the sandbox still holds EXACTLY the last
        # checkpoint (sha marker kept by the runner), skip the blob download and the full
        # wipe+untar — the dominant cost of every follow-up turn on a big workspace.
        want_sha = str(v.get("ws_sha") or "")
        if want_sha:
            try:
                pr = await _sandbox("/hydrate", sid, "POST", content=b"",
                                    params={**(params or {}), "probe": want_sha})
                pj = pr.json() if pr.headers.get("content-type", "").startswith("application/json") else {}
                if pr.status_code < 400 and pj.get("skipped"):
                    rec["hydrated"] = True
                    rec["hydrate"] = pj
                    return
            except Exception:  # noqa: BLE001
                pass                        # probe is best-effort; fall through to full hydrate
        # Stream the checkpoint tar VG blob -> runner /hydrate without buffering it (HR-INF-015).
        r = await _hydrate_relay(sid, params)
        rec["hydrated"] = r.status_code < 400
        rec["hydrate"] = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        if not rec["hydrated"] and want_sha:
            # A checkpoint EXISTED (ws_sha on the vertex) but restoring it failed. Do NOT let this
            # turn checkpoint over the good blob from a workspace that isn't that checkpoint.
            rec["hydrate_failed_with_checkpoint"] = True
    except Exception as e:  # noqa: BLE001
        rec["hydrate_error"] = str(e)[:200]
        if str(v.get("ws_sha") or ""):
            rec["hydrate_failed_with_checkpoint"] = True


async def _checkpoint(sid: str, rec: dict) -> None:
    """Pull the committed /workspace from the sandbox and persist it to durable blob storage."""
    _ws_tar_evict(sid)             # workspace changed — next file open refetches
    _WS_FILES_CACHE.pop(sid, None)
    _bus_publish("_ctrl", "_ctrl", "", sid, "", {"type": "hr.ctrl.ws_invalidate"})  # all replicas
    try:
        # Work-loss guard (HR-INF-015 review): if hydrate FAILED while a checkpoint existed, this
        # sandbox's /workspace is NOT that checkpoint (it was wiped or never restored). Overwriting
        # the good durable blob from it would destroy the user's work. Skip the checkpoint entirely.
        if rec.get("hydrate_failed_with_checkpoint"):
            rec["checkpoint_skipped_hydrate_failed"] = True
            return
        # Fence backstop (HR-INF-012): if a NEWER turn has taken the session lease, THIS turn's
        # workspace is superseded — writing it would clobber the newer turn's checkpoint
        # (last-writer-wins). Checked BEFORE the relay so a superseded turn doesn't even pull the
        # tar. observe: log the skew but still write; enforce: skip the write.
        _fence = rec.get("lease_fence") or 0
        if _fence and LEASE_MODE != "off" and control_store.enabled():
            try:
                if not await control_store.lease_still_held(rec.get("tenant") or "", sid, _fence):
                    print(f"[lease] stale checkpoint sid={sid} mode={LEASE_MODE} fence={_fence}", flush=True)
                    if LEASE_MODE == "enforce":
                        rec["checkpoint_skipped_stale"] = True
                        return
            except Exception:  # noqa: BLE001
                pass
        # Stream runner tar -> VG blob without buffering the whole workspace (HR-INF-015).
        ok, nbytes, ws_sha, git_head = await _checkpoint_relay(sid)
        if nbytes > 0:
            rec["checkpoint_bytes"] = nbytes
            rec["checkpointed"] = ok
            # HR-INF-014: advance ws_sha (which hydrate's warm-resume probe trusts) ONLY after the
            # blob write is acknowledged — else the next turn's probe "skips hydrate" against a
            # checkpoint that was never stored (silent workspace loss).
            if ok:
                rec["ws_sha"] = ws_sha
                await _vertex_upsert(sid, {"checkpoint_bytes": str(nbytes), "git_head": git_head,
                                           "ws_sha": ws_sha})
            else:
                rec["checkpoint_error"] = "durable workspace upload failed; ws_sha not advanced"
    except Exception as e:  # noqa: BLE001
        rec["checkpoint_error"] = str(e)[:200]


# ── HarnessSession vertex (best-effort; never blocks a turn) ──────────────────────
async def _vertex_upsert(sid: str, props: dict) -> None:
    await BACKING.graph.upsert("HarnessSession", sid, props)


async def _vertex_get(sid: str) -> dict | None:
    """Read a HarnessSession vertex as a flat dict. This is the durable, replica-independent
    session state — any gateway replica can serve it."""
    return await BACKING.graph.get(sid)


# ── reconcile orphaned "running" sessions ───────────────────────────────────────
# A turn runs in the sandbox (survives gateway restarts), but the gateway's in-memory poll loop is
# what flips the session to done/failed. If that loop dies (gateway redeploy / crash / client drop
# without a live re-attach) the session is stuck "running" forever even though the sandbox turn
# finished — the durable trace already holds the terminal result. This sweep reconciles such sessions
# from the trace so the UI never shows a phantom forever-running turn.
# Statuses that mean a session's turn is OVER — one definition (two local copies had drifted:
# the cross-replica tail's omitted cancelled/timeout, so those sessions were tailed forever).
_SESSION_TERMINAL = {"done", "completed", "failed", "incomplete", "max_turns", "error", "timeout", "cancelled"}
_RECONCILE_STALE_S = int(os.environ.get("HARNESS_RECONCILE_STALE_S", "120"))
_RECONCILE_EVERY_S = int(os.environ.get("HARNESS_RECONCILE_EVERY_S", "60"))
_GW_MAX_TURN_S = int(os.environ.get("HARNESS_MAX_TURN_S", "21600"))


async def _trace_terminal_status(base: str) -> str | None:
    """'done'/'failed' if the trace has a terminal result event, else None (not finished yet).

    Walks chunks NEWEST-to-OLDEST until a result event is found (HR-INF-015): the old code
    downloaded the whole transcript to find the last result; the semantics — the last result
    event ANYWHERE settles a multi-turn orphan even when the final turn died result-less — are
    preserved by walking back, almost always stopping at the first (newest) chunk. Bounded at 50
    chunks so a pathological session can't regress to a full download."""
    if not base:
        return None
    listed = await _blob_list_all(f"{base}/events/", kb=TRACE_KB)
    chunk_ids = sorted(it["file_id"] for it in listed if it.get("file_id"))
    for cid in reversed(chunk_ids[-50:]):
        part = await _blob_get(cid, kb=TRACE_KB)
        if not part:
            continue
        last = None
        for ln in part.split(b"\n"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            if e.get("type") == "result":
                last = e                       # keep the LAST result within this chunk
        if last is not None:
            return "failed" if last.get("is_error") else "done"
    return None


def _output_to_turn_fields(output: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """Project a Responses output[] into the (assistant_text, tools, files) the Workbench renders.
    ONE parser, shared by the finalized-record path and the in-flight trace-replay path, so both
    render a turn identically."""
    asst_parts: list[str] = []
    tools: list[dict] = []
    files: list[dict] = []
    for o in (output or []):
        t = o.get("type")
        if t == "message":
            for cp in (o.get("content") or []):
                if cp.get("type") == "output_text":
                    # each message item is its own paragraph — the agent's interleaved narration
                    # (between tool calls) must not fuse into one run-on block
                    if cp.get("text", "").strip():
                        asst_parts.append(cp.get("text", "").strip())
                    for a in (cp.get("annotations") or []):
                        if a.get("type") == "container_file_citation":
                            files.append({"container_id": a.get("container_id"), "file_id": a.get("file_id"),
                                          "filename": a.get("filename"),
                                          "download_url": _file_url(a.get("container_id") or "", a.get("file_id") or "")})
        elif t == "function_call":
            tools.append({"name": o.get("name"), "arguments": o.get("arguments", "")})
    return "\n\n".join(asst_parts), tools, files


async def _replay_output_from_trace(base: str, resp_id: str, model: str, since_ms: int = 0) -> list[dict]:
    """Reconstruct a turn's Responses output[] from its durable trace chunks — the SAME trace and
    the SAME translator the live cross-replica tail feeds. An in-flight turn's stored response
    record has an empty output[] (it's only assembled at finalize), so a client that LOADS the
    conversation mid-turn (GET /v1/sessions/{sid}/turns) would otherwise render a blank 'Working…'
    bubble even though the events exist. This makes catch-up read the one authoritative event log,
    so an initial load shows exactly what the live tail has been streaming. Returns [] on any
    trouble (caller falls back to the stored — empty — output, i.e. no regression).

    since_ms scopes the replay to THIS turn: the events/ directory is one flat, time-ordered
    stream shared by EVERY turn in the session (chunk keys carry no resp_id — see _trace_flush), so
    without a cutoff this feeds prior turns' events into the same translator with no boundary
    between them, silently fusing an earlier turn's reply onto this one (they share one open
    message item — no separator, no error, just concatenated text). Pass the current turn's own
    created_at (as epoch millis) so only chunks THIS turn could have written are replayed. 0 keeps
    the old whole-directory behavior for callers that can't supply a start time."""
    if not base:
        return []
    try:
        listed = await _blob_list_all(f"{base}/events/", kb=TRACE_KB)
        chunk_ids = sorted(it["file_id"] for it in listed
                            if it.get("file_id") and (since_ms <= 0 or (_chunk_ms(it["file_id"]) or 0) >= since_ms))
        parts = await asyncio.gather(*[_blob_get(cid, kb=TRACE_KB) for cid in chunk_ids])
        tr = _RespTranslator(resp_id, model or "", None, True, time.time(), sid="")
        for ln in b"".join(p for p in parts if p).split(b"\n"):
            if not ln.strip():
                continue
            try:
                cev = json.loads(ln)
            except Exception:  # noqa: BLE001
                continue
            try:
                tr.feed(cev)   # accumulates into tr.output; we ignore the emitted SSE events here
            except Exception:  # noqa: BLE001 — one bad line must not lose the rest of the turn
                continue
        # Close any open item (trailing text/tool with no explicit done) so partial content shows.
        try:
            tr._close_cur()
        except Exception:  # noqa: BLE001
            pass
        return tr.output
    except Exception:  # noqa: BLE001
        return []


async def _adopt_orphan_turn(sid: str, org: str, v: dict) -> bool:
    """Resume harvesting a RUNNING turn whose owning replica died (deploy / autoscale scale-in /
    crash) — the turn is still executing in its sandbox, but nobody is pulling its events into the
    durable trace or the live bus, so every viewer freezes until the turn ends.

    A harvest is a pure function of durable state, so any replica can take over:
      • runner_turn_id (durable on the vertex) addresses the live sandbox turn (routed by sid);
      • the resume cursor is the count already in the trace (chunk-name sum — no re-flush/re-emit);
      • the fenced session lease is the exactly-one-harvester mutex — lease_admit(enforce) refuses
        if the original owner is still fresh (so we never double-harvest a live owner), and its
        fence bump makes any zombie owner's next flush/finalize CAS fail and stand down.

    Feeds new events through a translator (native deltas) to the bus + durable trace, exactly like
    the primary poll loop, and finalizes when the sandbox reports done. Returns True if it settled
    the turn terminal, False if it couldn't adopt / the turn is still running for a later sweep."""
    if not POOL_ENDPOINT or not control_store.enabled():
        return False
    rt = str(v.get("runner_turn_id") or "")
    resp_id = str(v.get("running_response_id") or "")
    base = _prefix_from_vertex(sid, v)
    if not rt or not resp_id or not base:
        return False
    # Is the sandbox turn actually still ALIVE? A dead/gone turn (404 or done) is NOT adopted here —
    # the caller settles it from the durable trace instead. Only a live, still-running turn is worth
    # resuming.
    try:
        probe = await _sandbox_json(f"/turn/{rt}", sid, "GET", params={"since": 0}, attempts=2)
    except Exception:  # noqa: BLE001
        return False                          # sandbox unreachable → let the trace-based settle run
    if probe.get("done"):
        return False                          # already finished → caller settles from trace/status
    # Take the lease ONLY if the original owner isn't fresh (enforce refuses a live owner). This is
    # the atomic "exactly one harvester" gate.
    try:
        adm = await control_store.lease_admit(org, sid, resp_id, LEASE_TTL_S,
                                              reject_on_conflict=True, fresh_s=LEASE_FRESH_S)
    except Exception:  # noqa: BLE001
        return False
    if adm.get("rejected"):
        return False                          # a fresh owner still holds it — not orphaned after all
    fence = adm.get("fence", 0)
    print(f"[adopt] resuming orphaned turn sid={sid} rt={rt} resp={resp_id} fence={fence}", flush=True)
    # This turn's OWN start time (persisted by the original owner at accept) — NOT time.time() here,
    # which is only when THIS replica adopted it. Needed at settle to scope the full-trace replay to
    # this turn's own chunks (pre- AND post-adoption), not prior turns sharing the same session trace.
    _orig_rec = await _resp_get(resp_id)
    turn_since_ms = int(float((_orig_rec or {}).get("created_at") or 0) * 1000)
    # Build trace state for _trace_flush (globally-unique time-ordered chunk keys → appending from a
    # new replica can't collide). Cursor starts at what's already durable, so we re-flush nothing.
    tr = {"prefix": base, "org": org, "billing_org": str(v.get("billing_org") or org),
          "member": str(v.get("member_id") or ""),
          "harness_id": str(v.get("harness_id") or ""), "harness_name": str(v.get("harness_name") or ""),
          "workspace": str(v.get("workspace") or ""), "since": 0, "seq": 0, "count": 0, "last_ms": 0}
    _session_trace[sid] = tr
    model = str(v.get("model") or "")
    harness_id = tr["harness_id"]
    member = tr["member"]
    translator = _RespTranslator(resp_id, model, None, True, time.time(), sid=sid)
    # Resume at the PER-TURN harvest cursor (the sandbox indexes /turn/{rt}?since=N in THIS turn's
    # own event space — NOT the session-wide trace count). The primary loop persists it after each
    # ack'd flush; poll since=cursor so no already-flushed event is re-written or re-emitted. If it
    # was never persisted (turn died before its first flush), 0 is correct — nothing is durable yet.
    try:
        cursor = await control_store.resp_get_cursor(org, resp_id)
    except Exception:  # noqa: BLE001
        cursor = 0
    rec = {"sid": sid, "tenant": org, "backend": str(v.get("backend") or ""), "model": model,
           "started": time.time(), "status": "running", "tried": [], "lease_fence": fence,
           "connection": str(v.get("last_connection") or ""), "runner_turn_id": rt}

    def _emit(ev):
        _bus_publish(org, harness_id, member, sid, resp_id, ev)

    terminal = None
    poll_fails = polls = 0
    while True:
        await asyncio.sleep(RESP_POLL_S)
        polls += 1
        # Keep OUR lease + the vertex heartbeat fresh so a later sweep sees this turn as live again
        # (owned by us now) instead of trying to re-adopt it.
        if polls % LEASE_RENEW_EVERY == 0:
            try:
                await control_store.lease_renew(org, sid, resp_id, fence, LEASE_TTL_S)
                await _vertex_upsert(sid, {"heartbeat": str(time.time())})
            except Exception:  # noqa: BLE001
                pass
        if await _turn_cancelled(sid, org, resp_id, check_store=(polls % 10 == 0)):
            try:
                await _sandbox_json(f"/turn/{rt}/cancel", sid, "POST", attempts=2)
            except Exception:  # noqa: BLE001
                terminal = "cancelled"; break
        try:
            s = await _sandbox_json(f"/turn/{rt}", sid, "GET", params={"since": cursor}, attempts=3, base=2.0)
            poll_fails = 0
        except Exception:  # noqa: BLE001
            poll_fails += 1
            if poll_fails >= 5:
                break                          # give up; a later sweep settles from the trace
            continue
        new = s.get("events") or []
        n_total = s.get("n_total", cursor)
        if new:
            if await _trace_flush(tr, {"events": new, "n_total": n_total}):
                for cev in new:
                    try:
                        for oev in translator.feed(cev):
                            _emit(oev)
                    except Exception:  # noqa: BLE001
                        continue
                # Advance the durable per-turn cursor as WE harvest, so if this adopter also dies a
                # third replica resumes correctly (adoption chains without re-flushing).
                try:
                    await control_store.resp_set_cursor(org, resp_id, int(n_total))
                except Exception:  # noqa: BLE001
                    pass
                cursor = n_total
        if s.get("session_id") and s["session_id"] != rec.get("cli_session_id"):
            rec["cli_session_id"] = s["session_id"]
            await _vertex_upsert(sid, {"cli_session_id": s["session_id"]})
        if s.get("done"):
            st = s.get("status")
            terminal = ("completed" if st == "done" else "incomplete" if st == "max_turns"
                        else "cancelled" if st == "cancelled" else "incomplete" if st == "timeout"
                        else "failed")
            break
    if terminal is None:
        return False                          # still running / adoption interrupted — later sweep retries
    # Settle exactly like the primary loop's tail: finalize the trace + persist the response record
    # + drop the lease. The fence guards against a resurrected original double-finalizing.
    rec["status"] = "done" if terminal == "completed" else terminal
    if translator.usage:
        rec["usage"] = translator.usage
    await _vertex_upsert(sid, {"status": rec["status"], "turn_status": rec["status"]})
    try:
        produced = (await _collect_produced(sid, set()) if terminal in ("completed", "incomplete") else [])
        for oev in translator.complete(rec["status"], produced):
            _emit(oev)
    except Exception:  # noqa: BLE001
        pass
    await _checkpoint(sid, rec)
    await _trace_finalize(sid, rec)
    # Persist the response record with the FULL turn output — NOT translator.output, which only
    # holds events AFTER our resume cursor (we joined mid-turn). Reconstruct the whole turn from the
    # durable trace (every event, pre- and post-adoption) so GET /v1/responses/{id} and the turns
    # view show the complete reply, not just the tail we personally harvested.
    _status = _RESP_STATUS_MAP.get(rec["status"], "failed")
    try:
        full_output = await _replay_output_from_trace(base, resp_id, model, since_ms=turn_since_ms)
        stored = {**translator._response_obj(_status), "_session_id": sid, "_org": org,
                  "_member": member}
        if full_output:
            stored["output"] = full_output
        await _resp_put(resp_id, stored, org, sid, None, _status, translator.created_at, True)
    except Exception:  # noqa: BLE001
        pass
    if fence:
        try:
            await control_store.lease_release(org, sid, resp_id, fence)
        except Exception:  # noqa: BLE001
            pass
    print(f"[adopt] settled orphaned turn sid={sid} status={rec['status']}", flush=True)
    return True


async def _reconcile_session(v: dict) -> bool:
    sid = v.get("id") or v.get("session_id")
    if not sid:
        return False
    try:
        hb = float(v.get("heartbeat") or 0)
    except Exception:  # noqa: BLE001
        hb = 0
    age = time.time() - hb
    if age < _RECONCILE_STALE_S:
        return False                       # fresh heartbeat -> a live turn is still being polled
    base = v.get("trace_blob")
    status = await _trace_terminal_status(base)
    if status is None:
        if age > _GW_MAX_TURN_S:
            status = "failed"              # past the hard cap with no result -> interrupted
        else:
            # Stale heartbeat but no terminal result yet: the owning replica likely died mid-turn
            # (deploy / scale-in / crash) while the turn keeps executing in its sandbox. ADOPT it —
            # resume harvesting its events to the trace + bus so viewers don't freeze. Run it
            # DETACHED (it polls for the rest of the turn); blocking here would stall the sweep for
            # every other session. The lease makes adoption single-flight, so a duplicate spawn on
            # the next sweep simply refuses at lease_admit. Tracked in _inflight so drain settles it.
            if sid not in _adopting:
                _adopting.add(sid)
                async def _adopt_bg(_sid=sid, _org=str(v.get("tenant") or ""), _v=v):
                    try:
                        await _adopt_orphan_turn(_sid, _org, _v)
                    except Exception:  # noqa: BLE001 — best-effort; never surface
                        pass
                    finally:
                        _adopting.discard(_sid)
                _t = asyncio.create_task(_adopt_bg())
                _inflight.add(_t)
                _t.add_done_callback(_inflight.discard)
            return False                   # not settled yet; the detached adopter (or a later sweep) will
    await _vertex_upsert(sid, {"status": status, "turn_status": status})
    if base:                               # reflect in the manifest so the Recents/Traces card updates
        mb = await _blob_get(_manifest_key(base), kb=TRACE_KB)
        if mb:
            try:
                m = json.loads(mb)
                if m.get("status") != status:
                    m["status"] = status
                    await _index_manifest(base, m)
            except Exception:  # noqa: BLE001
                pass
    return True


# Map session/trace terminal vocabulary -> Responses status vocabulary.
_RESP_STATUS_MAP = {"done": "completed", "completed": "completed", "failed": "failed",
                    "cancelled": "cancelled", "max_turns": "incomplete", "timeout": "incomplete",
                    "incomplete": "incomplete", "error": "failed"}


async def _reconcile_response(rid: str, rec: dict) -> dict:
    """Durable settler for an async (background) response record. GET /v1/responses/{id} is the
    ONLY completion signal a background poller has, so a record left at 'running' by a replica that
    died mid-turn would hang the poller forever. If the record is non-terminal but its owning turn
    is actually finished/dead — the session vertex is already terminal, or its heartbeat is stale
    (the owner stopped renewing) and the trace shows a terminal result — settle the record from that
    durable truth. A genuinely-live turn (fresh heartbeat) is left untouched."""
    if str(rec.get("status") or "") in _IDEM_TERMINAL:
        return rec
    sid = str(rec.get("_session_id") or "")
    if not sid:
        return rec
    v = await _vertex_get(sid) or {}
    vs = str(v.get("status") or "")
    settled = None
    if vs in ("done", "failed", "cancelled"):
        settled = _RESP_STATUS_MAP.get(vs)
    else:
        try:
            hb = float(v.get("heartbeat") or 0)
        except Exception:  # noqa: BLE001
            hb = 0
        if time.time() - hb >= _RECONCILE_STALE_S:      # owner stopped heartbeating → orphaned
            ts = await _trace_terminal_status(v.get("trace_blob"))
            if ts:
                settled = _RESP_STATUS_MAP.get(ts, "failed")
            elif time.time() - hb > _GW_MAX_TURN_S:
                settled = "failed"                       # past the hard cap with no result
    if not settled or settled == str(rec.get("status") or ""):
        return rec
    # RE-READ before persisting: the owning replica may have written the FULL final record
    # (output + usage) between our earlier read and now — persisting our stale snapshot with a
    # settled status would permanently clobber that content (the 'response lost until refresh'
    # bug). Settle the freshest copy; if it's already terminal, the owner won and we write
    # nothing.
    try:
        b = await _blob_get(f"responses/{rid}.json", kb=RESP_BLOB_KB)
        if b:
            fresh = json.loads(b)
            if str(fresh.get("status") or "") in _IDEM_TERMINAL:
                return fresh
            rec = fresh
    except Exception:  # noqa: BLE001
        pass
    rec["status"] = settled
    try:
        await _blob_put(f"responses/{rid}.json", json.dumps(rec, default=str).encode(), kb=RESP_BLOB_KB)
        await _vg_upsert("HarnessResponse", rid, {"status": settled})
    except Exception:  # noqa: BLE001
        pass
    return rec


async def _reconcile_sweep() -> int:
    rows = await BACKING.graph.find("HarnessSession", {"status": "running"})
    fixed = 0
    for v in rows:
        try:
            if await _reconcile_session(v):
                fixed += 1
        except Exception:  # noqa: BLE001
            pass
    return fixed


@app.on_event("startup")
async def _start_bus() -> None:
    global _redis_out
    if REDIS_URL:
        _redis_out = asyncio.Queue(maxsize=100_000)
        asyncio.create_task(_redis_pump())
        asyncio.create_task(_redis_listen())


@app.on_event("startup")
async def _start_reconcile() -> None:
    async def loop() -> None:
        while True:
            try:
                # Single-flight across replicas (HR-INF-010): the sweep is a full-label Gremlin scan
                # on the shared partition; running it on every replica every cycle was O(replicas)
                # identical scans. A one-shot TTL lock elects one sweeper per cycle. Safe because the
                # sweep is an idempotent healer of orphaned 'running' vertices derived from durable
                # blob truth — a skipped cycle only delays healing (nothing depends on multiplicity),
                # and on-demand settling still happens in GET /v1/responses/{id}.
                run_it = True
                if control_store.enabled():
                    try:
                        run_it = await control_store.try_lock("reconcile-sweep", _RECONCILE_EVERY_S - 5)
                    except Exception:  # noqa: BLE001 — store DOWN: fail OPEN and sweep (duplicates harmless)
                        run_it = True
                if run_it:
                    await _reconcile_sweep()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_RECONCILE_EVERY_S)
    asyncio.create_task(loop())


@app.on_event("shutdown")
async def _drain_inflight() -> None:
    """HR-INF-019: on SIGTERM (deploy / autoscale scale-in) a replica must not instantly orphan its
    detached background turns — those hold no HTTP connection, so uvicorn's connection drain doesn't
    cover them and the old `except Exception` never caught the cancellation. Wait up to _DRAIN_S for
    in-flight turns to finish NATURALLY (checkpoint + metering happen on completion); then cancel any
    stragglers and await them HERE — while the loop is still alive — so each turn's CancelledError
    handler settles it 'failed' (honest) instead of leaving a 6h phantom 'running'."""
    if not _inflight:
        return
    pending = list(_inflight)
    print(f"[drain] SIGTERM: waiting up to {_DRAIN_S}s for {len(pending)} in-flight turn(s)", flush=True)
    try:
        await asyncio.wait(pending, timeout=_DRAIN_S)
    except Exception:  # noqa: BLE001
        pass
    still = [t for t in pending if not t.done()]
    if still:
        print(f"[drain] {len(still)} turn(s) still running at deadline — settling failed", flush=True)
        for t in still:
            t.cancel()
        # Await the cancellations so the CancelledError handlers' settle-writes complete before exit.
        try:
            await asyncio.gather(*still, return_exceptions=True)
        except Exception:  # noqa: BLE001
            pass


async def _harness_vertex(harness_id: str) -> dict | None:
    """Read a Harness vertex (HR tenant) as a flat dict — its config (mcp_servers, skills props)."""
    # harness_id is caller-controlled (metadata / X-Harness-Id) and now drives BILLING — keep it to
    # the id charset (chrn<hex> / builtin slugs) so it can never smuggle Gremlin syntax.
    if not harness_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", harness_id):
        return None
    # The label scope is load-bearing: harness_id is caller-controlled, and billing keys off this
    # vertex's org — an arbitrary vertex id (e.g. a session vertex, which has no `org` prop) must
    # resolve to None, never masquerade as a harness.
    return await BACKING.graph.get(harness_id, label="Harness")


async def _resolve_mcp_auth(org: str, auth: str) -> str:
    """Resolve an MCP server auth value. 'vault:<key>' → the secret from the org/global vault
    (token never sits in the graph). Anything else is treated as a literal bearer token."""
    if isinstance(auth, str) and auth.startswith("vault:"):
        key = auth[len("vault:"):]
        for tenant in _tenants_for(org):
            v = await _vault_get(tenant, key)
            if v:
                return v
        return ""
    return auth or ""


_HDR_REF = re.compile(r"\$headers\.([A-Za-z0-9_-]+)")


def _sub_headers(value: str, hdr_vals: dict[str, str]) -> str:
    """Substitute $headers.{Name} references with the per-request header values captured on
    POST /v1/responses (names matched case-insensitively — HTTP headers arrive lowercased).
    An undeclared/missing header renders as empty, so a bad call fails loudly at the MCP
    instead of leaking the literal placeholder."""
    if not isinstance(value, str) or "$headers." not in value:
        return value
    return _HDR_REF.sub(lambda m: hdr_vals.get(m.group(1).lower(), ""), value)


async def _harness_plugins(harness_id: str, org: str, hdr_vals: dict[str, str] | None = None,
                           hv: dict | None = None) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Resolve a harness's ENABLED MCP servers + skills for a turn. MCP auth refs are resolved
    from the vault here so the runner never sees vault keys, only the live token (or none).
    `hv` (HR-INF-010): the already-read harness vertex — the SOLE caller (_resp_execute) always
    threads it, so we DON'T re-read. Using the same snapshot as agent_doc means both degrade
    together if the read failed (hv is None → empty plugins), never inconsistently (review #5)."""
    if not harness_id:
        return [], [], [], []
    v = hv
    if not v:
        # An out-of-box harness has no stored record — there is nothing to read, and that is
        # normal, not a failure. It still gets the image's built-in skills: those are a property
        # of the deployment rather than of a saved configuration. Returning nothing here is why
        # the default harnesses, which is what most people actually use, had no image generation
        # and no document skills while custom ones did.
        return [], _builtin_default_skills(), [], []

    def _arr(prop):
        try:
            a = json.loads(v.get(prop) or "[]")
            return a if isinstance(a, list) else []
        except Exception:  # noqa: BLE001
            return []

    mcp_out: list[dict] = []
    for s in _arr("mcp_servers"):
        if not isinstance(s, dict) or str(s.get("enabled")) in ("False", "false", "0"):
            continue
        if not s.get("url"):
            continue
        _hvals = hdr_vals or {}   # (renamed from hv — that name is now the harness-vertex param)
        _url = _sub_headers(s["url"], _hvals)
        # Same rule the console's Test connection applies. Enforced here too, because this is the
        # call that actually reaches the network: a URL the policy rejects must never be handed to
        # a sandbox, whatever is stored on the harness.
        _blocked = _ssrf_check(_url)
        if _blocked:
            print(f"[mcp] refusing '{s.get('name') or 'mcp'}' for harness {harness_id}: {_blocked}",
                  flush=True)
            continue
        entry = {"name": s.get("name") or s.get("id") or "mcp", "url": _url,
                 "transport": s.get("transport") or "http"}
        # $headers refs resolve BEFORE vault: an auth of "$headers.X-App-JWT" is the caller's
        # per-request token, not a vault key. Values are injected here, gateway-side, so the
        # runner only ever receives fully-resolved literals (same contract as vault refs).
        raw_auth = _sub_headers(str(s.get("auth") or ""), _hvals)
        token = await _resolve_mcp_auth(org, raw_auth)
        if token:
            entry["auth"] = token
        if isinstance(s.get("headers"), dict):
            entry["headers"] = {k: _sub_headers(str(vv), _hvals) for k, vv in s["headers"].items()}
        mcp_out.append(entry)

    # Skill manifest = the harness's own skills MERGED with its base builtin's defaults (a custom
    # harness inherits the doc skills installed on its base; an own entry overrides by name, and an
    # own entry with enabled:false suppresses an inherited one). Builtins have no base → own only.
    own = [s for s in _arr("skills") if isinstance(s, dict) and (s.get("name") or s.get("id"))]
    own_names = {(s.get("name") or s.get("id")) for s in own}
    base_id = str(v.get("base") or "")
    inherited: list[dict] = []
    if base_id and base_id != harness_id:
        bv = await _harness_vertex(base_id)
        if bv:
            try:
                for bs in json.loads(bv.get("skills") or "[]"):
                    if isinstance(bs, dict) and (bs.get("name") or bs.get("id")) not in own_names:
                        inherited.append(bs)
            except Exception:  # noqa: BLE001
                pass

    skills_out: list[dict] = []
    suppressed: list[str] = []   # built-in skill names this harness disabled (runner skips mounting them)
    builtins = _builtin_skills()
    seen: set[str] = set()
    for sk in own + inherited:
        name = sk.get("name") or sk.get("id")
        if not name:
            continue
        seen.add(name)
        if str(sk.get("enabled")) in ("False", "false", "0"):
            suppressed.append(name)   # present-and-disabled → suppress the inherited built-in of this name
            continue
        files = sk.get("files")
        # An entry naming a built-in and carrying no files of its own is the harness switching that
        # built-in ON (it is stored only when the answer differs from the image's default). Its
        # content comes from the image, so a Harness never holds a stale copy of a bundled skill.
        if not files and not sk.get("content") and not sk.get("blob") and name in builtins:
            files = builtins[name]["files"]
        # Large skill bundles (the Agent Skills folders exceed the 64k vertex-prop cap) live in a
        # blob; the vertex prop carries only {name, enabled, blob}. Resolve the full files here.
        if not files and sk.get("blob"):
            raw = await _blob_get(f"skills/{sk['blob']}.json", kb=BLOB_KB)
            if raw:
                try:
                    files = json.loads(raw.decode())
                except Exception:  # noqa: BLE001
                    files = None
        if not (files or sk.get("content")):
            continue
        skills_out.append({"name": name, "files": files, "content": sk.get("content")})

    # Built-ins the harness never mentions: on when the image says so. Implicit, so the set follows
    # the image rather than whatever was true when the Harness was created.
    skills_out += _builtin_default_skills(seen)

    disabled_tools = [t for t in _arr("disabled_tools") if isinstance(t, str)]
    return mcp_out, skills_out, suppressed, disabled_tools


# ── API ──────────────────────────────────────────────────────────────────────────
# ── LLM egress broker endpoint ───────────────────────────────────────────────────────────────
# The sandbox's CLI points its base_url here and presents the per-turn token as its API key. We
# resolve the token to its connection, swap in the real provider credential, and stream the
# upstream response back untouched. The provider key never leaves this process.
# What may be reached with OUR provider credential. The broker existed to carry inference and
# nothing else, but it forwarded ANY path the sandbox asked for — so a customer's shell could call
# a provider's account or key-management endpoints on our account, not merely /v1/messages. The
# sandbox cannot read the key back, but "unlimited inference" and "full API access to our provider
# account" are very different grants.
#
# The surface below is the complete documented one for every brokered provider, taken from what the
# runner actually configures (harness_runner/server.py): Claude Code speaks the Anthropic Messages
# API, Codex speaks Responses or Chat Completions, hermes speaks Chat Completions. Matching is on
# the suffix AFTER the v1/ collapse, so it is the same string for every base_url shape.
#
# Modes mirror the other observe->enforce gates in this file (HR_IDENTITY_MODE, HR_SESSION_LEASE,
# HR_CREDIT_GATE): off | observe | enforce. A denial is one clearly-logged 403, never a silent
# corruption, and HR_BROKER_PATHS=observe reopens everything instantly if a real CLI path was missed.
_BROKER_ALLOWED_EXACT = {"messages", "messages/count_tokens", "responses", "chat/completions",
                         "completions", "embeddings", "models"}
_BROKER_ALLOWED_PREFIX = ("responses/", "models/", "messages/batches")
HR_BROKER_PATHS = os.environ.get("HR_BROKER_PATHS", "enforce").strip().lower()

# Image generation rides the same broker as chat, so a task never holds a provider key. It is a
# SEPARATE switch because the money works differently: this relay does not meter, and image APIs
# bill per image rather than per token, so a deployment spending its OWN key must count images
# before opening this.
#
# Default OFF, and the self-hosted entrypoint turns it on. The other way round — on by default,
# hosted sets 0 — fails OPEN: forget the variable in one environment and it quietly serves images
# on our key with nothing metered. Bring-your-own-key is the case where nothing needs metering,
# and that is exactly the case that opts in.
_BROKER_IMAGE_PATHS = {"images/generations", "images/edits", "images/variations"}
HR_BROKER_IMAGES = os.environ.get("HR_BROKER_IMAGES", "0").strip().lower() in ("1", "on", "true")


def _broker_path_allowed(suffix: str) -> bool:
    """True if this upstream path is part of the inference surface."""
    s = (suffix or "").strip("/").lower()
    if not s or ".." in s:      # empty or traversal — never forward our credential
        return False
    if s in _BROKER_IMAGE_PATHS:
        return HR_BROKER_IMAGES
    return s in _BROKER_ALLOWED_EXACT or s.startswith(_BROKER_ALLOWED_PREFIX)


_BROKER_HOP = ("host", "content-length", "connection", "keep-alive", "transfer-encoding",
               "authorization", "api-key", "x-api-key")


# Extended thinking is off through the broker, and this is the one place that enforces it.
#
# The decision itself is not new — harness_runner already set MAX_THINKING_TOKENS=0 to stop
# Claude Code sending thinking params, because opus-4.7/4.8 rejected `thinking.enabled` with a
# 400 that leaked into the reply. That mechanism lived in the CLI's environment, so it only
# covered one harness and only the shape the CLI used at the time. The CLI has since moved to
# `output_config.effort`, which MAX_THINKING_TOKENS does not suppress, and haiku-4.5 rejects it
# with "This model does not support the effort parameter" — the same class of failure, on a
# different harness, through a different field.
#
# Every harness's inference traffic passes through this proxy, so enforcing it here covers
# Claude Code, Hermes, Codex and anything added later, across whichever thinking API a CLI
# happens to speak. The per-harness env hack is deleted rather than kept alongside: two
# mechanisms for one behaviour is how the first one went stale unnoticed.
# These travel together and must be removed together. `context_management`'s only strategy
# today (clear_thinking_20251015) is defined in terms of thinking, so removing `thinking` while
# leaving it produced a NEW 400 — "clear_thinking_20251015 strategy requires thinking to be
# enabled or adaptive" — turning one broken model into a broken harness. Against this provider
# context_management is rejected outright ("Extra inputs are not permitted") whether thinking is
# present or not, so the coherent unit is: strip the whole group, leave a self-consistent request.
_STRIP_REQUEST_FIELDS = ("thinking", "reasoning", "reasoning_effort", "context_management")


def _strip_unsupported(body: bytes) -> bytes:
    """Remove thinking/effort controls from an inference request body.

    Returns the body unchanged if it is not JSON — the broker must stay a dumb pipe for
    anything it does not positively understand.
    """
    if not body:
        return body
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(doc, dict):
        return body
    changed = False
    for f in _STRIP_REQUEST_FIELDS:
        if f in doc:
            doc.pop(f)
            changed = True
    # `output_config` carries more than effort; drop only that key, and the object with it
    # if nothing else remains, so a provider never sees an empty container it may reject.
    oc = doc.get("output_config")
    if isinstance(oc, dict) and "effort" in oc:
        oc.pop("effort")
        changed = True
        if not oc:
            doc.pop("output_config")
    return json.dumps(doc).encode() if changed else body


def _broker_token(request: Request) -> str:
    """CLIs differ in how they present a key (Bearer / api-key / x-api-key) — accept all three
    rather than special-casing per backend, which would be three paths for one decision."""
    auth = request.headers.get("authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return (request.headers.get("api-key") or request.headers.get("x-api-key") or "").strip()


async def _broker_resolve(conn_name: str, org: str | None) -> dict | None:
    """Resolve a turn credential's connection name back to its credentials.

    TWO shapes reach here and both must work, which is why resolution lives in one function:
    a chain connection is a real vault entry (harness-conn-<name>), while a model-mapped
    integration is SYNTHETIC — built at turn time as "integration:<name>" and never stored, so a
    vault lookup 502s on it (which is exactly what the first cut of this broker did)."""
    if conn_name.startswith("integration:"):
        iname = conn_name.split(":", 1)[1]
        integ = next((i for i in await _integrations_doc() if (i.get("name") or "") == iname), None)
        if not integ:
            return None
        cfg = dict(integ.get("config") or {})
        # provider here is the INTEGRATION's own type — it selects the upstream auth header, which
        # is all the broker needs (the runner-side wiring already happened at turn start).
        cfg["provider"] = (integ.get("provider") or "").lower()
        return cfg
    conn, _ = await _get_connection(org, conn_name)
    return conn


@app.api_route("/v1/llm/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def llm_broker(path: str, request: Request):
    claims = _verify_turn_cred(_broker_token(request))
    if not claims:
        raise HTTPException(401, "invalid or expired turn credential")
    sid, conn_name = claims
    v = await _vertex_get(sid) or {}
    conn = await _broker_resolve(conn_name, str(v.get("tenant") or "") or None)
    if not conn:
        raise HTTPException(502, "connection unavailable")

    base = str(conn.get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(502, "connection has no base_url")
    # CLIs append their own version segment (…/v1/messages, …/v1/responses) while provider
    # base_urls already end in /v1 — collapse the duplicate rather than 404 upstream.
    suffix = path[3:] if path.startswith("v1/") else path
    if not _broker_path_allowed(suffix):
        print(f"[broker] path not on the inference allowlist: {suffix!r} (sid={sid}) "
              f"mode={HR_BROKER_PATHS}", flush=True)
        if HR_BROKER_PATHS == "enforce":
            raise HTTPException(403, "this path is not available through the model broker")
    url = f"{base}/{suffix}" if suffix else base
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {k: val for k, val in request.headers.items() if k.lower() not in _BROKER_HOP}
    key = str(conn.get("api_key") or "")
    provider = str(conn.get("provider") or "")
    # Present the real credential the way THIS provider expects it.
    if provider in ("azure", "azure-foundry"):
        headers["api-key"] = key
    elif provider == "anthropic":
        headers["x-api-key"] = key
    else:
        headers["authorization"] = f"Bearer {key}"

    body = _strip_unsupported(await request.body())
    rc = _relay_client()
    req = rc.build_request(request.method, url, headers=headers, content=body or None)
    up = await rc.send(req, stream=True)

    async def pump():
        try:
            async for chunk in up.aiter_raw():
                yield chunk
        finally:
            await up.aclose()

    out = {k: val for k, val in up.headers.items()
           if k.lower() not in ("content-length", "transfer-encoding", "connection")}
    return StreamingResponse(pump(), status_code=up.status_code, headers=out,
                             media_type=up.headers.get("content-type"))


# ── Unified Harness Protocol: version, discovery, and the error envelope ────────────────
# The protocol this server implements is specified in protocol/ — this section is the part of the
# implementation the specification names directly. Writing the specification exposed three things
# this server did not do, and all three were client-visible defects rather than cosmetic gaps:
#
#   1. Nothing told a client which contract a response was written to. Added UHP-Version on every
#      response, and honoured on the way in.
#   2. A client had no way to ask what this server supports; it had to guess, or learn from a 404.
#      Added GET /v1/uhp.
#   3. Failures returned a bare human string, so a client had to match on prose to decide whether to
#      retry. Added the structured error envelope. The old `detail` string is still emitted beside
#      it, because clients in the wild read it — it is documented as deprecated, not removed under
#      them.
UHP_VERSION = "2026-08-11"
UHP_VERSIONS = [UHP_VERSION]

# Capabilities are declared, not inferred, and the conformance suite checks each one against the
# behaviour it promises. Reporting false is a supported answer; omitting a key is not, because a
# client cannot tell an omission from an older server.
UHP_CAPABILITIES = {
    "streaming": True,
    "sessions": True,
    "cancellation": True,
    "files_input": True,
    "files_output": True,
    "session_listing": True,
    "harness_management": True,
    "session_sharing": True,
    "idempotency": True,
}
UHP_CONFORMANCE_CLASS = "full"

# status -> (error type, fallback code) for raises that predate uhp_error() and carry only a string.
# The type is always right because it follows from the status; the code is generic, which is honest:
# a made-up specific code would be worse than one that says only as much as the status does.
_UHP_STATUS_TYPE = {
    400: ("invalid_request_error", "invalid_input"),
    401: ("authentication_error", "invalid_credential"),
    403: ("permission_error", "insufficient_scope"),
    404: ("invalid_request_error", "not_found"),
    409: ("invalid_request_error", "conflict"),
    413: ("invalid_request_error", "file_too_large"),
    422: ("invalid_request_error", "unprocessable"),
    429: ("rate_limit_error", "rate_limited"),
    500: ("server_error", "internal_error"),
    501: ("server_error", "not_implemented"),
    502: ("server_error", "upstream_error"),
    503: ("server_error", "unavailable"),
    504: ("server_error", "timeout"),
}


def uhp_error(status: int, code: str, message: str, param: str | None = None,
              detail: dict | None = None) -> HTTPException:
    """Raise a failure the protocol names. `raise uhp_error(404, "harness_not_found", ...)`.

    Carries the structured fields through FastAPI's HTTPException.detail so the handler below can
    emit them verbatim instead of guessing from the status.
    """
    etype = _UHP_STATUS_TYPE.get(status, ("server_error", "internal_error"))[0]
    return HTTPException(status, {"__uhp__": True, "type": etype, "code": code,
                                  "message": message, "param": param, "detail": detail})


@app.exception_handler(HTTPException)
async def _uhp_http_exception(request: Request, exc: HTTPException):
    d = exc.detail
    if isinstance(d, dict) and d.get("__uhp__"):
        err = {k: d.get(k) for k in ("type", "code", "message", "param", "detail")}
    else:
        etype, code = _UHP_STATUS_TYPE.get(exc.status_code, ("server_error", "internal_error"))
        err = {"type": etype, "code": code, "message": str(d) if d else "request failed",
               "param": None, "detail": None}
    body = {"error": err, "detail": err["message"]}   # `detail`: deprecated alias, see above
    return JSONResponse(body, status_code=exc.status_code,
                        headers={**(exc.headers or {}), "UHP-Version": UHP_VERSION})


@app.middleware("http")
async def _uhp_version(request: Request, call_next):
    """Negotiate the protocol version, and state on every response which one was served.

    A client that asks for a version this server cannot serve is refused. Serving it a different
    version quietly would be worse: it would receive a body it may not be able to parse, with
    nothing indicating why.
    """
    want = (request.headers.get("uhp-version") or "").strip()
    if want and want not in UHP_VERSIONS:
        return JSONResponse(
            {"error": {"type": "invalid_request_error", "code": "unsupported_protocol_version",
                       "message": f"This server does not implement UHP version '{want}'.",
                       "param": "UHP-Version", "detail": {"supported": UHP_VERSIONS}},
             "detail": f"This server does not implement UHP version '{want}'."},
            status_code=400, headers={"UHP-Version": UHP_VERSION})
    resp = await call_next(request)
    resp.headers["UHP-Version"] = UHP_VERSION
    return resp


@app.get("/v1/uhp")
def uhp_discovery() -> dict:
    """Protocol discovery. Deliberately unauthenticated: a client has to be able to find out whether
    this is a UHP server, and which versions it speaks, BEFORE it decides what credential to present.
    Nothing here is principal-specific."""
    return {"object": "uhp.discovery", "protocol": "uhp",
            "versions": UHP_VERSIONS, "default_version": UHP_VERSION,
            "conformance_class": UHP_CONFORMANCE_CLASS,
            "capabilities": dict(UHP_CAPABILITIES),
            "implementation": {"name": "HarnessRouter Community Edition",
                               "version": os.environ.get("HR_VERSION", "0.3.0")}}


@app.get("/healthz")
def healthz(bus: int = 0) -> dict:
    if bus:
        return {"ok": True, "redis_configured": bool(REDIS_URL), **_redis_ok}
    return {"ok": True, "pool": bool(POOL_ENDPOINT), "vault": bool(VAULT_URL)}


@app.get("/readyz")
async def readyz(response: Response) -> dict:
    """Dependency-aware READINESS (HR-INF-014/034), distinct from liveness. Probes
    the blob/graph plane and the durable control store; returns 503 (so the edge
    stops routing) if a dependency required for correct operation is unreachable —
    a green /healthz with a dead blob plane was exactly how data loss stayed
    invisible. Redis is reported but not gating (the bus degrades, it doesn't lose
    durable state)."""
    checks: dict = {}
    ok = True
    # Blob/graph plane: a RAISING probe (the normal _blob_list swallows errors and returns
    # empty, so it could never fail readiness). This does the keyed vg-gateway round-trip and
    # treats a non-2xx / unreachable / unconfigured plane as NOT ready.
    try:
        await asyncio.wait_for(BACKING.blob.probe(), timeout=5)
        checks["blob"] = True
    except Exception as e:  # noqa: BLE001
        checks["blob"] = f"down: {str(e)[:80]}"; ok = False
    # Durable control store (idempotency/lease/cancel authority).
    if control_store.enabled():
        try:
            checks["control_store"] = await asyncio.wait_for(control_store.healthcheck(), timeout=8)
            ok = ok and bool(checks["control_store"])
        except Exception as e:  # noqa: BLE001
            checks["control_store"] = f"down: {type(e).__name__}: {str(e)[:200]}"; ok = False
    else:
        checks["control_store"] = "disabled"
    checks["redis"] = {"configured": bool(REDIS_URL), **_redis_ok}   # reported, not gating
    checks["bus_drops"] = dict(_bus_drops.counts)   # cumulative live-event drops (HR-INF-018 visibility)
    checks["billing_drops"] = dict(_billing_drops.counts)   # lost usage reports (HR-INF-023 visibility)
    checks["identity"] = {"mode": HR_IDENTITY_MODE, **_identity_obs.counts}   # LIVE-B rollout visibility
    checks["credit"] = {"mode": HR_CREDIT_GATE, **_credit_obs.counts}   # HR-INF-023 admission-gate rollout
    checks["build"] = HR_BUILD_SHA   # deploy fingerprint: bind a live instance to its source revision
    if not ok:
        response.status_code = 503
    return {"ok": ok, **checks}


@app.get("/version")
async def version() -> dict:
    """Deploy fingerprint — binds this running instance to the exact source commit it was
    built from, so release verification can confirm the live env matches the tested SHA."""
    return {"build": HR_BUILD_SHA}




# ── Traces read API (the Traces app reads from ABS; per-org prefix + inverted-ts = O(page)) ──
_TRACE_CARD_FIELDS = ("session_id", "title", "user_prompt", "status", "model", "backend",
                      "event_count", "elapsed", "finished_at", "trace_blob", "result",
                      "member_id", "harness_id", "harness_name", "last_response_id", "workspace",
                      "credits", "usage")


@app.get("/v1/traces")
async def list_traces(request: Request, org: str, limit: int = 20, cursor: str = "",
                      member: str = "", harness: str = "",
                      workspace: str = "", workspace_default: int = 0) -> dict:
    """Paginated, newest-first session cards for an org. Optional `member` + `harness` + `workspace`
    filters give per-user / per-harness / per-workspace isolation, served from dedicated narrow
    indexes so `limit` returns exactly that slice regardless of org volume. `workspace_default=1`
    marks the filter as the org's Default Workspace: legacy cards written before workspace stamping
    (no `workspace` field) belong to it, so the flat index is used and unstamped cards pass."""
    p = await _principal(request)
    if (p.get("org") or "") != org:
        raise HTTPException(403, "trace access is limited to your organization")
    return await _session_cards(org, limit, cursor, member, harness,
                                workspace=workspace, ws_default=bool(workspace_default))


async def _session_cards(org: str, limit: int, cursor: str, member: str, harness: str,
                         workspace: str = "", ws_default: bool = False) -> dict:
    # Pick the NARROWEST index prefix the filter allows, so the LIST returns exactly that slice —
    # newest-first, `limit` per page, with a real continuation cursor. No org-wide scan, no in-memory
    # post-filter: `limit=k` yields k for the slice (not k mixed across the org whittled to a few), and
    # a session-less harness costs one empty LIST. Harness wins when both are set (the tighter slice);
    # leftover member/workspace filters are applied per-card below. A Default-Workspace filter reads
    # the flat index (unstamped legacy cards belong to the default and have no idxw mirror).
    if harness:
        prefix = f"{org}/idxh/{_idx_seg(harness)}/"
    elif workspace and not ws_default:
        prefix = f"{org}/idxw/{_idx_seg(workspace)}/"
    elif member:
        prefix = f"{org}/idxm/{_idx_seg(member)}/"
    else:
        prefix = f"{org}/idx/"
    lst = await _blob_list(prefix, limit=limit, cursor=cursor or None)

    async def _card(item: dict):
        b = await _blob_get(item["file_id"], kb=TRACE_KB)
        if not b:
            return None
        try:
            m = json.loads(b)
        except Exception:  # noqa: BLE001
            return None
        if member and (m.get("member_id") or "") != member:
            return None
        if harness and (m.get("harness_id") or "") != harness:
            return None
        if workspace:
            mw = str(m.get("workspace") or "")
            if mw != workspace and not (ws_default and not mw):
                return None
        return {k: m.get(k) for k in _TRACE_CARD_FIELDS}

    cards = [c for c in await asyncio.gather(*[_card(it) for it in lst.get("items", [])]) if c]
    return {"sessions": cards, "cursor": lst.get("cursor") or ""}


def _prefix_from_vertex(sid: str, v: dict | None) -> str | None:
    """The session's trace prefix. Prefer the stored trace_blob, but RECONSTRUCT the deterministic
    '{tenant}/{created_at_inv}_{sid}' when trace_blob is missing/blank — so a blank value (e.g. left
    by a delete tombstone, then the session resumed) never silently disables the session's trace.
    The prefix is a pure function of (tenant, created_at_inv, sid), all durable on the vertex."""
    if not v:
        return None
    tb = (v.get("trace_blob") or "").strip()
    if tb:
        return tb
    inv = str(v.get("created_at_inv") or "").strip()
    ten = str(v.get("tenant") or "").strip()
    return f"{ten}/{inv}_{sid}" if (inv and ten) else None


async def _trace_base(sid: str) -> str | None:
    return _prefix_from_vertex(sid, await _vertex_get(sid))


# ── /v1/sessions — the PUBLIC session-management surface (HRP-007) ─────────────────
# API-key (or internal-header) callers manage their runs without insider knowledge:
# list newest-first, inspect one, cancel a running one. Cards come from the same
# manifest store the Workbench Recents uses, so every surface agrees.
@app.get("/v1/sessions")
async def list_sessions(request: Request, limit: int = 20, cursor: str = "",
                        harness: str = "", member: str = "") -> dict:
    p = await _principal(request)
    org = p.get("org", "")
    if not org:
        raise HTTPException(400, "no org resolved for this principal")
    harness = harness or str(request.headers.get("x-harness-id") or "")
    # A workspace-scoped principal (workspace-stamped API key, or the console's workspace header)
    # sees only its workspace's sessions; unscoped principals keep the whole-org view.
    return await _session_cards(org, limit, cursor, member, harness,
                                workspace=str(p.get("workspace") or ""),
                                ws_default=bool(p.get("workspace_default")))


async def _owned_session(request: Request, sid: str) -> tuple[str, dict]:
    p = await _principal(request)
    org = p.get("org", "")
    v = await _vertex_get(sid)
    if not v or str(v.get("tenant") or "") != org or str(v.get("status")) == "deleted":
        raise uhp_error(404, "session_not_found", "No session with that id.", "session_id")
    return org, v


@app.get("/v1/sessions/{sid}")
async def session_detail(sid: str, request: Request) -> dict:
    """Durable session detail: vertex state merged with the manifest card fields
    (title, model, event_count, last_response_id, result)."""
    org, v = await _owned_session(request, sid)
    out = {"session_id": sid,
           **{k: val for k, val in v.items() if k not in ("id", "pk", "label")}}
    base = _prefix_from_vertex(sid, v)
    if base:
        mb = await _blob_get(_manifest_key(base), kb=TRACE_KB)
        if mb:
            try:
                m = json.loads(mb)
                for k in _TRACE_CARD_FIELDS:
                    out.setdefault(k, m.get(k))
            except Exception:  # noqa: BLE001
                pass
    return out


async def _turn_cancelled(sid: str, org: str, resp_id: str, *, check_store: bool = True) -> bool:
    """THE cancellation check for a running turn — one signal, two tiers, no graph read:
      • `_cancel_req[sid]`   in-process flag — instant for a same-replica Stop.
      • per-response latch   durable + cross-replica; gated by `check_store` so the poll loop can
                             bound store reads (it only consults the store every Nth poll).
    _stop_session sets BOTH for every cancel (session- or response-level), resolving the running
    resp_id from the vertex (stamped at accept), so a cancel on ANY replica lands here without a
    per-poll vertex read.

    Consolidation trade-off (accepted): during a CONTROL-STORE OUTAGE, a CROSS-replica cancel that
    lands in the warmup window (before the runner CLI exists, so the direct sandbox kill can't apply
    either) is not observed until the turn's hard wall-clock cap. This is a narrow conjunction, the
    store is HA + surfaced on /readyz, and the alternative (keeping a redundant graph-status read)
    is the exact divergent second mechanism this consolidation removes. Mid-turn with the store
    healthy, cross-replica cancels still land two independent ways (direct sandbox kill + the latch)."""
    if sid in _cancel_req:
        return True
    if check_store and control_store.enabled() and await control_store.resp_is_cancelled(org, resp_id):
        return True
    return False


@app.post("/v1/sessions/{sid}/cancel")
async def cancel_session(sid: str, request: Request) -> dict:
    """Stop a running turn: kill the CLI process in the sandbox (via the persisted
    runner_turn_id, so any replica can do it), mark the session cancelled in the
    vertex + manifest, and broadcast a terminal event so open Workbenches settle."""
    org, v = await _owned_session(request, sid)
    # A follow-up turn leaves the PREVIOUS turn's terminal turn_status on the vertex until the
    # new turn's first upsert — so check BOTH fields for a live turn, else Stop during warmup
    # of turn N+1 reads turn N's "done" and refuses ("no running turn") while the CLI spins up.
    live = {"running", "starting"} & {str(v.get("turn_status") or ""), str(v.get("status") or "")}
    if not live:
        return {"session_id": sid, "status": str(v.get("status") or ""), "cancelled": False,
                "detail": "no running turn"}
    killed, rid = await _stop_session(org, sid, v)
    return {"session_id": sid, "status": "cancelled", "cancelled": True, "runner_killed": killed}


async def _stop_session(org: str, sid: str, v: dict, rid_hint: str = "") -> tuple[bool, str]:
    """Terminally stop the session's live turn: kill the runner CLI, latch the
    session cancelled in the vertex/manifest/response record, and broadcast so open
    Workbenches settle. Shared by the session- and response-level cancel endpoints
    so both propagate to the runner identically (HR-INF-013)."""
    # Flag FIRST: a same-replica turn task (even one still provisioning its sandbox) aborts at
    # its next checkpoint instead of un-cancelling the session with a later "running" upsert.
    _cancel_req[sid] = time.time()
    # Resolve the running turn's response id (HR-INF-010): rid_hint (cancel_response), else the
    # DURABLE running_response_id on the vertex (survives cross-replica — this is what lets us drop
    # the turn loop's per-poll vertex-status read), else the in-memory trace as a same-replica hint.
    rid = (rid_hint or str(v.get("running_response_id") or "")
           or str((_session_trace.get(sid) or {}).get("last_response_id") or ""))
    # Durable per-RESPONSE monotonic terminal (HR-INF-013): a one-way latch keyed on resp_id — NOT
    # the session status (a new turn reuses the sid and must be able to go running again). This is
    # THE cancellation signal a running turn observes (via resp_is_cancelled), on any replica.
    if rid and control_store.enabled():
        try:
            await control_store.resp_mark_terminal(org, rid, "cancelled", int(_GW_MAX_TURN_S))
        except Exception:  # noqa: BLE001
            pass
    # runner_turn_id is cleared at each turn's start, so a non-empty value here is THIS turn's
    # live CLI process. During startup it's empty — skip the sandbox call entirely (it would
    # block on the mid-provision sandbox); the flag/vertex checks stop the turn instead.
    rt = str(v.get("runner_turn_id") or "")
    killed = False
    if rt:
        try:
            await _sandbox_json(f"/turn/{rt}/cancel", sid, "POST", attempts=2)
            killed = True
        except Exception:  # noqa: BLE001
            killed = False   # sandbox may be gone already; still mark terminal below
    await _vertex_upsert(sid, {"status": "cancelled", "turn_status": "cancelled"})
    base = _prefix_from_vertex(sid, v)
    if base:
        mb = await _blob_get(_manifest_key(base), kb=TRACE_KB)
        if mb:
            try:
                m = json.loads(mb)
                m["status"] = "cancelled"
                await _index_manifest(base, m)
            except Exception:  # noqa: BLE001
                pass
    # Mark the stored response record terminal too — /turns reads THIS status, and a record left
    # at running/in_progress kept hydrating the conversation as "Working…" forever after refresh
    # even though the session card already said Cancelled.
    if rid:
        try:
            rec = await _resp_get(rid)
            if rec and str(rec.get("status") or "") in ("running", "in_progress", "queued", "starting"):
                rec["status"] = "cancelled"
                await _blob_put(f"responses/{rid}.json", json.dumps(rec, default=str).encode(), kb=RESP_BLOB_KB)
                await _vg_upsert("HarnessResponse", rid, {"status": "cancelled"})
        except Exception:  # noqa: BLE001
            pass
    _bus_publish(org, str(v.get("harness_id") or ""), str(v.get("member_id") or ""), sid, rid,
                 {"type": "response.failed", "reason": "cancelled",
                  "response": {"id": rid, "status": "cancelled",
                               "metadata": {"session_id": sid}}})
    return killed, rid


@app.get("/v1/traces/{sid}")
async def get_trace(sid: str, request: Request) -> dict:
    """One session's manifest (card + chunk index) from ABS."""
    await _owned_session(request, sid)
    base = await _trace_base(sid)
    if not base:
        raise HTTPException(404, "trace not found")
    b = await _blob_get(_manifest_key(base), kb=TRACE_KB)
    if not b:
        raise HTTPException(404, "trace manifest not found")
    return json.loads(b)


@app.get("/v1/traces/{sid}/events")
async def get_trace_events(sid: str, request: Request, chunk: int = 0) -> Response:
    """Raw events.jsonl for one chunk (stream-json, one event/line incl _ts + parent_tool_use_id)."""
    await _owned_session(request, sid)
    base = await _trace_base(sid)
    if not base:
        raise HTTPException(404, "trace not found")
    listed = await _blob_list_all(f"{base}/events/", kb=TRACE_KB)
    keys = sorted(it["file_id"] for it in listed
                  if str(it.get("file_id") or "").endswith(".jsonl"))
    if chunk >= len(keys):
        raise HTTPException(404, "trace chunk not found")
    b = await _blob_get(keys[chunk], kb=TRACE_KB)
    if b is None:
        raise HTTPException(404, "trace chunk not found")
    return Response(content=b, media_type="application/x-ndjson")


@app.get("/v1/traces/{sid}/all")
async def get_trace_all(sid: str, request: Request, compact: int = 0) -> Response:
    """ALL events for a session in ONE response.

    compact=1 (the viewer default): serve the pre-clipped transcript — long strings truncated so a
    30 MB long-horizon trace ships as a few hundred KB. The viewer lazy-loads full event content
    (compact=0) only when an event is opened. Finished traces are one blob read; otherwise chunks
    are read in PARALLEL, concatenated, and cached (both full + compact) for the next load."""
    await _owned_session(request, sid)
    base = await _trace_base(sid)
    if not base:
        raise HTTPException(404, "trace not found")
    media = "application/x-ndjson"
    # The consolidated all.jsonl / all.compact.jsonl caches are built LAZILY here on the first read
    # of a FINALIZED session (finalize only invalidates them). While a turn is running the join path
    # below serves live chunks; the cache is consulted only when the manifest says terminal.
    mb0 = await _blob_get(_manifest_key(base), kb=TRACE_KB)
    status = ""
    finished_at = None
    if mb0:
        try:
            _m0 = json.loads(mb0) or {}
            status = str(_m0.get("status") or "").lower()
            finished_at = _m0.get("finished_at")
        except Exception:  # noqa: BLE001
            status = ""
    finalized = status in _SESSION_TERMINAL
    # Lazy read-cache (HR-INF-015): finalize no longer consolidates on every turn's tail (it also
    # DELETES any stale cache, so a cache blob present here is authoritative for the finished
    # transcript). Serve it when present; otherwise join the chunks below and, for a FINALIZED
    # session, write the cache once — so consolidation cost is paid at most once per session, on
    # first view, never on the turn's critical path.
    if finalized:
        if compact:
            pre = await _blob_get(f"{base}/all.compact.jsonl", kb=TRACE_KB)
            if pre is not None:
                return Response(content=pre, media_type=media)
        else:
            consolidated = await _blob_get(f"{base}/all.jsonl", kb=TRACE_KB)
            if consolidated is not None:
                return Response(content=consolidated, media_type=media)
    # ONE join path for running AND finished sessions: LIST the actual events/ blobs (the manifest's
    # chunk list is written at finalize, so mid-run it's empty — trusting it would freeze the view).
    # Chunk keys are time-ordered, so a lexical sort == chronological order.
    listed = await _blob_list_all(f"{base}/events/", kb=TRACE_KB)
    chunk_ids = sorted(it["file_id"] for it in listed if it.get("file_id"))
    if not chunk_ids:  # fall back to the manifest's count (covers any listing hiccup)
        n = 0
        mb = await _blob_get(_manifest_key(base), kb=TRACE_KB)
        if mb:
            try:
                n = len(json.loads(mb).get("chunks") or [])
            except Exception:  # noqa: BLE001
                n = 0
        chunk_ids = [f"{base}/events/{i:06d}.jsonl" for i in range(max(n, 1))]
    parts = await asyncio.gather(*[_blob_get(cid, kb=TRACE_KB) for cid in chunk_ids])
    body = b"".join(p for p in parts if p)
    if finalized and body and all(p is not None for p in parts):
        # Cache ONLY a provably-complete join (a transient chunk-get failure must never become a
        # permanently-truncated authoritative transcript): every chunk fetched, and — when every
        # key carries its count suffix — the joined line count matches the suffix sum exactly.
        counts = [_chunk_event_count(c) for c in chunk_ids]
        complete = all(c is not None for c in counts) and body.count(b"\n") == sum(counts) \
            if counts and all(c is not None for c in counts) else True
        # Close the fast-follow-up race: a NEW turn may have started (and its finalize invalidated
        # the caches) while we joined. Re-read the manifest — cache only if the session is STILL
        # terminal with the same finished_at we started from.
        if complete:
            try:
                mb1 = await _blob_get(_manifest_key(base), kb=TRACE_KB)
                m1 = json.loads(mb1) if mb1 else {}
                if str(m1.get("status") or "").lower() in _SESSION_TERMINAL and m1.get("finished_at") == finished_at:
                    await _trace_put(f"{base}/all.jsonl", body)
                    await _trace_put(f"{base}/all.compact.jsonl", _compact_ndjson(body))
            except Exception:  # noqa: BLE001
                pass
    if compact and body:
        return Response(content=_compact_ndjson(body), media_type=media)
    return Response(content=body, media_type=media)


@app.delete("/v1/traces/{sid}")
async def delete_trace(sid: str, request: Request) -> dict:
    """Delete a whole conversation (session): its trace manifest + event chunks, its durable
    workspace tarball, and tombstone the session vertex. This is what the Workbench Recents
    'delete' uses — removing the card AND the underlying session workspace."""
    await _owned_session(request, sid)
    base = await _trace_base(sid)
    # 1) trace manifest + event chunks (drives the Recents/Traces list)
    if base:
        manifest = {}
        try:
            mb = await _blob_get(_manifest_key(base), kb=TRACE_KB)
            manifest = json.loads(mb) if mb else {}
        except Exception:  # noqa: BLE001
            manifest = {}
        chunks = manifest.get("chunks") or []
        for ch in chunks:
            await _blob_delete(f"{base}/{ch}", kb=TRACE_KB)
        # belt-and-suspenders: sweep ALL remaining event blobs under the prefix (follow the cursor —
        # a truncated sweep left most objects behind on long sessions, HR-INF-020).
        for it in await _blob_list_all(f"{base}/events/", kb=TRACE_KB):
            await _blob_delete(it["file_id"], kb=TRACE_KB)
        # the consolidated transcript caches were LEAKED by delete before (never in `chunks`)
        await _blob_delete(f"{base}/all.jsonl", kb=TRACE_KB)
        await _blob_delete(f"{base}/all.compact.jsonl", kb=TRACE_KB)
        # remove the flat index AND the per-harness/per-member mirrors (harness/member from the
        # manifest we just read; falls back to a bare flat-key delete if the manifest was unreadable)
        await _deindex_manifest(base, manifest)
    # 2) durable session workspace tarball
    await _blob_delete(_ws_blob(sid), kb=BLOB_KB)
    # 3) tombstone the session vertex + drop in-process state
    try:
        # Mark deleted but DON'T blank trace_blob — a blank prefix silently disables the trace if the
        # session is later resumed (the prefix is deterministic from created_at_inv anyway).
        await _vg_upsert("HarnessSession", sid, {"status": "deleted"})
    except Exception:  # noqa: BLE001
        pass
    _session_trace.pop(sid, None)
    return {"id": sid, "object": "session", "deleted": True}


# ── connection admin (org admins manage their own provider connections) ──────────
class ConnBody(BaseModel):
    backend: str
    provider: str
    model: str | None = None
    base_url: str | None = None
    region: str | None = None
    api_key: str | None = None
    aws_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_bearer_token: str | None = None
    gcp_project: str | None = None
    gcp_region: str | None = None
    gcp_sa_json: str | None = None
    wire_api: str | None = None


@app.put("/v1/orgs/{org}/connections/{name}", dependencies=[Depends(_internal_only)])
async def put_connection(org: str, name: str, body: ConnBody) -> dict:
    conn = {"name": name, **{k: v for k, v in body.model_dump().items() if v is not None}}
    await _vault_put(org, f"harness-conn-{name}", json.dumps(conn))
    return {"ok": True, "org": org, "connection": _conn_public(conn)}


# ── Integrations admin (token-provider routing console) ──────────────────────────────
# Platform-org only for now (the config is GLOBAL — it decides which provider serves each
# model for every harness). Identity comes from the verified login JWT (_principal), not
# self-asserted headers. Customer BYOK later = same schema written to the org tenant.
# Orgs allowed to administer provider integrations. Self-hosted runs single-tenant, so this is
# empty by default and every caller is refused; a hosted deployment sets HR_INTEGRATIONS_ADMIN_ORGS
# (comma-separated) to its own admin org. Never hardcode a deployment's org id here.
_INTEGRATIONS_ADMIN_ORGS = {o.strip() for o in
                            os.environ.get("HR_INTEGRATIONS_ADMIN_ORGS", "").split(",") if o.strip()}
_SECRET_SENTINEL = "__secret__"


async def _require_integrations_admin(request: Request) -> dict:
    p = await _principal(request)
    # Self-hosted (identity off) is single-tenant: the one operator IS the administrator, and
    # bringing your own key is the whole point of running it yourself. Requiring an allow-list
    # there would lock the owner out of their own box.
    if HR_IDENTITY_MODE == "off":
        return p
    if (p.get("org") or "") not in _INTEGRATIONS_ADMIN_ORGS:
        raise HTTPException(403, "not available for this organization")
    return p


# ── provider catalog ─────────────────────────────────────────────────────────────────
# What we already know about each vendor, so adding an integration asks for a key and nothing
# else. A base_url we can look up ourselves is not a question worth putting to a user, and a
# wrong answer there is a broken integration they can't debug.
#
# `base_url` present  -> fixed, applied automatically and never asked for.
# `base_url` None     -> genuinely per-deployment (an Azure resource, an AWS region), so it IS
#                        asked for, with `fields` naming exactly what to ask.
_PROVIDER_CATALOG: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "fields": [],
        "secret": "api_key",
        "secret_label": "API Key",
        "key_hint": "sk-ant-…",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "fields": [],
        "secret": "api_key",
        "secret_label": "API Key",
        "key_hint": "sk-…",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "fields": [],
        "secret": "api_key",
        "secret_label": "API Key",
        "key_hint": "sk-or-…",
    },
    "tokenrouter": {
        "label": "TokenRouter",
        "base_url": "https://api.tokenrouter.com/v1",
        "fields": [],
        "secret": "api_key",
        "secret_label": "API Key",
    },
    "azure-foundry": {
        "label": "Azure OpenAI",
        "base_url": None,          # one resource per customer — there is no default to know
        "fields": [{"key": "base_url", "label": "Endpoint URL",
                    "placeholder": "https://<resource>.openai.azure.com/openai/v1"}],
        "secret": "api_key",
        "secret_label": "API Key",
    },
    "bedrock": {
        "label": "AWS Bedrock",
        "base_url": None,          # region-addressed, not a URL
        "fields": [{"key": "aws_region", "label": "AWS Region", "placeholder": "us-east-1"}],
        "secret": "aws_bearer_token",
        "secret_label": "API Key (bearer token)",
    },
}


# Runner-side provider names differ from the integration console's names for the same vendor;
# this is the ONE place that reconciles them, so every lookup below goes through one table.
_RUNNER_VENDOR = {"azure": "azure-foundry", "openai-api": "openai"}


def _vendor_models(provider: str) -> dict[str, str]:
    """The {canonical: vendor id} table for a provider, by either of its names. Empty when we
    have no table for that vendor — callers must decide explicitly what that means."""
    p = (provider or "").lower()
    return _VENDOR_MODELS.get(_RUNNER_VENDOR.get(p, p), {})


def _provider_model_id(provider: str, canonical: str) -> str | None:
    """This vendor's own id for a canonical model, or None when it does not serve it.

    A pure table lookup, deliberately: anything cleverer (name heuristics, family guessing) has
    to decide what to do about a model it doesn't recognise, and every such answer is a guess.
    Not listed means not served."""
    return _vendor_models(provider).get(canonical)


def _provider_backends(provider: str) -> list[str]:
    """Runner backends that can carry this vendor (which agent CLI can drive it)."""
    return sorted({b for (p, b) in _INTEGRATION_WIRING if p == provider})


def _provider_catalog_public() -> list[dict]:
    """The catalog the console renders its Add-Integration form from."""
    return [{"id": pid,
             "label": meta["label"],
             "base_url": meta["base_url"],
             "fields": meta["fields"],
             "secret": meta["secret"],
             "secret_label": meta["secret_label"],
             "key_hint": meta.get("key_hint", ""),
             "models": [{"canonical": c, "provider_id": v}
                        for c, v in _VENDOR_MODELS.get(pid, {}).items()],
             "backends": _provider_backends(pid)}
            for pid, meta in _PROVIDER_CATALOG.items()]


def _integration_public(integ: dict) -> dict:
    """Integration as the console should see it: secrets replaced by a sentinel (never round-trip
    a secret), and `models` resolved to everything this integration actually serves — the stored
    field holds overrides only, which would read as "one model" for an integration serving thirty.
    """
    cfg = dict(integ.get("config") or {})
    for k in _INTEGRATION_SECRET_FIELDS:
        if cfg.get(k):
            cfg[k] = _SECRET_SENTINEL
    return {**integ, "config": cfg,
            "models": [{"canonical": c, "provider_id": v}
                       for c, v in _integration_models(integ).items()],
            "image_models": [{"canonical": c, "provider_id": v}
                             for c, v in _integration_image_models(integ).items()]}


@app.get("/v1/admin/integrations")
async def admin_integrations_get(request: Request) -> dict:
    await _require_integrations_admin(request)
    return {"integrations": [_integration_public(i) for i in await _integrations_doc()],
            "model_map": await _effective_model_map(),
            "image_model_map": await _effective_image_model_map(),
            "providers": sorted({p for p, _ in _INTEGRATION_WIRING}),
            "catalog": _provider_catalog_public()}


class IntegrationsBody(BaseModel):
    integrations: list[dict]
    model_map: dict
    # Optional: a console that predates image routing still saves without wiping the image map.
    # Absent means "leave it alone", which is not the same as an empty dict meaning "clear it".
    image_model_map: dict | None = None


@app.put("/v1/admin/integrations")
async def admin_integrations_put(body: IntegrationsBody, request: Request) -> dict:
    await _require_integrations_admin(request)
    stored = {str(i.get("name") or ""): i for i in await _integrations_doc()}
    out: list[dict] = []
    for i in body.integrations:
        name = str(i.get("name") or "").strip()
        provider = str(i.get("provider") or "").lower()
        if not name or provider not in {p for p, _ in _INTEGRATION_WIRING}:
            raise HTTPException(400, f"integration needs a name and a known provider (got '{provider}')")
        cfg = {k: v for k, v in (i.get("config") or {}).items() if v not in (None, "")}
        # The client never sees secrets (sentinel) — carry stored values through unchanged edits.
        prior_cfg = (stored.get(name) or {}).get("config") or {}
        for k in _INTEGRATION_SECRET_FIELDS:
            if cfg.get(k) == _SECRET_SENTINEL:
                if not prior_cfg.get(k):
                    raise HTTPException(400, f"integration '{name}': missing {k}")
                cfg[k] = prior_cfg[k]
        # A provider whose endpoint we know supplies its own base_url. Asking the user for a
        # value we can look up is a question with exactly one right answer and many wrong ones.
        known_base = (_PROVIDER_CATALOG.get(provider) or {}).get("base_url")
        if known_base and not cfg.get("base_url"):
            cfg["base_url"] = known_base
        # Store ONLY what the source table doesn't already say: an id this instance overrides
        # (a custom deployment name, say). Everything else is derived on read by
        # _integration_models, so the catalog in source stays the single source of truth and a
        # release that adds models reaches existing integrations without anyone re-saving.
        # Persisting the derived list instead is what made this list go stale — and worse, a
        # model later retired from the table would live on forever in whatever was written here.
        table = _vendor_models(provider)
        models = [{"canonical": c, "provider_id": pid}
                  for c, pid in ((str(m.get("canonical") or "").strip(),
                                  str(m.get("provider_id") or "").strip())
                                 for m in (i.get("models") or []))
                  if c and pid and table.get(c) != pid]
        out.append({"name": name, "provider": provider, "config": cfg, "models": models})
    names = {i["name"] for i in out}
    if len(names) != len(out):
        raise HTTPException(400, "integration names must be unique")
    mm = {str(k).strip(): str(v).strip() for k, v in (body.model_map or {}).items()
          if str(k).strip() and str(v).strip()}
    for model, iname in mm.items():
        if iname not in names:
            raise HTTPException(400, f"model '{model}' maps to unknown integration '{iname}'")
    imm = None
    if body.image_model_map is not None:
        imm = {str(k).strip(): str(v).strip() for k, v in body.image_model_map.items()
               if str(k).strip() and str(v).strip()}
        for model, iname in imm.items():
            if iname not in names:
                raise HTTPException(400, f"image model '{model}' maps to unknown integration '{iname}'")
    # Only EXPLICIT routes are stored. Claiming every servable model here is what froze the map:
    # a model added to the source table afterwards had no entry and read as "no provider", while
    # the console showed a full list and no way to tell anything was missing. _effective_model_map
    # does the claiming on read instead, so a key added today serves a model shipped tomorrow.
    #
    # This write REPLACES the whole document, which is what the console needs (it always sends
    # the full list) and is exactly how a careless caller destroys every integration in one
    # request — a mistake with no undo, because the API keys inside are never readable again.
    # So the previous document is kept before every write. One generation is enough: it turns an
    # "everything is gone" into a "restore the last one", which is the whole difference.
    prior = await _vault_get(GLOBAL_TENANT, _INTEGRATIONS_KEY)
    if prior:
        await _vault_put(GLOBAL_TENANT, _INTEGRATIONS_PREV_KEY, prior)
        prior_mm = await _vault_get(GLOBAL_TENANT, _MODEL_MAP_KEY)
        await _vault_put(GLOBAL_TENANT, _MODEL_MAP_PREV_KEY, prior_mm or "{}")
        prior_imm = await _vault_get(GLOBAL_TENANT, _IMAGE_MODEL_MAP_KEY)
        await _vault_put(GLOBAL_TENANT, _IMAGE_MODEL_MAP_PREV_KEY, prior_imm or "{}")
    await _vault_put(GLOBAL_TENANT, _INTEGRATIONS_KEY, json.dumps(out))
    await _vault_put(GLOBAL_TENANT, _MODEL_MAP_KEY, json.dumps(mm))
    if imm is not None:
        await _vault_put(GLOBAL_TENANT, _IMAGE_MODEL_MAP_KEY, json.dumps(imm))
    # Answer with what will actually route, not with what was just filed away — the two differ by
    # every model claimed on read, and the console renders this straight into the picker.
    return {"ok": True, "integrations": [_integration_public(i) for i in out],
            "model_map": await _effective_model_map(),
            "image_model_map": await _effective_image_model_map()}


@app.post("/v1/admin/integrations/restore")
async def admin_integrations_restore(request: Request) -> dict:
    """Put back the document as it was before the last write, and keep the current one as the
    new previous — so an accidental restore is itself undoable."""
    await _require_integrations_admin(request)
    prev = await _vault_get(GLOBAL_TENANT, _INTEGRATIONS_PREV_KEY)
    if not prev:
        raise HTTPException(404, "no previous version to restore")
    prev_mm = await _vault_get(GLOBAL_TENANT, _MODEL_MAP_PREV_KEY) or "{}"
    cur = await _vault_get(GLOBAL_TENANT, _INTEGRATIONS_KEY) or "[]"
    cur_mm = await _vault_get(GLOBAL_TENANT, _MODEL_MAP_KEY) or "{}"
    await _vault_put(GLOBAL_TENANT, _INTEGRATIONS_KEY, prev)
    await _vault_put(GLOBAL_TENANT, _MODEL_MAP_KEY, prev_mm)
    await _vault_put(GLOBAL_TENANT, _INTEGRATIONS_PREV_KEY, cur)
    await _vault_put(GLOBAL_TENANT, _MODEL_MAP_PREV_KEY, cur_mm)
    return {"ok": True, "integrations": [_integration_public(i) for i in json.loads(prev)],
            "model_map": json.loads(prev_mm)}


@app.get("/v1/orgs/{org}/connections/{name}", dependencies=[Depends(_internal_only)])
async def get_connection_meta(org: str, name: str) -> dict:
    conn, src = await _get_connection(org, name)
    if not conn:
        raise HTTPException(404, "connection not found")
    return {"connection": _conn_public(conn), "source_tenant": src}


class PolicyBody(BaseModel):
    connections: list[str]


@app.put("/v1/orgs/{org}/policy/{backend}", dependencies=[Depends(_internal_only)])
async def put_policy(org: str, backend: str, body: PolicyBody) -> dict:
    await _vault_put(org, f"harness-policy-{backend}", json.dumps(body.connections))
    return {"ok": True, "org": org, "backend": backend, "chain": body.connections}


# ════════════════════════════════════════════════════════════════════════════════════
# OpenAI Responses-compatible surface (/v1/responses …). Wire-compatible per the design in
# backend openapi.yaml + example_stream.http: an unmodified OpenAI SDK can point its base_url
# at  https://<gw>/v1  and work. Statefulness via previous_response_id (resolved against our own
# VG store). Agent progress (thinking/tool calls/tool output) maps ONTO native event types only.
# ════════════════════════════════════════════════════════════════════════════════════

def _rid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


async def _vg_upsert(label: str, vid: str, props: dict, *, raise_on_fail: bool = False) -> None:
    """Generic coalesce-upsert for any VG vertex label (HarnessResponse / HarnessApiKey).
    Best-effort by default; VG is closed-world on labels so an unregistered label silently no-ops.
    raise_on_fail=True (the API-KEY mint/revoke path): a swallowed failure would make a revoke
    silently revert or a shown-once key permanently 401, so surface it as a 502 to the caller."""
    try:
        await BACKING.graph.upsert(label, vid, props, raise_on_fail=raise_on_fail)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        if raise_on_fail:
            raise HTTPException(502, "graph write failed") from e


async def _vg_edge(label: str, from_id: str, to_id: str) -> None:
    """Idempotent edge create between two existing vertices (HR tenant), using the proven
    seed form addE().from(V(a)).to(V(b)) with a deterministic edge id (uuid5 of a|label|b)
    so a re-run can't duplicate. Both endpoints must exist or the addE no-ops. Best-effort."""
    await BACKING.graph.add_edge(label, from_id, to_id)


def _org_uid(org: str) -> str:
    """Shadow Account vertex id (HR tenant) — mirrors the frontend/seed convention acct.<org_id>."""
    return "acct." + org


# ── canonical (claude stream-json) → ordered (kind, payload) blocks ──────────────────
def _blocks_from_canonical(ev: dict) -> list[tuple[str, object]]:
    t = ev.get("type")
    out: list[tuple[str, object]] = []
    if t == "assistant":
        content = (ev.get("message") or {}).get("content")
        for c in (content if isinstance(content, list) else []):
            if not isinstance(c, dict):
                continue
            ct = c.get("type")
            if ct == "text" and c.get("text"):
                out.append(("text", c["text"]))
            elif ct == "thinking" and c.get("thinking"):
                out.append(("reasoning", c["thinking"]))
            elif ct == "tool_use":
                out.append(("tool_use", {"id": c.get("id") or _rid("call"),
                                         "name": c.get("name") or "tool",
                                         "input": c.get("input") if c.get("input") is not None else {}}))
    elif t == "user":
        # A trace-injected user-prompt event stores content as a plain STRING (the prompt itself);
        # only tool_result block LISTS translate to output. Guard both shapes — iterating a string
        # here crashed feed() and silently killed the cross-replica live tail on its first line.
        content = (ev.get("message") or {}).get("content")
        for c in (content if isinstance(content, list) else []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_result":
                content = c.get("content")
                if isinstance(content, list):
                    content = "\n".join((x.get("text", "") if isinstance(x, dict) else str(x)) for x in content)
                out.append(("tool_result", {"call_id": c.get("tool_use_id") or "",
                                            "output": str(content if content is not None else ""),
                                            "is_error": bool(c.get("is_error"))}))
    elif t == "result":
        out.append(("result", {"text": ev.get("result") or "", "usage": ev.get("usage"),
                               "is_error": bool(ev.get("is_error"))}))
    elif t == "system" and ev.get("subtype") == "resume_lost":
        # The runner asked to continue a prior session, but it wasn't found in this sandbox — it
        # silently started fresh instead (see harness_runner _run_hermes_bg). A caller who believed
        # this was a continuation has no other way to learn the context was actually dropped, so
        # surface it as a short, honest note rather than let the reply look like a real continuation.
        out.append(("text", "_Note: couldn't resume the prior session in this sandbox — "
                            "continuing as a new session, without earlier context._\n\n"))
    return out


class _RespTranslator:
    """Feed canonical blocks → native Responses SSE events; also assembles the final output[] +
    usage so the non-streaming path and the stored record reuse the same assembly. sequence_number
    is monotonic across the whole stream; each output item gets its own increasing output_index."""

    def __init__(self, resp_id: str, model: str, prev: str | None, store: bool, created_at: float, sid: str = ""):
        self.resp_id, self.model, self.prev, self.store, self.created_at = resp_id, model, prev, store, created_at
        self.sid = sid   # surfaced in response.metadata so the client can highlight/track the session
        # run metadata (CT-124): the model the caller asked for, and whether the gateway substituted
        # the harness's authorized default because the request was unavailable for this backend.
        self.requested_model = ""
        self.model_fallback = False
        self.fallback_reason = ""
        self.seq = 0
        self.out_index = -1
        self.output: list[dict] = []
        self.usage: dict | None = None
        self.error: dict | None = None
        self.cur: dict | None = None
        self.any_text = False

    def _ev(self, type_: str, **f) -> dict:
        e = {"type": type_, "sequence_number": self.seq, **f}
        self.seq += 1
        return e

    def _response_obj(self, status: str) -> dict:
        meta: dict = {}
        if self.sid:
            meta["session_id"] = self.sid
        # run metadata: expose the effective vs requested model + fallback, so a caller can see the
        # gateway ran a different (authorized) model than it asked for.
        if self.requested_model and self.requested_model != self.model:
            meta["requested_model"] = self.requested_model
        if self.model_fallback:
            meta["model_fallback"] = True
            if self.fallback_reason:
                meta["model_fallback_reason"] = self.fallback_reason
        return {"id": self.resp_id, "object": "response", "created_at": int(self.created_at),
                "status": status, "error": self.error, "incomplete_details": None,
                "previous_response_id": self.prev, "model": self.model,
                "output": self.output, "store": self.store, "usage": self.usage,
                "metadata": meta}

    def start(self) -> list[dict]:
        snap = {**self._response_obj("in_progress"), "output": []}
        return [self._ev("response.created", response=snap),
                self._ev("response.in_progress", response=snap)]

    def _close_cur(self) -> list[dict]:
        if not self.cur:
            return []
        evs: list[dict] = []
        c = self.cur
        if c["kind"] == "reasoning":
            part = {"type": "summary_text", "text": c["text"]}
            item = {"id": c["id"], "type": "reasoning", "summary": [part] if c["text"] else [],
                    "status": "completed"}
            evs.append(self._ev("response.reasoning_summary_part.done", item_id=c["id"],
                                output_index=c["oi"], summary_index=0, part=part))
            evs.append(self._ev("response.output_item.done", output_index=c["oi"], item=item))
            self.output.append(item)
        elif c["kind"] == "message":
            ann = c.get("annotations") or []
            part = {"type": "output_text", "text": c["text"], "annotations": ann}
            item = {"id": c["id"], "type": "message", "status": "completed", "role": "assistant",
                    "content": [part]}
            for i, a in enumerate(ann):
                evs.append(self._ev("response.output_text.annotation.added", item_id=c["id"],
                                    output_index=c["oi"], content_index=0, annotation_index=i, annotation=a))
            evs.append(self._ev("response.output_text.done", item_id=c["id"], output_index=c["oi"],
                                content_index=0, text=c["text"]))
            evs.append(self._ev("response.content_part.done", item_id=c["id"], output_index=c["oi"],
                                content_index=0, part=part))
            evs.append(self._ev("response.output_item.done", output_index=c["oi"], item=item))
            self.output.append(item)
        self.cur = None
        return evs

    def _open_reasoning(self) -> list[dict]:
        self.out_index += 1
        rid = _rid("rs")
        self.cur = {"kind": "reasoning", "id": rid, "oi": self.out_index, "text": ""}
        item = {"id": rid, "type": "reasoning", "summary": [], "status": "in_progress"}
        return [self._ev("response.output_item.added", output_index=self.out_index, item=item),
                self._ev("response.reasoning_summary_part.added", item_id=rid, output_index=self.out_index,
                         summary_index=0, part={"type": "summary_text", "text": ""})]

    def _open_message(self) -> list[dict]:
        self.out_index += 1
        mid = _rid("msg")
        self.cur = {"kind": "message", "id": mid, "oi": self.out_index, "text": "", "annotations": []}
        item = {"id": mid, "type": "message", "status": "in_progress", "role": "assistant", "content": []}
        return [self._ev("response.output_item.added", output_index=self.out_index, item=item),
                self._ev("response.content_part.added", item_id=mid, output_index=self.out_index,
                         content_index=0, part={"type": "output_text", "text": "", "annotations": []})]

    def _handle(self, kind: str, payload) -> list[dict]:
        evs: list[dict] = []
        if kind == "reasoning":
            if not self.cur or self.cur["kind"] != "reasoning":
                evs += self._close_cur(); evs += self._open_reasoning()
            self.cur["text"] += payload
            evs.append(self._ev("response.reasoning_summary_text.delta", item_id=self.cur["id"],
                                output_index=self.cur["oi"], summary_index=0, delta=payload))
        elif kind == "text":
            if not self.cur or self.cur["kind"] != "message":
                evs += self._close_cur(); evs += self._open_message()
            self.cur["text"] += payload
            self.any_text = True
            evs.append(self._ev("response.output_text.delta", item_id=self.cur["id"],
                                output_index=self.cur["oi"], content_index=0, delta=payload))
        elif kind == "tool_use":
            evs += self._close_cur()
            self.out_index += 1
            fid = _rid("fc")
            inp = payload["input"]
            args = inp if isinstance(inp, str) else json.dumps(inp, default=str)
            shell = {"id": fid, "type": "function_call", "call_id": payload["id"],
                     "name": payload["name"], "arguments": "", "status": "in_progress"}
            done = {**shell, "arguments": args, "status": "completed"}
            evs.append(self._ev("response.output_item.added", output_index=self.out_index, item=shell))
            evs.append(self._ev("response.function_call_arguments.delta", item_id=fid,
                                output_index=self.out_index, delta=args))
            evs.append(self._ev("response.function_call_arguments.done", item_id=fid,
                                output_index=self.out_index, arguments=args))
            evs.append(self._ev("response.output_item.done", output_index=self.out_index, item=done))
            self.output.append(done)
        elif kind == "tool_result":
            evs += self._close_cur()
            self.out_index += 1
            oid = _rid("fco")
            item = {"id": oid, "type": "function_call_output", "call_id": payload["call_id"],
                    "output": payload["output"], "status": "completed"}
            evs.append(self._ev("response.output_item.added", output_index=self.out_index, item=item))
            evs.append(self._ev("response.output_item.done", output_index=self.out_index, item=item))
            self.output.append(item)
        elif kind == "result":
            u = payload.get("usage")
            if u:
                self.usage = {"input_tokens": u.get("input_tokens", 0),
                              "output_tokens": u.get("output_tokens", 0),
                              "total_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0)}
                # Cache tokens, priced separately as cache_read/write. Accept both the claude CLI's
                # raw names AND the runner's already-normalized cache_read_tokens/cache_write_tokens.
                for src, dst in (("cache_read_input_tokens", "cache_read_tokens"),
                                 ("cache_read_tokens", "cache_read_tokens"),
                                 ("cache_creation_input_tokens", "cache_write_tokens"),
                                 ("cache_write_tokens", "cache_write_tokens")):
                    if u.get(src):
                        self.usage[dst] = u[src]
            if not self.any_text and payload.get("text"):
                evs += self._handle("text", payload["text"])
        return evs

    def feed(self, ev: dict) -> list[dict]:
        out: list[dict] = []
        for kind, payload in _blocks_from_canonical(ev):
            out += self._handle(kind, payload)
        return out

    def complete(self, status: str, files: list[dict] | None = None) -> list[dict]:
        evs: list[dict] = []
        if files:
            if not (self.cur and self.cur["kind"] == "message"):
                evs += self._close_cur()
                evs += self._open_message()
            self.cur["annotations"] = [
                {"type": "container_file_citation", "container_id": f["container_id"],
                 "file_id": f["file_id"], "filename": f["filename"],
                 "download_url": _file_url(f["container_id"], f["file_id"]),
                 "start_index": 0, "end_index": len(self.cur["text"])} for f in files]
        evs += self._close_cur()
        ev_type = {"completed": "response.completed", "incomplete": "response.incomplete",
                   "failed": "response.failed", "cancelled": "response.failed"}.get(status, "response.completed")
        evs.append(self._ev(ev_type, response=self._response_obj(status)))
        return evs

    def fail(self, message: str) -> list[dict]:
        self.error = {"code": "harness_error", "message": message}
        evs = self._close_cur()
        evs.append(self._ev("error", code="harness_error", message=message, param=None))
        evs.append(self._ev("response.failed", response=self._response_obj("failed")))
        return evs


# ── input parsing (string | array of items with input_text/input_file/input_image) ──────
def _decode_input_file(p: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """→ (filename, base64, media_type, file_id). base64/file_id are mutually exclusive sources."""
    fname = p.get("filename")
    fd = p.get("file_data")
    if isinstance(fd, str) and fd:
        media, b64 = "application/octet-stream", fd
        if fd.startswith("data:"):
            head, _, b64 = fd.partition(",")
            media = head[5:].split(";")[0] or media
        return fname, b64, media, None
    if p.get("file_id"):
        return fname, None, None, p["file_id"]
    return fname, None, None, None


def _parse_input(inp) -> tuple[str, list[dict], list[dict]]:
    """→ (prompt_text, file_specs, normalized_input_items). file_specs carry content_b64 or file_id."""
    if isinstance(inp, str):
        return inp, [], [{"role": "user", "content": inp}]
    texts: list[str] = []
    files: list[dict] = []
    items_norm: list[dict] = []
    for it in (inp or []):
        role = it.get("role", "user")
        content = it.get("content")
        if isinstance(content, str):
            if role in ("user", "developer", "system"):
                texts.append(content)
            items_norm.append({"role": role, "content": content})
            continue
        parts = []
        for p in (content or []):
            pt = p.get("type")
            if pt == "input_text":
                if role in ("user", "developer", "system"):
                    texts.append(p.get("text") or "")
                parts.append({"type": "input_text", "text": p.get("text") or ""})
            elif pt == "input_file":
                fname, b64, media, file_id = _decode_input_file(p)
                # file_id refs survive without an inline filename — the standard
                # OpenAI shape is {"type":"input_file","file_id":...}; the name is
                # recovered from the uploads/{fid}.meta blob at resolution time.
                # Inline file_data still requires a filename (nothing to recover).
                if (fname and b64 is not None) or file_id:
                    files.append({"filename": fname, "content_b64": b64, "file_id": file_id, "media_type": media})
                parts.append({"type": "input_file", "filename": fname, "file_id": file_id})
            elif pt == "input_image":
                parts.append({"type": "input_image", "image_url": p.get("image_url"), "file_id": p.get("file_id")})
        items_norm.append({"role": role, "content": parts})
    return "\n\n".join(t for t in texts if t).strip(), files, items_norm


def _route_backend(model: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit.lower()
    m = (model or "").lower()
    if "hermes" in m:
        return "hermes"
    if any(k in m for k in ("codex", "gpt", "openai", "o3", "o4")):
        return "codex"
    if any(k in m for k in ("claude", "anthropic", "sonnet", "opus", "haiku")):
        return "claude"
    return DEFAULT_BACKEND


# Friendly model name (what the UI shows) -> the provider's actual model id. The catalog names are
# indications; the real id depends on the resolved connection's provider. Bedrock Anthropic uses
# `us.anthropic.claude-<x>` inference-profile ids (verified live); Anthropic-direct uses `claude-<x>`.
_BEDROCK_CLAUDE = {
    "opus-4.8": "us.anthropic.claude-opus-4-8", "opus-4.7": "us.anthropic.claude-opus-4-7",
    "opus-4.6": "us.anthropic.claude-opus-4-6", "opus-4.5": "us.anthropic.claude-opus-4-5",
    "sonnet-4.6": "us.anthropic.claude-sonnet-4-6", "sonnet-4.5": "us.anthropic.claude-sonnet-4-5",
    "opus-5": "us.anthropic.claude-opus-5", "sonnet-5": "us.anthropic.claude-sonnet-5",
    "haiku-4.5": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "fable-5": "us.anthropic.claude-fable-5",
}
_ANTHROPIC_CLAUDE = {
    "opus-4.8": "claude-opus-4-8", "opus-4.7": "claude-opus-4-7", "opus-4.6": "claude-opus-4-6",
    "opus-4.5": "claude-opus-4-5", "sonnet-4.6": "claude-sonnet-4-6", "sonnet-4.5": "claude-sonnet-4-5",
    "opus-5": "claude-opus-5", "sonnet-5": "claude-sonnet-5",
    "haiku-4.5": "claude-haiku-4-5-20251001", "fable-5": "claude-fable-5",
}


# ── what each vendor actually serves ────────────────────────────────────────────────
# EXPLICIT, per vendor: canonical name -> that vendor's own model id. Not derived, not
# inferred from the model's name.
#
# The previous version classified a model by substring ("qwen" -> other family) and let anything
# it couldn't classify through. That fails OPEN, and it did: five models added without a matching
# hint were unclassified, so an OpenAI integration happily claimed to serve Qwen, Kimi and
# Nemotron. A vendor now serves exactly what is written here and nothing else — an unlisted model
# is unavailable, and adding one is a deliberate line in this table.
#
# Sources: Anthropic's models overview and AWS's Bedrock model cards for the claude ids;
# developers.openai.com model pages for the gpt ids; OpenRouter's live /v1/models for the
# vendor/slug forms. TokenRouter mirrors OpenRouter's slugs.
_VENDOR_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {
        "claude-opus-5":     "claude-opus-5",
        "claude-fable-5":    "claude-fable-5",
        "claude-opus-4.8":   "claude-opus-4-8",
        "claude-sonnet-5":   "claude-sonnet-5",
        "claude-opus-4.7":   "claude-opus-4-7",
        "claude-sonnet-4.6": "claude-sonnet-4-6",
        "claude-haiku-4.5":  "claude-haiku-4-5-20251001",
    },
    "bedrock": {
        "claude-opus-5":     "us.anthropic.claude-opus-5",
        "claude-fable-5":    "us.anthropic.claude-fable-5",
        "claude-opus-4.8":   "us.anthropic.claude-opus-4-8",
        "claude-sonnet-5":   "us.anthropic.claude-sonnet-5",
        "claude-opus-4.7":   "us.anthropic.claude-opus-4-7",
        "claude-sonnet-4.6": "us.anthropic.claude-sonnet-4-6",
        "claude-haiku-4.5":  "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    },
    "openai": {
        "gpt-5.6-sol":   "gpt-5.6-sol",
        "gpt-5.6-terra": "gpt-5.6-terra",
        "gpt-5.6-luna":  "gpt-5.6-luna",
        "gpt-5.5":       "gpt-5.5",
        "gpt-5.4":       "gpt-5.4",
        "gpt-5.4-mini":  "gpt-5.4-mini",
        "gpt-5.2":       "gpt-5.2",
        "gpt-5.3-codex": "gpt-5.3-codex",
    },
    "azure-foundry": {
        "gpt-5.6-sol":   "gpt-5.6-sol",
        "gpt-5.6-terra": "gpt-5.6-terra",
        "gpt-5.6-luna":  "gpt-5.6-luna",
        "gpt-5.5":       "gpt-5.5",
        "gpt-5.4":       "gpt-5.4",
        "gpt-5.4-mini":  "gpt-5.4-mini",
        "gpt-5.2":       "gpt-5.2",
        "gpt-5.3-codex": "gpt-5.3-codex",
    },
    "openrouter": {
        "gpt-5.6-sol":        "openai/gpt-5.6-sol",
        "gpt-5.6-terra":      "openai/gpt-5.6-terra",
        "gpt-5.6-luna":       "openai/gpt-5.6-luna",
        "gpt-5.5":            "openai/gpt-5.5",
        "gpt-5.4":            "openai/gpt-5.4",
        "gpt-5.4-mini":       "openai/gpt-5.4-mini",
        "gpt-5.2":            "openai/gpt-5.2",
        "gpt-5.3-codex":      "openai/gpt-5.3-codex",
        "claude-opus-5":      "anthropic/claude-opus-5",
        "claude-fable-5":     "anthropic/claude-fable-5",
        "claude-opus-4.8":    "anthropic/claude-opus-4.8",
        "claude-sonnet-5":    "anthropic/claude-sonnet-5",
        "claude-opus-4.7":    "anthropic/claude-opus-4.7",
        "claude-sonnet-4.6":  "anthropic/claude-sonnet-4.6",
        "claude-haiku-4.5":   "anthropic/claude-haiku-4.5",
        "gemini-3.6-flash":   "google/gemini-3.6-flash",
        "deepseek-v4-pro":    "deepseek/deepseek-v4-pro",
        "deepseek-v4-flash":  "deepseek/deepseek-v4-flash",
        "kimi-k3":            "moonshotai/kimi-k3",
        "qwen3.7-max":        "qwen/qwen3.7-max",
        "qwen3.8-max":        "qwen/qwen3.8-max",
        "kimi-k2.7-code":     "moonshotai/kimi-k2.7-code",
        "mistral-medium-3.5": "mistralai/mistral-medium-3-5",
        "step-3.7-flash":     "stepfun/step-3.7-flash",
        "minimax-m3":         "minimax/minimax-m3",
        "nemotron-3-ultra":   "nvidia/nemotron-3-ultra-550b-a55b",
        "hunyuan-3":          "tencent/hy3",
        "ling-3.0-flash":     "inclusionai/ling-3.0-flash",
        "qwen3.7-flash":      "qwen/qwen3.7-flash",
    },
}

# TokenRouter speaks OpenRouter's slugs, so it starts from that table rather than a second copy
# that would drift. It is not the same catalogue though: an aggregator only serves what it has an
# upstream channel for, and for these it answers
#   HTTP 503: No available channel for model <slug> under group default
# which surfaces as a model that appears in the picker and then fails on send. Listing a model a
# vendor cannot actually reach is the same broken promise as listing one that doesn't exist, so
# it comes off THIS vendor's list — not out of the catalog, because OpenRouter still serves them
# and a user who brings an OpenRouter key should get them.
#
# Verified by calling each one on a TokenRouter connection (2026-08-10). Re-check before adding
# back: channels come and go on an aggregator, which is exactly why this lives next to the table
# and not in someone's memory.
# glm-5.2 is NOT here and is not in the catalog: the provider serves it correctly (a direct call
# returns "ok" in 2.2s, streams cleanly, and honours function tools), but hermes 0.19.0 hangs
# after receiving the response — no output, no error, until the turn is stopped. That is a CLI
# defect, not an availability one, so it is recorded here rather than as a missing channel.
# Re-test with a newer hermes before adding it back.
_TOKENROUTER_NO_CHANNEL = {
    "minimax-m3", "nemotron-3-ultra", "hunyuan-3", "ling-3.0-flash", "qwen3.7-flash",
}
# Image models, kept OUT of _VENDOR_MODELS on purpose: those tables feed the chat model pickers
# and the per-backend catalogs, and an image model offered as a chat model is a broken choice a
# user can make. Canonical → provider id, same shape, resolved by _image_auth only.
_IMAGE_VENDOR_MODELS: dict[str, dict[str, str]] = {
    "openai": {"gpt-image-1": "gpt-image-1", "gpt-image-1-mini": "gpt-image-1-mini"},
    "azure":  {"gpt-image-1": "gpt-image-1"},
    "azure-foundry": {"gpt-image-1": "gpt-image-1"},
}


_VENDOR_MODELS["tokenrouter"] = {c: v for c, v in _VENDOR_MODELS["openrouter"].items()
                                 if c not in _TOKENROUTER_NO_CHANNEL}

# The chain path (_map_model) maps aggregator ids from the same table.
_AGGREGATOR_SLUGS = _VENDOR_MODELS["openrouter"]




def _map_model(conn: dict, friendly: str) -> str | None:
    """Map a friendly model name to the connection provider's real id.

    Must NEVER emit an id the provider will reject: an unmappable name (e.g. the bare backend name
    'claude' the client sends when no model is selected) would otherwise reach Bedrock verbatim and
    400 with 'invalid model identifier', failing the whole turn. So an unmappable/empty name falls
    back to the connection's configured default, then the provider's sonnet id — always something valid."""
    backend = (conn.get("backend") or "").lower()
    provider = (conn.get("provider") or "").lower()
    default = conn.get("model") or ""

    def _valid_default() -> str | None:
        # a connection default is only useful if it's a real id, not the bare backend name
        return default if default and default.lower() not in ("claude", "anthropic", "bedrock") else None

    # One lookup for every vendor we have a table for: canonical -> that vendor's own id.
    table = _vendor_models(provider)
    if friendly and friendly in table:
        return table[friendly]
    if backend == "claude" or (backend == "hermes" and provider in ("anthropic", "bedrock")):
        # Older claude ids the catalog no longer lists still map, and a caller may pass a
        # provider-native id directly; _LEGACY_CLAUDE_IDS carries both, keyed bare (opus-4.5).
        legacy = _BEDROCK_CLAUDE if provider == "bedrock" else _ANTHROPIC_CLAUDE
        if friendly:
            key = friendly[len("claude-"):] if friendly.startswith("claude-") else friendly
            mapped = legacy.get(friendly) or legacy.get(key)
            if mapped:
                return mapped
            # already a provider-native id (bedrock inference-profile / direct claude-<x>-<date>)? keep it.
            if provider == "bedrock" and friendly.startswith(("us.", "eu.", "apac.", "anthropic.", "arn:")):
                return friendly
            if provider == "anthropic" and friendly.startswith("claude-") and friendly != "claude":
                return friendly
        # empty or unmappable -> a guaranteed-valid id (connection default, else provider sonnet)
        return _valid_default() or legacy.get("sonnet-4.6") or (default or None)
    # Aggregators: an id already in vendor/slug form isn't a canonical and passes through.
    # Direct gpt vendors: the deployment/model name is used as-is.
    return friendly or (default or None)


# ── model catalog + per-harness policy (CT-124) ─────────────────────────────────────────
# The curated models each backend serves (mirrors the console harness catalog). This is the
# authoritative allowed set for server-side permission validation: a request for a model outside
# the harness's backend family is NOT run — the harness's authorized fallback (its default) runs
# instead, and the substitution is recorded in the response's run metadata so it is auditable.
_MODEL_CATALOG: dict[str, dict] = {
    # THE BAR FOR ADDING A MODEL, both halves required:
    #   1. It is a chat model the agent loop can drive — text in, text out, and tool calling.
    #      Image/video generators, embedders and safety classifiers are not candidates however
    #      capable: picking one produces a task that dies at the first tool call. Vision input is
    #      welcome, so a VLM qualifies; a model that only EMITS pixels does not. Enforced by
    #      tests/test_model_catalog_capabilities.py against the live capability data.
    #   2. A real turn on the harness that will run it, completed against the live provider,
    #      CHECKED FOR SUBSTITUTION. An unauthorized model is silently replaced by the harness
    #      default and the run records `requested_model` next to it — so a probe that only reads
    #      "completed" measures the default. Nine models once "passed" a file-writing test that
    #      was claude-sonnet-4.6 writing the file nine times, because the probe named a harness
    #      id that did not exist and every turn fell back to the claude default.
    # Neither half substitutes for the other, and being listed by an aggregator is not either of
    # them: minimax-m3, nemotron-3-ultra, hunyuan-3, ling-3.0-flash and qwen3.7-flash are all real
    # tool-using chat models, all published in OpenRouter's catalog with correct modalities, and
    # all answered "HTTP 503: No available channel for model X under group default" when actually
    # called. A slug in a catalog is an advertisement; a channel behind it is the product.
    #
    # Do not trim this list on taste either — "too many open-weight models" is a UI problem, and
    # removing a model that runs takes it out of the user's hands for a cosmetic reason.
    #
    # Probe-verified against the live provider before listing (2026-07-19:
    # gpt-5.6 sol/terra/luna + gpt-5.2 deployed on the Azure resource and probed OK;
    # claude additions probed through the Bedrock path).
    "codex":  {"default": "gpt-5.4",
               "models": ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
                          "gpt-5.4", "gpt-5.4-mini", "gpt-5.2",
                          # Codex-optimized line (separate from the general one; 5.3-codex is
                          # OpenAI's most capable agentic coding model, there is no 5.6-codex).
                          "gpt-5.3-codex"]},
    # claude-opus-5 is now wired in both _ANTHROPIC_CLAUDE and _BEDROCK_CLAUDE (ids read off
    # Anthropic's models overview and AWS's own model card), so it routes directly instead of
    # falling through to the unmapped default it used at launch.
    "claude": {"default": "claude-sonnet-4.6",
               "models": ["claude-opus-5", "claude-fable-5", "claude-opus-4.8", "claude-sonnet-5",
                          "claude-opus-4.7", "claude-sonnet-4.6", "claude-haiku-4.5"]},
    # hermes (NousResearch hermes-agent) is multi-family — it runs any frontier model through
    # the matching provider connection (family-aware chain selection in _resp_execute). Friendly
    # names are shared with the codex/claude catalogs, so pricing/billing metrics stay identical
    # (2026-07-21: gpt-5.5 via azure-foundry + opus-4.8/haiku-4.5 via Bedrock probe-verified
    # through the hermes CLI).
    "hermes": {"default": "gpt-5.4",
               "models": ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
                          "gpt-5.4", "gpt-5.4-mini", "gpt-5.2",
                          "gpt-5.3-codex",
                          "claude-opus-5", "claude-fable-5", "claude-opus-4.8", "claude-sonnet-5",
                          "claude-opus-4.7", "claude-sonnet-4.6", "claude-haiku-4.5",
                          # frontier US+China set, served via the TokenRouter/OpenRouter
                          # integrations (2026-07-22: each probe-verified through the hermes
                          # CLI on the TokenRouter connection)
                          "gemini-3.6-flash", "deepseek-v4-pro", "deepseek-v4-flash", "kimi-k3",
                          "qwen3.7-max", "qwen3.8-max", "kimi-k2.7-code",
                          "mistral-medium-3.5", "step-3.7-flash", "minimax-m3",
                          "nemotron-3-ultra", "hunyuan-3", "ling-3.0-flash",
                          "qwen3.7-flash"]},
}
_BARE_MODELS = {"", "claude", "codex", "anthropic", "bedrock", "openai", "hermes"}
# Union of BOTH tables' values — a dict merge would drop the bedrock ids (shared keys, anthropic
# values win), silently rejecting the us.anthropic.* ids this set exists to allow.
_PROVIDER_CLAUDE_IDS = {v.lower() for v in [*_BEDROCK_CLAUDE.values(), *_ANTHROPIC_CLAUDE.values()]}


def _conn_serves(conn: dict, friendly: str) -> bool:
    """Whether this connection's vendor actually serves the requested model.

    Table membership, not a name heuristic. The heuristic this replaces classified models by
    substring and treated "unrecognised" as "fine" — so every model whose family nobody had
    added a hint for was served by whatever connection came first, which is how an OpenAI
    connection ended up claiming Qwen and Nemotron.

    A vendor we have no table for cannot be filtered at all; that is stated here rather than
    happening by accident, and it is NOT the path the model catalog uses (see
    _provider_model_id, which is a pure lookup and refuses anything unlisted)."""
    table = _vendor_models(conn.get("provider") or "")
    if not table:
        return True
    m = (friendly or "").strip()
    if not m:
        return True                      # no model requested: the connection default decides
    return m in table or m in table.values()


def _backend_of_harness(hv: dict | None) -> str:
    """The backend a harness is pinned to, from its base. Empty when unknown (caller-inferred)."""
    base = str((hv or {}).get("base") or "").lower()
    if base == "codex":
        return "codex"
    if base in ("claude-code", "claude"):
        return "claude"
    if base == "hermes":
        return "hermes"
    return ""


def _model_authorized(requested: str, backend: str) -> bool:
    r = (requested or "").strip().lower()
    if not r:
        return False
    if r in {m.lower() for m in _MODEL_CATALOG.get(backend, {}).get("models", [])}:
        return True
    if backend in ("claude", "hermes") and r in _PROVIDER_CLAUDE_IDS:
        return True   # power users may pass a provider-native claude id (claude-opus-4-8 / us.anthropic...)
    if backend in ("codex", "hermes") and r.startswith("gpt-"):
        return True   # gpt-* family; Azure deployment names vary
    return False


def _harness_model_default(hv: dict | None, backend: str) -> str:
    return str((hv or {}).get("default_model") or _MODEL_CATALOG.get(backend, {}).get("default") or "")


def _resolve_model_policy(requested: str, hv: dict | None, backend: str) -> tuple[str, str, bool, str]:
    """Server-side model permission for a turn. Returns (effective, requested, fallback?, reason).
    Empty/bare request -> the harness default (not a fallback). An unauthorized model is replaced by
    the authorized fallback (the harness default) and flagged."""
    default = _harness_model_default(hv, backend)
    req = (requested or "").strip()
    if not req or req.lower() in _BARE_MODELS:
        return default, req, False, ""
    if _model_authorized(req, backend):
        return req, req, False, ""
    return default, req, True, (f"model '{req}' is not available for this harness's backend "
                                f"'{backend}'; used the authorized default '{default}'")


async def _servable_models(org: str | None, backend: str) -> set[str] | None:
    """Canonical models something can actually run on this backend.

    None means "no restriction": a policy chain exists, and a chain's connections are
    provider-level rather than per-model, so the backend can attempt its whole catalog.

    Otherwise the only thing that can serve a turn is a model→integration mapping, so the
    answer is exactly those canonicals whose integration's provider is wired to this backend.
    Offering a model nothing can serve is a promise the router then breaks — the picker would
    accept it and the turn would fail at the point of no return."""
    if await _resolve_chain(org, backend, None):
        return None
    integrations = {str(i.get("name") or ""): i for i in await _integrations_doc()}
    servable: set[str] = set()
    for canonical, iname in (await _effective_model_map()).items():
        integ = integrations.get(iname)
        if not integ:
            continue
        if _INTEGRATION_WIRING.get((str(integ.get("provider") or "").lower(), backend)):
            servable.add(canonical)
    return servable


def _harness_models_view(hv: dict | None, backend: str, servable: set[str] | None = None) -> dict:
    """The per-harness model capability view: allowed models, default, and authorized fallback.
    `servable` (from _servable_models) marks the ones a provider is actually configured for."""
    cat = _MODEL_CATALOG.get(backend, {})
    default = _harness_model_default(hv, backend)
    curated = cat.get("models", [])
    ok = (lambda m: True) if servable is None else (lambda m: m in servable)
    models = [{"id": m, "label": m, "backend": backend, "available": ok(m), "default": m == default}
              for m in curated]
    if default and default not in curated:   # a custom default outside the curated list
        models.insert(0, {"id": default, "label": default, "backend": backend,
                          "available": ok(default), "default": True})
    return {"backend": backend, "default": default, "fallback": default, "models": models}


# ── response record store (blob = source of truth; VG vertex = index/fallback) ──────────
async def _resp_put(rid: str, stored: dict, org: str, sid: str, prev: str | None,
                    status: str, created_at: float, store: bool) -> None:
    try:
        await _blob_put(f"responses/{rid}.json", json.dumps(stored, default=str).encode(), kb=RESP_BLOB_KB)
    except Exception:  # noqa: BLE001
        pass
    await _vg_upsert("HarnessResponse", rid, {"org": org, "session_id": sid,
                     "previous_response_id": prev or "", "status": status,
                     "created_at": str(created_at), "store": "1" if store else "0"})


async def _resp_get(rid: str) -> dict | None:
    b = await _blob_get(f"responses/{rid}.json", kb=RESP_BLOB_KB)
    if not b:
        return None
    try:
        rec = json.loads(b)
    except Exception:  # noqa: BLE001
        return None
    return None if rec.get("_deleted") else rec


def _strip_internal(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


# Harness-internal seed/config files the runner writes into the workspace to drive the agent
# (e.g. AGENTS.md surfaces installed skills for codex; CLAUDE.md is the claude equivalent). They are
# never user-facing artifacts, so they must never appear in a turn's output file list.
_OUTPUT_EXCLUDE_NAMES = {"AGENTS.md", "CLAUDE.md"}


def _is_internal_output(name: str) -> bool:
    return name in _OUTPUT_EXCLUDE_NAMES or name.startswith(".harness/") or "/.harness/" in name


# ── output (container) file collection: produced-this-turn files → blobs + citations ────
async def _collect_produced(sid: str, exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    try:
        r = await _sandbox("/produced", sid, "GET")
        if r.status_code >= 400:
            return []
        items = (r.json() or {}).get("files") or []
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for it in items[:RESP_MAX_FILES]:
        path = (it or {}).get("path")
        if not path:
            continue
        rel = path.lstrip("./")
        if rel in exclude or _is_internal_output(rel):
            continue
        try:
            fr = await _sandbox("/file", sid, "GET", params={"path": path})
            if fr.status_code >= 400 or not fr.content or len(fr.content) > RESP_MAX_FILE_BYTES:
                continue
            cfile = _rid("cfile")
            media = fr.headers.get("content-type", "application/octet-stream")
            fname = path.lstrip("./")
            if await _blob_put(f"containers/{sid}/{cfile}", fr.content, kb=RESP_BLOB_KB):
                await _blob_put(f"containers/{sid}/{cfile}.meta",
                                json.dumps({"filename": fname, "media_type": media}).encode(), kb=RESP_BLOB_KB)
                out.append({"container_id": sid, "file_id": cfile, "filename": fname, "bytes": len(fr.content)})
        except Exception:  # noqa: BLE001
            continue
    return out


# ── session resolution (previous_response_id → reuse prior session for continuity) ──────
async def _resp_resolve_session(org: str, member: str, prev: str | None, backend_hint: str,
                                harness_id: str = "", harness_name: str = "",
                                session_hint: str = "", workspace: str = "") -> tuple[str, str | None]:
    # Continue an existing conversation by (1) the response-id chain, or (2) an explicit session id.
    # (2) is the robust path: the client always knows which conversation it's in, so a follow-up never
    # forks a new empty session just because previous_response_id was momentarily unavailable.
    async def _continue(sid: str, v: dict | None) -> tuple[str, str | None]:
        tr = _session_trace.setdefault(sid, {"prefix": None, "org": org, "since": 0, "chunk": 0, "count": 0})
        tr["member"], tr["harness_id"], tr["harness_name"] = member, harness_id, harness_name
        # Workspace sticks to the session: the vertex's stamp wins (set at creation/backfill);
        # the caller's workspace only fills the gap for pre-stamping sessions.
        tr["workspace"] = str((v or {}).get("workspace") or "") or tr.get("workspace") or workspace or ""
        if not tr.get("prefix"):
            vv = v or await _vertex_get(sid)
            tr["prefix"] = _prefix_from_vertex(sid, vv)
            # Self-heal: if trace_blob was blank (e.g. a stale delete tombstone) but we rebuilt the
            # prefix from created_at_inv, re-persist it so the vertex is consistent again.
            if tr.get("prefix") and not (vv or {}).get("trace_blob"):
                await _vertex_upsert(sid, {"trace_blob": tr["prefix"], "status": "running"})
        # Follow-up: append after the prior turns' event chunks (never overwrite from chunk 0).
        await _recover_trace_cursor(tr)
        resume = (v or await _vertex_get(sid) or {}).get("cli_session_id") or None
        return sid, resume
    if prev:
        rec = await _resp_get(prev)
        sid = (rec or {}).get("_session_id")
        if sid:
            # Same cross-tenant guard as session_hint below: a leaked/stored response id of another
            # org's session must not let a caller continue (and re-bill/re-stamp) that session —
            # fall through and start a fresh session in the caller's own org instead.
            v = await _vertex_get(sid)
            if v and str(v.get("tenant") or "") == org:
                return await _continue(sid, v)
    if session_hint:
        v = await _vertex_get(session_hint)
        if v and str(v.get("tenant") or "") == org:   # exists + belongs to this org (no cross-tenant continue)
            return await _continue(session_hint, v)
    sid = "hsess" + uuid.uuid4().hex
    created = time.time()
    inv = _inv_ts(created)
    trace_prefix = f"{org}/{inv}_{sid}"
    _session_trace[sid] = {"prefix": trace_prefix, "org": org, "since": 0, "chunk": 0, "count": 0,
                           "member": member, "harness_id": harness_id, "harness_name": harness_name,
                           "workspace": workspace or ""}
    room = await _brain_mint_room(sid)   # persisted on the vertex (brain_room) below — the durable copy
    await _vertex_upsert(sid, {"tenant": org, "member_id": member or "", "backend": backend_hint,
                               "conv_id": "", "status": "created", "created_at": str(created),
                               "created_at_inv": inv, "trace_blob": trace_prefix, "brain_room": room or "",
                               "harness_id": harness_id or "", "harness_name": harness_name or "",
                               "workspace": workspace or ""})
    # Stamp the ownership/usage topology: Account OWNS HarnessSession USES Harness (HR tenant).
    # Account vertex is upserted by org provisioning; coalesce so a missing endpoint just no-ops.
    await _vg_edge("OWNS", _org_uid(org), sid)
    if harness_id:
        await _vg_edge("USES", sid, harness_id)
    return sid, None


async def _resp_execute(translator: _RespTranslator, *, org: str, member: str, sid: str,
                        backend: str, chain: list[str], prompt: str, files_in: list[dict],
                        resume: str | None, emit, model_req: str = "", user_text: str = "",
                        harness_id: str = "", max_step: int = 40,
                        timeout_s: int | None = None,
                        hdr_vals: dict[str, str] | None = None,
                        partial_messages: bool = False,
                        codex_appserver: bool = False,
                        hv: dict | None = None) -> tuple[str, list[dict], dict]:
    """Hydrate → run turn over the connection chain → translate events to `emit` → collect produced
    files → checkpoint + persist trace. Returns (status, produced_files, rec).
    model_req: the caller-selected model (honored over the connection default when provided)."""
    rec = {"sid": sid, "tenant": org, "backend": backend, "started": time.time(),
           "prompt": prompt, "user_text": user_text,   # raw user message — card titles use THIS,
           "model": model_req or translator.model, "tried": [], "status": "starting"}
    #        never the runtime prompt with its file-note/instructions prepends
    tr = _session_trace.setdefault(sid, {"prefix": None, "org": org, "since": 0, "chunk": 0, "count": 0})
    if not tr.get("prefix"):
        tr["prefix"] = _prefix_from_vertex(sid, await _vertex_get(sid))
    await _recover_trace_cursor(tr)      # append after prior turns (never overwrite); safe if same-replica
    # Re-persist a healed/known prefix so the vertex never stays blank (the cause of silent 0-event traces).
    # runner_turn_id is cleared: until THIS turn starts a CLI process there is nothing to kill,
    # and a stale id from the last turn would make cancel_session block on a dead handle. The
    # Stop flag is NOT cleared here — the POST handler already cleared stale ones at accept
    # time, so any flag present now targets THIS turn and must survive to the checkpoints.
    # running_response_id is stamped once at accept (create_response) — it lets a cross-replica
    # cancel_session resolve THIS turn's resp_id and latch the per-response cancel (the ONE cancel
    # mechanism), so the turn loop needs no per-poll vertex status read (HR-INF-010). Not re-written
    # here: accept already set it to this same resp_id and nothing clears it.
    await _vertex_upsert(sid, {"status": "running", "turn_status": "starting",
                               "heartbeat": str(time.time()), "runner_turn_id": "",
                               **({"trace_blob": tr["prefix"]} if tr.get("prefix") else {})})
    # Session execution lease (HR-INF-012), acquired BEFORE hydrate — hydrate wipes /workspace, so
    # an overlapping turn is the real corruption risk. observe mode only LOGS a conflict; enforce
    # rejects it. rec carries the fence for heartbeat renewal + the checkpoint backstop.
    rec["lease_fence"] = 0
    if LEASE_MODE != "off" and control_store.enabled():
        try:
            _adm = await control_store.lease_admit(
                org, sid, translator.resp_id, LEASE_TTL_S,
                reject_on_conflict=(LEASE_MODE == "enforce"), fresh_s=LEASE_FRESH_S)
            rec["lease_fence"] = _adm.get("fence", 0)
            if _adm.get("conflict"):
                print(f"[lease] conflict sid={sid} mode={LEASE_MODE} holder={_adm.get('holder')} "
                      f"rejected={_adm.get('rejected')} fence={_adm.get('fence')} resp={translator.resp_id}",
                      flush=True)
            if _adm.get("rejected"):
                # enforce: another turn actively owns this session. Refuse WITHOUT hydrating
                # (hydrate would wipe the live workspace). The incumbent keeps running; we did NOT
                # take the fence. Return "failed" with the reason in `tried` — the caller's
                # status=="failed" path emits the single terminal event (no double-emit here).
                rec["status"] = "failed"
                rec["tried"] = [{"error": "a turn is already in progress for this session"}]
                return "failed", [], rec
        except Exception:  # noqa: BLE001 — lease is best-effort; never block a turn on it
            pass
    await _hydrate(sid, rec)
    # Capture the USER's message as the first trace event of this turn — the runner's
    # stream only carries agent/tool/result, never the prompt, so without this the
    # Traces timeline has no user turn. flatten.js renders type:'user' as a User row.
    if tr.get("prefix") and (user_text or "").strip():
        await _trace_flush(tr, {"events": [{"type": "user",
            "message": {"content": user_text}, "_ts": time.time()}]})
    # Write the session card NOW (status running) so a new chat shows up in Recents/Traces the moment
    # it starts — not only after the turn finalizes. _trace_finalize overwrites this at the end.
    if tr.get("prefix"):
        try:
            await _write_running_card(tr, sid=sid, org=org, member=member, harness_id=harness_id,
                                       backend=backend, model=model_req or translator.model or "",
                                       user_text=user_text or "")
        except Exception:  # noqa: BLE001
            pass
    # Resolve the harness's enabled MCP servers + skills (vault token refs resolved here), plus the
    # built-in skill names / tool names the harness disabled (the runner skips mounting them).
    # HR-INF-010: the caller (create_response) already read this harness's vertex — thread it in
    # instead of re-reading it twice more here. Beyond cutting reads, a same-request snapshot means
    # _harness_plugins and agent_doc can't observe a mid-turn config edit inconsistently.
    mcp_servers, skills, skills_suppressed, tools_disabled = await _harness_plugins(harness_id, org, hdr_vals, hv=hv)
    if mcp_servers or skills or skills_suppressed or tools_disabled:
        rec["plugins"] = {"mcp": [m.get("name") for m in mcp_servers], "skills": [s.get("name") for s in skills],
                          "skills_off": skills_suppressed, "tools_off": tools_disabled}
    # The harness's configured instructions are the agent's CLAUDE.md (claude) / AGENTS.md (codex) —
    # written into the workspace by the runner, NOT injected as a system prompt. The model keeps the
    # CLI's default system prompt; persistent project instructions live in the doc the agent reads.
    agent_doc = str((hv or {}).get("system_prompt") or "")
    status = "failed"
    # Model→integration mapping (global token-provider routing): a mapped model runs on its
    # integration FIRST; the backend's policy chain stays as the failure fallback.
    mapped_conn = await _mapped_integration_conn(backend, model_req)
    candidates: list[tuple[str, dict | None]] = ([(mapped_conn["name"], mapped_conn)] if mapped_conn else [])
    candidates += [(n, None) for n in chain]
    # Independent of which chat connection wins below: images are usually a different provider.
    image_auth = await _image_auth(sid, backend)
    for name, pre in candidates:
        conn, src = (pre, "integration") if pre is not None else await _get_connection(org, name)
        if not conn:
            rec["tried"].append({"connection": name, "error": "not found"})
            continue
        # An explicit model→integration mapping already asserts this connection serves the model
        # (validated against the integration's model list at save time) — the family heuristic
        # reads the RUNNER provider (e.g. openai-api for a TokenRouter aggregator) and would
        # wrongly reject non-gpt families, so it applies to chain connections only.
        if pre is None and not _conn_serves(conn, model_req):
            # Multi-family backend (hermes): this connection's provider can't run the requested
            # model's family — skipping is the honest move (running it would silently substitute
            # the connection's default model).
            rec["tried"].append({"connection": name, "error": f"provider does not serve '{model_req}'"})
            continue
        sandbox_auth = _auth_from_conn(conn, sid)
        if sandbox_auth is None:
            # Refusing beats running: the only alternative is handing the sandbox a real provider
            # key. The chain moves on, and a fully unbrokerable chain fails the turn loudly.
            rec["tried"].append({"connection": name,
                                 "error": "credential cannot be brokered; refused"})
            continue
        body = {"backend": conn.get("backend", backend), "provider": conn.get("provider"),
                "model": (conn.get("model") if conn.get("_model_resolved") else _map_model(conn, model_req)),
                "prompt": prompt, "max_turns": max_step,
                "timeout_seconds": timeout_s,
                "auth": sandbox_auth, "resume_session_id": resume, "files": files_in,
                "mcp_servers": mcp_servers, "skills": skills, "agent_doc": agent_doc,
                "skills_suppressed": skills_suppressed, "tools_disabled": tools_disabled,
                # Image generation, when an integration can serve it. A per-turn credential for
                # the broker, never a provider key — see _image_auth.
                "image_auth": image_auth,
                # idempotency: all _sandbox_json retries of THIS turn share the response id, so a
                # lost/slow first reply that gets retried dedups to the same runner turn (no re-exec).
                "idempotency_key": f"{translator.resp_id}:{name}",
                # token-level streaming (claude): runner adds --include-partial-messages + emits deltas
                "partial_messages": bool(partial_messages),
                # codex streaming: run via the app-server protocol (item/agentMessage/delta)
                "codex_appserver": bool(codex_appserver)}
        # Stop requested while we were resolving the connection / provisioning the previous
        # attempt? Honor it BEFORE launching a CLI process (from any replica, via the one signal).
        if await _turn_cancelled(sid, org, translator.resp_id):
            status = "cancelled"
            rec["status"] = "cancelled"
            await _vertex_upsert(sid, {"status": "cancelled", "turn_status": "cancelled"})
            break
        try:
            started = await _sandbox_json("/turn", sid, body=body)   # retries cold-start / transient empties
        except Exception as e:  # noqa: BLE001
            rec["tried"].append({"connection": name, "tenant": src, "error": str(e)[:200]})
            continue
        rt = started.get("turn_id")
        rec.update(connection=name, runner_turn_id=rt, status="running")
        # runner_turn_id persisted so ANY replica (or a later cancel request) can address
        # the live turn inside the sandbox — it was in-memory-only before, so cancel and
        # cross-replica ops had no handle after the starting replica died.
        # A cancel that raced the sandbox spin-up must NOT be overwritten back to "running" —
        # kill the just-started CLI instead and let the poll loop collect the cancelled status.
        # Register the live turn in the durable control store so a cancel landing on
        # ANOTHER replica (via resp_mark_terminal) is visible to this poll loop.
        if control_store.enabled():
            try:
                await control_store.resp_put_running(org, translator.resp_id, sid, rt or "", int(_GW_MAX_TURN_S))
            except Exception:  # noqa: BLE001
                pass
        if sid in _cancel_req:
            try:
                await _sandbox_json(f"/turn/{rt}/cancel", sid, "POST", attempts=2)
            except Exception:  # noqa: BLE001
                pass
            await _vertex_upsert(sid, {"last_connection": name, "runner_turn_id": rt or ""})
        else:
            await _vertex_upsert(sid, {"status": "running", "turn_status": "running",
                                       "last_connection": name, "runner_turn_id": rt or ""})
        # cursor = durable fetch offset (only advances on an ack'd flush); fed_upto = how far
        # events have been fed to the translator/emit (advances always) so a held-cursor re-fetch
        # after a failed flush re-persists WITHOUT re-emitting duplicate output.
        cursor, fed_upto, terminal, poll_fails, kill_sent, polls = 0, 0, None, 0, False, 0
        while True:
            await asyncio.sleep(RESP_POLL_S)
            polls += 1
            # Heartbeat-renew the session lease so a long turn's lease never expires and gets
            # stolen by a follow-up (which would wipe this live workspace). Best-effort.
            if (rec.get("lease_fence") and control_store.enabled()
                    and polls % LEASE_RENEW_EVERY == 0):
                try:
                    await control_store.lease_renew(org, sid, translator.resp_id,
                                                    rec["lease_fence"], LEASE_TTL_S)
                except Exception:  # noqa: BLE001
                    pass
            # Renew the vertex heartbeat too, so the reconcile sweep sees a long turn as live (its
            # fresh-heartbeat fast path applies) instead of re-scanning trace chunks every cycle.
            if polls % LEASE_RENEW_EVERY == 0:
                try:
                    await _vertex_upsert(sid, {"heartbeat": str(time.time())})
                except Exception:  # noqa: BLE001
                    pass
            # Stop observed mid-turn (bypasses cancel_session's own sandbox call when that raced
            # startup). The durable per-response latch is consulted every 10th poll so a cancel on
            # any replica lands; the in-process flag is instant for a same-replica Stop.
            if not kill_sent and await _turn_cancelled(sid, org, translator.resp_id,
                                                        check_store=(polls % 10 == 0)):
                kill_sent = True
                try:
                    await _sandbox_json(f"/turn/{rt}/cancel", sid, "POST", attempts=2)
                except Exception:  # noqa: BLE001
                    terminal = "cancelled"   # sandbox unreachable — settle the turn terminally anyway
                    break
            try:
                s = await _sandbox_json(f"/turn/{rt}", sid, "GET", params={"since": cursor}, attempts=3, base=2.0)
                poll_fails = 0
            except Exception as e:  # noqa: BLE001
                # a transient poll hiccup must not abort a live turn — only give up after a run
                poll_fails += 1
                if poll_fails >= 5:
                    rec["tried"].append({"connection": name, "error": f"poll: {str(e)[:150]}"})
                    break
                continue
            new = s.get("events") or []
            n_total = s.get("n_total", cursor)
            flush_ok = True
            if new:
                flush_ok = await _trace_flush(tr, {"events": new, "n_total": n_total})
            # Feed/emit ONLY the slice not already fed — so a held-cursor re-fetch (after a failed
            # flush) re-persists the events without re-emitting them into the response/stream.
            if new and n_total > fed_upto:
                skip = fed_upto - cursor if fed_upto > cursor else 0
                for cev in new[skip:]:
                    for oev in translator.feed(cev):
                        await emit(oev)
                fed_upto = n_total
            # HR-INF-014: advance the DURABLE fetch cursor only once the events are acknowledged.
            # On a failed flush we hold it so the next poll re-fetches and re-persists them (the
            # durable trace is the authority and must not lose events). No events → advance.
            if flush_ok or not new:
                if new and flush_ok and cursor != n_total and control_store.enabled():
                    # Persist the per-turn harvest cursor so a replica that ADOPTS this turn after we
                    # die resumes at exactly the right sandbox index — no re-flush, no re-emit. Only
                    # on a real advance (new events actually flushed), so it's ≤ once per poll batch.
                    try:
                        await control_store.resp_set_cursor(org, translator.resp_id, int(n_total))
                    except Exception:  # noqa: BLE001 — advisory; adoption falls back to session-count
                        pass
                cursor = n_total
            # Persist the CLI resume id ONLY when it CHANGES (HR-INF-010). The runner echoes
            # session_id on every poll (~1.2s), but it's set once per turn — an unconditional
            # upsert was ~1500 identical writes/turn to the shared partition. This loop is the
            # sole writer of rec["cli_session_id"], so comparing against it is authoritative.
            if s.get("session_id") and s["session_id"] != rec.get("cli_session_id"):
                rec["cli_session_id"] = s["session_id"]
                await _vertex_upsert(sid, {"cli_session_id": s["session_id"]})   # durable resume id
            if s.get("done"):
                st = s.get("status")
                if st == "done":
                    terminal = "completed"
                elif st == "max_turns":
                    terminal = "incomplete"
                elif st in ("cancelled", "timeout"):
                    # user cancel / wall-clock cap end the SESSION's turn — never retry it
                    # on the next connection in the chain (that would re-run the whole task)
                    terminal = "cancelled" if st == "cancelled" else "incomplete"
                    if st == "timeout":
                        rec["tried"].append({"connection": name, "status": st,
                                             "error": "turn hit its wall-clock cap"})
                else:
                    rec["tried"].append({"connection": name, "status": st,
                                         "error": (s.get("result") or s.get("error") or "")[:200]})
                break
        if terminal:
            status = terminal
            rec["status"] = "done" if terminal == "completed" else terminal
            await _vertex_upsert(sid, {"status": rec["status"], "turn_status": rec["status"],
                                       "last_connection": name})
            break
    produced = (await _collect_produced(sid, {f.get("filename", "") for f in files_in})
                if status in ("completed", "incomplete") else [])
    # Persist THIS turn's changed/created files as the session's "latest changed" set so
    # GET /v1/sessions/{sid}/files?changed=true is durable + replica-independent (the live
    # sandbox is gone after the turn). Overwrites each turn = always the most recent run.
    try:
        await _blob_put(f"sessions/{sid}/changed.json", json.dumps({
            "at": time.time(),
            "files": [{"path": f.get("filename"), "file_id": f.get("file_id"),
                       "bytes": f.get("bytes")} for f in produced if f.get("file_id")],
        }).encode(), kb=RESP_BLOB_KB)
    except Exception:  # noqa: BLE001
        pass
    if rec.get("status") in ("starting", "running"):
        rec["status"] = "failed"
    # Thread the turn's token usage (the CLI's own report, captured by the translator) into the
    # finalize record — it's what the per-model llm.* metering bills.
    if translator.usage:
        rec["usage"] = translator.usage
    _cancel_req.pop(sid, None)           # turn settled — a leftover Stop must not hit the next turn
    await _checkpoint(sid, rec)
    await _trace_finalize(sid, rec)
    # Release the session lease so a follow-up turn admits immediately (no TTL wait). Best-effort.
    if rec.get("lease_fence") and control_store.enabled():
        try:
            await control_store.lease_release(org, sid, translator.resp_id, rec["lease_fence"])
        except Exception:  # noqa: BLE001
            pass
    return status, produced, rec


# ── auth: internal (web BFF behind the engine JWT) or public Bearer API key ─────────────
def _hash_key(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


# API-key "last used": stamp the key vertex on use, but THROTTLED — a write on every request
# would hammer the graph partition on a busy key. Only persist when >_APIKEY_TOUCH_S has passed
# since the last stamp for that key (tracked per-replica; the graph value is monotonic so a
# missed stamp on one replica is harmless — another request re-stamps).
_apikey_touched_at: dict[str, float] = {}
_APIKEY_TOUCH_S = 60.0


def _touch_apikey(sha: str) -> None:
    now = time.time()
    if now - _apikey_touched_at.get(sha, 0.0) < _APIKEY_TOUCH_S:
        return
    _apikey_touched_at[sha] = now
    if len(_apikey_touched_at) > 5000:      # bounded: drop the oldest half
        for k in sorted(_apikey_touched_at, key=_apikey_touched_at.get)[:2500]:
            _apikey_touched_at.pop(k, None)

    async def _stamp():
        try:
            await _vg_upsert("HarnessApiKey", sha, {"last_used": repr(now)})
        except Exception:  # noqa: BLE001 — last-used is best-effort telemetry, never block auth
            pass
    try:
        asyncio.get_running_loop().create_task(_stamp())
    except RuntimeError:
        pass


async def _apikey_resolve(tok: str) -> dict | None:
    if not tok:
        return None
    sha = _hash_key(tok)
    # HR-INF-010: hot path = control-store point-read (off the shared Gremlin partition). The
    # store is a write-through cache of the graph key record kept in sync by mint/revoke; a HIT is
    # authoritative (revocation dual-writes it). A MISS (or store-down) falls back to the graph and
    # backfills, so pre-existing keys migrate on first use and Gremlin is never hit for them again.
    if control_store.enabled():
        doc = await control_store.apikey_get(sha)
        if doc is not None:
            if doc.get("revoked"):
                return None
            _touch_apikey(sha)
            return {"org": doc.get("org", ""), "member": doc.get("member", ""),
                    "workspace": doc.get("workspace", "") or "",
                    "workspace_default": bool(doc.get("workspace_default"))}
    v = await _vertex_get(sha)
    if v and v.get("kind") == "harness_api_key" and str(v.get("revoked")) not in ("1", "true", "True"):
        _touch_apikey(sha)
        p = {"org": v.get("org", ""), "member": v.get("member", ""),
             "workspace": v.get("workspace", "") or "",
             "workspace_default": str(v.get("workspace_default") or "") in ("1", "true", "True")}
        if control_store.enabled():
            try:
                # create_only: never overwrite an existing doc — a revoke tombstone may have landed
                # in the race window between the graph read above and this write (review #1).
                await control_store.apikey_put(sha, p["org"], p["member"], p["workspace"],
                                               p["workspace_default"], create_only=True)
            except Exception:  # noqa: BLE001 — backfill is best-effort; the graph read already succeeded
                pass
        return p
    return None


_identity_obs = _OpsDrops("identity", 60, ("jwt_ok", "service_call", "jwt_invalid", "mismatch"))


def _verify_login_jwt(auth: str) -> dict | None:
    """Verify a platform login JWT (engine-minted HS256) from an Authorization header.
    Returns {org, member} claims, or None when the header isn't a JWT / doesn't verify."""
    if not AUTH_JWT_SECRET or auth[:7].lower() != "bearer ":
        return None
    tok = auth[7:].strip()
    if tok.count(".") != 2:          # API keys also arrive as Bearer; JWTs have two dots
        return None
    try:
        import jwt as _pyjwt
        claims = _pyjwt.decode(tok, AUTH_JWT_SECRET, algorithms=["HS256"])
        # member = the EMAIL claim: it's the app's canonical member key (authHeaders sends it,
        # traces scope per-user by it). The JWT `sub` is the member-id form — using it would
        # silently break per-member trace isolation. org (the tenancy boundary) is the `org` claim.
        return {"org": str(claims.get("org") or ""),
                "member": str(claims.get("email") or claims.get("sub") or "")}
    except Exception:  # noqa: BLE001 — expired/garbage/foreign token
        return None


async def _principal(request: Request) -> dict:
    h = request.headers
    if INTERNAL_KEY and h.get("x-harness-internal", "") == INTERNAL_KEY:
        hdr = {"org": h.get("x-harness-org", ""), "member": h.get("x-harness-member", ""),
               "workspace": h.get("x-harness-workspace", ""),
               "workspace_default": h.get("x-harness-workspace-default", "") == "1"}
        auth = h.get("authorization", "")
        if auth:
            ver = _verify_login_jwt(auth)
            if ver is not None:
                _identity_obs.bump("jwt_ok")
                if ver["org"] != hdr["org"] or ver["member"] != hdr["member"]:
                    _identity_obs.bump("mismatch")
                    print(f"[identity] header/jwt mismatch hdr_org={hdr['org']} jwt_org={ver['org']} "
                          f"hdr_member={hdr['member']} jwt_member={ver['member']} path={request.url.path}",
                          flush=True)
                if HR_IDENTITY_MODE == "enforce":
                    if not ver["org"]:
                        raise HTTPException(401, "no active organization in session")
                    return {**hdr, "org": ver["org"], "member": ver["member"]}
                return hdr
            _identity_obs.bump("jwt_invalid")
            if HR_IDENTITY_MODE == "enforce":
                # Key + a PRESENT-but-unverifiable Authorization: refuse — otherwise a browser
                # could ride the BFF's key with junk auth and self-asserted identity headers.
                raise HTTPException(401, "invalid session token")
            return hdr
        # No Authorization at all: service-to-service (engine executor) — header identity
        # stands on key possession. The BFF never sends key-without-auth after LIVE-B.
        _identity_obs.bump("service_call")
        return hdr
    auth = h.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        p = await _apikey_resolve(auth[7:].strip())
        if p:
            return p
    raise HTTPException(401, "missing or invalid API key")


async def _owned_org(request: Request, org: str) -> dict:
    """Authorize an org-scoped management route (keys, harness CRUD, MCP secrets, connections).
    V1C02-002/003/005: these used _internal_only, which trusts ONLY the internal header — so the
    BFF's key + ANY/empty Bearer + a browser-chosen path org read/wrote another org's data. The
    fix is to resolve the FULL principal (which verifies the login JWT under HR_IDENTITY_MODE=
    enforce, or an API key) and require the path org to equal the principal's own org. The path
    org is never trusted for identity — only for addressing your own resources."""
    p = await _principal(request)
    if not p.get("org"):
        raise HTTPException(401, "no organization in session")
    if org != p.get("org"):
        raise HTTPException(403, "not your organization")
    return p


@app.get("/internal/storage-usage", dependencies=[Depends(_internal_only)])
async def storage_usage() -> dict:
    """Total durable workspace bytes per org, for the daily storage.gb_day billing sweep.
    Sums each non-deleted session's checkpoint_bytes (the persisted workspace-tar size) grouped
    by its tenant (== org). One rate covers every storage type — the margin is baked into the
    single storage.gb_day price, so callers just multiply GB × days."""
    # Sum checkpoint_bytes per tenant. Done client-side (not a backend aggregate): props are
    # stored as strings, so a backend sum() may not coerce — this was already the fallback path
    # and is the only one that behaves identically across backings.
    by_org: dict[str, int] = {}
    for v in await BACKING.graph.find("HarnessSession", neq={"status": "deleted"}):
        tenant = str(v.get("tenant") or "")
        if not tenant:
            continue
        try:
            by_org[tenant] = by_org.get(tenant, 0) + int(float(v.get("checkpoint_bytes") or 0))
        except (TypeError, ValueError):
            pass
    return {"by_org": by_org}


@app.post("/internal/reindex-traces", dependencies=[Depends(_internal_only)])
async def reindex_traces(org: str, dry_run: bool = False, max_pages: int = 500) -> dict:
    """One-time backfill: mirror every existing flat-index manifest ({org}/idx/) into the narrow
    per-harness ({org}/idxh/{harness}/) and per-member ({org}/idxm/{member}/) indexes the filtered
    Traces/Recents reads now use — without it, sessions created before this deploy are invisible to
    filtered views. Idempotent (overwrites mirrors), so safe to re-run."""
    scanned = 0
    mirrored = 0
    cursor: str | None = None
    pages = 0
    while pages < max_pages:
        lst = await _blob_list(f"{org}/idx/", limit=200, cursor=cursor)
        items = lst.get("items", [])
        if not items:
            break

        async def _one(it: dict):
            nonlocal mirrored
            b = await _blob_get(it["file_id"], kb=TRACE_KB)
            if not b:
                return
            try:
                m = json.loads(b)
            except Exception:  # noqa: BLE001
                return
            base = (m.get("trace_blob") or "").strip()
            if not base:
                return
            if not dry_run:
                await _index_manifest(base, m)
            mirrored += 1

        await asyncio.gather(*[_one(it) for it in items])
        scanned += len(items)
        cursor = lst.get("cursor")
        pages += 1
        if not cursor:
            break
    return {"org": org, "scanned": scanned, "mirrored": mirrored, "dry_run": dry_run, "pages": pages}


@app.post("/internal/backfill-workspace", dependencies=[Depends(_internal_only)])
async def backfill_workspace(org: str, workspace: str, dry_run: bool = False, max_pages: int = 500) -> dict:
    """One-time migration for Workspaces-as-Spaces: stamp every pre-existing HR resource of `org`
    onto `workspace` (the org's Default Workspace space id). Covers Harness vertices, API-key
    vertices (marked workspace_default so legacy leniency applies), session vertices, and every
    trace manifest — re-indexed so the per-workspace idxw mirror exists. Only touches records
    with NO workspace stamp, so re-runs and mixed states are safe."""
    out = {"org": org, "workspace": workspace, "dry_run": dry_run,
           "harnesses": 0, "keys": 0, "manifests": 0, "sessions": 0}
    for row in await _vg_list_by_org("Harness", org):
        if not (row.get("workspace") or ""):
            if not dry_run:
                await _vg_upsert("Harness", str(row.get("id")), {"workspace": workspace})
            out["harnesses"] += 1
    key_rows = await BACKING.graph.find("HarnessApiKey", {"org": org})
    for row in key_rows:
        if not (row.get("workspace") or ""):
            if not dry_run:
                await _vg_upsert("HarnessApiKey", str(row.get("id")),
                                 {"workspace": workspace, "workspace_default": "1"})
            out["keys"] += 1
    cursor: str | None = None
    pages = 0
    while pages < max_pages:
        lst = await _blob_list(f"{org}/idx/", limit=200, cursor=cursor)
        items = lst.get("items", [])
        if not items:
            break

        async def _one(it: dict):
            b = await _blob_get(it["file_id"], kb=TRACE_KB)
            if not b:
                return
            try:
                m = json.loads(b)
            except Exception:  # noqa: BLE001
                return
            if m.get("workspace"):
                return
            base = (m.get("trace_blob") or "").strip()
            if not base:
                return
            m["workspace"] = workspace
            if not dry_run:
                await _index_manifest(base, m)
                sid = str(m.get("session_id") or "")
                if sid:
                    await _vertex_upsert(sid, {"workspace": workspace})
                    out["sessions"] += 1
            out["manifests"] += 1

        await asyncio.gather(*[_one(it) for it in items])
        cursor = lst.get("cursor")
        pages += 1
        if not cursor:
            break
    return out


# ── /v1/responses ───────────────────────────────────────────────────────────────────
class CreateResponseBody(BaseModel):
    model: str | None = None
    input: object = None
    stream: bool = False
    previous_response_id: str | None = None
    store: bool = True
    instructions: str | None = None
    max_output_tokens: int | None = None
    background: bool = False
    metadata: dict | None = None
    tools: list | None = None
    include: list | None = None
    backend: str | None = None     # non-OpenAI convenience: force codex|claude
    max_step: int | None = None         # per-request agent step budget (claude --max-turns)
    timeout_seconds: int | None = None  # per-request wall-clock cap for the turn


_IDEM_TERMINAL = {"completed", "failed", "incomplete", "cancelled", "error"}


async def _idem_replay(resp_id: str, stream: bool):
    """A duplicate request (same Idempotency-Key) returns the FIRST request's result instead of
    starting a second run. Polls the stored response until it's terminal (the first run may still be
    in flight), then returns it — non-stream as JSON, stream as a minimal SSE that ends on the
    terminal event. No re-execution."""
    async def _await_terminal() -> dict | None:
        for _ in range(1800):   # ~ up to the turn cap; poll the durable response record
            rec = await _resp_get(resp_id)
            if rec and str(rec.get("status") or "") in _IDEM_TERMINAL:
                return rec
            await asyncio.sleep(2.0)
        return await _resp_get(resp_id)

    if not stream:
        rec = await _await_terminal()
        return JSONResponse(rec or {"id": resp_id, "status": "unknown",
                                    "error": {"message": "idempotent replay: original response not found"}})

    async def gen():
        created = {"type": "response.created", "sequence_number": 0,
                   "response": {"id": resp_id, "object": "response", "status": "in_progress"}}
        yield f"data: {json.dumps(created)}\n\n"
        rec = await _await_terminal()
        st = str((rec or {}).get("status") or "failed")
        ev = "response.completed" if st == "completed" else "response.failed"
        yield f"data: {json.dumps({'type': ev, 'sequence_number': 1, 'response': rec or {'id': resp_id, 'status': st}})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/v1/responses")
async def create_response(body: CreateResponseBody, request: Request):
    principal = await _principal(request)
    org, member = principal.get("org", ""), principal.get("member", "")
    if not org:
        raise HTTPException(400, "no org resolved for this principal")
    meta = body.metadata or {}
    # Request idempotency: the durable control store is the SINGLE authority (create_item = atomic
    # reservation). No in-process/blob/Redis fallback — a keyed request without the store fails
    # closed (503), never runs a divergent degraded path. idem_sha_v/idem_rhash are computed here
    # (read-only replay fast-path for retries) and reused by the authoritative reserve below.
    idem_key = (request.headers.get("Idempotency-Key") or str(meta.get("idempotency_key") or "")).strip()
    idem_sha_v: str | None = None
    idem_rhash: str | None = None
    if idem_key:
        if not control_store.enabled():
            raise HTTPException(503, "idempotency store unavailable; retry")
        idem_sha_v = _idem_sha(idem_key)
        idem_rhash = _req_hash(body)
        try:
            existing = await control_store.idem_get(org, idem_sha_v)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, "idempotency store unavailable; retry") from e
        if existing is not None:
            if str(existing.get("req_hash") or "") not in ("", idem_rhash):
                raise HTTPException(409, "Idempotency-Key reused with a different request payload")
            return await _idem_replay(str(existing.get("resp_id") or ""), bool(body.stream))
    # harness id: request metadata, else the X-Harness-Id header (set by a front proxy that maps
    # {harness_id}/v1/* -> /v1/*, or by the native public-shape route above).
    harness_id = str(meta.get("harness_id") or request.headers.get("x-harness-id") or "")
    harness_name = str(meta.get("harness_name") or "")
    hv = await _harness_vertex(harness_id) if harness_id else None
    # A deleted harness cannot run new turns (same 404 as the read endpoints). Cross-org runs are
    # ALLOWED — sibling products legitimately run a user's harness under a platform credential, and
    # the marketplace model is exactly "callers run it, the owner pays infra". Until entitlements
    # land, the unguessable harness id is the run capability.
    if hv and str(hv.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    # HR-INF-023: credit admission. BILLING is the harness OWNER's org — the Developer who built the
    # harness funds its infra consumption (hv["org"], stamped at harness creation), regardless of who
    # calls it. A turn with no harness vertex (built-in, or an ad-hoc/chained turn that carries no
    # harness_id — it runs without harness config) bills the CALLER's org. The gate here and the meter
    # at trace-finalize key on the SAME org. Runs after the idempotency replay fast-path (a retry
    # replays, never 402s) and before any session resolve / reserve / lease / hydrate — a 402 here
    # allocates nothing. (The caller-pays-the-builder's-price / platform-fee / revenue-split is a
    # SEPARATE Stripe Connect flow — a different fund system, not this credit gate.)
    billing_org = (str(hv.get("org") or "") if hv else "") or org
    await _credit_gate(billing_org)
    # Caller-selected model: the top-level OpenAI `model` field (what the console + API users send),
    # then request metadata. When omitted, fall back to the harness's saved default_model so every
    # session of a custom harness inherits its configured default.
    model_req = str(body.model or meta.get("model") or "")
    # The client sends the bare backend name ("claude"/"codex") as the model when no model is
    # explicitly selected — that's not a valid provider id. Treat it as "unset" and inherit, in order:
    #   previous round's model -> the harness default_model -> connection default (in _map_model).
    # This keeps a conversation on the user's chosen model and never ships the bare backend to Bedrock.
    _BARE = {"claude", "codex", "anthropic", "bedrock", "openai", "hermes", ""}
    if model_req.lower() in _BARE:
        inherited = ""
        if body.previous_response_id:
            pr = await _resp_get(body.previous_response_id)
            cand = str((pr or {}).get("model") or "")
            if cand.lower() not in _BARE:
                inherited = cand
        model_req = inherited or ""
    if (not model_req) and hv:
        model_req = str(hv.get("default_model") or "")

    # step budget + wall-clock cap: request field -> request metadata -> harness config -> defaults.
    def _num(v) -> int | None:
        try:
            n = int(str(v))
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None
    max_step = (_num(body.max_step) or _num(meta.get("max_step"))
                or _num((hv or {}).get("max_step")) or 400)
    timeout_s = (_num(body.timeout_seconds) or _num(meta.get("timeout_seconds"))
                 or _num((hv or {}).get("timeout_seconds")) or DEFAULT_TIMEOUT_S)
    # Pin the backend to the harness's base (a custom harness always runs on its own backend);
    # only fall back to inferring it from the model name when there's no harness. This makes the
    # model permission check below meaningful — the requested model is validated against the
    # harness's fixed backend, not allowed to silently re-route to a different one.
    backend = _backend_of_harness(hv) or _route_backend(model_req or body.model, body.backend)
    # Server-side model permission (CT-124): an unauthorized model for this backend is replaced by
    # the harness's authorized default and the substitution is recorded in the run metadata.
    model_req, requested_model, model_fallback, model_fallback_reason = _resolve_model_policy(
        model_req, hv, backend)
    # Token-level streaming (CT-127): opt in globally via env HARNESS_STREAM_PARTIAL=1, or per-request
    # via metadata.stream_partial (for testing). Claude uses --include-partial-messages; codex diffs
    # item.updated (self-healing → batch if it doesn't emit updates). Default off = current batch
    # behavior, so a rollback is just flipping the env with no redeploy.
    want_partial = (backend in ("claude", "codex") and (
        os.environ.get("HARNESS_STREAM_PARTIAL", "0") == "1" or bool(meta.get("stream_partial"))))
    # Codex streaming path: run the codex turn via the app-server protocol (the only codex mode that
    # streams assistant text). Flag-gated (env HARNESS_CODEX_APPSERVER or metadata.codex_appserver);
    # default off keeps codex on the stable `codex exec` path. Rollback = flip env, no redeploy.
    want_appserver = (backend == "codex" and (
        os.environ.get("HARNESS_CODEX_APPSERVER", "0") == "1" or bool(meta.get("codex_appserver"))))
    chain = await _resolve_chain(org, backend, None)
    # The chain is the FALLBACK, not the entry condition: a model mapped to an integration runs on
    # that integration first (see the candidate list in _resp_execute). Requiring a policy chain
    # here rejected the turn before the executor could ever reach the integration — so a user who
    # had just added their own key was told there was no connection for the backend, which was
    # both wrong and unactionable. Only refuse when NOTHING can serve it.
    if not chain and not await _mapped_integration_conn(backend, model_req):
        raise HTTPException(400, f"no provider configured for backend '{backend}' — add an "
                                 f"integration for a provider that serves '{model_req or backend}', "
                                 f"or configure a connection policy")
    # Additional Headers (app-level auth pass-through): the harness config declares header NAMES;
    # capture the caller's per-request values here (case-insensitive) and thread them to the MCP
    # resolver, where $headers.{name} references render into the runner's MCP config. Values are
    # per-turn only — never persisted to the harness row or the trace. `hv` (the harness vertex) was
    # already read above; its list props are JSON strings on the vertex.
    def _hv_arr(prop: str) -> list:
        try:
            a = json.loads((hv or {}).get(prop) or "[]")
            return a if isinstance(a, list) else []
        except Exception:  # noqa: BLE001
            return []
    hdr_vals: dict[str, str] = {}
    declared = [h.strip() for h in _hv_arr("additional_headers") if isinstance(h, str) and h.strip()]
    for _hn in declared:
        _v = request.headers.get(_hn)
        if _v is not None:
            hdr_vals[_hn.lower()] = _v
    # Fail fast, not deep in the tool: if an ENABLED MCP server references $headers.{name} and this
    # request didn't supply that header, the tool call would fail opaquely (bad auth at the MCP).
    # Reject up-front instead, naming exactly what's missing and where it's needed.
    missing: list[str] = []
    for _s in _hv_arr("mcp_servers"):
        if not isinstance(_s, dict) or str(_s.get("enabled")) in ("False", "false", "0"):
            continue
        _blob = " ".join([str(_s.get("url") or ""), str(_s.get("auth") or ""),
                          " ".join(str(x) for x in (_s.get("headers") or {}).values())])
        for _ref in _HDR_REF.findall(_blob):
            if _ref.lower() not in hdr_vals:
                missing.append(f"'{_ref}' (needed by MCP server '{_s.get('name') or _s.get('id') or 'mcp'}')")
    if missing:
        raise HTTPException(400, "missing required header(s): " + ", ".join(sorted(set(missing)))
                            + ". This harness declares Additional Headers that its tools reference — "
                              "send them on the request (in the Playground, set values via the gear "
                              "icon in the preview pane).")

    prompt, files_in, input_items = _parse_input(body.input)
    user_text = prompt   # the raw user message (before instructions / file-note prepends) for the trace
    # resolve file_id-referenced inputs to inline base64 (uploaded via POST /v1/files);
    # the original filename comes from the uploads/{fid}.meta blob when the input
    # block didn't inline one (mirrors the containers/*.meta read in the files lister)
    for f in files_in:
        if f.get("content_b64") is None and f.get("file_id"):
            data = await _blob_get(f"uploads/{f['file_id']}", kb=RESP_BLOB_KB)
            if data is not None:
                f["content_b64"] = base64.b64encode(data).decode()
            if not f.get("filename"):
                fmeta = await _blob_get(f"uploads/{f['file_id']}.meta", kb=RESP_BLOB_KB)
                if fmeta is not None:
                    try:
                        f["filename"] = (json.loads(fmeta.decode()) or {}).get("filename") or ""
                    except Exception:
                        f["filename"] = ""
                if not f.get("filename"):
                    f["filename"] = f["file_id"]   # last resort: readable, unique
    files_in = [{"filename": f["filename"], "content_b64": f["content_b64"]}
                for f in files_in if f.get("content_b64") and f.get("filename")]
    if body.instructions:
        prompt = f"{body.instructions}\n\n---\n\n{prompt}"
    if not prompt and not files_in:
        raise HTTPException(400, "empty input")
    if files_in:
        names = ", ".join(f["filename"] for f in files_in)
        prompt = f"[Attached files saved in your working directory: {names}]\n\n{prompt}"

    # session_hint: the client's known active session — a fallback continuity signal so a
    # follow-up never forks a new session when previous_response_id was lost client-side
    # (interrupted stream, tab switch). The resolver validates org ownership before reuse.
    sid, resume = await _resp_resolve_session(org, member, body.previous_response_id, backend,
                                              harness_id=harness_id, harness_name=harness_name,
                                              session_hint=str(meta.get("session_id") or ""),
                                              workspace=str(principal.get("workspace") or ""))
    # Bill the harness OWNER's org (resolved above), not the caller's — stamp it on the in-process
    # session trace so trace-finalize meters usage against the same org the gate admitted. The turn
    # executes + finalizes on THIS replica, so this in-process stamp is authoritative for metering;
    # it is also persisted on the vertex below for durability/observability. Fixed per session (a
    # session is one harness), so every turn re-stamps the same value.
    _bt = _session_trace.get(sid)
    if _bt is not None:
        _bt["billing_org"] = billing_org
    resp_id = _rid("resp")
    created_at = time.time()
    # Authoritative idempotency reservation (HR-INF-011): AFTER validation, BEFORE the turn
    # executes. One atomic create_item wins; a 409 means a concurrent/earlier request already
    # reserved this key → replay its response instead of running twice. Fail CLOSED (retryable
    # 503) if the store errors. If the request later raises before entering execution, the guard
    # further down RELEASES this reservation so a retry can re-run (no 'poisoned' key).
    if idem_key and idem_sha_v is not None:
        try:
            existing = await control_store.idem_reserve(org, idem_sha_v, resp_id, idem_rhash or "", int(_IDEM_TTL))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, "idempotency store unavailable; retry") from e
        if existing is not None:
            if str(existing.get("req_hash") or "") not in ("", idem_rhash or ""):
                raise HTTPException(409, "Idempotency-Key reused with a different request payload")
            return await _idem_replay(str(existing.get("resp_id") or ""), bool(body.stream))
    # This turn owns the session from HERE: clear a leftover Stop flag (it belonged to the
    # previous turn) and mark the vertex starting so cancel_session sees a live turn during
    # the entire warmup window — even while this task waits on the concurrency gates. Stamp
    # running_response_id NOW (not only in _resp_execute): from the instant the client holds this
    # resp_id, a cross-replica cancel_session can resolve it and latch the per-response cancel —
    # closing the accept→execute window (HR-INF-010, the ONE cancel mechanism).
    _cancel_req.pop(sid, None)
    try:
        # Clear runner_turn_id too: a stale value (the PREVIOUS turn's CLI) would make a cancel in
        # this warmup window burn seconds on a dead-handle sandbox kill before settling.
        await _vertex_upsert(sid, {"status": "running", "turn_status": "starting",
                                   "running_response_id": resp_id, "runner_turn_id": "",
                                   "billing_org": billing_org})
    except Exception as e:  # noqa: BLE001 — this write is load-bearing for cross-replica cancel: log it
        print(f"[cancel] accept-time running_response_id write failed sid={sid} resp={resp_id}: {str(e)[:120]}",
              flush=True)
    # From reserve through the point we ENTER execution, guard the idempotency reservation: if
    # anything raises before the turn starts running (so no response record will ever be
    # persisted), release the reservation so a retry re-runs instead of replaying a resp_id that
    # produced nothing (a 'poisoned' key). Once we enter the stream/non-stream branch the turn is
    # guaranteed to persist a terminal record even on failure, so releasing there would wrongly
    # permit a double run — so we release ONLY on an exception before execution begins.
    try:
        # remember this turn's response id on the trace + session so a loaded session can resume
        _session_trace.setdefault(sid, {}).update(last_response_id=resp_id)
        tr = _RespTranslator(resp_id, model_req or body.model or backend, body.previous_response_id, body.store, created_at, sid=sid)
        tr.requested_model, tr.model_fallback, tr.fallback_reason = requested_model, model_fallback, model_fallback_reason

        # Broadcast a synthetic turn-start so the bus alone can render a conversation turn from
        # scratch (the native Responses events don't echo the user's prompt).
        _bus_publish(org, harness_id, member, sid, resp_id,
                     {"type": "harness.turn.started", "user_text": user_text, "response_id": resp_id})

        async def persist(status: str) -> None:
            stored = {**tr._response_obj(status), "_session_id": sid, "_org": org,
                      "_member": member, "_input": input_items, "_backend": backend}
            await _resp_put(resp_id, stored, org, sid, body.previous_response_id, status, created_at, body.store)

        # Persist the turn as 'running' NOW so GET /v1/sessions/{sid}/turns surfaces the in-flight
        # turn to any fetch (fresh panel, refresh, different replica, restart). Best-effort: even
        # if it fails, execution proceeds and a terminal record is persisted at the end.
        try:
            await persist("running")
        except Exception:  # noqa: BLE001
            pass
    except Exception:
        if idem_key and idem_sha_v is not None:
            try:
                await control_store.idem_release(org, idem_sha_v, resp_id)
            except Exception:  # noqa: BLE001
                pass
        raise
    # Past this point we are committed to executing; the turn will persist a terminal record even
    # on failure, so the reservation must stand (releasing would permit a double run).

    if body.background:
        # Durable async: run the turn as a DETACHED task and return the already-persisted 'running'
        # record immediately. The caller polls GET /v1/responses/{id} until a terminal status. This
        # is the same proven machinery as the streaming path's run(), minus the SSE queue — events
        # still go to the bus so an open Workbench renders the turn live.
        async def bus_emit_bg(ev):
            _bus_publish(org, harness_id, member, sid, resp_id, ev)

        async def run_bg():
            try:
                async with _global_sem(), _tenant_sem(org):
                    for ev in tr.start():
                        await bus_emit_bg(ev)
                    status, produced, rec = await _resp_execute(
                        tr, org=org, member=member, sid=sid, backend=backend, chain=chain,
                        prompt=prompt, files_in=files_in, resume=resume, emit=bus_emit_bg,
                        model_req=model_req, user_text=user_text, harness_id=harness_id,
                        max_step=max_step, timeout_s=timeout_s, hdr_vals=hdr_vals,
                        partial_messages=want_partial, codex_appserver=want_appserver, hv=hv)
                    if status == "failed":
                        tr.error = {"code": "harness_error",
                                    "message": (json.dumps(rec.get("tried") or [])[:400]) or "turn failed"}
                    for ev in tr.complete(status, produced):
                        await bus_emit_bg(ev)
                    await persist(status)
            except asyncio.CancelledError:
                # HR-INF-019: the replica is draining (SIGTERM) and this detached turn didn't finish
                # inside the drain window. Settle it HONESTLY ('failed') instead of leaving a 6h
                # phantom 'running', then re-raise so the loop can shut down. Best-effort I/O — the
                # shutdown hook awaits us while the loop is still alive so these writes can land.
                await _settle_drained(persist, tr, bus_emit_bg)
                raise
            except Exception as e:  # noqa: BLE001
                # Emit the terminal failure to the bus too (parity with streaming) so an open
                # Workbench settles instead of showing the turn stuck 'running'.
                for ev in tr.fail(str(e)[:300]):
                    await bus_emit_bg(ev)
                try:
                    await persist("failed")
                except Exception:  # noqa: BLE001
                    pass

        task = asyncio.create_task(run_bg())
        _inflight.add(task)
        task.add_done_callback(_inflight.discard)
        # Return a SNAPSHOT (copy the output list) so the immediate JSON can't alias the list the
        # detached task appends to. Already persisted 'running'; poll GET /v1/responses/{id}.
        _snap = tr._response_obj("running")
        _snap["output"] = list(_snap.get("output") or [])
        return _snap

    if body.stream:
        async def gen():
            q: asyncio.Queue = asyncio.Queue()

            async def emit(ev):
                await q.put(ev)
                _bus_publish(org, harness_id, member, sid, resp_id, ev)  # broadcast to all subscribers

            async def run():
                try:
                    async with _global_sem(), _tenant_sem(org):
                        for ev in tr.start():
                            await emit(ev)
                        status, produced, rec = await _resp_execute(
                            tr, org=org, member=member, sid=sid, backend=backend, chain=chain,
                            prompt=prompt, files_in=files_in, resume=resume, emit=emit, model_req=model_req,
                            user_text=user_text, harness_id=harness_id, max_step=max_step,
                            timeout_s=timeout_s, hdr_vals=hdr_vals, partial_messages=want_partial, codex_appserver=want_appserver, hv=hv)
                        if status == "failed":
                            tr.error = {"code": "harness_error",
                                        "message": (json.dumps(rec.get("tried") or [])[:400]) or "turn failed"}
                        for ev in tr.complete(status, produced):
                            await emit(ev)
                        await persist(status)
                except asyncio.CancelledError:
                    await _settle_drained(persist, tr, emit)   # HR-INF-019 drain (see run_bg)
                    raise
                except Exception as e:  # noqa: BLE001
                    for ev in tr.fail(str(e)[:300]):
                        await emit(ev)
                    try:
                        await persist("failed")
                    except Exception:  # noqa: BLE001
                        pass
                finally:
                    await q.put(None)

            task = asyncio.create_task(run())
            _inflight.add(task)                       # keep a ref so it isn't GC'd, and so it
            task.add_done_callback(_inflight.discard)  # survives client disconnect
            try:
                while True:
                    # Keepalive: emit an SSE comment if the agent is quiet for a while (long tool calls,
                    # model thinking) so nginx / ACA don't idle-close the stream mid-run ("transfer
                    # closed with outstanding read data").
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if ev is None:
                        break
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
            finally:
                # Do NOT cancel on client disconnect. Let the turn run to completion and persist so a
                # dropped browser/SSE connection never loses the work — the frontend recovers by polling
                # the stored response (GET /v1/responses/{id}) or re-listing the session's turns.
                pass

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                          "Connection": "keep-alive"})

    # non-streaming: run to completion, return the assembled Response object. Still publish every
    # event to the broadcast bus so an open Workbench renders this turn live even though the API
    # caller isn't streaming (the bus, not the POST stream, is the UI's source of truth).
    async def bus_emit(ev):
        _bus_publish(org, harness_id, member, sid, resp_id, ev)
    try:
        async with _global_sem(), _tenant_sem(org):
            for ev in tr.start():
                await bus_emit(ev)
            status, produced, rec = await _resp_execute(
                tr, org=org, member=member, sid=sid, backend=backend, chain=chain,
                prompt=prompt, files_in=files_in, resume=resume, emit=bus_emit, model_req=model_req,
                user_text=user_text, harness_id=harness_id, max_step=max_step,
                timeout_s=timeout_s, hdr_vals=hdr_vals, partial_messages=want_partial, codex_appserver=want_appserver, hv=hv)
            if status == "failed":
                tr.error = {"code": "harness_error",
                            "message": (json.dumps(rec.get("tried") or [])[:400]) or "turn failed"}
            for ev in tr.complete(status, produced):
                await bus_emit(ev)
            obj = tr._response_obj(status)
    except Exception as e:  # noqa: BLE001
        tr.error = {"code": "harness_error", "message": str(e)[:300]}
        obj = tr._response_obj("failed")
        status = "failed"
    await persist(status)
    return obj


@app.get("/v1/harnesses/{harness_id}/events")
async def harness_events(harness_id: str, request: Request):
    """Realtime broadcast: subscribe to ALL live events for this harness's sessions (per-user
    filtered), each tagged with session_id + response_id. The Workbench opens ONE of these per
    harness and routes events to the matching conversation — so any session updates live without a
    per-turn stream or a hard refresh. Durable history (closed turns) still loads via
    GET /v1/sessions/{sid}/turns; this stream carries the in-flight deltas."""
    principal = await _principal(request)
    org, member = principal.get("org", ""), principal.get("member", "")
    if not org:
        raise HTTPException(400, "no org resolved for this principal")
    topic = _bus_topic(org, harness_id)
    q: asyncio.Queue = asyncio.Queue(maxsize=_BUS_Q_MAX)
    _bus.setdefault(topic, set()).add(q)

    def _put(sid: str, rid: str, ev, replay: bool = False) -> None:
        try:
            m = {"session_id": sid, "response_id": rid, "member": member, "event": ev}
            if replay:
                # Catch-up frame reconstructing already-happened history: the client ALREADY loaded
                # this via GET /v1/sessions/{sid}/turns (which reconstructs an in-flight turn from
                # the same durable trace), so it drops replay frames to avoid double-rendering. The
                # tag keeps the two catch-up paths (this cross-replica first-pass + the in-process
                # buffer replay) consistent: both are history, only forward events render live.
                m["replay"] = True
            q.put_nowait(m)
        except asyncio.QueueFull:
            _bus_drops.bump("sse_q")   # this SSE client is behind; it reconciles via /turns on next open

    # Tail state lives OUTSIDE the tail coroutine so the supervisor below can restart a crashed tail
    # without re-emitting already-delivered events (cursors survive the restart).
    translators: dict[str, _RespTranslator] = {}
    cursors: dict[str, str] = {}   # sid -> last-consumed chunk KEY (time-ordered names)
    started: set = set()

    async def _xreplica_tail():
        """Cross-replica live: a turn runs on ONE replica (its in-process pub/sub only reaches clients
        on that replica). For running sessions whose turn is NOT on this replica, tail the durable
        trace (the canonical events the translator consumes are exactly what's stored) and reconstruct
        native deltas — so live progress reaches a viewer on ANY replica. No shared backplane needed."""
        first_pass = True
        while True:
            # FIRST pass runs IMMEDIATELY (no 2.5s wait, no Redis-health skip): a tab that opens on
            # a running session whose turn is on ANOTHER replica — or after a mid-turn gateway
            # restart cleared this replica's in-memory buffer — must catch up from the durable trace
            # right away, not blank until the next event or a refresh. The buffer replay on connect
            # only covers sessions THIS replica is running; this covers all the rest.
            if not first_pass:
                await asyncio.sleep(2.5)
                # Steady state with a healthy backplane: live deltas arrive via the bus, so throttle
                # the (expensive) durable-trace catch-up. Any Redis doubt → keep tailing every 2.5s.
                if REDIS_URL and _redis_ok.get("sub") and _redis_ok.get("pub"):
                    await asyncio.sleep(27.5)
                    continue
            # The first pass reconstructs history the client already loaded via /turns → tag its
            # emissions replay so the client drops them; later passes carry genuinely-new forward
            # events (a turn running on another replica) and render live.
            catchup = first_pass
            first_pass = False
            try:
                cards = (await list_traces(org=org, limit=40, member=member, harness=harness_id)).get("sessions", [])
            except Exception:  # noqa: BLE001
                continue
            for c in cards:
                sid = c.get("session_id"); status = (c.get("status") or "").lower()
                if not sid:
                    continue
                if sid in _turn_buffers:          # this replica runs it → in-process pub/sub covers it
                    continue
                terminal = status in _SESSION_TERMINAL
                # Only tail RUNNING sessions, or ones we were ALREADY tailing that just finalized
                # (completed sessions we never tailed load via /turns — skip them).
                if terminal and sid not in started:
                    continue
                if not terminal and status not in ("running", "starting", ""):
                    continue
                base = c.get("trace_blob")
                if not base and sid not in started:
                    continue
                # ALWAYS read+feed the trace first (even on the finalizing poll) — a one-shot CLI emits
                # the whole assistant turn as a single event that lands together with completion, so
                # skipping the read here would drop the entire response for cross-replica viewers.
                if base:
                    # Incremental tail via a CHUNK-KEY cursor (HR-INF-015): chunk names are
                    # time-ordered and immutable once written, so fetching only keys > the last-seen
                    # key yields exactly the new events. The old line-index cursor forced a FULL
                    # re-download+rejoin of the session every 2.5s poll (O(session) per tick).
                    if sid not in started:
                        _put(sid, c.get("last_response_id") or "", {"type": "harness.turn.started", "user_text": c.get("user_prompt") or ""}, replay=catchup)
                        translators[sid] = _RespTranslator(c.get("last_response_id") or sid, c.get("model") or "", None, True, time.time(), sid=sid)
                        cursors[sid] = ""; started.add(sid)
                    try:
                        listed = await _blob_list_all(f"{base}/events/", kb=TRACE_KB)
                        new_ids = sorted(it["file_id"] for it in listed
                                         if it.get("file_id") and it["file_id"] > cursors.get(sid, ""))
                        parts = await asyncio.gather(*[_blob_get(cid, kb=TRACE_KB) for cid in new_ids])
                        # Feed only the leading CONTIGUOUS run of successful gets: advancing the
                        # cursor past a transiently-failed chunk would skip its events forever
                        # (the old full-rejoin design self-healed; the cursor must too).
                        ok = 0
                        while ok < len(parts) and parts[ok] is not None:
                            ok += 1
                        new_ids, parts = new_ids[:ok], parts[:ok]
                    except Exception:  # noqa: BLE001
                        new_ids, parts = [], []
                    tr = translators[sid]
                    for ln in b"".join(p for p in parts if p).split(b"\n"):
                        if not ln.strip():
                            continue
                        try:
                            cev = json.loads(ln)
                        except Exception:  # noqa: BLE001
                            continue
                        # One malformed/unexpected event must NEVER kill the tail (it once died on the
                        # trace-injected user-prompt line and every cross-replica viewer went silent
                        # for the whole turn). Skip the bad line, keep streaming the rest.
                        try:
                            for oev in tr.feed(cev):
                                _put(sid, tr.resp_id, oev, replay=catchup)
                        except Exception:  # noqa: BLE001
                            continue
                    if new_ids:
                        cursors[sid] = new_ids[-1]
                if terminal:                       # emit the terminal event, then stop tailing this sid
                    tr = translators.get(sid)
                    st = "failed" if status in ("failed", "error") else ("incomplete" if status in ("incomplete", "max_turns") else "completed")
                    if tr:
                        try:
                            for oev in tr.complete(st):
                                _put(sid, tr.resp_id, oev)
                        except Exception:  # noqa: BLE001
                            pass
                    translators.pop(sid, None); cursors.pop(sid, None); started.discard(sid)

    async def _tail_forever():
        """Supervisor: the live tail must NEVER stay dead for the life of the subscription. Every
        risky op inside is individually guarded, but if anything unforeseen still escapes, restart
        the tail — cursors/translators persist in the enclosing scope, so it resumes where it left
        off instead of re-emitting. (The original tail died unsupervised on one bad event and every
        cross-replica viewer silently lost live progress for the whole turn.)"""
        while True:
            try:
                await _xreplica_tail()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await asyncio.sleep(2.5)

    async def gen():
        tail_task = asyncio.create_task(_tail_forever())
        try:
            yield ": connected\n\n"
            # Replay the in-flight turn of every running session of this harness (the client just
            # connected mid-turn — completed turns load via /turns; this hands it the running one so
            # it renders immediately instead of blank-until-next-event).
            for sid, buf in list(_turn_buffers.items()):
                if buf.get("harness") != harness_id:
                    continue
                if member and buf.get("member") and buf["member"] != member:
                    continue
                for ev in list(buf.get("events") or []):
                    yield f"data: {json.dumps({'session_id': sid, 'response_id': buf.get('rid',''), 'member': buf.get('member',''), 'event': ev, 'replay': True}, default=str)}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"          # keep nginx/ACA from idle-closing the stream
                    continue
                # per-user isolation: only this member's sessions (publisher tags member)
                if member and msg.get("member") and msg["member"] != member:
                    continue
                yield f"data: {json.dumps(msg, default=str)}\n\n"
        finally:
            tail_task.cancel()
            subs = _bus.get(topic)
            if subs is not None:
                subs.discard(q)
                if not subs:
                    _bus.pop(topic, None)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


@app.get("/v1/responses/{response_id}")
async def get_response(response_id: str, request: Request):
    principal = await _principal(request)
    rec = await _resp_get(response_id)
    if not rec:
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")
    # Object-level ownership (LIVE-B): one org must not read another's response. 404 (not 403)
    # so a cross-org id probe can't confirm existence. Legacy records with no _org stay readable.
    if str(rec.get("_org") or principal.get("org", "")) != principal.get("org", ""):
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")
    # Durable settler for async/background polling: never leave a poller stuck at 'running' if the
    # owning turn actually finished/died (reconciled from the session vertex + trace).
    rec = await _reconcile_response(response_id, rec)
    return _strip_internal(rec)


@app.get("/v1/sessions/{sid}/turns")
async def session_turns(sid: str, request: Request, limit: int = 0) -> dict:
    """Full conversation for a session: each HarnessResponse turn's user input + assistant output,
    oldest-first. Powers the Workbench 'open a recent session → see its chat history' flow.
    ?limit=N returns only the LAST N turns (HR-INF-015: bounds the per-open blob fan-out on
    long-horizon sessions; 0/absent = all, preserving existing callers)."""
    await _owned_session(request, sid)   # LIVE-B: enforce org ownership before returning content
    return await _session_turns_data(sid, limit=limit)


async def _session_turns_data(sid: str, limit: int = 0) -> dict:
    # find this session's response ids (HarnessResponse vertices carry session_id)
    ids: list[str] = []
    safe_sid = re.sub(r"[^A-Za-z0-9_-]", "", sid)
    rows = await BACKING.graph.find("HarnessResponse", {"session_id": safe_sid})
    rows.sort(key=lambda x: str(x.get("created_at") or ""))
    ids = [str(x.get("id")) for x in rows if x.get("id")]
    if limit and limit > 0:
        ids = ids[-limit:]   # last N turns only — bounds blob fetches AND response size
    turns = []
    # GB-history sessions: hundreds of turn records must not serialize into hundreds of
    # sequential blob round-trips. Bounded parallel fetch keeps order via index.
    _sem = asyncio.Semaphore(16)

    async def _fetch(rid: str) -> dict | None:
        async with _sem:
            return await _resp_get(rid)

    recs = await asyncio.gather(*(_fetch(rid) for rid in ids))
    for rid, rec in zip(ids, recs):
        if not rec or rec.get("_deleted"):
            continue
        # user text + attached input files from the stored input items; assistant text +
        # tool calls + files from the output. Attachments hydrate the user bubble's file
        # chips after a refresh (the bytes live in the session workspace; the by-path
        # artifact route serves them if the user clicks through).
        user_text = ""
        user_files: list[dict] = []
        for it in (rec.get("_input") or []):
            c = it.get("content")
            if isinstance(c, str):
                user_text += c
            elif isinstance(c, list):
                for p in c:
                    if not isinstance(p, dict):
                        continue
                    if p.get("type") == "input_text":
                        user_text += p.get("text", "")
                    elif p.get("type") in ("input_file", "input_image") and p.get("filename"):
                        user_files.append({"name": p.get("filename")})
        asst, tools, files = _output_to_turn_fields(rec.get("output") or [])
        turns.append({"id": rid, "status": rec.get("status"), "user": user_text,
                      "user_files": user_files, "assistant": asst, "tools": tools, "files": files,
                      "_model": rec.get("model") or "", "_created_at": rec.get("created_at") or 0})
    # Only the LAST turn can be in-flight, and only it can need reconciliation — both want the
    # session vertex, so read it ONCE.
    last_running = bool(turns) and str(turns[-1].get("status") or "") in (
        "running", "in_progress", "queued", "starting")
    if last_running:
        v = await _vertex_get(sid) or {}
        # (1) Terminal-reconcile: a cancel or replica death can leave the stored response at
        # running even though the session is terminal — which strands every future hydration at
        # "Working…". The session vertex is authoritative, so settle the status from it first.
        vst = str(v.get("turn_status") or v.get("status") or "")
        if vst in ("cancelled", "failed", "error", "done", "completed", "incomplete", "max_turns", "timeout"):
            turns[-1]["status"] = vst
        # (2) Trace catch-up whenever the stored record has NO content yet — output[] is only
        # written by persist() at finalize, so this covers BOTH cases with one mechanism:
        #   • turn still running → show progress-so-far, the bus streams new events on top;
        #   • turn JUST finished (vertex already terminal, persist()/produced-file collection still
        #     in flight — seconds for many files) → the trace already holds the full turn, so the
        #     client must never see "terminal but empty" and wipe its streamed content (that exact
        #     race blanked a finished turn until a refresh).
        # NOT elif of the status settle above — the settle changes status, not content.
        if not turns[-1]["assistant"] and not turns[-1]["tools"]:
            base = _prefix_from_vertex(sid, v)
            if base:
                # Scope replay to chunks THIS turn could have written — the events/ directory is one
                # flat cross-turn stream, so without this cutoff a fresh open silently fuses the
                # PRIOR turn's reply onto this one (see _replay_output_from_trace's since_ms doc).
                since_ms = int(float(turns[-1].get("_created_at") or 0) * 1000)
                out = await _replay_output_from_trace(
                    base, str(turns[-1]["id"]), str(turns[-1].get("_model") or ""), since_ms=since_ms)
                asst, tools, files = _output_to_turn_fields(out)
                turns[-1].update(assistant=asst, tools=tools, files=files)
    for _t in turns:
        _t.pop("_model", None)
        _t.pop("_created_at", None)
    return {"session_id": sid, "turns": turns, "last_response_id": ids[-1] if ids else None}


@app.delete("/v1/responses/{response_id}")
async def delete_response(response_id: str, request: Request):
    principal = await _principal(request)
    rec = await _resp_get(response_id)
    if not rec:
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")
    # V1C02-004: object-level ownership — one org must not delete another's response. 404 (not
    # 403) so a cross-org id probe can't confirm existence. Legacy records with no _org stay owned.
    if str(rec.get("_org") or principal.get("org", "")) != principal.get("org", ""):
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")
    rec["_deleted"] = True
    try:
        await _blob_put(f"responses/{response_id}.json", json.dumps(rec, default=str).encode(), kb=RESP_BLOB_KB)
    except Exception:  # noqa: BLE001
        pass
    await _vg_upsert("HarnessResponse", response_id, {"status": "deleted"})


# ── Session sharing + artifact serving by path (HRP-011) ─────────────────────────────────
# Default access: the harness org's members, via the console BFF (internal headers → org match).
# Opt-in sharing is SESSION-level only (product decision 2026-07-19): enabling share makes the
# read-only conversation AND every artifact reachable by anyone with the unguessable link; all
# artifacts inherit the session's share state. The share record lives in the graph auth data:
# `shared`/`share_token` props on the HarnessSession vertex (token reused across re-enables so a
# re-shared link keeps working; disable flips `shared` off which kills the whole surface).

def _artifact_headers(media: str, fname: str) -> dict:
    # Browser-renderable types serve INLINE so html/css/js/img/pdf render directly (relative
    # asset urls in an html page resolve to sibling paths under the same route prefix).
    return {"Content-Disposition": f'inline; filename="{fname}"',
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff"}


# Source/code/config files preview as plain text in the browser tab — the default mime
# guesses (video/mp2t for .ts, octet-stream for .tsx/.gitignore/.lock/…) force a download.
# html/css/js/json/svg keep their real types so pages render and assets resolve.
_TEXT_PREVIEW_EXTS = {
    "ts", "tsx", "jsx", "mjs", "cjs", "py", "rs", "go", "java", "c", "cc", "cpp", "h", "hpp",
    "sh", "bash", "zsh", "ps1", "rb", "php", "swift", "kt", "sql", "r", "jl", "lua", "vue",
    "toml", "ini", "cfg", "conf", "lock", "log", "txt", "md", "markdown", "yml", "yaml",
    "csv", "tsv", "env.example", "gitignore", "prettierrc", "eslintrc", "npmrc",
    "editorconfig", "dockerfile", "makefile", "gitattributes",
}


def _preview_media(path: str, media: str, data: bytes) -> str:
    base = path.rsplit("/", 1)[-1].lower()
    ext = base.rsplit(".", 1)[-1] if "." in base else base
    if ext in _TEXT_PREVIEW_EXTS or base.lstrip(".") in _TEXT_PREVIEW_EXTS:
        return "text/plain; charset=utf-8"
    if (not media or media == "application/octet-stream"):
        try:                       # unknown extension but textual content → preview as text
            data[:8192].decode("utf-8")
            return "text/plain; charset=utf-8"
        except Exception:  # noqa: BLE001
            pass
    return media or "application/octet-stream"


async def _serve_workspace_path(sid: str, path: str) -> Response:
    path = path.lstrip("/")
    if not path or not _ws_visible(path):
        raise HTTPException(404, "file not found")
    got = await _container_file_bytes(sid, _wf_id(path))
    if not got:
        raise HTTPException(404, "file not found")
    data, media, fname = got
    media = _preview_media(path, media, data)
    return Response(data, media_type=media, headers=_artifact_headers(media, fname))


async def _session_shared(sid: str) -> bool:
    """Single cached flag check — one vertex prop read on miss, no traversal."""
    now = time.time()
    hit = _SHARE_STATE_CACHE.get(sid)
    if hit and now - hit[0] < _SHARE_TTL:
        return hit[1]
    v = await _vertex_get(sid)
    shared = bool(v) and str(v.get("shared") or "") == "1"
    _SHARE_STATE_CACHE[sid] = (now, shared)
    return shared


@app.get("/w/{harness_id}/{sid}/workspace/{path:path}")
async def workspace_by_path(harness_id: str, sid: str, path: str) -> Response:
    """Canonical artifact URL: /{harness}/{session}/workspace/{path}. Access is ONE cached
    session-level check: is the session shared? (The console BFF maps its same-shaped route
    here.) harness_id is part of the address, not the auth — the sid is the lookup key."""
    if not await _session_shared(sid):
        raise HTTPException(404, "file not found")
    return await _serve_workspace_path(sid, path)


@app.get("/a/{sid}/{path:path}")
async def artifact_by_path(sid: str, path: str, request: Request) -> Response:
    """Authenticated artifact-by-path: org members open workspace files directly (inline)."""
    p = await _principal(request)
    v = await _vertex_get(sid)
    if not v or str(v.get("tenant") or "") != p.get("org"):
        raise uhp_error(404, "session_not_found", "No session with that id.", "session_id")
    return await _serve_workspace_path(sid, path)


class ShareBody(BaseModel):
    enabled: bool


@app.post("/v1/sessions/{sid}/share")
async def set_session_share(sid: str, body: ShareBody, request: Request) -> dict:
    p = await _principal(request)
    v = await _vertex_get(sid)
    if not v or str(v.get("tenant") or "") != p.get("org"):
        raise uhp_error(404, "session_not_found", "No session with that id.", "session_id")
    if body.enabled:
        token = str(v.get("share_token") or "") or ("shr" + uuid.uuid4().hex)
        await _vertex_upsert(sid, {"share_token": token, "shared": "1",
                                   "shared_at": str(time.time())})
        _SHARE_STATE_CACHE.pop(sid, None)
        _SHARE_TOKEN_CACHE.clear()
        return {"enabled": True, "token": token}
    await _vertex_upsert(sid, {"shared": "0"})
    _SHARE_STATE_CACHE.pop(sid, None)
    _SHARE_TOKEN_CACHE.clear()
    return {"enabled": False, "token": str(v.get("share_token") or "")}


@app.get("/v1/sessions/{sid}/share")
async def get_session_share(sid: str, request: Request) -> dict:
    p = await _principal(request)
    v = await _vertex_get(sid)
    if not v or str(v.get("tenant") or "") != p.get("org"):
        raise uhp_error(404, "session_not_found", "No session with that id.", "session_id")
    return {"enabled": str(v.get("shared") or "") == "1", "token": str(v.get("share_token") or "")}


async def _share_sid(token: str) -> str | None:
    """Resolve a share token to its session id — only while sharing is enabled."""
    tok = re.sub(r"[^A-Za-z0-9]", "", token or "")
    if not tok or not VG_GATEWAY_URL:
        return None
    hit = _SHARE_TOKEN_CACHE.get(tok)
    if hit and time.time() - hit[0] < _SHARE_TTL:
        return hit[1] or None
    rows = await BACKING.graph.find("HarnessSession", {"share_token": tok, "shared": "1"})
    if not rows:
        _SHARE_TOKEN_CACHE[tok] = (time.time(), "")
        return None
    sid = str(rows[0].get("id") or "")
    _SHARE_TOKEN_CACHE[tok] = (time.time(), sid)
    return sid


_SHARE_META_FIELDS = ("session_id", "title", "status", "model", "backend",
                      "harness_id", "harness_name", "event_count", "elapsed", "finished_at")


@app.get("/share/{token}/meta")
async def share_meta(token: str) -> dict:
    sid = await _share_sid(token)
    if not sid:
        raise HTTPException(404, "share not found")
    base = await _trace_base(sid)
    m = {}
    if base:
        b = await _blob_get(_manifest_key(base), kb=TRACE_KB)
        if b:
            try:
                m = json.loads(b)
            except Exception:  # noqa: BLE001
                m = {}
    return {k: m.get(k) for k in _SHARE_META_FIELDS} | {"session_id": sid}


@app.get("/share/{token}/turns")
async def share_turns(token: str) -> dict:
    sid = await _share_sid(token)
    if not sid:
        raise HTTPException(404, "share not found")
    return await _session_turns_data(sid)


@app.get("/share/{token}/files")
async def share_files(token: str) -> dict:
    sid = await _share_sid(token)
    if not sid:
        raise HTTPException(404, "share not found")
    cached = await _ws_files(sid)
    files = [{"path": path, "bytes": len(data),
              "media_type": mimetypes.guess_type(path)[0] or "application/octet-stream"}
             for path, data in sorted((cached or {}).items())]
    files.sort(key=lambda f: f["path"])
    return {"count": len(files), "files": files}


@app.get("/share/{token}/f/{path:path}")
async def share_file(token: str, path: str) -> Response:
    sid = await _share_sid(token)
    if not sid:
        raise HTTPException(404, "share not found")
    resp = await _serve_workspace_path(sid, path)
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.get("/v1/responses/{response_id}/input_items")
async def list_input_items(response_id: str, request: Request, limit: int = 20, order: str = "asc"):
    principal = await _principal(request)
    rec = await _resp_get(response_id)
    if not rec:
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")
    if str(rec.get("_org") or principal.get("org", "")) != principal.get("org", ""):
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")   # LIVE-B: object-level ownership
    data = list(rec.get("_input") or [])
    if order == "desc":
        data.reverse()
    data = data[:limit]
    return {"object": "list", "data": data, "first_id": None, "last_id": None, "has_more": False}


@app.post("/v1/responses/{response_id}/cancel")
async def cancel_response(response_id: str, request: Request):
    """Cancel a response's in-flight turn. Unlike the old no-op (it guarded on
    statuses that are never stored and never touched the runner), this is a real
    monotonic cancellation that propagates to the sandbox — and it enforces
    object-level ownership so one org can't cancel another's response (LIVE-B)."""
    principal = await _principal(request)
    org = principal.get("org", "")
    rec = await _resp_get(response_id)
    if not rec:
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")
    # Ownership (LIVE-B): the resolved principal must own this response. 404 (not 403)
    # so a cross-org probe can't even confirm the id exists.
    if str(rec.get("_org") or "") != org:
        raise uhp_error(404, "response_not_found", "No response with that id.", "response_id")
    sid = str(rec.get("_session_id") or "")
    # PRIMARY (safe, cross-replica): a durable per-RESPONSE monotonic terminal latch. The turn's
    # own loop checks resp_is_cancelled(its resp_id) at every stage and self-terminates within
    # ~one poll — this can NEVER affect a newer turn (different resp_id). resp_mark_terminal
    # returns the record's runner_turn_id, letting us safely take the fast path below.
    store_rec: dict = {}
    if control_store.enabled():
        try:
            store_rec = await control_store.resp_mark_terminal(
                org, response_id, "cancelled", int(_GW_MAX_TURN_S)) or {}
        except Exception:  # noqa: BLE001
            pass
    was_live = str(rec.get("status") or "") in ("running", "in_progress", "queued", "starting")
    if was_live and sid:
        v = await _vertex_get(sid)
        v_rt = str((v or {}).get("runner_turn_id") or "")
        my_rt = str(store_rec.get("runner_turn_id") or "")
        v_live = bool({"running", "starting"} & {str((v or {}).get("turn_status") or ""),
                                                 str((v or {}).get("status") or "")})
        # FAST PATH — kill the sandbox turn immediately, but ONLY when we can prove this response
        # owns the live sandbox: its durably-recorded runner_turn_id matches the vertex's current
        # one (cross-replica safe). Without the store, fall back to the same-replica in-memory
        # current-turn hint. If neither confirms ownership we do NOT kill (a newer turn may own the
        # sid) — the durable latch above already stops THIS turn via its self-check.
        current = str((_session_trace.get(sid) or {}).get("last_response_id") or "")
        owns_live = bool(v and v_live and my_rt and v_rt and my_rt == v_rt)
        hint_owns = bool(v and v_live and not control_store.enabled()
                         and (current == response_id or (not current and not v_rt)))
        if owns_live or hint_owns:
            await _stop_session(org, sid, v, rid_hint=response_id)
        else:
            # Not confirmed as the live turn: latch this record cancelled in blob + graph (keep
            # them consistent) and let the turn's own resp_is_cancelled check settle it.
            rec["status"] = "cancelled"
            try:
                await _blob_put(f"responses/{response_id}.json",
                                json.dumps(rec, default=str).encode(), kb=RESP_BLOB_KB)
                await _vg_upsert("HarnessResponse", response_id, {"status": "cancelled"})
            except Exception:  # noqa: BLE001
                pass
    rec = await _resp_get(response_id) or rec
    return _strip_internal(rec)


# ── files: upload (in) + container content (out) ────────────────────────────────────────
@app.post("/v1/files")
async def upload_file(request: Request, purpose: str = Form("user_data"), file: UploadFile = File(...)):
    """Upload a file for use in later turns. STREAMED to durable storage (HR-INF-015): the
    gateway never holds the whole payload (Starlette already spools large multipart parts to
    disk; we relay it in chunks to the blob plane, whose staged-block commit-at-end makes a
    truncated stream harmless). Capped: uploads are inlined base64 into the runner's turn body,
    so the cap bounds turn-payload RAM too — matching the engine's 25 MiB attachment cap."""
    await _principal(request)
    if BACKING.mode == "vg" and not VG_GATEWAY_URL:
        raise HTTPException(503, "file storage is not configured")
    # Fail fast on the declared size when present (well-behaved clients send Content-Length);
    # the in-stream guard below still catches chunked/lying uploads.
    _decl = request.headers.get("content-length")
    if _decl and _decl.isdigit() and int(_decl) > _UPLOAD_MAX_BYTES + 16384:  # + multipart framing
        raise HTTPException(413, f"file exceeds the {_UPLOAD_MAX_BYTES // (1024*1024)} MiB upload limit")
    fid = _rid("file")
    nbytes = 0

    async def _pipe():
        nonlocal nbytes
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            nbytes += len(chunk)
            if nbytes > _UPLOAD_MAX_BYTES:
                raise HTTPException(413, f"file exceeds the {_UPLOAD_MAX_BYTES // (1024*1024)} MiB upload limit")
            yield chunk

    h = _blob_headers("application/octet-stream")
    try:
        r = await _client().put(_blob_url(f"uploads/{fid}", RESP_BLOB_KB),
                                headers=h, content=_pipe())
    except HTTPException:
        raise                     # the 413 from _pipe surfaces verbatim
    except httpx.HTTPError as e:  # early server reject can surface as a WriteError, not a status
        raise HTTPException(502, "durable upload failed") from e
    if r.status_code >= 400:
        raise HTTPException(502, "durable upload failed")
    await _blob_put(f"uploads/{fid}.meta", json.dumps(
        {"filename": file.filename, "media_type": file.content_type or "application/octet-stream"}).encode(),
        kb=RESP_BLOB_KB)
    return {"id": fid, "object": "file", "bytes": nbytes, "created_at": int(time.time()),
            "filename": file.filename, "purpose": purpose}


# ── session workspace files (list + download-by-id) ─────────────────────────────
# The agent's workspace persists between turns as a checkpoint tarball. These helpers expose it
# read-only: list every user-visible file, and serve any of them through the SAME download endpoint
# the produced-file cards already use. Files captured as turn outputs keep their `cfile_…` id; any
# other workspace file gets a stable synthetic id `wf_<urlsafe-b64(path)>` that the download endpoint
# resolves by extracting from the checkpoint. One id scheme, one download URL, everything reachable.
_WS_HIDE_PREFIXES = (".git/", ".harness/", ".claude/", ".codex/", "tmp/",
                     "node_modules/", "__pycache__/", ".venv/", "venv/", ".cache/", ".next/")
_WS_HIDE_NAMES = {".gitignore", "AGENTS.md", "CLAUDE.md"}


def _ws_visible(path: str) -> bool:
    """User-visible workspace file? Hides VCS/agent-internal/scratch paths (same families the
    produced-file collector excludes) so the listing reads like the agent's actual deliverables."""
    if not path or path.endswith("/"):
        return False
    if path in _WS_HIDE_NAMES or path.startswith("."):
        return False
    return not any(path.startswith(p) or f"/{p}" in path for p in _WS_HIDE_PREFIXES)


def _wf_id(path: str) -> str:
    return "wf_" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def _wf_path(file_id: str) -> str | None:
    try:
        b = file_id[3:]
        return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()
    except Exception:  # noqa: BLE001
        return None


async def _workspace_tar(sid: str) -> tarfile.TarFile | None:
    """Open the session's checkpoint tarball for extraction, from a DISK-cached copy
    (HR-INF-015): the blob is streamed straight to a local file — never held whole in
    RAM — and tarfile decompresses from disk, so extraction memory is O(member)."""
    now = time.time()
    hit = _WS_TAR_CACHE.get(sid)
    if hit and now - hit[0] < _WS_TAR_TTL and os.path.isfile(hit[1]):
        path = hit[1]
    else:
        # Single-flight per sid: concurrent misses would each stream the (possibly GB) tarball.
        lock = _WS_TAR_LOCKS.setdefault(sid, asyncio.Lock())
        async with lock:
            hit = _WS_TAR_CACHE.get(sid)
            if hit and time.time() - hit[0] < _WS_TAR_TTL and os.path.isfile(hit[1]):
                return await asyncio.to_thread(_open_tar_or_none, hit[1], sid)
            path = await _ws_tar_download(sid)
            if path is None:
                return None
    return await asyncio.to_thread(_open_tar_or_none, path, sid)


def _open_tar_or_none(path: str, sid: str) -> tarfile.TarFile | None:
    try:
        return tarfile.open(name=path, mode="r:gz")
    except Exception:  # noqa: BLE001
        _ws_tar_evict(sid)
        return None


async def _ws_tar_download(sid: str) -> str | None:
    """Stream the checkpoint blob to a disk file and insert it into the cache. Lock held by caller."""
    fd, path = tempfile.mkstemp(suffix=".tgz", dir=_WS_TAR_DIR)
    nbytes = 0
    try:
        if not _blob_streaming():
            # Local backing: no HTTP surface to stream from — read then write, and fall through to
            # the shared cache-insert tail below so both paths bound and evict identically.
            tar = await BACKING.blob.get(BLOB_KB, _ws_blob(sid))
            if not tar:
                raise RuntimeError("no checkpoint")
            with os.fdopen(fd, "wb") as out:
                fd = -1
                out.write(tar)
                nbytes = len(tar)
        else:
            resp = await _blob_open_stream(_ws_blob(sid))
            try:
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                with os.fdopen(fd, "wb") as out:
                    fd = -1
                    async for chunk in resp.aiter_bytes():
                        out.write(chunk)
                        nbytes += len(chunk)
            finally:
                await resp.aclose()
    except Exception:  # noqa: BLE001 — no checkpoint / transient blob failure
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    if not nbytes:
        try:
            os.unlink(path)
        except OSError:
            pass
        return None
    while len(_WS_TAR_CACHE) >= _WS_TAR_MAX:   # bounded: evict oldest (unlinks its file)
        _ws_tar_evict(min(_WS_TAR_CACHE, key=lambda k: _WS_TAR_CACHE[k][0]))
    _ws_tar_evict(sid)   # replace any rival entry without leaking its file
    _WS_TAR_CACHE[sid] = (time.time(), path)
    return path


async def _ws_files(sid: str) -> dict[str, bytes] | None:
    """All user-visible workspace files, extracted in ONE decompression pass and cached."""
    hit = _WS_FILES_CACHE.get(sid)
    if hit and time.time() - hit[0] < _WS_FILES_TTL:
        return hit[1]
    tf = await _workspace_tar(sid)
    if tf is None:
        return None
    out: dict[str, bytes] = {}
    total = 0
    with tf:
        for m in tf.getmembers():
            if not m.isreg():
                continue
            path = m.name[2:] if m.name.startswith("./") else m.name
            if not _ws_visible(path):
                continue
            if m.size > _WS_FILE_CAP or total + m.size > _WS_TOTAL_CAP:
                continue                       # oversized: served via the single-member fallback
            f = tf.extractfile(m)
            if f is None:
                continue
            out[path] = f.read()
            total += m.size
    while len(_WS_FILES_CACHE) >= _WS_FILES_MAX:
        _WS_FILES_CACHE.pop(min(_WS_FILES_CACHE, key=lambda k: _WS_FILES_CACHE[k][0]), None)
    _WS_FILES_CACHE[sid] = (time.time(), out)
    return out


async def _container_file_bytes(container_id: str, file_id: str) -> tuple[bytes, str, str] | None:
    """→ (data, media_type, filename) for either id form: a captured `cfile_…` blob, or a synthetic
    `wf_…` workspace-path id extracted from the session checkpoint."""
    if file_id.startswith("wf_"):
        path = _wf_path(file_id)
        if not path or not _ws_visible(path):     # refuse crafted ids into .git/.harness internals
            return None
        cached = await _ws_files(container_id)
        if cached is not None and path in cached:
            data = cached[path]
            media = mimetypes.guess_type(path)[0] or "application/octet-stream"
            return data, media, path.rsplit("/", 1)[-1]
        tf = await _workspace_tar(container_id)
        if tf is None:
            return None
        with tf:
            for name in (f"./{path}", path):
                try:
                    m = tf.getmember(name)
                except KeyError:
                    continue
                if not m.isreg():
                    return None
                f = tf.extractfile(m)
                data = f.read() if f else None
                if data is None:
                    return None
                media = mimetypes.guess_type(path)[0] or "application/octet-stream"
                return data, media, path.rsplit("/", 1)[-1]
        return None
    data = await _blob_get(f"containers/{container_id}/{file_id}", kb=RESP_BLOB_KB)
    if data is None:
        return None
    media, fname = "application/octet-stream", file_id
    meta_b = await _blob_get(f"containers/{container_id}/{file_id}.meta", kb=RESP_BLOB_KB)
    if meta_b:
        try:
            m = json.loads(meta_b)
            media, fname = m.get("media_type", media), m.get("filename", fname)
        except Exception:  # noqa: BLE001
            pass
    return data, media, fname


@app.get("/v1/sessions/{sid}/files")
async def session_workspace_files(sid: str, request: Request, changed: bool = False) -> dict:
    """List files in the session's workspace, each with a `file_id` the download endpoint
    (GET /v1/containers/{sid}/files/{file_id}/content) serves.

    - default: EVERY user-visible file in the agent's working directory (the full accumulated
      set across all turns, from the last checkpoint).
    - ?changed=true: only the files the agent created/modified in the MOST RECENT turn.
    """
    await _owned_session(request, sid)   # V1C02-004: session-scoped files, org-owned only
    if changed:
        blob = await _blob_get(f"sessions/{sid}/changed.json", kb=RESP_BLOB_KB)
        items = []
        if blob:
            try:
                items = (json.loads(blob) or {}).get("files") or []
            except Exception:  # noqa: BLE001
                items = []
        files = [{"object": "file", "id": it["file_id"], "container_id": sid,
                  "filename": it["path"].rsplit("/", 1)[-1],
                  "path": it["path"], "bytes": it.get("bytes"),
                  "media_type": mimetypes.guess_type(it["path"])[0] or "application/octet-stream",
                  "file_id": it["file_id"], "download_url": _file_url(sid, it["file_id"])}
                 for it in items if it.get("path") and it.get("file_id")]
        files.sort(key=lambda f: f["path"])
        return {"session_id": sid, "changed": True, "count": len(files), "files": files}
    tf = await _workspace_tar(sid)
    if tf is None:
        raise HTTPException(404, "no workspace for this session yet — run a task first")
    # Captured-output ids by filename (so listed entries reuse the id the response already cited).
    cfile_by_name: dict[str, str] = {}
    listing = await _blob_list(f"containers/{sid}/", limit=200, kb=RESP_BLOB_KB)
    metas = [i for i in (listing.get("items") or []) if str(i.get("file_id", "")).endswith(".meta")]
    for it in metas[:200]:
        meta_b = await _blob_get(it["file_id"], kb=RESP_BLOB_KB)
        if not meta_b:
            continue
        try:
            fname = json.loads(meta_b).get("filename")
        except Exception:  # noqa: BLE001
            continue
        cfile = it["file_id"].rsplit("/", 1)[-1][: -len(".meta")]
        if fname:
            cfile_by_name.setdefault(str(fname), cfile)
    files = []
    with tf:
        for m in tf.getmembers():
            if not m.isreg():
                continue
            path = m.name[2:] if m.name.startswith("./") else m.name
            if not _ws_visible(path):
                continue
            fid = cfile_by_name.get(path) or _wf_id(path)
            files.append({"object": "file", "id": fid, "container_id": sid,
                          "filename": path.rsplit("/", 1)[-1],
                          "path": path, "bytes": m.size,
                          "media_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
                          "file_id": fid,
                          "download_url": _file_url(sid, fid)})
    files.sort(key=lambda f: f["path"])
    return {"session_id": sid, "count": len(files), "files": files}


_ARCHIVE_MAX_BYTES = 512 * 1024 * 1024   # in-memory zip cap; beyond this, download files singly


class WorkspaceWrite(BaseModel):
    content: str | None = None        # text
    content_b64: str | None = None    # bytes


@app.get("/v1/sessions/{sid}/files/{path:path}")
async def read_session_file(sid: str, path: str, request: Request) -> Response:
    """Read ONE file from a session's workspace, by path — the mirror of the PUT below.

    This goes through BACKING.workspace, which is the whole point: self-hosted, that is the live
    directory the agent is writing into RIGHT NOW, so an app sees a file the moment a tool call
    creates it. The listing route next door reads the checkpoint tarball instead, which only
    exists once a turn ENDS — and an app polling it for a file the agent had already written
    minutes ago sits there showing a spinner for something that is on disk.

    Unlike writing, reading during a turn is safe and is exactly what a live app wants: a
    half-written deck is better than no deck, and the next read gets the rest.
    """
    await _owned_session(request, sid)
    data = await BACKING.workspace.read(sid, path)
    if data is None:
        raise uhp_error(404, "file_not_found",
                        f"No file '{path}' in this session's workspace.", "path")
    media = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return Response(content=data, media_type=media,
                    headers={"cache-control": "no-store"})


@app.put("/v1/sessions/{sid}/files/{path:path}")
async def write_session_file(sid: str, path: str, body: WorkspaceWrite, request: Request) -> dict:
    """Write or replace one file in a session's workspace.

    This is what lets an app built on a Harness own state the agent also edits — the slides kit
    keeps deck.json here, so the canvas and the agent read and write the same file rather than two
    copies that drift.

    Where that file physically lives differs completely by deployment, which is why it goes
    through BACKING.workspace: a live directory on the data volume self-hosted, the checkpoint
    tarball in blob storage hosted, where between turns that archive IS the workspace.

    REFUSED WHILE A TURN IS RUNNING, and that is the whole conflict story. Hosted, the live
    sandbox would overwrite this at its next checkpoint, so the write would appear to succeed and
    then vanish. Self-hosted, the agent may be editing the same file. Blocking is honest; both
    sides silently racing is not.
    """
    # The SAME ownership check every other session route uses. Hand-rolling a second one is how
    # this shipped broken: it compared v["org"], but a session vertex carries the owner in
    # `tenant`, so every write 404'd on a session the caller could plainly read.
    _org, v = await _owned_session(request, sid)

    live = {"running", "starting"} & {str(v.get("turn_status") or ""), str(v.get("status") or "")}
    if live:
        raise uhp_error(409, "session_busy",
                        "The agent is working on this session. Wait for the turn to finish "
                        "before writing to its workspace.")

    if body.content_b64 is not None:
        try:
            data = base64.b64decode(body.content_b64)
        except Exception:  # noqa: BLE001
            raise uhp_error(400, "invalid_request", "content_b64 is not valid base64.") from None
    elif body.content is not None:
        data = body.content.encode()
    else:
        raise uhp_error(400, "invalid_request", "Provide content or content_b64.")

    if len(data) > _WS_WRITE_MAX:
        raise uhp_error(413, "payload_too_large",
                        f"A workspace file written this way is limited to {_WS_WRITE_MAX} bytes.")

    ok = await BACKING.workspace.write(sid, path, data)
    if not ok:
        # The only ways to get here are a path that tried to leave the workspace and a storage
        # failure. Both are the caller's problem to see, not something to swallow.
        raise uhp_error(400, "write_failed",
                        "Could not write that path. It must be inside the session workspace.")
    return {"session_id": sid, "path": path, "bytes": len(data), "written": True}


@app.get("/v1/sessions/{sid}/files/archive")
async def session_files_archive(sid: str, request: Request, changed: bool = False, files: str = ""):
    """Every artifact of a session (or one turn) as a single zip, preserving the workspace's
    folder hierarchy — each entry's path inside the zip is the file's relative path.

    - default: every user-visible file in the working directory (same set as GET .../files)
    - ?changed=true: only the files created/modified in the MOST RECENT turn
    - ?files=fid1,fid2: exactly those file ids (e.g. one specific turn's cited outputs)
    """
    await _owned_session(request, sid)   # V1C02-004: session-scoped files, org-owned only
    _reap_spool_dir()   # sweep ZIP temps/orphaned tars whose BackgroundTask cleanup was skipped
    want_ids = [f.strip() for f in files.split(",") if f.strip()][:200] if files else None
    # The ZIP is SPOOLED TO DISK, never built in RAM (HR-INF-015): whole-workspace mode streams
    # each tar member from the disk-cached tarball straight into the zip entry (O(copy-buffer)
    # memory); the id-scoped modes write their capped per-file payloads. FileResponse streams it
    # out; the temp file is removed after the response is sent.
    fd, zpath = tempfile.mkstemp(suffix=".zip", dir=_WS_TAR_DIR)
    os.close(fd)
    nput = 0
    total = 0
    try:
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            seen: set[str] = set()

            def _add_bytes(p: str, data: bytes) -> None:
                nonlocal nput, total
                p = p.lstrip("/")
                if p in seen:        # duplicate ids in ?files= — keep the first
                    return
                seen.add(p)
                total += len(data)
                if total > _ARCHIVE_MAX_BYTES:
                    raise HTTPException(413, "workspace too large for one archive — download files individually")
                z.writestr(p, data)
                nput += 1

            if want_ids:
                for fid in want_ids:
                    got = await _container_file_bytes(sid, fid)
                    if got:
                        data, _media, fname = got
                        _add_bytes(fname, data)
            elif changed:
                blob = await _blob_get(f"sessions/{sid}/changed.json", kb=RESP_BLOB_KB)
                try:
                    items = ((json.loads(blob) or {}).get("files") or []) if blob else []
                except Exception:  # noqa: BLE001
                    items = []
                for it in items[:200]:
                    fid, path = it.get("file_id"), it.get("path")
                    if not (fid and path):
                        continue
                    got = await _container_file_bytes(sid, fid)
                    if got:
                        _add_bytes(path, got[0])
            else:
                tf = await _workspace_tar(sid)
                if tf is None:
                    raise HTTPException(404, "no workspace for this session yet — run a task first")

                def _zip_workspace() -> tuple[int, int]:
                    # Pure sync file work (disk tar in, disk zip out) — runs in a worker thread so
                    # GB-scale gzip-decompress + deflate never stalls the event loop (SSE streams,
                    # turn relays, and health probes keep flowing).
                    n, tot = 0, 0
                    with tf:
                        for m in tf.getmembers():
                            if not m.isreg():
                                continue
                            path = m.name[2:] if m.name.startswith("./") else m.name
                            if not _ws_visible(path) or path.lstrip("/") in seen:
                                continue
                            tot += m.size
                            if tot > _ARCHIVE_MAX_BYTES:
                                raise HTTPException(413, "workspace too large for one archive — download files individually")
                            fh = tf.extractfile(m)
                            if fh is None:
                                continue
                            seen.add(path.lstrip("/"))
                            # Explicit ZipInfo: bare ZipInfo defaults to STORED (uncompressed),
                            # epoch-1980 mtime, and zero permissions — set them all properly.
                            zi = zipfile.ZipInfo(path.lstrip("/"), date_time=time.localtime(m.mtime)[:6])
                            zi.compress_type = zipfile.ZIP_DEFLATED
                            zi.external_attr = (m.mode & 0xFFFF) << 16
                            with fh, z.open(zi, "w") as zw:
                                shutil.copyfileobj(fh, zw, 1024 * 1024)
                            n += 1
                    return n, tot

                _n, _tot = await asyncio.to_thread(_zip_workspace)
                nput += _n
                total += _tot
        if not nput:
            raise HTTPException(404, "no files to archive")
    except BaseException:
        try:
            os.unlink(zpath)
        except OSError:
            pass
        raise
    scope = "turn" if (want_ids or changed) else "all"
    bg = BackgroundTask(os.unlink, zpath)
    return FileResponse(zpath, media_type="application/zip", background=bg,
                        headers={"Content-Disposition":
                                 f'attachment; filename="{sid[:20]}-{scope}-files.zip"'})


@app.get("/v1/containers/{container_id}/files/{file_id}/content")
async def container_file_content(container_id: str, file_id: str, request: Request):
    await _owned_session(request, container_id)   # V1C02-004: container_id IS the session id
    got = await _container_file_bytes(container_id, file_id)
    if got is None:
        raise HTTPException(404, "file not found")
    data, media, fname = got
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# Office types with no faithful browser renderer → convert to PDF server-side (LibreOffice) so the
# UI can preview them inline. docx/xlsx render client-side; this covers pptx/ppt/odp (+ doc/xls).
_PDF_CONVERTIBLE = {"pptx", "ppt", "pptm", "odp", "doc", "docx", "odt", "rtf", "xls", "xlsx", "xlsm", "ods"}
_SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")


def _convert_to_pdf(data: bytes, ext: str) -> bytes | None:
    """Blocking: run LibreOffice headless to convert one office file (bytes) to PDF bytes."""
    if not _SOFFICE:
        return None
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, f"in.{ext}")
        with open(src, "wb") as f:
            f.write(data)
        env = {**os.environ, "HOME": td}
        try:
            subprocess.run([_SOFFICE, "--headless", "--norestore", "--convert-to", "pdf",
                            "--outdir", td, src], env=env, capture_output=True, timeout=120, check=False)
        except Exception:  # noqa: BLE001
            return None
        out = os.path.join(td, "in.pdf")
        if os.path.exists(out):
            with open(out, "rb") as f:
                return f.read()
    return None


@app.get("/v1/containers/{container_id}/files/{file_id}/pdf")
async def container_file_pdf(container_id: str, file_id: str, request: Request):
    """Return a PDF rendering of an office file (cached). Lets the UI preview pptx/ppt/odp inline."""
    await _owned_session(request, container_id)   # V1C02-004: container_id IS the session id
    cache_key = f"previews/{container_id}/{file_id}.pdf"
    cached = await _blob_get(cache_key, kb=RESP_BLOB_KB)
    if cached is not None:
        return Response(content=cached, media_type="application/pdf")
    got = await _container_file_bytes(container_id, file_id)   # cfile_… blob or wf_… workspace path
    if got is None:
        raise HTTPException(404, "file not found")
    data, _media, fname = got
    ext = (fname.rsplit(".", 1)[-1] if "." in fname else "").lower()
    if ext == "pdf":
        return Response(content=data, media_type="application/pdf")
    if ext not in _PDF_CONVERTIBLE:
        raise HTTPException(415, f"no pdf preview for .{ext}")
    if not _SOFFICE:
        # Distinguish "this build cannot preview documents" from "this document failed to
        # convert" — they need different actions, and one generic error told the user neither.
        raise HTTPException(501, "document preview is not available in this build")
    pdf = await asyncio.to_thread(_convert_to_pdf, data, ext)
    if pdf is None:
        raise HTTPException(502, f"could not convert this .{ext} file")
    await _blob_put(cache_key, pdf, kb=RESP_BLOB_KB)   # cache so repeat previews are instant
    return Response(content=pdf, media_type="application/pdf")


# ── per-org API keys (public-surface Bearer auth). Mint/list/revoke gated by the internal key
#    (the web BFF, already behind the engine JWT + org-admin check, calls these). ───────────
class KeyBody(BaseModel):
    member_id: str | None = None
    name: str | None = None
    workspace: str | None = None           # workspace (Space id) this key is scoped to
    workspace_default: bool = False        # the org's Default Workspace (legacy unstamped data belongs to it)


@app.post("/v1/orgs/{org}/keys")
async def mint_key(org: str, body: KeyBody, request: Request) -> dict:
    await _owned_org(request, org)
    tok = "sk-hr-" + uuid.uuid4().hex + uuid.uuid4().hex
    h = _hash_key(tok)
    # Graph FIRST and it must succeed (raise_on_fail): the graph is the source of truth + the
    # backstop the hot read falls to on a store miss/expiry. A silently-failed graph write would
    # let a store-only key work for one TTL then permanently 401 (HR-INF-010 review #3).
    await _vg_upsert("HarnessApiKey", h, {"kind": "harness_api_key", "org": org,
                     "member": body.member_id or "", "name": body.name or "default",
                     "workspace": body.workspace or "",
                     "workspace_default": "1" if body.workspace_default else "",
                     "revoked": "0", "created_at": str(time.time())}, raise_on_fail=True)
    # Then dual-write the control-store hot-read doc SYNCHRONOUSLY — the key is shown once and used
    # on the very next request. If this fails, the graph write already succeeded, so the first
    # resolve misses -> reads the graph -> backfills; no 401 window.
    if control_store.enabled():
        try:
            await control_store.apikey_put(h, org, body.member_id or "", body.workspace or "",
                                           bool(body.workspace_default))
        except Exception:  # noqa: BLE001 — graph is authoritative; resolve backfills on miss
            pass
    return {"id": h, "org": org, "name": body.name or "default", "created_at": int(time.time()),
            "workspace": body.workspace or "",
            "key": tok, "note": "store this key now; it is shown only once"}


@app.get("/v1/orgs/{org}/keys")
async def list_keys(org: str, request: Request) -> dict:
    await _owned_org(request, org)
    try:
        rows = await BACKING.graph.find("HarnessApiKey", {"org": org})
    except Exception:  # noqa: BLE001
        rows = []
    keys = [{"id": x.get("id"), "name": x.get("name"), "created_at": x.get("created_at"),
             "revoked": str(x.get("revoked")) in ("1", "true", "True"), "member": x.get("member"),
             "workspace": x.get("workspace") or "", "last_used": x.get("last_used") or ""}
            for x in rows]
    return {"keys": keys}


@app.delete("/v1/orgs/{org}/keys/{kid}")
async def revoke_key(org: str, kid: str, request: Request) -> dict:
    await _owned_org(request, org)
    # V1C02-005: the key must belong to THIS org — otherwise a caller could revoke another org's
    # key by id. Verify org ownership on the vertex before writing the tombstone.
    kv = await _vertex_get(kid)
    if kv and str(kv.get("org") or "") != org:
        raise HTTPException(404, "key not found")
    # Graph revoke FIRST and it MUST succeed (raise_on_fail): the graph is the backstop the hot
    # read falls to when the store doc expires. A silently-failed graph revoke would let the key
    # revive when its store tombstone lapses (HR-INF-010 review #2). Store tombstone is dual-written
    # after — instant revocation on the hot path; the graph guarantees it stays revoked.
    await _vg_upsert("HarnessApiKey", kid, {"revoked": "1"}, raise_on_fail=True)
    if control_store.enabled():
        try:
            await control_store.apikey_revoke(kid)
        except Exception:  # noqa: BLE001 — graph is authoritative; the store tombstone is a fast-path
            pass
    return {"id": kid, "revoked": True}


def _parse_jsonrpc(text: str) -> dict:
    """A streamable-HTTP MCP endpoint answers either as plain JSON or as SSE (`data: {…}`
    lines). Return the first JSON-RPC object found, whichever form."""
    t = (text or "").strip()
    if t.startswith("{"):
        try:
            return json.loads(t)
        except Exception:  # noqa: BLE001
            pass
    for line in t.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            body = line[5:].strip()
            if body.startswith("{"):
                try:
                    return json.loads(body)
                except Exception:  # noqa: BLE001
                    continue
    return {}


def _ssrf_check(url: str) -> str | None:
    """The ONE rule for whether this server may talk to an MCP endpoint.

    V1C02-006: gate a caller-supplied MCP URL before the server fetches it. HTTPS only; resolve
    EVERY DNS answer and reject loopback / link-local / RFC1918 / IPv6 private / cloud metadata
    (169.254.169.254 falls under link-local) so a hostname can't rebind to an internal target.
    Returns an error string to reject, or None to allow.

    Applied at BOTH config time (the console's Test connection) and run time (_harness_plugins).
    It used to run only on the test button, so the console refused a URL that a turn then connected
    to anyway: the check was advisory, the operator got a red error and a working server, and on a
    multi-tenant deployment the actual protection was absent. A test that does not predict run time
    is worse than no test.

    On a self-hosted instance the private-address rules are dropped, because there the "internal"
    network is the operator's own laptop: a local MCP server on 127.0.0.1 is a legitimate and
    common setup, the operator already has full access to that machine, and blocking it would
    remove a real capability while protecting nobody from anybody.
    """
    if _pool_is_local():
        from urllib.parse import urlparse
        try:
            u = urlparse(url)
        except Exception:  # noqa: BLE001
            return "invalid url"
        if u.scheme not in ("http", "https"):
            return "MCP endpoints must be http or https"
        return None if u.hostname else "url has no host"

    import ipaddress
    import socket
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
    except Exception:  # noqa: BLE001
        return "invalid url"
    if u.scheme != "https":
        return "only https MCP endpoints are allowed"
    host = u.hostname or ""
    if not host:
        return "url has no host"
    try:
        infos = socket.getaddrinfo(host, u.port or 443, proto=socket.IPPROTO_TCP)
    except Exception:  # noqa: BLE001
        return "host does not resolve"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return "target resolves to a disallowed (internal) address"
    return None


async def _mcp_list_tools(url: str, token: str) -> dict:
    """Probe a remote MCP server: initialize → notifications/initialized → tools/list. Returns
    {ok, server, tools:[{name,description}]} or {ok:false, error}. Used by the config UI's
    'Test connection'. Token may be a literal bearer or a vault:<ref> (resolved by the caller)."""
    ssrf = _ssrf_check(url)
    if ssrf:
        return {"ok": False, "error": ssrf}
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    if token:
        headers["authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    c = _client()
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "harnessrouter", "version": "1"}}}
    try:
        r = await c.post(url, headers=headers, content=json.dumps(init), timeout=20)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"unreachable: {str(e)[:140]}"}
    if r.status_code >= 400:
        return {"ok": False, "error": f"initialize returned HTTP {r.status_code}"}
    init_res = _parse_jsonrpc(r.text)
    server = ((init_res.get("result") or {}).get("serverInfo") or {}).get("name") or ""
    h2 = dict(headers)
    sid = r.headers.get("mcp-session-id")
    if sid:
        h2["mcp-session-id"] = sid
    try:
        await c.post(url, headers=h2, content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), timeout=20)
        r2 = await c.post(url, headers=h2, content=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}), timeout=20)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"tools/list failed: {str(e)[:140]}"}
    tl = _parse_jsonrpc(r2.text)
    if tl.get("error"):
        return {"ok": False, "error": str(tl["error"])[:160], "server": server}
    tools = [{"name": t.get("name", ""), "description": (t.get("description") or "")[:200]}
             for t in ((tl.get("result") or {}).get("tools") or [])]
    return {"ok": True, "server": server, "tools": tools}


class McpSecretBody(BaseModel):
    token: str


class McpTestBody(BaseModel):
    url: str
    auth: str | None = None   # literal bearer OR vault:<ref> (left blank → no auth)


@app.put("/v1/orgs/{org}/mcp-secrets/{ref}")
async def put_mcp_secret(org: str, ref: str, body: McpSecretBody, request: Request) -> dict:
    await _owned_org(request, org)
    """Store an MCP server bearer token in the vault under a stable ref, so the harness config
    stores only 'vault:<ref>' and the live token never lands in the graph. Stored in the org's
    own vault tenant when valid, else the global pool (dotted org ids aren't valid vault tenants)."""
    tenant = org if _vault_tenant_ok(org) else GLOBAL_TENANT
    # vault key names allow only [a-z0-9-] (same charset as harness-conn-/harness-policy- keys)
    safe = re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-") or "mcp"
    key = f"harness-mcp-{safe}"
    await _vault_put(tenant, key, body.token)
    return {"ref": f"vault:{key}", "tenant": tenant}


@app.post("/v1/orgs/{org}/mcp-test")
async def test_mcp(org: str, body: McpTestBody, request: Request) -> dict:
    await _owned_org(request, org)
    """Probe an MCP server (initialize + tools/list) so the config UI can validate a server and
    show its tools before saving. Resolves a vault:<ref> auth to the live token server-side."""
    if not body.url:
        raise HTTPException(400, "url required")
    token = await _resolve_mcp_auth(org, str(body.auth or ""))
    return await _mcp_list_tools(body.url, token)


# ── PUBLIC mcp-secret + mcp-test (Bearer sk-hr-... key; org resolved from the key) ─────
# Lets a vibe coder's agent vault an MCP bearer token and reference it as vault:<ref> on the
# harness config — so the live token never lands in the graph and never sits in plaintext config.
@app.put("/v1/mcp-secrets/{ref}")
async def put_mcp_secret_public(ref: str, body: McpSecretBody, request: Request) -> dict:
    org, _ = await _pub_org_member(request)
    tenant = org if _vault_tenant_ok(org) else GLOBAL_TENANT
    safe = re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-") or "mcp"
    key = f"harness-mcp-{safe}"
    await _vault_put(tenant, key, body.token)
    return {"ref": f"vault:{key}", "tenant": tenant}


@app.post("/v1/mcp-test")
async def test_mcp_public(body: McpTestBody, request: Request) -> dict:
    org, _ = await _pub_org_member(request)
    if not body.url:
        raise HTTPException(400, "url required")
    token = await _resolve_mcp_auth(org, str(body.auth or ""))
    return await _mcp_list_tools(body.url, token)


# ── Starter Kits ──────────────────────────────────────────────────────────────────────────────
# A kit is a whole product in a folder: the Harness it needs, and a UI that talks to that Harness
# as its backend. Both are baked into the image from HarnessRouter/starter-kit (see
# docker/install-kits.sh), so launching one provisions a Harness and opens an app that is already
# here — there is no service to deploy and no database to configure.
#
# Read from disk for the same reason skills are: a catalog compiled into source goes stale the
# moment the kit repo moves, and nothing says so.
_KITS_DIR = os.environ.get("HR_KITS_DIR", "/opt/harnessrouter/kits")


@functools.lru_cache(maxsize=1)
def _kits() -> dict:
    """{id: kit.json}, empty when the image was built without kits (a supported build)."""
    root = pathlib.Path(_KITS_DIR)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return {}
    try:
        ids = json.loads(manifest.read_text()).get("kits", [])
    except Exception:  # noqa: BLE001
        print(f"[kits] unreadable manifest at {manifest}", flush=True)
        return {}
    out: dict = {}
    for kid in ids:
        f = root / str(kid) / "kit.json"
        if not f.is_file():
            print(f"[kits] {kid} in manifest but not on disk — skipped", flush=True)
            continue
        try:
            out[str(kid)] = json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            print(f"[kits] {kid}/kit.json is not valid JSON — skipped", flush=True)
    if out:
        print(f"[kits] {len(out)} available: {', '.join(sorted(out))}", flush=True)
    return out


def _kit_skills(kit: dict) -> list[dict]:
    """A kit's own skills, read from its folder. Self-contained by design: a kit carries the
    skills its Harness needs rather than depending on what the image happens to bundle."""
    root = pathlib.Path(_KITS_DIR) / str(kit.get("id") or "")
    out: list[dict] = []
    for name in (kit.get("harness") or {}).get("skills") or []:
        folder = root / "skills" / str(name)
        if not (folder / "SKILL.md").is_file():
            print(f"[kits] {kit.get('id')}: skill {name} is declared but not on disk", flush=True)
            continue
        files = []
        for f in sorted(folder.rglob("*")):
            if not f.is_file() or f.stat().st_size > _SKILL_FILE_MAX:
                continue
            rel = f.relative_to(folder).as_posix()
            raw = f.read_bytes()
            try:
                files.append({"path": rel, "content": raw.decode()})
            except UnicodeDecodeError:
                files.append({"path": rel, "content_b64": base64.b64encode(raw).decode()})
        if files:
            out.append({"name": str(name), "enabled": True, "files": files})
    return out


# What to run a kit's Harness on, in preference order. A kit declares its own list in kit.json
# (`harness.recommended`), because the right pairing is a property of the work: a deck designer and
# a log analyser do not want the same agent or the same model.
#
# This is only the fallback for a kit that declares none. Note it is a preference ORDER, not a
# pin — which one is used depends on what the person actually connected, since pinning one base
# strands the common case: someone who wired only DeepSeek launching a kit that says "claude-code"
# would get a Harness that cannot run a single turn.
_KIT_BASE_PREFERENCE: tuple[tuple[str, str], ...] = (
    ("hermes", "deepseek-v4-pro"),
    ("codex", "gpt-5.6-sol"),
    ("claude-code", "claude-opus-5"),
)


def _kit_preference(kit: dict) -> list[tuple[str, str]]:
    """A kit's recommended pairings, or the default order when it names none."""
    out: list[tuple[str, str]] = []
    for r in (kit.get("harness") or {}).get("recommended") or []:
        base, model = str(r.get("base") or ""), str(r.get("model") or "")
        if base in _BASE_CATALOG:
            out.append((base, model))
        else:
            print(f"[kits] {kit.get('id')}: recommended base {base!r} is not a base — ignored",
                  flush=True)
    return out or list(_KIT_BASE_PREFERENCE)


async def _base_serves(org: str, base: str, model: str) -> bool:
    """Can this org actually run `model` on `base` right now?

    `_servable_models` returning None means a policy chain is in play, which is provider-level
    rather than per-model — the backend may attempt its whole catalog, so anything in that
    catalog counts as available.
    """
    b = _BASE_CATALOG.get(base)
    if not b:
        return False
    if model and model not in (_MODEL_CATALOG.get(b["backend"], {}).get("models") or []):
        return False
    servable = await _servable_models(org, b["backend"])
    return servable is None or not model or model in servable


async def _kit_choices(org: str, kit: dict) -> list[dict]:
    """This kit's recommended pairings, each with whether this org can run it.

    Unavailable options are returned rather than filtered out: "Claude Code — connect Anthropic to
    use this" tells someone what to do next, where a short list just looks like the product only
    supports two agents.
    """
    out: list[dict] = []
    picked = False
    for base, model in _kit_preference(kit):
        b = _BASE_CATALOG.get(base) or {}
        available = await _base_serves(org, base, model)
        recommended = available and not picked
        picked = picked or available
        out.append({"base": base, "model": model,
                    "baseLabel": b.get("label") or base,
                    "available": available, "recommended": recommended})
    return out


async def _kit_base(org: str, kit: dict) -> tuple[str, str]:
    """What a launch runs on when the caller expressed no preference: the recommended pairing.

    Falling through every option means nothing is wired up yet. The kit's own base is the last
    word then, so a launch still produces something coherent to look at rather than failing.
    """
    for c in await _kit_choices(org, kit):
        if c["recommended"]:
            print(f"[kits] {kit.get('id')}: base {c['base']} ({c['model']})", flush=True)
            return c["base"], c["model"]
    spec = kit.get("harness") or {}
    fallback = str(spec.get("base") or "claude-code")
    print(f"[kits] {kit.get('id')}: no connected provider serves a preferred model — "
          f"falling back to {fallback}", flush=True)
    return fallback, str(spec.get("default_model") or "")


# ── Built-in skills ───────────────────────────────────────────────────────────────────────────
# Baked into the image from HarnessRouter/skills (see docker/install-skills.sh). Read from disk,
# never hard-coded: the console used to carry its own list of four "built-in skills" that existed
# nowhere, with Replace and Disable buttons beside them acting on nothing.
#
# A built-in is implicit — a Harness stores nothing to use one. It stores an entry only to turn a
# default-off skill ON, or a default-on skill OFF. So changing what the image ships changes every
# Harness at once, and no Harness carries a stale copy of a skill's files.
_BUILTIN_SKILLS_DIR = os.environ.get("HR_BUILTIN_SKILLS_DIR", "/opt/harnessrouter/skills")
_SKILL_FILE_MAX = 2 * 1024 * 1024   # per file; a skill is instructions, not a data set


@functools.lru_cache(maxsize=1)
def _builtin_skills() -> dict:
    """{name: {"title","description","default_enabled","origin","files":[{path,content|content_b64}]}}

    Empty when the image was built without them (WITH_BUILTIN_SKILLS=0), which is a supported
    build, not an error — callers must render that honestly rather than as "none configured"."""
    root = pathlib.Path(_BUILTIN_SKILLS_DIR)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return {}
    try:
        entries = json.loads(manifest.read_text()).get("skills", [])
    except Exception:  # noqa: BLE001 — a corrupt manifest must not take the gateway down
        print(f"[skills] unreadable manifest at {manifest}", flush=True)
        return {}

    out: dict = {}
    for e in entries:
        name = (e.get("name") or "").strip()
        folder = root / name
        if not name or not (folder / "SKILL.md").is_file():
            print(f"[skills] {name or '(unnamed)'} in manifest but not on disk — skipped", flush=True)
            continue
        files: list[dict] = []
        for f in sorted(folder.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(folder).as_posix()
            raw = f.read_bytes()
            if len(raw) > _SKILL_FILE_MAX:
                print(f"[skills] {name}/{rel} exceeds {_SKILL_FILE_MAX} bytes — skipped", flush=True)
                continue
            try:                      # text where possible, so the stored form stays readable
                files.append({"path": rel, "content": raw.decode()})
            except UnicodeDecodeError:
                files.append({"path": rel, "content_b64": base64.b64encode(raw).decode()})
        if not files:
            continue
        out[name] = {"title": e.get("title") or name, "description": e.get("description") or "",
                     "default_enabled": bool(e.get("default_enabled")),
                     "origin": e.get("origin") or "", "files": files}
    if out:
        print(f"[skills] {len(out)} built-in: {', '.join(sorted(out))}", flush=True)
    return out


def _builtin_default_skills(seen: set[str] | None = None) -> list[dict]:
    """Built-ins that are on by default, minus any the harness has its own entry for.

    `seen` is what a stored harness has an opinion about — an override, or an explicit disable.
    An out-of-box harness has no stored record at all, so it passes nothing and gets the lot."""
    skip = seen or set()
    return [{"name": n, "files": m["files"], "content": None}
            for n, m in sorted(_builtin_skills().items())
            if n not in skip and m["default_enabled"]]


# ── custom harnesses (per-org, server-persisted; replaces the client localStorage seam) ───────
# ── base harness catalog ─────────────────────────────────────────────────────────────────
# What each base IS. The console used to carry its own copy of this — models, tools, skills and
# system prompts hard-coded in the frontend — which drifted from what the server actually runs: it
# advertised four built-in skills (docx/pdf/pptx/xlsx) that exist nowhere, and a model list that
# went stale the moment the catalog here changed. Anything a user sees about a base is served from
# this table plus the live model catalog, so there is one answer and it is the running one.
#
# `tools` carries BOTH the real name and how far disabling it actually goes, because those differ by
# runtime and the console must not imply a guarantee the runtime cannot keep (see the protocol's
# harnesses.md §4.3):
#   hard        — the CLI enforces it (claude: --disallowedTools takes these exact names).
#   instruction — no per-tool switch exists; the name is written into the agent doc as a request.
_BASE_CATALOG: dict[str, dict] = {
    "codex": {
        "label": "Codex", "backend": "codex", "status": "ready",
        "system_prompt": ("You are Codex, an autonomous software-engineering agent. You operate on "
                          "a real git workspace with shell access, reading and editing files and "
                          "running commands to complete the task, returning reviewable diffs and "
                          "results."),
        "tools": [("shell", "Shell"), ("apply_patch", "Apply Patch"), ("read_file", "File Read"),
                  ("write_file", "File Write"), ("git", "Git")],
        "tool_enforcement": "instruction",
    },
    "claude-code": {
        "label": "Claude Code", "backend": "claude", "status": "ready",
        "system_prompt": ("You are Claude Code, an agentic coding assistant. You work on a real "
                          "local git working tree with bash, edit files, run tests, and use "
                          "sub-agents to complete engineering tasks end to end."),
        # These are the names Claude Code's --disallowedTools accepts. They are the real thing, not
        # display labels: a label with a suffix would silently fail to match and disable nothing.
        "tools": [("Bash", "Bash"), ("Read", "Read"), ("Edit", "Edit"), ("Write", "Write"),
                  ("Grep", "Grep"), ("Glob", "Glob"), ("WebFetch", "WebFetch"),
                  ("WebSearch", "WebSearch"), ("Task", "Task (subagents)")],
        "tool_enforcement": "hard",
    },
    "hermes": {
        "label": "Hermes", "backend": "hermes", "status": "ready",
        "system_prompt": ("You are Hermes, a self-improving autonomous agent. You work on a real "
                          "project workspace with shell and file access, complete tasks end to end, "
                          "and build a persistent memory and skill library from what you learn."),
        "tools": [("terminal", "Terminal"), ("read_file", "File Read"), ("write_file", "File Write"),
                  ("patch", "Patch"), ("search_files", "Search"), ("web_search", "Web Search"),
                  ("web_extract", "Web Extract")],
        "tool_enforcement": "instruction",
    },
}

# Bases this server can execute. Derived from the catalog above so the two cannot disagree —
# `claude` is accepted as an alias for `claude-code` because existing harnesses store it.
_SUPPORTED_BASES = tuple(_BASE_CATALOG) + ("claude",)


def _require_supported_base(base: str) -> str:
    b = (base or "").strip().lower()
    if b not in _SUPPORTED_BASES:
        raise uhp_error(422, "unsupported_base",
                        f"This server cannot run the harness base '{base}'.", "base",
                        {"supported": list(_SUPPORTED_BASES)})
    return b


class HarnessBody(BaseModel):
    name: str
    base: str
    base_label: str | None = None
    default_model: str | None = None
    system_prompt: str | None = None
    mcp_servers: list | None = None
    skills: list | None = None
    disabled_tools: list | None = None     # inherited/built-in tool names the harness disabled
    max_step: int | None = None            # default agent step budget for this harness's turns
    timeout_seconds: int | None = None     # default per-turn wall-clock cap
    additional_headers: list | None = None  # declared header NAMES callers may pass per request


def _harness_out(v: dict) -> dict:
    """VG vertex (snake_case, JSON-string lists) -> the frontend CustomHarness shape (camelCase)."""
    def _parse(s):
        try:
            return json.loads(s) if s else []
        except Exception:  # noqa: BLE001
            return []
    try:
        created = int(v.get("created_at") or 0)
    except Exception:  # noqa: BLE001
        created = 0
    return {"id": v.get("id"), "name": v.get("name"), "base": v.get("base"),
            # The starter kit that provisioned this Harness, when one did. The kit's app uses it
            # to find its own Harness instead of asking the user to choose from a list.
            "kit": v.get("kit") or None,
            "baseLabel": v.get("base_label") or v.get("base"),
            "defaultModel": v.get("default_model") or "",
            "systemPrompt": v.get("system_prompt") or "",
            "mcpServers": _parse(v.get("mcp_servers")), "skills": _parse(v.get("skills")),
            "disabledTools": [t for t in _parse(v.get("disabled_tools")) if isinstance(t, str)],
            "additionalHeaders": [h for h in _parse(v.get("additional_headers")) if isinstance(h, str) and h.strip()],
            "maxStep": int(v.get("max_step")) if str(v.get("max_step") or "").isdigit() else None,
            "timeoutSeconds": int(v.get("timeout_seconds")) if str(v.get("timeout_seconds") or "").isdigit() else None,
            "member": v.get("member") or "", "workspace": v.get("workspace") or "", "createdAt": created}


async def _vg_list_by_org(label: str, org: str) -> list[dict]:
    return await BACKING.graph.find(label, {"org": org})


def _harness_props(body: HarnessBody) -> dict:
    base = _require_supported_base(body.base)   # refuse at create, not at the first task
    return {"name": body.name, "base": base, "base_label": body.base_label or base,
            "default_model": body.default_model or "", "system_prompt": body.system_prompt or "",
            "mcp_servers": json.dumps(body.mcp_servers or []), "skills": json.dumps(body.skills or []),
            "disabled_tools": json.dumps(body.disabled_tools or []),
            "additional_headers": json.dumps([str(h).strip() for h in (body.additional_headers or [])
                                              if isinstance(h, str) and str(h).strip()]),
            "max_step": str(body.max_step) if body.max_step else "",
            "timeout_seconds": str(body.timeout_seconds) if body.timeout_seconds else ""}


_WS_WRITE_MAX = 4 * 1024 * 1024   # an app writing its own state, not an upload path
_SKILL_INLINE_MAX = 48_000   # keep the vertex `skills` prop safely under the 64k value cap


async def _skills_prepare(skills: list | None) -> list:
    """Validate + normalize harness skills at config time (HRP-008).

    Invalid bundles used to persist verbatim and then vanish silently at runtime
    (_write_skills skips nameless/payload-less entries). Reject them loudly here.
    Large inline bundles are offloaded to the skills/{id}.json blob — the exact
    key _harness_plugins resolves — so the vertex prop carries only
    {name, enabled, blob} and the bundle actually reaches the runner."""
    out: list = []
    for i, sk in enumerate(skills or []):
        if not isinstance(sk, dict):
            raise HTTPException(400, f"skills[{i}]: must be an object")
        name = sk.get("name") or sk.get("id")
        if not name:
            raise HTTPException(400, f"skills[{i}]: missing name")
        if str(sk.get("enabled")) in ("False", "false", "0"):
            out.append(sk)            # suppress-marker for an inherited built-in: no payload needed
            continue
        files, content, blob = sk.get("files"), sk.get("content"), sk.get("blob")
        if not (files or content or blob):
            raise HTTPException(400, f"skill '{name}': no files, content or blob payload")
        if files:
            if not isinstance(files, list):
                raise HTTPException(400, f"skill '{name}': files must be a list of {{path, content}}")
            paths = [str((f or {}).get("path") or "") for f in files if isinstance(f, dict)]
            if not any(p == "SKILL.md" or p.endswith("/SKILL.md") for p in paths):
                raise HTTPException(400, f"skill '{name}': bundle has no SKILL.md")
            if len(json.dumps(files)) > _SKILL_INLINE_MAX:
                sid = _rid("skb")
                if not await _blob_put(f"skills/{sid}.json", json.dumps(files).encode(), kb=BLOB_KB):
                    raise HTTPException(502, f"skill '{name}': bundle blob store failed")
                sk = {k: v for k, v in sk.items() if k != "files"}
                sk["blob"] = sid
            elif sk.get("blob"):
                # Edited back under the inline cap: the fresh `files` are authoritative — drop the
                # stale blob pointer so nothing can ever resolve the old bundle again.
                sk = {k: v for k, v in sk.items() if k != "blob"}
        out.append(sk)
    return out


async def _skill_bundle_files(sk: dict) -> list:
    """Resolve a harness skill entry to its full files list — inline `files`, blob-offloaded
    bundle, or a single-`content` SKILL.md — so the console can hydrate an offloaded folder
    skill for editing (the vertex prop only carries {name, enabled, blob} for large bundles)."""
    files = sk.get("files")
    if not files and sk.get("blob"):
        raw = await _blob_get(f"skills/{sk['blob']}.json", kb=BLOB_KB)
        if raw:
            try:
                files = json.loads(raw.decode())
            except Exception:  # noqa: BLE001
                files = None
    if not files and sk.get("content"):
        files = [{"path": "SKILL.md", "content": sk["content"]}]
    return files or []


def _workspace_keep(item_ws: str, workspace: str, ws_default: bool) -> bool:
    """Workspace filter with Default-Workspace leniency: unstamped legacy records belong
    to the org's Default Workspace."""
    if not workspace:
        return True
    return item_ws == workspace or (ws_default and not item_ws)


@app.post("/v1/orgs/{org}/harnesses")
async def create_harness(org: str, body: HarnessBody, request: Request) -> dict:
    p = await _owned_org(request, org)
    member = p.get("member") or request.headers.get("x-harness-member", "")
    workspace = request.headers.get("x-harness-workspace", "")
    body.skills = await _skills_prepare(body.skills)
    hid = _rid("chrn")
    now = str(int(time.time() * 1000))
    props = {"org": org, "member": member, "workspace": workspace, **_harness_props(body),
             "custom": "1", "created_at": now, "updated_at": now, "deleted": "0"}
    await _vg_upsert("Harness", hid, props)
    return _harness_out({"id": hid, **props})


@app.get("/v1/orgs/{org}/harnesses")
async def list_harnesses(org: str, request: Request,
                         workspace: str = "", workspace_default: int = 0) -> dict:
    """Org-scoped, member-agnostic — the same semantics as the engine's hr.harness.list
    (the Manager's reader). The old exact-member filter made harnesses invisible across
    surfaces because member identity is not canonical (plain email vs member.<email> id
    vs empty for org keys); GET-by-id never filtered by member anyway. The member prop
    is still recorded on the vertex for attribution. Optional `workspace` narrows to one
    workspace (Space id); `workspace_default=1` lets unstamped legacy records through."""
    await _owned_org(request, org)
    rows = await _vg_list_by_org("Harness", org)
    items = [_harness_out(r) for r in rows
             if str(r.get("deleted")) not in ("1", "true", "True")]
    if workspace:
        items = [i for i in items if _workspace_keep(i.get("workspace") or "", workspace, bool(workspace_default))]
    items.sort(key=lambda x: x["createdAt"], reverse=True)
    return {"harnesses": items}


@app.get("/v1/orgs/{org}/harnesses/{hid}")
async def get_harness(org: str, hid: str, request: Request) -> dict:
    await _owned_org(request, org)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    return _harness_out(v)


@app.get("/v1/orgs/{org}/harnesses/{hid}/models")
async def get_harness_models(org: str, hid: str, request: Request) -> dict:
    """Model-capability view for a harness (internal / console BFF): allowed models, default, and
    the authorized fallback. The console populates its model selector from this."""
    await _owned_org(request, org)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    backend = _backend_of_harness(v) or _route_backend(str(v.get("default_model") or ""), None)
    return {"harness_id": hid,
            **_harness_models_view(v, backend, await _servable_models(org, backend))}


@app.get("/v1/orgs/{org}/harnesses/{hid}/skills/{skill_id}/files")
async def get_harness_skill_files(org: str, hid: str, skill_id: str, request: Request) -> dict:
    """Full files of one harness skill, resolving the blob offload — the console uses this to
    hydrate a folder skill for editing (large bundles round-trip as {name, enabled, blob})."""
    await _owned_org(request, org)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    try:
        skills = json.loads(v.get("skills") or "[]")
    except Exception:  # noqa: BLE001
        skills = []
    sk = next((s for s in skills if isinstance(s, dict)
               and (s.get("id") == skill_id or s.get("name") == skill_id)), None)
    if not sk:
        raise HTTPException(404, "skill not found on this harness")
    return {"id": sk.get("id") or sk.get("name"), "name": sk.get("name"),
            "files": await _skill_bundle_files(sk)}


@app.put("/v1/orgs/{org}/harnesses/{hid}")
async def update_harness(org: str, hid: str, body: HarnessBody, request: Request) -> dict:
    await _owned_org(request, org)
    # V1C02-005: bind the mutation to the caller's org — a foreign harness id must not be editable.
    cur = await _vertex_get(hid)
    if not cur or str(cur.get("org") or "") != org or str(cur.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    # coalesce-upsert: created_at/org are untouched (only the provided props are set)
    body.skills = await _skills_prepare(body.skills)
    await _vg_upsert("Harness", hid, {**_harness_props(body), "updated_at": str(int(time.time() * 1000))})
    v = await _vertex_get(hid)
    return _harness_out(v or {"id": hid})


@app.delete("/v1/orgs/{org}/harnesses/{hid}")
async def delete_harness(org: str, hid: str, request: Request) -> dict:
    await _owned_org(request, org)
    # V1C02-005: only delete a harness that belongs to the caller's org.
    cur = await _vertex_get(hid)
    if not cur or str(cur.get("org") or "") != org:
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    await _vg_upsert("Harness", hid, {"deleted": "1"})
    return {"id": hid, "deleted": True}


# ── PUBLIC harness CRUD (Bearer sk-hr-... API key; org resolved from the key) ──────────
# This is what a vibe coder's agent (driven by AGENTS.md) calls — no org id, no internal header.
async def _pub_org_member(request: Request) -> tuple[str, str]:
    p = await _principal(request)
    org = p.get("org", "")
    if not org:
        raise uhp_error(401, "invalid_credential", "Missing or invalid API key.")
    return org, p.get("member", "")


@app.post("/v1/harnesses")
async def create_harness_public(body: HarnessBody, request: Request) -> dict:
    p = await _principal(request)
    org, member = p.get("org", ""), p.get("member", "")
    if not org:
        raise uhp_error(401, "invalid_credential", "Missing or invalid API key.")
    body.skills = await _skills_prepare(body.skills)
    hid = _rid("chrn")
    now = str(int(time.time() * 1000))
    props = {"org": org, "member": member, "workspace": str(p.get("workspace") or ""),
             **_harness_props(body),
             "custom": "1", "created_at": now, "updated_at": now, "deleted": "0"}
    await _vg_upsert("Harness", hid, props)
    return _harness_out({"id": hid, **props})


@app.get("/v1/kits")
async def list_kits(request: Request) -> dict:
    """The kit catalog, with each kit's launched Harness when it has one.

    `launched` is what makes the tab honest: a kit is either something you can start or something
    you already run, and the card should not offer to "Launch" a thing that is already there."""
    p = await _principal(request)
    org = p.get("org", "")
    if not org:
        raise uhp_error(401, "invalid_credential", "Missing or invalid API key.")
    rows = await _vg_list_by_org("Harness", org)
    by_kit = {str(r.get("kit") or ""): r for r in rows if str(r.get("deleted") or "0") != "1"}
    out = []
    for kid, kit in sorted(_kits().items()):
        h = by_kit.get(kid)
        out.append({"id": kid, "object": "kit",
                    "title": kit.get("title") or kid,
                    "tagline": kit.get("tagline") or "",
                    "description": kit.get("description") or "",
                    "icon": kit.get("icon") or "", "accent": kit.get("accent") or "",
                    "route": (kit.get("app") or {}).get("route") or "",
                    "launched": bool(h),
                    "harnessId": (h or {}).get("id") or None,
                    # What the kit actually installs, from its own config — so the card can say
                    # what you get instead of asking you to take it on trust.
                    "skills": [str(n) for n in ((kit.get("harness") or {}).get("skills") or [])],
                    # What to run it on: this kit's own recommended pairings, each marked with
                    # whether the caller's integrations can serve it. The launch dialog renders
                    # these directly and preselects the one flagged `recommended`.
                    "choices": await _kit_choices(org, kit)})
    return {"kits": out}


class KitLaunchBody(BaseModel):
    """What to run the kit on. Both optional: no body at all means "use the recommendation"."""
    base: str = ""
    model: str = ""


@app.post("/v1/kits/{kit_id}/launch")
async def launch_kit(kit_id: str, request: Request, body_in: KitLaunchBody | None = None) -> dict:
    """Provision this kit's Harness, or hand back the one that already exists.

    Idempotent on purpose. Launch is a button someone presses twice — because the first press
    seemed slow, or because they came back a week later — and the second press must not leave
    them with two Harnesses and their decks split across both."""
    p = await _principal(request)
    org, member = p.get("org", ""), p.get("member", "")
    if not org:
        raise uhp_error(401, "invalid_credential", "Missing or invalid API key.")
    kit = _kits().get(kit_id)
    if not kit:
        raise uhp_error(404, "kit_not_found", f"No starter kit '{kit_id}' in this build.")

    for r in await _vg_list_by_org("Harness", org):
        if str(r.get("kit") or "") == kit_id and str(r.get("deleted") or "0") != "1":
            return {"kit": kit_id, "harnessId": r.get("id"),
                    "route": (kit.get("app") or {}).get("route") or "", "created": False}

    spec = kit.get("harness") or {}
    # An explicit choice from the launch dialog wins; no choice means take the recommendation.
    # It is validated rather than trusted: a pairing nothing can serve produces a Harness whose
    # every turn fails, and the failure would surface far from the launch that caused it.
    want_base = (body_in.base if body_in else "").strip()
    want_model = (body_in.model if body_in else "").strip()
    if want_base:
        if want_base not in _BASE_CATALOG:
            raise uhp_error(400, "invalid_base", f"No base harness '{want_base}'.", "base")
        if not await _base_serves(org, want_base, want_model):
            raise uhp_error(400, "model_unavailable",
                            f"Nothing you have connected can run {want_model or 'that model'} "
                            f"on {want_base}.", "model")
        base, model = want_base, want_model
    else:
        base, model = await _kit_base(org, kit)
    body = HarnessBody(name=spec.get("name") or kit.get("title") or kit_id,
                       base=base,
                       default_model=model,
                       system_prompt=spec.get("system_prompt") or "",
                       skills=_kit_skills(kit),
                       mcp_servers=spec.get("mcp_servers") or [],
                       disabled_tools=spec.get("disabled_tools") or [])
    body.skills = await _skills_prepare(body.skills)
    hid = _rid("chrn")
    now = str(int(time.time() * 1000))
    props = {"org": org, "member": member, "workspace": str(p.get("workspace") or ""),
             **_harness_props(body),
             # The kit that made it. This is what keeps launch idempotent and what lets the app
             # find its own Harness without the user picking one from a list.
             "kit": kit_id,
             "custom": "1", "created_at": now, "updated_at": now, "deleted": "0"}
    await _vg_upsert("Harness", hid, props)
    print(f"[kits] launched {kit_id} -> {hid}", flush=True)
    return {"kit": kit_id, "harnessId": hid,
            "route": (kit.get("app") or {}).get("route") or "", "created": True}


@app.get("/v1/harnesses")
async def list_harnesses_public(request: Request) -> dict:
    p = await _principal(request)
    org = p.get("org", "")
    if not org:
        raise uhp_error(401, "invalid_credential", "Missing or invalid API key.")
    # Org-scoped, member-agnostic (see list_harnesses): an API key sees every harness in its
    # org — narrowed to its workspace when the key is workspace-scoped — exactly like the
    # console, so both surfaces always agree.
    rows = await _vg_list_by_org("Harness", org)
    items = [_harness_out(r) for r in rows
             if str(r.get("deleted")) not in ("1", "true", "True")]
    ws = str(p.get("workspace") or "")
    if ws:
        items = [i for i in items if _workspace_keep(i.get("workspace") or "", ws, bool(p.get("workspace_default")))]
    items.sort(key=lambda x: x["createdAt"], reverse=True)
    return {"harnesses": items}


@app.get("/v1/harnesses/{hid}")
async def get_harness_public(hid: str, request: Request) -> dict:
    org, _ = await _pub_org_member(request)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    return _harness_out(v)


@app.get("/v1/bases")
async def list_bases(request: Request) -> dict:
    """What each base harness is, and what it can actually do here.

    The console renders bases entirely from this: models with live availability, the real tool names
    and how far disabling one goes, and the built-in skills — which is an EMPTY list, deliberately.
    Codex, Claude Code and Hermes each discover their own bundled skills at run time and expose no
    way to enumerate them from outside a turn, so this server does not know them. It says so rather
    than listing plausible names: the console previously showed four (docx, pdf, pptx, xlsx) that
    exist nowhere, and every control next to them — Replace, Disable — acted on nothing.
    """
    org, _ = await _pub_org_member(request)
    out = []
    for bid, b in _BASE_CATALOG.items():
        backend = b["backend"]
        cat = _MODEL_CATALOG.get(backend, {})
        servable = await _servable_models(org, backend)
        ok = (lambda m: True) if servable is None else (lambda m: m in servable)
        out.append({
            "id": bid, "object": "harness.base", "label": b["label"], "backend": backend,
            "status": b["status"], "systemPrompt": b["system_prompt"],
            "defaultModel": cat.get("default", ""),
            "models": [{"id": m, "available": ok(m), "default": m == cat.get("default")}
                       for m in cat.get("models", [])],
            "tools": [{"name": n, "label": lbl, "enforcement": b["tool_enforcement"]}
                      for n, lbl in b["tools"]],
            # Skills bundled into the image, which every base can use. A base ALSO discovers
            # skills of its own at run time that nothing outside a turn can enumerate, so
            # `builtinSkillsEnumerable` stays False: the console must say "and it brings its own"
            # rather than presenting this list as everything the agent has.
            "builtinSkills": [{"name": n, "title": b2["title"], "description": b2["description"],
                               "defaultEnabled": b2["default_enabled"], "origin": b2["origin"]}
                              for n, b2 in sorted(_builtin_skills().items())],
            "builtinSkillsEnumerable": False,
        })
    return {"bases": out}


@app.get("/v1/models")
async def list_models(request: Request) -> dict:
    """Global model catalog (public, Bearer): every backend's available models + default. Callers
    use this to build a model picker; per-harness allowances come from the harness models route."""
    org, _ = await _pub_org_member(request)
    # `available` is computed, not asserted: a model with no provider behind it is listed as
    # unavailable so a picker can disable it, instead of offering a choice that fails at run time.
    out = {}
    for b, c in _MODEL_CATALOG.items():
        servable = await _servable_models(org, b)
        ok = (lambda m: True) if servable is None else (lambda m: m in servable)
        out[b] = {"default": c["default"],
                  "models": [{"id": m, "label": m, "backend": b, "available": ok(m),
                              "default": m == c["default"]} for m in c["models"]]}
    return {"backends": out}


@app.get("/v1/harnesses/{hid}/models")
async def get_harness_models_public(hid: str, request: Request) -> dict:
    """Model-capability view for a harness (public, Bearer): allowed models, default, authorized
    fallback. A request for a model outside this set is replaced by the fallback at run time."""
    org, _ = await _pub_org_member(request)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    backend = _backend_of_harness(v) or _route_backend(str(v.get("default_model") or ""), None)
    return {"harness_id": hid,
            **_harness_models_view(v, backend, await _servable_models(org, backend))}


@app.get("/v1/harnesses/{hid}/skills/{skill_id}/files")
async def get_harness_skill_files_public(hid: str, skill_id: str, request: Request) -> dict:
    """Full files of one skill (public, Bearer), resolving the server-side blob offload — large
    folder bundles round-trip on the harness record as {name, enabled, blob}; this returns the
    real files for editing or verification. `skill_id` matches the entry's id or name."""
    org, _ = await _pub_org_member(request)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    try:
        skills = json.loads(v.get("skills") or "[]")
    except Exception:  # noqa: BLE001
        skills = []
    sk = next((s for s in skills if isinstance(s, dict)
               and (s.get("id") == skill_id or s.get("name") == skill_id)), None)
    if not sk:
        raise HTTPException(404, "skill not found on this harness")
    return {"id": sk.get("id") or sk.get("name"), "name": sk.get("name"),
            "files": await _skill_bundle_files(sk)}


@app.put("/v1/harnesses/{hid}")
async def update_harness_public(hid: str, body: HarnessBody, request: Request) -> dict:
    org, _ = await _pub_org_member(request)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    body.skills = await _skills_prepare(body.skills)
    await _vg_upsert("Harness", hid, {**_harness_props(body), "updated_at": str(int(time.time() * 1000))})
    return _harness_out(await _vertex_get(hid) or {"id": hid})


@app.delete("/v1/harnesses/{hid}")
async def delete_harness_public(hid: str, request: Request) -> dict:
    org, _ = await _pub_org_member(request)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org:
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    await _vg_upsert("Harness", hid, {"deleted": "1"})
    return {"id": hid, "deleted": True}
