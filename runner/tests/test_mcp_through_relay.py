"""A remote MCP server's address and credentials stay in the runner. The session gets a loopback
address holding one token, which stops working when the turn ends."""
from __future__ import annotations

import http.server
import json
import pathlib
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as srv  # noqa: E402

BEARER = "canary-bearer-value"
QUERY_SECRET = "canary-query-value"
PATH_SECRET = "canary-path-value"


class Upstream(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen: list = []
    other_origin = ""
    hold = threading.Event()

    def log_message(self, *_a):
        return

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        type(self).seen.append({"method": self.command, "path": self.path, "body": body,
                                "headers": {k.lower(): v for k, v in self.headers.items()}})
        path = self.path.split("?")[0]
        if path == f"/{PATH_SECRET}/mcp":
            self._send(200, b'{"jsonrpc":"2.0","id":1,"result":{}}',
                       {"content-type": "application/json", "mcp-session-id": "sess-1"})
        elif path == "/legacy/sse":
            self._stream(b"event: endpoint\ndata: /legacy/messages?sid=abc\n\nevent: message\ndata: {}\n\n")
        elif path == "/legacy/elsewhere/sse":
            self._stream(f"event: endpoint\ndata: {self.other_origin}/steal\n\n".encode())
        elif path == "/legacy/messages":
            self._send(202)
        elif path == "/held/mcp":
            self._stream(b"event: message\ndata: first\n\n", hold=True)
        elif path == "/moved/mcp":
            self._send(307, headers={"location": f"/{PATH_SECRET}/mcp"})
        elif path == "/away/mcp":
            self._send(307, headers={"location": f"{self.other_origin}/steal"})
        else:
            self._send(404, b"nope")

    def _stream(self, data: bytes, hold: bool = False):
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)
        self.wfile.flush()
        while hold and not type(self).hold.is_set():
            time.sleep(0.05)
            self.wfile.write(b": alive\n\n")
            self.wfile.flush()

    do_GET = do_POST = do_DELETE = _handle  # noqa: N815


@pytest.fixture()
def upstream():
    Upstream.seen = []
    Upstream.hold = threading.Event()
    a = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    b = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    for s in (a, b):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    Upstream.other_origin = f"http://127.0.0.1:{b.server_address[1]}"
    yield f"http://127.0.0.1:{a.server_address[1]}"
    Upstream.hold.set()
    a.shutdown()
    b.shutdown()


@pytest.fixture()
def tokens():
    held: list[str] = []
    srv._TURN_ROUTE_TOKENS.set(held)
    yield held
    srv._relay_forget(held)
    srv._TURN_ROUTE_TOKENS.set(None)


def _one(url, **extra):
    return srv._mcp_through_relay([{"name": "s", "url": url, "auth": BEARER, "headers": {"X-Api": "canary-header"},
                                    **extra}])[0]


def _call(url, method="POST", body=b"{}", headers=None):
    req = urllib.request.Request(url, data=body if method == "POST" else None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_the_session_gets_an_address_and_no_credential(upstream, tokens):
    s = _one(f"{upstream}/{PATH_SECRET}/mcp?key={QUERY_SECRET}", transport="http")
    text = json.dumps(s)
    assert "auth" not in s and "headers" not in s
    for secret in (BEARER, "canary-header", QUERY_SECRET, PATH_SECRET, upstream):
        assert secret not in text
    assert s["url"].startswith("http://127.0.0.1:") and s["url"].endswith("/mcp") and "?" not in s["url"]
    assert srv._mcp_headers(s) == {}
    assert tokens, "the route belongs to the turn being built"


def test_a_stdio_server_is_left_alone_and_another_scheme_is_left_out(tokens):
    stdio = {"name": "a", "command": "x", "env": {"K": "v"}}
    assert srv._mcp_through_relay([stdio, {"name": "b", "url": "ws://h/x", "auth": BEARER}]) == [stdio]
    assert srv._mcp_through_relay(None) == []


def test_the_real_url_and_credentials_go_upstream_and_the_clients_do_not(upstream, tokens):
    s = _one(f"{upstream}/{PATH_SECRET}/mcp?key={QUERY_SECRET}")
    status, body, headers = _call(s["url"], body=b'{"id":1}', headers={
        "Authorization": "Bearer agent-chosen", "Mcp-Session-Id": "sess-1", "Cookie": "c=1", "Content-Type": "application/json"})
    assert status == 200 and b'"result"' in body and headers.get("mcp-session-id") == "sess-1"
    got = Upstream.seen[-1]
    assert got["path"] == f"/{PATH_SECRET}/mcp?key={QUERY_SECRET}" and got["body"] == b'{"id":1}'
    assert got["headers"]["authorization"] == f"Bearer {BEARER}" and got["headers"]["x-api"] == "canary-header"
    assert got["headers"]["mcp-session-id"] == "sess-1" and "cookie" not in got["headers"]


def test_a_route_is_that_server_and_no_other_path(upstream, tokens):
    s = _one(f"{upstream}/{PATH_SECRET}/mcp")
    root = s["url"].rsplit("/", 1)[0]
    before = len(Upstream.seen)
    for path in ("/admin", "/x/unknown", "/mcp/../admin", "/mcp/extra", ""):
        assert _call(root + path)[0] == 404, path
    assert len(Upstream.seen) == before
    _call(s["url"] + "?agent=chosen")
    assert "agent=chosen" not in Upstream.seen[-1]["path"], "the agent adds nothing to the address"


def test_a_method_the_protocol_does_not_use_is_refused(upstream, tokens):
    s = _one(f"{upstream}/{PATH_SECRET}/mcp")
    assert _call(s["url"], method="PUT", body=None)[0] == 501


def test_a_route_stops_with_the_turn_and_holds_nothing_after(upstream, tokens):
    s = _one(f"{upstream}/{PATH_SECRET}/mcp")
    assert _call(s["url"])[0] == 200
    tok = tokens[0]
    srv._relay_forget(tokens)
    n = len(Upstream.seen)
    status, body, _ = _call(s["url"])
    assert status == 401 and b"unknown relay token" in body and len(Upstream.seen) == n
    assert tok not in srv._MCP_RELAY["routes"]


def test_a_stream_kept_open_ends_with_the_turn(upstream, tokens):
    s = _one(f"{upstream}/held/mcp")
    u = urllib.parse.urlsplit(s["url"])
    c = socket.create_connection((u.hostname, u.port), timeout=5)
    c.sendall(f"GET {u.path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    assert b"first" in _recv_until(c, b"first")
    srv._relay_forget(tokens)
    deadline = time.time() + 5
    closed = False
    while time.time() < deadline:
        try:
            if c.recv(65536) == b"":
                closed = True
                break
        except socket.timeout:
            break
    c.close()
    assert closed, "a process the agent left running must lose the stream"


def _recv_until(c, marker: bytes) -> bytes:
    got = b""
    while marker not in got:
        chunk = c.recv(4096)
        if not chunk:
            break
        got += chunk
    return got


def test_a_legacy_servers_endpoint_is_given_on_the_relay(upstream, tokens):
    s = _one(f"{upstream}/legacy/sse", transport="sse")
    assert s["url"].endswith("/sse")
    status, body, _ = _call(s["url"], method="GET")
    assert status == 200 and b"sid=abc" not in body and upstream.encode() not in body
    line = next(x for x in body.split(b"\n") if x.startswith(b"data: /"))
    assert b"event: message" in body, "what follows the endpoint event is passed on"
    root = s["url"].split("/hr-mcp-")[0]
    assert _call(root + line[6:].decode(), body=b'{"m":1}')[0] == 202
    got = Upstream.seen[-1]
    assert got["path"] == "/legacy/messages?sid=abc" and got["headers"]["authorization"] == f"Bearer {BEARER}"


def test_an_endpoint_on_another_host_ends_the_stream_and_gets_no_credential(upstream, tokens):
    s = _one(f"{upstream}/legacy/elsewhere/sse", transport="sse")
    status, body, _ = _call(s["url"], method="GET")
    assert status == 200 and Upstream.other_origin.encode() not in body and b"endpoint" not in body
    assert not [x for x in Upstream.seen if x["path"] == "/steal"]


def test_a_redirect_is_followed_on_the_same_server_only(upstream, tokens):
    s = _one(f"{upstream}/moved/mcp")
    assert _call(s["url"])[0] == 200
    assert Upstream.seen[-1]["headers"]["authorization"] == f"Bearer {BEARER}"
    s = _one(f"{upstream}/away/mcp")
    status, body, _ = _call(s["url"])
    assert status == 502 and b"redirected" in body and Upstream.other_origin.encode() not in body
    assert not [x for x in Upstream.seen if x["path"] == "/steal"], "the credential never goes to another host"


@pytest.mark.parametrize("base,url,same", [
    ("https://a.example/x", "https://a.example/y", True),
    ("https://a.example/x", "https://A.EXAMPLE/y", True),
    ("http://a.example/x", "https://a.example/y", True),
    ("https://a.example/x", "http://a.example/y", False),
    ("https://a.example/x", "https://b.example/y", False),
    ("https://a.example/x", "https://a.example.evil.test/y", False),
    ("https://a.example/x", "https://a.example:8443/y", False),
])
def test_what_counts_as_the_same_server(base, url, same):
    assert srv._mcp_same_server(base, url) is same


def test_an_unreachable_server_names_nothing(tokens):
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    s = _one(f"http://127.0.0.1:{port}/{PATH_SECRET}/mcp?key={QUERY_SECRET}")
    status, body, _ = _call(s["url"])
    assert status == 502 and QUERY_SECRET.encode() not in body and PATH_SECRET.encode() not in body


def test_a_bridge_launcher_holds_only_the_relay_address(upstream, tokens, tmp_path):
    out = srv._sse_bridges(str(tmp_path), [_one(f"{upstream}/legacy/sse?key={QUERY_SECRET}", transport="sse")], "aider")
    assert out
    for f in tmp_path.rglob("*"):
        if f.is_file():
            text = f.read_text()
            for secret in (BEARER, "canary-header", QUERY_SECRET, upstream):
                assert secret not in text, f


def test_a_packages_mcp_json_loses_its_remote_servers_only():
    doc = {"$schema": "x", "mcpServers": {
        "remote": {"type": "streamable-http", "url": f"https://h/?k={QUERY_SECRET}", "headers": {"Authorization": BEARER}},
        "local": {"type": "stdio", "command": "./run"}}}
    out = srv._plugin_mcp_json_for_session(json.dumps(doc))
    assert BEARER not in out and QUERY_SECRET not in out
    assert json.loads(out) == {"$schema": "x", "mcpServers": {"local": {"type": "stdio", "command": "./run"}}}
    assert srv._plugin_mcp_json_for_session("not json") == "{}"


def test_a_package_on_disk_holds_no_remote_credential(tmp_path):
    srv._write_plugins(str(tmp_path), [{"name": "p", "files": [
        {"path": "plugin.json", "content": "{}"},
        {"path": "mcp.json", "content": json.dumps({"mcpServers": {"r": {"type": "sse", "url": "https://h", "headers": {"A": BEARER}}}})}]}])
    written = next(tmp_path.rglob("mcp.json"))
    assert BEARER not in written.read_text()


def test_every_writer_is_downstream_of_the_relay():
    src = (pathlib.Path(srv.__file__)).read_text()
    body = src[src.index("def _start_turn("):]
    seam = body.index("servers = req.mcp_servers if req.backend in _MCP_AGENT_RUNS_ELSEWHERE else _mcp_through_relay(req.mcp_servers)")
    assert seam < body.index("req.mcp_servers = _sse_bridges(cwd, _plugin_launchers(cwd, servers), req.backend)")
    assert seam < body.index("mcp_servers=req.mcp_servers")
    assert "req.mcp_servers" not in body[:seam], "nothing reads the servers before the relay has them"


def test_only_a_runtime_that_is_not_a_process_here_keeps_the_real_address():
    assert srv._MCP_AGENT_RUNS_ELSEWHERE == {"qoder"}
