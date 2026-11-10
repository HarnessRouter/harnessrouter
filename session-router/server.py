"""session-router — one gateway, many runners.

The gateway addresses its runner through ONE base URL (POOL_MGMT_ENDPOINT) and carries the
session — or environment — identifier as `?identifier=` on every call. That contract is what
makes this proxy possible without touching the gateway: this service holds that base URL,
keeps a registry of runners, and pins every identifier to the runner that owns it.

Why a router at all: the all-in-one and split deployments put one runner beside the gateway,
and its capacity is one machine's. The hosted service scales by giving each identifier its own
sandbox from a pool (ACA Dynamic Sessions); a self-hosted cluster scales by adding runner
containers and letting this router hand each NEW identifier to the least-loaded one. Affinity
is the whole trick:

  - A turn, a file read, a produced-files listing: all stateless HTTP to the runner that OWNS
    the identifier, and the owner is a directory on that runner's volume (and, behind the
    write-wall, a uid there). Two runners answering one session's calls would be two
    half-workspaces — so every call for an identifier goes to the one runner, always.
  - The durable copy of a workspace is the checkpoint tarball in the gateway's blob store,
    restored by /hydrate on ANY runner. When a runner dies, only /hydrate may reassign a session;
    other session calls fail until its workspace is restored. A turn in flight on the
    dead runner is lost the way any machine loss loses it; nothing else is.
  - Environments ride the same affinity: every environments call carries identifier=<env id>,
    so a layer is built on (and pinned to) one runner. A turn whose body names an environment
    is routed to THAT runner. The gateway includes the environment id on /hydrate too, so the
    workspace is restored on the same box before the turn runs.

Everything else is pass-through: path, query, headers and body (streamed both ways — a GB
checkpoint never buffers here, exactly as it never buffers in the gateway, HR-INF-015). The
gateway signs its calls with X-Harness-Internal and the router forwards that header untouched;
optionally the router itself demands it first (HR_ROUTER_KEY), so only the gateway can use it.

Configured by environment variables, all optional:

  HR_RUNNERS            static registry, "name=url,name=url" — read at every start.
  HR_ROUTER_KEY         when set, proxied and register calls must carry X-Harness-Internal
                        with this value (use the gateway's HARNESS_INTERNAL_KEY).
  HR_ROUTER_DB          SQLite file for the registry (dynamic entries) and the affinity
                        table, so a router restart keeps every session on its runner.
                        Default: ./session-router.db (the container sets /data/...).
  HR_HEALTH_INTERVAL_S  seconds between health sweeps (default 10).
  HR_RUNNER_DEAD_S      a runner whose last good health check is older than this is dead and
                        its sessions reassign (default 45).

Run: python -m uvicorn server:app --host 0.0.0.0 --port 8090
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import sqlite3
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# A router in front of runners must never be the reason a turn fails: the gateway's own client
# allows an hour between body chunks (a turn may legitimately think for that long between
# events), so this hop allows the same plus a margin, and a connect timeout short enough that a
# dead runner reads as 502 — which the gateway's retry ladder treats as transient — at once.
_CLIENT_TIMEOUT = httpx.Timeout(connect=15, read=3900, write=600, pool=300)

HEALTH_INTERVAL_S = float(os.environ.get("HR_HEALTH_INTERVAL_S", "10") or 10)
DEAD_AFTER_S = float(os.environ.get("HR_RUNNER_DEAD_S", "45") or 45)
HEALTH_TIMEOUT_S = 3.0

# Only POST /turn is buffered, and only to look for an environment id in its body (see the
# docstring). A turn body carries caller files base64-encoded, so cap the buffer: past this the
# hint is skipped and plain session affinity decides, which is correct for a turn with no
# environment or one this session already used.
TURN_HINT_MAX_BYTES = 8 * 1024 * 1024

# Hop-by-hop headers never travel (RFC 9110 §7.6.1) plus the two httpx recomputes itself
# (host, content-length). Everything else — X-Harness-Internal, content-type, and on the way
# back X-Git-Head and content-disposition, both read by the gateway — is forwarded as arrived.
# A repeated response header collapses to its last value; the runner sends none that matter.
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length"}


def static_runners_from_env() -> list[tuple[str, str]]:
    """HR_RUNNERS, "name=url,name=url", in order. A malformed entry is skipped loudly rather
    than silently halving the cluster."""
    out: list[tuple[str, str]] = []
    for part in os.environ.get("HR_RUNNERS", "").split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, url = part.partition("=")
        if not (sep and name.strip() and url.strip()):
            print(f"[router] ignoring malformed HR_RUNNERS entry: {part!r}", flush=True)
            continue
        out.append((name.strip(), url.strip().rstrip("/")))
    return out


class _Runner:
    """One registered runner and the health facts that decide routability."""

    __slots__ = ("name", "url", "static", "last_ok", "last_error", "draining", "active", "capacity")

    def __init__(self, name: str, url: str, static: bool):
        self.name, self.url, self.static = name, url, static
        # Optimistic: alive until a health check says otherwise, so a fresh router serves turns
        # before its first sweep. A wrong guess costs one 502 retry at the gateway.
        self.last_ok = time.time()
        self.last_error = ""
        self.draining = False
        self.active = 0
        self.capacity = 0

    def alive(self, now: float, dead_after: float) -> bool:
        return (now - self.last_ok) <= dead_after


class RegisterBody(BaseModel):
    """POST /register body: a runner announcing itself."""

    name: str
    url: str


class DeregisterBody(BaseModel):
    """POST /deregister body: a runner leaving the registry."""

    name: str


class DrainBody(BaseModel):
    name: str
    draining: bool = True
    capacity: int = 0


class _Store:
    """SQLite persistence: dynamic registry rows and the affinity table.

    Small and synchronous, and only touched from the event loop; the lock exists for the
    general case (a threaded server), not because today's needs it. The affinity table is
    write-through — memory decides, the db survives a restart — so a restarted router puts
    every session back on the runner that owns its workspace directory.
    """

    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._db.execute("CREATE TABLE IF NOT EXISTS runner"
                             "(name TEXT PRIMARY KEY, url TEXT NOT NULL, at REAL NOT NULL)")
            self._db.execute("CREATE TABLE IF NOT EXISTS affinity"
                             "(ident TEXT PRIMARY KEY, runner TEXT NOT NULL, at REAL NOT NULL)")
            self._db.execute("CREATE INDEX IF NOT EXISTS affinity_runner ON affinity(runner)")
            self._db.execute("CREATE TABLE IF NOT EXISTS runner_policy"
                             "(name TEXT PRIMARY KEY, draining INTEGER NOT NULL, capacity INTEGER NOT NULL)")
            if "ready" not in {row[1] for row in self._db.execute("PRAGMA table_info(affinity)")}:
                self._db.execute("ALTER TABLE affinity ADD COLUMN ready INTEGER NOT NULL DEFAULT 1")
            self._db.commit()

    def runners(self) -> list[tuple[str, str]]:
        with self._lock:
            return [(n, u) for n, u in self._db.execute("SELECT name, url FROM runner")]

    def add_runner(self, name: str, url: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO runner(name, url, at) VALUES(?,?,?) "
                             "ON CONFLICT(name) DO UPDATE SET url=excluded.url, at=excluded.at",
                             (name, url, time.time()))
            self._db.commit()

    def del_runner(self, name: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM runner WHERE name = ?", (name,))
            self._db.commit()

    def affinity(self) -> dict[str, str]:
        with self._lock:
            return dict(self._db.execute("SELECT ident, runner FROM affinity"))

    def pending(self) -> set[str]:
        with self._lock:
            return {row[0] for row in self._db.execute("SELECT ident FROM affinity WHERE ready = 0")}

    def policies(self):
        return list(self._db.execute("SELECT name, draining, capacity FROM runner_policy"))

    def set_policy(self, name: str, draining: bool, capacity: int):
        self._db.execute("INSERT OR REPLACE INTO runner_policy VALUES(?,?,?)", (name, int(draining), capacity))
        self._db.commit()

    def set_affinity(self, ident: str, runner: str, ready: bool = True) -> None:
        with self._lock:
            self._db.execute("INSERT INTO affinity(ident, runner, at, ready) VALUES(?,?,?,?) "
                             "ON CONFLICT(ident) DO UPDATE SET runner=excluded.runner, at=excluded.at, ready=excluded.ready",
                             (ident, runner, time.time(), int(ready)))
            self._db.commit()


def create_app(*, db_path: str | None = None, static_runners: list[tuple[str, str]] | None = None,
               key: str | None = None, health_interval_s: float | None = None,
               dead_after_s: float | None = None,
               client_factory=None) -> FastAPI:
    """The router app. Every knob is a parameter so the module-level `app` (env-configured)
    and the tests (explicit, no env, no background loop) build the same thing."""

    db_path = db_path or os.environ.get("HR_ROUTER_DB") or "session-router.db"
    key = key if key is not None else (os.environ.get("HR_ROUTER_KEY", "").strip() or None)
    interval = float(health_interval_s if health_interval_s is not None else HEALTH_INTERVAL_S)
    dead_after = float(dead_after_s if dead_after_s is not None else DEAD_AFTER_S)
    make_client = client_factory or (lambda: httpx.AsyncClient(timeout=_CLIENT_TIMEOUT))

    store = _Store(db_path)
    runners: dict[str, _Runner] = {}
    affinity: dict[str, str] = store.affinity()
    pending = store.pending()
    snapshots = pathlib.Path(db_path).resolve().parent / (pathlib.Path(db_path).name + ".snapshots")
    snapshots.mkdir(mode=0o700, exist_ok=True)
    environment_locks: dict[str, asyncio.Lock] = {}
    client = make_client()
    stats = {"reassigned": 0, "proxied": 0}

    for name, url in (static_runners if static_runners is not None else static_runners_from_env()):
        runners[name] = _Runner(name, url, static=True)
    for name, url in store.runners():          # dynamic registrations from a previous life
        runners.setdefault(name, _Runner(name, url, static=False))
    for name, draining, capacity in store.policies():
        if name in runners:
            runners[name].draining = bool(draining)
            runners[name].capacity = capacity

    def _alive(r: _Runner, now: float) -> bool:
        return r.alive(now, dead_after)

    def _counts() -> dict[str, int]:
        out: dict[str, int] = {}
        for name in affinity.values():
            out[name] = out.get(name, 0) + 1
        return out

    def _least_loaded(now: float) -> _Runner:
        """The alive runner carrying the fewest identifiers. Ties go to the first registered —
        deterministic, so a fresh cluster's first sessions land in a stable order."""
        alive = [r for r in runners.values() if _alive(r, now) and not r.draining
                 and (not r.capacity or r.active < r.capacity)]
        if not alive:
            raise HTTPException(503, "no runner is reachable; the router has nowhere to send this")
        counts = _counts()
        return min(alive, key=lambda r: (r.active / (r.capacity or 1), counts.get(r.name, 0), r.name))

    def _pick(ident: str, hint: str | None = None, *, hydrate: bool = False,
              environment_call: bool = False, checkpoint: bool = False) -> _Runner:
        """Keep session ownership until hydrate explicitly restores it elsewhere.

        An environment hint fixes the hydrate target; turn cannot move a restored workspace.
        Environment management retains its independent affinity and reassignment policy.
        """
        now = time.time()
        hinted = None
        if hint:
            hinted = runners.get(affinity.get(hint, ""))
            if not hinted or not _alive(hinted, now):
                raise HTTPException(503, "the runner holding the environment is unavailable")
        if checkpoint and (not ident or ident not in affinity):
            raise HTTPException(409, "hydrate the session before checkpointing")
        if ident in pending and not hydrate and not environment_call:
            raise HTTPException(409, "the session must be hydrated before use")
        with_thread = None
        if ident:
            owner = affinity.get(ident)
            r = runners.get(owner) if owner else None
            if r and _alive(r, now):
                if not hinted or hinted.name == r.name:
                    return r
                if not hydrate:
                    raise HTTPException(409, "hydrate the session on its environment runner first")
            if owner and (not r or not _alive(r, now)):
                if not hydrate and not environment_call:
                    raise HTTPException(503, "session runner unavailable; hydrate before reassignment")
                with_thread = owner     # logged below, only if we actually reassign
        target = hinted
        if target is None:
            target = _least_loaded(now)
        if ident:
            old = affinity.get(ident)
            needs_restore = hydrate or (old is not None and old != target.name and not environment_call)
            store.set_affinity(ident, target.name, ready=not needs_restore)
            affinity[ident] = target.name
            if needs_restore:
                pending.add(ident)
            if with_thread and with_thread != target.name:
                stats["reassigned"] += 1
                print(f"[router] {ident}: runner {with_thread} is gone — "
                      f"reassigned to {target.name}", flush=True)
        return target

    async def _sweep() -> None:
        """One health pass over every runner. Few runners, one GET each; per-request timeout
        so one hung runner cannot stretch the sweep."""
        for r in list(runners.values()):
            try:
                resp = await client.get(f"{r.url}/healthz", timeout=HEALTH_TIMEOUT_S)
                if resp.status_code < 400:
                    r.last_ok, r.last_error = time.time(), ""
                else:
                    r.last_error = f"HTTP {resp.status_code}"
            except Exception as e:  # noqa: BLE001 — a dead runner is a health fact, not an error
                r.last_error = type(e).__name__

    @asynccontextmanager
    async def _lifespan(_app):
        task = asyncio.create_task(_health_loop())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await client.aclose()

    async def _health_loop():
        while True:
            await _sweep()
            await _snapshot_builds()
            await asyncio.sleep(interval)

    app = FastAPI(title="harness-session-router", lifespan=_lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    # ── the router's own surface ────────────────────────────────────────────────
    # Defined before the catch-all, which takes everything else.
    @app.get("/healthz")
    async def healthz() -> dict:
        now = time.time()
        alive = [r for r in runners.values() if _alive(r, now)]
        return {"ok": True, "runners": len(runners), "alive": len(alive),
                "reassigned": stats["reassigned"]}

    @app.get("/readyz")
    async def readyz():
        available = any(_alive(r, time.time()) and not r.draining for r in runners.values())
        return JSONResponse({"ok": available}, status_code=200 if available else 503)

    @app.get("/runners")
    async def list_runners() -> dict:
        now = time.time()
        counts = _counts()
        return {"runners": [{"name": r.name, "url": r.url, "static": r.static,
                             "alive": _alive(r, now), "sessions": counts.get(r.name, 0),
                             "draining": r.draining, "active": r.active, "capacity": r.capacity,
                             "last_error": r.last_error} for r in runners.values()],
                "reassigned": stats["reassigned"]}

    @app.post("/drain")
    async def drain(body: DrainBody, request: Request):
        refused = _require_key(request)
        if refused:
            return refused
        r = runners.get(body.name)
        if not r:
            raise HTTPException(404, "no such runner")
        if body.capacity < 0:
            raise HTTPException(400, "capacity must be nonnegative")
        store.set_policy(r.name, body.draining, body.capacity)
        r.draining, r.capacity = body.draining, body.capacity
        return {"ok": True, "draining": r.draining, "active": r.active}

    @app.post("/register")
    async def register(body: RegisterBody, request: Request) -> dict:
        refused = _require_key(request)
        if refused:
            return refused
        url = body.url.strip().rstrip("/")
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
            raise HTTPException(400, "url must be an http(s) address")
        name = body.name.strip()
        if not name or "/" in name:
            raise HTTPException(400, "name must be non-empty and path-free")
        if name in runners and runners[name].static:
            raise HTTPException(409, f"{name} is a static runner (HR_RUNNERS); "
                                     f"remove it from the environment instead")
        runners[name] = _Runner(name, url, static=False)
        store.add_runner(name, url)
        print(f"[router] registered {name} -> {url}", flush=True)
        return {"ok": True, "name": name, "url": url}

    @app.post("/deregister")
    async def deregister(body: DeregisterBody, request: Request) -> dict:
        refused = _require_key(request)
        if refused:
            return refused
        r = runners.get(body.name.strip())
        if not r:
            raise HTTPException(404, "no such runner")
        if r.static:
            raise HTTPException(409, f"{r.name} is a static runner (HR_RUNNERS); "
                                     f"remove it from the environment instead")
        if r.active:
            raise HTTPException(409, "runner still has active requests")
        del runners[r.name]
        store.del_runner(r.name)
        # Its affinity rows are left: a name may return (a replaced container re-registering
        # under the same name), and if it never does, each row reassigns at its next call.
        print(f"[router] deregistered {r.name}", flush=True)
        return {"ok": True, "name": r.name}

    def _require_key(request: Request) -> JSONResponse | None:
        if key and request.headers.get("x-harness-internal") != key:
            return JSONResponse({"detail": "router key required"}, status_code=401)
        return None

    # ── the proxy ───────────────────────────────────────────────────────────────
    async def _proxy(request: Request, path: str):
        refused = _require_key(request)
        if refused:
            return refused
        ident = request.query_params.get("identifier", "")
        eid = ident if path.startswith("environments/") else request.query_params.get("environment", "")
        if eid:
            if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in eid):
                return JSONResponse({"detail": "invalid environment identifier"}, status_code=400)
            async with environment_locks.setdefault(eid, asyncio.Lock()):
                try:
                    await _restore_environment(eid, request)
                    return await _proxy_request(request, path, eid)
                except (httpx.HTTPError, OSError) as e:
                    return JSONResponse({"detail": f"environment recovery failed: {type(e).__name__}"}, status_code=503)
                except HTTPException as e:
                    return JSONResponse({"detail": e.detail}, status_code=e.status_code)
        return await _proxy_request(request, path, "")

    async def _restore_environment(eid: str, request: Request):
        owner = runners.get(affinity.get(eid, ""))
        if eid not in affinity or (owner and _alive(owner, time.time())):
            return
        saved = snapshots / (eid + ".tar.gz")
        if not saved.is_file():
            raise HTTPException(503, "environment owner unavailable and no durable snapshot exists")
        target = _least_loaded(time.time())
        async def chunks():
            with saved.open("rb") as source:
                while chunk := source.read(256 * 1024):
                    yield chunk
        response = await client.post(f"{target.url}/environments/{eid}/restore", content=chunks(),
                                     headers={"x-harness-internal": request.headers.get("x-harness-internal", "")})
        if response.status_code != 200:
            raise HTTPException(503, "environment snapshot could not be restored")
        store.set_affinity(eid, target.name)
        affinity[eid] = target.name

    async def _save_environment(eid: str, target: _Runner, headers: dict):
        async with client.stream("GET", f"{target.url}/environments/{eid}/snapshot", headers=headers) as response:
            # Older runners have no snapshot endpoint. Their environments retain the
            # existing owner-only behavior until a compatible runner captures them.
            if response.status_code in (404, 409):
                return
            if response.status_code != 200:
                raise HTTPException(503, "environment snapshot could not be saved")
            if not response.headers.get("content-type", "").startswith("application/gzip"):
                return
            fd, temporary = tempfile.mkstemp(dir=snapshots)
            try:
                with os.fdopen(fd, "wb") as dest:
                    async for chunk in response.aiter_bytes():
                        dest.write(chunk)
                    dest.flush()
                    os.fsync(dest.fileno())
                os.replace(temporary, snapshots / (eid + ".tar.gz"))
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    async def _snapshot_builds():
        """Finish snapshots even when a client stops polling an asynchronous build."""
        for marker in list(snapshots.glob("*.building")):
            eid = marker.stem
            owner = runners.get(affinity.get(eid, ""))
            if owner and _alive(owner, time.time()):
                async with environment_locks.setdefault(eid, asyncio.Lock()):
                    try:
                        await _save_environment(eid, owner, {"x-harness-internal": key or ""})
                        if (snapshots / (eid + ".tar.gz")).is_file():
                            marker.unlink(missing_ok=True)
                    except (httpx.HTTPError, OSError, HTTPException):
                        pass

    async def _proxy_request(request: Request, path: str, eid: str):
        stats["proxied"] += 1
        if key and request.headers.get("x-harness-internal") != key:
            return JSONResponse({"detail": "router key required"}, status_code=401)
        ident = request.query_params.get("identifier", "")
        method = request.method
        buffered = b""
        if method == "POST" and path == "turn":
            n = int(request.headers.get("content-length") or 0)
            if 0 < n <= TURN_HINT_MAX_BYTES:
                buffered = await request.body()
        try:
            hydrate = method == "POST" and path == "hydrate"
            hint = request.query_params.get("environment") if hydrate else _env_hint(buffered)
            target = _pick(ident, hint, hydrate=hydrate,
                           environment_call=path.startswith("environments/"),
                           checkpoint=path == "checkpoint")
            if hydrate and ident:
                store.set_affinity(ident, target.name, ready=False)
                pending.add(ident)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
        url = f"{target.url}/{path}"
        if request.url.query:
            url += f"?{request.url.query}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
        if buffered:
            content = buffered
        elif method in ("POST", "PUT", "PATCH") or (
                method == "DELETE" and request.headers.get("content-length")):
            content = request.stream()      # streamed, never buffered: a GB hydrate stays a stream
        else:
            content = None
        req = client.build_request(method, url, headers=headers, content=content)
        if path == "turn" and target.capacity and target.active >= target.capacity:
            return JSONResponse({"detail": "runner turn capacity reached"}, status_code=429)
        if path == "turn" and target.draining:
            return JSONResponse({"detail": "runner is draining; retry after maintenance"}, status_code=503)
        target.active += 1
        if eid and path.startswith("environments/") and method not in ("GET", "HEAD", "OPTIONS"):
            # A mutation can succeed upstream even if its response is lost. Until its new
            # snapshot commits, recovery must fail closed instead of restoring old data.
            (snapshots / (eid + ".tar.gz")).unlink(missing_ok=True)
            (snapshots / (eid + ".building")).touch()
        try:
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            target.active -= 1
            # Fail the call without silently moving a session's workspace. A subsequent
            # hydrate can reassign once the health sweep considers the owner dead.
            return JSONResponse({"detail": f"the runner did not answer: {type(e).__name__}"},
                                status_code=502)
        except BaseException:
            target.active -= 1
            raise

        if eid and path.startswith("environments/") and resp.status_code < 300:
            try:
                if method == "DELETE" and path.count("/") == 1:
                    (snapshots / (eid + ".tar.gz")).unlink(missing_ok=True)
                    (snapshots / (eid + ".building")).unlink(missing_ok=True)
                elif not path.endswith(("/snapshot", "/restore")):
                    await _save_environment(eid, target, headers)
                    if (snapshots / (eid + ".tar.gz")).is_file():
                        (snapshots / (eid + ".building")).unlink(missing_ok=True)
            except BaseException:
                await resp.aclose()
                target.active -= 1
                raise

        if hydrate and ident and resp.status_code < 300 and affinity.get(ident) == target.name:
            store.set_affinity(ident, target.name, ready=True)
            pending.discard(ident)

        async def stream():
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()
                target.active -= 1

        rheaders = {k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP}
        # The demux-style test transport hands back a fully-read Response; a real network
        # transport hands back an unread stream. Stream when there is a stream, echo otherwise.
        if resp.is_stream_consumed:
            await resp.aclose()
            target.active -= 1
            return StreamingResponse(iter([resp.content]), status_code=resp.status_code,
                                     headers=rheaders)
        return StreamingResponse(stream(), status_code=resp.status_code, headers=rheaders)

    @app.get("/")
    async def index() -> dict:
        return {"service": "harness-session-router",
                "runners": "/runners", "proxy": "/*?identifier=<session|environment id>"}

    app.add_api_route("/{path:path}", _proxy,
                      methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])

    # Test hook: the health loop lives in the lifespan, which ASGI test transports do not run.
    app.state.sweep_now = _sweep
    app.state._runners = runners          # noqa: SLF001 — tests assert on registry state
    app.state._affinity = affinity
    return app


def _env_hint(body: bytes) -> str | None:
    """The environment id a buffered /turn body names, or None."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    env = data.get("environment") if isinstance(data, dict) else None
    if isinstance(env, dict):
        return str(env.get("id") or "").strip() or None
    return None


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
