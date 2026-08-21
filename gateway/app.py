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
import contextlib
import functools
import hashlib
import ipaddress
import mimetypes
import pathlib
import shutil
import socket
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
import media_plane           # the media plane (capability catalog, provider adapters, ffmpeg)
import sql_plane             # the read-only SQL data plane (gate, row cap, introspection)
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
            names = _policy_chain(v)
            if names:
                return names
    return []


def _policy_chain(raw: str) -> list[str]:
    """The connection names in a policy document.

    TWO shapes are one document, and both must be read here or a working install stops working:
    `{"chain": ["anthropic"]}` is the form the README, the docker run line and .env.example have
    always published, so it is what is sitting in operators' .env files; the bare `["anthropic"]`
    is what PUT /v1/orgs/{org}/policy/{backend} writes. Only the second parsed, which meant the
    documented quickstart produced a gateway that could serve no model and said nothing about why.
    """
    try:
        doc = json.loads(raw)
    except Exception:  # noqa: BLE001 — a corrupt policy is no policy, not a crash
        return []
    names = doc.get("chain") if isinstance(doc, dict) else doc
    return [str(n) for n in names if str(n).strip()] if isinstance(names, list) else []


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
# Video, speech and music are NOT routed by a model map. They are routed by the media
# chain: an ordered list of candidates per capability, each carrying what it measurably
# does, and the first one whose provider is connected wins. This document is the operator's
# preference over that order — which to try first, which to switch off — and it is kept
# apart from the catalog for the reason media_plane.set_policy explains: the catalog is
# measurement, this is policy, and one must not overwrite the other.
_MEDIA_POLICY_KEY = "harness-media-policy"
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
    # Vercel's gateway answers on BOTH shapes from one base_url and one key: OpenAI's
    # /v1/chat/completions and Anthropic's /v1/messages. That is the same pair TokenRouter
    # offers, so it carries all three backends by the same runner providers, for the same
    # reasons — 'tokenrouter' being the runner's name for "OpenAI/Anthropic-compatible, and the
    # base_url says where", not a statement about whose service it is.
    ("vercel", "claude"): "tokenrouter",       ("vercel", "codex"): "tokenrouter",
    ("vercel", "hermes"): "openai-api",
    # LLMTR answers on the same two shapes from one base_url and one key, so it is wired like
    # Vercel. Its Anthropic surface is not in the published catalogue — every model there lists
    # OpenAI endpoints only — but it is real, and was probed live on 2026-08-19: POST /v1/messages
    # with anthropic/claude-sonnet-4.6 came back 200 with a proper Anthropic message envelope,
    # while an unknown path under /v1 answers {"type":"not_found"}.
    ("llmtr", "claude"): "tokenrouter",        ("llmtr", "codex"): "tokenrouter",
    ("llmtr", "hermes"): "openai-api",
    # Pi (earendil-works pi coding agent) is multi-family like hermes: native env auth for the
    # two vendors it speaks directly, a models.json custom provider for everything with a
    # base_url. 'tokenrouter' on the runner again means "OpenAI/Anthropic-compatible, api picked
    # by model family" — TokenRouter, Vercel and LLMTR all serve both shapes from one base_url.
    ("anthropic", "pi"): "anthropic",          ("openai", "pi"): "openai",
    ("azure-foundry", "pi"): "azure",
    ("openrouter", "pi"): "openai-api",
    ("tokenrouter", "pi"): "tokenrouter",      ("vercel", "pi"): "tokenrouter",
    ("llmtr", "pi"): "tokenrouter",
    # dsh (DeepSeek Harness) is multi-family via dsh-llm-pi-ai — pi's unified LLM library as
    # a Cordis plugin — so its wiring mirrors pi's: 'deepseek' on the runner is the launch
    # adapter for the deepseek family, 'tokenrouter' again means "OpenAI/Anthropic-compatible,
    # api picked by model family" at the driver's relay. A first-party DeepSeek Platform
    # integration is still NOT listed: nobody here holds a platform key; unprobed is unlisted.
    ("anthropic", "dsh"): "anthropic",         ("openai", "dsh"): "openai",
    ("azure-foundry", "dsh"): "azure",
    ("openrouter", "dsh"): "openai-api",
    ("tokenrouter", "dsh"): "tokenrouter",     ("vercel", "dsh"): "tokenrouter",
    ("llmtr", "dsh"): "tokenrouter",
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


async def _media_policy_doc() -> dict:
    v = await _vault_get(GLOBAL_TENANT, _MEDIA_POLICY_KEY)
    try:
        doc = json.loads(v) if v else {}
        return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


async def _media_policy_load() -> dict:
    """Read it and hand it to the media plane. The plane holds one cached copy because it is read
    on every resolve; this is the only thing that sets it."""
    doc = await _media_policy_doc()
    media_plane.set_policy(doc)
    return doc


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


async def _prior_manifest(prefix: str) -> dict:
    """The session's current manifest, or {}. Session CARDS are built from this blob, not from the
    session vertex, so anything that must change what a list shows has to change this."""
    if not prefix:
        return {}
    try:
        pm = await _blob_get(_manifest_key(prefix), kb=TRACE_KB)
        return json.loads(pm) if pm else {}
    except Exception:  # noqa: BLE001
        return {}


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
    _pm = await _prior_manifest(tr.get("prefix") or "")
    prior_title = str(_pm.get("title") or "") if str(_pm.get("title_custom") or "") == "1" else ""
    await _index_manifest(tr["prefix"], {
        "session_id": sid, "org_id": org, "tenant": org,
        "member_id": tr.get("member") or member or "",
        "harness_id": tr.get("harness_id") or harness_id or "",
        "workspace": tr.get("workspace") or "",
        "harness_name": tr.get("harness_name") or "",
        "backend": backend, "model": model,
        # A title the person set survives every later turn. Without this the card is renamed to
        # the first line of whatever you last said — which is why decks ended up called
        # "Change primary color to brown".
        "title": (prior_title if prior_title
                  else (user_text.strip().splitlines()[0][:120] if user_text.strip() else sid[:16])),
        **({"title_custom": "1"} if prior_title else {}),
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
async def _start_media_policy() -> None:
    """The operator's media preference, published to the plane before the first turn can arrive.
    Without this the order they chose applies only after something else happens to write it."""
    try:
        await _media_policy_load()
    except Exception as e:  # noqa: BLE001 — a missing preference is not a reason not to start
        print(f"[media] could not read the routing preference ({e}); using the catalog order",
              flush=True)


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


# ── servers this gateway hosts itself, recognised by ADDRESS ──────────────────────────────────
# A server is ours if its url is one of our own addresses. That is the one thing true of every
# server we host and of no server we do not, so recognising them costs no field on the entry, no
# kind registry and no client-visible flag — and a second first-party server later needs nothing
# but a path under /v1/mcp/.
_HOSTED_MCP_PREFIX = "/v1/mcp/"
# What may follow that prefix: the server's name and nothing else — no second segment, no query,
# no dot-dot. See _hosted_mcp_path.
_HOSTED_MCP_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# Where a hosted server's own state lives. A namespace inside the secret store rather than a field
# anywhere: PUT /v1/mcp-secrets/{ref} prefixes every key it writes with `harness-mcp-`, so no
# caller can write into this one.
_HOSTED_SECRET_PREFIX = "harness-hosted-"


def _own_origins() -> list[str]:
    """Every address a client could legitimately have stored for a server WE host.

    Hosted, that is the public base URL a sandbox reaches us on. Self-hosted, the runner is a
    process beside us and loopback is both correct and the only thing that resolves. Both are
    listed, in preference order, because an instance that gains a public URL later must keep
    serving the entries it wrote before it had one.
    """
    out = []
    if PUBLIC_BASE_URL:
        out.append(PUBLIC_BASE_URL)
    local = os.environ.get("HARNESS_GATEWAY_URL", "").rstrip("/")
    if local and _pool_is_local():
        out.append(local)
    return out


def _hosted_mcp_path(url: str) -> str | None:
    """The path of a server THIS GATEWAY HOSTS, or None for a server somewhere else."""
    for origin in _own_origins():
        if not url.startswith(origin + _HOSTED_MCP_PREFIX):
            continue
        name = url[len(origin) + len(_HOSTED_MCP_PREFIX):]
        # A NAME under the prefix, not an arbitrary path. `/v1/mcp/../../v1/admin` starts with our
        # prefix and is a different endpoint once any client normalises it — hosted is what earns
        # a minted credential and a pass on _ssrf_check, and neither is owed to a string that only
        # looks like one of our servers. Not ours → the ordinary remote path, which hands it no
        # credential at all because _resolve_mcp_auth refuses this namespace.
        return _HOSTED_MCP_PREFIX + name if _HOSTED_MCP_NAME.match(name) else None
    return None


def _vault_key(auth) -> str:
    """The secret-store key an entry's auth references, or "" when it references none."""
    return auth[len("vault:"):] if isinstance(auth, str) and auth.startswith("vault:") else ""


async def _resolve_mcp_auth(org: str, auth: str) -> str:
    """Resolve an MCP server auth value. 'vault:<key>' → the secret from the org/global vault
    (token never sits in the graph). Anything else is treated as a literal bearer token."""
    if isinstance(auth, str) and auth.startswith("vault:"):
        key = auth[len("vault:"):]
        if key.startswith(_HOSTED_SECRET_PREFIX):
            # A record we hold for a server we host. It is not a bearer token for anybody, and
            # this is the one place a stored secret becomes a literal on an outbound request — so
            # refusing HERE is what makes "the connection string never leaves this process" true
            # for callers that do not exist yet, including an entry that names this ref and points
            # somewhere else on purpose.
            print(f"[mcp] refusing to resolve {key} as a bearer token", flush=True)
            return ""
        for tenant in _tenants_for(org):
            v = await _vault_get(tenant, key)
            if v:
                return v
        return ""
    return auth or ""


def _mcp_list(v: dict | None) -> list[dict]:
    """Every MCP server on a harness vertex. THE ONE READER: _harness_plugins, _harness_out and
    the $headers pre-scan all come through here, so a harness's tool list cannot mean one thing on
    the page that lists capabilities and another in the turn."""
    try:
        a = json.loads((v or {}).get("mcp_servers") or "[]")
    except Exception:  # noqa: BLE001
        a = []
    return [s for s in a if isinstance(s, dict)] if isinstance(a, list) else []


_MCP_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _mcp_name(s: str) -> str:
    """The identifier the agent's CLI will see for a server. The runner's _mcp_name, duplicated:
    the gateway has to ask the same question the runner will answer, and asking it over HTTP is
    not an option at config time."""
    return _MCP_NAME_RE.sub("_", (s or "").strip()).strip("_") or "mcp"


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
                           hv: dict | None = None, sid: str = "") -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Resolve a harness's ENABLED MCP servers + skills for a turn. MCP auth refs are resolved
    from the vault here so the runner never sees vault keys, only the live token (or none).
    `hv` (HR-INF-010): the already-read harness vertex — the SOLE caller (_resp_execute) always
    threads it, so we DON'T re-read. Using the same snapshot as agent_doc means both degrade
    together if the read failed (hv is None → empty plugins), never inconsistently (review #5).
    `sid`: the session this turn belongs to, used to scope the database tool's credential to it."""
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
    v = await _mcp_migrate(org, harness_id, v)

    def _arr(prop):
        try:
            a = json.loads(v.get(prop) or "[]")
            return a if isinstance(a, list) else []
        except Exception:  # noqa: BLE001
            return []

    mcp_out: list[dict] = []
    for s in _mcp_list(v):
        if str(s.get("enabled")) in ("False", "false", "0"):
            continue
        if not s.get("url"):
            continue
        _hvals = hdr_vals or {}   # (renamed from hv — that name is now the harness-vertex param)
        _url = _sub_headers(s["url"], _hvals)
        hosted = _hosted_mcp_path(_url)

        if hosted:
            # A SERVER WE HOST. Two things follow, and neither is about what kind of server it is.
            #
            # The address is re-derived from the origin we serve on NOW, not the one stored: an
            # operator who moves the gateway must not strand every entry written before the move.
            # No _ssrf_check, because that rule's subject is a target a customer named, and a url
            # that already equals one of our own origins is not one however it got typed.
            #
            # The credential is MINTED, not resolved. _resolve_mcp_auth returns a literal that the
            # runner writes into .harness/mcp.json inside a container with bash — right for a
            # third-party bearer token, and never right for a credential to one of our own
            # services. That is the lesson of 2026-07-25, and it is a property of first-party
            # servers rather than of databases. What the sandbox holds is a capability scoped to
            # this harness, this session and the record this entry's auth names, and it expires.
            key = _vault_key(s.get("auth"))
            if not key.startswith(_HOSTED_SECRET_PREFIX):
                print(f"[mcp] '{s.get('name')}' on {harness_id} points here but names no record "
                      f"this server holds — not offered this turn.", flush=True)
                continue
            mcp_out.append({"name": s.get("name") or s.get("id") or "mcp",
                            "url": _own_origins()[0] + hosted,
                            "transport": s.get("transport") or "http",
                            "auth": _mint_hosted_cred(harness_id, sid, key)})
            continue

        # Same rule the console's Test connection applies. Enforced here too, because this is the
        # call that actually reaches the network: a URL the policy rejects must never be handed to
        # a sandbox, whatever is stored on the harness.
        _blocked = await _ssrf_check(_url)
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


class SessionPatch(BaseModel):
    """The parts of a session a person may edit. Only the title, for now."""
    title: str | None = None


@app.patch("/v1/sessions/{sid}")
async def patch_session(sid: str, body: SessionPatch, request: Request) -> dict:
    """Rename a session.

    A conversation's title is auto-derived from its first message (see _TRACE_CARD_FIELDS), which
    is a reasonable default and a poor permanent name — "A 4-slide deck: why onboarding drops off
    at step 3, and the three fixes…" is not what anyone wants their deck called. An app built on a
    Harness needs to be able to fix that, and until now there was no route to do it with: the
    obvious PATCH did not exist, so a rename silently did nothing and reverted on the next load.
    """
    _org, _v = await _owned_session(request, sid)
    title = (body.title or "").strip()
    if not title:
        raise uhp_error(400, "invalid_title", "A title is required.", "title")
    title = title[:120]
    # The vertex for anything reading the session directly, AND the trace manifest, because that
    # blob is what every LIST renders. Writing only the vertex looks like it worked and reverts on
    # the next load. `title_custom` is what stops the next turn regenerating it from your message.
    await _vg_upsert("HarnessSession", sid, {"title": title})
    base = await _trace_base(sid)
    if base:
        m = await _prior_manifest(base)
        if m:
            m["title"] = title
            m["title_custom"] = "1"
            await _index_manifest(base, m)
    return {"id": sid, "object": "session", "title": title}


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
    # 2) durable session workspace tarball, and anything the media server holds for it
    await _blob_delete(_ws_blob(sid), kb=BLOB_KB)
    await _media_session_purge(sid)
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
    "vercel": {
        "label": "Vercel AI Gateway",
        "base_url": "https://ai-gateway.vercel.sh/v1",
        "fields": [],
        "secret": "api_key",
        "secret_label": "API Key",
        "key_hint": "vck_…",
    },
    "llmtr": {
        "label": "LLMTR",
        "base_url": "https://llmtr.com/v1",
        "fields": [],
        "secret": "api_key",
        "secret_label": "API Key",
        "key_hint": "llmtr-…",
    },
    # Media only: it serves no chat model, so it carries no entry in _VENDOR_MODELS and shows no
    # models on its row. It is HERE because the console validates every entry in the integrations
    # document against this table on every write — so with ElevenLabs connected and absent from
    # it, the whole document was refused with "integration needs a name and a known provider (got
    # 'elevenlabs')" and NO integration could be added or edited on that instance again. Measured
    # on the test box 2026-08-16, where an ElevenLabs connection added for the media plane had
    # quietly locked the page.
    "elevenlabs": {
        "label": "ElevenLabs",
        "base_url": "https://api.elevenlabs.io",
        "fields": [],
        "secret": "api_key",
        "secret_label": "API Key",
        "key_hint": "sk_…",
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


async def _media_chains_public() -> list[dict]:
    """Every media capability's chain, in the order it will actually be walked.

    Read through media_plane.capability(), which is where the operator's preference is applied —
    so what the console draws is the list the router uses, not a second reading of the file that
    could drift from it.

    The measured facts travel with each candidate because they are the reason for the order. An
    operator moving a model to the top is choosing between "honours the duration you ask for" and
    "ignores it and returns 6 s", and that choice cannot be made from a model name.
    """
    connected = set((await _media_providers()).keys())
    out: list[dict] = []
    for name in media_plane.capability_names():
        cap = media_plane.capability(name)
        cands = [c for c in (cap.get("candidates") or []) if isinstance(c, dict)]
        rows = []
        for c in cands:
            model = str(c.get("model") or "")
            provider = str(c.get("provider") or "")
            rows.append({
                "model": model,
                "provider": provider,
                "connected": provider in connected,
                "off": bool(c.get("policy_off")),
                # Why it is where it is, in the words the file recorded when it was called.
                "resolution": c.get("resolution") or "",
                "seconds": c.get("duration_observed_s"),
                "duration_ignored": bool(c.get("duration_ignored")),
                "accepts_input_image": c.get("accepts_input_image"),
                "usd": c.get("usd"),
                "verification": c.get("verification") or "",
                # The clause the chain would use if this one were asked for right now.
                "unavailable": media_plane.stood_down(c),
            })
        out.append({"capability": name, "unit": cap.get("unit") or "", "candidates": rows})
    return out


@app.get("/v1/admin/integrations")
async def admin_integrations_get(request: Request) -> dict:
    await _require_integrations_admin(request)
    return {"integrations": [_integration_public(i) for i in await _integrations_doc()],
            "model_map": await _effective_model_map(),
            "image_model_map": await _effective_image_model_map(),
            "providers": sorted({p for p, _ in _INTEGRATION_WIRING}),
            "catalog": _provider_catalog_public(),
            "media_chains": await _media_chains_public(),
            "media_policy": await _media_policy_doc()}


class IntegrationsBody(BaseModel):
    integrations: list[dict]
    model_map: dict
    # Optional: a console that predates image routing still saves without wiping the image map.
    # Absent means "leave it alone", which is not the same as an empty dict meaning "clear it".
    image_model_map: dict | None = None
    # Same rule: absent leaves the media preference alone, {} clears it back to the catalog's own
    # order. A console that does not know about media routing must not silently reset it.
    media_policy: dict | None = None


@app.put("/v1/admin/integrations")
async def admin_integrations_put(body: IntegrationsBody, request: Request) -> dict:
    await _require_integrations_admin(request)
    stored = {str(i.get("name") or ""): i for i in await _integrations_doc()}
    out: list[dict] = []
    for i in body.integrations:
        name = str(i.get("name") or "").strip()
        provider = str(i.get("provider") or "").lower()
        # Against the CATALOG, which is the list of providers this console offers, and not against
        # _INTEGRATION_WIRING, which answers a different question: which agent backends can be
        # driven by one. A media-only provider has no backend wiring by definition, so validating
        # here against the wiring made ElevenLabs unsaveable — and because the console PUTs the
        # WHOLE document, one such row already in the vault failed every subsequent write and no
        # integration of any kind could be added to that instance again.
        if not name or provider not in _PROVIDER_CATALOG:
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
    if body.media_policy is not None:
        # Only models this deployment actually HAS. A preference naming a model the catalog does
        # not carry is silent dead weight: it survives every write, explains nothing, and reorders
        # nothing — and the day that name appears in an upgraded catalog it takes effect without
        # anyone choosing it.
        known = {str(c.get("model")) for n in media_plane.capability_names()
                 for c in (media_plane.capability(n).get("candidates") or [])
                 if isinstance(c, dict)}
        clean: dict = {}
        for cap, pref in (body.media_policy or {}).items():
            if not isinstance(pref, dict):
                continue
            order = [str(m) for m in (pref.get("order") or []) if str(m) in known]
            off = [str(m) for m in (pref.get("disabled") or []) if str(m) in known]
            if order or off:
                clean[str(cap)] = {"order": order, "disabled": off}
        await _vault_put(GLOBAL_TENANT, _MEDIA_POLICY_KEY, json.dumps(clean))
        # The plane caches it, so the write must publish it. Otherwise the order takes effect on
        # the next restart, which is indistinguishable from the control not working.
        media_plane.set_policy(clean)
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
    # LLMTR is a Turkey-hosted gateway: models running on its own infrastructure in Turkey
    # beside the global frontier catalogue, behind one base_url and one key. Ids are
    # vendor-qualified like OpenRouter's, so the canonical is the id with the vendor prefix
    # removed — except where a canonical for that model already exists above (hunyuan-3 is
    # tencent/hy3, nemotron-3-ultra is the 550b-a55b id), because one model arriving in the
    # picker twice under two names is worse than a name that reads oddly.
    #
    # This table is deliberately the INTERSECTION with _MODEL_CATALOG rather than everything
    # LLMTR serves: connecting the provider adds no name to any picker, it only makes models
    # that are already there reachable through Turkey. Its published catalogue
    # (GET https://llmtr.com/v1/models, which needs no key) was read and measured on
    # 2026-08-19: of 245 published ids, 131 clear the agent-loop bar _MODEL_CATALOG states,
    # and the 107 of those that only LLMTR serves — including the three Turkey-resident
    # models, gemma-4, qwen3-6-35b and qwen3-5-4b — are proposed separately, once the
    # capability test can check this catalogue the way it checks OpenRouter's. The rules
    # they were measured by, so that follow-up can re-apply them rather than trust a number:
    #
    #   1. Text out and `tools` in supported_parameters — the same agent-loop bar
    #      _MODEL_CATALOG states. 81 fail it: embedders, image/video/speech models, and the
    #      small Turkish chat models (trendyol-asure-12b, magibu-11b-v8, medgemma-4b) that
    #      serve no tools.
    #   2. No dated snapshot of an id already listed (qwen-plus-2025-07-14 beside qwen-plus).
    #      The snapshot is the same model under a pinned name; two picker rows for it help
    #      nobody.
    #   3. The transport has to be the one the runner will actually use for that id. Both ways
    #      round, and 17 models fail it: gpt-5.4/5.2/5.1/5/o1/o3 and friends are published here
    #      for /v1/chat/completions only while hermes drives every gpt-5*/o[1-4] id over
    #      /v1/responses (_HERMES_RESPONSES_API_MODEL), and the grok ids are published for
    #      /v1/responses only while hermes drives them over chat. Offering either is a picker
    #      row that fails on send — the same broken promise _TOKENROUTER_NO_CHANNEL records.
    #   4. It has to answer. Every id was called live on 2026-08-19 — max_tokens=4 on
    #      /v1/chat/completions, max_output_tokens=16 on /v1/responses — and seven published as
    #      available did not, twice: llmtr/muse-glimmer-30b-tr returns no bytes at all (45 s,
    #      70 s and 120 s), publicai/apertus-8b-instruct 502s after about a minute,
    #      llmtr/ornith-1-35b and anthropic/claude-opus-4.1 502 immediately, aion-labs/aion-2.5
    #      and publicai/apertus-v1.5-8b 400, and openai/gpt-oss-120b 402 while the gpt-oss-20b
    #      beside it answers. A catalogue entry is an advertisement; an answer is the product.
    #
    # A ping is not a long agentic turn, so the harnesses on the test box ran real ones, each
    # completing without substitution: Claude Code over /v1/messages on claude-sonnet-4.6 and
    # claude-opus-4.8, hermes over /v1/chat/completions on claude-haiku-4.5, and codex over
    # /v1/responses on gpt-5.3-codex and gpt-5.5, both of which called the shell tool and came
    # back with its real output. A model here that turns out to fail a real turn comes off this
    # table the same way those seven did.
    #
    # One thing those runs turned up that is NOT this table's doing, recorded so the next person
    # does not have to rediscover it: driven by CODEX, gpt-5.6-sol, gpt-5.6-terra and
    # gpt-5.6-luna finish a turn but are never offered tools, so they cannot act — they answer
    # that they have no shell and stop. This is the codex CLI, not the provider. Pointed at a
    # local endpoint that records what it is sent, codex 0.148.0 emits the gpt-5.6-* request with
    # NO `tools` and NO `instructions` field at all, while the same binary against the same
    # endpoint sends 11 tools and a 21k-char instructions block for gpt-5.5. Nothing ever reaches
    # the provider for it to drop. The family first tries wss://api.openai.com/v1/responses and
    # its request carries x-codex-window-id, so it appears to expect the WebSocket session where
    # tools and instructions are established on the connection; falling back to plain HTTPS
    # against a configured provider, it sends neither. HERMES drives the same three ids over the
    # same /v1/responses transport against the same base_url with tools intact. So it applies to
    # every non-OpenAI provider, not this one: all three are already in _MODEL_CATALOG["codex"]
    # and reachable through openrouter, tokenrouter and vercel. Left alone here rather than
    # worked around in one vendor's table.
    "llmtr": {
        "gpt-5.6-sol":        "openai/gpt-5.6-sol",
        "gpt-5.6-terra":      "openai/gpt-5.6-terra",
        "gpt-5.6-luna":       "openai/gpt-5.6-luna",
        "gpt-5.5":            "openai/gpt-5.5",
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
        "kimi-k3":            "moonshot/kimi-k3",
        "qwen3.7-max":        "qwen/qwen3.7-max",
        "qwen3.8-max":        "qwen/qwen3.8-max",
        "kimi-k2.7-code":     "moonshot/kimi-k2.7-code",
        "step-3.7-flash":     "stepfun/step-3.7-flash",
        "minimax-m3":         "minimax/minimax-m3",
        "nemotron-3-ultra":   "nvidia/nemotron-3-ultra-550b-a55b",
        "hunyuan-3":          "tencent/hy3",
        "ling-3.0-flash":     "inclusionai/ling-3.0-flash",
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
    # Verified on the live gateway 2026-08-16: gpt-image-1-mini returned a 1,286,643 byte PNG at
    # 1024x1024 through the ordinary /v1/images/generations path.
    "vercel": {"gpt-image-1": "openai/gpt-image-1",
               "gpt-image-1-mini": "openai/gpt-image-1-mini"},
}


_VENDOR_MODELS["tokenrouter"] = {c: v for c, v in _VENDOR_MODELS["openrouter"].items()
                                 if c not in _TOKENROUTER_NO_CHANNEL}

# Vercel's AI Gateway carries the same catalogue under nearly the same slugs, so it starts from
# OpenRouter's table too. Only the vendor prefix differs on four of them, and it differs because
# the two aggregators disagree about who publishes the model, not about which model it is.
#
# Checked against the gateway's own list (GET https://ai-gateway.vercel.sh/v1/models, which needs
# no key) on 2026-08-15: 25 of the 29 resolve byte-identical, these 4 do not, and every one of the
# 29 exists there under one name or the other. A slug that stops resolving belongs here or nowhere
# — an aggregator that does not serve what the picker offers is the broken promise recorded above.
_VERCEL_RESLUG = {
    "qwen3.7-max":        "alibaba/qwen3.7-max",
    "qwen3.8-max":        "alibaba/qwen3.8-max",
    "qwen3.7-flash":      "alibaba/qwen3.7-flash",
    "mistral-medium-3.5": "mistral/mistral-medium-3.5",
}
_VENDOR_MODELS["vercel"] = {c: _VERCEL_RESLUG.get(c, v)
                            for c, v in _VENDOR_MODELS["openrouter"].items()}

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
    if backend == "claude" or (backend in ("hermes", "pi", "dsh") and provider in ("anthropic", "bedrock")):
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
    # pi (earendil-works pi coding agent) is multi-family the same way hermes is: the CLI's
    # unified LLM layer runs either family natively and anything OpenAI/Anthropic-compatible
    # through a custom provider. The list grew the same way hermes's did — a model is added when
    # a real pi turn on the live provider has been checked for substitution:
    #   2026-08-19: gpt + claude families through the product path (claude-haiku-4.5 and
    #   gpt-5.4-mini, TokenRouter connection, trace checked for substitution).
    #   2026-08-19: the frontier set below, each probed through the pi CLI on the TokenRouter
    #   connection (openai-completions custom provider); every reply echoed exactly and every
    #   response reported the requested model id. hunyuan-3, ling-3.0-flash, minimax-m3,
    #   nemotron-3-ultra and qwen3.7-flash are NOT here: TokenRouter lists no channel for them,
    #   hermes serves them via OpenRouter, and no OpenRouter credential was available to probe
    #   pi with — unprobed is unlisted, per the bar at the top of this table.
    # dsh (DeepSeek Harness) went multi-family once the single-provider phase the audit
    # required had proven itself (deepseek family, full product path, 2026-08-20). The wider
    # families ride dsh-llm-pi-ai — pi's LLM library as a dsh plugin — through the driver's
    # relay, so the serving paths are the ones pi's rows already earned; each family below was
    # re-verified through a real dsh turn on the TokenRouter connection, substitution-checked,
    # and the frontier set was probed per-model through the dsh driver (2026-08-20).
    "dsh": {"default": "deepseek-v4-pro",
            "models": ["deepseek-v4-pro", "deepseek-v4-flash",
                       "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
                       "gpt-5.4", "gpt-5.4-mini", "gpt-5.2", "gpt-5.3-codex",
                       "claude-opus-5", "claude-fable-5", "claude-opus-4.8", "claude-sonnet-5",
                       "claude-opus-4.7", "claude-sonnet-4.6", "claude-haiku-4.5",
                       "gemini-3.6-flash", "kimi-k3", "kimi-k2.7-code",
                       "qwen3.7-max", "qwen3.8-max",
                       "mistral-medium-3.5", "step-3.7-flash"]},
    "pi": {"default": "gpt-5.4",
           "models": ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
                      "gpt-5.4", "gpt-5.4-mini", "gpt-5.2", "gpt-5.3-codex",
                      "claude-opus-5", "claude-fable-5", "claude-opus-4.8", "claude-sonnet-5",
                      "claude-opus-4.7", "claude-sonnet-4.6", "claude-haiku-4.5",
                      "gemini-3.6-flash", "deepseek-v4-pro", "deepseek-v4-flash", "kimi-k3",
                      "kimi-k2.7-code", "qwen3.7-max", "qwen3.8-max",
                      "mistral-medium-3.5", "step-3.7-flash"]},
}
_BARE_MODELS = {"", "claude", "codex", "anthropic", "bedrock", "openai", "hermes", "pi", "dsh", "deepseek"}
# Models whose serving CHANNEL refuses image input outright. Measured, not assumed — probed
# 2026-08-19 on the TokenRouter connection with a data-URI image in a user message:
#   qwen3.7-max  -> 400 InvalidParameter "Unexpected item type in content"  (rejects the TYPE)
#   qwen3.8-max  -> 400 about image DIMENSIONS (a 1x1 probe) — i.e. it accepts images
#   gemini-3.6-flash, deepseek-v4-pro, kimi-k3, mistral-medium-3.5, step-3.7-flash -> all 200
# Consumed by the pi backend: pi replays a session's image tool-results to the CURRENT model
# (a cross-model conversation is one session), so a text-only channel turns every follow-up in
# an image-bearing session into a hard 400. Declared text-only, pi drops the image instead —
# a degraded answer beats a dead conversation.
_TEXT_ONLY_INPUT = {"qwen3.7-max"}
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
    if base == "pi":
        return "pi"
    if base in ("dsh", "deepseek-harness"):
        return "dsh"
    return ""


def _model_authorized(requested: str, backend: str) -> bool:
    r = (requested or "").strip().lower()
    if not r:
        return False
    if r in {m.lower() for m in _MODEL_CATALOG.get(backend, {}).get("models", [])}:
        return True
    if backend in ("claude", "hermes", "pi", "dsh") and r in _PROVIDER_CLAUDE_IDS:
        return True   # power users may pass a provider-native claude id (claude-opus-4-8 / us.anthropic...)
    if backend in ("codex", "hermes", "pi", "dsh") and r.startswith("gpt-"):
        return True   # gpt-* family; Azure deployment names vary
    if backend == "dsh" and r.startswith(("deepseek", "deepseek/")):
        return True   # deepseek family; aggregator slugs vary (deepseek/deepseek-v4-pro)
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
        # The vertex names the harness the session belongs to, and every app route addressed to a
        # harness refuses a session that names none — correctly, since an unnamed session cannot be
        # proved to be this harness's. But the stamp is written at CREATION only, and this is the
        # other moment the answer is known: a session made before the stamp existed, or made with no
        # harness at all and later run on one, would name none forever and its canvas would 404 for
        # good. So fill it in here — ONCE, and only into a blank.
        #
        # NEVER OVERWRITE. Re-pointing a session that already names a harness at whoever happened to
        # run the next turn is exactly the cross-harness read those routes exist to refuse: two
        # agents in one org, both legitimate callers, and the second one silently inherits the
        # first's canvas, jobs and rendered bytes. `harness_id` is caller-supplied; a blank is the
        # only state where nobody's claim is being taken away.
        if harness_id and v is not None and not str(v.get("harness_id") or ""):
            await _vertex_upsert(sid, {"harness_id": harness_id, "harness_name": harness_name or ""})
            await _vg_edge("USES", sid, harness_id)   # same topology edge the create path stamps
            v["harness_id"], v["harness_name"] = harness_id, harness_name or ""
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
    mcp_servers, skills, skills_suppressed, tools_disabled = await _harness_plugins(harness_id, org, hdr_vals, hv=hv, sid=sid)
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
                # pi: whether this model's channel takes image input (see _TEXT_ONLY_INPUT)
                "vision": model_req.strip().lower() not in _TEXT_ONLY_INPUT,
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
    # The checkpoint replaced the workspace tarball with the sandbox's own copy, so anything the
    # media server wrote into it during the turn is gone. Re-project here — one line, one place,
    # and the only ordering at which a hosted write survives.
    if sid in _media_project_due:
        await _media_project(sid)
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
    _BARE = {"claude", "codex", "anthropic", "bedrock", "openai", "hermes", "pi", "dsh", "deepseek", ""}
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
        raise HTTPException(400, f"no provider configured for backend '{backend}'. Add an "
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
    # Through the one reader, so this scan sees exactly the servers the turn will get.
    for _s in _mcp_list(hv):
        if str(_s.get("enabled")) in ("False", "false", "0"):
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


async def _ssrf_check(url: str) -> str | None:
    """The ONE rule for whether this server may talk to an MCP endpoint.

    V1C02-006: gate a caller-supplied MCP URL before the server fetches it. HTTPS only; resolve
    EVERY DNS answer and reject loopback / link-local / CGNAT / RFC1918 / IPv6 private / cloud
    metadata (169.254.169.254 falls under link-local). Returns an error string to reject, or None
    to allow.

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

    from urllib.parse import urlparse
    try:
        u = urlparse(url)
    except Exception:  # noqa: BLE001
        return "invalid url"
    if u.scheme != "https":
        return "only https MCP endpoints are allowed"
    if not u.hostname:
        return "url has no host"
    return await _internal_target(u.hostname, u.port or 443)


# The internal ranges Python's own classifiers do not call internal. Named here rather than folded
# into `not ip.is_global`, because that would also reject 192.0.0.0/24 and the documentation ranges
# and nobody would know why.
#
#   100.64.0.0/10  carrier-grade NAT, and what a managed Kubernetes cluster hands its pods and its
#                  nodes. Not RFC1918, so `is_private` is False: it was the one whole IPv4 range
#                  this classifier let through, and a provider naming a pod address had this
#                  server fetching from inside its own cluster.
#   fec0::/10      IPv6 site-local. Deprecated by RFC 3879, which is exactly why Python answers
#                  False to both `is_private` and `is_reserved` for it — the same hole as CGNAT,
#                  for the same reason, on the other address family.
_INTERNAL_NETS = (ipaddress.ip_network("100.64.0.0/10"),
                  ipaddress.ip_network("::ffff:100.64.0.0/106"),
                  ipaddress.ip_network("fec0::/10"))


async def _internal_target(host: str, port: int) -> str | None:
    """Does this hostname resolve somewhere a caller must not be able to point this server?

    EVERY DNS answer is resolved and classified — loopback, link-local (which is where cloud
    metadata lives), RFC1918, CGNAT, IPv6 private, reserved — so a name whose second A record is
    internal is refused on the strength of that second record.

    WHAT IT DOES NOT DO, because a comment claiming otherwise is worse than no comment: it does not
    survive a DNS rebind. This resolves the name; httpx then resolves it AGAIN when it opens the
    socket, so a TTL-0 name that answers 93.184.216.34 here can answer 10.0.0.5 a millisecond
    later and this check will have passed. Closing that means pinning the address we classified
    into the connection itself, which is a different piece of work and is not what this does. What
    it buys is the multi-A case and every literal internal address, and that is the whole of it.

    Shared by MCP URLs, database hosts and provider-supplied file URLs because it is one question,
    not three: each is a target somebody else names and this server then opens a socket to. A
    second copy of this rule would be a second thing to remember to fix.

    A LOOKUP THAT DID NOT ANSWER IS NOT AN ANSWER. This used to take an `allow_unresolvable` flag,
    on the reasoning that a name which does not resolve is not internal and cannot be reached
    anyway — and its `except Exception` swallowed a resolver timeout, an EAI_AGAIN under load and
    a resolver that was down along with the genuine NXDOMAIN. Our lookup failing says nothing
    about what the socket does a millisecond later: the caller resolves again, from its own
    resolver, in a cluster where `.svc` is a search domain. So there is no allow branch at all —
    an address this server could not classify is one it does not open a socket to.

    The two failures are still told apart, because the operator reading the log needs them apart:
    one of them is a bad URL and the other is a broken resolver.

    ASYNC BECAUSE getaddrinfo BLOCKS. It is a synchronous C call and it can sit for the resolver's
    whole timeout; run on the event loop it stops the entire process, not one request. Measured: a
    1.01 s lookup let ZERO other tasks run. Every provider file URL is classified on every poll, so
    one relay naming a slow-resolving host froze the gateway for everybody, ten seconds apart.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        no_such = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
        return "host does not resolve" if e.errno in no_such else "host could not be resolved"
    except Exception:  # noqa: BLE001
        return "host could not be resolved"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified
                or any(ip in net for net in _INTERNAL_NETS if ip.version == net.version)):
            return "target resolves to a disallowed (internal) address"
    return None


async def _mcp_list_tools(url: str, token: str) -> dict:
    """Probe a remote MCP server: initialize → notifications/initialized → tools/list. Returns
    {ok, server, tools:[{name,description}]} or {ok:false, error}. Used by the config UI's
    'Test connection'. Token may be a literal bearer or a vault:<ref> (resolved by the caller)."""
    ssrf = await _ssrf_check(url)
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


# ── The database, an ordinary MCP server ──────────────────────────────────────────────────────
# A customer's own database, connected to one Harness: the agent explores it to decide what a
# dashboard should show, and the dashboard re-runs its queries when someone opens it.
#
# Its entry in `mcp_servers` is INDISTINGUISHABLE from a third-party one — {id, name, url,
# transport, auth, enabled} and not one field more. Nothing stored says "this one is ours",
# because nothing has to: a server is ours if its url is one of our own addresses
# (_hosted_mcp_path), and that answer is already knowable.
#
# THE ENTRY AND THE CONNECTION LIVE IN DIFFERENT PLACES, on purpose:
#   * The ENTRY is configuration. It rides the vertex read every turn already does, is listed,
#     renamed, switched off and removed exactly as any other server, and holds nothing about
#     which database it reads.
#   * THE CONNECTION — engine, host, database, the DSN, how many sample rows may be read — is one
#     encrypted record at the key the entry's `auth` references, owned BY THE SERVER. It goes
#     through BACKING.secrets with require_encryption=True, so host and database are encrypted at
#     rest alongside the credential. It is read here, inside the gateway, at the moment of use:
#     the runner never receives it, the browser never receives it, and neither does the agent —
#     an agent is given a tool that runs SELECTs, not a credential.
#
# The record names the server it is for and the harness it belongs to, and each endpoint refuses a
# record not addressed to it (see _hosted_resolve). `auth` is a client-writable field on an
# ordinary entry and harness ids are public, so that binding — not the shape of a key — is what
# stops one harness pointing at another's connection.
#
# Everything a statement passes through — the read-only gate, the row cap, the timeout — is in
# sql_plane.py, so the app's refresh and the agent's tool cannot diverge.

# Both spellings of each engine, resolved once here so nothing downstream has to know that
# "postgresql" and "postgres" are the same thing.
_DB_ENGINE_ALIASES = {"postgres": "postgres", "postgresql": "postgres", "pg": "postgres",
                      "mysql": "mysql", "mariadb": "mysql"}
# The URL schemes each engine will accept. A MySQL string pasted into a Postgres connection is
# caught here, with a sentence, rather than by a driver timing out twenty seconds later.
_DB_SCHEMES = {"postgres": ("postgres", "postgresql"), "mysql": ("mysql", "mariadb")}
# Rows per table the agent sees when sampling is ON. Enough to tell an id from a status string
# and a cents column from a dollars one; not enough to be an export of anyone's customer list.
_DB_SAMPLE_ROWS = 5
# The cap on an agent's own SELECT. Far below the app's, because an agent is checking that a
# query works before it writes it into a panel — 5000 rows of that is tokens, not information.
_DB_AGENT_MAX_ROWS = 200


def _db_engine(engine: str) -> str:
    e = _DB_ENGINE_ALIASES.get((engine or "").strip().lower())
    if not e:
        raise uhp_error(400, "unsupported_engine",
                        "This connects to PostgreSQL and MySQL databases.", "engine")
    return e


def _db_parse(engine: str, conn: str) -> tuple[str, str]:
    """(host, database) from a connection string, with the string itself validated.

    Parsed at attach time so a person can later confirm WHICH database is attached without the
    credential ever being read back out of the secret store."""
    from urllib.parse import urlparse
    try:
        u = urlparse((conn or "").strip())
    except Exception as e:  # noqa: BLE001
        raise uhp_error(400, "invalid_connection_string",
                        "That does not parse as a connection string.", "connection_string") from e
    if (u.scheme or "").lower() not in _DB_SCHEMES[engine]:
        want = "postgresql://user:password@host:5432/database" if engine == "postgres" \
            else "mysql://user:password@host:3306/database"
        raise uhp_error(400, "invalid_connection_string",
                        f"A {'PostgreSQL' if engine == 'postgres' else 'MySQL'} connection string "
                        f"looks like {want}", "connection_string")
    if not u.hostname:
        raise uhp_error(400, "invalid_connection_string",
                        "That connection string has no host.", "connection_string")
    db = (u.path or "/").lstrip("/")
    if not db:
        raise uhp_error(400, "invalid_connection_string",
                        "That connection string names no database — add /yourdatabase to the end.",
                        "connection_string")
    host = u.hostname + (f":{u.port}" if u.port else "")
    return host, db


def _hosted_secret_key(hid: str, entry_id: str) -> str:
    """Where the record for one hosted server on one harness lives. Same charset rule as
    harness-mcp-<ref>.

    The harness id is in it so an operator reading the secret store can tell what a record belongs
    to; the entry id is what allows MORE THAN ONE hosted server per harness — the "at most one
    database" rule only ever existed because a key derived from the harness id alone made two of
    them collide. The key is not a security boundary: the record names its own harness, and that
    is (see _hosted_resolve).
    """
    def safe(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return f"{_HOSTED_SECRET_PREFIX}{safe(hid) or 'harness'}-{safe(entry_id) or 'server'}"


async def _hosted_put_record(org: str, key: str, record: dict, *, secret: bool = True,
                             param: str = "connection_string") -> None:
    """Write a hosted server's record.

    `secret=True` — the default, and the database's case — says the record holds a customer
    credential: the connection string is in it, and so are the host and the database name, which
    is strictly more than the vertex ever protected. A store that cannot encrypt must refuse
    rather than write that in the clear.

    `secret=False` is for a record that holds only a BINDING, {server, harness}, with no credential
    in it at all — the media server's case, where the provider key belongs to this deployment's own
    integrations and never becomes a per-harness secret. It is still written encrypted wherever
    encryption is available; what changes is that an instance with no passphrase is not blocked
    from a feature that has no secret to protect.
    """
    tenant = org if _vault_tenant_ok(org) else GLOBAL_TENANT
    try:
        await BACKING.secrets.put(tenant, key, json.dumps(record), require_encryption=secret)
    except backing.SecretsNotConfigured as e:
        # 501 rather than 500: nothing is broken. This instance has not been given a key to
        # encrypt with, and refusing is the correct behaviour — the message names the variable
        # that fixes it, because a stack trace would not.
        raise uhp_error(501, "secrets_not_configured", str(e), param) from e


async def _hosted_record(org: str, key: str) -> dict | None:
    """A hosted server's record, or None when there is nothing readable to serve from.

    Deliberately NOT _resolve_mcp_auth: that helper falls back to treating a value as a literal
    bearer token, and refuses this namespace outright for exactly that reason.
    """
    if not key:
        return None
    for tenant in _tenants_for(org):
        raw = await _vault_get(tenant, key)
        if raw:
            try:
                rec = json.loads(raw)
            except Exception:  # noqa: BLE001
                return None
            return rec if isinstance(rec, dict) else None
    return None


def _hosted_keys(servers: list[dict]) -> set[str]:
    """The records a list of entries references. Read off the entries, because with a per-entry
    key the entry is the only thing that knows where its record is."""
    return {k for k in (_vault_key(s.get("auth")) for s in servers)
            if k.startswith(_HOSTED_SECRET_PREFIX)}


async def _hosted_scrub_removed(org: str, hid: str, before: list[dict], after: list[dict]) -> None:
    """Overwrite the record behind every hosted entry this write removed.

    Dropping the entry and leaving its connection string encrypted on disk would be a surprise of
    the worst kind: removing the tool, or deleting the agent, is the most decisive thing the
    surface offers. Shared by every write that can drop an entry, so they cannot promise
    differently.

    THE RECORD MUST BE THIS HARNESS'S — the same binding _hosted_resolve refuses a read on. `auth`
    is a client-writable field and harness ids are public, so anyone may name another agent's ref
    on an entry of their own; removing it would otherwise destroy a connection they were never
    given. Losing a database is the louder of the two surprises, so the check belongs on both.
    Positive evidence of foreign ownership is what skips the scrub: a record we cannot read is one
    we overwrite, because leaving a connection string behind is the failure this function exists
    to prevent.
    """
    gone = _hosted_keys(before) - _hosted_keys(after)
    if not gone:
        return
    tenant = org if _vault_tenant_ok(org) else GLOBAL_TENANT
    scrubbed = 0
    for key in sorted(gone):
        rec = await _hosted_record(org, key)
        if rec and str(rec.get("harness") or "") != hid:
            print(f"[mcp] {hid}: not scrubbing {key} — that record belongs to another agent",
                  flush=True)
            continue
        with contextlib.suppress(Exception):   # an unwritable store must not block the write
            await BACKING.secrets.put(tenant, key, "", require_encryption=True)
        scrubbed += 1
    if scrubbed:
        print(f"[sql] {hid}: disconnected ({scrubbed} record(s) scrubbed)", flush=True)


async def _mcp_write(hid: str, servers: list[dict]) -> None:
    """Write mcp_servers outside the config PUT — kit launch provisioning the server it needs."""
    await _vg_upsert("Harness", hid, {"mcp_servers": json.dumps(servers),
                                      "updated_at": str(int(time.time() * 1000))})


def _connection_out(rec: dict) -> dict:
    """What a caller may see of a connection: which database, and how much of it the agent reads.
    Everything except the credential."""
    return {"engine": str(rec.get("engine") or ""), "host": str(rec.get("host") or ""),
            "database": str(rec.get("database") or ""),
            "sampleRows": bool(rec.get("sample_rows"))}


# What every refusal below says. One sentence, because from the caller's side "there is no such
# entry", "its record is gone" and "that record is not yours" are the same fact: nothing here is
# connected to read.
_NOT_CONNECTED = "No database is connected to this agent yet."
# Per hosted server, because "No database is connected" is a lie about a media server and a lie in
# a refusal is worse than a vague one. Keyed by the server name _hosted_resolve was asked for, so
# a server added later declares its own sentence here and nowhere else.
_HOSTED_NOT_CONNECTED = {
    "database": ("database_not_connected", _NOT_CONNECTED),
    "media": ("media_not_connected", "No media tools are connected to this agent yet."),
}


async def _hosted_resolve(server: str, hid: str, org: str, servers: list[dict], *,
                          key: str = "", entry_id: str = "",
                          check_enabled: bool = False) -> tuple[dict, dict]:
    """(entry, record) for one server this gateway hosts — the resolution EVERY hosted endpoint
    shares, so the agent's tool and the app's data plane cannot answer differently.

    THE ENTRY IS FOUND BY WHAT ADDRESSED IT: the record key a turn credential carries, or the
    entry's own id from a route. Never by name, position or a flag — which is what makes renaming,
    reordering and several hosted servers on one harness free.

    THEN THE RECORD MUST BE ADDRESSED TO THIS SERVER AND THIS HARNESS. `auth` is a client-writable
    field on an ordinary entry and harness ids are public, so without the second check a caller
    could write another harness's ref onto their own entry and read a database they were never
    given. One structural check, behind the credential, that survives any write path added later —
    where a write-time validation would only cover the writes that exist today.

    `check_enabled` is for a turn and not for the app: switching a server off is a statement about
    what an AGENT is handed, and a dashboard refresh is not a turn. A token minted before the
    switch stays valid for hours, so the refusal has to be here and not only where turns are built.
    """
    code, msg = _HOSTED_NOT_CONNECTED.get(server, ("server_not_connected",
                                                   "That is not connected to this agent yet."))
    if key:
        entry = next((e for e in servers if _vault_key(e.get("auth")) == key), None)
    elif entry_id:
        entry = next((e for e in servers if str(e.get("id") or "") == entry_id), None)
    else:
        entry = None
    if not entry:
        raise uhp_error(404, code, msg, "harness_id")
    if check_enabled and str(entry.get("enabled")) in ("False", "false", "0"):
        raise uhp_error(404, code, msg, "harness_id")
    rec = await _hosted_record(org, _vault_key(entry.get("auth")))
    if not rec or rec.get("server") != server or rec.get("harness") != hid:
        raise uhp_error(404, code, msg, "harness_id")
    return entry, rec


async def _harness_for_route(hid: str, org: str) -> dict:
    """The harness a /servers/{sid} route is addressed to: owned by this org, not deleted, and
    converted off any earlier shape first — which is the reason this is a helper rather than the
    three inline lines every other route carries."""
    v = await _vertex_get(hid)
    if not v or v.get("org") != org or str(v.get("deleted")) in ("1", "true", "True"):
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    return await _mcp_migrate(org, hid, v)


# ── migration: two earlier shapes of "the harness's database" ─────────────────────────────────
# Shape 0, everything deployed: a `datasource` prop on the vertex. Shape 1, the refactor this
# replaces: an mcp_servers entry with `managed` and `config`. Both hold {engine, secret, host,
# database, sample_rows, updated_at} beside a BARE DSN at harness-ds-<hid-safe>.
#
# The payload genuinely changes — bare string to a JSON record, at a new key — so this is a
# CONVERTER and not a wrapper. A read-repair projection would force _hosted_record to understand
# two secret shapes forever, which is the accretion the house style forbids.
_DS_PROP_LEGACY = "datasource"


def _legacy_db_config(c) -> dict | None:
    """An earlier configuration block, or None. Fails closed: a block we cannot read has to mean
    "not connected", and a `secret` that is not a reference is not a fallback to a literal."""
    if not isinstance(c, dict) or c.get("engine") not in sql_plane.ENGINES:
        return None
    return c if str(c.get("secret") or "").startswith("vault:") else None


async def _mcp_migrate(org: str, hid: str, v: dict | None) -> dict | None:
    """Convert a database connected under either earlier shape into an ordinary hosted entry.

    Once, in place, on the first read that needs it — there is no global harness scan, and a
    customer connected before this change must not have a broken turn while an operator remembers
    to run something. Prints one [migrate] line per harness, so the condition for deleting this
    function is a number you can count rather than a guess.
    """
    if not v:
        return v
    # The HARNESS's org, not the caller's: this writes a record that belongs to the harness, and
    # only the vertex knows whose tenant that is.
    org = str(v.get("org") or org)
    # Parsed ONCE. Two _mcp_list calls return two sets of dicts parsed from the same JSON, so the
    # replacement below would match nothing and leave both entries on the harness.
    servers = _mcp_list(v)
    old_entry = next((e for e in servers if _legacy_db_config(e.get("config"))), None)
    cfg = _legacy_db_config((old_entry or {}).get("config"))
    if not cfg:
        try:
            cfg = _legacy_db_config(json.loads(v.get(_DS_PROP_LEGACY) or "null"))
        except Exception:  # noqa: BLE001
            cfg = None
    if not cfg:
        return v

    origins = _own_origins()
    if not origins:
        print(f"[migrate] {hid}: no address to serve its database on — set "
              f"HARNESS_PUBLIC_BASE_URL. Left as it was.", flush=True)
        return v
    old_key = cfg["secret"][len("vault:"):]
    dsn = ""
    for tenant in _tenants_for(org):
        dsn = await _vault_get(tenant, old_key) or ""
        if dsn:
            break
    if not dsn:
        # A harness we cannot migrate must not be a harness we silently disconnect.
        print(f"[migrate] {hid}: its stored credential could not be read — left as it was.",
              flush=True)
        return v

    entry_id = "mcp.database"
    key = _hosted_secret_key(hid, entry_id)
    # Every field taken from the old configuration: nothing re-derived, nothing re-parsed.
    await _hosted_put_record(org, key, {
        "server": "database", "harness": hid, "engine": cfg["engine"], "dsn": dsn,
        "host": cfg.get("host") or "", "database": cfg.get("database") or "",
        "sample_rows": int(cfg.get("sample_rows") or 0),
        "updated_at": int(cfg.get("updated_at") or 0)})
    entry = {"id": entry_id, "name": str((old_entry or {}).get("name") or "database"),
             "url": origins[0] + _HOSTED_MCP_PREFIX + "database", "transport": "http",
             "auth": f"vault:{key}",
             "enabled": str((old_entry or {}).get("enabled", True)) not in ("False", "false", "0")}
    servers = [e for e in servers if e is not old_entry] + [entry]
    await _vg_upsert("Harness", hid, {"mcp_servers": json.dumps(servers), _DS_PROP_LEGACY: ""})
    with contextlib.suppress(Exception):   # an unwritable store must not strand the conversion
        tenant = org if _vault_tenant_ok(org) else GLOBAL_TENANT
        await BACKING.secrets.put(tenant, old_key, "", require_encryption=True)
    print(f"[migrate] {hid}: database is now an ordinary MCP server", flush=True)
    return {**v, "mcp_servers": json.dumps(servers), _DS_PROP_LEGACY: ""}


def _sql_http(e: Exception) -> HTTPException:
    """One rule for turning a SQL failure into a response.

    Refused means we stopped it before it reached the database — that is the caller's statement,
    so 400. Anything else means the database itself answered with a failure, upstream of us, so
    502. Both carry the sentence the caller can act on ('column "revenu" does not exist').
    """
    if isinstance(e, sql_plane.SqlRefused):
        return uhp_error(400, "sql_refused", str(e), "sql")
    return uhp_error(502, "sql_failed", str(e), "sql")


class DatabaseTestBody(BaseModel):
    engine: str
    connection_string: str


async def _db_validate(engine: str, conn: str) -> tuple[str, str, str, str]:
    """(engine, connection string, host, database) — or the 400 that says what is wrong with it.

    Provisions nothing, so kit launch can check what it was given BEFORE it provisions anything: a
    typo in a connection string should not leave a half-configured Harness behind. It is not free,
    though: classifying the host is a DNS lookup, which is why it is awaited."""
    eng = _db_engine(engine)
    c = (conn or "").strip()
    if not c:
        raise uhp_error(400, "invalid_connection_string",
                        "A connection string is required.", "connection_string")
    host, db = _db_parse(eng, c)
    # A connection string is a target this server opens a socket to on a caller's say-so, which is
    # the same thing an MCP URL is — so it passes the same check, for the same reason, with the
    # same exemption: self-hosted, the "internal" network is the operator's own machine and a
    # database on localhost is the normal case rather than an attack.
    if not _pool_is_local():
        hostname, _, port = host.partition(":")
        blocked = await _internal_target(hostname, int(port) if port.isdigit() else
                                         (5432 if eng == "postgres" else 3306))
        if blocked:
            raise uhp_error(400, "unreachable_host",
                            f"This server cannot connect to {hostname}: {blocked}.",
                            "connection_string")
    return eng, c, host, db


async def _hosted_db_entry(hid: str, v: dict | None, decl: dict) -> None:
    """The database ENTRY, with no credential in it.

    A kit that declares `launch.database` gets its database tool the moment it is launched, the
    same way a kit that declares media gets its media tool — because the tool belongs to the KIT
    DEFINITION, not to the credential. Tying the entry's existence to a connection string meant
    a dashboard harness could sit there with the five built-in tools and no way to reach a
    database, and nothing on the page explaining that the tool was missing rather than broken.

    An entry with no record is honestly unconnected: the tool is listed, and asking it anything
    says so. That is a better thing to hand someone than a tool that is not there at all, which
    reads as "this kit cannot do that" rather than "this kit is not finished being set up".

    Never overwrites a connected entry — reconnecting is _hosted_db_attach's job, and this runs
    on every launch including the idempotent second press.
    """
    origins = _own_origins()
    if not origins:
        raise uhp_error(501, "gateway_address_not_configured",
                        "This server has no address an agent could reach it on — set "
                        "HARNESS_PUBLIC_BASE_URL.", "database")
    cur = _mcp_list(v)
    if any(str(e.get("id") or "") == decl["id"] for e in cur):
        return                                   # already there, connected or not
    entry = {"id": decl["id"], "name": decl["name"],
             "url": origins[0] + _HOSTED_MCP_PREFIX + "database", "transport": "http",
             "enabled": True}
    await _mcp_write(hid, cur + [entry])
    print(f"[sql] {hid}: database tool provisioned (no connection yet)", flush=True)


async def _hosted_db_attach(org: str, hid: str, v: dict | None, decl: dict,
                            checked: tuple[str, str, str, str], sample_rows: bool) -> None:
    """Provision a database connection: one encrypted record, one ordinary entry.

    THE ONLY THING THAT EVER WRITES A RECORD, and kit launch is its only caller — connecting a
    database is something the kit that reads one drives, not something the tool list exposes.

    Reconnecting after a password change replaces the record ON THE EXISTING ENTRY, reusing that
    entry's key, so no record is left orphaned behind. `name` and `enabled` come from the entry
    being replaced: they belong to whoever configured the harness, and reconnecting is a statement
    about the credential and about nothing else.
    """
    engine, conn, host, db = checked
    origins = _own_origins()
    if not origins:
        # An entry with no url is not an ordinary entry, so refusing beats storing a broken one.
        raise uhp_error(501, "gateway_address_not_configured",
                        "This server has no address an agent could reach it on — set "
                        "HARNESS_PUBLIC_BASE_URL.", "database")
    cur = _mcp_list(v)
    prev = next((e for e in cur if str(e.get("id") or "") == decl["id"]), None) or {}
    prev_key = _vault_key(prev.get("auth"))
    key = prev_key if prev_key.startswith(_HOSTED_SECRET_PREFIX) else _hosted_secret_key(hid, decl["id"])
    await _hosted_put_record(org, key, {
        "server": "database", "harness": hid, "engine": engine, "dsn": conn,
        "host": host, "database": db,
        # Stored as the row COUNT introspection will take, not as a boolean, so the one place that
        # decides how much data leaves the customer's database is this line.
        "sample_rows": _DB_SAMPLE_ROWS if sample_rows else 0,
        "updated_at": int(time.time() * 1000)})
    entry = {"id": decl["id"], "name": str(prev.get("name") or decl["name"]),
             "url": origins[0] + _HOSTED_MCP_PREFIX + "database", "transport": "http",
             "auth": f"vault:{key}",
             "enabled": str(prev.get("enabled", True)) not in ("False", "false", "0")}
    await _mcp_write(hid, [e for e in cur if str(e.get("id") or "") != decl["id"]] + [entry])
    # host and database only. The credential is not printed, here or anywhere.
    print(f"[sql] {hid}: connected {engine} {host}/{db} "
          f"(sample rows {'on' if sample_rows else 'off'})", flush=True)


async def _db_probe(engine: str, conn: str) -> dict:
    """Try a connection string, and say what went wrong if it fails.

    Same shape as /v1/mcp-test: {ok:true, …} or {ok:false, error} with HTTP 200, because "your
    password is wrong" is a successful test that reports a failure, not a failed request.
    """
    # Validated exactly as attaching would validate it, so a string this button accepts is a
    # string the save accepts. A test that does not predict what happens next is worse than none.
    engine, conn, host, db = await _db_validate(engine, conn)
    try:
        # Not SELECT 1: reaching the database proves the credential, and reading the catalog
        # proves the account can see tables — which is the failure people actually hit when they
        # follow the advice to use a read-only account and grant it nothing.
        schema = await sql_plane.introspect(engine, conn, sample_rows=0, timeout=15.0)
    except sql_plane.SqlError as e:
        return {"ok": False, "engine": engine, "host": host, "database": db, "error": str(e)}
    return {"ok": True, "engine": engine, "host": host, "database": db,
            "tableCount": schema["table_count"],
            "tables": [f"{t['schema']}.{t['name']}" for t in schema["tables"][:12]]}


# Two probes rather than one because a DSN is not a URL: /v1/mcp-test takes {url, auth} and this
# takes {engine, connection_string}, and a union body would be worse than two names. Both come in
# an org-scoped and a public flavour so a console that tests either kind has one auth shape.
@app.post("/v1/orgs/{org}/mcp-test/database")
async def test_database(org: str, body: DatabaseTestBody, request: Request) -> dict:
    await _owned_org(request, org)
    return await _db_probe(body.engine, body.connection_string)


@app.post("/v1/mcp-test/database")
async def test_database_public(body: DatabaseTestBody, request: Request) -> dict:
    await _pub_org_member(request)
    return await _db_probe(body.engine, body.connection_string)


class SqlQueryBody(BaseModel):
    sql: str
    max_rows: int | None = None


# ── the app's data plane: one hosted server, addressed by the entry that names it ─────────────
# A dashboard re-runs every panel's query when someone opens it, and doing that through the agent
# would cost a turn per panel per page-load. Not a second mechanism for the same thing — a browser
# is not an MCP client and must never hold a turn credential — and every statement still passes
# the same read-only gate, row cap and timeout the agent's own tool does.
#
# Addressed by entry id rather than by harness, because "the harness's database" is the same
# assumption that put connection state on the vertex: a harness may have several hosted servers,
# and the caller has to be able to say which. The harness segment carries authorization; the
# server segment names the server.

@app.get("/v1/harnesses/{hid}/servers/{sid}")
async def get_harness_server(hid: str, sid: str, request: Request) -> dict:
    """One server this gateway hosts, describing itself — including what it is connected to.

    The server that owns the connection is the one that names it, exactly as tools/list is a
    third-party server describing itself. Connection state does not ride a harness read.
    """
    org, _ = await _pub_org_member(request)
    v = await _harness_for_route(hid, org)
    # WHICH server this is comes from the record, not from a field on the entry and not from the
    # route. One route, because "the server describing itself" is one question — and the entry has
    # nothing on it to branch on, which is the property this whole shape exists to keep.
    entry, rec = await _hosted_resolve_any(hid, org, _mcp_list(v), entry_id=sid)
    out = {"id": entry.get("id"), "name": entry.get("name"),
           "enabled": str(entry.get("enabled", True)) not in ("False", "false", "0")}
    if str(rec.get("server") or "") == _MEDIA_SERVER:
        return {**out, **await _media_server_out()}
    return {**out, "connection": _connection_out(rec)}


def _hosted_server_name(entry: dict | None) -> str:
    """Which server an entry SAYS it is, from its own url. "" for anything not ours.

    The entry's url, and not the record it names: the url is the caller's own statement about what
    they are addressing, so shaping a refusal with it tells them nothing they did not already say.
    Reading the server name off a record they merely named would answer "that key is a database"
    to anyone who guessed a key.
    """
    path = _hosted_mcp_path(str((entry or {}).get("url") or ""))
    return path[len(_HOSTED_MCP_PREFIX):] if path else ""


async def _hosted_resolve_any(hid: str, org: str, servers: list[dict], *,
                              entry_id: str) -> tuple[dict, dict]:
    """(entry, record) for whichever server this gateway hosts at that entry.

    Not a second resolution — the same one, with the server name taken from the entry instead of
    asserted by the caller. Used only where the question is "what is this", never where it is
    "read this": every route that acts on a server still names the server it means.
    """
    entry = next((e for e in servers if str(e.get("id") or "") == entry_id), None)
    return await _hosted_resolve(_hosted_server_name(entry), hid, org, servers, entry_id=entry_id)


@app.post("/v1/harnesses/{hid}/servers/{sid}/query")
async def run_server_query(hid: str, sid: str, body: SqlQueryBody, request: Request) -> dict:
    """Run one SELECT — what refreshing a dashboard panel does."""
    org, _ = await _pub_org_member(request)
    v = await _harness_for_route(hid, org)
    _entry, rec = await _hosted_resolve("database", hid, org, _mcp_list(v), entry_id=sid)
    want = int(body.max_rows or sql_plane.DEFAULT_MAX_ROWS)
    max_rows = max(1, min(want, sql_plane.DEFAULT_MAX_ROWS))
    try:
        return await sql_plane.run_query(rec["engine"], rec["dsn"], body.sql or "", max_rows=max_rows)
    except sql_plane.SqlError as e:
        raise _sql_http(e) from e


@app.get("/v1/harnesses/{hid}/servers/{sid}/schema")
async def get_server_schema(hid: str, sid: str, request: Request) -> dict:
    """The shape of the connected database: tables, columns, types — and a few rows per table when
    the person left sample rows on. `sampled` in the response says which they got."""
    org, _ = await _pub_org_member(request)
    v = await _harness_for_route(hid, org)
    _entry, rec = await _hosted_resolve("database", hid, org, _mcp_list(v), entry_id=sid)
    try:
        return await sql_plane.introspect(rec["engine"], rec["dsn"],
                                          sample_rows=int(rec.get("sample_rows") or 0))
    except sql_plane.SqlError as e:
        raise _sql_http(e) from e


# ── the agent's side: an MCP server this gateway hosts ────────────────────────────────────────
# An agent designing a dashboard needs two things: the schema, and the ability to run a candidate
# query and see rows or the error. It must never need the credential.
#
# This is a built-in MCP server rather than a built-in tool because THERE IS NO BUILT-IN TOOL
# MECHANISM to use: every base runs a third-party CLI (Claude Code, Codex, hermes) with its own
# fixed tool set, and the only channel this server has for adding a capability to all three is the
# MCP config the runner already writes for each of them (_write_mcp_config_claude / _codex_mcp_toml
# / _hermes_mcp_section). Hosting the server here rather than as a separate process is what keeps
# the credential in the gateway: the sandbox is handed a URL and a per-turn token, resolves nothing
# itself, and a token that leaks buys one session's read access to one database and expires with it.
_DB_MCP_TOOLS = [
    {"name": "schema",
     "description": ("Tables and columns in the connected database, with types. Call this first: "
                     "it is the only way to learn what can be charted."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "query",
     "description": (f"Run one read-only SELECT and see the rows (up to {_DB_AGENT_MAX_ROWS}). "
                     "Use it to check a query works before putting it in a dashboard panel. "
                     "Only SELECT is accepted; anything that would modify data is refused."),
     "inputSchema": {"type": "object", "required": ["sql"],
                     "properties": {"sql": {"type": "string", "description": "One SELECT statement."}},
                     "additionalProperties": False}},
]


def _mint_hosted_cred(hid: str, sid: str, key: str) -> str:
    """Per-turn credential for a server this gateway hosts: harness.session.record.exp.hmac.

    The same HMAC construction as the model broker's turn credential (_mint_turn_cred) and
    deliberately a different prefix and a different claim set: this one authorises reading one
    record on one harness and nothing else, so a token lifted out of a sandbox cannot be replayed
    at the broker, and one lifted from the broker cannot read a database.
    """
    exp = str(int(time.time()) + _BROKER_TTL_S)
    body = f"{hid}|{sid}|{key}|{exp}"
    sig = hmac.new((INTERNAL_KEY or "dev-insecure").encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"hrs_{base64.urlsafe_b64encode(body.encode()).decode().rstrip('=')}.{sig}"


def _verify_hosted_cred(tok: str) -> tuple[str, str, str] | None:
    """(harness_id, session_id, record key) for a valid unexpired token, else None."""
    if not tok or not tok.startswith("hrs_"):
        return None
    try:
        b64, sig = tok[4:].rsplit(".", 1)
        body = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode()
        hid, sid, key, exp = body.split("|")
    except Exception:  # noqa: BLE001 — a malformed token is simply invalid
        return None
    good = hmac.new((INTERNAL_KEY or "dev-insecure").encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good) or int(exp) < int(time.time()):
        return None
    return hid, sid, key


def _jsonrpc_result(rid, result: dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})


def _tool_text(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


@app.post("/v1/mcp/database")
async def database_mcp(request: Request):
    """The MCP endpoint the agent's CLI talks to. Streamable HTTP, stateless.

    Stateless — no mcp-session-id — because there is nothing to keep between calls: every request
    carries the token that identifies the harness and the record, and the connection is opened and
    closed per query. That also means any replica can serve any call.
    """
    claims = _verify_hosted_cred(_broker_token(request))
    if not claims:
        raise HTTPException(401, "invalid or expired turn credential")
    hid, _sid, key = claims
    try:
        req = json.loads(await request.body() or b"{}")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "malformed JSON-RPC request") from None
    method, rid, params = req.get("method") or "", req.get("id"), req.get("params") or {}

    if method == "initialize":
        return _jsonrpc_result(rid, {
            # Echo the client's protocol version when it names one: every CLI in play speaks a
            # different revision and this server's two tools are identical in all of them.
            "protocolVersion": str(params.get("protocolVersion") or "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "database", "version": "1"}})
    if rid is None:            # a notification (notifications/initialized) — nothing to answer
        return Response(status_code=202)
    if method == "tools/list":
        return _jsonrpc_result(rid, {"tools": _DB_MCP_TOOLS})
    if method != "tools/call":
        return JSONResponse({"jsonrpc": "2.0", "id": rid,
                             "error": {"code": -32601, "message": f"method not found: {method}"}})

    v = await _harness_vertex(hid)
    if v and str(v.get("deleted")) in ("1", "true", "True"):
        v = None                    # a token outlives the agent it was minted for; the agent's
                                    # database access must not
    org = str((v or {}).get("org") or "")
    try:
        _entry, rec = await _hosted_resolve("database", hid, org, _mcp_list(v),
                                            key=key, check_enabled=True)
    except HTTPException:
        # Every refusal, in the agent's terms. The last clause is load-bearing: without it a model
        # spends the rest of the turn looking for a way to connect one itself.
        return _jsonrpc_result(rid, _tool_text(
            "No database is connected to this agent. Ask the person to connect one, then try "
            "again — you cannot connect it yourself.", True))
    name = params.get("name") or ""
    args = params.get("arguments") or {}
    try:
        if name == "schema":
            out = await sql_plane.introspect(rec["engine"], rec["dsn"],
                                             sample_rows=int(rec.get("sample_rows") or 0))
            # WHICH database this is, from the record that owns it. The kit's skill tells the agent
            # to copy this into the dashboard it writes, and the agent has no other way to know.
            out["connection"] = _connection_out(rec)
            if not out.get("sampled"):
                # Said plainly, because an agent that does not know sampling is off will read the
                # absence of rows as an empty database and design a dashboard for one.
                out["note"] = ("Sample rows are turned off for this connection, so you see the "
                               "shape of the data and none of its values. Use the query tool to "
                               "check a specific figure.")
            return _jsonrpc_result(rid, _tool_text(json.dumps(out, ensure_ascii=False)))
        if name == "query":
            out = await sql_plane.run_query(rec["engine"], rec["dsn"], str(args.get("sql") or ""),
                                            max_rows=_DB_AGENT_MAX_ROWS)
            return _jsonrpc_result(rid, _tool_text(json.dumps(out, ensure_ascii=False)))
    except sql_plane.SqlError as e:
        # The database's own sentence, back to the agent as a tool error so it can fix the query
        # itself. This is the loop that makes the tool worth having.
        return _jsonrpc_result(rid, _tool_text(str(e), True))
    except HTTPException as e:
        return _jsonrpc_result(rid, _tool_text(_uhp_message(e), True))
    return _jsonrpc_result(rid, _tool_text(f"No tool named {name!r} on this server.", True))


def _uhp_message(e: HTTPException) -> str:
    d = e.detail
    return str(d.get("message")) if isinstance(d, dict) and d.get("__uhp__") else str(d)


# ── Media, an ordinary MCP server ─────────────────────────────────────────────────────────────
# Making a picture, a clip or a line of speech, and cutting the clips into one film. Same shape as
# the database next door and for the same reasons: its entry in `mcp_servers` is INDISTINGUISHABLE
# from a third-party one, a server is ours because its url is one of our own addresses, and the
# record the entry's `auth` names is owned BY THE SERVER.
#
# WHAT IS DIFFERENT FROM THE DATABASE, and it is only this: nothing is collected from anyone. A
# database record holds a customer's connection string; a media record holds only the binding
# {server, harness}, because the provider credential is THIS DEPLOYMENT'S OWN INTEGRATION and must
# never become a per-harness secret. The record with no secret in it is the whole trick — the
# `harness-hosted-` prefix is still what makes the entry offerable, and `rec["harness"] == hid` is
# still what stops one harness addressing another's canvas.
#
# THE AGENT NEVER NAMES A MODEL. It asks for a capability; media_plane walks that capability's
# ordered candidate list and the tool reports which model actually ran. Four video models are
# listed and two are broken, which is exactly why.
#
# THE CANVAS IS OWNED BY THIS SERVER, not by the session workspace. Hosted, the gateway cannot
# durably write a live sandbox's workspace mid-turn — `_checkpoint` replaces the whole tarball from
# the sandbox at turn end, so anything written into it in between is gone (which is why
# PUT /v1/sessions/{sid}/files/{path} answers 409). So the scene lives in blob storage and is
# PROJECTED into the workspace after every mutation and after every checkpoint, write-only, so
# `scene.excalidraw` is still an ordinary artifact the console lists. Generated media are NOT
# projected: the workspace is a tarball rewritten whole at every checkpoint, and a ten-clip project
# would re-upload two hundred megabytes on every subsequent turn.

_MEDIA_SERVER = "media"
_MEDIA_SCENE_FILE = "scene.excalidraw"
# How long a still is held when the cut does not say lives with the rest of that decision, in
# media_plane.shot_window — a second copy here is how the total and the film came to disagree.
# Candidates stood down after a BILLABLE failure. Per-replica and in memory on purpose: it is a
# hint that saves money, not state anything depends on, and a replica that has not seen the
# failure simply pays for one more attempt rather than serving a stale verdict for half an hour.
_media_quarantine: dict[str, float] = {}
# One lock per session, so read-modify-write of a scene is serialised and the canvas tools never
# have to fail on concurrency.
_media_scene_locks: dict[str, asyncio.Lock] = {}
_media_job_locks: dict[str, asyncio.Lock] = {}
# Sessions whose scene moved since the last projection. The sweeper drains this, so a job that
# lands with no turn running still leaves an up-to-date artifact behind.
_media_project_due: set[str] = set()

# What each capability produces. The one place kind is decided, so a job, an element and a stored
# file cannot disagree about whether a thing is a video.
_MEDIA_KIND = {"text_to_video": "video", "image_to_video": "video",
               "text_to_image": "image", "image_to_image": "image",
               "text_to_speech": "audio", "text_to_music": "audio", "export": "film"}


def _media_scene_lock(sid: str) -> asyncio.Lock:
    lk = _media_scene_locks.get(sid)
    if lk is None:
        lk = _media_scene_locks[sid] = asyncio.Lock()
    if len(_media_scene_locks) > 4000:          # bounded; an unheld lock is free to drop
        for k in [k for k, v in list(_media_scene_locks.items()) if not v.locked()][:2000]:
            _media_scene_locks.pop(k, None)
    return lk


def _media_job_lock(jid: str) -> asyncio.Lock:
    """One advance per job at a time. The sweeper, the agent's check_jobs and the app's poll route
    all advance jobs, and they run concurrently by design — so without this they each saw the same
    SUCCESS, each downloaded the same clip and each stored it under a NEW media id. Measured: one
    6 s clip landed three times, ~4 MB apiece, two of them orphaned the moment the third won the
    vertex. Same shape and same bound as the scene lock, because it is the same problem.
    """
    lk = _media_job_locks.get(jid)
    if lk is None:
        lk = _media_job_locks[jid] = asyncio.Lock()
    if len(_media_job_locks) > 4000:
        for k in [k for k, v in list(_media_job_locks.items()) if not v.locked()][:2000]:
            _media_job_locks.pop(k, None)
    return lk


def _media_client() -> httpx.AsyncClient:
    """The client every provider call goes through. One seam, so a test can drive all five
    adapters through a transport it controls without stubbing the adapters themselves."""
    return _client()


async def _media_providers() -> dict[str, dict]:
    """{provider: {api_key, base_url, auth}} for every catalog provider this deployment can reach.

    Read HERE, at the moment of use, from the integrations document — the same document the model
    broker reads. The key is returned to this process and to nothing else: it is never written into
    a record, never put on a vertex, never handed to the runner and never sent to a browser.
    """
    out: dict[str, dict] = {}
    integrations = await _integrations_doc()
    for pname, pmeta in (media_plane.catalog().get("providers") or {}).items():
        want = str((pmeta or {}).get("integration_provider") or pname).strip().lower()
        for integ in integrations:
            if str(integ.get("provider") or "").strip().lower() != want:
                continue
            cfg = integ.get("config") or {}
            key = str(cfg.get("api_key") or "").strip()
            if not key:
                continue
            base = str(cfg.get("base_url") or (pmeta or {}).get("base_url") or "").rstrip("/")
            if not base:
                continue
            # `auth` travels with the key, from the same entry that says where to send it. The
            # call site then has one thing to hold and no reason to ask which provider this is.
            out[pname] = {"api_key": key, "base_url": base,
                          "auth": (pmeta or {}).get("auth")}
            # The one place the key is resolved is the one place that can say what must never be
            # relayed back. Every provider sentence this process produces is scrubbed of it —
            # a 401 quotes the key it rejected, and that sentence reaches an agent, a vertex and
            # a browser.
            media_plane.remember_secret(key)
            break
    return out


class _MediaNoModel(Exception):
    """No candidate could serve this request. Carries the refusal the agent is shown and the
    attempts that led to it.

    Usually nothing was generated and nothing was charged. Not always: a candidate that answers
    200 with nothing in it has billed, and a request may reach its billable ceiling before any
    candidate delivers. The refusal says which of the two happened — see `_media_billed_out` —
    because "nothing was charged" is the one sentence an agent must never be told wrongly.
    """

    def __init__(self, text: str, attempts: list[dict], billed_usd: float = 0.0):
        super().__init__(text)
        self.text, self.attempts, self.billed_usd = text, attempts, billed_usd


def _media_doc(r: httpx.Response, body: bytes):
    """One provider response, classified before it is read — the document, or the media itself.

    The classification is `media_plane.response_doc`, beside the readers that consume it, because
    "what did the provider send" and "what does it mean" are one question asked twice otherwise.
    """
    return media_plane.response_doc(r.headers.get("content-type", ""), body)


# How many times ONE REQUEST may fall down its chain after a candidate has already billed. One.
# Every advance is another full-price render, so a second one is the agent's decision, made with
# the first one's cost in front of it.
#
# ONE BUDGET, TWO WALKS. A request can fall down the chain in two places — at SUBMIT, when a
# candidate answers 200 with nothing in it, and later at POLL, when a render that billed comes
# back failed — and they are the same event to whoever is paying. What the submit walk spent is
# therefore written onto the job (`advances`), which is the only thing that outlives the tool call
# and the only place the poll walk can read it from.
_MEDIA_MAX_ADVANCES = 1

# How many outbound submits ONE REQUEST may make AT ALL, whatever the provider answers to any of
# them — where a request is one tool call, one browser poll or one sweep pass. Separate from the
# budget above because it is a different fact: that one is about money and stops at the second
# render bought; this one is about sockets. A candidate that answers 4xx costs nothing and IS
# walked past — deliberately, because leaving a broken model in the chain
# is what let the owner's preferred one start working again on its own — but "costs nothing" is
# not "free": each submit carries the provider key out of this process, and a chain eleven long
# meant one tool call could make eleven of them. Four is the measured outage (one broken model at
# rank 1) with room, and a long way short of any chain in the catalog.
#
# WHERE IT IS CLAIMED, and why that is the whole of the fix: at `_media_call`, which is the only
# place in this process that opens a socket to a provider. It used to be claimed at the top of
# `_media_chain`'s loop, which counted the WALK — so `_media_job_resubmit`, which opens its own
# submit and which a synchronous render reaches inside the very same tool call, made a fifth one
# that no ceiling saw. Counting walks is what let four rounds of this bug each be "fixed" in the
# branch beside the one that overspent. A ceiling written in submits has to be counted in submits.
#
# IT BOUNDS THE POLL ENTRIES TOO, which took a sixth round to become true. It used to bound a
# SUBMIT WALK and nothing else: a poll pass built one budget per JOB out of `for_job`, which seeds
# `billed` off the job and left `submits` at zero, so `claim()` could not refuse anything and what
# actually stopped the walk was the `advances` check one branch over — a guard beside the socket,
# which is the construction this whole series exists to delete. Measured: one check_jobs over six
# failing jobs made six outbound submits, one _media_sweep() over five made five, and setting this
# number to 1 changed neither count.
#
# NOT AN OVERSPEND, and the fix is not sold as one. Per job the money rule held throughout
# (`advances` caps each job at `_MEDIA_MAX_ADVANCES + 1` renders) and the total across sweeps was
# unchanged: it was a BURST — six full-price renders started by what the agent issued as a read —
# and a ceiling that claims to bound a request while counting only a walk is how four rounds of
# this survived. So `submits` now belongs to the REQUEST and `billed` to the job; see the class.
#
# WHAT THIS COSTS, so the next reader does not have to find out the hard way: a free refusal is
# never quarantined, so every call starts the walk at rank 1 again. If the FIRST FOUR candidates
# all answer 4xx, no call ever reaches the fifth and the capability is refused until one of the
# four recovers. That is judged acceptable because the chains interleave providers on purpose —
# the first four of text_to_image span three of them — so four consecutive refusals means the
# relay itself is down, and the fifth candidate would not have answered either. If a chain ever
# stacks one provider's models at the top, this number and that fact have to be looked at
# together.
#
# AND ON THE POLL ENTRIES IT COSTS AN ADVANCE, not a delay — measured, because "the next pass will
# pick it up" is the first thing a reader assumes and it is not what happens. A pass that refuses
# a job's advance FAILS that job then and there, exactly as `_media_job_resubmit` has always done
# when the submit walk runs out: five failing jobs in one sweep means four get their second
# candidate and the fifth ends `failed` with the upstream error, for the agent to resubmit if it
# still wants the shot. Softening that by leaving the job running so a later pass retries is the
# tempting change and it is a re-buy: the render is banked and the model stood down BEFORE the
# submit is refused, so a second visit banks it twice (test_v42c pins this). The ceiling costs a
# retry, never a second charge.
_MEDIA_MAX_SUBMITS = 4


class _MediaBudget:
    """What one request may buy and what it may try, and the ONE PLACE that decides it.

    THE COUNT LIVES WHERE THE SOCKET IS, NOT WHERE THE EXITS ARE. This same overspend was closed
    four times and found four times, each time in the branch beside the one that was patched: the
    poll walk was capped and the submit walk was not; then `except MediaEmpty` was capped and
    `except MediaError` was not; then the gate moved to the submit walk's loop and
    `_media_job_resubmit` went on opening its own socket beside it. Every one of those fixes
    counted a WALK. What costs money is a SUBMIT, so a submit is what is counted, and it is
    claimed in `_media_call` — before the request goes out, in the one function that can send one.
    The ceiling therefore holds for an answer nobody has imagined, for an exception type invented
    next year, and for a caller that has never heard of this class.

    A CLAIM IS BILLABLE UNTIL THE ANSWER SAYS OTHERWISE. `claim` counts the submit against the
    money budget immediately and `free` gives it back only when the answer says nothing ran, which
    is the only evidence there is. That ordering is also what makes the ceiling hold when an agent
    fires four generate calls at once: the claim and the check happen with no await between them,
    so two concurrent walks cannot both see the last slot.

    TWO LIFETIMES, ONE OBJECT, BECAUSE THEY ARE TWO DIFFERENT FACTS. `billed` is money and
    belongs to a JOB — it is seeded from what that job already bought and carries across the
    minutes between the tool call and the poll. `submits` is sockets and belongs to a REQUEST —
    nothing about one job says how many sockets the pass it is being polled in has opened. Keeping
    them in one object with one lifetime is what made the ceiling decorative on the poll path:
    `for_job` handed out a fresh count per job, so a request that polled six jobs made six
    submits and `_MEDIA_MAX_SUBMITS` never said a word.
    """

    __slots__ = ("submits", "billed", "sharers", "walk")

    def __init__(self, walk: "_MediaBudget | None" = None) -> None:
        self.submits = 0
        self.billed = 0
        self.sharers = 0
        # WHOSE SUBMIT COUNT THIS SPENDS. Itself, for the budget a request opens; the request's,
        # for the per-job views `for_job` hands out below. A budget built with no argument starts
        # a NEW REQUEST'S COUNT, which is why only the three entry points may build one.
        self.walk = walk if walk is not None else self

    def for_job(self, job: dict) -> "_MediaBudget":
        """The money ceiling THIS JOB carries, spending THIS REQUEST'S submit count.

        A poll happens minutes after the tool call that started the job, in some other request —
        usually the sweeper's, with no agent anywhere near it — so that call's budget is long
        gone. What survives is on the job: `advances` is what the submit walk and any earlier poll
        already bought, and seeding it back here is what keeps the two walks sharing ONE money
        ceiling instead of each keeping a private count of the same spend.

        THE SUBMIT COUNT DOES NOT RESTART, and that is the whole of round 6. This used to be a
        classmethod returning a budget with `submits` at zero, so a pass that polled N jobs made N
        submits against a ceiling of four and moving the ceiling moved nothing. It is an instance
        method now for exactly that reason: there is no way to ask for a job's money ceiling
        without already holding the request's socket count.
        """
        b = _MediaBudget(self.walk)
        b.billed = int(job.get("advances") or 0)
        return b

    def claim(self) -> str:
        """"" if another outbound submit is allowed, else the clause saying why it is not."""
        if self.billed > _MEDIA_MAX_ADVANCES:
            return "billed"
        if self.walk.submits >= _MEDIA_MAX_SUBMITS:
            return "tried"
        self.walk.submits += 1
        self.billed += 1
        return ""

    def free(self) -> None:
        """The answer said nothing ran, so the claim goes back."""
        self.billed -= 1


class _MediaSpent(media_plane.MediaError):
    """The budget refused another outbound submit. Carries WHICH ceiling said no.

    A MediaError deliberately. The two callers that know about the budget catch this first and say
    something better; any caller that does not — including one written next year by somebody who
    read none of this — still turns it into a sentence the agent can read rather than an HTTP 500.
    """

    def __init__(self, stopped: str):
        super().__init__(
            "this request has already bought every render one request may buy"
            if stopped == "billed" else
            f"this request has made the {_MEDIA_MAX_SUBMITS} attempts it is allowed")
        self.stopped = stopped


def _media_unusable(r: httpx.Response | None, e: Exception) -> media_plane.MediaError:
    """Whatever a provider call raised that was not already a MediaError, said in the media
    plane's own terms.

    ONE QUESTION DECIDES IT, and it is the same one `_read_submit` asks: DID THE PROVIDER ANSWER?
    No response at all is a refusal and nothing ran. A status of 400 or worse is a refusal too.
    A 200 whose body this could not read is the expensive one — the provider answered, so it
    billed — and it gets exactly what a 200 with no media in it gets: banked, and the model stood
    down. That last case is what a relay renaming a field looks like from in here, which is the
    single most common thing that happens to this code.
    """
    if r is None:
        return media_plane.MediaRefused(f"the provider did not answer ({type(e).__name__})")
    if r.status_code >= 400:
        return media_plane.MediaRefused(media_plane.provider_message(None, r.status_code))
    return media_plane.MediaEmpty(f"the provider answered 200 with a body this could not read "
                                  f"({type(e).__name__}) — it billed and returned nothing usable")


async def _media_call(cand: dict, prov: dict, params: dict,
                      budget: _MediaBudget) -> tuple[str, object, dict]:
    """One provider call: (task_id, payload, response doc). The ONLY blocking provider call, the
    ONE place an outbound submit is made, and therefore the one place the budget is claimed.

    A shape that hands back a task id returns in about a second. A synchronous shape renders
    inside this call, which is why the timeout is the candidate's own measured latency with room
    rather than one number for a four-second model and a ninety-second one.

    THE CLAIM IS HERE BECAUSE THE SOCKET IS HERE. Every earlier cap belonged to a walk, and the
    submit that overspent came from beside it — from `_media_job_resubmit`, which a synchronous
    render reaches INSIDE THE SAME TOOL CALL. Anything that submits comes through here, so
    anything that submits is counted, whether or not whoever wrote it knew there was a count.

    THE ANSWER IS INTERPRETED INSIDE THE `try`, BODY AND ALL. `read_submit` used to be called one
    line below it: a renamed provider field then raised AttributeError, which is outside the
    MediaError tree, so it went past every handler above and left the route as an HTTP 500 —
    nothing banked, nothing stood down, no sentence for the agent, and a render paid for. What
    each kind of failure MEANS is `_media_unusable`'s job.
    """
    sub = media_plane.build_submit(cand, prov["base_url"], params)
    # SIGNED IN THIS PROVIDER'S OWN STYLE, and the style came off the provider entry beside its
    # base url — see media_plane.auth_of. There is no branch here on WHICH provider this is, and
    # that is deliberate: this function is the one place every outbound submit passes through, and
    # everything it has learnt to special-case has cost a round of the budget bug. It builds one
    # header out of one dict; a provider with a third auth style is a catalog edit.
    # The shape's own headers go UNDER the credential and the content type, never over them: a
    # catalog entry names a model and a protocol version, and must not be able to name an
    # `authorization` that would send the key somewhere this did not decide.
    headers = {**sub.headers, **media_plane.auth_headers(prov),
               "content-type": "application/json"}
    cl = _media_client()
    stopped = budget.claim()
    if stopped:
        raise _MediaSpent(stopped)
    r = None
    try:
        if sub.stream:
            # gpt-audio refuses without stream:true and then delivers audio in deltas.
            chunks: list[str] = []
            async with cl.stream(sub.method, sub.url, json=sub.body, headers=headers,
                                 timeout=sub.timeout) as r:
                if r.status_code >= 400:
                    raise media_plane.MediaRefused(
                        media_plane.provider_message(_media_doc(r, await r.aread()),
                                                     r.status_code))
                async for line in r.aiter_lines():
                    chunks.append(line)
            return "", media_plane.read_stream_audio(cand, chunks), {}
        r = await cl.request(sub.method, sub.url, json=sub.body, headers=headers,
                             timeout=sub.timeout)
        doc = _media_doc(r, r.content)
        task_id, payload = media_plane.read_submit(cand, r.status_code, doc)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — a refusal, a dead socket, or a body we cannot read
        err = e if isinstance(e, media_plane.MediaError) else _media_unusable(r, e)
        if not isinstance(err, media_plane.MediaEmpty):
            # Nothing ran, so the claim goes back and the model stays in the chain — retrying it
            # is free, and that is precisely what lets a model the relay has broken sit at rank 1
            # and start working the day the mapping is fixed, with no code change and no cost.
            budget.free()
        elif err is not e:
            # A 200 this code could not interpret is an OPERATIONAL event, not just a failed call:
            # it is what a relay renaming a field looks like from in here, and it is now costing
            # money one render at a time. The model is named so the operator can act on it; the
            # body is not logged, because a provider document is not ours to write down.
            print(f"[media] {cand.get('model')}: a 200 this could not read "
                  f"({type(e).__name__})", flush=True)
        if err is not e:
            raise err from e
        raise
    return task_id, payload, doc if isinstance(doc, dict) else {}


# One budget per agent tool call — SHARED WITH EVERY CALL THAT OVERLAPS IT ON THE SAME SESSION.
_media_budgets: dict[str, _MediaBudget] = {}


@contextlib.asynccontextmanager
async def _media_budget_for(sid: str):
    """The budget this tool call spends out of — a generation, or the check_jobs that polls it.

    Per request rather than per session, because a session lives for hours and one budget for all
    of it would refuse an agent that has been working correctly since. But an agent parallelises:
    four generate_image calls issued in ONE turn each opened a private budget and bought the whole
    chain between them. The rule this budget exists to enforce is that a second render is the
    agent's DECISION, made with the first one's cost in front of it — and that is not true of a
    call which was already in flight when the first one billed. So overlapping calls share one
    budget, and the first call to arrive after they have all answered opens a fresh one: "the
    agent has seen an answer" is exactly the boundary, and in-flight is exactly how to spell it.
    """
    b = _media_budgets.get(sid)
    if b is None:
        b = _media_budgets[sid] = _MediaBudget()
    b.sharers += 1
    try:
        yield b
    finally:
        b.sharers -= 1
        if b.sharers <= 0:
            _media_budgets.pop(sid, None)


def _media_billed_out(err: str, billed: int) -> str:
    """What an agent is told when its request has spent the whole billable budget. ONE sentence
    for both walks, because a second one would drift and only one of them would be true."""
    what = "1 model has" if billed == 1 else f"{billed} models have"
    return (f"{err} — {what} now billed for this one request and nothing further was bought. "
            f"Ask again if you want another attempt.")


def _media_walk_over(cap: str, reasons: list[str], billed: int, stopped: str,
                     turn_billed: int) -> str:
    """What the agent is told when a walk ended with no media. One builder for every way it can
    end, so "nothing was charged" — the one sentence an agent must never be told wrongly —
    survives on exactly the paths where it is true, and so does the advice that follows it.
    """
    if billed:
        return _media_billed_out("; ".join(reasons), billed)
    if stopped == "billed":
        # This call bought nothing and a call issued ALONGSIDE it spent the shared budget. Its own
        # sentence, because the two others would each be wrong here: `refusal` would tell the agent
        # to go and ask somebody to connect a provider, and the billed-out sentence would charge
        # this call for renders it did not make.
        return (f"Another generation issued in the same turn has already bought the "
                f"{turn_billed} renders one turn is allowed and none of them delivered. Nothing "
                f"was generated here and nothing was charged for it. Ask again — one at a time — "
                f"if you want another attempt.")
    if stopped == "tried":
        return (f"{'; '.join(reasons)} — this request has made the {_MEDIA_MAX_SUBMITS} attempts "
                f"it is allowed and none of them produced anything. Nothing was generated and "
                f"nothing was charged. Ask again if you want the remaining models tried.")
    return media_plane.refusal(cap, reasons)


async def _media_chain(cap: str, params: dict, providers: dict,
                       budget: _MediaBudget) -> tuple[dict, str, object, dict, dict]:
    """Walk the capability's chain until one candidate actually runs. Returns the tally of what
    the walk cost along with what it produced, because the job that comes out of it has to carry
    the spend forward.

    THE WALK DOES NOT COUNT ITSELF. Whether another submit may be made is asked inside
    `_media_call`, because that is where the socket is — a gate here would bound this loop and
    nothing else, which is exactly how the last four rounds of this bug each survived their own
    fix. This loop only says what the walk is TOLD: `_MediaSpent` means the request has spent
    what a request may spend, and it ends the walk with the same refusal a chain that ran out of
    candidates gets.

    What the answer WAS decides only one thing here: a 200 that gave nothing billed, so it is
    written down and the model is stood down. A status code billed nothing, so the model stays in
    the chain — retrying it is free, and that is precisely what lets `dreamina-seedance-2-5-hc`
    sit permanently at rank 1 and start working the day the relay's mapping is fixed, with no code
    change and no cost. The money that goes with either answer is the budget's, in `_media_call`.
    """
    tally: dict = {"attempts": [], "billed_usd": 0.0}
    tried: set[str] = set()
    while True:
        cand, skipped = media_plane.resolve(cap, params, set(providers), _media_quarantine,
                                            exclude=tried)
        if not cand:
            stopped = "chain"
            break
        model = str(cand.get("model") or "")
        tried.add(model)
        try:
            task_id, payload, doc = await _media_call(cand, providers[cand["provider"]], params,
                                                      budget)
        except _MediaSpent as e:
            stopped = e.stopped
            break
        except media_plane.MediaError as e:
            if isinstance(e, media_plane.MediaEmpty):
                _media_billed(tally, model, media_plane.estimated_usd(cand) or 0.0, str(e))
            else:
                tally["attempts"].append({"model": model, "error": str(e)})
            continue
        return cand, task_id, payload, doc, tally
    reasons = [f"{a['model']} — {a['error']}" for a in tally["attempts"]] + skipped
    billed = sum(1 for a in tally["attempts"] if a.get("billed"))
    raise _MediaNoModel(_media_walk_over(cap, reasons, billed, stopped, budget.billed),
                        tally["attempts"], float(tally["billed_usd"]))


# ── the job store ─────────────────────────────────────────────────────────────────────────────
# One vertex per job. A vertex and not an in-memory dict because a job outlives the turn, the tab
# and a gateway restart — a clip takes about four minutes and nobody watches it arrive.
#
# NOTE FOR A HOSTED DEPLOYMENT: the graph is closed-world on labels, so `MediaJob` has to be
# registered there exactly as `HarnessSession` and `Harness` are, or every upsert silently no-ops.
_MEDIA_JOB_LABEL = "MediaJob"
_MEDIA_JOB_NUM = ("bytes", "width", "height", "next_poll_at", "poll_backoff_s", "created_at",
                  "updated_at", "shots", "advances")
_MEDIA_JOB_FLOAT = ("seconds", "usd", "quota", "planned_seconds", "billed_usd")


def _media_job_props(job: dict) -> dict:
    """A job as flat string props. The graph stores strings; keeping the conversion in one place
    is what stops a job that reads back as the string "None".

    `attempts` and `params` are stored ONCE, as their _json siblings. Writing both would be two
    copies of the same fact, and the day they disagree is the day a job's history is a coin toss.
    """
    out = {}
    for k, v in job.items():
        if k in ("id", "attempts", "params"):
            continue
        out[k] = json.dumps(v) if isinstance(v, (dict, list)) else ("" if v is None else str(v))
    return out


def _media_job_out(v: dict | None) -> dict | None:
    if not v:
        return None
    job = {"id": str(v.get("id") or "")}
    for k, val in v.items():
        if k in ("id", "pk", "label"):
            continue
        job[k] = val
    for k in _MEDIA_JOB_NUM:
        job[k] = int(float(job.get(k) or 0) or 0)
    for k in _MEDIA_JOB_FLOAT:
        job[k] = float(job.get(k) or 0) or 0.0
    for k, empty in (("attempts", []), ("params", {})):
        try:
            job[k] = json.loads(job.get(k + "_json") or json.dumps(empty))
        except Exception:  # noqa: BLE001
            job[k] = empty
    return job


async def _media_job_save(job: dict) -> None:
    job["updated_at"] = int(time.time() * 1000)
    await _vg_upsert(_MEDIA_JOB_LABEL, job["id"], _media_job_props(job))


async def _media_job_get(jid: str) -> dict | None:
    if not jid or not jid.startswith("mjob_"):
        return None
    return _media_job_out(await BACKING.graph.get(jid, label=_MEDIA_JOB_LABEL))


async def _media_jobs_of(sid: str) -> list[dict]:
    rows = await BACKING.graph.find(_MEDIA_JOB_LABEL, {"session": sid})
    return [j for j in (_media_job_out(r) for r in rows) if j and j.get("deleted") != "1"]


async def _media_spend(sid: str) -> float:
    """What this session has actually cost: the summed MEASURED usd of everything that billed.

    A render that billed and then failed is money spent. Summing only the SUCCEEDED jobs is how a
    session that burned six full-price renders read as $0.00 and the budget cap never fired —
    `billed_usd` is what each failed candidate cost, banked as the chain moved off it.

    Measured only. A session whose jobs reported no cost sums to nothing and the caller shows
    nothing — never "$0.00", which reads as free rather than as unknown. Most candidates carry no
    measured price, so this is a floor on what was spent and never an estimate of it.
    """
    jobs = await _media_jobs_of(sid)
    return round(sum(float(j.get("usd") or 0.0) for j in jobs if j.get("status") == "succeeded")
                 + sum(float(j.get("billed_usd") or 0.0) for j in jobs), 4)


# ── the media store ───────────────────────────────────────────────────────────────────────────
def _media_blob(sid: str, med: str, ext: str) -> str:
    return f"media/{sid}/{med}.{ext}"


def _media_url(hid: str, eid: str, sid: str, med: str) -> str:
    """Where the app fetches these bytes. A PATH, not an absolute URL: an absolute one breaks the
    moment the deployment moves, which is the same lesson `_harness_plugins` already encodes by
    re-deriving hosted server addresses at turn time instead of trusting the stored one."""
    return f"/v1/harnesses/{hid}/servers/{eid}/sessions/{sid}/media/{med}"


async def _media_store(sid: str, kind: str, data: bytes, meta: dict) -> dict:
    """Verify these bytes really are that media, then keep our own copy.

    THE PROVIDER URL IS NEVER STORED. Every one of them is signed or short-lived — happyhorse's
    lasts a day — so a scene holding one is a scene that stops working tomorrow.
    """
    info = media_plane.verify(kind, data)
    med = "med_" + uuid.uuid4().hex[:16]
    ok = await _blob_put(_media_blob(sid, med, info["ext"]), data, kb=BLOB_KB)
    if not ok:
        raise media_plane.MediaError("the generated file could not be stored")
    rec = {"media_id": med, "kind": kind, "ext": info["ext"], "mime": info["mime"],
           "bytes": info["bytes"], "width": info.get("width") or 0,
           "height": info.get("height") or 0, "seconds": info.get("seconds") or 0.0,
           "created_at": int(time.time() * 1000), **meta}
    await _blob_put(_media_blob(sid, med, info["ext"]) + ".meta",
                    json.dumps(rec).encode(), kb=BLOB_KB)
    return rec


async def _media_meta(sid: str, med: str) -> dict | None:
    """The record beside the bytes, found without knowing the extension."""
    listing = await _blob_list_all(f"media/{sid}/{med}.", kb=BLOB_KB)
    for it in listing:
        fid = str(it.get("file_id") or "")
        if fid.endswith(".meta"):
            raw = await _blob_get(fid, kb=BLOB_KB)
            if raw:
                try:
                    return json.loads(raw)
                except Exception:  # noqa: BLE001
                    return None
    return None


async def _provider_url_check(url: str) -> str | None:
    """Whether this server may fetch an address THE PROVIDER named. The rule _ssrf_check applies
    to a customer's MCP endpoint, minus its self-hosted exemption.

    That exemption exists because a local MCP server on 127.0.0.1 is one the OPERATOR typed on a
    machine they already own. A result_url is chosen by a remote relay, so on a self-hosted box
    the operator's own network is exactly what a hostile relay would reach for — the reasoning
    that makes the exemption right there makes it wrong here.

    Nor is there an exemption for a name that did not resolve. This is the one caller whose
    address a REMOTE PARTY chose, and it is polled again and again — so "our lookup failed, allow
    it" is not one gamble, it is a fresh roll on every poll until one of them lands.
    """
    from urllib.parse import urlparse
    refused = "the finished file was offered from an address this will not fetch"
    try:
        u = urlparse(url)
    except Exception:  # noqa: BLE001
        return refused
    if u.scheme not in ("http", "https") or not u.hostname:
        return refused
    bad = await _internal_target(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    if not bad:
        return None
    # The host, in the log, where an operator can act on it — and only the host: a result_url
    # carries a signature, and that is a credential like any other.
    print(f"[media] refused a provider file address at {u.hostname}: {bad}", flush=True)
    return refused


async def _media_fetch(url: str) -> bytes:
    """Pull a finished render off the provider, capped. Streamed rather than read whole, so a
    provider that answers with a gigabyte is a refused job and not an out-of-memory.

    The response's content-type is deliberately NOT returned: what the bytes are is decided by the
    bytes (media_plane.verify), and a header is a claim.

    WHERE it is pulled from is a claim too, and one the provider makes: a relay that answers a
    poll with `result_url: http://169.254.169.254/…` had this server fetching cloud metadata and
    storing the answer. No credential rides along and the body is never echoed, but a status and
    a size still leak through `attempts`, and that is a probe of our own network either way.
    """
    refused = await _provider_url_check(url)
    if refused:
        raise media_plane.MediaEmpty(refused)
    buf = bytearray()
    try:
        async with _media_client().stream("GET", url, timeout=300) as r:
            if r.status_code >= 400:
                raise media_plane.MediaEmpty(f"the finished file could not be fetched "
                                             f"(HTTP {r.status_code})")
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > media_plane.MAX_BYTES:
                    raise media_plane.MediaEmpty(
                        f"the provider returned more than {media_plane.MAX_BYTES} bytes")
    except media_plane.MediaError:
        raise
    except Exception as e:  # noqa: BLE001
        # EVERY WAY THIS FAILS IS A MediaError, which is this function's contract and not a
        # courtesy. Its three callers all handle MediaError and none of them handles anything
        # else, so an httpx.ConnectError — a CDN host that resolves and then refuses, resets or
        # times out the socket — escaped the poll BEFORE the backoff was bumped and before the age
        # check, and the blanket `except Exception` in the sweeper, in check_jobs and in the
        # browser's jobs route each swallowed it in silence. The job stayed `running` for ever:
        # one provider poll CARRYING THE KEY plus one CDN fetch every ten seconds, presenting to
        # the person as a placeholder that never resolves and never errors. The same rule
        # `_media_call` already holds for the submit — a network failure is a failure with a
        # sentence, not a crash.
        raise media_plane.MediaEmpty(
            f"the finished file could not be fetched ({type(e).__name__})") from e
    return bytes(buf)


# ── the scene ─────────────────────────────────────────────────────────────────────────────────
def _media_scene_key(sid: str) -> str:
    return f"sessions/{sid}/{_MEDIA_SCENE_FILE}"


async def _media_scene_read(sid: str) -> dict:
    raw = await _blob_get(_media_scene_key(sid), kb=BLOB_KB)
    if not raw:
        return media_plane.new_scene()
    try:
        return media_plane.sanitize_scene(json.loads(raw))
    except Exception:  # noqa: BLE001
        return media_plane.new_scene()


async def _media_scene_write(sid: str, scene: dict) -> int:
    """Store the scene and bump its revision. The revision lives IN the document, so there is one
    thing to read and one thing to write and they cannot disagree."""
    scene = media_plane.sanitize_scene(scene)
    meta = scene.get("meta") or {}
    rev = int(float(meta.get("rev") or 0)) + 1
    scene["meta"] = {**meta, "rev": rev}
    (scene.get("timeline") or {})["updatedAt"] = int(time.time() * 1000)
    await _blob_put(_media_scene_key(sid), json.dumps(scene).encode(), kb=BLOB_KB)
    _media_project_due.add(sid)
    await _media_project(sid, scene)
    return rev


async def _media_project(sid: str, scene: dict | None = None) -> None:
    """Write the scene into the session's workspace, so it is an ordinary artifact.

    WRITE-ONLY, store → workspace. Nothing ever reads it back as authority. Self-hosted it is
    live; hosted it is up to one turn stale, because a live sandbox's tarball is replaced wholesale
    at checkpoint — which is the same staleness the console already shows for every other kit
    mid-turn. Best-effort: a projection that fails must never fail the generation it describes.
    """
    try:
        doc = scene if scene is not None else await _media_scene_read(sid)
        if not (doc.get("elements") or doc.get("timeline", {}).get("shots")):
            _media_project_due.discard(sid)
            return                       # nothing to project yet; don't create an empty artifact
        ok = await BACKING.workspace.write(sid, _MEDIA_SCENE_FILE,
                                           json.dumps(doc, indent=2).encode())
        if ok:
            _media_project_due.discard(sid)
        else:
            # Hosted, mid-turn, this is EXPECTED — the live sandbox owns the tarball and its own
            # checkpoint will replace whatever we wrote. Leaving it queued is what makes the
            # re-projection after `_checkpoint` land, so the artifact is at most one turn stale.
            print(f"[media] projection of {sid} deferred to the next checkpoint", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[media] projection of {sid} deferred: {type(e).__name__}", flush=True)


async def _media_scene_touch(sid: str, mutate) -> tuple[int, object]:
    """Read-modify-write one scene under its lock. Every canvas tool comes through here, so the
    agent's edits and a landing render cannot interleave into a broken document."""
    async with _media_scene_lock(sid):
        scene = await _media_scene_read(sid)
        out = mutate(scene)
        rev = await _media_scene_write(sid, scene)
        return rev, out


# ── running a job ─────────────────────────────────────────────────────────────────────────────
async def _media_job_land(job: dict, data: bytes, transcript: str = "") -> dict:
    """A finished render becomes our own file, and the element that was holding its place becomes
    the clip. Verification first: a body that is not media is a failure, not a success."""
    kind = _MEDIA_KIND.get(str(job.get("capability") or ""), "image")
    rec = await _media_store(str(job["session"]), kind, data,
                             {"model": job.get("model") or "", "capability": job.get("capability"),
                              "job_id": job["id"], "prompt": (job.get("params") or {}).get("prompt") or ""})
    job.update({"status": "succeeded", "media_id": rec["media_id"], "bytes": rec["bytes"],
                "width": rec["width"], "height": rec["height"], "seconds": rec["seconds"],
                "error": ""})
    if transcript:
        job["spoken_text"] = transcript
    await _media_job_save(job)
    await _media_element_ready(job, rec)
    return job


async def _media_element_ready(job: dict, rec: dict) -> None:
    """Swap the placeholder for the real thing, server-side.

    Server-side is the point: the scene is mutated in the store, not in a browser reacting to a
    stream, so a clip cannot go missing because nobody had the canvas tab open when it landed.
    """
    eid = str(job.get("element_id") or "")
    if not eid:
        return
    sid = str(job["session"])

    def mutate(scene: dict):
        for el in scene.get("elements") or []:
            if el.get("id") != eid:
                continue
            m = media_plane.media_of(el)
            m.update({"status": "ready", "mediaId": rec["media_id"], "model": job.get("model"),
                      "seconds": rec.get("seconds") or None, "width": rec.get("width") or None,
                      "height": rec.get("height") or None})
            if el.get("type") == "image":
                # A NEW fileId, equal to the new media id. Excalidraw's addFiles will not update a
                # fileId that already exists, so reusing one leaves the placeholder on screen
                # forever.
                el["fileId"] = rec["media_id"]
                el["status"] = "saved"
                scene.setdefault("files", {})[rec["media_id"]] = media_plane.file_entry(
                    rec["media_id"], rec["mime"],
                    _media_url(str(job.get("harness") or ""), str(job.get("entry") or "mcp.media"),
                               sid, rec["media_id"]))
            else:
                el["link"] = _media_url(str(job.get("harness") or ""),
                                        str(job.get("entry") or "mcp.media"), sid,
                                        rec["media_id"])
            return None
        return None

    await _media_scene_touch(sid, mutate)


async def _media_element_failed(job: dict) -> None:
    eid = str(job.get("element_id") or "")
    if not eid:
        return

    def mutate(scene: dict):
        for el in scene.get("elements") or []:
            if el.get("id") == eid:
                media_plane.media_of(el).update({"status": "failed"})
        return None

    await _media_scene_touch(str(job["session"]), mutate)


async def _media_job_live(job: dict) -> bool:
    """May this job still spend? Asked before every poll it would pay for.

    A running job IS money: each poll carries this deployment's provider key, and a poll that
    reports SUCCESS downloads a file and stores it. So the question is not "does this job exist"
    but "is the server that started it still connected and still switched on".

    Asked here rather than in the sweeper because check_jobs and the app's jobs route advance jobs
    too, and `check_enabled` only ever refused a TURN — a media server the owner switched off went
    on polling and paying for everything earlier turns had started. Switching it back on resumes
    the same job, which is the difference between this and deleting the agent (that buries them).
    """
    hid = str(job.get("harness") or "")
    v = await _vertex_get(hid) if hid else None
    if not v or str(v.get("deleted")) in ("1", "true", "True"):
        return False
    try:
        await _hosted_resolve(_MEDIA_SERVER, hid, str(v.get("org") or ""), _mcp_list(v),
                              entry_id=str(job.get("entry") or ""), check_enabled=True)
    except HTTPException:
        return False
    return True


async def _media_job_advance(job: dict, budget: _MediaBudget) -> dict:
    """Move one job forward. THE one function that does — check_jobs, the app's poll route and the
    sweeper all call it, so a job cannot mean one thing to a browser and another to an agent.

    THE BUDGET IS THE PASS'S, not this job's. A poll that answers FAILURE advances the chain, and
    advancing it opens a socket: every job this function is called for in one request therefore
    counts against ONE `_MEDIA_MAX_SUBMITS`. It used to make its own per job, which is why six
    failing jobs meant six outbound submits from a single check_jobs. `for_job` below takes the
    money ceiling off the job and leaves the socket count where it is."""
    if job.get("status") != "running" or not job.get("provider_task_id"):
        return job
    if float(job.get("next_poll_at") or 0) > time.time() * 1000:
        return job
    # Serialise from here: everything below can DOWNLOAD AND STORE, and those callers overlap.
    async with _media_job_lock(str(job.get("id") or "")):
        fresh = await _media_job_get(str(job.get("id") or "")) or job
        # Re-check under the lock. A caller that queued behind the one that landed this job must
        # return the landed answer, not fetch the same clip a second time.
        if fresh.get("status") != "running" or not fresh.get("provider_task_id"):
            return fresh
        if float(fresh.get("next_poll_at") or 0) > time.time() * 1000:
            return fresh
        try:
            # INSIDE the try, because the liveness check reads the backing store and the store is
            # a thing that blips. It answered False for "switched off" and let a RuntimeError past
            # for "could not tell" — and the caller could not tell those apart either, so the job
            # kept its old `next_poll_at`, was due immediately, and was re-read on every sweep for
            # as long as the gateway ran. Nothing spends on that path; it is graph churn and a
            # placeholder that never resolves, which is why it sat there.
            if not await _media_job_live(fresh):
                return fresh
            return await _media_job_poll(fresh, budget)
        except Exception as e:  # noqa: BLE001
            # THE INVARIANT OF THIS FUNCTION, and the reason it is stated once here rather than
            # guarded at each raise inside the poll: a job this function looked at comes out of it
            # either TERMINAL or DUE LATER — or untouched, when the answer was a definite "this
            # deployment may not spend". `_media_job_poll` bumps the backoff on every path it
            # returns by; if anything in here raised instead, nobody did — and every caller of
            # this function (the sweeper, check_jobs, the browser's jobs route) swallows the
            # exception. Whatever raised, the backoff still applies and JOB_MAX_S still ends it.
            print(f"[media] poll of {fresh.get('id')} raised {type(e).__name__}: {e}", flush=True)
            return await _media_job_stalled(fresh)


async def _media_job_poll(job: dict, budget: _MediaBudget) -> dict:
    """One poll of one job, under its lock. Split out so the locking above reads as one thought."""
    now = time.time()
    cand = _media_candidate(str(job.get("capability") or ""), str(job.get("model") or ""))
    providers = await _media_providers()
    prov = providers.get(str(job.get("provider") or ""))
    if not cand or not prov:
        job["next_poll_at"] = int((now + 60) * 1000)
        await _media_job_save(job)
        return job

    poll = media_plane.build_poll(cand, prov["base_url"], str(job["provider_task_id"]))
    try:
        # Same rule as the submit: the shape's headers go UNDER the credential, so a catalog entry
        # can name a model and a protocol version but never an `authorization`.
        r = await _media_client().request(
            poll.method, poll.url,
            headers={**poll.headers, **media_plane.auth_headers(prov)},
            json=poll.body if poll.body is not None else None,
            timeout=media_plane.POLL_TIMEOUT_S)
        status, payload, err, progress = media_plane.read_poll(cand, r.status_code,
                                                               _media_doc(r, r.content))
    except Exception:  # noqa: BLE001 — a poll that did not answer is unknown, never failed
        status, payload, err, progress = "unknown", None, "", ""

    job["progress"] = progress
    if status == "succeeded" and payload is not None:
        try:
            data = await _media_fetch(payload.url)
            return await _media_job_land(job, data)
        except media_plane.MediaError as e:
            status, err = "failed", str(e)

    if status == "failed":
        await _media_job_billable_failure(job, err, budget.for_job(job))
        return job

    # WHAT THE LAST POLL SAID, kept beside the status rather than in it. `unknown` is never a
    # state a job is IN — it is what one answer was — so recording it here lets check_jobs tell the
    # agent "ask again" without a poll that came back empty ever becoming terminal.
    job["last_poll"] = status
    return await _media_job_stalled(job, back_off=status == "unknown")


async def _media_job_stalled(job: dict, back_off: bool = True) -> dict:
    """A poll that told us nothing terminal: back the job off, or end it because it is too old.

    THE ONE PLACE a job that did not finish is put down again, so "a polled job comes out either
    terminal or due later" is a property of the poll loop and not of each way a poll can end. Its
    other caller is `_media_job_advance`, for a poll that RAISED — every caller up there swallows
    exceptions, so without this the job kept its old `next_poll_at`, was due immediately, and was
    polled again on every sweep for as long as the gateway ran.
    """
    if back_off:
        job["poll_backoff_s"] = min(60, int(job.get("poll_backoff_s") or 20) * 2)
    age_s = (time.time() * 1000 - float(job.get("created_at") or 0)) / 1000.0
    if age_s > media_plane.JOB_MAX_S:
        # THE SAME ANSWER THE OTHER EXIT GIVES ABOUT THE SAME EVENT. This job has a provider task
        # id, which means a submit came back 200 — and a 200 is the provider answering, which is
        # the only evidence there is that it billed. A poll that answers FAILURE banks that money
        # and stands the model down (`_media_job_billable_failure`); ageing out wrote `failed` and
        # nothing else, so the session read $0.00 for a render it paid for and the model that
        # never delivered was still at rank 1 for the next call — measured, three sequential
        # generate_video calls bought the same dead model three times.
        #
        # It does NOT advance the chain, and that is the one place the two exits differ on
        # purpose: this job has run out of the time a job gets, so a render started here has none
        # left to land in. It would be a second full-price render bought at the moment we decided
        # the first one was too late.
        _media_billed(job, str(job.get("model") or ""), float(job.get("usd") or 0.0),
                      "the provider never finished this render")
        job.update({"status": "failed", "error": "The provider never finished this render."})
        await _media_job_save(job)
        await _media_element_failed(job)
        return job
    job["next_poll_at"] = int((time.time() + int(job.get("poll_backoff_s") or 20)) * 1000)
    await _media_job_save(job)
    return job


def _media_candidate(cap: str, model: str) -> dict | None:
    for c in media_plane.capability(cap).get("candidates") or []:
        if isinstance(c, dict) and str(c.get("model") or "") == model:
            return c
    return None


def _media_params_stored(params: dict) -> dict:
    """What of a job's parameters is written down: everything except the image bytes."""
    return {k: v for k, v in params.items() if k not in ("image", "image_mime")}


async def _media_land_payload(job: dict, payload) -> bool:
    """Turn a payload that is already in hand into our own file. True when it landed.

    The ONE place a synchronous result lands, shared by the first submit and by a chain that
    advanced — so "the file was verified before it was stored" cannot be true of one and not the
    other. It records the reason and DECIDES NOTHING: whether a failure here advances the chain is
    a policy the caller holds, which is what keeps the advance to exactly one.
    """
    try:
        data = (payload.data if getattr(payload, "data", None)
                else await _media_fetch(payload.url))
        await _media_job_land(job, data, getattr(payload, "transcript", ""))
        return True
    except media_plane.MediaError as e:
        job["error"] = str(e)
        return False


def _media_billed(job: dict, model: str, usd: float, err: str) -> None:
    """Write down that a candidate BILLED and gave us nothing: the attempt, the stand-down, and
    the money.

    One function, because those three always go together and every place that did them by hand
    got a different subset right. The advance that a chain then makes is NOT here: whether this
    request may buy another render is the caller's decision, and keeping it there is what keeps
    the count at one per request rather than one per place that noticed.
    """
    job.setdefault("attempts", []).append({"model": model, "error": err, "billed": True})
    job["attempts_json"] = json.dumps(job["attempts"])
    _media_quarantine[model] = time.time() + media_plane.QUARANTINE_S
    # Banked BEFORE the next candidate overwrites `usd`. A render that billed and failed is money
    # the session spent, and the job ends at `failed`, so the succeeded-sum never sees it.
    job["billed_usd"] = round(float(job.get("billed_usd") or 0.0) + float(usd or 0.0), 6)


async def _media_job_billable_failure(job: dict, err: str, budget: _MediaBudget) -> bool:
    """A candidate that had already billed has failed. Record it, stand it down, count what it
    cost, and advance the chain EXACTLY ONCE PER JOB.

    Once per JOB, which is what this always said and never did: it advanced once per FAILURE, and
    there is a poll after every advance, so a CDN briefly answering 503 on an otherwise-fine render
    walked one generate_video down the entire six-model chain — six full-price renders, $1.96 of
    list price, from one tool call. The count lives on the job because the job is what outlives
    the poll that reads it.

    Shared by the poll path and by a synchronous render whose file turned out not to be a file,
    because they are the same event. `advances` may already be non-zero when this is first
    reached: the submit walk spends out of the same budget and writes what it spent onto the job.

    THE BUDGET IS PASSED IN, never made here. A synchronous render reaches this INSIDE the tool
    call that started it, and the submit it then makes is one of that call's — it is how one
    generate_image made five. The poll path is a different request and hands in the budget the
    job carries (`budget.for_job`). Either way the submit itself is claimed in
    `_media_call`; this only decides whether one is worth trying.
    """
    _media_billed(job, str(job.get("model") or ""), float(job.get("usd") or 0.0), err)
    if int(job.get("advances") or 0) < _MEDIA_MAX_ADVANCES:
        job["advances"] = int(job.get("advances") or 0) + 1
        if await _media_job_resubmit(job, budget):
            return True
    else:
        # advances + this one. NOT len(attempts): that also counts candidates that were refused
        # at submit, which cost nothing — a count of what was spent has to be a count of what
        # actually billed.
        err = _media_billed_out(err, int(job.get("advances") or 0) + 1)
    job.update({"status": "failed", "error": err or "the render failed upstream"})
    await _media_job_save(job)
    await _media_element_failed(job)
    return False


async def _media_job_resubmit(job: dict, budget: _MediaBudget) -> bool:
    """After a billable failure, try the next candidate — once. True when one took the job.

    The budget is the caller's request's, and the submit below is claimed out of it in
    `_media_call` like every other. This function opening its own socket without asking anyone is
    what made one tool call's fifth submit.
    """
    providers = await _media_providers()
    tried = {str(a.get("model") or "") for a in job.get("attempts") or []}
    tried.add(str(job.get("model") or ""))
    params = dict(job.get("params") or {})
    if params.get("from_media") and not params.get("image"):
        # Read back from OUR copy, not from the provider's expiring one — and this is also what
        # makes a chain advance work after a restart, when the job came back off a vertex.
        try:
            params["image"], params["image_mime"] = await _media_read_image(
                str(job["session"]), str(params["from_media"]))
        except media_plane.MediaError as e:
            job.setdefault("attempts", []).append({"model": "", "error": str(e)})
            job["attempts_json"] = json.dumps(job["attempts"])
            return False
    cand, _skipped = media_plane.resolve(str(job["capability"]), params, set(providers),
                                         _media_quarantine, exclude=tried)
    if not cand:
        return False
    model = str(cand.get("model") or "")
    usd = media_plane.estimated_usd(cand) or 0.0
    try:
        task_id, payload, doc = await _media_call(cand, providers[cand["provider"]], params,
                                                  budget)
    except _MediaSpent:
        # This request has spent what a request may spend. No submit was made, so there is nothing
        # to write down about a candidate — the job fails with the failure that brought us here.
        return False
    except media_plane.MediaError as e:
        # ONE BRANCH, asking the same question `_media_chain` asks, in the same words. This is the
        # place round 2 found doing this bookkeeping by hand, and a hand-written copy of a rule is
        # a copy that gets a different subset of it right: a second render that answered 200 with
        # nothing was neither banked nor stood down here, so the next request bought it again.
        if isinstance(e, media_plane.MediaEmpty):
            _media_billed(job, model, usd, str(e))
        else:
            job.setdefault("attempts", []).append({"model": model, "error": str(e)})
            job["attempts_json"] = json.dumps(job["attempts"])
        return False
    job.update({"model": model, "provider": str(cand.get("provider") or ""), "usd": usd})
    if task_id:
        job.update({"provider_task_id": task_id, "status": "running",
                    "next_poll_at": int((time.time() + 20) * 1000)})
        await _media_job_save(job)
        return True
    if payload is None:
        return False
    if await _media_land_payload(job, payload):
        return True
    _media_billed(job, model, usd, str(job.get("error") or ""))
    return False


async def _media_generate(cap: str, params: dict, hid: str, sid: str, org: str,
                          entry_id: str, budget: _MediaBudget, shot: str = "") -> dict:
    """Resolve the chain, start the work, and record a job. A refusal leaves no vertex behind when
    nothing ran — but a walk that BOUGHT renders and delivered none of them is not nothing, and
    what it spent is written down before the refusal goes back.

    `shot` is the canvas label the agent gave this render, and it is a JOB field rather than a
    provider parameter: no model is told about it, and the job is the only thing that survives the
    four minutes between the submit and the `place` call that puts the clip on the board.
    """
    providers = await _media_providers()
    try:
        cand, task_id, payload, doc, tally = await _media_chain(cap, params, providers, budget)
    except _MediaNoModel as e:
        await _media_walk_spend(cap, params, hid, sid, org, entry_id, e)
        raise
    attempts = tally["attempts"]
    now = int(time.time() * 1000)
    job = {"id": "mjob_" + uuid.uuid4().hex[:16], "org": org, "harness": hid, "session": sid,
           "entry": entry_id, "capability": cap,
           # WITHOUT the input image. A vertex property has a size cap and a base64 frame is
           # megabytes; the media id is kept instead and the bytes are re-read from our own store
           # if the chain has to advance (see _media_job_resubmit).
           "params_json": json.dumps(_media_params_stored(params)),
           "params": params, "status": "running", "shot": shot,
           "model": str(cand.get("model") or ""), "provider": str(cand.get("provider") or ""),
           "provider_task_id": task_id, "attempts_json": json.dumps(attempts),
           "attempts": attempts, "next_poll_at": now + 20_000, "poll_backoff_s": 20,
           "media_id": "", "bytes": 0, "width": 0, "height": 0, "seconds": 0.0,
           "quota": float(cand.get("quota") or 0), "usd": media_plane.estimated_usd(cand) or 0.0,
           # WHAT THE SUBMIT WALK ALREADY SPENT, carried onto the job so the poll walk reads the
           # same budget rather than opening a second one. Without this, a request that billed
           # getting here bills again on its first failed poll — the two walks are one request.
           "advances": sum(1 for a in attempts if a.get("billed")),
           "billed_usd": tally["billed_usd"],
           "element_id": "", "error": "", "created_at": now, "updated_at": now}
    inline_usd = media_plane.usage_usd(doc)
    if inline_usd is not None:
        job["usd"] = inline_usd          # a cost the provider reported itself; measured, so used
    # SAVED BEFORE THE FILE IS FETCHED, always. A synchronous shape has already billed by the time
    # we get here, so a fetch that then fails must leave a job that says so rather than no record
    # at all — an untraceable charge is worse than a visible failure.
    await _media_job_save(job)
    if task_id:
        return job
    # A synchronous shape rendered inside the submit. Reporting it as "running" would be a lie the
    # very next call exposes, so the job carries the truth and the agent's loop is unchanged.
    if not await _media_land_payload(job, payload):
        await _media_job_billable_failure(job, str(job.get("error") or ""), budget)
    return job


async def _media_walk_spend(cap: str, params: dict, hid: str, sid: str, org: str, entry_id: str,
                            e: _MediaNoModel) -> None:
    """A submit walk that bought renders and delivered nothing still leaves the money where the
    session can see it.

    Same rule the job store already states one function up — an untraceable charge is worse than a
    visible failure — applied to the one path that had no job to write it on. A generate_video
    whose candidates each answered 200 and handed back nothing bought up to the whole chain, and
    because the refusal never reached `_media_job_save`, `_media_spend` read $0.00 and the session
    budget that exists to stop a runaway never saw a cent of it.

    Nothing is written when nothing billed: a refusal for a capability nobody has connected is
    still not an event, and a failed job for it would be noise on the person's canvas.
    """
    billed = [a for a in (e.attempts or []) if a.get("billed")]
    if not billed:
        return
    now = int(time.time() * 1000)
    await _media_job_save({
        "id": "mjob_" + uuid.uuid4().hex[:16], "org": org, "harness": hid, "session": sid,
        "entry": entry_id, "capability": cap, "status": "failed", "error": e.text,
        "params_json": json.dumps(_media_params_stored(params)), "params": params,
        "model": str(billed[-1].get("model") or ""), "provider": "", "provider_task_id": "",
        "attempts_json": json.dumps(e.attempts), "attempts": e.attempts,
        "next_poll_at": 0, "poll_backoff_s": 20, "media_id": "", "bytes": 0, "width": 0,
        "height": 0, "seconds": 0.0, "quota": 0.0, "usd": 0.0,
        "advances": len(billed), "billed_usd": float(e.billed_usd or 0.0),
        "element_id": "", "created_at": now, "updated_at": now})


# ── the sweeper ───────────────────────────────────────────────────────────────────────────────
_MEDIA_SWEEP_EVERY_S = int(os.environ.get("HR_MEDIA_SWEEP_S", "10"))


async def _media_sweep() -> int:
    """Advance every job nobody is watching.

    Not an optimisation. Without it a job whose turn ended and whose tab is closed never completes,
    and its provider URL expires — happyhorse's in a day, every kling and seedream URL signed. This
    is what makes "generation outlives the session being watched" true rather than aspirational.
    """
    rows = await BACKING.graph.find(_MEDIA_JOB_LABEL, {"status": "running"})
    now_ms = time.time() * 1000
    moved = 0
    # ONE PASS IS ONE REQUEST. A poll that answers FAILURE advances the chain and that costs a
    # socket, so a sweep that finds fifty dead jobs may not fire fifty submits between two ticks
    # of a ten-second timer — the ones it refuses are simply advanced by the next pass. Per pass
    # rather than per session because the sweeper is not anybody's session: it is one job of work
    # this process does, and `_MEDIA_MAX_SUBMITS` is how much of it may leave the process at once.
    budget = _MediaBudget()
    for r in rows:
        job = _media_job_out(r)
        if not job or float(job.get("next_poll_at") or 0) > now_ms:
            continue
        try:
            before = job.get("status")
            job = await _media_job_advance(job, budget)
            moved += int(job.get("status") != before)
        except Exception as e:  # noqa: BLE001 — one bad job must not stop the sweep
            print(f"[media] sweep: {job.get('id')} {type(e).__name__}", flush=True)
    for sid in list(_media_project_due)[:20]:
        await _media_project(sid)
    return moved


@app.on_event("startup")
async def _start_media_sweep() -> None:
    async def loop() -> None:
        while True:
            try:
                run_it = True
                if control_store.enabled():
                    try:
                        run_it = await control_store.try_lock("media-sweep",
                                                              _MEDIA_SWEEP_EVERY_S - 2)
                    except Exception:  # noqa: BLE001 — store down: sweep anyway. A duplicate GET
                        run_it = True   # poll is idempotent and free, and a stalled job is not.
                if run_it:
                    await _media_sweep()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_MEDIA_SWEEP_EVERY_S)
    asyncio.create_task(loop())


# ── the agent's tools ─────────────────────────────────────────────────────────────────────────
# Thirteen. Not eighteen: there is no concatenate_audio, no select_background_music and no
# mix_audio_with_bgm, because set_timeline + export_timeline express all three — and a matcher that
# cannot report "no match" is how a silent-substitution bug ships.
_MEDIA_MCP_TOOLS = [
    {"name": "list_capabilities",
     "description": ("What can actually be made right now, which model each capability resolves "
                     "to, and roughly what a unit costs. CALL THIS FIRST, before planning "
                     "anything expensive — it is free and it is the only way to know that a model "
                     "is broken today. A capability with no model returns a plain refusal: "
                     "believe it."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},

    {"name": "generate_video",
     "description": ("Start one shot rendering. Returns a job id immediately — a clip takes about "
                     "four minutes. Submit every shot you have planned, place them all straight "
                     "away, then call check_jobs once. Never submit one clip and wait for it."),
     "inputSchema": {"type": "object", "required": ["prompt", "seconds"],
                     "additionalProperties": False,
                     "properties": {
                         "prompt": {"type": "string", "maxLength": 2000,
                                    "description": "What the shot shows. One shot, not a script."},
                         "seconds": {"type": "number", "minimum": 1, "maximum": 15,
                                     "description": ("REQUIRED. Every model bills by length and "
                                                     "one of them defaults to 15 s.")},
                         "from_image": {"type": "string",
                                        "description": ("A media id (med_…) or job id (mjob_…) to "
                                                        "start from, instead of generating from "
                                                        "text alone. An IMAGE becomes this shot's "
                                                        "first frame. A CLIP means 'carry on from "
                                                        "where that one ended' — its last frame "
                                                        "is used, which is how two shots join "
                                                        "without a visible jump. Only some models "
                                                        "can do this and the tool says which one "
                                                        "it used.")},
                         "aspect": {"enum": ["16:9", "9:16", "1:1"]},
                         "allow_watermark": {"type": "boolean", "default": False},
                         "shot": {"type": "string", "maxLength": 60,
                                  "description": ("A label, e.g. 'Shot 3'. Groups the clip with "
                                                  "its caption on the canvas.")}}}},

    {"name": "generate_image",
     "description": ("Make one still. Seconds and cents, where a clip is minutes and dollars — "
                     "generate every frame first and show them before you render anything. Use "
                     "from_image to keep a character the same across shots."),
     "inputSchema": {"type": "object", "required": ["prompt"], "additionalProperties": False,
                     "properties": {
                         "prompt": {"type": "string", "maxLength": 2000},
                         "size": {"type": "string", "pattern": "^[0-9]{3,5}x[0-9]{3,5}$",
                                  "default": "1024x1024"},
                         "from_image": {"type": "string",
                                        "description": ("A media id or job id to edit or restyle. "
                                                        "Use this to keep a character consistent "
                                                        "across shots rather than re-generating "
                                                        "them.")},
                         "shot": {"type": "string", "maxLength": 60}}}},

    {"name": "generate_speech",
     "description": ("Speak a line. The result names the model and the voice that read it — and "
                     "if the model that ran answers prompts instead of reading them, it says so "
                     "and returns what was actually said."),
     "inputSchema": {"type": "object", "required": ["text"], "additionalProperties": False,
                     "properties": {"text": {"type": "string", "maxLength": 4000},
                                    "voice": {"type": "string",
                                              "description": ("A voice name from "
                                                              "list_capabilities. Leave it out "
                                                              "and the model that runs uses its "
                                                              "own default; naming one picks the "
                                                              "model that has it.")},
                                    "shot": {"type": "string", "maxLength": 60}}}},

    {"name": "generate_music",
     "description": ("Scored music for a film. Says plainly what is missing if it cannot be made "
                     "— a speech model is not a substitute and will not be used."),
     "inputSchema": {"type": "object", "required": ["prompt"], "additionalProperties": False,
                     "properties": {"prompt": {"type": "string", "maxLength": 2000},
                                    "seconds": {"type": "number", "minimum": 1, "maximum": 300}}}},

    {"name": "check_jobs",
     "description": ("Status for jobs you started. `unknown` is NOT a failure — it is a poll that "
                     "came back empty, and it means ask again. A job that succeeded reports the "
                     "model that actually ran and what it cost."),
     "inputSchema": {"type": "object", "required": ["job_ids"], "additionalProperties": False,
                     "properties": {"job_ids": {"type": "array", "maxItems": 50,
                                                "items": {"type": "string"}}}}},

    {"name": "describe_canvas",
     "description": ("What is on the canvas: every element, where it is, whether it is ready, and "
                     "where the next thing would land. This is your ONLY read of it — never open "
                     "or edit the scene file."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},

    {"name": "place",
     "description": ("Put media, a running job or a caption on the canvas. Place a job the moment "
                     "you submit it: a placeholder appears now and becomes the clip when the "
                     "render lands, so the person watches the film arrive."),
     "inputSchema": {"type": "object", "required": ["items"], "additionalProperties": False,
                     "properties": {
                         "items": {"type": "array", "minItems": 1, "maxItems": 20,
                                   "items": {"type": "object", "additionalProperties": False,
                                             "properties": {
                                                 "job_id": {"type": "string"},
                                                 "media_id": {"type": "string"},
                                                 "text": {"type": "string", "maxLength": 280},
                                                 "x": {"type": "number"}, "y": {"type": "number"},
                                                 "w": {"type": "number"}, "h": {"type": "number"},
                                                 "caption": {"type": "string", "maxLength": 280},
                                                 "shot": {"type": "string", "maxLength": 60}}}},
                         "arrange": {"enum": ["auto", "none"], "default": "auto"}}}},

    {"name": "move",
     "description": "Move or resize elements. Moving one inside a shot moves the shot with it.",
     "inputSchema": {"type": "object", "required": ["moves"], "additionalProperties": False,
                     "properties": {"moves": {"type": "array", "minItems": 1, "maxItems": 50,
                                              "items": {"type": "object",
                                                        "required": ["element_id"],
                                                        "additionalProperties": False,
                                                        "properties": {
                                                            "element_id": {"type": "string"},
                                                            "x": {"type": "number"},
                                                            "y": {"type": "number"},
                                                            "w": {"type": "number"},
                                                            "h": {"type": "number"}}}}}}},

    {"name": "arrange",
     "description": ("Lay the canvas out. Use storyboard after every batch — one row per shot, "
                     "caption beneath — rather than computing coordinates by hand."),
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {
                         "layout": {"enum": ["grid", "row", "column", "storyboard"],
                                    "default": "grid"},
                         "element_ids": {"type": "array", "items": {"type": "string"}},
                         "columns": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                         "gutter": {"type": "integer", "minimum": 0, "maximum": 200,
                                    "default": 24},
                         "origin": {"type": "object", "additionalProperties": False,
                                    "properties": {"x": {"type": "number"},
                                                   "y": {"type": "number"}}}}}},

    {"name": "remove",
     "description": ("Take elements off the canvas. This never deletes media — the file stays and "
                     "can be placed again, so tidying a canvas is safe."),
     "inputSchema": {"type": "object", "required": ["element_ids"], "additionalProperties": False,
                     "properties": {"element_ids": {"type": "array", "minItems": 1, "maxItems": 50,
                                                    "items": {"type": "string"}}}}},

    {"name": "set_timeline",
     "description": ("The cut: which shots, in what order, at what length. ARRAY ORDER IS THE CUT "
                     "ORDER — it is never inferred from where things sit on the canvas. "
                     "`overlays` are layers above the cut: each names the second of the film it "
                     "appears at, so adding one never moves the shots underneath. A layer fills "
                     "the frame unless given a smaller `scale`, and the film stays as long as "
                     "its shots — a layer running past the end is trimmed."),
     "inputSchema": {"type": "object", "required": ["shots"], "additionalProperties": False,
                     "properties": {
                         "shots": {"type": "array", "minItems": 1, "maxItems": 40,
                                   "items": {"type": "object", "required": ["element_id"],
                                             "additionalProperties": False,
                                             "properties": {"element_id": {"type": "string"},
                                                            "in_s": {"type": "number",
                                                                     "minimum": 0},
                                                            "out_s": {"type": "number",
                                                                      "minimum": 0}}}},
                         "audio": {"type": "array", "maxItems": 8,
                                   "items": {"type": "object", "required": ["element_id"],
                                             "additionalProperties": False,
                                             "properties": {"element_id": {"type": "string"},
                                                            "start_s": {"type": "number",
                                                                        "minimum": 0,
                                                                        "default": 0},
                                                            "gain_db": {"type": "number",
                                                                        "minimum": -40,
                                                                        "maximum": 6,
                                                                        "default": 0}}}},
                         "overlays": {"type": "array", "maxItems": 12,
                                      "items": {"type": "object",
                                                "required": ["element_id", "start_s"],
                                                "additionalProperties": False,
                                                "properties": {
                                                    "element_id": {"type": "string"},
                                                    "start_s": {"type": "number", "minimum": 0},
                                                    "in_s": {"type": "number", "minimum": 0},
                                                    "out_s": {"type": "number", "minimum": 0},
                                                    "layer": {"type": "integer", "minimum": 1,
                                                              "maximum": 8, "default": 1},
                                                    "scale": {"type": "number", "minimum": 0.05,
                                                              "maximum": 1, "default": 1},
                                                    "position": {"enum": ["full", "tl", "tr",
                                                                          "bl", "br", "center"],
                                                                 "default": "full"}}}},
                         "fps": {"enum": [24, 25, 30], "default": 30},
                         "resolution": {"enum": ["1920x1080", "1080x1920", "1080x1080"],
                                        "default": "1920x1080"}}}},

    {"name": "export_timeline",
     "description": ("Assemble the timeline into one video. Refuses while any shot is still "
                     "rendering. Progress is reported as a real count of shots, never an ETA."),
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"filename": {"type": "string", "maxLength": 120}}}},
]

# The refusal a tool gives when the credential carries no session. There is nowhere to put media,
# so saying so beats generating something that lands nowhere.
_MEDIA_NO_SESSION = ("This agent has no workspace, so there is nowhere to place media. "
                     "Nothing was generated.")


def _media_json_text(obj) -> dict:
    return _tool_text(json.dumps(obj, ensure_ascii=False))


# ── the schemas above, enforced ───────────────────────────────────────────────────────────────
# Every tool declares its arguments and NOTHING CHECKED THEM. The bodies coerced by hand and
# assumed the declaration had held: `float(args["seconds"])` is a ValueError on the string "six"
# and a TypeError on {"n": 6}; `for j in args["job_ids"]` is a TypeError on a bare 5; a mistyped
# argument name read as "that argument was not sent". None of those are in the MediaError tree, so
# each one left the agent with an HTTP 500 — and a model writing "six" where a number goes is an
# ordinary turn, not an attack. The schema was already written; this makes it true.
_MCP_TYPES = {"string": str, "array": list, "object": dict}
_MCP_TYPE_WORDS = {"string": "a string", "number": "a number", "integer": "a whole number",
                   "boolean": "true or false", "array": "a list", "object": "an object"}


def _mcp_kind(v) -> str:
    """What a value IS, in the same words a refusal asks for."""
    if v is None:
        return "nothing"
    if isinstance(v, bool):
        return "true or false"
    if isinstance(v, (int, float)):
        return "a number"
    return {str: "a string", list: "a list"}.get(type(v), "an object")


def _mcp_type_ok(want: str, v) -> bool:
    """Does `v` match a declared `type`? `True` is an int in Python and is not a number in JSON."""
    if want in ("number", "integer"):
        return (not isinstance(v, bool)
                and isinstance(v, int if want == "integer" else (int, float)))
    if want == "boolean":
        return isinstance(v, bool)
    py = _MCP_TYPES.get(want)
    return py is None or isinstance(v, py)


def _mcp_argument_refusal(schema: dict, value, where: str = "") -> str:
    """The first way `value` does not match `schema`, said to the agent — "" when it does.

    THE PART OF THE SCHEMA THAT IS ABOUT SHAPE, and deliberately not the rest. `type`, `required`,
    `enum` and `additionalProperties` are what a tool body assumes before it touches an argument,
    and a wrong shape is what raises. `minimum`, `maxLength` and `pattern` are NOT enforced here:
    those are value limits that the tool bodies and the media plane already answer for themselves,
    and a second opinion on a limit, kept in step by hand, is the exact thing this file keeps
    finding. One rule, one place.
    """
    at = f" for {where}" if where else ""
    if "enum" in schema and value not in schema["enum"]:
        return (f"{where or 'that'} has to be one of "
                f"{', '.join(json.dumps(e) for e in schema['enum'])}; "
                f"{json.dumps(value)[:60]} was sent.")
    want = str(schema.get("type") or "")
    if want and not _mcp_type_ok(want, value):
        return (f"{where or 'that argument'} has to be {_MCP_TYPE_WORDS.get(want, want)}; "
                f"{_mcp_kind(value)} was sent.")
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if req not in value:
                return f"{req} is required{at} and was not sent."
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    return (f"there is no argument called {k}{at} — the ones it takes are "
                            f"{', '.join(sorted(props)) or 'none'}.")
        for k, v in value.items():
            bad = _mcp_argument_refusal(props[k], v, f"{where}.{k}" if where else k) \
                if k in props else ""
            if bad:
                return bad
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(value):
            bad = _mcp_argument_refusal(schema["items"], v, f"{where}[{i}]")
            if bad:
                return bad
    return ""


async def _media_read_image(sid: str, med: str) -> tuple[str, str]:
    """(base64, mime) for one image OUT OF OUR OWN STORE. Never out of a provider URL: those
    expire, and a continuity frame that stops resolving is a different character in shot four."""
    meta = await _media_meta(sid, med)
    if not meta:
        raise media_plane.MediaError(f"There is no media with the id {med} in this session.")
    data = await _blob_get(_media_blob(sid, med, str(meta.get("ext") or "png")), kb=BLOB_KB)
    if not data:
        raise media_plane.MediaError(f"The file behind {med} is no longer readable.")
    return base64.b64encode(data).decode(), str(meta.get("mime") or "image/png")


async def _media_resolve_input_image(sid: str, ref: str) -> tuple[str, str, str]:
    """(media id, base64, mime) for a media id or job id the agent named as the input to a render.

    The id comes back too: it is what gets written down, so a chain that has to advance can
    re-read the frame instead of carrying megabytes of base64 on a graph vertex.
    """
    med = ref
    if ref.startswith("mjob_"):
        job = await _media_job_get(ref)
        if not job or str(job.get("session") or "") != sid:
            raise media_plane.MediaError(f"No job with the id {ref} in this session.")
        if not job.get("media_id"):
            raise media_plane.MediaError(f"Job {ref} has produced nothing to work from yet.")
        med = str(job["media_id"])

    # NAMING A CLIP MEANS "CARRY ON FROM WHERE THAT ONE ENDED", and the frame it ended on is the
    # only thing that can express it: the still that seeded a shot is where the shot BEGAN, and
    # five seconds of movement later the world has moved on. Handing the mp4 over as though it
    # were an image is what happened before — a video sent to an image input, paid for, refused.
    meta = await _media_meta(sid, med) or {}
    if str(meta.get("mime") or "").startswith("video/") or str(meta.get("ext") or "") == "mp4":
        data = await _blob_get(_media_blob(sid, med, str(meta.get("ext") or "mp4")), kb=BLOB_KB)
        if not data:
            raise media_plane.MediaError(f"The clip behind {med} is no longer readable.")
        tmp = tempfile.mkdtemp(prefix="hr-frame-")
        try:
            path = os.path.join(tmp, f"clip.{meta.get('ext') or 'mp4'}")
            pathlib.Path(path).write_bytes(data)
            frame = await media_plane.to_thread(media_plane.grab_frame, path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return med, base64.b64encode(frame).decode(), "image/jpeg"

    b64, mime = await _media_read_image(sid, med)
    return med, b64, mime


async def _media_tool_call(name: str, args: dict, hid: str, sid: str, org: str,
                           entry_id: str) -> dict:
    """One tool. Every failure is a TOOL RESULT and never an HTTP error, because an agent can read
    a sentence and cannot read a 500."""
    # ---- what can be made ----
    if name == "list_capabilities":
        providers = await _media_providers()
        out = []
        for cap_name in media_plane.capability_names():
            cap = media_plane.capability(cap_name)
            if cap.get("local"):
                ok = media_plane.have_ffmpeg()
                out.append({"name": cap_name, "available": ok, "model": None,
                            "limits": {"max_shots": cap.get("max_shots"),
                                       "max_total_s": cap.get("max_total_s")},
                            **({} if ok else {"reason": "This deployment cannot assemble video — "
                                                        "ffmpeg is not installed."})})
                continue
            probe = {"seconds": 6} if cap_name.endswith("_video") else {}
            if cap_name.startswith("image_to"):
                probe["image"] = "probe"
            cand, skipped = media_plane.resolve(cap_name, probe, set(providers),
                                                _media_quarantine)
            row = {"name": cap_name, "available": bool(cand),
                   "model": str(cand.get("model")) if cand else None,
                   "limits": media_plane.limits_of(cand) if cand else {}}
            usd = media_plane.estimated_usd(cand) if cand else None
            if usd is not None:
                row["estimated_usd_per_unit"] = usd
            if not cand:
                # The first thing the chain skipped, which is the most specific reason there is.
                # A capability-level refusal string used to win here; it was a second answer to
                # the same question, kept in step with the candidates by hand.
                row["reason"] = skipped[0] if skipped else "No connected provider serves it."
            if skipped:
                row["skipped"] = [{"reason": s} for s in skipped[:6]]
            out.append(row)
        return _media_json_text({"capabilities": out})

    # ---- generation ----
    if name in ("generate_video", "generate_image", "generate_speech", "generate_music"):
        if not sid:
            return _tool_text(_MEDIA_NO_SESSION, True)
        spent = await _media_spend(sid)
        if spent >= media_plane.SESSION_BUDGET_USD:
            return _tool_text(
                f"This video has already cost ${spent:.2f}, which is the ${media_plane.SESSION_BUDGET_USD:.2f} "
                f"limit for one session. Nothing was generated. Ask the person whether to carry "
                f"on — you cannot raise the limit yourself.", True)
        params: dict = {}
        notes: list[str] = []
        if name == "generate_video":
            params = {"prompt": str(args.get("prompt") or ""),
                      "seconds": float(args.get("seconds") or 0),
                      "allow_watermark": bool(args.get("allow_watermark"))}
            if args.get("aspect"):
                # CARRIED, not dropped. It goes into `params` and therefore onto the job, which is
                # what makes it hold on the poll walk too: a chain that advances re-resolves out
                # of the same params, so the second candidate is filtered by the same rule as the
                # first and cannot quietly hand back a landscape clip.
                params["aspect"] = str(args["aspect"])
            cap = "text_to_video"
        elif name == "generate_image":
            size = str(args.get("size") or "1024x1024")
            params = {"prompt": str(args.get("prompt") or ""), "size": size}
            cap = "text_to_image"
        elif name == "generate_music":
            # The same path as every other generation, so the refusal is the chain's own answer
            # rather than a second sentence kept in step by hand. It exists as a tool at all so
            # that "no music model" is a stated fact and not a missing tool a model works around
            # by reaching for speech.
            params = {"prompt": str(args.get("prompt") or "")}
            if args.get("seconds"):
                params["seconds"] = float(args["seconds"])
            cap = "text_to_music"
        else:
            # THE LINE, AS ASKED FOR. What each model has to be TOLD to make it read that line is
            # the model's own business and is applied per candidate in `build_submit` — this used
            # to wrap it in "Read this aloud exactly as written…" here, before any model had been
            # chosen, which is an instruction about gpt-audio handed to whatever ran. A real
            # reader reads it out.
            params = {"prompt": str(args.get("text") or "")}
            if args.get("voice"):
                # ONLY WHEN THE CALLER NAMED ONE. A default written here would be one provider's
                # voice name applied to every provider — `alloy` was, and it skipped the model
                # that reads on every call that named no voice, because it has no voice by that
                # name and `can_serve` correctly said so.
                params["voice"] = str(args["voice"])
            cap = "text_to_speech"
        if args.get("from_image"):
            try:
                med, b64, mime = await _media_resolve_input_image(sid, str(args["from_image"]))
            except media_plane.MediaError as e:
                return _tool_text(str(e), True)
            params.update({"image": b64, "image_mime": mime, "from_media": med})
            cap = "image_to_video" if name == "generate_video" else "image_to_image"
        try:
            # The budget is opened HERE, around the whole generation, because it belongs to the
            # call and not to the walk: the synchronous shapes bill inside `_media_generate` too.
            async with _media_budget_for(sid) as budget:
                job = await _media_generate(cap, params, hid, sid, org, entry_id, budget,
                                            shot=str(args.get("shot") or ""))
        except _MediaNoModel as e:
            return _tool_text(e.text, True)
        except media_plane.MediaError as e:
            return _tool_text(str(e), True)
        cand = _media_candidate(cap, str(job["model"])) or {}
        out = {"job_id": job["id"], "capability": cap, "model": job["model"],
               "status": job["status"]}
        if name == "generate_video":
            out["seconds"] = params["seconds"]
            allowed = cand.get("durations_s")
            if allowed:
                notes.append(f"This model renders {' and '.join(str(a) for a in allowed)} s only; "
                             f"{params['seconds']:g} s was requested and accepted.")
            elif cand.get("duration_ignored"):
                # Measured: it takes the duration and returns whatever length it likes. Anything
                # that needs an exact length has to read the one that actually landed.
                obs = cand.get("duration_observed_s")
                notes.append("This model does not honour a requested duration"
                             + (f" — the clip measured came back {float(obs):g} s" if obs else "")
                             + ". check_jobs reports the real length once it lands; cut from that "
                               "rather than from the seconds you asked for.")
        # THE SHAPE THAT WAS ACTUALLY SECURED, on the same footing as the model that ran. It can
        # only be the one asked for — a candidate that could not hold it was skipped — so what is
        # worth saying is HOW, because "it was told" and "it is only ever that" are different
        # promises and only one of them survives the model being swapped.
        if params.get("aspect"):
            out["aspect"] = params["aspect"]
            told = media_plane.aspect_size(cand, params["aspect"])
            if told:
                notes.append(f"{cand['model']} was asked for a {told} frame.")
            elif cand.get("resolution"):
                notes.append(f"{cand['model']} renders {cand['resolution']} and nothing else, "
                             f"which is {params['aspect']}.")
        if name == "generate_image":
            # ONLY WHAT THE PROVIDER WAS ACTUALLY TOLD. This used to echo the requested size on
            # every call, including the rank-1 gemini models whose params are ["prompt"] and which
            # are never sent one — a number printed beside the model that never received it.
            told = media_plane.size_for(cand, params)
            if told:
                out["size"] = told
            else:
                notes.append("This model cannot be told a frame size, so the one you asked for "
                             "was not sent. check_jobs reports the size that actually landed.")
        if job.get("usd"):
            out["estimated_usd"] = round(float(job["usd"]), 4)
        if job.get("attempts"):
            out["attempts"] = job["attempts"]
        if job.get("media_id"):
            out["media_id"] = job["media_id"]
        if name == "generate_speech":
            # THE VOICE THAT WAS ACTUALLY SENT, on the same footing as the model — computed by the
            # one function the submit is built from, so the two cannot disagree. Absent where the
            # model has no voices to be told about.
            told = media_plane.voice_for(cand, params)
            if told:
                out["voice"] = told
            if cand.get("answers_prompts"):
                # ABOUT THE MODEL THAT RAN, not about the capability. This sentence used to be on
                # every result, including the ones from a model that reads what it is given —
                # where it is a warning about a defect the caller does not have, and an
                # instruction to compare a transcript that does not exist.
                out["warning"] = ("This model answers prompts rather than reading them. check_jobs "
                                  "returns spoken_text — compare it with what you asked for before "
                                  "you use the audio.")
            if job.get("spoken_text"):
                out["spoken_text"] = job["spoken_text"]
                out["verbatim"] = media_plane.levenshtein_ratio(
                    params.get("prompt") or "", str(job["spoken_text"])) >= 0.9
        if notes:
            out["note"] = " ".join(notes)
        return _media_json_text(out)

    if name == "check_jobs":
        ids = [str(j) for j in (args.get("job_ids") or [])][:50]
        rows = []
        # ONE BUDGET FOR THE WHOLE CALL, not one per job. A poll that answers FAILURE advances
        # the chain, and an advance is an outbound submit — so six failing jobs in one check_jobs
        # meant six of them, from what the agent issued as a READ. The same budget a generate
        # call opens, for the same reason: overlapping work on one session shares one ceiling.
        async with _media_budget_for(sid) as budget:
            for jid in ids:
                job = await _media_job_get(jid)
                if not job or str(job.get("session") or "") != sid:
                    # NEVER omitted: a missing row reads as "still running".
                    rows.append({"job_id": jid, "status": "failed",
                                 "error": "No job with that id in this session."})
                    continue
                try:
                    job = await _media_job_advance(job, budget)
                except Exception as e:  # noqa: BLE001
                    print(f"[media] advance {jid}: {type(e).__name__}", flush=True)
                row = {"job_id": jid, "status": job.get("status"),
                       "capability": job.get("capability"), "model": job.get("model")}
                if job.get("status") == "running" and job.get("last_poll") == "unknown":
                    # The known background-response race. Said plainly, because a model
                    # that reads an empty record as failure throws away a render that is
                    # about to land.
                    row["status"] = "unknown"
                    row["note"] = ("The provider returned an empty record. This is transient "
                                   "— ask again.")
                if job.get("status") == "succeeded":
                    row.update({"media_id": job.get("media_id"),
                                "kind": _MEDIA_KIND.get(str(job.get("capability")), "image"),
                                "seconds": job.get("seconds") or None,
                                "width": job.get("width") or None,
                                "height": job.get("height") or None,
                                "bytes": job.get("bytes") or None})
                    if job.get("usd"):
                        row["usd"] = round(float(job["usd"]), 4)
                    if job.get("spoken_text"):
                        row["spoken_text"] = job["spoken_text"]
                        row["verbatim"] = media_plane.levenshtein_ratio(
                            (job.get("params") or {}).get("prompt") or "",
                            str(job["spoken_text"])) >= 0.9
                elif job.get("status") == "failed":
                    row["error"] = job.get("error") or "the render failed"
                    if job.get("attempts"):
                        row["attempts"] = job["attempts"]
                elif job.get("progress"):
                    row["progress"] = job["progress"]
                if job.get("element_id"):
                    row["element_id"] = job["element_id"]
                rows.append(row)
        # `unknown` never appears as a terminal state here; it is a poll that came back empty and
        # the tool description says to ask again.
        return _media_json_text({"jobs": rows})

    # ---- the canvas ----
    if not sid:
        return _tool_text(_MEDIA_NO_SESSION, True)

    if name == "describe_canvas":
        scene = await _media_scene_read(sid)
        els = [e for e in scene.get("elements") or [] if not e.get("isDeleted")]
        tl = scene.get("timeline") or {}
        shots = {}
        for e in els:
            label = ((e.get("customData") or {}).get("shot") or "")
            if label:
                shots.setdefault(label, []).append(e.get("id"))
        x, y = media_plane.next_free(els)
        return _media_json_text({
            "scene_rev": int(float((scene.get("meta") or {}).get("rev") or 0)),
            "bounds": media_plane.scene_bounds(els),
            "elements": [media_plane.element_summary(e) for e in els],
            "shots": [{"name": k, "element_ids": v} for k, v in shots.items()],
            "timeline": {"shots": len(tl.get("shots") or []),
                         "total_seconds": media_plane.timeline_total(scene),
                         "fps": tl.get("fps"), "resolution": tl.get("resolution")},
            "free_space": {"x": x, "y": y}})

    if name == "place":
        items = args.get("items") or []
        for i, it in enumerate(items, 1):
            named = [k for k in ("job_id", "media_id", "text") if it.get(k)]
            if len(named) != 1:
                return _tool_text(f"An item must name a job, a media id or text — item {i} named "
                                  f"{'both' if len(named) > 1 else 'neither'}.", True)
        placed: list[dict] = []
        # "auto" packs anything you gave no coordinates for into the next free row. "none" means
        # exactly that: an item with no coordinates lands at the canvas origin and moving it is
        # yours to do. A parameter whose two values behave identically is a lie in a schema.
        auto = str(args.get("arrange") or "auto") == "auto"

        prepared = []
        for it in items:
            if it.get("job_id"):
                job = await _media_job_get(str(it["job_id"]))
                if not job or str(job.get("session") or "") != sid:
                    return _tool_text(f"No job with the id {it['job_id']} in this session.", True)
                prepared.append((it, job, None))
            elif it.get("media_id"):
                meta = await _media_meta(sid, str(it["media_id"]))
                if not meta:
                    return _tool_text(f"There is no media with the id {it['media_id']} in this "
                                      f"session.", True)
                prepared.append((it, None, meta))
            else:
                prepared.append((it, None, None))

        def mutate(scene: dict):
            els = scene.get("elements") or []
            for it, job, meta in prepared:
                x, y = it.get("x"), it.get("y")
                if x is None or y is None:
                    x, y = (media_plane.next_free([e for e in els if not e.get("isDeleted")])
                            if auto else (0.0, 0.0))
                w = float(it.get("w") or media_plane.TILE_W)
                h = float(it.get("h") or media_plane.TILE_H)
                # The job's own label is the default, and a label named here overrides it: an
                # agent that renames a shot while placing it means the rename. Without the
                # fallback, the `shot` argument on the generate tools promised a grouping that
                # only happened if the agent typed the same label a second time.
                shot = str(it.get("shot") or (job or {}).get("shot") or "")
                if it.get("text"):
                    # `h` only when it was actually asked for. A caption's height is CAPTION_H and
                    # not the tile default, so passing the computed `h` unconditionally would make
                    # every caption a tile tall — but ignoring an `h` the caller DID send is the
                    # same declared-and-unread defect as the two this commit is about.
                    el = media_plane.text_element(str(it["text"]), x=x, y=y, w=w,
                                                  **({"h": float(it["h"])} if it.get("h") else {}))
                else:
                    kind = (_MEDIA_KIND.get(str((job or {}).get("capability")), "image")
                            if job else str((meta or {}).get("kind") or "image"))
                    med = str((job or {}).get("media_id") or (meta or {}).get("media_id") or "")
                    ready = bool(med)
                    el = media_plane.media_element(
                        kind, x=x, y=y, w=w, h=h, media_id=med,
                        job_id=str((job or {}).get("id") or ""),
                        status="ready" if ready else str((job or {}).get("status") or "running"),
                        model=str((job or {}).get("model") or (meta or {}).get("model") or ""),
                        cap=str((job or {}).get("capability") or (meta or {}).get("capability") or ""),
                        seconds=float((job or {}).get("seconds") or (meta or {}).get("seconds") or 0),
                        width=int((job or {}).get("width") or (meta or {}).get("width") or 0),
                        height=int((job or {}).get("height") or (meta or {}).get("height") or 0),
                        prompt=str(((job or {}).get("params") or {}).get("prompt")
                                   or (meta or {}).get("prompt") or ""),
                        label=shot,
                        media_url=_media_url(hid, entry_id, sid, med) if med else "")
                    if kind == "image" and med:
                        scene.setdefault("files", {})[med] = media_plane.file_entry(
                            med, str((meta or {}).get("mime") or "image/png"),
                            _media_url(hid, entry_id, sid, med))
                    if job:
                        job["element_id"] = el["id"]
                if shot:
                    el.setdefault("customData", {})["shot"] = shot
                els.append(el)
                placed.append({"element_id": el["id"], "kind": media_plane.media_of(el).get("kind")
                               or "text", "status": media_plane.media_of(el).get("status"),
                               "x": el["x"], "y": el["y"], "w": el["width"], "h": el["height"],
                               **({"job_id": it["job_id"]} if it.get("job_id") else {}),
                               **({"media_id": it["media_id"]} if it.get("media_id") else {})})
                if it.get("caption"):
                    cap_el = media_plane.text_element(str(it["caption"]), x=el["x"],
                                                      y=el["y"] + el["height"] + 8, w=el["width"])
                    if shot:
                        cap_el.setdefault("customData", {})["shot"] = shot
                    els.append(cap_el)
                    placed.append({"element_id": cap_el["id"], "kind": "text",
                                   "x": cap_el["x"], "y": cap_el["y"], "w": cap_el["width"],
                                   "h": cap_el["height"]})
            scene["elements"] = els
            return None

        rev, _ = await _media_scene_touch(sid, mutate)
        for _it, job, _meta in prepared:
            if job and job.get("element_id"):
                await _media_job_save(job)
        return _media_json_text({"scene_rev": rev, "placed": placed})

    if name == "move":
        moves = {str(m.get("element_id")): m for m in (args.get("moves") or [])}
        moved: list[str] = []
        missing: list[str] = []

        def mutate(scene: dict):
            by_id = {e.get("id"): e for e in scene.get("elements") or []}
            for eid, m in moves.items():
                el = by_id.get(eid)
                if not el:
                    missing.append(eid)
                    continue
                dx = float(m["x"]) - float(el.get("x") or 0) if m.get("x") is not None else 0.0
                dy = float(m["y"]) - float(el.get("y") or 0) if m.get("y") is not None else 0.0
                for key, src in (("x", "x"), ("y", "y"), ("width", "w"), ("height", "h")):
                    if m.get(src) is not None:
                        el[key] = float(m[src])
                moved.append(eid)
                shot = (el.get("customData") or {}).get("shot")
                if shot and (dx or dy):
                    # Moving one element of a shot moves the shot: a caption left behind is a
                    # caption under the wrong clip.
                    for other in scene.get("elements") or []:
                        if other is el or (other.get("customData") or {}).get("shot") != shot:
                            continue
                        other["x"] = float(other.get("x") or 0) + dx
                        other["y"] = float(other.get("y") or 0) + dy
            return None

        rev, _ = await _media_scene_touch(sid, mutate)
        return _media_json_text({"scene_rev": rev, "moved": moved, "not_found": missing})

    if name == "arrange":
        layout = str(args.get("layout") or "grid")
        want = {str(e) for e in (args.get("element_ids") or [])}
        columns = int(args.get("columns") or 4)
        gutter = int(args.get("gutter") if args.get("gutter") is not None else media_plane.GUTTER)
        origin = args.get("origin") or {}
        ox = float(origin.get("x", 40)); oy = float(origin.get("y", 40))
        positions: list[dict] = []

        def mutate(scene: dict):
            positions.clear()          # mutate may be re-run; positions is the caller's answer
            els = [e for e in scene.get("elements") or [] if not e.get("isDeleted")]
            # Named ids, or every media element when none were named. A named set that matches
            # nothing arranges NOTHING — falling back to "everything" would rearrange a board the
            # caller was trying to leave alone.
            chosen = ([e for e in els if e.get("id") in want] if want
                      else [e for e in els if media_plane.is_media(e)])
            if layout == "storyboard":
                items = media_plane.storyboard_items(els, chosen)
            else:
                items = [{"id": e.get("id"),
                          "w": float(e.get("width") or media_plane.TILE_W),
                          "h": float(e.get("height") or media_plane.TILE_H)} for e in chosen]
            positions.extend(media_plane.layout_positions(items, layout, columns=columns,
                                                          gutter=gutter, origin=(ox, oy)))
            by_id = {e.get("id"): e for e in els}
            for p in positions:
                el = by_id.get(p["element_id"])
                if el:
                    el["x"], el["y"] = float(p["x"]), float(p["y"])
            return None

        rev, _ = await _media_scene_touch(sid, mutate)
        return _media_json_text({"scene_rev": rev, "positions": positions})

    if name == "remove":
        ids = {str(e) for e in (args.get("element_ids") or [])}
        removed: list[str] = []
        missing: list[str] = []

        def mutate(scene: dict):
            keep = []
            found = set()
            for el in scene.get("elements") or []:
                if el.get("id") in ids:
                    found.add(el.get("id"))
                    continue
                keep.append(el)
            scene["elements"] = keep
            removed.extend(sorted(found))
            missing.extend(sorted(ids - found))
            tl = scene.get("timeline") or {}
            tl["shots"] = [s for s in tl.get("shots") or [] if s.get("elementId") not in ids]
            tl["audio"] = [a for a in tl.get("audio") or [] if a.get("elementId") not in ids]
            return None

        rev, _ = await _media_scene_touch(sid, mutate)
        # Said in the return, because an agent that believes remove is destructive will not tidy.
        return _media_json_text({"scene_rev": rev, "removed": removed, "not_found": missing,
                                 "media_kept": True})

    if name == "set_timeline":
        shots_in = args.get("shots") or []
        audio_in = args.get("audio") or []
        overlays_in = args.get("overlays") or []
        cap = media_plane.capability("export")
        max_shots = int(cap.get("max_shots") or 40)
        if len(shots_in) > max_shots:
            return _tool_text(f"A timeline holds at most {max_shots} shots; this one has "
                              f"{len(shots_in)}.", True)
        warnings: list[str] = []
        # NAMING SOMETHING THAT IS NOT THERE IS A MISTAKE, NOT A NOTE IN THE MARGIN. Skipping it
        # and reporting a warning wrote a cut that quietly lacked what was asked for: a real run
        # lost its whole music bed that way — the ids had gone stale, every entry was dropped,
        # the film exported without a note of music in it and nothing failed. A warning the
        # caller is free to ignore is not a guard when the result is silence.
        bad: list[str] = []
        result: dict = {}

        def mutate(scene: dict):
            by_id = {e.get("id"): e for e in scene.get("elements") or []}
            shots = []
            for i, s in enumerate(shots_in, 1):
                eid = str(s.get("element_id") or "")
                el = by_id.get(eid)
                if not el:
                    bad.append(f"Shot {i} names {eid}, which is not on the canvas.")
                    continue
                m = media_plane.media_of(el)
                if m.get("status") != "ready":
                    warnings.append(f"Shot {i} ({eid}) is still rendering — export will refuse "
                                    f"until it lands.")
                w, h = int(m.get("width") or 0), int(m.get("height") or 0)
                res = str(args.get("resolution") or "1920x1080")
                rw, rh = media_plane.parse_size(res)
                if w and h and rw and rh and abs(w / h - rw / rh) > 0.02:
                    warnings.append(f"Shot {i} is {w}x{h} and will be letterboxed into {res}.")
                # Normalised on the way IN, so what is stored is what will be filmed. Written
                # raw, a still the agent placed without a duration was stored as outS 0 — in the
                # cut, absent from the film, and nothing anywhere said why.
                a, b, _ = media_plane.shot_window(
                    {"inS": s.get("in_s"), "outS": s.get("out_s")}, m)
                shots.append({"elementId": eid, "inS": a, "outS": b})
            # CHECKED THE SAME WAY THE SHOTS ARE. Written blind, a bed naming an element that
            # is gone — an id that changed when the clip was placed again — stayed in the
            # document, was dropped without a word at export, and the film came out silent.
            audio = []
            for i, a in enumerate(audio_in, 1):
                eid = str(a.get("element_id") or "")
                m = media_plane.media_of(by_id.get(eid) or {})
                if not m:
                    bad.append(f"Sound {i} names {eid}, which is not on the canvas.")
                    continue
                if m.get("kind") != "audio":
                    bad.append(f"Sound {i} names {eid}, which is a {m.get('kind')} rather than a "
                              f"sound. Put it in `shots` or `overlays`.")
                    continue
                if m.get("status") != "ready":
                    warnings.append(f"Sound {i} ({eid}) is still rendering — export will refuse "
                                    f"until it lands.")
                audio.append({"elementId": eid, "startS": float(a.get("start_s") or 0.0),
                              "gainDb": float(a.get("gain_db") or 0.0)})
            # A LAYER IS PLACED, NOT QUEUED. An overlay names the moment on the film's clock
            # where it appears, so adding one never moves the shots underneath it.
            overlays = []
            for i, o in enumerate(overlays_in, 1):
                eid = str(o.get("element_id") or "")
                el = by_id.get(eid)
                if not el:
                    bad.append(f"Layer {i} names {eid}, which is not on the canvas.")
                    continue
                m = media_plane.media_of(el)
                a, b, _ = media_plane.shot_window(
                    {"inS": o.get("in_s"), "outS": o.get("out_s")}, m)
                pos = str(o.get("position") or "full")
                if pos not in media_plane.OVERLAY_POS:
                    warnings.append(f"Layer {i} asks to sit {pos!r}; it will fill the frame.")
                    pos = "full"
                overlays.append({"elementId": eid, "layer": max(1, int(o.get("layer") or 1)),
                                 "startS": max(0.0, float(o.get("start_s") or 0.0)),
                                 "inS": a, "outS": b, "position": pos,
                                 "scale": min(1.0, max(0.05, float(o.get("scale") or 1.0)))})
            scene["timeline"] = {"v": 1, "fps": int(args.get("fps") or 30),
                                 "resolution": str(args.get("resolution") or "1920x1080"),
                                 # ARRAY ORDER IS THE CUT ORDER. Never derived from canvas
                                 # position: dragging a card would silently re-cut the film.
                                 "shots": shots, "audio": audio, "overlays": overlays,
                                 "updatedAt": int(time.time() * 1000)}
            result["total"] = media_plane.timeline_total(scene)
            result["ready"] = bool(shots) and all(
                media_plane.media_of(by_id.get(s["elementId"], {})).get("status") == "ready"
                for s in shots)
            result["n"] = len(shots)
            result["layers"] = len(overlays)
            return None

        # Checked against the canvas BEFORE anything is written, so a refusal leaves the cut
        # exactly as it was rather than half-replaced.
        probe = await _media_scene_read(sid)
        by_id = {e.get("id"): e for e in probe.get("elements") or []}
        check_bad: list[str] = []
        for i, s_in in enumerate(shots_in, 1):
            if str(s_in.get("element_id") or "") not in by_id:
                check_bad.append(f"Shot {i} names {s_in.get('element_id')}, which is not on the "
                                 f"canvas.")
        for i, a_in in enumerate(audio_in, 1):
            m = media_plane.media_of(by_id.get(str(a_in.get("element_id") or "")) or {})
            if not m:
                check_bad.append(f"Sound {i} names {a_in.get('element_id')}, which is not on the "
                                 f"canvas.")
            elif m.get("kind") != "audio":
                check_bad.append(f"Sound {i} names {a_in.get('element_id')}, which is a "
                                 f"{m.get('kind')} rather than a sound.")
        for i, o_in in enumerate(overlays_in, 1):
            if str(o_in.get("element_id") or "") not in by_id:
                check_bad.append(f"Layer {i} names {o_in.get('element_id')}, which is not on the "
                                 f"canvas.")
        if check_bad:
            return _tool_text(" ".join(check_bad) + " Nothing was changed — call describe_canvas "
                              "for the ids that exist now.", True)

        rev, _ = await _media_scene_touch(sid, mutate)
        out = {"scene_rev": rev,
               "timeline": {"shots": result.get("n", 0), "layers": result.get("layers", 0),
                            "fps": int(args.get("fps") or 30),
                            "resolution": str(args.get("resolution") or "1920x1080")},
               "total_seconds": result.get("total", 0.0), "ready": bool(result.get("ready"))}
        if warnings:
            out["warnings"] = warnings
        return _media_json_text(out)

    if name == "export_timeline":
        if not media_plane.have_ffmpeg():
            return _tool_text("This deployment cannot assemble video — ffmpeg is not installed. "
                              "The clips are all still here to download individually.", True)
        try:
            job = await _media_export_start(hid, sid, org, entry_id,
                                            str(args.get("filename") or ""))
        except media_plane.MediaError as e:
            return _tool_text(str(e), True)
        return _media_json_text({"job_id": job["id"], "capability": "export",
                                 "shots": int(job.get("shots") or 0),
                                 "total_seconds": float(job.get("planned_seconds") or 0.0),
                                 "status": job["status"]})

    return _tool_text(f"No tool named {name!r} on this server.", True)


# ── export ────────────────────────────────────────────────────────────────────────────────────
async def _media_export_start(hid: str, sid: str, org: str, entry_id: str,
                              filename: str) -> dict:
    """Check the cut is assemblable, then run ffmpeg off the event loop as an ordinary job."""
    scene = await _media_scene_read(sid)
    tl = scene.get("timeline") or {}
    shots = tl.get("shots") or []
    if not shots:
        raise media_plane.ExportRefused("There is nothing in the timeline to export. Use "
                                        "set_timeline first.")
    cap = media_plane.capability("export")
    if len(shots) > int(cap.get("max_shots") or 40):
        raise media_plane.ExportRefused(f"A film here is at most {cap.get('max_shots')} shots.")
    running = [j for j in await _media_jobs_of(sid)
               if j.get("capability") == "export" and j.get("status") == "running"]
    if running:
        raise media_plane.ExportRefused("An export of this video is already running.")
    by_id = {e.get("id"): e for e in scene.get("elements") or []}
    plan: list[dict] = []
    for i, s in enumerate(shots, 1):
        m = media_plane.media_of(by_id.get(s.get("elementId")) or {})
        if m.get("status") != "ready" or not m.get("mediaId"):
            raise media_plane.ExportRefused(
                f"Shot {i} is still rendering. Every shot has to have landed before the film can "
                f"be cut.")
        # What window of the clip this shot shows — asked of the one function that answers it, so
        # the film, the planned total and the preview cannot come to different conclusions.
        in_s, out_s, still = media_plane.shot_window(s, m)
        plan.append({"media_id": str(m["mediaId"]), "in_s": in_s, "out_s": out_s, "still": still})
    total = media_plane.timeline_total(scene)
    if total > float(cap.get("max_total_s") or 600):
        raise media_plane.ExportRefused(
            f"That film is {total:.0f}s and the limit here is {cap.get('max_total_s')}s.")
    # The sound under the film. Refused rather than dropped, for the same reason a shot is: a
    # film delivered without the music somebody asked for is not the film, and the silent version
    # used to report success.
    audio_plan: list[dict] = []
    for i, a in enumerate(tl.get("audio") or [], 1):
        m = media_plane.media_of(by_id.get(a.get("elementId")) or {})
        if not m:
            raise media_plane.ExportRefused(
                f"Sound {i} is no longer on the canvas. Take it off the timeline, or put the "
                f"clip back, before the film is cut.")
        if m.get("status") != "ready" or not m.get("mediaId"):
            raise media_plane.ExportRefused(
                f"Sound {i} is still rendering. Everything in the film has to have landed "
                f"before it can be cut.")
        audio_plan.append({"media_id": str(m["mediaId"]),
                           "start_s": float(a.get("startS") or 0.0),
                           "gain_db": float(a.get("gainDb") or 0.0)})

    # The layers above the cut. A layer whose clip has not landed is refused for the same reason
    # a shot is: half a film is not a film, and the alternative is exporting it silently missing.
    overlay_plan: list[dict] = []
    for i, o in enumerate(tl.get("overlays") or [], 1):
        m = media_plane.media_of(by_id.get(o.get("elementId")) or {})
        if not m:
            continue                       # the layer names something that is not a clip
        # STATUS FIRST. Asking for the media id first skipped every layer that had not landed
        # yet — the export ran, succeeded, and quietly did not contain them.
        if m.get("status") != "ready" or not m.get("mediaId"):
            raise media_plane.ExportRefused(
                f"Layer {i} is still rendering. Every layer has to have landed before the film "
                f"can be cut.")
        o_in, o_out, still = media_plane.shot_window(o, m)
        overlay_plan.append({"media_id": str(m["mediaId"]), "in_s": o_in, "out_s": o_out,
                             "still": still, "start_s": max(0.0, float(o.get("startS") or 0.0)),
                             "layer": max(1, int(o.get("layer") or 1)),
                             "pos": str(o.get("position") or "full"),
                             "scale": float(o.get("scale") or 1.0)})

    now = int(time.time() * 1000)
    job = {"id": "mjob_" + uuid.uuid4().hex[:16], "org": org, "harness": hid, "session": sid,
           "entry": entry_id, "capability": "export", "params_json": json.dumps({}), "params": {},
           "status": "running", "model": "", "provider": "local", "provider_task_id": "",
           "attempts_json": "[]", "attempts": [], "next_poll_at": 0, "poll_backoff_s": 0,
           "media_id": "", "bytes": 0, "width": 0, "height": 0, "seconds": 0.0, "quota": 0.0,
           "usd": 0.0, "element_id": "", "error": "", "created_at": now, "updated_at": now,
           "shots": len(plan), "planned_seconds": total,
           "progress": f"0/{len(plan)} shots", "filename": filename or "film.mp4"}
    await _media_job_save(job)
    asyncio.create_task(_media_export_run(job, plan, audio_plan, overlay_plan,
                                          int(tl.get("fps") or 30),
                                          str(tl.get("resolution") or "1920x1080")))
    return job


async def _media_export_run(job: dict, plan: list[dict], audio_plan: list[dict],
                            overlay_plan: list[dict], fps: int, resolution: str) -> None:
    sid = str(job["session"])
    tmp = tempfile.mkdtemp(prefix="hr-media-")
    try:
        shots = []
        for i, s in enumerate(plan):
            meta = await _media_meta(sid, s["media_id"]) or {}
            data = await _blob_get(_media_blob(sid, s["media_id"], str(meta.get("ext") or "mp4")),
                                   kb=BLOB_KB)
            if not data:
                raise media_plane.ExportRefused(f"Shot {i + 1} is no longer readable.")
            path = os.path.join(tmp, f"shot{i}.{meta.get('ext') or 'mp4'}")
            pathlib.Path(path).write_bytes(data)
            shots.append({"path": path, "in_s": s["in_s"], "out_s": s["out_s"],
                          "still": s["still"]})
            job["progress"] = f"{i + 1}/{len(plan)} shots"
            await _media_job_save(job)
        tracks = []
        for j, a in enumerate(audio_plan):
            meta = await _media_meta(sid, a["media_id"]) or {}
            data = await _blob_get(_media_blob(sid, a["media_id"], str(meta.get("ext") or "wav")),
                                   kb=BLOB_KB)
            if not data:
                continue
            path = os.path.join(tmp, f"track{j}.{meta.get('ext') or 'wav'}")
            pathlib.Path(path).write_bytes(data)
            tracks.append({"path": path, "start_s": a["start_s"], "gain_db": a["gain_db"]})
        layers = []
        for j, o in enumerate(overlay_plan):
            meta = await _media_meta(sid, o["media_id"]) or {}
            data = await _blob_get(_media_blob(sid, o["media_id"], str(meta.get("ext") or "mp4")),
                                   kb=BLOB_KB)
            if not data:
                raise media_plane.ExportRefused(f"Layer {j + 1} is no longer readable.")
            path = os.path.join(tmp, f"layer{j}.{meta.get('ext') or 'mp4'}")
            pathlib.Path(path).write_bytes(data)
            layers.append({**o, "path": path,
                           "has_audio": bool(media_plane.probe_file(path).get("has_audio"))})
        out_path = os.path.join(tmp, "film.mp4")
        info = await media_plane.to_thread(media_plane.assemble, shots, tracks, fps=fps,
                                           resolution=resolution, out_path=out_path,
                                           overlays=layers)
        data = pathlib.Path(out_path).read_bytes()
        await _media_job_land(job, data)
        print(f"[media] {sid}: exported {len(shots)} shots"
              f"{f' + {len(layers)} layers' if layers else ''}, {info['seconds']}s", flush=True)
    except Exception as e:  # noqa: BLE001
        job.update({"status": "failed", "error": str(e)})
        await _media_job_save(job)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── the MCP endpoint ──────────────────────────────────────────────────────────────────────────
@app.post("/v1/mcp/media")
async def media_mcp(request: Request):
    """The MCP endpoint the agent's CLI talks to. The database server's twin: streamable HTTP,
    stateless, `initialize` echoes the client's protocol version, a notification is a 202.

    THE SESSION COMES FROM THE CREDENTIAL. No tool takes one as an argument and every schema is
    `additionalProperties: false`, so an agent cannot address another session's canvas — it cannot
    mint another session's token.

    EVERY FAILURE IS A TOOL RESULT AND NEVER AN HTTP ERROR, and below it is finally STRUCTURAL
    rather than a list of exception types. `except MediaError` / `except HTTPException` covered
    the failures somebody had thought of, so a ValueError from parsing an argument, a KeyError
    from building a submit and anything the store raised all left as a 500 — a status code an
    agent cannot read, on a path a well-behaved model reaches by writing "six" where a number
    goes. The two named handlers stay, because each says something better than the last one can.
    """
    claims = _verify_hosted_cred(_broker_token(request))
    if not claims:
        raise HTTPException(401, "invalid or expired turn credential")
    hid, sid, key = claims
    try:
        req = json.loads(await request.body() or b"{}")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "malformed JSON-RPC request") from None
    method, rid, params = req.get("method") or "", req.get("id"), req.get("params") or {}

    if method == "initialize":
        return _jsonrpc_result(rid, {
            "protocolVersion": str(params.get("protocolVersion") or "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "media", "version": "1"}})
    if rid is None:
        return Response(status_code=202)
    if method == "tools/list":
        return _jsonrpc_result(rid, {"tools": _MEDIA_MCP_TOOLS})
    if method != "tools/call":
        return JSONResponse({"jsonrpc": "2.0", "id": rid,
                             "error": {"code": -32601, "message": f"method not found: {method}"}})

    v = await _harness_vertex(hid)
    if v and str(v.get("deleted")) in ("1", "true", "True"):
        v = None            # a token outlives the agent it was minted for; its tools must not
    org = str((v or {}).get("org") or "")
    try:
        entry, _rec = await _hosted_resolve(_MEDIA_SERVER, hid, org, _mcp_list(v),
                                            key=key, check_enabled=True)
    except HTTPException:
        return _jsonrpc_result(rid, _tool_text(
            "This agent cannot make media — no media tools are connected to it. Ask the person to "
            "add them, then try again — you cannot connect them yourself.", True))
    name, args = str(params.get("name") or ""), params.get("arguments") or {}
    schema = next((t["inputSchema"] for t in _MEDIA_MCP_TOOLS if t["name"] == name), None)
    # CHECKED AGAINST THE DECLARATION, before any body assumes it held. An unknown tool is not
    # checked — `_media_tool_call` has a better sentence for that than "no schema".
    bad = _mcp_argument_refusal(schema, args) if schema is not None else ""
    if bad:
        return _jsonrpc_result(rid, _tool_text(
            f"{name} was not run, because {bad} Nothing happened; correct the call and repeat it.",
            True))
    try:
        out = await _media_tool_call(name, args, hid, sid, org,
                                     str(entry.get("id") or "mcp.media"))
    except media_plane.MediaError as e:
        return _jsonrpc_result(rid, _tool_text(str(e), True))
    except HTTPException as e:
        return _jsonrpc_result(rid, _tool_text(_uhp_message(e), True))
    except Exception as e:  # noqa: BLE001 — the promise, made structural: see this route's note
        # Named for the operator, not for the agent: what raised is ours to fix and not something
        # a model can act on, and a stack trace is not a sentence.
        print(f"[media] {name}: {type(e).__name__}: {e}", flush=True)
        return _jsonrpc_result(rid, _tool_text(
            f"{name} did not finish — something went wrong on this side, not in the way you "
            f"called it. Try it once more; if it fails the same way, tell the person rather than "
            f"working around it.", True))
    return _jsonrpc_result(rid, out)


# ── the app's data plane ──────────────────────────────────────────────────────────────────────
# A browser is not an MCP client and must never hold a turn credential, so the app reaches the same
# store through routes that carry the harness (which binds the entry) and the session (which owns
# the document) explicitly. Every one: member of the org → the harness → the session → the entry.

async def _media_server_out() -> dict:
    """What the media server says about itself: what can be made right now, which model each
    capability resolves to, and whether this deployment can assemble a film.

    Derived at read time, never stored. A model breaks or a provider is connected and the answer
    changes with no form re-saved — the same rule the integration model list already follows.
    """
    providers = await _media_providers()
    caps = []
    for cap_name in media_plane.capability_names():
        cap = media_plane.capability(cap_name)
        if cap.get("local"):
            caps.append({"name": cap_name, "available": media_plane.have_ffmpeg(), "model": None})
            continue
        probe = {"seconds": 6} if cap_name.endswith("_video") else {}
        if cap_name.startswith("image_to"):
            probe["image"] = "probe"
        cand, _sk = media_plane.resolve(cap_name, probe, set(providers), _media_quarantine)
        row = {"name": cap_name, "available": bool(cand),
               "model": str(cand.get("model")) if cand else None}
        usd = media_plane.estimated_usd(cand) if cand else None
        if usd is not None:
            row["estimatedUsdPerUnit"] = usd
        caps.append(row)
    return {"capabilities": caps, "export": {"available": media_plane.have_ffmpeg()}}


async def _media_route(hid: str, sid: str, eid: str, request: Request) -> tuple[str, dict, dict]:
    """(org, entry, session vertex) — the FOUR binds every app route to this server shares.

    Member of the org → the harness → the entry on that harness → AND THE SESSION ON THAT
    HARNESS. The fourth was missing and each of the first three looks like it covers it: the entry
    is bound to the harness, the session is bound to the org, so a second agent in the same org
    presenting its OWN media entry and this session's id was served this session's jobs, this
    session's canvas and the bytes of its renders. Harness ids and session ids are both public.

    The session vertex has said which harness it belongs to since it was created (`harness_id`,
    stamped by the session-create path, and filled in by _resp_resolve_session's continue branch for
    a session that reached a harness without one); it was written and never read. A session that
    names no harness cannot be proved to belong to this one, so it is refused rather than assumed —
    the routes are always addressed to a harness, so a session with no harness has no business here.

    Refusing is right and it is also a dead end: the person is holding a link to something the list
    still offers them. The app that owns that screen has to say so and offer the way back, which is
    why the kit renders this 404 as a video that cannot be opened rather than as a bare canvas.
    """
    org, _ = await _pub_org_member(request)
    v = await _harness_for_route(hid, org)
    entry, _rec = await _hosted_resolve(_MEDIA_SERVER, hid, org, _mcp_list(v), entry_id=eid)
    sv: dict = {}
    if sid:
        _o, sv = await _owned_session(request, sid)
        if str(sv.get("harness_id") or "") != hid:
            raise uhp_error(404, "session_not_found", "No session with that id.", "session_id")
    return org, entry, sv


class SceneWrite(BaseModel):
    scene: dict


@app.get("/v1/harnesses/{hid}/servers/{eid}/sessions/{sid}/scene")
async def get_media_scene(hid: str, eid: str, sid: str, request: Request) -> dict:
    await _media_route(hid, sid, eid, request)
    scene = await _media_scene_read(sid)
    return {"rev": int(float((scene.get("meta") or {}).get("rev") or 0)), "scene": scene}


@app.put("/v1/harnesses/{hid}/servers/{eid}/sessions/{sid}/scene")
async def put_media_scene(hid: str, eid: str, sid: str, body: SceneWrite,
                          request: Request) -> dict:
    """The app's write, with the whole conflict story in three status codes.

    409 while a turn is running — the agent owns the document during a turn, the same rule
    write_session_file holds for the same reason. 412 when the revision has moved, so a stale tab
    merges rather than clobbers. 422 when the write would add or delete a generated media element:
    a browser bug must not be able to orphan a rendered clip or resurrect a deleted one.
    """
    _org, _entry, v = await _media_route(hid, sid, eid, request)
    live = {"running", "starting"} & {str(v.get("turn_status") or ""), str(v.get("status") or "")}
    if live:
        raise uhp_error(409, "session_busy",
                        "The agent is working on this video. Wait for the turn to finish before "
                        "saving.")
    want = request.headers.get("if-match") or ""
    async with _media_scene_lock(sid):
        cur = await _media_scene_read(sid)
        rev = int(float((cur.get("meta") or {}).get("rev") or 0))
        if want and want.strip('"') != str(rev):
            raise uhp_error(412, "scene_moved",
                            "This canvas changed while you were editing it.", "If-Match",
                            {"rev": rev})
        incoming = media_plane.sanitize_scene(body.scene)
        before = {e.get("id") for e in cur.get("elements") or [] if media_plane.is_media(e)}
        after = {e.get("id") for e in incoming.get("elements") or [] if media_plane.is_media(e)}
        if before != after:
            raise uhp_error(422, "media_elements_are_the_agents",
                            "Media elements are placed and removed by the agent.")
        incoming["meta"] = {**(incoming.get("meta") or {}), "rev": rev}
        new_rev = await _media_scene_write(sid, incoming)
    return {"rev": new_rev}


@app.get("/v1/harnesses/{hid}/servers/{eid}/sessions/{sid}/jobs")
async def get_media_jobs(hid: str, eid: str, sid: str, request: Request,
                         ids: str = "") -> dict:
    """The same _media_job_advance path the agent's check_jobs takes, so a browser and an agent
    cannot see a job differently.

    EVERY job in the session, deliberately — a listing that dropped rows past a limit would be a
    canvas with clips missing from it. What is capped is not how many jobs are LISTED but how many
    outbound submits one tick of this may cause, and that is the budget below: a browser sitting
    on a session where several renders have failed used to fire one submit per failed job per
    tick, which is the same burst check_jobs made and from something the person did not ask for.

    ITS OWN BUDGET, not the session's shared one. `_media_budget_for` exists so that generate
    calls an agent issued in one turn share a ceiling — "a second render is the agent's decision,
    made with the first one's cost in front of it". A browser tick is not the agent's decision and
    is not part of that turn, so joining it there would let a person watching the canvas spend a
    ceiling the agent then gets refused against, with a sentence about "this request" that would
    be about somebody else's. One request, one budget; these are two requests.
    """
    await _media_route(hid, sid, eid, request)
    wanted = {i.strip() for i in (ids or "").split(",") if i.strip()}
    out = []
    budget = _MediaBudget()
    for job in await _media_jobs_of(sid):
        if wanted and job["id"] not in wanted:
            continue
        try:
            job = await _media_job_advance(job, budget)
        except Exception:  # noqa: BLE001
            pass
        out.append({"job_id": job["id"], "status": job.get("status"),
                    # WHEN it was submitted. Without it a caller holding several exports cannot
                    # tell which one is the latest, and the app followed whichever came first.
                    "created_at": job.get("created_at") or 0,
                    "capability": job.get("capability"), "model": job.get("model"),
                    "media_id": job.get("media_id") or None,
                    "element_id": job.get("element_id") or None,
                    "seconds": job.get("seconds") or None, "progress": job.get("progress") or None,
                    "error": job.get("error") or None,
                    **({"usd": round(float(job["usd"]), 4)} if job.get("usd") else {})})
    return {"jobs": out, "spend_usd": await _media_spend(sid)}


@app.post("/v1/harnesses/{hid}/servers/{eid}/sessions/{sid}/export")
async def post_media_export(hid: str, eid: str, sid: str, request: Request) -> dict:
    org, entry, _sv = await _media_route(hid, sid, eid, request)
    if not media_plane.have_ffmpeg():
        raise uhp_error(501, "export_unavailable",
                        "This deployment cannot assemble video — ffmpeg is not installed. The "
                        "clips are all still here to download individually.")
    try:
        job = await _media_export_start(hid, sid, org, str(entry.get("id") or eid), "")
    except media_plane.MediaError as e:
        raise uhp_error(400, "export_refused", str(e)) from e
    return {"job_id": job["id"], "shots": job.get("shots"),
            "total_seconds": job.get("planned_seconds"), "status": job["status"]}


@app.post("/v1/harnesses/{hid}/servers/{eid}/sessions/{sid}/media")
async def post_media_import(hid: str, eid: str, sid: str, request: Request) -> dict:
    """Put a picture the person already has into this video, as media the agent can work from.

    EVERYTHING ELSE IN A SESSION ARRIVED BY BEING RENDERED, which meant a reference image — the
    frame a template starts from, a photograph of the actual product — had nowhere to live. It
    could be shown in the app and never used, which is decoration, or not offered at all.

    It goes through the same door a render does: `_media_store` verifies the bytes really are
    what they claim before anything is kept, so an import cannot put a file into a timeline that
    the exporter will later refuse. The kind is read from the bytes, not from what the caller
    says they sent.
    """
    org, entry, _sv = await _media_route(hid, sid, eid, request)
    data = await request.body()
    if not data:
        raise uhp_error(400, "empty_upload", "There were no bytes in that upload.")
    if len(data) > media_plane.MAX_BYTES:
        raise uhp_error(413, "too_large",
                        f"That file is {len(data)} bytes and the limit here is "
                        f"{media_plane.MAX_BYTES}.")
    mime, _ext = media_plane.sniff(data)
    kind = {"image": "image", "video": "video", "audio": "audio"}.get(
        str(mime or "").split("/")[0] or "", "")
    if not kind:
        raise uhp_error(415, "not_media",
                        "That file is not a picture, a clip or a sound this can read.")
    label = (request.headers.get("x-media-label") or "")[:200]
    try:
        rec = await _media_store(sid, kind, data, {
            "model": "", "capability": "import", "job_id": "", "prompt": label})
    except media_plane.MediaError as e:
        raise uhp_error(400, "import_refused", str(e)) from e

    # ON THE CANVAS, IN THE SAME CALL. Media that is only in the store is invisible: the agent's
    # one view of a video is describe_canvas, and it said so itself when a reference was imported
    # and not placed — "it exists as media but was never put on the board". Doing it here also
    # removes a race the browser could not win, since the agent reads the canvas within seconds
    # of the session existing. `?place=0` for a caller that wants the bytes and nothing else.
    element_id = ""
    if str(request.query_params.get("place") or "1") not in ("0", "false", "no"):
        med = rec["media_id"]

        def mutate(scene: dict) -> None:
            els = scene.get("elements") or []
            x, y = media_plane.next_free([e for e in els if not e.get("isDeleted")])
            el = media_plane.media_element(
                rec["kind"], x=x, y=y, w=media_plane.TILE_W, h=media_plane.TILE_H,
                media_id=med, status="ready", cap="import", label=label,
                seconds=float(rec.get("seconds") or 0),
                width=int(rec.get("width") or 0), height=int(rec.get("height") or 0),
                media_url=_media_url(hid, str(entry.get("id") or eid), sid, med))
            if rec["kind"] == "image":
                scene.setdefault("files", {})[med] = media_plane.file_entry(
                    med, str(rec.get("mime") or "image/png"),
                    _media_url(hid, str(entry.get("id") or eid), sid, med))
            els.append(el)
            scene["elements"] = els
            return el["id"]

        _rev, element_id = await _media_scene_touch(sid, mutate)

    return {"media_id": rec["media_id"], "kind": rec["kind"], "mime": rec["mime"],
            "bytes": rec["bytes"], "width": rec["width"], "height": rec["height"],
            "seconds": rec["seconds"], "element_id": element_id or None}


@app.get("/v1/harnesses/{hid}/servers/{eid}/sessions/{sid}/media/{med}")
async def get_media_bytes(hid: str, eid: str, sid: str, med: str, request: Request) -> Response:
    """The bytes, with Range support.

    Range is not a nicety: without it Safari refuses to play at all and a timeline cannot scrub.
    The media id is immutable, so it is its own ETag and may be cached forever.
    """
    await _media_route(hid, sid, eid, request)
    meta = await _media_meta(sid, med)
    if not meta:
        raise uhp_error(404, "media_not_found", "No media with that id in this video.", "med")
    data = await _blob_get(_media_blob(sid, med, str(meta.get("ext") or "bin")), kb=BLOB_KB)
    if data is None:
        raise uhp_error(404, "media_not_found", "No media with that id in this video.", "med")
    mime = str(meta.get("mime") or "application/octet-stream")
    headers = {"accept-ranges": "bytes", "etag": f'"{med}"',
               "cache-control": "private, max-age=31536000, immutable"}
    rng = request.headers.get("range") or ""
    m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip()) if rng else None
    if m and (m.group(1) or m.group(2)):
        total = len(data)
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else total - 1
        else:                                   # bytes=-N — the last N bytes
            start, end = max(0, total - int(m.group(2))), total - 1
        if start >= total:
            return Response(status_code=416, headers={**headers,
                                                      "content-range": f"bytes */{total}"})
        end = min(end, total - 1)
        return Response(content=data[start:end + 1], status_code=206, media_type=mime,
                        headers={**headers, "content-range": f"bytes {start}-{end}/{total}",
                                 "content-length": str(end - start + 1)})
    return Response(content=data, media_type=mime, headers=headers)


# ── what launch provisions ────────────────────────────────────────────────────────────────────
def _kit_launch_media(kit: dict) -> dict | None:
    """What this kit needs provisioned at launch: an entry pointing at the media server we host.

    Unlike a database this collects NOTHING from the person. The provider credential is this
    deployment's own integration and must never become a per-harness secret — so the record holds
    only the binding, which is what _hosted_resolve checks, and holds no secret at all.
    """
    d = ((kit.get("harness") or {}).get("launch") or {}).get("media")
    if not isinstance(d, dict):
        return None
    return {"name": str(d.get("name") or "media"), "id": str(d.get("id") or "mcp.media")}


async def _hosted_media_attach(org: str, hid: str, v: dict | None, decl: dict) -> None:
    origins = _own_origins()
    if not origins:
        raise uhp_error(501, "gateway_address_not_configured",
                        "This server has no address an agent could reach it on — set "
                        "HARNESS_PUBLIC_BASE_URL.", "media")
    cur = _mcp_list(v)
    prev = next((e for e in cur if str(e.get("id") or "") == decl["id"]), None) or {}
    prev_key = _vault_key(prev.get("auth"))
    key = (prev_key if prev_key.startswith(_HOSTED_SECRET_PREFIX)
           else _hosted_secret_key(hid, decl["id"]))
    # No secret in it, so no passphrase is demanded to write it: this record is a binding and
    # nothing else, and the provider key it does NOT contain lives in the integrations document.
    await _hosted_put_record(org, key, {"server": _MEDIA_SERVER, "harness": hid,
                                        "updated_at": int(time.time() * 1000)},
                             secret=False, param="media")
    entry = {"id": decl["id"], "name": str(prev.get("name") or decl["name"]),
             "url": origins[0] + _HOSTED_MCP_PREFIX + _MEDIA_SERVER, "transport": "http",
             "auth": f"vault:{key}",
             "enabled": str(prev.get("enabled", True)) not in ("False", "false", "0")}
    await _mcp_write(hid, [e for e in cur if str(e.get("id") or "") != decl["id"]] + [entry])
    print(f"[media] {hid}: media tools attached", flush=True)


async def _media_harness_purge(hid: str) -> None:
    """Deleting the agent stops the jobs it started. Called from the one place that deletes a
    harness, so there is no second answer to 'is it gone'.

    The same method _media_session_purge already uses, because it is the same problem: the sweeper
    finds work by STATUS, so the only thing that stops a job is no longer being running. Without
    it, DELETE returned 200 and the sweeper carried on — provider calls carrying the key, and a
    finished file written into the store, for an agent that no longer existed.

    Only the jobs still running. A finished one is the record of a clip that is still in the
    session's canvas, and the sessions outlive the agent that made them.
    """
    with contextlib.suppress(Exception):
        for row in await BACKING.graph.find(_MEDIA_JOB_LABEL, {"harness": hid,
                                                               "status": "running"}):
            job = _media_job_out(row) or {}
            if not job.get("id"):
                continue
            await _vg_upsert(_MEDIA_JOB_LABEL, job["id"], {"deleted": "1", "status": "deleted"})
            # A placeholder that spins forever is a lie the canvas keeps telling.
            with contextlib.suppress(Exception):
                await _media_element_failed(job)


async def _media_session_purge(sid: str) -> None:
    """Deleting the video deletes its media and tombstones its jobs. Called from the one place
    that deletes a session, so there is no second answer to 'is it gone'."""
    with contextlib.suppress(Exception):
        for it in await _blob_list_all(f"media/{sid}/", kb=BLOB_KB):
            await _blob_delete(str(it.get("file_id") or ""), kb=BLOB_KB)
    with contextlib.suppress(Exception):
        await _blob_delete(_media_scene_key(sid), kb=BLOB_KB)
    with contextlib.suppress(Exception):
        for job in await _media_jobs_of(sid):
            await _vg_upsert(_MEDIA_JOB_LABEL, job["id"], {"deleted": "1", "status": "deleted"})


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
        print(f"[kits] {len(out)} available: {', '.join(out)}", flush=True)
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


def _kit_launch_database(kit: dict) -> dict | None:
    """What this kit's LAUNCH DIALOG must collect, from its own kit.json (`harness.launch`).

    A statement about launch, not an mcp_servers entry: a kit that reads a database is asked for
    one before anything is provisioned, because every panel it builds would otherwise have nothing
    to read. Declaring it is what makes it required, so there is no `required` field to disagree
    with. `engines` narrows the picker and is a list rather than a flag, so adding a warehouse
    later is a change to this server and to a kit's manifest and to nothing else.
    """
    d = ((kit.get("harness") or {}).get("launch") or {}).get("database")
    if not isinstance(d, dict):
        return None
    declared = [e for e in (d.get("engines") or []) if e in sql_plane.ENGINES]
    return {"engines": declared or list(sql_plane.ENGINES),
            "name": str(d.get("name") or "database"),
            "id": str(d.get("id") or "mcp.database")}


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
    "pi": {
        "label": "Pi", "backend": "pi", "status": "ready",
        "system_prompt": ("You are Pi, a minimal autonomous coding agent. You operate on a real "
                          "git workspace, reading, writing and editing files and running bash "
                          "to complete the task end to end."),
        # Pi's four built-in tools, by their real names — -xt enforces these hard, so a disabled
        # tool is genuinely absent, not merely requested (see _build_pi in the runner).
        "tools": [("bash", "Bash"), ("read", "File Read"), ("write", "File Write"),
                  ("edit", "Edit")],
        "tool_enforcement": "hard",
    },
    "dsh": {
        "label": "DeepSeek Harness", "backend": "dsh", "status": "ready",
        # MCP note: the pinned runtime wheel (0.1.0rc7) does not bundle dsh's MCP client yet,
        # so configured MCP servers are announced-and-skipped per turn (see dsh_driver.py).
        # The runner flips DSH_RUNTIME_HAS_MCP when the pin moves to a build that ships it.
        "system_prompt": ("You are DeepSeek Harness, an autonomous coding agent. You work on a "
                          "real git workspace, running shell commands and editing files to "
                          "complete the task end to end."),
        # The bundled runtime's model-facing tools. No per-tool switch exists on the wire, so
        # disabling is an instruction to the model, the same standing as codex/hermes.
        "tools": [("bash", "Bash"), ("read", "File Read"), ("write", "File Write"),
                  ("edit", "Edit"), ("todo_write", "Todo"), ("subagent", "Subagent")],
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
            # Verbatim: what a client reads is what is stored, for every entry, which is the
            # ordinary contract and the only one there now is.
            "mcpServers": _mcp_list(v), "skills": _parse(v.get("skills")),
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


def _mcp_servers_prepare(incoming: list | None) -> list[dict]:
    """Normalise mcp_servers at config time (the same bar _skills_prepare holds skills to).

    ONE RULE FOR EVERY ENTRY, including the ones this gateway hosts itself. An entry the caller
    did not send is gone — there is no keep-if-omitted exemption, because keeping one requires
    knowing which entries are special, which is the parallel path this replaced. The record behind
    a removed entry is scrubbed rather than orphaned (see _hosted_scrub_removed); a stale tab's
    Save can therefore disconnect a database, and the fix for that is optimistic concurrency for
    ALL entries rather than an exemption for one.
    """
    out: list[dict] = []
    for i, s in enumerate(incoming or []):
        if not isinstance(s, dict):
            raise uhp_error(400, "invalid_mcp_server", f"mcp_servers[{i}]: must be an object.", "mcp_servers")
        if not s.get("url"):
            raise uhp_error(400, "invalid_mcp_server", f"mcp_servers[{i}]: url required.", "mcp_servers")
        out.append(s)
    # Two servers with the same sanitised name are ONE server to every backend — the runner keys
    # them by name and the last wins, so half the tool list would vanish with no error.
    names: dict[str, str] = {}
    for e in out:
        nm = _mcp_name(str(e.get("name") or "mcp"))
        if nm in names:
            raise uhp_error(400, "duplicate_server_name",
                            f"'{e.get('name')}' and '{names[nm]}' are the same server to an agent "
                            f"— give one of them a different name.", "mcp_servers")
        names[nm] = str(e.get("name") or "")
    return out


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
    body.mcp_servers = _mcp_servers_prepare(body.mcp_servers)
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
    items = [_harness_out(await _mcp_migrate(org, str(r.get("id") or ""), r)) for r in rows
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
    return _harness_out(await _mcp_migrate(org, hid, v))


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
    cur = await _mcp_migrate(org, hid, cur)
    # coalesce-upsert: created_at/org are untouched (only the provided props are set)
    body.mcp_servers = _mcp_servers_prepare(body.mcp_servers)
    body.skills = await _skills_prepare(body.skills)
    await _vg_upsert("Harness", hid, {**_harness_props(body), "updated_at": str(int(time.time() * 1000))})
    # AFTER the write: _harness_props can still refuse this save (an unsupported base), and a
    # refused save that had already scrubbed a record would disconnect a database nobody removed.
    await _hosted_scrub_removed(org, hid, _mcp_list(cur), body.mcp_servers)
    v = await _vertex_get(hid)
    return _harness_out(v or {"id": hid})


@app.delete("/v1/orgs/{org}/harnesses/{hid}")
async def delete_harness(org: str, hid: str, request: Request) -> dict:
    await _owned_org(request, org)
    # V1C02-005: only delete a harness that belongs to the caller's org.
    cur = await _vertex_get(hid)
    if not cur or str(cur.get("org") or "") != org:
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    cur = await _mcp_migrate(org, hid, cur)
    await _vg_upsert("Harness", hid, {"deleted": "1"})
    # a deleted agent must not still be holding a database password, and must not still be
    # spending at a provider
    await _hosted_scrub_removed(org, hid, _mcp_list(cur), [])
    await _media_harness_purge(hid)
    return {"id": hid, "deleted": True}


# ── workspaces: the DIRECTORY, server-side (fix for the localStorage split-brain) ──────
# Harnesses, tasks and keys were always stamped with a workspace id in the store — but the
# REGISTRY of workspaces (id, name, description) had no server-side home on self-host: the
# console served it from each browser's localStorage. Two laptops on one instance therefore
# saw two different workspace lists, and records stamped with a workspace one browser had
# never minted were unreachable from it. The registry now lives with the stamps. Hosted keeps
# its Spaces service; these routes are what the console's existing /v1/hr/workspaces calls
# expect, same shapes, so the provider and switcher are unchanged.
_WORKSPACE_DEFAULT_ID = "default"


def _workspace_slug(name: str, taken: set[str]) -> str:
    """Same minting rules the localStorage store used, so ids stay stable across the migration
    (a browser-minted 'research' and a server-minted 'research' must be the same workspace)."""
    base = re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())) or "workspace"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _workspace_out(v: dict) -> dict:
    return {"id": str(v.get("ws_id") or ""), "name": str(v.get("name") or "Untitled"),
            "description": str(v.get("description") or "")}


async def _workspace_rows(org: str) -> list[dict]:
    rows = [v for v in await _vg_list_by_org("Workspace", org)
            if str(v.get("deleted") or "0") != "1"]
    rows.sort(key=lambda v: (str(v.get("ws_id")) != _WORKSPACE_DEFAULT_ID,
                             str(v.get("created_at") or "")))
    return rows


@app.get("/v1/hr/workspaces")
async def workspaces_list(request: Request) -> dict:
    org, member = await _pub_org_member(request)
    rows = await _workspace_rows(org)
    if not any(str(v.get("ws_id")) == _WORKSPACE_DEFAULT_ID for v in rows):
        # Ensured idempotently on read, exactly as the hosted engine does — which also lazily
        # backfills instances that predate server-side workspaces.
        props = {"kind": "workspace", "org": org, "member": member,
                 "ws_id": _WORKSPACE_DEFAULT_ID, "name": "Default Workspace",
                 "description": "All harnesses and tasks on this instance.",
                 "created_at": str(int(time.time() * 1000)), "deleted": "0"}
        await _vg_upsert("Workspace", f"ws.{org}.{_WORKSPACE_DEFAULT_ID}", props)
        rows = [props] + rows
    return {"workspaces": [_workspace_out(v) for v in rows],
            "default_workspace_id": _WORKSPACE_DEFAULT_ID}


class WorkspaceBody(BaseModel):
    name: str | None = None
    description: str | None = None
    id: str | None = None   # migration only: adopt a browser-minted id verbatim


@app.post("/v1/hr/workspaces")
async def workspaces_create(body: WorkspaceBody, request: Request) -> dict:
    org, member = await _pub_org_member(request)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "a workspace needs a name")
    rows = await _workspace_rows(org)
    taken = {str(v.get("ws_id")) for v in rows} | {_WORKSPACE_DEFAULT_ID}
    if body.id:
        # Migration path: the console pushes localStorage-era workspaces up with their exact
        # browser-minted ids so existing stamped records reattach. An id that is already here
        # is simply that workspace (idempotent merge), never a duplicate.
        wid = re.sub(r"[^a-z0-9-]", "", body.id.strip().lower())[:64]
        if not wid:
            raise HTTPException(400, "invalid workspace id")
        if wid in taken:
            existing = next((v for v in rows if str(v.get("ws_id")) == wid), None)
            if existing is not None:
                return _workspace_out(existing)
            return {"id": wid, "name": "Default Workspace", "description": ""}
    else:
        wid = _workspace_slug(name, taken)
    props = {"kind": "workspace", "org": org, "member": member, "ws_id": wid, "name": name,
             "description": (body.description or "").strip(),
             "created_at": str(int(time.time() * 1000)), "deleted": "0"}
    await _vg_upsert("Workspace", f"ws.{org}.{wid}", props, raise_on_fail=True)
    return _workspace_out(props)


@app.patch("/v1/hr/workspaces/{wid}")
async def workspaces_update(wid: str, body: WorkspaceBody, request: Request) -> dict:
    org, _member = await _pub_org_member(request)
    rows = await _workspace_rows(org)
    v = next((r for r in rows if str(r.get("ws_id")) == wid), None)
    if v is None:
        raise HTTPException(404, "workspace not found")
    if body.name is not None and body.name.strip():
        v["name"] = body.name.strip()
    if body.description is not None:
        v["description"] = body.description.strip()
    await _vg_upsert("Workspace", f"ws.{org}.{wid}", v, raise_on_fail=True)
    return _workspace_out(v)


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
    body.mcp_servers = _mcp_servers_prepare(body.mcp_servers)
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
    # Manifest order, NOT alphabetical. kits.json lists the kits in the order the catalogue wants
    # them shown, install-kits.sh bundles them in that order, and _kits() builds its dict by
    # walking the manifest — so the intent survives all the way here and sorting threw it away.
    # A catalogue that cannot decide what a newcomer sees first is a catalogue in name only, and
    # "add a second file to specify the order" would be a second source of truth for something
    # kits.json already says.
    for kid, kit in _kits().items():
        h = by_kit.get(kid)
        row = {"id": kid, "object": "kit",
                    "title": kit.get("title") or kid,
                    "tagline": kit.get("tagline") or "",
                    "description": kit.get("description") or "",
                    "icon": kit.get("icon") or "", "accent": kit.get("accent") or "",
                    # The kit's own mark, when it ships one (install-kits.sh puts it beside the
                    # app). Reported as a URL rather than inlined: it is an image, the route that
                    # serves the kit's app serves it already, and inlining markup from a file into
                    # a page is a habit worth not having. `icon` remains the fallback.
                    "iconUrl": (f"/kits/{kid}/icon.svg"
                                if (pathlib.Path(_KITS_DIR) / kid / "app" / "icon.svg").is_file()
                                else ""),
                    "route": (kit.get("app") or {}).get("route") or "",
                    "launched": bool(h),
                    "harnessId": (h or {}).get("id") or None,
                    # What the kit actually installs, from its own config — so the card can say
                    # what you get instead of asking you to take it on trust.
                    "skills": [str(n) for n in ((kit.get("harness") or {}).get("skills") or [])],
                    # What a LAUNCHED kit is really running on. Not the same thing as the
                    # recommendation: the person may have chosen differently at launch, or changed
                    # it since. Showing the recommendation for a running kit would state something
                    # about their setup that is not true.
                    "runningOn": ({"base": str(h.get("base") or ""),
                                   "model": str(h.get("default_model") or "")} if h else None),
                    # What to run it on: this kit's own recommended pairings, each marked with
                    # whether the caller's integrations can serve it. The launch dialog renders
                    # these directly and preselects the one flagged `recommended`.
                    "choices": await _kit_choices(org, kit)}
        # Two facts, both about the KIT: that it reads a database, and which engines it takes. What
        # a launched one is pointed AT is deliberately absent — nobody reads their data on this
        # page, and the surface where they do names it from the server that owns the connection.
        decl = _kit_launch_database(kit)
        if decl:
            row["database"] = {"engines": decl["engines"]}
        out.append(row)
    return {"kits": out}


class KitDatabaseBody(BaseModel):
    """The connection a kit that reads a database is launched with. `sample_rows` defaults ON:
    with it on the agent sees a few real rows per table and can tell a status column from a
    category one; with it off it sees names and types and not one row of business data."""
    engine: str
    connection_string: str
    sample_rows: bool = True


class KitLaunchBody(BaseModel):
    """What to run the kit on, and what it runs against.

    A kit that declares `harness.launch.database` collects the connection HERE, at launch, so the
    first thing the person sees is their own data — and so that connecting a database is something
    the kit that reads one drives rather than something the tool list exposes. Relaunching with a
    connection string is how you reconnect after a password change.
    """
    base: str = ""
    model: str = ""
    database: KitDatabaseBody | None = None


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

    decl = _kit_launch_database(kit)
    media_decl = _kit_launch_media(kit)
    db_in = body_in.database if body_in else None
    if db_in and not decl:
        raise uhp_error(400, "connection_not_used",
                        f"The '{kit_id}' kit does not read a database.", "database")
    # Checked before anything is provisioned: a typo in a connection string should cost the person
    # a corrected form, not a half-configured Harness to find and fix.
    checked = await _db_validate(db_in.engine, db_in.connection_string) if db_in else None

    existing = next((r for r in await _vg_list_by_org("Harness", org)
                     if str(r.get("kit") or "") == kit_id and str(r.get("deleted") or "0") != "1"),
                    None)
    if decl and not db_in and not existing:
        # Declaring launch.database is what makes it required: every panel this kit builds would
        # have nothing to read, so a launch without a connection is not a partial success.
        raise uhp_error(400, "connection_required",
                        "This kit reads a database. Give it a connection string to launch it.",
                        "database")

    if existing:
        hid0 = str(existing.get("id") or "")
        # Someone who typed a connection string and pressed Launch means "connect this", whether
        # or not the Harness already existed — which is also how you reconnect after a password
        # change. Without one the existing connection is left alone.
        if decl:
            # The tool comes from the kit definition, so a harness launched before this existed —
            # or one whose connection never landed — gets it on the next press of Launch.
            existing = await _mcp_migrate(org, hid0, existing) or existing
            await _hosted_db_entry(hid0, existing, decl)
            existing = await _vertex_get(hid0) or existing
        if db_in:
            await _hosted_db_attach(org, hid0, existing, decl, checked, db_in.sample_rows)
            existing = await _vertex_get(hid0) or existing
        if media_decl:
            # Idempotent, like the database one: pressing Launch twice must leave one entry and
            # one record, not two of each.
            await _hosted_media_attach(org, hid0, existing, media_decl)
            existing = await _vertex_get(hid0) or existing
        return {"kit": kit_id, "harnessId": hid0,
                "route": (kit.get("app") or {}).get("route") or "", "created": False,
                "harness": _harness_out(existing)}

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
    body.mcp_servers = _mcp_servers_prepare(body.mcp_servers)
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
    v = {"id": hid, **props}
    if decl:
        await _hosted_db_entry(hid, v, decl)
        v = await _vertex_get(hid) or v
    if db_in:
        await _hosted_db_attach(org, hid, v, decl, checked, db_in.sample_rows)
        v = await _vertex_get(hid) or v
    if media_decl:
        await _hosted_media_attach(org, hid, v, media_decl)
        v = await _vertex_get(hid) or v
    print(f"[kits] launched {kit_id} -> {hid}", flush=True)
    return {"kit": kit_id, "harnessId": hid,
            "route": (kit.get("app") or {}).get("route") or "", "created": True,
            "harness": _harness_out(v)}


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
    items = [_harness_out(await _mcp_migrate(org, str(r.get("id") or ""), r)) for r in rows
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
    return _harness_out(await _mcp_migrate(org, hid, v))


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
    v = await _mcp_migrate(org, hid, v)
    body.mcp_servers = _mcp_servers_prepare(body.mcp_servers)
    body.skills = await _skills_prepare(body.skills)
    await _vg_upsert("Harness", hid, {**_harness_props(body), "updated_at": str(int(time.time() * 1000))})
    # AFTER the write: see update_harness.
    await _hosted_scrub_removed(org, hid, _mcp_list(v), body.mcp_servers)
    return _harness_out(await _vertex_get(hid) or {"id": hid})


@app.delete("/v1/harnesses/{hid}")
async def delete_harness_public(hid: str, request: Request) -> dict:
    org, _ = await _pub_org_member(request)
    v = await _vertex_get(hid)
    if not v or v.get("org") != org:
        raise uhp_error(404, "harness_not_found", "No harness with that id.", "harness_id")
    v = await _mcp_migrate(org, hid, v)
    await _vg_upsert("Harness", hid, {"deleted": "1"})
    # a deleted agent must not still be holding a database password, and must not still be
    # spending at a provider
    await _hosted_scrub_removed(org, hid, _mcp_list(v), [])
    await _media_harness_purge(hid)
    return {"id": hid, "deleted": True}
