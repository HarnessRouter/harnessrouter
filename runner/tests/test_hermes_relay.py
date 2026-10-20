"""The hermes loopback relay (issue #12).

hermes emits OpenAI-legal messages that aggregator translators reject: a tool-call assistant
message with `content: ""` becomes an empty Anthropic text block behind TokenRouter and the
provider 400s ('messages: text content blocks must be non-empty', captured live 2026-08-20 by
conformance X-05 on claude-haiku-4.5). The relay repairs the shape before the provider sees it
and keeps the real key out of the CLI's environment. These tests pin the normalization and run
one real request through the relay against a local fake upstream.
"""
import json
import pathlib
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import Auth, _hermes_relay_route, _normalize_openai_chat_body  # noqa: E402


def _norm(obj):
    return json.loads(_normalize_openai_chat_body(json.dumps(obj).encode()))


def test_tool_call_message_with_empty_content_becomes_null():
    body = {"model": "claude-haiku-4.5", "messages": [
        {"role": "user", "content": "read the file"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "the secret token is x"},
    ]}
    out = _norm(body)
    assert out["messages"][1]["content"] is None
    assert out["messages"][0]["content"] == "read the file"      # untouched
    assert out["messages"][2]["content"] == "the secret token is x"


def test_empty_text_parts_are_dropped_from_list_content():
    body = {"messages": [
        {"role": "assistant",
         "content": [{"type": "text", "text": ""}, {"type": "text", "text": "real"}]},
        {"role": "assistant", "content": [{"type": "text", "text": ""}],
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "f", "arguments": "{}"}}]},
    ]}
    out = _norm(body)
    assert out["messages"][0]["content"] == [{"type": "text", "text": "real"}]
    assert out["messages"][1]["content"] is None                 # emptied + tool_calls → null


def test_compliant_bodies_pass_through_byte_identical():
    for body in (b"not json", b"[]",
                 json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
                 json.dumps({"messages": [{"role": "assistant", "content": ""}]}).encode()):
        # an empty assistant message WITHOUT tool_calls is left alone — inventing content is
        # not this relay's job, and translators handle that case (it has no tool_result pair).
        assert _normalize_openai_chat_body(body) == body


def test_relay_normalizes_and_injects_the_real_key():
    seen = {}

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen["auth"] = self.headers.get("authorization")
            seen["path"] = self.path
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
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        assert tok.startswith("hr-relay-") and "sk-real" not in tok
        body = json.dumps({"messages": [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "f", "arguments": "{}"}}]}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json"})
        assert json.loads(urllib.request.urlopen(req, timeout=10).read()) == {"ok": True}
        assert seen["auth"] == "Bearer sk-real"                  # real key injected upstream
        assert seen["path"] == "/v1/chat/completions"
        assert seen["body"]["messages"][0]["content"] is None    # normalized in flight
    finally:
        up.shutdown()


def test_relay_refuses_an_unknown_token():
    base, _ = _hermes_relay_route("http://127.0.0.1:9/v1", "sk-x")   # ensures server is up
    req = urllib.request.Request(base + "/chat/completions", data=b"{}", method="POST",
                                 headers={"authorization": "Bearer nope"})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 401")
    except urllib.error.HTTPError as e:
        assert e.code == 401


# ── max_tokens rename-on-rejection (opencode x custom-Azure, 2026-08-27) ───────────────────────
# Azure's gpt-5.x deployments 400 on max_tokens and name the fix in the error body. The relay
# applies exactly that fix, once, and remembers it for the route.

def test_rename_max_tokens_helper():
    from server import _rename_max_tokens
    body = json.dumps({"model": "m", "max_tokens": 64, "messages": []}).encode()
    out = json.loads(_rename_max_tokens(body))
    assert out["max_completion_tokens"] == 64 and "max_tokens" not in out
    already = json.dumps({"max_tokens": 1, "max_completion_tokens": 2}).encode()
    assert _rename_max_tokens(already) == already          # never clobber an explicit value
    assert _rename_max_tokens(b"not json") == b"not json"


def test_relay_retries_a_max_tokens_rejection_and_sticks():
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(body)
            if "max_tokens" in body:
                data = (b'{"error": {"message": "Unsupported parameter: max_tokens is not '
                        b'supported with this model. Use max_completion_tokens instead."}}')
                self.send_response(400)
            else:
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
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        body = json.dumps({"model": "m", "max_tokens": 64,
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json"})
        assert json.loads(urllib.request.urlopen(req, timeout=10).read()) == {"ok": True}
        assert len(calls) == 2                              # rejected once, renamed, succeeded
        assert "max_completion_tokens" in calls[1] and "max_tokens" not in calls[1]
        # The route remembers: the next request renames preemptively — one call, not two.
        urllib.request.urlopen(urllib.request.Request(
            base + "/chat/completions", data=body, method="POST",
            headers={"authorization": f"Bearer {tok}", "content-type": "application/json"}), timeout=10)
        assert len(calls) == 3 and "max_completion_tokens" in calls[2]
    finally:
        up.shutdown()

# ── tool-content stringify-on-rejection (qwen x LLMTR, 2026-08-27) ──────────────────────────────
# qwen-code sends tool-result content as an array of parts; strict aggregators 400 with
# 'tool message content must be a string' — measured live, killing the turn after the tool ran.

def test_stringify_tool_content_helper():
    from server import _stringify_tool_content
    body = json.dumps({"messages": [
        {"role": "user", "content": [{"type": "text", "text": "leave arrays on non-tool roles"}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": [{"type": "text", "text": "TOOL-"}, {"type": "text", "text": "OUT"}]},
    ]}).encode()
    out = json.loads(_stringify_tool_content(body))
    assert out["messages"][1]["content"] == "TOOL-OUT"
    assert isinstance(out["messages"][0]["content"], list)    # user parts untouched
    already = json.dumps({"messages": [{"role": "tool", "content": "s"}]}).encode()
    assert _stringify_tool_content(already) == already
    assert _stringify_tool_content(b"not json") == b"not json"


def test_relay_retries_a_tool_content_rejection_and_sticks():
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(body)
            if any(m.get("role") == "tool" and not isinstance(m.get("content"), str)
                   for m in body["messages"]):
                data = b'{"error": {"message": "tool message content must be a string"}}'
                self.send_response(400)
            else:
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
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        body = json.dumps({"model": "m", "messages": [
            {"role": "user", "content": "run it"},
            {"role": "tool", "tool_call_id": "c1",
             "content": [{"type": "text", "text": "TOOL-Q"}]},
        ]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json"})
        assert json.loads(urllib.request.urlopen(req, timeout=10).read()) == {"ok": True}
        assert len(calls) == 2                              # rejected once, flattened, succeeded
        assert calls[1]["messages"][1]["content"] == "TOOL-Q"
        # Sticky for the route: the next request flattens preemptively.
        urllib.request.urlopen(urllib.request.Request(
            base + "/chat/completions", data=body, method="POST",
            headers={"authorization": f"Bearer {tok}", "content-type": "application/json"}), timeout=10)
        assert len(calls) == 3 and calls[2]["messages"][1]["content"] == "TOOL-Q"
    finally:
        up.shutdown()

# ── empty reasoning_content (qwen x deepseek-v4-pro on LLMTR, 2026-08-27) ───────────────────────
# qwen echoes DeepSeek's reasoning_content back verbatim; when it is empty, LLMTR's validator
# 400s with 'String must contain at least 1 character(s)' — measured live, right after the tool.

def test_normalize_drops_empty_reasoning_content_only():
    from server import _normalize_openai_chat_body
    body = json.dumps({"messages": [
        {"role": "assistant", "content": None, "reasoning_content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "assistant", "content": "hi", "reasoning_content": "kept: real thinking"},
    ]}).encode()
    out = json.loads(_normalize_openai_chat_body(body))
    assert "reasoning_content" not in out["messages"][0]
    assert out["messages"][1]["reasoning_content"] == "kept: real thinking"


# ── stream_options drop-on-rejection (qwen x LLMTR gpt-5.x, 2026-08-27) ─────────────────────────
# LLMTR's openai/gpt-5.x upstream 400s any streaming body carrying stream_options, with only the
# generic 'model provider rejected the request' — so the relay retries a 400 once without the
# field and remembers the fix only when that retry succeeded.

def test_relay_retries_a_stream_options_rejection_and_sticks():
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(body)
            if "stream_options" in body:
                data = b'{"error": {"message": "The model provider rejected the request."}}'
                self.send_response(400)
            else:
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
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        body = json.dumps({"model": "m", "stream": True, "stream_options": {"include_usage": True},
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json"})
        assert json.loads(urllib.request.urlopen(req, timeout=10).read()) == {"ok": True}
        assert len(calls) == 2 and "stream_options" not in calls[1]
        urllib.request.urlopen(urllib.request.Request(
            base + "/chat/completions", data=body, method="POST",
            headers={"authorization": f"Bearer {tok}", "content-type": "application/json"}), timeout=10)
        assert len(calls) == 3 and "stream_options" not in calls[2]   # sticky: no second 400
    finally:
        up.shutdown()

# ── cumulative repairs in one request (qwen x LLMTR gpt-5.6, 2026-08-27) ────────────────────────
# A single request can need TWO named fixes: the first 400 (generic) goes away with
# stream_options dropped, and only then does the upstream surface "Function tools with
# reasoning_effort are not supported ... set reasoning_effort to 'none'". Three attempts let
# both land; the reasoning_effort fix sticks per (route, model), never route-wide.

def test_relay_applies_two_repairs_cumulatively_and_scopes_effort_per_model():
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(body)
            if "stream_options" in body:
                data = b'{"error": {"message": "The model provider rejected the request."}}'
                self.send_response(400)
            elif body["model"] == "gpt-5.6-luna" and body.get("reasoning_effort") != "none":
                data = (b'{"error": {"message": "Function tools with reasoning_effort are not '
                        b'supported for gpt-5.6-luna in /v1/chat/completions. To use function '
                        b'tools, use /v1/responses or set reasoning_effort to \'none\'."}}')
                self.send_response(400)
            else:
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
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        mk = lambda model: json.dumps({"model": model, "stream": True,
                                       "stream_options": {"include_usage": True},
                                       "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = lambda b: urllib.request.Request(base + "/chat/completions", data=b, method="POST",
                                               headers={"authorization": f"Bearer {tok}",
                                                        "content-type": "application/json"})
        assert json.loads(urllib.request.urlopen(req(mk("gpt-5.6-luna")), timeout=10).read()) == {"ok": True}
        # attempt 0: generic 400 -> drop stream_options; attempt 1: named 400 -> effort none; attempt 2: OK
        assert len(calls) == 3
        assert "stream_options" not in calls[1] and calls[2]["reasoning_effort"] == "none"
        # a DIFFERENT model on the same route inherits the stream_options drop but NOT the effort
        assert json.loads(urllib.request.urlopen(req(mk("other-model")), timeout=10).read()) == {"ok": True}
        assert calls[-1]["model"] == "other-model" and "reasoning_effort" not in calls[-1]
        assert "stream_options" not in calls[-1] and len(calls) == 4     # no extra 400 round-trip
    finally:
        up.shutdown()

# ── a local model server's discovery probes (hermes x any provider, 2026-10-14) ─────────────────
# hermes calls the loopback relay a local model server and asks it Ollama/llama.cpp/LM Studio/vLLM
# discovery paths before its first model call: 10 on OpenRouter, 22 on Anthropic, each a provider
# 404. On a provider that is not itself a local server the relay answers them at once; a person's own
# local server behind a custom connection still gets them, as before.

_PROBES = [("GET", "/api/tags"), ("GET", "/v1/props"), ("GET", "/props"), ("GET", "/version"),
           ("GET", "/api/v1/models"), ("POST", "/api/show")]


def _call(base, tok, method, path):
    root = base.removesuffix("/v1")
    req = urllib.request.Request(root + path, data=b'{"name": "m"}' if method == "POST" else None,
                                 method=method, headers={"authorization": f"Bearer {tok}",
                                                         "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_upstream_is_local_server_follows_hermes():
    from server import _upstream_is_local_server as local
    for base in ("http://127.0.0.1:11434/v1", "http://localhost:8080", "http://ollama:11434/v1",
                 "http://host.docker.internal:11434/v1", "http://192.168.1.20:8000/v1",
                 "http://10.0.0.5/v1", "http://172.20.0.3:1234", "http://100.101.2.3:11434",
                 "http://[::1]:8080/v1", "http://169.254.1.1"):
        assert local(base), base
    for base in ("https://openrouter.ai/api/v1", "https://api.anthropic.com/v1",
                 "https://x.openai.azure.com/openai/v1", "https://8.8.8.8/v1", "https://provider.invalid/v1"):
        assert not local(base), base


def test_probes_are_answered_by_the_relay_when_the_provider_is_not_local():
    # provider.invalid never resolves: an answer can only have come from the relay itself
    base, tok = _hermes_relay_route("https://provider.invalid/v1", "sk-real")
    for method, path in _PROBES:
        status, data = _call(base, tok, method, path)
        assert status == 404, (method, path, status)
        assert json.loads(data)["error"]["message"] == "Not found"
    # the model listing is not a probe: it still goes upstream (and fails to resolve here)
    status, data = _call(base, tok, "GET", "/v1/models")
    assert status != 404 or b"Not found" not in data


def test_probes_still_reach_a_local_server_behind_a_custom_connection():
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _answer(self):
            seen.append((self.command, self.path))
            data = b'{"models": []}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            self._answer()

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length") or 0))
            self._answer()

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        for method, path in _PROBES:
            assert _call(base, tok, method, path)[0] == 200, (method, path)
        assert len(seen) == len(_PROBES)
    finally:
        up.shutdown()


# ── the caller's trace context (#473) ─────────────────────────────────────────────────────────
# The gateway hands the runner the caller's W3C traceparent/tracestate. The relay puts a CHILD of
# the traceparent on the model calls it forwards — the same trace id, a new span id, so the
# provider's log joins the caller's trace and this hop is a span of its own. Only these two
# headers leave the box: `baggage` carries the caller's own data and never goes out. A malformed
# value is dropped, never forwarded, and never fails the turn.

TRACE_PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def _relay_with_trace(upstream_port: int, trace: dict | None):
    """Register a route for a turn carrying `trace`, and return (relay base, placeholder token)."""
    token = rs._TURN_TRACE.set(trace or {})
    try:
        return rs._hermes_relay_route(f"http://127.0.0.1:{upstream_port}/v1", "sk-real")
    finally:
        rs._TURN_TRACE.reset(token)


def _relay_upstream(seen: dict):
    """A fake provider that records the headers it was sent."""
    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            seen["traceparent"] = self.headers.get("traceparent")
            seen["tracestate"] = self.headers.get("tracestate")
            seen["baggage"] = self.headers.get("baggage")
            self.rfile.read(int(self.headers.get("content-length") or 0))
            data = b'{"ok": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    return Upstream


def test_a_relayed_call_carries_a_child_of_the_callers_traceparent():
    seen = {}
    up = ThreadingHTTPServer(("127.0.0.1", 0), _relay_upstream(seen))
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _relay_with_trace(up.server_address[1], {"traceparent": TRACE_PARENT})
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    finally:
        up.shutdown()
    got = seen.get("traceparent")
    assert got, "the relayed call carried no traceparent at all"
    parts = got.split("-")
    assert len(parts) == 4, f"the relayed traceparent is not a W3C traceparent: {got!r}"
    version, trace_id, span_id, flags = parts
    assert version == "00", f"the child changed the trace version: {got!r}"
    assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736", f"the child lost the caller's trace: {got!r}"
    assert span_id != "00f067aa0ba902b7", f"the relay forwarded the caller's own span id: {got!r}"
    assert len(span_id) == 16 and span_id == span_id.lower() and all(c in "0123456789abcdef" for c in span_id), (
        f"the child's span id is not 16 lowercase hex characters: {got!r}")
    assert flags == "01", f"the child changed the sampled flag: {got!r}"


def test_a_turn_with_no_trace_context_sends_no_traceparent():
    seen = {}
    up = ThreadingHTTPServer(("127.0.0.1", 0), _relay_upstream(seen))
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _relay_with_trace(up.server_address[1], None)
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    finally:
        up.shutdown()
    assert not seen.get("traceparent"), f"a turn with no trace context still sent {seen.get('traceparent')!r}"


def test_a_malformed_traceparent_is_not_forwarded():
    seen = {}
    up = ThreadingHTTPServer(("127.0.0.1", 0), _relay_upstream(seen))
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _relay_with_trace(up.server_address[1], {"traceparent": "not-a-traceparent"})
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    finally:
        up.shutdown()
    assert not seen.get("traceparent"), f"a malformed traceparent was forwarded as {seen.get('traceparent')!r}"


def test_the_turn_validates_the_trace_context_it_is_handed():
    """The runner is the last place before a provider sees the value, so it checks it itself: a
    header nobody can read is worth less than a turn."""
    assert rs._trace_context(TRACE_PARENT, "") == {"traceparent": TRACE_PARENT}
    assert rs._trace_context(TRACE_PARENT.upper(), "") == {"traceparent": TRACE_PARENT}
    for bad in ("not-a-traceparent",
                "00-" + "0" * 32 + "-00f067aa0ba902b7-01",     # an all-zero trace-id
                "00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01",   # an all-zero span-id
                "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",  # version ff
                "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",     # no flags
                ""):
        assert rs._trace_context(bad, "vendor=1") == {}, f"{bad!r} was accepted as a trace context"
    # A tracestate is only ever read with a traceparent, and a malformed member drops the
    # tracestate alone — never the traceparent beside it.
    assert rs._trace_context("", "vendor=1") == {}
    assert rs._trace_context(TRACE_PARENT, "vendor=1") == {"traceparent": TRACE_PARENT, "tracestate": "vendor=1"}
    assert rs._trace_context(TRACE_PARENT, "not a member") == {"traceparent": TRACE_PARENT}
    # The spec's own rules for a member: a value may hold a space anywhere but its last character
    # and must not be empty, and only one entry per key may exist.
    assert rs._trace_context(TRACE_PARENT, "vendor=a b") == {"traceparent": TRACE_PARENT,
                                                             "tracestate": "vendor=a b"}
    assert rs._trace_context(TRACE_PARENT, "vendor=") == {"traceparent": TRACE_PARENT}
    assert rs._trace_context(TRACE_PARENT, "vendor=1,vendor=2") == {"traceparent": TRACE_PARENT}
    assert rs._trace_context(TRACE_PARENT, "a=1,b=2") == {"traceparent": TRACE_PARENT,
                                                           "tracestate": "a=1,b=2"}
    # A newer version may carry fields this code does not know yet: the spec parses the first 55
    # characters and ignores the rest, so the trace is kept. Version `00` has no trailing data.
    assert rs._trace_context("01-" + "4bf92f3577b34da6a3ce929d0e0e4736" + "-00f067aa0ba902b7-01-extra",
                             "") == {"traceparent": "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    assert rs._trace_context(TRACE_PARENT + "-extra", "") == {}


def test_the_turn_hands_the_trace_context_to_the_cli(monkeypatch, tmp_path):
    """The CLI's own environment carries it, so a tool in the turn that speaks OpenTelemetry joins
    the caller's trace."""
    launched = []
    started = threading.Event()

    def _fake(*args):
        launched.append(args)
        started.set()
    monkeypatch.setattr(rs, "_run_hermes_bg", _fake)
    cwd = tmp_path / "w"
    cwd.mkdir()
    rs.turn(rs.TurnReq(backend="hermes", provider="anthropic", model="claude-haiku-4.5", prompt="hi",
                        auth=Auth(api_key="sk-test", base_url="https://proxy.example/v1"),
                        cwd=str(cwd), traceparent=TRACE_PARENT, tracestate="vendor=1"))
    assert started.wait(10), "the hermes turn was never launched"
    env = launched[-1][2]
    assert env.get("TRACEPARENT") == TRACE_PARENT, f"the CLI's env carries {env.get('TRACEPARENT')!r}"
    assert env.get("TRACESTATE") == "vendor=1", f"the CLI's env carries {env.get('TRACESTATE')!r}"


def test_a_turn_with_no_trace_context_gives_the_cli_none(monkeypatch, tmp_path):
    launched = []
    started = threading.Event()

    def _fake(*args):
        launched.append(args)
        started.set()
    monkeypatch.setattr(rs, "_run_hermes_bg", _fake)
    cwd = tmp_path / "w"
    cwd.mkdir()
    rs.turn(rs.TurnReq(backend="hermes", provider="anthropic", model="claude-haiku-4.5", prompt="hi",
                        auth=Auth(api_key="sk-test", base_url="https://proxy.example/v1"),
                        cwd=str(cwd)))
    assert started.wait(10), "the hermes turn was never launched"
    env = launched[-1][2]
    assert "TRACEPARENT" not in env and "TRACESTATE" not in env, (
        f"a turn with no trace context still got {env.get('TRACEPARENT')!r} / {env.get('TRACESTATE')!r}")


def test_every_route_of_the_turn_carries_the_trace_context(monkeypatch):
    """Every way a route is registered must carry the turn's traceparent, not just the one the
    hermes builders use. The relay mints the provider's child span from the route's flag, so a
    route registered without it sends the provider a request the caller's trace cannot be joined
    to — and the route that missed it would be whichever base nobody tested."""
    routes: dict = {}
    monkeypatch.setattr(rs, "_HERMES_RELAY", {"server": None, "port": 0, "routes": routes, "lock": threading.Lock()})
    token = rs._TURN_TRACE.set({"traceparent": TRACE_PARENT, "tracestate": "vendor=1"})
    try:
        rs._hermes_relay_route("https://proxy.example/v1", "sk-test")
        rs._qoder_relay_route("https://proxy.example/api/v1/cloud", "pat-test")
        rs._bedrock_anthropic_route("https://bedrock.example", "sk-test")
        rs._gemini_relay_route("https://generativelanguage.example", "sk-test", "gemini-4-argon", "gemini-4-argon")
        rs._systemone_relay_route("openrouter", "https://openrouter.example/api/v1", "sk-test")
    finally:
        rs._TURN_TRACE.reset(token)

    assert routes, "no route was registered"
    for tok, (_base, _key, flags) in routes.items():
        assert flags.get("traceparent") == TRACE_PARENT, (
            f"the route {tok} carries {flags.get('traceparent')!r} instead of the caller's traceparent")


def _relay_call(headers: dict | None = None) -> dict:
    """Send one call through the relay to a fake provider, and return what the provider saw."""
    seen: dict = {}
    up = ThreadingHTTPServer(("127.0.0.1", 0), _relay_upstream(seen))
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _relay_with_trace(up.server_address[1], {"traceparent": TRACE_PARENT,
                                                             "tracestate": "vendor=1"})
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json",
                                              **(headers or {})})
        urllib.request.urlopen(req, timeout=10).read()
    finally:
        up.shutdown()
    return seen


def test_a_client_cannot_replace_the_callers_trace_id():
    """The turn's context is the trace's root: the caller's trace id is never taken from the
    client. A client that sends a traceparent of its own would otherwise send the provider a
    request under a different trace, which the caller's trace cannot be joined to."""
    foreign = "00-11111111111111111111111111111111-2222222222222222-01"
    seen = _relay_call({"traceparent": foreign})
    got = seen.get("traceparent")
    assert got, "the relayed call carried no traceparent at all"
    assert got.split("-")[1] == "4bf92f3577b34da6a3ce929d0e0e4736", (
        f"the provider got {got!r}: the client's own trace id replaced the caller's")
    assert got.split("-")[1] != foreign.split("-")[1], f"the provider got the client's trace: {got!r}"


def test_a_clients_own_child_of_the_callers_trace_is_the_parent():
    """A CLI that read TRACEPARENT from its environment has already made a child of the caller's
    span, and the provider's request belongs under THAT span: the same trace id, a new span id."""
    child = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    seen = _relay_call({"traceparent": child})
    got = seen.get("traceparent")
    assert got, "the relayed call carried no traceparent at all"
    assert got.split("-")[1] == "4bf92f3577b34da6a3ce929d0e0e4736", f"the provider got {got!r}"
    assert got.split("-")[2] != "00f067aa0ba902b7", f"the relay forwarded the CLI's own span id: {got!r}"


def test_a_malformed_client_traceparent_does_not_reach_the_provider():
    """A header nobody can read is worth less than a turn: the client's own value is dropped and
    the provider gets the caller's trace, not the client's all-zero one."""
    seen = _relay_call({"traceparent": "00-" + "0" * 32 + "-00f067aa0ba902b7-01"})
    got = seen.get("traceparent")
    assert got, "the relayed call carried no traceparent at all"
    assert got.split("-")[1] == "4bf92f3577b34da6a3ce929d0e0e4736", f"the provider got {got!r}"


def test_baggage_never_reaches_the_provider():
    """`baggage` carries the caller's own data to whoever reads it, and it does not leave the
    box — not even the client's own."""
    seen = _relay_call({"baggage": "userid=secret,tenant=acme"})
    assert not seen.get("baggage"), f"the provider got baggage {seen.get('baggage')!r}"


def test_the_callers_tracestate_reaches_the_provider():
    """The tracestate is the caller's vendor state for that trace, and the provider is the other
    end of it."""
    seen = _relay_call()
    assert seen.get("tracestate") == "vendor=1", f"the provider got {seen.get('tracestate')!r}"


def test_a_turn_with_no_trace_context_leaves_the_clients_headers_alone():
    """No header in means nothing out: a turn with no trace context changes nothing, so a client
    that traces already keeps the span it made."""
    seen: dict = {}
    up = ThreadingHTTPServer(("127.0.0.1", 0), _relay_upstream(seen))
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _relay_with_trace(up.server_address[1], None)
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}",
                                              "content-type": "application/json",
                                              "traceparent": TRACE_PARENT})
        urllib.request.urlopen(req, timeout=10).read()
    finally:
        up.shutdown()
    assert seen.get("traceparent") == TRACE_PARENT, (
        f"a turn with no trace context changed the client's own header: {seen.get('traceparent')!r}")
