"""The relay drops the top-level field Google refused as unknown, remembers it, and sends again."""
import json
import pathlib
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from server import _google_unknown_field, _hermes_relay_route  # noqa: E402


def test_the_refusal_names_the_field():
    assert _google_unknown_field(b'{"error": {"message": "Invalid JSON payload received. Unknown name \\"store\\": Cannot find field.", "code": 400}}') == "store"
    assert _google_unknown_field(b'{"error": {"message": "Unknown name \\"strict\\" at \'tools[0].function\': Cannot find field."}}') == ""
    assert _google_unknown_field(b'{"error": {"message": "quota exceeded"}}') == ""


def test_relay_drops_the_refused_fields_and_remembers_them():
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            calls.append(body)
            for f in ("store", "seed"):
                if f in body:
                    data = json.dumps({"error": {"code": 400, "message": f'Invalid JSON payload received. Unknown name "{f}": Cannot find field.'}}).encode()
                    self.send_response(400)
                    break
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
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1beta/openai", "AQ.key")
        body = json.dumps({"model": "gemini-3.6-flash", "store": False, "seed": 7, "messages": [{"role": "user", "content": "hi"}]}).encode()
        headers = {"authorization": f"Bearer {tok}", "content-type": "application/json"}
        assert json.loads(urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=body, method="POST", headers=headers), timeout=10).read()) == {"ok": True}
        assert len(calls) == 3 and "store" not in calls[2] and "seed" not in calls[2]
        # the route remembers both: the next request goes once, already without them
        urllib.request.urlopen(urllib.request.Request(base + "/chat/completions", data=body, method="POST", headers=headers), timeout=10)
        assert len(calls) == 4 and "store" not in calls[3] and "seed" not in calls[3]
    finally:
        up.shutdown()


def test_pi_on_an_openai_shape_endpoint_rides_the_relay(tmp_path):
    env = {"HOME": str(tmp_path)}
    server._build_pi("openai-api", server.Auth(provider="openai-api", api_key="AQ.real", base_url="https://generativelanguage.googleapis.com/v1beta/openai"), "gemini-3.6-flash", "hi", str(tmp_path), env)
    cfg = json.load(open(tmp_path / ".pi" / "agent" / "models.json"))
    text = json.dumps(cfg)
    assert "127.0.0.1" in text and "AQ.real" not in text
