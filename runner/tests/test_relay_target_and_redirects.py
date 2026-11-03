"""The relay sends a connection's real key to the connection's own host and nowhere else.

Two ways it did not (2026-11-02):
- The request target was joined onto the route's base as text. On a base with no path (a TokenRouter host
  root, the Bedrock adapter, a custom base), a target that does not start with "/" made
  "https://api.example.com" + ".evil.com/x" another host, and the key went there with the request.
- It followed redirects with the key on: a provider path the agent chose that answers 30x to another host
  handed the key on.
"""
import http.server
import pathlib
import socket
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

KEY = "sk-real-relay-key-0123456789"


def _serve(handler_cls):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _recorder():
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def _any(self):
            seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        do_GET = do_POST = _any

        def log_message(self, *a):
            pass
    return _serve(H), seen


def _raw(port, target, tok):
    """An HTTP/1.1 request with the target exactly as given (no client library would send this one)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {tok}\r\nConnection: close\r\n\r\n".encode())
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return int(data.split(b" ", 2)[1]), data


def test_a_target_that_is_not_a_path_is_refused_and_nothing_goes_upstream():
    up, seen = _recorder()
    base = f"http://127.0.0.1:{up.server_address[1]}"           # a base with no path: the case that escaped
    relay, tok = server._hermes_relay_route(base, KEY, exact_base=True)
    port = int(relay.rsplit(":", 1)[1].split("/")[0])
    for target in (".evil.example/x", "-evil.example/x", "@evil.example/x", "evil.example/x"):
        status, _ = _raw(port, target, tok)
        assert status == 400, target
    assert seen == []
    status, _ = _raw(port, "/v1/models", tok)                    # a path still goes, to the route's own host
    assert status == 200 and seen and seen[-1]["path"] == "/models"
    up.shutdown()


def test_a_redirect_is_handed_back_and_never_followed_with_the_key():
    other, other_seen = _recorder()

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("location", f"http://127.0.0.1:{other.server_address[1]}/steal")
            self.send_header("content-length", "0")
            self.end_headers()
        do_POST = do_GET

        def log_message(self, *a):
            pass
    up = _serve(Redirector)
    relay, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", KEY)
    port = int(relay.rsplit(":", 1)[1].split("/")[0])
    status, data = _raw(port, "/v1/models", tok)
    assert status == 302
    assert other_seen == [], "the relay followed the redirect"
    assert KEY.encode() not in data
    up.shutdown(); other.shutdown()


def test_a_passthrough_route_refuses_a_non_path_target_too():
    up, seen = _recorder()
    relay, tok = server._qoder_relay_route(f"http://127.0.0.1:{up.server_address[1]}", KEY)
    port = int(relay.rsplit(":", 1)[1].split("/")[0])
    assert _raw(port, ".evil.example/x", tok)[0] == 400 and seen == []
    up.shutdown()
