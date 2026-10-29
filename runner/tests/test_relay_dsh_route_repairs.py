"""What the DeepSeek Harness driver's own relay was tested to do on main, tested again where dsh's
model calls go now: a route on the runner's relay, registered by _build_dsh (#382).

The driver's relay went with its tests (test_dsh_driver_gemini_schema.py,
test_dsh_driver_google_unknown.py, test_dsh_driver_stream_liveness.py,
test_dsh_driver_thought_signature.py, and the reasoning_effort helpers in test_dsh_normalize.py).
The runner's relay has tests of its own for each of these, but on a default route or on the helper
functions alone, and a dsh route is not a default one: it joins onto the base as stored
(exact_base), and its tool_call_deltas_no_empty flag forwards a stream line by line rather than read
by read. So every case here is built by _build_dsh and goes through the real handler to a provider on
loopback. Each docstring names the test on main it stands for.
"""
import http.client
import http.server
import json
import pathlib
import sys
import threading
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import reasoning  # noqa: E402
import server as rs  # noqa: E402
from test_relay_upstream_failure import _Upstream as _Misbehaving  # noqa: E402

_OK = (200, "application/json",
       b'{"id":"c","model":"served","choices":[{"index":0,"finish_reason":"stop",'
       b'"message":{"role":"assistant","content":"ok"}}]}')


def _ok(n, doc):
    return _OK


def _refusal(message: str):
    return 400, "application/json", json.dumps({"error": {"message": message, "code": 400}}).encode()


class _Provider:
    """A provider on loopback that records every request and answers with what `answer(n, doc)`
    returns for the nth one: (status, content type, body)."""

    def __init__(self, answer):
        self.seen: list[dict] = []
        provider = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                try:
                    doc = json.loads(raw)
                except ValueError:
                    doc = None
                provider.seen.append({"path": self.path, "auth": self.headers.get("authorization"),
                                      "raw": raw, "doc": doc})
                status, ctype, out = answer(len(provider.seen), doc)
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def dsh_route(tmp_path):
    """_build_dsh's route for one turn → (relay host, placeholder); dropped from the relay after."""
    made = []

    def make(base: str, model: str = "deepseek/deepseek-v4-flash", provider: str = "tokenrouter"):
        env = {"HOME": str(tmp_path)}
        rs._build_dsh(provider, rs.Auth(api_key="sk-real", base_url=base), model, "x", str(tmp_path), env)
        made.append(env["HR_DSH_RELAY_TOKEN"])
        return env["HR_DSH_RELAY_BASE"].removeprefix("http://").removesuffix("/v1"), env["HR_DSH_RELAY_TOKEN"]

    yield make
    for tok in made:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def _call(host: str, tok: str, doc: dict, path: str = "/v1/chat/completions", timeout: float = 15):
    """One call to the relay the way the runtime makes it → (status, body). A body the relay cut
    short on purpose comes back with what did arrive, marked."""
    conn = http.client.HTTPConnection(host, timeout=timeout)
    try:
        conn.request("POST", path, body=json.dumps(doc),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        try:
            return resp.status, resp.read()
        except http.client.IncompleteRead as e:
            return resp.status, e.partial + b"<<INCOMPLETE>>"
    finally:
        conn.close()


def _flags(tok: str) -> dict:
    return rs._HERMES_RELAY["routes"][tok][2]


# ── Gemini tool declarations through a strict channel (test_dsh_driver_gemini_schema.py) ──────

@pytest.fixture
def strict_gemini(monkeypatch):
    """Loopback is a strict Gemini channel here, as api.tokenrouter.com is (the host the driver's
    relay keyed on, and the first of _STRICT_GEMINI_HOSTS)."""
    monkeypatch.setattr(rs, "_STRICT_GEMINI_HOSTS", ("127.0.0.1",))


_CLINE_LIKE = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
               "properties": {"files": {"type": "array", "items": {"type": "object", "properties": {
                   "path": {"type": "string"}, "end_line": {"description": "line"},
                   "count": {"type": "integer", "exclusiveMinimum": 0},
                   "mode": {"oneOf": [{"const": "a"}, {"const": "b"}]},
                   "tag": {"type": ["string", "null"]}}, "required": ["path", "gone"]}},
                              "opts": {"type": "object", "properties": {}}, "list": {"type": "array"}},
               "required": ["files"]}


def _gemini_call(host, tok, tools, model="google/gemini-3.8-flash"):
    return _call(host, tok, {"model": model, "messages": [{"role": "user", "content": "hi"}], "tools": tools})


def test_a_harness_tool_schema_reaches_a_strict_gemini_channel_in_googles_subset(dsh_route, strict_gemini):
    """main: test_dsh_driver_gemini_schema.py::test_a_harness_tool_schema_is_normalised_to_googles_subset"""
    up = _Provider(_ok)
    host, tok = dsh_route(up.base, model="google/gemini-3.8-flash")
    try:
        status, _ = _gemini_call(host, tok, [{"type": "function", "function": {"name": "read", "parameters": _CLINE_LIKE}}])
    finally:
        up.close()
    assert status == 200
    out = up.seen[0]["doc"]["tools"][0]["function"]["parameters"]
    assert "$schema" not in out and "additionalProperties" not in out
    item = out["properties"]["files"]["items"]
    assert item["properties"]["end_line"] == {"description": "line", "type": "string"}
    assert item["properties"]["count"] == {"type": "integer", "minimum": 0}
    assert item["properties"]["mode"] == {"type": "string", "enum": ["a", "b"]}
    assert item["properties"]["tag"] == {"type": "string", "nullable": True}
    assert item["required"] == ["path"]
    assert out["properties"]["opts"] == {"type": "object"}
    assert out["properties"]["list"] == {"type": "array", "items": {"type": "string"}}


def test_only_tool_parameters_change_and_an_empty_declaration_is_dropped(dsh_route, strict_gemini):
    """main: test_dsh_driver_gemini_schema.py::test_only_tool_parameters_change_and_an_empty_declaration_is_dropped"""
    up = _Provider(_ok)
    host, tok = dsh_route(up.base, model="google/gemini-3.8-flash")
    plain = {"model": "google/gemini-3.8-flash", "messages": []}
    try:
        _gemini_call(host, tok, [
            {"type": "function", "function": {"name": "a", "parameters": {"$schema": "x", "type": "object", "properties": {"p": {"type": "string"}}}}},
            {"type": "function", "function": {"name": "b", "parameters": {"type": "object", "properties": {}}}}])
        _call(host, tok, plain)
    finally:
        up.close()
    sent = up.seen[0]["doc"]
    assert sent["tools"][0]["function"]["parameters"] == {"type": "object", "properties": {"p": {"type": "string"}}}
    assert "parameters" not in sent["tools"][1]["function"]
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert up.seen[1]["doc"] == plain                     # a call with no tools goes as it came


def test_a_nullable_choice_gets_a_type(dsh_route, strict_gemini):
    """main: test_dsh_driver_gemini_schema.py::test_a_nullable_choice_gets_a_type"""
    up = _Provider(_ok)
    host, tok = dsh_route(up.base, model="google/gemini-3.8-flash")
    params = {"type": "object", "properties": {
        "line": {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "line"},
        "either": {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}], "description": "either"},
        "nothing": {"anyOf": [{"type": "null"}]}}}
    try:
        _gemini_call(host, tok, [{"type": "function", "function": {"name": "f", "parameters": params}}])
    finally:
        up.close()
    props = up.seen[0]["doc"]["tools"][0]["function"]["parameters"]["properties"]
    assert props["line"] == {"type": "integer", "nullable": True, "description": "line"}
    assert props["either"] == {"type": "string", "nullable": True, "description": "either"}   # no anyOf leaves the relay
    assert props["nothing"] == {"type": "string", "nullable": True}


def test_a_model_that_is_not_gemini_keeps_its_declarations_on_that_channel(dsh_route, strict_gemini):
    """The driver's relay normalised only a model whose id names gemini; so does the route."""
    up = _Provider(_ok)
    host, tok = dsh_route(up.base)
    params = {"type": "object", "properties": {"count": {"type": "integer", "exclusiveMinimum": 0},
                                               "tag": {"type": ["string", "null"]}}}
    try:
        _gemini_call(host, tok, [{"type": "function", "function": {"name": "f", "parameters": params}}],
                     model="deepseek/deepseek-v4-flash")
    finally:
        up.close()
    assert up.seen[0]["doc"]["tools"][0]["function"]["parameters"] == params


# ── a field Google refuses by name (test_dsh_driver_google_unknown.py) ─────────────────────────

def test_fields_a_google_endpoint_refuses_by_name_are_dropped_and_remembered(dsh_route):
    """main: test_dsh_driver_google_unknown.py::test_the_refusal_names_the_field and
    ::test_the_fields_are_dropped_from_the_body. dsh sends OpenAI's optional store and seed; Google's
    OpenAI-compatible endpoint names one unknown field per 400."""
    def answer(n, doc):
        for field in ("store", "seed"):
            if field in doc:
                return _refusal(f'Invalid JSON payload received. Unknown name "{field}": Cannot find field.')
        return _OK

    up = _Provider(answer)
    host, tok = dsh_route(up.base, model="google/gemini-3.6-flash")
    body = {"model": "google/gemini-3.6-flash", "store": False, "seed": 1,
            "messages": [{"role": "user", "content": "hi"}]}
    try:
        first = _call(host, tok, body)
        second = _call(host, tok, body)
        flags = _flags(tok)
    finally:
        up.close()
    assert first[0] == 200 and second[0] == 200, (first, second)
    assert [sorted(f for f in ("store", "seed") if f in s["doc"]) for s in up.seen] == \
        [["seed", "store"], ["seed"], [], []], "each refused once, then left off for the rest of the route"
    assert {"store", "seed"} <= set(flags["drop_fields"])
    assert all(s["doc"]["messages"] == body["messages"] for s in up.seen)


def test_a_field_refused_inside_an_object_is_not_dropped(dsh_route):
    """main: test_dsh_driver_google_unknown.py::test_the_refusal_names_the_field (a field named
    at 'tools[0]' is not a top-level one)"""
    up = _Provider(lambda n, doc: _refusal("Unknown name \"strict\" at 'tools[0].function': Cannot find field."))
    host, tok = dsh_route(up.base, model="google/gemini-3.6-flash")
    try:
        status, raw = _call(host, tok, {"model": "google/gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}],
                                        "tools": [{"type": "function", "function": {"name": "f", "strict": True}}]})
    finally:
        up.close()
    assert status == 400 and b"strict" in raw                 # the provider's own refusal, for the runtime to read
    assert all(s["doc"]["tools"][0]["function"].get("strict") is True for s in up.seen)


def test_the_helper_the_route_drops_fields_with_leaves_every_other_body_alone():
    """main: test_dsh_driver_google_unknown.py::test_the_fields_are_dropped_from_the_body and
    test_dsh_normalize.py::test_drop_reasoning_effort_leaves_other_bodies_alone, on the helper the
    route uses for both (_drop_top_level_field)"""
    body = b'{"model": "m", "store": false, "seed": 1, "messages": []}'
    out = rs._drop_top_level_field(rs._drop_top_level_field(body, "store"), "seed")
    assert json.loads(out) == {"model": "m", "messages": []}
    effort = json.dumps({"model": "deepseek-v4-pro", "reasoning_effort": "high",
                         "messages": [{"role": "user", "content": "hi"}]}).encode()
    assert json.loads(rs._drop_top_level_field(effort, "reasoning_effort")) == \
        {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "hi"}]}
    for other in (b"not json", b"not json at all", b"[1,2,3]", json.dumps({"model": "m", "messages": []}).encode()):
        for field in ("store", "reasoning_effort"):
            assert rs._drop_top_level_field(other, field) is other


# ── reasoning_effort the provider does not take (test_dsh_normalize.py, T-01 against LLMTR) ────

_EFFORT_REFUSAL = 'The "reasoning_effort" parameter is not supported by "deepseek/deepseek-v4-pro"'


def test_a_refused_reasoning_effort_is_the_only_thing_taken_off_the_call(dsh_route):
    """main: test_dsh_normalize.py::test_drop_reasoning_effort_removes_only_that_key"""
    up = _Provider(lambda n, doc: _refusal(_EFFORT_REFUSAL) if "reasoning_effort" in doc else _OK)
    host, tok = dsh_route(up.base, model="deepseek/deepseek-v4-pro")
    body = {"model": "deepseek/deepseek-v4-pro", "reasoning_effort": "high", "temperature": 0.2,
            "messages": [{"role": "user", "content": "hi"}]}
    try:
        status, _ = _call(host, tok, body)
    finally:
        up.close()
    assert status == 200 and len(up.seen) == 2
    assert up.seen[1]["doc"] == {k: v for k, v in body.items() if k != "reasoning_effort"}


def test_a_refusal_about_another_parameter_does_not_cost_the_call_its_reasoning_effort(dsh_route):
    """main: test_dsh_normalize.py::test_drop_reasoning_effort_leaves_other_bodies_alone, at the
    route: only a refusal of the parameter itself takes it off"""
    up = _Provider(lambda n, doc: _refusal('The "seed" parameter is not supported'))
    host, tok = dsh_route(up.base, model="deepseek/deepseek-v4-pro")
    try:
        status, raw = _call(host, tok, {"model": "deepseek/deepseek-v4-pro", "reasoning_effort": "high",
                                        "messages": [{"role": "user", "content": "hi"}]})
        flags = _flags(tok)
    finally:
        up.close()
    assert status == 400 and b"seed" in raw
    assert all(s["doc"].get("reasoning_effort") == "high" for s in up.seen)
    assert not any(k.startswith("drop_reasoning_effort:") for k in flags)


# ── the turn's thinking level (the driver applied HR_DSH_REASONING_EFFORT with reasoning.apply) ─

@pytest.fixture
def turn_asking(monkeypatch):
    """A turn that asked for a thinking level, on a route measured as OpenRouter is."""
    monkeypatch.setattr(reasoning, "route_of", lambda base: "openrouter")
    tokens = []

    def ask(level: str) -> dict:
        tokens.append(rs._TURN_THINKING.set({"asked": level, "applied": "", "routes": []}))
        return rs._TURN_THINKING.get()

    yield ask
    for t in reversed(tokens):
        rs._TURN_THINKING.reset(t)


def test_the_turns_thinking_level_is_written_into_a_dsh_call_as_the_turn_records_it(dsh_route, turn_asking):
    """No test on main: the driver's relay wrote the level with the same function the runner's relay
    uses (runner/reasoning.py), and _build_dsh recorded what it would apply. The route does the
    writing now, so what _build_dsh records must be what reaches the provider."""
    up = _Provider(_ok)
    thinking = turn_asking("minimal")
    host, tok = dsh_route(up.base, model="openai/gpt-5.4")
    try:
        status, _ = _call(host, tok, {"model": "openai/gpt-5.4", "messages": [{"role": "user", "content": "hi"}]})
        flags = _flags(tok)
    finally:
        up.close()
    assert status == 200
    assert up.seen[0]["doc"]["reasoning_effort"] == "low"
    assert thinking["applied"] == "low" == flags["effort_applied"]["openai/gpt-5.4"]


def test_a_refused_level_never_fails_a_dsh_call_and_is_not_offered_again(dsh_route, turn_asking):
    """No test on main: the driver's relay sent a refused level's call again without it and kept
    it off that model for the turn (_effort_refused). So does the route."""
    up = _Provider(lambda n, doc: _refusal("Reasoning is mandatory for this endpoint and cannot be disabled.")
                   if "reasoning_effort" in doc else _OK)
    turn_asking("high")
    host, tok = dsh_route(up.base, model="openai/gpt-5.4")
    doc = {"model": "openai/gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    try:
        first = _call(host, tok, doc)
        second = _call(host, tok, doc)
    finally:
        up.close()
    assert first[0] == 200 and second[0] == 200
    assert [("reasoning_effort" in s["doc"]) for s in up.seen] == [True, False, False]


# ── the stream, line by line (test_dsh_driver_stream_liveness.py) ─────────────────────────────

def _misbehaving_route(dsh_route, mode: str):
    up = _Misbehaving(mode)
    host, tok = dsh_route(f"http://127.0.0.1:{up.port}/v1")
    return up, host, tok


def test_an_event_reaches_the_runtime_when_it_arrives(dsh_route):
    """main: test_dsh_driver_stream_liveness.py::test_an_event_is_forwarded_when_it_arrives"""
    up, host, tok = _misbehaving_route(dsh_route, "first_event_then_pause")
    conn = http.client.HTTPConnection(host, timeout=10)
    try:
        t0 = time.time()
        conn.request("POST", "/v1/chat/completions",
                     body=json.dumps({"model": "m", "messages": [], "stream": True}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        first = resp.read1(4096)
        waited = time.time() - t0
        rest = resp.read()
    finally:
        conn.close()
        up.close()
    assert b'"first"' in first and waited < 1.0, (waited, first[:80])
    assert b"second" in rest and b"[DONE]" in rest


def test_keep_alive_lines_alone_end_the_call_with_the_reason(dsh_route, monkeypatch):
    """main: test_dsh_driver_stream_liveness.py::test_keep_alive_lines_alone_end_the_call_with_the_reason"""
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    up, host, tok = _misbehaving_route(dsh_route, "keepalive_forever")
    t0 = time.time()
    try:
        status, body = _call(host, tok, {"model": "m", "messages": [], "stream": True})
    finally:
        up.close()
    assert time.time() - t0 < 6, "the relay must end the call itself, near its own wait"
    assert status == 200 and body.endswith(b"<<INCOMPLETE>>"), body[-160:]
    assert b'"code": "upstream_unavailable"' in body and b"no data" in body


def test_the_wait_is_the_runners_own_figure(dsh_route, monkeypatch):
    """main: test_dsh_driver_stream_liveness.py::test_the_wait_is_the_runners_figure_and_600_without_it.
    The driver read the runner's figure from HR_RELAY_UPSTREAM_TIMEOUT_S, which _build_dsh handed
    over; the route waits on the runner's own (HR_RELAY_UPSTREAM_TIMEOUT_S in server.py, whose 600 s
    default and junk values test_relay_upstream_failure.py checks), so there is one figure now."""
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    up, host, tok = _misbehaving_route(dsh_route, "silent")
    try:
        status, body = _call(host, tok, {"model": "m", "messages": [], "stream": True}, timeout=20)
    finally:
        up.close()
    assert status == 504, (status, body[:200])
    assert "timed out" in json.loads(body)["error"]["message"]
    assert up.requests == 1


def test_a_stream_that_stalls_is_not_ended_as_a_complete_answer(dsh_route, monkeypatch):
    """main: the driver's relay said so in the stream and left the body unterminated (its stopped
    branch), which test_dsh_driver_stream_liveness.py reached through the keep-alive case."""
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    up, host, tok = _misbehaving_route(dsh_route, "stall_mid_stream")
    try:
        status, body = _call(host, tok, {"model": "m", "messages": [], "stream": True}, timeout=20)
    finally:
        up.close()
    assert status == 200 and body.endswith(b"<<INCOMPLETE>>"), body[-120:]
    assert b'"code": "upstream_unavailable"' in body and b"mid-stream" in body


# ── a provider that does not answer: what the driver's relay could not do (#382) ───────────────

def test_a_refused_connection_is_an_answer_the_runtime_can_read(dsh_route):
    """No test on main, and the defect #382 names first: the driver's relay caught only HTTPError,
    so a refused connection escaped it and the runtime held a closed socket ("DeepSeek API request
    to http://127.0.0.1:<the driver's port>/v1 failed")."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead = sock.getsockname()[1]
    sock.close()
    host, tok = dsh_route(f"http://127.0.0.1:{dead}/v1")
    status, body = _call(host, tok, {"model": "deepseek/deepseek-v4-flash", "messages": []})
    assert status == 502, (status, body[:200])
    assert json.loads(body)["error"]["code"] == "upstream_unavailable"


def test_a_dropped_connection_is_tried_once_more_then_answered(dsh_route):
    up, host, tok = _misbehaving_route(dsh_route, "drop")
    try:
        status, body = _call(host, tok, {"model": "m", "messages": []})
    finally:
        up.close()
    assert status == 502 and "did not answer" in json.loads(body)["error"]["message"]
    assert up.requests == 2


# ── Gemini 3 thought signatures (test_dsh_driver_thought_signature.py) ─────────────────────────

_REPLAY = {"model": "google/gemini-3.6-flash", "messages": [
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_7", "type": "function", "function": {"name": "f", "arguments": "{}"}},
        {"id": "call_new", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "call_7", "content": "ok"},
    {"role": "tool", "tool_call_id": "call_new", "content": "ok"}]}


def _signature_of(call: dict):
    return ((call.get("extra_content") or {}).get("google") or {}).get("thought_signature")


def test_signatures_a_google_answer_streams_are_replayed_on_the_next_call(dsh_route, monkeypatch):
    """main: test_dsh_driver_thought_signature.py::test_dsh_relay_reads_signatures_and_replays_them_or_the_sentinel"""
    monkeypatch.setattr(rs, "_GOOGLE_HOST", "127.0.0.1")    # loopback is Google's own endpoint here
    tc = {"index": 0, "id": "call_7", "type": "function", "function": {"name": "f", "arguments": "{}"},
          "extra_content": {"google": {"thought_signature": "sig7"}}}
    stream = (b"data: " + json.dumps({"choices": [{"index": 0, "delta": {"tool_calls": [tc]}}]}).encode() + b"\n\n"
              b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n')
    up = _Provider(lambda n, doc: (200, "text/event-stream", stream) if n == 1 else _OK)
    host, tok = dsh_route(up.base, model="google/gemini-3.6-flash")
    plain = {"model": "google/gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}]}
    try:
        s1, streamed = _call(host, tok, {**plain, "stream": True})
        s2, _ = _call(host, tok, _REPLAY)
        s3, _ = _call(host, tok, plain)
    finally:
        up.close()
    assert s1 == s2 == s3 == 200
    assert b"sig7" in streamed                              # the runtime has it as the provider sent it
    calls = up.seen[1]["doc"]["messages"][1]["tool_calls"]
    assert _signature_of(calls[0]) == "sig7"
    assert _signature_of(calls[1]) == rs._GOOGLE_SIG_SKIP   # a call the relay never saw an answer for
    assert up.seen[2]["doc"] == plain                       # a call with no tool calls goes as it came


def test_an_endpoint_that_names_a_missing_signature_gets_the_call_again_with_one(dsh_route):
    """main: the driver's relay did this for a Gemini 3 endpoint it did not recognise as Google
    (_google_required); its test covered the replay that retry uses."""
    def answer(n, doc):
        calls = [c for m in doc["messages"] if m.get("role") == "assistant" for c in m.get("tool_calls") or []]
        if calls and not all(_signature_of(c) for c in calls):
            return _refusal("Function call is missing a thought_signature in functionCall parts.")
        return _OK

    up = _Provider(answer)
    host, tok = dsh_route(up.base, model="google/gemini-3.6-flash")
    try:
        status, _ = _call(host, tok, _REPLAY)
        flags = _flags(tok)
    finally:
        up.close()
    assert status == 200 and len(up.seen) == 2
    assert all(_signature_of(c) == rs._GOOGLE_SIG_SKIP for c in up.seen[1]["doc"]["messages"][1]["tool_calls"])
    assert flags.get("thought_signature") is True


# ── what the tool-call delta rewrite must leave alone ──────────────────────────────────────────

def test_a_messages_stream_on_the_dsh_route_reaches_the_runtime_byte_for_byte(dsh_route):
    """The driver's relay rewrote tool-call deltas on chat-completions streams only, and passed
    anthropic-messages and openai-responses through byte-faithful. The route's flag looks at every
    stream line, so a Messages stream (no `choices`, no `tool_calls`, an empty string or two) must
    come through as the provider sent it."""
    stream = (b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_1","model":"claude-haiku-4-5",'
              b'"content":[],"usage":{"input_tokens":3,"output_tokens":0}}}\n\n'
              b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":'
              b'{"type":"tool_use","id":"toolu_1","name":"bash","input":{}}}\n\n'
              b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":'
              b'{"type":"input_json_delta","partial_json":""}}\n\n'
              b'event: message_stop\ndata: {"type":"message_stop"}\n\n')
    up = _Provider(lambda n, doc: (200, "text/event-stream", stream))
    host, tok = dsh_route(up.base, model="claude-haiku-4-5", provider="anthropic")
    try:
        status, raw = _call(host, tok, {"model": "claude-haiku-4-5", "max_tokens": 16, "stream": True,
                                        "messages": [{"role": "user", "content": "hi"}]}, path="/v1/messages")
    finally:
        up.close()
    assert status == 200 and raw == stream
    assert up.seen[0]["path"] == "/v1/messages" and up.seen[0]["auth"] == "Bearer sk-real"
