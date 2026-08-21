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
from server import _hermes_relay_route, _normalize_openai_chat_body  # noqa: E402


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
