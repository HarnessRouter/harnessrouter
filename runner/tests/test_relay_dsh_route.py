'''One relay for the DeepSeek Harness (#382).

The dsh driver ran a loopback relay of its own between the runtime and the provider, so this base's
model calls never passed the runner's relay and missed its repairs: an answer when the provider does
not answer, the served model and usage read off the bytes, the tool-schema flattening, the
conversation repairs, the cache breakpoints. Now _build_dsh registers a route on the runner's relay
and the driver hands the runtime that route. What the driver's relay did that the runner's did not
came along as route behaviour, and these tests drive it through a real relay to a real socket:

- the empty-string id/name taken off a streamed tool-call delta (tool_call_deltas_no_empty), on the
  dsh route only: every other route still gets the provider's bytes as they came;
- a provider that takes no reasoning_effort at all (LLMTR on deepseek/*) gets the call again without it.
'''
import http.client
import http.server
import json
import pathlib
import sys
import threading
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402
import server as rs  # noqa: E402

# The exact TokenRouter delta shapes (test_dsh_normalize.py), plus a `data:` line with no space, a
# keep-alive comment and the end marker, which must all reach the client.
_FIRST = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_617","type":"function",'
          b'"function":{"name":"bash","arguments":""}}]},"finish_reason":null,"index":0}]}\n\n')
_CONT = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"","type":"function",'
         b'"function":{"name":"","arguments":"{\\"command\\""}}]},"finish_reason":null,"index":0}]}\n\n')
_TIGHT = (b'data:{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"","type":"function",'
          b'"function":{"name":"","arguments":":\\"ls\\"}"}}]},"finish_reason":"tool_calls","index":0}]}\n\n')
_STREAM = _FIRST + b": keep-alive\n\n" + _CONT + _TIGHT + b"data: [DONE]\n\n"
_LLMTR_REFUSAL = (b'{"error":{"message":"The \\"reasoning_effort\\" parameter is not supported by '
                  b'\\"deepseek/deepseek-v4-pro\\"","type":"invalid_request_error"}}')


class _Provider:
    '''A provider on loopback that records what reached it.'''

    def __init__(self, mode: str):
        self.seen: list[dict] = []
        provider = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("content-length") or 0))
                provider.seen.append({"path": self.path, "auth": self.headers.get("authorization"),
                                      "body": json.loads(body or b"{}")})
                if mode == "stream":
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream")
                    self.send_header("content-length", str(len(_STREAM)))
                    self.end_headers()
                    self.wfile.write(_STREAM)
                    return
                if "reasoning_effort" in provider.seen[-1]["body"]:
                    data, status = _LLMTR_REFUSAL, 400
                else:
                    data, status = b'{"id":"c","model":"deepseek/deepseek-v4-pro","choices":[]}', 200
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _call(relay_base: str, tok: str, body: dict) -> tuple[int, bytes]:
    '''One chat/completions call to the relay, the way the runtime makes it.'''
    conn = http.client.HTTPConnection(relay_base.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        conn.request("POST", "/v1/chat/completions", body=json.dumps(body),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _deltas(raw: bytes) -> list:
    return [json.loads(ln[5:]) for ln in raw.split(b"\n") if ln.startswith(b"data:") and b"{" in ln]


def test_the_dsh_route_takes_the_empty_id_and_name_off_every_tool_call_delta():
    up = _Provider("stream")
    relay_base, tok = rs._hermes_relay_route(up.base, "sk-real", tool_call_deltas_no_empty=True)
    try:
        status, raw = _call(relay_base, tok, {"model": "deepseek/deepseek-v4-flash", "messages": [], "stream": True})
    finally:
        up.close()
        rs._HERMES_RELAY["routes"].pop(tok, None)
    assert status == 200
    calls = [d["choices"][0]["delta"]["tool_calls"][0] for d in _deltas(raw)]
    assert calls[0]["id"] == "call_617" and calls[0]["function"]["name"] == "bash"
    for cont in calls[1:]:          # the spaced line and the one with no space after `data:`
        assert "id" not in cont and "name" not in cont["function"], cont
    assert "".join(c["function"]["arguments"] for c in calls) == '{"command":"ls"}'
    assert b": keep-alive" in raw and b"data: [DONE]" in raw
    assert up.seen[0]["auth"] == "Bearer sk-real"      # the key went upstream from the relay


def test_another_route_gets_the_providers_stream_byte_for_byte():
    up = _Provider("stream")
    relay_base, tok = rs._hermes_relay_route(up.base, "sk-real")
    try:
        status, raw = _call(relay_base, tok, {"model": "m", "messages": [], "stream": True})
    finally:
        up.close()
        rs._HERMES_RELAY["routes"].pop(tok, None)
    assert status == 200 and raw == _STREAM


def test_a_provider_that_takes_no_reasoning_effort_gets_the_call_again_without_it():
    up = _Provider("json")
    relay_base, tok = rs._hermes_relay_route(up.base, "sk-real", tool_call_deltas_no_empty=True)
    body = {"model": "deepseek/deepseek-v4-pro", "reasoning_effort": "high",
            "messages": [{"role": "user", "content": "hi"}]}
    try:
        first = _call(relay_base, tok, body)
        second = _call(relay_base, tok, body)
        flags = rs._HERMES_RELAY["routes"][tok][2]
    finally:
        up.close()
        rs._HERMES_RELAY["routes"].pop(tok, None)
    assert first[0] == 200 and second[0] == 200, (first, second)
    assert [("reasoning_effort" in s["body"]) for s in up.seen] == [True, False, False], \
        "refused once, then left off for that model on the route"
    assert flags.get("drop_reasoning_effort:deepseek/deepseek-v4-pro") is True
    assert up.seen[1]["body"]["messages"] == body["messages"]


def test_build_dsh_routes_the_runtime_through_the_runners_relay(tmp_path):
    '''What the driver hands the runtime (DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY) reaches the
    provider with the connection's key, and the dsh repair applied on the way.'''
    up = _Provider("stream")
    env = {"HOME": str(tmp_path)}
    rs._build_dsh("tokenrouter", rs.Auth(api_key="sk-real", base_url=up.base), "deepseek/deepseek-v4-flash",
                  "x", str(tmp_path), env)
    try:
        status, raw = _call(env["HR_DSH_RELAY_BASE"], env["HR_DSH_RELAY_TOKEN"],
                            {"model": "deepseek/deepseek-v4-flash", "messages": [], "stream": True})
        flags = rs._HERMES_RELAY["routes"][env["HR_DSH_RELAY_TOKEN"]][2]
    finally:
        up.close()
        rs._HERMES_RELAY["routes"].pop(env["HR_DSH_RELAY_TOKEN"], None)
    assert status == 200 and up.seen[0]["path"] == "/v1/chat/completions"
    assert up.seen[0]["auth"] == "Bearer sk-real"
    assert all("id" not in d["choices"][0]["delta"]["tool_calls"][0] for d in _deltas(raw)[1:])
    # the runner's taps see this base's calls now: the matrix rows read "turn(s) unlabelled" without it
    assert flags.get("last_finish") == "tool_calls"


class _FakeHarness:
    '''deepseek_harness.DeepSeekHarness, recording how the driver launched it.'''
    launched: dict = {}

    def __init__(self, **kw):
        import os
        _FakeHarness.launched = {"kw": kw, "env": dict(os.environ)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, prompt, session_id=None, on_notification=None):
        return types.SimpleNamespace(final_response="done", finish_reason="completed", session_id="s1")


def test_the_driver_hands_the_runtime_the_route_and_runs_no_relay_of_its_own(tmp_path, monkeypatch, capsys):
    import yaml
    monkeypatch.setitem(sys.modules, "deepseek_harness", types.SimpleNamespace(DeepSeekHarness=_FakeHarness))
    for k in ("DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "HR_RELAY_TOKEN", "DSH_PERMISSION_MODE"):
        monkeypatch.setenv(k, "before")       # restored after the test; the driver overwrites them
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HR_DSH_RELAY_BASE", "http://127.0.0.1:4321/v1")
    monkeypatch.setenv("HR_DSH_RELAY_TOKEN", "hr-relay-abc")
    job = {"prompt": "hi", "model": "claude-haiku-4-5", "cwd": str(tmp_path), "session_id": "",
           "mcp_servers": [], "llm": {"api": "anthropic-messages", "vision": True}}
    monkeypatch.setattr(sys, "argv", ["dsh_driver.py", json.dumps(job)])
    assert dsh_driver.main() == 0
    env = _FakeHarness.launched["env"]
    assert env["DEEPSEEK_BASE_URL"] == "http://127.0.0.1:4321/v1"
    assert env["DEEPSEEK_API_KEY"] == env["HR_RELAY_TOKEN"] == "hr-relay-abc"
    assert "HR_DSH_RELAY_BASE" not in env and "HR_DSH_RELAY_TOKEN" not in env
    patch = yaml.safe_load(pathlib.Path(_FakeHarness.launched["kw"]["patches"][0]).read_text())
    hr = [e for e in patch if e.get("id") == "llm-pi-ai"][0]["config"]["providers"]["hr"]
    assert hr["baseURL"] == "http://127.0.0.1:4321"     # anthropic-messages appends /v1/messages itself
    assert '"m": "__hr_result"' in capsys.readouterr().out
    assert not hasattr(dsh_driver, "_Relay"), "one relay: the runner's"


def test_the_driver_without_a_route_stops_before_the_runtime(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "deepseek_harness", types.SimpleNamespace(DeepSeekHarness=_FakeHarness))
    monkeypatch.delenv("HR_DSH_RELAY_BASE", raising=False)
    monkeypatch.delenv("HR_DSH_RELAY_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["dsh_driver.py", json.dumps({"prompt": "hi", "model": "m"})])
    _FakeHarness.launched = {}
    assert dsh_driver.main() == 2 and _FakeHarness.launched == {}
