"""A model that allows one temperature only is sent none (2026-10-25): Moonshot's kimi models through
TokenRouter refuse anything but 1 ("invalid temperature: only 1 is allowed for this model"), and vibe
sends its own default of 0.2, so every vibe turn on kimi-k2.7-code and kimi-k3 was refused there."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

REFUSAL = (b'{"error":{"message":"invalid temperature: only 1 is allowed for this model",'
           b'"type":"invalid_request_error","param":"","code":"invalid_argument"}}')


def test_the_refusal_is_recognised_and_nothing_else_is():
    assert server._temperature_refused(REFUSAL)
    assert not server._temperature_refused(b'{"error":{"message":"invalid tool schema"}}')
    assert not server._temperature_refused(b"")


def test_the_call_goes_again_without_it_and_the_model_is_sent_none_after():
    got: list[dict] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            got.append(body)
            strict = body.get("model", "").startswith("moonshotai/")
            if strict and "temperature" in body:
                self.send_response(400)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(REFUSAL)))
                self.end_headers()
                self.wfile.write(REFUSAL)
                return
            ok = json.dumps({"object": "chat.completion", "model": body["model"], "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "M1"}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(ok)))
            self.end_headers()
            self.wfile.write(ok)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")

        def post(model: str) -> dict:
            body = json.dumps({"model": model, "temperature": 0.2,
                               "messages": [{"role": "user", "content": "hi"}]}).encode()
            return json.loads(urllib.request.urlopen(urllib.request.Request(
                base + "/chat/completions", data=body, method="POST",
                headers={"authorization": f"Bearer {tok}", "content-type": "application/json"}), timeout=10).read())

        assert post("moonshotai/kimi-k2.7-code")["choices"][0]["message"]["content"] == "M1"
        assert [("temperature" in b) for b in got] == [True, False]           # refused, then sent without it
        post("moonshotai/kimi-k2.7-code")
        assert "temperature" not in got[2]                                      # learned for this model
        post("openai/gpt-5.4")
        assert got[3]["temperature"] == 0.2                                     # another model keeps its own
    finally:
        up.shutdown()
