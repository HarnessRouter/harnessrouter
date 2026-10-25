"""An earlier turn's reasoning items go upstream without their encrypted content on a route that asks for it
(dcode's), 2026-10-25: after a model switch dcode replays reasoning another model minted, and the upstream
refused the whole request ("The encrypted content for item rs_tmp_… could not be verified"). The items this
turn minted are replayed as they are; an earlier turn's keep their id and lose the blob."""
import json
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

DONE = {"type": "response.output_item.done", "output_index": 0,
        "item": {"type": "reasoning", "id": "rs_this_turn", "encrypted_content": "gAAAA-this", "summary": []}}


def _request(model="openai/gpt-6.1-sol"):
    return json.dumps({"model": model, "stream": True, "input": [
        {"type": "message", "role": "user", "content": "hi"},
        {"type": "reasoning", "id": "rs_tmp_earlier", "encrypted_content": "AY89a1-gemini", "status": "in_progress"},
        {"type": "message", "role": "assistant", "id": "msg_tmp_1", "content": [{"type": "output_text", "text": "M1"}]},
        {"type": "reasoning", "id": "rs_this_turn", "encrypted_content": "gAAAA-this", "summary": []},
        {"type": "function_call_output", "call_id": "c1", "output": "ok"}]}).encode()


def test_reasoning_ids_are_read_off_an_event_a_completed_response_and_a_whole_one():
    assert server._reasoning_ids_in(DONE) == ["rs_this_turn"]
    done = {"type": "response.completed", "response": {"model": "m", "output": [
        {"type": "reasoning", "id": "rs_a"}, {"type": "message", "id": "msg_a"}]}}
    assert server._reasoning_ids_in(done) == ["rs_a"]
    assert server._reasoning_ids_in({"object": "response", "output": [{"type": "reasoning", "id": "rs_b"}]}) == ["rs_b"]
    assert server._reasoning_ids_in_line(b"data: " + json.dumps(DONE).encode()) == ["rs_this_turn"]
    assert server._reasoning_ids_in_line(b'data: {"type": "response.output_text.delta", "delta": "x"}') == []


def test_only_an_earlier_turn_s_reasoning_loses_its_blob_and_keeps_its_id():
    out = json.loads(server._without_earlier_reasoning_blobs(_request(), {"rs_this_turn"}))
    items = {i.get("id") or i.get("call_id") or i["type"]: i for i in out["input"]}
    assert "encrypted_content" not in items["rs_tmp_earlier"] and items["rs_tmp_earlier"]["summary"] == []
    assert items["rs_tmp_earlier"]["type"] == "reasoning"                    # the item and its id stay
    assert items["rs_this_turn"]["encrypted_content"] == "gAAAA-this"
    assert items["msg_tmp_1"]["content"][0]["text"] == "M1" and items["c1"]["output"] == "ok"
    plain = b'{"model": "m", "input": [{"type": "message", "role": "user", "content": "hi"}]}'
    assert server._without_earlier_reasoning_blobs(plain, set()) is plain


def _route(**flags):
    got: list[dict] = []
    sse = b"data: " + json.dumps(DONE).encode() + b"\n\ndata: [DONE]\n\n"

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


def test_a_route_that_asks_sends_this_turn_s_reasoning_whole_and_an_earlier_turn_s_without_its_blob():
    up, got, post = _route(turn_reasoning_only=True)
    try:
        post(_request())          # rs_this_turn is not yet this turn's: the first request mints it
        first = {i.get("id"): i for i in got[0]["input"] if i.get("type") == "reasoning"}
        assert all("encrypted_content" not in i for i in first.values())
        post(_request())          # now it is: it goes whole, the earlier one without its blob
        second = {i.get("id"): i for i in got[1]["input"] if i.get("type") == "reasoning"}
        assert second["rs_this_turn"]["encrypted_content"] == "gAAAA-this"
        assert "encrypted_content" not in second["rs_tmp_earlier"]
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
    import tempfile
    ws = tempfile.mkdtemp(prefix="dcode-route-")
    env: dict = {}
    server._build_dcode("openai-api", server.Auth(base_url="https://up.example/v1", api_key="k"),
                        "gpt-5.4", "hi", ws, env)
    tok = env.get("OPENAI_API_KEY") or ""          # the route's placeholder bearer, never the key
    route = server._HERMES_RELAY["routes"].get(tok)
    assert route is not None and route[2].get("turn_reasoning_only") is True
