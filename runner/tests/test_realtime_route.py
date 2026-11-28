"""The realtime base as the runner holds it: the registry entry, the route in the relay, the builder.

What these pin:

  the turn's relay route forwards the client-secret mint to the provider with the connection's
      key, and the client only ever held the placeholder
  the same placeholder opens nothing else on that key: another path, another method and a DELETE
      are refused by the relay before the key is put on anything, and never reach the provider
  the route is a pass-through: the mint's answer names the model that was ASKED for, and it is not
      recorded as a served model
  the builder registers that route, hands the driver the placeholder, and refuses a connection
      with nothing to dial before a route exists
  the registration points: the passthrough normaliser, no instruction file composed (the
      instructions travel in the job), a session probe that reads the workspace, a step budget of
      the driver's own, and not a remote backend

The driver's own behaviour is in test_realtime_driver.py, and the module's pure parts in
test_realtime_backend.py; neither imports the runner.
"""
import http.server
import json
import pathlib
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import realtime_backend as rb  # noqa: E402
import server as rs  # noqa: E402

KEY = "azure-real-key-0123456789"


class Provider:
    """The provider's API, as much as the route can reach: it records every request it is sent."""

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []          # (method, path, authorization)
        provider = self

        class H(http.server.BaseHTTPRequestHandler):
            def _answer(self):
                n = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                provider.calls.append((self.command, self.path, self.headers.get("authorization") or ""))
                if self.command == "POST" and self.path.split("?")[0].endswith("/realtime/client_secrets"):
                    out = {"value": "ek_minted", "expires_at": 2000000000,
                           "session": {"type": "realtime", "model": (body.get("session") or {}).get("model")}}
                else:
                    out = {"data": [{"id": "gpt-6.1-sol"}], "model": "gpt-6.1-sol"}
                raw = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            do_GET = do_POST = do_DELETE = _answer  # noqa: N815

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}/openai/v1"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def provider():
    p = Provider()
    yield p
    p.close()


def call(base, tok, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# ── the route ──
def test_the_route_forwards_the_mint_with_the_key_the_client_never_held(provider):
    base, tok = rs._realtime_relay_route(provider.base, KEY)
    try:
        assert tok.startswith("hr-relay-") and base.startswith("http://127.0.0.1:") and base.endswith("/v1")
        status, doc = call(base, tok, "POST", rb.MINT_PATH,
                           {"expires_after": {"anchor": "created_at", "seconds": 120},
                            "session": {"type": "realtime", "model": "gpt-realtime-2-1"}})
        assert status == 200 and doc["value"] == "ek_minted"
        assert provider.calls == [("POST", "/openai/v1/realtime/client_secrets", f"Bearer {KEY}")]
        assert tok not in json.dumps(provider.calls)
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


@pytest.mark.parametrize("method, path, body", [
    ("POST", "/chat/completions", {"model": "gpt-6.1-sol", "messages": []}),
    ("POST", "/responses", {"model": "gpt-6.1-sol", "input": "hi"}),
    ("GET", "/models", None),
    ("GET", rb.MINT_PATH, None),
    ("DELETE", rb.MINT_PATH, None),
    ("DELETE", "/files/file_1", None),
    ("POST", "/realtime/calls", {}),
    ("POST", rb.MINT_PATH + "/../chat/completions", {}),
])
def test_the_placeholder_opens_nothing_else_on_the_connections_key(provider, method, path, body):
    base, tok = rs._realtime_relay_route(provider.base, KEY)
    try:
        status, doc = call(base, tok, method, path, body)
        assert status == 403 and "does not forward" in doc["error"]
        assert provider.calls == []                 # refused in the relay: the key went nowhere
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_the_mints_answer_is_not_recorded_as_a_served_model(provider):
    """The answer's `model` is the one the request named. Through the model-call taps it would be
    stamped on the turn as what served it, and the matrix would score a substitution check on a
    model the turn has not run yet. The driver reports what the socket's session names instead."""
    base, tok = rs._realtime_relay_route(provider.base, KEY)
    try:
        assert rs._HERMES_RELAY["routes"][tok][2].get("passthrough") is True
        status, doc = call(base, tok, "POST", rb.MINT_PATH, {"session": {"type": "realtime", "model": "asked-for"}})
        assert status == 200 and doc["session"]["model"] == "asked-for"
        env = {"HR_REALTIME_KEY": tok}
        assert rs._relay_served_model(env) == "" and rs._relay_usage(env) == {} and rs._relay_last_finish(env) == ""
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_other_routes_forward_as_they_always_did(provider):
    """`only` is the realtime route's. A model route with no such limit is untouched by the check."""
    base, tok = rs._hermes_relay_route(provider.base, KEY, exact_base=True)
    try:
        assert "only" not in rs._HERMES_RELAY["routes"][tok][2]
        status, _doc = call(base, tok, "GET", "/models")
        assert status == 200 and provider.calls[-1][:2] == ("GET", "/openai/v1/models")
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


# ── the builder ──
def test_the_builder_registers_the_one_call_route_and_hands_over_a_placeholder(tmp_path):
    env: dict = {}
    auth = rs.Auth(api_key=KEY, base_url="https://res.openai.azure.com/openai/v1")
    cmd = rb.build("azure-foundry", auth, "gpt-realtime-2-1", "hi", str(tmp_path), env,
                   relay=rs._realtime_relay_route, driver_cmd=rs._driver_cmd, agent_doc="Rules.", max_turns=4)
    tok = None
    try:
        assert cmd == [rb.PYTHON, rb.DRIVER] and len(cmd) == 2      # the job rides the env: argv is every uid's to read
        job = json.loads(env["HR_DRIVER_JOB"])
        tok = job["api_key"]
        assert tok.startswith("hr-relay-") and env["HR_REALTIME_KEY"] == tok
        assert KEY not in json.dumps(cmd) + json.dumps(env)
        upstream, key, flags = rs._HERMES_RELAY["routes"][tok]
        assert upstream == "https://res.openai.azure.com/openai/v1" and key == KEY
        assert flags.get("passthrough") is True and tuple(flags["only"]) == rb.ROUTE_ONLY
        assert job["mint_url"].startswith("http://127.0.0.1:") and job["mint_url"].endswith("/v1/realtime/client_secrets")
        assert job["ws_url"] == "wss://res.openai.azure.com/openai/v1/realtime?model=gpt-realtime-2-1"
        assert job["agent_doc"] == "Rules." and job["max_turns"] == 4
    finally:
        if tok:
            rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_connection_with_nothing_to_dial_is_refused_and_leaves_no_route(tmp_path):
    before = set(rs._HERMES_RELAY["routes"])
    for auth in (rs.Auth(), rs.Auth(api_key=KEY), rs.Auth(base_url="https://res.openai.azure.com/openai/v1"),
                 rs.Auth(api_key=KEY, base_url="res.openai.azure.com")):
        with pytest.raises(rs.HTTPException) as e:
            rb.build("azure-foundry", auth, "m", "hi", str(tmp_path), {},
                     relay=rs._realtime_relay_route, driver_cmd=rs._driver_cmd)
        assert e.value.status_code == 400 and KEY not in str(e.value.detail)
    with pytest.raises(rs.HTTPException):
        rb.build("openai", rs.Auth(api_key=KEY, base_url="https://api.openai.com/v1"), "m", "hi", str(tmp_path), {},
                 relay=rs._realtime_relay_route, driver_cmd=rs._driver_cmd)       # not a provider of this base yet
    assert set(rs._HERMES_RELAY["routes"]) == before


# ── the registration points ──
def test_the_registration_points(tmp_path):
    b = rs.BACKENDS["realtime"]
    assert b["normalize"] is rs._claude_passthrough          # the driver emits claude's stream-json itself
    assert b["providers"] == sorted(rb.PROVIDERS) == ["azure-foundry"]
    assert b["default_model"] == rb.DEFAULT_MODEL == "gpt-realtime-2.1"
    assert not b.get("remote")                               # one process per turn on this box, like every local base
    # its instructions travel in the job: no workspace file is composed for it
    assert rs._compose_agent_doc(str(tmp_path), "realtime", "Be brief.", []) == ""
    # a lost session is said: the probe reads the workspace, where the driver keeps it
    assert rs._SESSION_PRESENT["realtime"] is rb.session_present
    # the step budget is the driver's own (the Realtime Harness's max_step), not the runner's counter
    assert "realtime" not in rs._GENERIC_STEP_BUDGET


def test_a_turn_that_names_a_session_whose_file_is_gone_is_told_so(tmp_path):
    (tmp_path / ".harness" / "realtime" / "rt_here").mkdir(parents=True)
    (tmp_path / ".harness" / "realtime" / "rt_here" / "items.json").write_text("[]", encoding="utf-8")
    assert rs._resume_lost("realtime", [], "rt_here", str(tmp_path)) is None
    assert rs._resume_lost("realtime", [], "rt_gone", str(tmp_path)) == "rt_gone"
    assert rs._resume_lost("realtime", [], None, str(tmp_path)) is None


def test_the_skills_the_runner_writes_are_the_ones_the_driver_reads(tmp_path):
    """The two halves of a skill's road to this base: the runner writes the turn's skills into the
    workspace and returns their entries, and the driver's reader takes those entries as they are."""
    import realtime_skills
    refunds = "---" + chr(10) + "name: refunds" + chr(10) + "description: How to refund an order." + chr(10) + "---" + chr(10) + chr(10) + "Ask for the order number first." + chr(10)
    written = rs._write_skills(str(tmp_path), [
        {"name": "refunds", "files": [{"path": "SKILL.md", "content": refunds},
                                      {"path": "references/policy.md", "content": "Thirty days."}]},
        {"name": "pdf", "files": [{"path": "SKILL.md", "content": refunds},
                                  {"path": "scripts/fill.py", "content": "print(1)"}]}], "realtime")
    assert [w["name"] for w in written] == ["refunds", "pdf"]
    assert written[0]["entry"] == ".harness/skills/refunds/SKILL.md"       # under .harness/: never a produced file
    assert written[0]["desc"] == "How to refund an order."
    skills, left = realtime_skills.read(tmp_path, written)
    assert [(s.name, s.description, s.body, s.resources) for s in skills] == [
        ("refunds", "How to refund an order.", "Ask for the order number first.", ("references/policy.md",))]
    assert left == [{"name": "pdf", "reason": realtime_skills.HAS_SCRIPTS}]
    # and the job the driver is started with carries those entries (realtime_backend.build)
    import inspect
    assert "skills=installed_skills" in inspect.getsource(rs._start_turn).split('backend == "realtime"')[1].split("elif backend")[0]
