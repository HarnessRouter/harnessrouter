"""The Bedrock-Anthropic adapter (custom integrations, anthropic format x bedrock-runtime).

Bedrock has no bearer-auth /v1/messages surface — the path 200s an UnknownOperationException
envelope (measured 2026-08-27). InvokeModel takes the same Anthropic Messages body with three
differences the relay applies in flight: model moves to the URL, anthropic_version moves into
the body, and streaming answers in AWS binary eventstream whose frame payloads wrap the real
anthropic SSE events as base64. These tests pin the frame parser against hand-built frames and
run both directions through the real relay against a fake bedrock-runtime upstream.
"""
import base64
import io
import json
import pathlib
import struct
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import Auth, _adapt_custom_auth, _aws_eventstream_frames, _bedrock_anthropic_route  # noqa: E402


def _frame(event_json: dict) -> bytes:
    payload = json.dumps({"bytes": base64.b64encode(json.dumps(event_json).encode()).decode()}).encode()
    name = b":event-type"
    headers = bytes([len(name)]) + name + bytes([7]) + struct.pack(">H", 5) + b"chunk"
    total = 12 + len(headers) + len(payload) + 4
    return (struct.pack(">I", total) + struct.pack(">I", len(headers)) + b"\x00" * 4
            + headers + payload + b"\x00" * 4)


def test_eventstream_parser_roundtrip():
    events = [{"type": "message_start", "message": {"id": "m1"}},
              {"type": "content_block_delta", "delta": {"text": "hi"}},
              {"type": "message_stop"}]
    blob = b"".join(_frame(e) for e in events)
    out = []
    for headers, payload in _aws_eventstream_frames(io.BytesIO(blob)):
        assert headers[":event-type"] == "chunk"
        out.append(json.loads(base64.b64decode(json.loads(payload)["bytes"])))
    assert out == events


def test_adapt_custom_auth_matches_only_bedrock_anthropic():
    a = Auth(api_key="k", base_url="https://bedrock-runtime.us-west-2.amazonaws.com",
             api_format="anthropic")
    b = _adapt_custom_auth(a)
    assert b.base_url.startswith("http://127.0.0.1:") and b.api_key.startswith("hr-relay-")
    # non-bedrock hosts and openai format pass through untouched
    for a2 in (Auth(api_key="k", base_url="https://llmtr.com", api_format="anthropic"),
               Auth(api_key="k", base_url="https://bedrock-runtime.us-west-2.amazonaws.com",
                    api_format="openai")):
        assert _adapt_custom_auth(a2) is a2


def test_adapter_translates_both_directions():
    seen = {}

    class FakeBedrock(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            seen["path"] = self.path
            seen["auth"] = self.headers.get("authorization")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            if self.path.endswith("/invoke"):
                data = json.dumps({"type": "message", "content": [{"type": "text", "text": "ok"}],
                                   "stop_reason": "end_turn"}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:   # invoke-with-response-stream
                blob = b"".join(_frame(e) for e in (
                    {"type": "message_start", "message": {"id": "m1"}},
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
                    {"type": "message_stop"}))
                self.send_response(200)
                self.send_header("content-type", "application/vnd.amazon.eventstream")
                self.send_header("content-length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), FakeBedrock)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _bedrock_anthropic_route(f"http://127.0.0.1:{up.server_address[1]}", "bedrock-key")
        body = {"model": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "max_tokens": 8,
                "messages": [{"role": "user", "content": "hi"}]}
        # non-streaming
        req = urllib.request.Request(base + "/messages", data=json.dumps(body).encode(),
                                     method="POST", headers={"authorization": f"Bearer {tok}",
                                                             "content-type": "application/json"})
        out = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert out["type"] == "message" and out["content"][0]["text"] == "ok"
        assert seen["path"] == "/model/us.anthropic.claude-haiku-4-5-20251001-v1%3A0/invoke"
        assert seen["auth"] == "Bearer bedrock-key"          # real key injected upstream
        assert "model" not in seen["body"] and "stream" not in seen["body"]
        assert seen["body"]["anthropic_version"] == "bedrock-2023-05-31"
        # streaming: eventstream in, ordinary SSE out
        req2 = urllib.request.Request(base + "/messages",
                                      data=json.dumps({**body, "stream": True}).encode(),
                                      method="POST", headers={"authorization": f"Bearer {tok}",
                                                              "content-type": "application/json"})
        r2 = urllib.request.urlopen(req2, timeout=10)
        assert "text/event-stream" in r2.headers.get("content-type", "")
        sse = r2.read().decode()
        assert seen["path"].endswith("/invoke-with-response-stream")
        assert "event: message_start" in sse and "event: content_block_delta" in sse
        assert '"text": "ok"' in sse or '"text":"ok"' in sse
        assert "event: message_stop" in sse
    finally:
        up.shutdown()


def test_pop_json_path_handles_phantom_segments_and_list_siblings():
    from server import _pop_json_path
    # Bedrock reports tools.0.custom.eager_input_streaming for a tool whose JSON has no
    # "custom" wrapper — the validator's union discriminator leaks into the path. And a client
    # that sends the field sends it on EVERY tool, so one complaint strips all of them.
    o = {"tools": [{"name": "a", "eager_input_streaming": True},
                   {"name": "b", "eager_input_streaming": False}], "keep": 1}
    assert _pop_json_path(o, "tools.0.custom.eager_input_streaming")
    assert all("eager_input_streaming" not in t for t in o["tools"])
    assert o["tools"][0]["name"] == "a" and o["keep"] == 1
    assert _pop_json_path(o, "keep") and "keep" not in o
    assert not _pop_json_path(o, "tools.0.custom.eager_input_streaming")   # already gone


def test_adapter_matches_messages_with_query_string():
    # claude-code sends /v1/messages?beta=true on streaming requests; the raw-tail match let
    # those fall through to a generic forward against a host with no such route.
    seen = {}

    class FakeBedrock(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            seen["path"] = self.path
            data = b'{"type": "message", "content": []}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), FakeBedrock)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _bedrock_anthropic_route(f"http://127.0.0.1:{up.server_address[1]}", "k")
        body = json.dumps({"model": "m", "max_tokens": 8, "messages": []}).encode()
        req = urllib.request.Request(base + "/messages?beta=true", data=body, method="POST",
                                     headers={"authorization": f"Bearer {tok}"})
        out = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert out["type"] == "message"
        assert seen["path"] == "/model/m/invoke"     # adapted, not blind-forwarded
    finally:
        up.shutdown()
