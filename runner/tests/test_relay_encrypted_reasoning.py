"""OpenRouter's encrypted reasoning through the loopback relay (2026-10-25).

OpenRouter carries a Gemini 3 tool call's thought signature as a `reasoning_details` entry of type
`reasoning.encrypted` whose `id` is the tool call's id, and takes it back on the replayed assistant
message. docker-agent sent none back in 69 requests, and 3 of 8 artifact turns on
gemini-3.5-flash-lite ended MALFORMED_FUNCTION_CALL, finish_reason "error"; with the relay putting
them back, 8 of 8 passed. The stream line below is the shape OpenRouter sent, its data shortened."""
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

ENC = {"type": "reasoning.encrypted", "data": "AY89a19r0ZY+kzuS", "format": "google-gemini-v1",
       "id": "call_1754831", "index": 0}


def _chunk(details, tool_id=None):
    delta = {"role": "assistant", "reasoning_details": details}
    if tool_id:
        delta["tool_calls"] = [{"index": 0, "id": tool_id, "type": "function",
                                "function": {"name": "update_todos", "arguments": "{}"}}]
    return {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta}]}


def _replay(own=None):
    second = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_other", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}
    if own is not None:
        second["reasoning_details"] = own
    return json.dumps({"model": "google/gemini-3.5-flash-lite", "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1754831", "type": "function", "function": {"name": "update_todos", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1754831", "content": "ok"},
        second,
        {"role": "tool", "tool_call_id": "call_other", "content": "ok"}]}).encode()


def test_entries_are_read_off_a_line_and_a_whole_answer_only_when_they_name_a_call():
    line = b"data: " + json.dumps(_chunk([ENC], "call_1754831")).encode()
    assert server._encrypted_reasoning_in_line(line) == [ENC]
    text = {"type": "reasoning.text", "text": "Generating file content"}
    no_id = dict(ENC, id=None)
    assert server._encrypted_reasoning_in_line(b"data: " + json.dumps(_chunk([text, no_id])).encode()) == []
    assert server._encrypted_reasoning_in_line(b"data: [DONE]") == []
    whole = {"object": "chat.completion", "choices": [{"message": {"reasoning_details": [ENC]}}]}
    assert server._encrypted_reasoning_in(whole) == [ENC]


def test_the_replay_carries_each_call_s_entry_and_leaves_the_rest_as_written():
    out = json.loads(server._with_encrypted_reasoning(_replay(own=[{"type": "reasoning.text", "text": "x"}]),
                                                      {"call_1754831": ENC}))
    assert out["messages"][1]["reasoning_details"] == [ENC]
    assert out["messages"][3]["reasoning_details"] == [{"type": "reasoning.text", "text": "x"}]   # the client's own
    untouched = b'{"model": "m", "messages": [{"role": "user", "content": "hi"}]}'
    assert server._with_encrypted_reasoning(untouched, {"call_1754831": ENC}) is untouched
    assert server._with_encrypted_reasoning(b"not json tool_calls", {}) == b"not json tool_calls"
    unknown = server._with_encrypted_reasoning(_replay(), {"call_elsewhere": ENC})
    assert all("reasoning_details" not in m for m in json.loads(unknown)["messages"])


def _route(answer: bytes, ctype: str):
    got: list[dict] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")
    headers = {"authorization": f"Bearer {tok}", "content-type": "application/json"}

    def post(body: bytes) -> None:
        urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                                      headers=headers), timeout=10).read()
    return up, got, post


def test_a_streamed_entry_comes_back_on_the_message_that_made_the_call():
    sse = b"data: " + json.dumps(_chunk([ENC], "call_1754831")).encode() + b"\n\ndata: [DONE]\n\n"
    up, got, post = _route(sse, "text/event-stream")
    try:
        post(json.dumps({"model": "google/gemini-3.5-flash-lite", "stream": True,
                         "messages": [{"role": "user", "content": "hi"}]}).encode())
        post(_replay())      # the call replayed WITHOUT its reasoning_details, as docker-agent does
        msgs = got[1]["messages"]
        assert msgs[1]["reasoning_details"] == [ENC]
        assert "reasoning_details" not in msgs[3]          # a call the relay saw no entry for
    finally:
        up.shutdown()


def test_an_entry_in_a_whole_answer_comes_back_too():
    whole = json.dumps({"object": "chat.completion", "choices": [{"index": 0, "finish_reason": "tool_calls",
                        "message": {"role": "assistant", "reasoning_details": [ENC], "tool_calls": [
                            {"id": "call_1754831", "type": "function",
                             "function": {"name": "update_todos", "arguments": "{}"}}]}}]}).encode()
    up, got, post = _route(whole, "application/json")
    try:
        post(json.dumps({"model": "google/gemini-3.5-flash-lite",
                         "messages": [{"role": "user", "content": "hi"}]}).encode())
        post(_replay())
        assert got[1]["messages"][1]["reasoning_details"] == [ENC]
    finally:
        up.shutdown()


def test_a_route_whose_answers_carry_no_entry_is_left_alone():
    sse = b"data: " + json.dumps(_chunk([{"type": "reasoning.text", "text": "t"}], "call_1754831")).encode() \
        + b"\n\ndata: [DONE]\n\n"
    up, got, post = _route(sse, "text/event-stream")
    try:
        post(json.dumps({"model": "gpt-5.4", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode())
        post(_replay())
        assert json.loads(_replay()) == got[1]
    finally:
        up.shutdown()
