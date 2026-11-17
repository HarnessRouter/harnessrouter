"""The session-router: affinity, health, reassignment, and pass-through fidelity.

Every test builds its own app with `create_app`, explicit parameters, no environment and no
background health loop (the ASGI test transport never runs a lifespan) — the sweep is invoked
through the `sweep_now` hook the factory hangs on app.state. Fake runners are plain ASGI apps
the router's outbound client reaches through a demultiplexing transport, so the tests are
hermetic: no sockets, no ports, no timing races. A runner marked dead is dead because the test
aged its last_ok, not because a socket timed out.
"""
import asyncio
import json
import pathlib
import sqlite3
import sys
import time

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import server as router  # noqa: E402


# ── fake runners ────────────────────────────────────────────────────────────────
def _fake_runner(routes: dict, state: dict | None = None):
    """A minimal ASGI app standing in for a runner. Routes map path -> handler(scope, body,
    state) -> (payload, status). `state` is a mutable dict tests read afterwards to assert
    what the runner actually received."""

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        body = b""
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                body += msg.get("body", b"")
                if not msg.get("more_body"):
                    break
            elif msg["type"] == "http.disconnect":
                return
        handler = routes.get(scope["path"], routes.get("*"))
        if handler is None:
            payload, status = {"detail": "not found"}, 404
        else:
            payload, status = handler(scope, body, state if state is not None else {})
        data = json.dumps(payload).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"x-git-head", b"testhead")]})
        await send({"type": "http.response.body", "body": data})

    return app


class _Demux(httpx.AsyncBaseTransport):
    """Route the router's outbound calls to a fake runner by host name: a -> apps[0], b -> 1."""

    def __init__(self, apps):
        self.apps = apps

    async def handle_async_request(self, request):
        host = request.url.host or ""
        app = self.apps[{"a": 0, "b": 1, "c": 2}.get(host, 0)]
        await request.aread()               # the proxy streams; a fake needs the whole body
        query = request.url.query
        if isinstance(query, str):
            query = query.encode()
        scope = {"type": "http", "method": request.method, "path": request.url.path,
                 "query_string": query,
                 "headers": [(k.lower().encode(), v.encode()) for k, v in request.headers.items()]}

        async def receive():
            return {"type": "http.request", "body": request.content, "more_body": False}

        sent = {"start": None, "body": b""}

        async def send(msg):
            if msg["type"] == "http.response.start":
                sent["start"] = msg
            elif msg["type"] == "http.response.body":
                sent["body"] += msg.get("body", b"")

        try:
            await app(scope, receive, send)
        except OSError as e:
            # A real socket failure surfaces here as httpx.ConnectError; the fake raises OSError.
            raise httpx.ConnectError(str(e), request=request) from e
        start = sent["start"] or {"status": 500, "headers": []}
        return httpx.Response(status_code=start["status"], headers=start["headers"],
                              content=sent["body"], request=request)


def _mk_router(tmp_path, apps, *, key=None, dead_after=45.0, static=None):
    def factory():
        return httpx.AsyncClient(timeout=router._CLIENT_TIMEOUT, transport=_Demux(apps))
    return router.create_app(db_path=str(tmp_path / "router.db"),
                             static_runners=static or [], key=key,
                             health_interval_s=1e9, dead_after_s=dead_after,
                             client_factory=factory)


def _runner_app(state=None):
    def hit(scope, body, st):
        st.setdefault("hits", []).append((scope["path"], scope["query_string"],
                                          body, scope["headers"]))
        if scope["path"] == "/healthz":
            return {"ok": True}, 200
        return {"ok": True, "echo": body.decode() if body else ""}, 200
    return _fake_runner({"/healthz": hit, "*": hit}, state)   # any other proxied path: recorded


A, B = "http://a:8081", "http://b:8081"


def test_dynamic_runner_requires_ready_heartbeat_and_keeps_affinity(tmp_path):
    app = _mk_router(tmp_path, [_runner_app({})], key="test-key")

    async def go():
        headers = {"x-harness-internal": "test-key"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router", headers=headers) as client:
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/readyz")).status_code == 503
            assert (await client.post("/register", json={"name": "dynamic", "url": A})).status_code == 200
            waiting = await client.post("/turn?identifier=dynamic-session", json={})
            assert waiting.status_code == 503
            assert waiting.json()["detail"]["code"] == "runner_not_ready"
            heartbeat = {"name": "dynamic", "phase": "ready", "ready": True, "accepting": True,
                         "installed_backends": ["codex"], "version": "test"}
            assert (await client.post("/heartbeat", json=heartbeat)).status_code == 200
            assert (await client.get("/readyz")).status_code == 200
            assert (await client.post("/turn?identifier=dynamic-session", json={})).status_code == 200
            assert app.state._affinity["dynamic-session"] == "dynamic"
            rows = (await client.get("/runners")).json()["runners"]
            assert rows[0]["backends"] == ["codex"]
            assert rows[0]["last_heartbeat"]
            assert (await client.post("/drain", json={"name": "dynamic"})).status_code == 200
            assert (await client.post("/turn?identifier=new-session", json={})).status_code == 503
            assert app.state._affinity["dynamic-session"] == "dynamic"

    asyncio.run(go())


def test_drain_persists_and_readiness_tracks_available_runners(tmp_path):
    async def go():
        app = _mk_router(tmp_path, [_runner_app({})], static=[("a", A)])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as c:
            assert (await c.post("/drain", json={"name": "a", "capacity": 2})).status_code == 200
            assert (await c.get("/readyz")).status_code == 503
            assert (await c.post("/turn?identifier=new", json={})).status_code == 503
        app = _mk_router(tmp_path, [_runner_app({})], static=[("a", A)])
        assert app.state._runners["a"].draining
        assert app.state._runners["a"].capacity == 2
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as c:
            await c.post("/drain", json={"name": "a", "draining": False, "capacity": 2})
            assert (await c.get("/readyz")).status_code == 200
            app.state._runners["a"].active = 2
            assert (await c.post("/turn?identifier=new", json={})).status_code == 503
    asyncio.run(go())


async def _get(client, url, **kw):
    return await client.get(url, **kw)


async def _post(client, url, **kw):
    return await client.post(url, **kw)


# ── tests ───────────────────────────────────────────────────────────────────────
def test_a_session_sticks_to_the_runner_that_first_served_it(tmp_path):
    """Two calls for one identifier hit the same runner, and a second session may land on the
    other one — affinity, not round-robin."""
    sa, sb = {}, {}
    app = _mk_router(tmp_path, [_runner_app(sa), _runner_app(sb)],
                     static=[("a", A), ("b", B)])
    seen = []

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            for _ in range(3):
                r = await _post(c, "http://router/turn?identifier=s1", json={"prompt": "hi"})
                seen.append(r.json())
            await _post(c, "http://router/turn?identifier=s2", json={})

    asyncio.run(go())
    # which runner took s1: the one whose /turn state has the hits
    assert sa.get("hits") or sb.get("hits")
    owner = sa if len(sa.get("hits", [])) == 3 else sb
    other = sb if owner is sa else sa
    assert len(owner["hits"]) == 3                      # every call for s1, one runner
    assert other["hits"]                                # s2 went to the other runner
    assert json.loads(owner["hits"][0][2]) == {"prompt": "hi"}


def test_affinity_survives_a_router_restart(tmp_path):
    """The affinity table is SQLite: a new router over the same db sends s1 back to a."""
    sa, sb = {}, {}
    db = str(tmp_path / "router.db")

    def make():
        # The SAME fake apps both times: a fresh router process would reach the same runners.
        demux = _Demux([_runner_app(sa), _runner_app(sb)])
        return router.create_app(db_path=db, static_runners=[("a", A), ("b", B)],
                                 health_interval_s=1e9,
                                 client_factory=lambda: httpx.AsyncClient(
                                     timeout=router._CLIENT_TIMEOUT, transport=demux))

    async def go():
        app1 = make()
        tr = httpx.ASGITransport(app1)
        async with httpx.AsyncClient(transport=tr) as c:
            r = await _post(c, "http://router/turn?identifier=s1", json={})
            assert r.status_code == 200
        app2 = make()                                # a fresh process would read the same db
        tr = httpx.ASGITransport(app2)
        async with httpx.AsyncClient(transport=tr) as c:
            r = await _post(c, "http://router/turn?identifier=s1", json={})
            assert r.status_code == 200

    asyncio.run(go())
    assert len(sa["hits"]) == 2 and not sb.get("hits")   # same runner before and after


def test_a_dead_owners_session_reassigns(tmp_path):
    """When a's health goes stale, s1's next call lands on b — and stays there."""
    sa, sb = {}, {}
    app = _mk_router(tmp_path, [_runner_app(sa), _runner_app(sb)],
                     static=[("a", A), ("b", B)], dead_after=45.0)

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            await _post(c, "http://router/turn?identifier=s1", json={})
            assert sa["hits"] and not sb.get("hits")
            await app.state.sweep_now()                 # both healthy: a keeps the session
            app.state._runners["a"].last_ok = time.time() - 100   # a goes stale
            r = await _get(c, "http://router/checkpoint?identifier=s1")
            assert r.status_code == 503
            assert app.state._affinity["s1"] == "a"
            r = await _post(c, "http://router/hydrate?identifier=s1", content=b"checkpoint")
            assert r.status_code == 200
            await _post(c, "http://router/turn?identifier=s1", json={})
            await _post(c, "http://router/turn?identifier=s1", json={})

    asyncio.run(go())
    assert [h[0] for h in sb["hits"]] == ["/healthz", "/readyz", "/hydrate", "/turn", "/turn"]


def test_no_alive_runner_is_a_503_that_names_itself(tmp_path):
    app = _mk_router(tmp_path, [_runner_app({})],      # a runner that answers nothing
                     static=[("a", A)], dead_after=45.0)

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            app.state._runners["a"].last_ok = 0         # stale from the start
            return await _post(c, "http://router/turn?identifier=s1", json={})

    r = asyncio.run(go())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "no_runner"


def test_a_turn_naming_an_environment_lands_on_the_layer(tmp_path):
    """The environment was built on b (its env id is pinned there); a turn on a fresh session
    whose body names it routes to b, so the layer exists where the turn runs."""
    sa, sb = {}, {}
    app = _mk_router(tmp_path, [_runner_app(sa), _runner_app(sb)],
                     static=[("a", A), ("b", B)])

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            # The gateway builds environments through the same proxy: identifier = env id.
            await _post(c, "http://router/environments/e1/build?identifier=e1", json={})
            home = sa if sa.get("hits") else sb         # tie-break: the first runner by name
            away = sb if home is sa else sa
            assert home["hits"] and not away.get("hits")
            # A brand-new session's first turn names the environment in its body.
            r = await _post(c, "http://router/turn?identifier=s9",
                            json={"prompt": "x", "environment": {"id": "e1"}})
            assert r.status_code == 200
            return home, away

    home, away = asyncio.run(go())
    assert [h[0] for h in home["hits"]] == ["/environments/e1/build", "/environments/e1/snapshot", "/turn"]
    assert not away.get("hits")


def test_hop_by_hop_headers_never_travel_but_the_key_does(tmp_path):
    st = {}
    app = _mk_router(tmp_path, [_runner_app(st)], static=[("a", A)], key="router-key")

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            r = await _post(c, "http://router/turn?identifier=s1", json={},
                            headers={"x-harness-internal": "router-key",
                                     "connection": "keep-alive", "content-type": "application/json"})
            return r

    r = asyncio.run(go())
    assert r.status_code == 200
    headers = st["hits"][0][3]
    names = [(k if isinstance(k, str) else k.decode()).lower() for k, _ in headers]
    # The gateway's key travels; the inbound connection header was dropped (httpx adds its own
    # single connection header on the wire, as any HTTP client does), and content-length was
    # recomputed rather than copied — no doubled hop-by-hop values from the inbound request.
    assert "x-harness-internal" in names
    assert names.count("connection") == 1
    assert names.count("content-length") == 1


def test_without_the_key_the_router_refuses(tmp_path):
    app = _mk_router(tmp_path, [_runner_app({})], static=[("a", A)], key="router-key")

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            r1 = await _post(c, "http://router/turn?identifier=s1", json={})
            r2 = await _post(c, "http://router/turn?identifier=s1", json={},
                             headers={"x-harness-internal": "router-key"})
            return r1, r2

    r1, r2 = asyncio.run(go())
    assert r1.status_code == 401
    assert r2.status_code == 200


def test_a_dead_runner_answers_502_not_a_hang(tmp_path):
    """A connect failure is a fast 502 — the gateway's ladder retries, the sweep reassigns."""

    async def raising(scope, receive, send):
        raise OSError("connection refused")

    app = _mk_router(tmp_path, [raising], static=[("a", A)])

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            return await _post(c, "http://router/turn?identifier=s1", json={})

    r = asyncio.run(go())
    assert r.status_code == 502


def test_dynamic_registration_and_its_409s(tmp_path):
    sa, sb = {}, {}
    app = _mk_router(tmp_path, [_runner_app(sa), _runner_app(sb)],
                     static=[("a", A)])

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            r_dup = await _post(c, "http://router/register", json={"name": "a", "url": "http://b:9"})
            r_ok = await _post(c, "http://router/register", json={"name": "b", "url": B})
            r_bad = await _post(c, "http://router/register", json={"name": "c", "url": "not a url"})
            r = await _post(c, "http://router/turn?identifier=s1", json={})
            r_off = await _post(c, "http://router/deregister", json={"name": "b"})
            r_after = await _post(c, "http://router/turn?identifier=s1", json={})
            return r_dup, r_ok, r_bad, r, r_off, r_after

    r_dup, r_ok, r_bad, r, r_off, r_after = asyncio.run(go())
    assert r_dup.status_code == 409                     # static runners are env-owned
    assert r_ok.status_code == 200
    assert r_bad.status_code == 400
    assert r.status_code == 200
    assert r_off.status_code == 200
    assert r_after.status_code == 200                   # reassigned to a, served anyway


def test_health_and_listing_endpoints(tmp_path):
    app = _mk_router(tmp_path, [_runner_app({})], static=[("a", A)])

    async def go():
        tr = httpx.ASGITransport(app)
        async with httpx.AsyncClient(transport=tr) as c:
            h = await _get(c, "http://router/healthz")
            ls = await _get(c, "http://router/runners")
            return h.json(), ls.json()

    h, ls = asyncio.run(go())
    assert h["ok"] and h["runners"] == 1 and h["alive"] == 1
    assert ls["runners"][0]["name"] == "a" and ls["runners"][0]["static"] is True


def test_hydrate_and_turn_follow_the_environment_before_session_assignment(tmp_path):
    sa, sb = {}, {}
    app = _mk_router(tmp_path, [_runner_app(sa), _runner_app(sb)],
                     static=[("a", A), ("b", B)])

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as c:
            await c.post("/environments/e1/build?identifier=e1", json={})
            r = await c.post("/hydrate?identifier=s1&environment=e1", content=b"checkpoint")
            assert r.status_code == 200
            r = await c.post("/turn?identifier=s1", json={"environment": {"id": "e1"}})
            assert r.status_code == 200
    asyncio.run(go())
    assert [h[0] for h in sa["hits"]] == ["/environments/e1/build", "/environments/e1/snapshot", "/hydrate", "/turn"]
    assert not sb.get("hits")


def test_turn_cannot_move_an_already_hydrated_workspace(tmp_path):
    sa, sb = {}, {}
    app = _mk_router(tmp_path, [_runner_app(sa), _runner_app(sb)],
                     static=[("a", A), ("b", B)])

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as c:
            await c.post("/environments/e1/build?identifier=e1", json={})
            await c.post("/hydrate?identifier=s1", content=b"checkpoint")
            r = await c.post("/turn?identifier=s1", json={"environment": {"id": "e1"}})
            assert r.status_code == 409
            assert app.state._affinity["s1"] == "b"
            await c.post("/hydrate?identifier=s1&environment=e1", content=b"checkpoint")
            r = await c.post("/turn?identifier=s1", json={"environment": {"id": "e1"}})
            assert r.status_code == 200
    asyncio.run(go())
    assert [h[0] for h in sb["hits"]] == ["/hydrate"]


def test_failed_migration_stays_blocked_across_router_restart(tmp_path):
    sa, sb = {}, {}
    fail = {"value": True}

    def hit(scope, body, st):
        st.setdefault("paths", []).append(scope["path"])
        return {"ok": not fail["value"]}, 500 if fail["value"] else 200

    apps = [_runner_app(sa), _fake_runner({"*": hit}, sb)]
    app = _mk_router(tmp_path, apps, static=[("a", A), ("b", B)])

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as c:
            await c.post("/hydrate?identifier=s1", content=b"checkpoint")
            app.state._runners["a"].last_ok = 0
            r = await c.get("/checkpoint?identifier=s1")
            assert r.status_code == 503 and not sb
            r = await c.post("/hydrate?identifier=s1", content=b"checkpoint")
            assert r.status_code == 500
        restarted = _mk_router(tmp_path, apps, static=[("a", A), ("b", B)])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(restarted), base_url="http://router") as c:
            for method, path in [("GET", "checkpoint"), ("POST", "turn"), ("GET", "file")]:
                r = await c.request(method, f"/{path}?identifier=s1")
                assert r.status_code == 409
            assert sb["paths"] == ["/hydrate"]
            fail["value"] = False
            assert (await c.post("/hydrate?identifier=s1", content=b"checkpoint")).status_code == 200
            assert (await c.get("/checkpoint?identifier=s1")).status_code == 200
    asyncio.run(go())


def test_environment_owner_failure_does_not_move_the_layer(tmp_path):
    app = _mk_router(tmp_path, [_runner_app({}), _runner_app({})],
                     static=[("a", A), ("b", B)])

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as c:
            await c.post("/environments/e1/build?identifier=e1", json={})
            app.state._runners["a"].last_ok = 0
            r = await c.post("/hydrate?identifier=s1&environment=e1", content=b"checkpoint")
            assert r.status_code == 503
            assert "s1" not in app.state._affinity
            assert app.state._affinity["e1"] == "a"
    asyncio.run(go())


def test_existing_affinity_database_is_upgraded_without_losing_owners(tmp_path):
    db_path = str(tmp_path / "router.db")
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE affinity(ident TEXT PRIMARY KEY, runner TEXT NOT NULL, at REAL NOT NULL)")
        db.execute("INSERT INTO affinity VALUES('s1', 'b', 0)")
    sa, sb = {}, {}
    app = _mk_router(tmp_path, [_runner_app(sa), _runner_app(sb)],
                     static=[("a", A), ("b", B)])

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as c:
            assert (await c.get("/checkpoint?identifier=s1")).status_code == 200
            assert (await c.get("/checkpoint?identifier=unknown")).status_code == 409
    asyncio.run(go())
    assert not sa.get("hits")
    assert [h[0] for h in sb["hits"]] == ["/checkpoint"]
