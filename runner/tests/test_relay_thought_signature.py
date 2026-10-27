"""Gemini 3 thought signatures through the loopback relay (2026-09-06)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _delta(cid, sig=None):
    tc = {"id": cid, "type": "function", "function": {"name": "write_file", "arguments": "{}"}}
    if sig:
        tc["extra_content"] = {"google": {"thought_signature": sig}}
    return {"object": "chat.completion.chunk", "choices": [{"delta": {"tool_calls": [tc]}}]}


def _replay():
    return json.dumps({"model": "gemini-3.6-flash", "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            {"id": "call_x", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            {"id": "call_k", "type": "function", "function": {"name": "f", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "kept"}}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"}]}).encode()


def test_signatures_are_read_off_a_chunk_a_whole_message_and_an_sse_line():
    assert server._google_signatures_in(_delta("call_1", "sigA")) == [("call_1", "sigA")]
    assert server._google_signatures_in(_delta("call_1")) == []
    whole = {"object": "chat.completion", "choices": [{"message": {"tool_calls": [
        {"id": "call_2", "type": "function", "function": {"name": "f", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "sigB"}}}]}}]}
    assert server._google_signatures_in(whole) == [("call_2", "sigB")]
    line = b"data: " + json.dumps(_delta("call_9", "sigZ")).encode()
    assert server._google_signatures_in_line(line) == [("call_9", "sigZ")]
    assert server._google_signatures_in_line(b"data: [DONE]") == []
    assert server._google_signatures_in_line(b'data: {"choices": [{"delta": {"content": "thought_signature"}}]}') == []


def test_the_replay_carries_the_seen_signature_or_the_sentinel():
    sigs = {"call_1": "sigA"}
    out = json.loads(server._google_with_signatures(_replay(), sigs))
    calls = out["messages"][1]["tool_calls"]
    assert calls[0]["extra_content"] == {"google": {"thought_signature": "sigA"}}
    assert calls[1]["extra_content"] == {"google": {"thought_signature": server._GOOGLE_SIG_SKIP}}
    assert calls[2]["extra_content"] == {"google": {"thought_signature": "kept"}}
    assert out["messages"][2] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    untouched = b'{"model": "gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}]}'
    assert server._google_with_signatures(untouched, sigs) is untouched
    assert server._google_with_signatures(b"not json tool_calls", sigs) == b"not json tool_calls"


def test_an_aggregator_that_streams_signatures_gets_them_back_on_the_replay():
    """Not Google's host: an aggregator (Vercel's gateway) that serves Gemini 3 streams the same
    signature, and a replay without it is not refused with the 400 that teaches the relay — it comes
    back as an answer with no content and finish_reason "error" (measured 2026-10-24, docker-agent,
    gemini-3.5-flash-lite through Vercel, 8 of 12 artifact turns). The first signature the route
    sees marks it, and the next request carries the signature back."""
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    got: list[dict] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            line = b"data: " + json.dumps(_delta("call_1", "sigA")).encode() + b"\n\ndata: [DONE]\n\n"
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(line)))
            self.end_headers()
            self.wfile.write(line)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")
        headers = {"authorization": f"Bearer {tok}", "content-type": "application/json"}

        def post(body: bytes) -> None:
            urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                                          headers=headers), timeout=10).read()

        post(json.dumps({"model": "google/gemini-3.5-flash-lite", "stream": True,
                         "messages": [{"role": "user", "content": "hi"}]}).encode())
        # call_1's tool call replayed WITHOUT its extra_content, as an OpenAI-shaped client does, to the model
        # that made it (another model's goes as the sentinel: test_relay_signature_maker.py)
        post(_replay().replace(b'"gemini-3.6-flash"', b'"google/gemini-3.5-flash-lite"'))
        calls = {tc["id"]: tc for m in got[1]["messages"] for tc in m.get("tool_calls") or []}
        assert calls["call_1"]["extra_content"]["google"]["thought_signature"] == "sigA"
        assert calls["call_k"]["extra_content"]["google"]["thought_signature"] == "kept"
        assert calls["call_x"]["extra_content"]["google"]["thought_signature"] == server._GOOGLE_SIG_SKIP
    finally:
        up.shutdown()


def test_a_route_that_never_saw_a_signature_is_left_alone():
    """A non-Google upstream whose answers carry no signature: replays go through as the client sent them."""
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    got: list[dict] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            line = b"data: " + json.dumps(_delta("call_1")).encode() + b"\n\ndata: [DONE]\n\n"
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(line)))
            self.end_headers()
            self.wfile.write(line)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")
        headers = {"authorization": f"Bearer {tok}", "content-type": "application/json"}
        for body in (json.dumps({"model": "gpt-5.4", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode(),
                     _replay()):
            urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                                          headers=headers), timeout=10).read()
        calls = {tc["id"]: tc for m in got[1]["messages"] for tc in m.get("tool_calls") or []}
        assert "extra_content" not in calls["call_1"] and "extra_content" not in calls["call_x"]
    finally:
        up.shutdown()
