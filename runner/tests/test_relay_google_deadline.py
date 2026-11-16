"""Google refuses a call whose deadline is under ten seconds ("Manually set deadline 8s is too short. Minimum allowed
deadline is 10s."), and agy's helper model asked for 8 on every step; the relay raises a shorter deadline to Google's
minimum, on Google's own endpoint only."""
import json
import pathlib
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _upstream(seen: list):
    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length") or 0))
            seen.append(self.headers.get("x-server-timeout"))
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
    return up


def _send(base, tok, deadline):
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}).encode()
    headers = {"authorization": f"Bearer {tok}", "content-type": "application/json"}
    if deadline is not None:
        headers["X-Server-Timeout"] = deadline
    req = urllib.request.Request(base + "/models/gemini-3.1-flash-lite-preview:generateContent", data=body,
                                 method="POST", headers=headers)
    assert json.loads(urllib.request.urlopen(req, timeout=10).read()) == {"ok": True}


def test_a_deadline_under_googles_minimum_reaches_google_as_the_minimum(monkeypatch):
    seen: list = []
    up = _upstream(seen)
    try:
        # the stand-in for Google's endpoint is local, so it is the host the relay knows as Google's here
        monkeypatch.setattr(server, "_GOOGLE_HOST", "127.0.0.1")
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1beta", "AQ.key")
        for asked in ("8", "8.5", "0", "-3", "10", "30", "soon", None):
            _send(base, tok, asked)
        assert seen == ["10", "10", "10", "10", "10", "30", "soon", None]
    finally:
        up.shutdown()


def test_another_providers_deadline_is_its_own(monkeypatch):
    seen: list = []
    up = _upstream(seen)
    try:
        monkeypatch.setattr(server, "_GOOGLE_HOST", "generativelanguage.googleapis.com")
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")
        _send(base, tok, "8")
        assert seen == ["8"]
    finally:
        up.shutdown()
