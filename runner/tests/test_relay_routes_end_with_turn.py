"""A relay route ends with its turn.

A route holds the connection's key. It used to outlive the turn, so a process the agent left running held a
right to spend that key until the runner restarted, even after the operator removed the connection (measured
2026-11-03 on a real Vertex route: 200 after the turn had ended).
"""
import contextvars
import http.client
import json
import os
import pathlib
import sys
import tempfile
import threading
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

CANARY = "canary-provider-key-route-lifetime-0123456789"


def _tokens():
    return {t for t in server._HERMES_RELAY["routes"]}


def _call(tok):
    """A call the agent could make: the placeholder as its bearer, on the relay's own address."""
    conn = http.client.HTTPConnection("127.0.0.1", server._HERMES_RELAY["port"], timeout=10)
    conn.request("POST", "/v1/chat/completions", body=json.dumps({"model": "m", "messages": []}),
                 headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
    r = conn.getresponse(); r.read(); conn.close()
    return r.status


def test_every_registrar_belongs_to_the_turn_that_registered_it():
    held: list[str] = []
    ctx = server._TURN_ROUTE_TOKENS.set(held)
    try:
        made = [server._hermes_relay_route("https://a.example/v1", CANARY)[1],
                server._hermes_relay_route("https://a.example/v1", CANARY, aux=True)[1],
                server._gemini_relay_route("https://a.example", CANARY, "m", "")[1],
                server._qoder_relay_route("https://a.example", CANARY)[1],
                server._image_relay_route("https://a.example/v1", CANARY)[1],
                server._bedrock_anthropic_route("https://bedrock-runtime.us-east-1.amazonaws.com", CANARY)[1],
                server._systemone_relay_route("systemone", "https://a.example/v1", CANARY)[1],
                server._bedrock_relay_route("us-east-1", bearer=CANARY)[1]]
    finally:
        server._TURN_ROUTE_TOKENS.reset(ctx)
    assert sorted(held) == sorted(made)
    assert set(made) <= _tokens()
    server._relay_forget(held)
    assert not (set(made) & _tokens())
    assert not any(CANARY in repr(v[1]) for v in server._HERMES_RELAY["routes"].values() if isinstance(v[1], str))


def test_a_route_registered_outside_a_turn_is_recorded_against_none():
    """The turn's list is per context, so a turn being built elsewhere gets nothing of this one's."""
    other: list[str] = []
    server._TURN_ROUTE_TOKENS.set(other)
    tok = contextvars.Context().run(lambda: server._hermes_relay_route("https://a.example/v1", CANARY)[1])
    try:
        assert tok in _tokens() and other == []
    finally:
        server._relay_forget([tok])
        server._TURN_ROUTE_TOKENS.set(None)


def test_the_relay_refuses_a_route_after_it_is_forgotten():
    held: list[str] = []
    ctx = server._TURN_ROUTE_TOKENS.set(held)
    try:
        tok = server._hermes_relay_route("http://127.0.0.1:9/v1", CANARY)[1]
    finally:
        server._TURN_ROUTE_TOKENS.reset(ctx)
    assert _call(tok) == 502       # known: it tried the (closed) upstream
    server._relay_forget(held)
    assert _call(tok) == 401       # now it is any unknown token


def test_ending_one_turn_leaves_another_turns_routes():
    a, b = [], []
    for held in (a, b):
        ctx = server._TURN_ROUTE_TOKENS.set(held)
        server._hermes_relay_route("https://a.example/v1", CANARY)
        server._TURN_ROUTE_TOKENS.reset(ctx)
    server._relay_forget(a)
    assert not (set(a) & _tokens()) and set(b) <= _tokens()
    server._relay_forget(b)


def test_the_wrapper_forgets_when_the_runner_returns_and_when_it_raises():
    def _with_route():
        held = []
        ctx = server._TURN_ROUTE_TOKENS.set(held)
        server._hermes_relay_route("https://a.example/v1", CANARY)
        server._TURN_ROUTE_TOKENS.reset(ctx)
        return held
    held = _with_route()
    during = []
    assert server._routes_end_with_turn(lambda: during.append(set(held) <= _tokens()) or "ok", held)() == "ok"
    assert during == [True], "the route must work while the turn runs"
    assert not (set(held) & _tokens())
    held = _with_route()
    with pytest.raises(RuntimeError):
        server._routes_end_with_turn(lambda: (_ for _ in ()).throw(RuntimeError("boom")), held)()
    assert not (set(held) & _tokens())


# ---- through /turn, with a CLI that does not exist: what matters is the route, not the model

class _P:
    """A CLI: alive until told to finish, then exits with nothing written."""
    release = None

    def __init__(self, *a, **k):
        self.pid = os.getpid(); self.returncode = None
        r, w = os.pipe()
        self.stdout = os.fdopen(r); self._w = w
        self.stderr = None; self.stdin = None
        threading.Thread(target=self._finish, daemon=True).start()

    def _finish(self):
        _P.release.wait(20)
        self.returncode = 0
        os.close(self._w)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        _P.release.wait(20)
        return 0

    def kill(self):
        _P.release.set()

    terminate = kill
    send_signal = lambda self, *_: None
    communicate = lambda self, *a, **k: ("", "")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


BODY = {"backend": "claude", "provider": "anthropic", "model": "claude-sonnet-5.5", "prompt": "hi",
        "auth": {"api_key": CANARY, "base_url": "https://api.anthropic.com"}}


def _client(monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", False, raising=False)
    monkeypatch.setattr(server, "WORKSPACE_ROOT", tempfile.mkdtemp(prefix="hrwsroot-"), raising=False)
    return TestClient(server.app)


def _new_routes(before):
    return _tokens() - before


def _wait_gone(tokens, seconds=15):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if not (tokens & _tokens()):
            return True
        time.sleep(0.05)
    return False


def test_a_turn_holds_its_route_while_it_runs_and_drops_it_after(monkeypatch):
    _P.release = threading.Event()
    monkeypatch.setattr(server.subprocess, "Popen", _P)
    before = _tokens()
    r = _client(monkeypatch).post("/turn", params={"identifier": "hsess-route-a"}, json=BODY)
    assert r.status_code == 200, r.text[:300]
    made = _new_routes(before)
    assert made, "the turn registered no route"
    assert made <= _tokens(), "the route must live while the turn runs"
    assert not any(t in r.text for t in made)
    _P.release.set()
    assert _wait_gone(made), "the route outlived its turn"
    rec = server._turns[r.json()["turn_id"]]
    assert "routes" in rec, "the record keeps the route's flags for its usage"
    assert not any(t in json.dumps(rec.get("reasoning"), default=str) for t in made)


def test_a_turn_whose_spawn_fails_drops_its_route(monkeypatch):
    def nope(*a, **k):
        raise OSError("no such binary")
    monkeypatch.setattr(server.subprocess, "Popen", nope)
    before = _tokens()
    r = _client(monkeypatch).post("/turn", params={"identifier": "hsess-route-b"}, json=BODY)
    assert r.status_code == 200, r.text[:300]
    t0 = time.time()
    while not server._turns[r.json()["turn_id"]].get("done") and time.time() - t0 < 10:
        time.sleep(0.05)
    assert not _new_routes(before) or _wait_gone(_new_routes(before)), "a turn that never ran kept its route"


def test_a_builder_that_refuses_the_turn_leaves_no_route(monkeypatch):
    before = _tokens()
    def boom(*a, **k):
        server._hermes_relay_route("https://a.example/v1", CANARY)
        raise server.HTTPException(400, "refused")
    monkeypatch.setattr(server, "_build_claude", boom)
    r = _client(monkeypatch).post("/turn", params={"identifier": "hsess-route-c"}, json=BODY)
    assert r.status_code == 400, r.text[:300]
    assert not _new_routes(before), "a refused turn kept a route"


def test_a_retry_answered_by_the_running_turn_leaves_no_second_route(monkeypatch):
    _P.release = threading.Event()
    monkeypatch.setattr(server.subprocess, "Popen", _P)
    client = _client(monkeypatch)
    body = {**BODY, "idempotency_key": "route-dedupe-1"}
    before = _tokens()
    first = client.post("/turn", params={"identifier": "hsess-route-d"}, json=body)
    assert first.status_code == 200, first.text[:300]
    made = _new_routes(before)
    again = client.post("/turn", params={"identifier": "hsess-route-d"}, json=body)
    assert again.json().get("deduplicated") is True, again.text[:300]
    assert _new_routes(before) == made, "the retry left a route of its own"
    assert made <= _tokens(), "the retry must not end the running turn's route"
    _P.release.set()
    assert _wait_gone(made)


def test_the_remote_clean_up_of_a_session_delete_drops_its_route(monkeypatch):
    ws = tempfile.mkdtemp(prefix="hrws-")
    state = pathlib.Path(ws) / server.QODER_STATE_REL
    state.parent.mkdir(parents=True); state.write_text("{}")
    class Done:
        stdout = ""; stderr = ""; returncode = 0
    monkeypatch.setattr(server.subprocess, "run", lambda *a, **k: Done())
    before = _tokens()
    server._remote_purge(ws, server.Auth(provider="qoder", api_key=CANARY))
    assert not _new_routes(before)
