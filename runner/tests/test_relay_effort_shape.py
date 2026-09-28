"""The relay drops `reasoning_effort` for a model whose provider refuses the thinking shape the
aggregator made of it, remembers that for the model on the route, and sends again."""
import json
import pathlib
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import _effort_shape_refused, _hermes_relay_route  # noqa: E402

# TokenRouter's words for anthropic/claude-opus-5 on hr-test 0.25.13 (2026-09-28), field names masked as sent
REFUSAL = (b'{"error":{"message":"\\"***.***.enabled\\" is not supported for this model. Use \\"***.***.adaptive\\" '
           b'and \\"output_config.effort\\" to control thinking behavior.","type":"invalid_request_error","param":"","code":null}}')


def test_the_refusal_is_the_thinking_shape_and_nothing_else():
    assert _effort_shape_refused(REFUSAL)
    assert _effort_shape_refused(b'{"error": {"message": "\\"thinking.type: enabled\\" is not supported for this model. Use \\"thinking.type: adaptive\\" and \\"output_config.effort\\"."}}')
    assert not _effort_shape_refused(b'{"error": {"message": "reasoning_effort is not supported for this model."}}')
    assert not _effort_shape_refused(b"") and not _effort_shape_refused(None)


def test_relay_drops_the_effort_for_that_model_and_remembers_it():
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(body)
            if body.get("model", "").startswith("anthropic/") and "reasoning_effort" in body:
                data = REFUSAL
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
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")
        headers = {"authorization": f"Bearer {tok}", "content-type": "application/json"}

        def send(model):
            body = json.dumps({"model": model, "reasoning_effort": "high", "messages": [{"role": "user", "content": "hi"}]}).encode()
            return json.loads(urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=body, method="POST", headers=headers), timeout=10).read())

        assert send("anthropic/claude-opus-5") == {"ok": True}
        assert len(calls) == 2 and "reasoning_effort" in calls[0] and "reasoning_effort" not in calls[1]
        # the route remembers it for that model: the next request goes once, already without the effort
        assert send("anthropic/claude-opus-5") == {"ok": True}
        assert len(calls) == 3 and "reasoning_effort" not in calls[2]
        # another model on the same route keeps its effort: the refusal was the model's, not the route's
        assert send("openai/gpt-6") == {"ok": True}
        assert len(calls) == 4 and calls[3]["reasoning_effort"] == "high"
    finally:
        up.shutdown()
