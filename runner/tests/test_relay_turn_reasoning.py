"""On a route that asks for it (dcode's), an earlier turn is replayed as plain content (2026-10-25).

After a model switch dcode replays what another model minted, and the upstream refused it: "The encrypted
content for item rs_tmp_… could not be verified" (Gemini to gpt-6.1-sol, OpenRouter), "Unknown parameter:
'input[2].status'" and "Item with id 'rs_…' not found" (grok-4.3 to gpt-6.1-sol, TokenRouter). This turn's
items go as they are; an earlier turn's reasoning items are left out and its other items lose id and status."""
import json
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

DONE = {"type": "response.output_item.done", "output_index": 0,
        "item": {"type": "reasoning", "id": "rs_this_turn", "encrypted_content": "gAAAA-this", "summary": []}}
MSG_DONE = {"type": "response.output_item.done", "output_index": 1,
            "item": {"type": "message", "id": "msg_this_turn", "role": "assistant", "content": []}}


def _request(model="openai/gpt-6.1-sol"):
    return json.dumps({"model": model, "stream": True, "input": [
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "reasoning", "id": "rs_tmp_earlier", "encrypted_content": "AY89a1-gemini", "status": "in_progress",
         "summary": [{"type": "summary_text", "text": "The user asks"}]},
        {"type": "message", "role": "assistant", "id": "msg_tmp_1", "status": "completed",
         "content": [{"type": "output_text", "text": "M1"}]},
        {"type": "function_call", "id": "fc_earlier", "call_id": "c1", "name": "write_file", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        {"type": "reasoning", "id": "rs_this_turn", "encrypted_content": "gAAAA-this", "summary": []},
        {"type": "message", "role": "assistant", "id": "msg_this_turn", "content": [{"type": "output_text", "text": "M2"}]}]}).encode()


def test_output_item_ids_are_read_off_an_event_a_completed_response_and_a_whole_one():
    assert server._output_item_ids_in(DONE) == ["rs_this_turn"]
    assert server._output_item_ids_in(MSG_DONE) == ["msg_this_turn"]
    done = {"type": "response.completed", "response": {"model": "m", "output": [
        {"type": "reasoning", "id": "rs_a"}, {"type": "message", "id": "msg_a"}]}}
    assert server._output_item_ids_in(done) == ["rs_a", "msg_a"]
    assert server._output_item_ids_in({"object": "response", "output": [{"type": "function_call", "id": "fc_b"}]}) == ["fc_b"]
    assert server._output_item_ids_in_line(b"data: " + json.dumps(DONE).encode()) == ["rs_this_turn"]
    assert server._output_item_ids_in_line(b'data: {"type": "response.output_text.delta", "delta": "x"}') == []


def test_an_earlier_turn_is_plain_content_and_this_turn_is_as_it_was():
    out = json.loads(server._earlier_turns_as_content(_request(), {"rs_this_turn", "msg_this_turn"}))["input"]
    assert [i.get("type") for i in out] == ["message", "message", "function_call", "function_call_output",
                                            "reasoning", "message"]                       # the earlier reasoning left out
    assert out[1] == {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "M1"}]}
    assert out[2] == {"type": "function_call", "call_id": "c1", "name": "write_file", "arguments": "{}"}
    assert out[4]["encrypted_content"] == "gAAAA-this" and out[5]["id"] == "msg_this_turn"   # this turn's, whole
    plain = b'{"model": "m", "input": [{"type": "message", "role": "user", "content": "hi"}]}'
    assert server._earlier_turns_as_content(plain, set()) is plain


def _route(**flags):
    got: list[dict] = []
    sse = b"\n\n".join(b"data: " + json.dumps(e).encode() for e in (DONE, MSG_DONE)) + b"\n\ndata: [DONE]\n\n"

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(sse)))
            self.end_headers()
            self.wfile.write(sse)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key", **flags)
    headers = {"authorization": f"Bearer {tok}", "content-type": "application/json"}

    def post(body: bytes) -> None:
        urllib.request.urlopen(urllib.request.Request(base + "/responses", data=body, method="POST",
                                                      headers=headers), timeout=10).read()
    return up, got, post


def test_a_route_that_asks_keeps_this_turn_s_items_once_they_are_minted():
    up, got, post = _route(turn_reasoning_only=True)
    try:
        post(_request())          # nothing is this turn's yet: every id-bearing item is an earlier turn's
        assert not any(i.get("id") for i in got[0]["input"])
        post(_request())          # the first answer minted rs_this_turn and msg_this_turn
        ids = [i.get("id") for i in got[1]["input"] if i.get("id")]
        assert ids == ["rs_this_turn", "msg_this_turn"]
    finally:
        up.shutdown()


def test_a_route_that_does_not_ask_is_left_alone():
    up, got, post = _route()
    try:
        post(_request())
        assert json.loads(_request()) == got[0]
    finally:
        up.shutdown()


def test_dcode_s_route_asks():
    env: dict = {}
    server._build_dcode("openai-api", server.Auth(base_url="https://up.example/v1", api_key="k"),
                        "gpt-5.4", "hi", tempfile.mkdtemp(prefix="dcode-route-"), env)
    tok = env.get("OPENAI_API_KEY") or ""          # the route's placeholder bearer, never the key
    route = server._HERMES_RELAY["routes"].get(tok)
    assert route is not None and route[2].get("turn_reasoning_only") is True
