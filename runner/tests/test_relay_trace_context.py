"""A caller's W3C trace context reaches the model calls of its turn (#473): the CLI gets TRACEPARENT
and TRACESTATE in its environment, and the relay sends a child traceparent (same trace id, new span
id, sampled flag kept) and the caller's tracestate on every call it forwards. Nothing else of the
caller's context travels, a value that is not W3C syntax is dropped, and a turn that brought none
sends none."""
import json
import pathlib
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402
import tracecontext  # noqa: E402
from server import Auth, _TURN_TRACE, _hermes_relay_route  # noqa: E402

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"
STATE = "congo=t61rcWkgMzE,rojo=00f067aa0ba902b7"


@pytest.fixture()
def upstream():
    seen: list[dict] = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers["content-length"]))
            seen.append({k.lower(): v for k, v in self.headers.items()})
            data = b'{"ok": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{up.server_address[1]}/v1", seen
    finally:
        up.shutdown()


def _call(base: str, tok: str, **extra: str) -> None:
    body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}]}).encode()
    headers = {"authorization": f"Bearer {tok}", "content-type": "application/json", **extra}
    urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                                  headers=headers), timeout=10).read()


def _route(base: str, trace: dict) -> tuple[str, str]:
    """(relay base, placeholder) for a route registered while a turn with `trace` was being built."""
    reset = _TURN_TRACE.set(trace)
    try:
        return _hermes_relay_route(base, "sk-key")
    finally:
        _TURN_TRACE.reset(reset)


def test_valid_context_is_kept_and_anything_else_is_dropped():
    assert tracecontext.parse(PARENT, STATE) == {"traceparent": PARENT, "tracestate": STATE}
    assert tracecontext.parse(PARENT) == {"traceparent": PARENT}
    assert tracecontext.parse(PARENT, "not a state") == {"traceparent": PARENT}
    for bad in ("", None, "garbage", PARENT.upper(), f"ff-{TRACE_ID}-00f067aa0ba902b7-01",
                f"00-{'0' * 32}-00f067aa0ba902b7-01", f"00-{TRACE_ID}-{'0' * 16}-01",
                PARENT + "-extra", PARENT + "\r\nx-injected: 1"):
        assert tracecontext.parse(bad, STATE) == {}, bad
    # a later version may carry more fields; its four known ones are read
    assert tracecontext.parse(f"01-{TRACE_ID}-00f067aa0ba902b7-01-what-the-future-holds")


def test_a_child_keeps_the_trace_id_and_the_sampled_flag_with_a_new_span():
    child = tracecontext.child(PARENT)
    version, trace_id, span, flags = child.split("-")
    assert (version, trace_id, flags) == ("00", TRACE_ID, "01")
    assert span != "00f067aa0ba902b7" and len(span) == 16 and tracecontext.parse(child)
    assert tracecontext.child(f"00-{TRACE_ID}-00f067aa0ba902b7-00").endswith("-00")
    assert tracecontext.child(f"00-{TRACE_ID}-00f067aa0ba902b7-ff").endswith("-01")  # unknown flags dropped
    assert tracecontext.child("garbage") == ""


def test_relayed_model_calls_carry_a_child_of_the_callers_trace(upstream):
    base, seen = upstream
    relay, tok = _route(base, {"traceparent": PARENT, "tracestate": STATE})
    _call(relay, tok)
    _call(relay, tok)
    spans = set()
    for h in seen:
        version, trace_id, span, flags = h["traceparent"].split("-")
        assert (version, trace_id, flags) == ("00", TRACE_ID, "01")
        assert span != "00f067aa0ba902b7"
        assert h["tracestate"] == STATE
        spans.add(span)
    assert len(spans) == 2                       # a span per call


def test_a_call_the_cli_traced_under_the_same_trace_keeps_its_own_span(upstream):
    base, seen = upstream
    relay, tok = _route(base, {"traceparent": PARENT})
    own = f"00-{TRACE_ID}-1111111111111111-01"
    _call(relay, tok, traceparent=own, tracestate="cli=1")
    _call(relay, tok, traceparent=f"00-{'a' * 32}-1111111111111111-01")   # another trace: replaced
    assert seen[0]["traceparent"] == own and seen[0]["tracestate"] == "cli=1"
    assert seen[1]["traceparent"].split("-")[1] == TRACE_ID and "tracestate" not in seen[1]


def test_no_context_in_means_none_out(upstream):
    base, seen = upstream
    _call(*_route(base, {}))
    assert "traceparent" not in seen[0] and "tracestate" not in seen[0]


def test_a_turn_hands_the_context_to_the_cli_and_its_routes(monkeypatch, tmp_path, upstream):
    base, seen = upstream
    launched = []
    monkeypatch.setattr(server, "_run_hermes_bg", lambda *args: launched.append(args))

    def run(name, **trace):
        cwd = tmp_path / name
        cwd.mkdir()
        server.turn(server.TurnReq(backend="hermes", provider="openai-api", model="m", prompt="hi",
                                   auth=Auth(api_key="sk-test", base_url=base), cwd=str(cwd), **trace))
        return launched[-1][2]

    env = run("traced", traceparent=PARENT, tracestate=STATE)
    assert env["TRACEPARENT"] == PARENT and env["TRACESTATE"] == STATE
    _call(env["OPENAI_BASE_URL"], env["OPENAI_API_KEY"])
    assert seen[-1]["traceparent"].split("-")[1] == TRACE_ID

    env = run("untraced")                       # the next turn in this context brought none
    assert "TRACEPARENT" not in env and "TRACESTATE" not in env
    _call(env["OPENAI_BASE_URL"], env["OPENAI_API_KEY"])
    assert "traceparent" not in seen[-1]

    env = run("invalid", traceparent="nope", tracestate=STATE)
    assert "TRACEPARENT" not in env and "TRACESTATE" not in env
