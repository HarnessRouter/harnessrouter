"""The DeepSeek Harness driver's own relay forwards a stream as it arrives and ends one that only
keeps the connection warm. It is a second copy of the runner's relay loop (it holds the key in the
driver's process), and it had the same read: `resp.read(4096)`, which waits for 4096 bytes or the end
of the stream. See runner/tests/test_relay_upstream_failure.py for the measurement."""
import http.client
import http.server
import json
import pathlib
import socket
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402


class _Upstream:
    def __init__(self, mode: str):
        self.mode = mode
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                             b"transfer-encoding: chunked\r\n\r\n")
                if self.mode == "keepalive_forever":
                    line = b": PROCESSING\n\n"
                    while not self.stop.wait(0.1):
                        conn.sendall(b"%x\r\n" % len(line) + line + b"\r\n")
                else:
                    first = b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                    rest = b'data: {"choices":[{"delta":{"content":" second"}}]}\n\ndata: [DONE]\n\n'
                    conn.sendall(b"%x\r\n" % len(first) + first + b"\r\n")
                    self.stop.wait(1.5)
                    conn.sendall(b"%x\r\n" % len(rest) + rest + b"\r\n0\r\n\r\n")
                conn.close()
            except OSError:
                pass

    def close(self):
        self.stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def _relay(monkeypatch, upstream_port: int, wait_s: float):
    monkeypatch.setattr(dsh_driver, "UPSTREAM_BASE", f"http://127.0.0.1:{upstream_port}/v1")
    monkeypatch.setattr(dsh_driver, "UPSTREAM_KEY", "sk-real")
    monkeypatch.setattr(dsh_driver, "UPSTREAM_WAIT_S", wait_s)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), dsh_driver._Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _post(srv, timeout_s: float):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=timeout_s)
    conn.request("POST", "/v1/chat/completions",
                 body=json.dumps({"model": "m", "messages": [], "stream": True}),
                 headers={"authorization": "Bearer placeholder", "content-type": "application/json"})
    return conn, conn.getresponse()


def test_an_event_is_forwarded_when_it_arrives(monkeypatch):
    up = _Upstream("first_event_then_pause"); srv = _relay(monkeypatch, up.port, 30.0)
    try:
        t0 = time.time()
        conn, resp = _post(srv, 10)
        first = resp.read1(4096)
        waited = time.time() - t0
        rest = resp.read()
        conn.close()
    finally:
        up.close(); srv.shutdown()
    assert b'"first"' in first and waited < 1.0, (waited, first[:80])
    assert b"second" in rest and b"[DONE]" in rest


def test_keep_alive_lines_alone_end_the_call_with_the_reason(monkeypatch):
    up = _Upstream("keepalive_forever"); srv = _relay(monkeypatch, up.port, 1.0)
    try:
        t0 = time.time()
        conn, resp = _post(srv, 15)
        try:
            body = resp.read()
            ended = "complete"
        except http.client.IncompleteRead as e:
            body, ended = e.partial, "incomplete"
        took = time.time() - t0
        conn.close()
    finally:
        up.close(); srv.shutdown()
    assert took < 6 and ended == "incomplete", (took, ended)
    assert b'"code": "upstream_unavailable"' in body and b"no data" in body


def test_the_wait_is_the_runners_figure_and_600_without_it(monkeypatch):
    monkeypatch.delenv("HR_RELAY_UPSTREAM_TIMEOUT_S", raising=False)
    assert dsh_driver._upstream_wait() == 600
    monkeypatch.setenv("HR_RELAY_UPSTREAM_TIMEOUT_S", "180")
    assert dsh_driver._upstream_wait() == 180
    for junk in ("", "0", "-1", "soon"):
        monkeypatch.setenv("HR_RELAY_UPSTREAM_TIMEOUT_S", junk)
        assert dsh_driver._upstream_wait() == 600, junk
