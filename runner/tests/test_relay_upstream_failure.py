"""The relay must ANSWER its client even when the provider does not answer it.

Only `urllib.error.HTTPError` was caught around the upstream call, so a transport failure — a
refused connection, a connection dropped before the answer, a provider that accepts the request and
then goes silent — escaped `_forward`, `ThreadingHTTPServer` printed a traceback, and the socket was
closed WITH NO RESPONSE. The CLI on the other end was left holding a dead connection, and the turn
hung until something above it gave up.

Measured on a support-matrix instance on 2026-09-29: ten such tracebacks
(`http.client.RemoteDisconnected: Remote end closed connection without response`), two of them
inside the window where the family tour recorded seven of fourteen families as "not settled in
600s" with no served model and no tool call. The relay's own wait was 600 s, the same as the cap
above it, so a silent provider could never be reported as one — the cap always fired first.

These tests drive the real handler against a real socket, because that is where the defect lived:
the shape of what reaches the client when the upstream misbehaves, not the parsing of a body.
"""
import http.client
import json
import pathlib
import socket
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


class _Upstream:
    """A provider that misbehaves in one chosen way."""

    def __init__(self, mode: str):
        self.mode, self.requests = mode, 0
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.requests += 1
            try:
                conn.recv(65536)
                if self.mode == "drop":
                    conn.close()                      # no response at all
                    continue
                if self.mode == "silent":
                    self.stop.wait(30)                # accept, then say nothing
                    conn.close()
                    continue
                if self.mode == "drop_then_ok" and self.requests == 1:
                    conn.close()
                    continue
                if self.mode == "stall_mid_stream":
                    ev = b'data: {"choices":[{"delta":{"content":"par"}}]}\n\n'
                    conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                                 b"transfer-encoding: chunked\r\n\r\n"
                                 + b"%x\r\n" % len(ev) + ev + b"\r\n")
                    self.stop.wait(30)                # one event, then nothing and no end
                    conn.close()
                    continue
                if self.mode == "keepalive_forever":
                    # what an aggregator sends while ITS upstream says nothing: comment lines, on
                    # and on. The socket is never silent and no answer ever comes.
                    conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                                 b"transfer-encoding: chunked\r\n\r\n")
                    line = b": PROCESSING\n\n"
                    while not self.stop.wait(0.1):
                        conn.sendall(b"%x\r\n" % len(line) + line + b"\r\n")
                    conn.close()
                    continue
                if self.mode == "first_event_then_pause":
                    first = b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                    rest = (b'data: {"choices":[{"delta":{"content":" second"},"finish_reason":"stop"}]}\n\n'
                            b'data: [DONE]\n\n')
                    conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                                 b"transfer-encoding: chunked\r\n\r\n"
                                 + b"%x\r\n" % len(first) + first + b"\r\n")
                    self.stop.wait(1.5)               # the model is still writing
                    conn.sendall(b"%x\r\n" % len(rest) + rest + b"\r\n0\r\n\r\n")
                    conn.close()
                    continue
                if self.mode == "split_fields":
                    # one event, written in pieces that cut the model name and the finish reason
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                                 b"transfer-encoding: chunked\r\n\r\n")
                    for piece in (b'data: {"id":"c","mo', b'del":"served/', b'in-three-reads","choices":[{"delta":'
                                  b'{"content":"OK"},"finish_', b'reason":"st', b'op"}]}\n\ndata: [DONE]\n\n'):
                        conn.sendall(b"%x\r\n" % len(piece) + piece + b"\r\n")
                        self.stop.wait(0.08)
                    conn.sendall(b"0\r\n\r\n")
                    conn.close()
                    continue
                if self.mode == "stall_mid_body":
                    conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
                                 b"content-length: 500\r\n\r\n" + b'{"id":')
                    self.stop.wait(30)                # six of five hundred bytes
                    conn.close()
                    continue
                body = (b'data: {"id":"c","object":"chat.completion.chunk",'
                        b'"model":"served/by-the-stub","choices":[{"delta":{"content":"OK"}}]}\n\n'
                        b'data: [DONE]\n\n')
                conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                             b"content-length: %d\r\n\r\n" % len(body) + body)
                conn.close()
            except OSError:
                pass

    def close(self):
        self.stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def _relay_call(upstream_port: int, timeout_s: float = 10.0):
    """One chat/completions request through a real relay to a real (misbehaving) upstream."""
    base = f"http://127.0.0.1:{upstream_port}/v1"
    relay_base, tok = rs._hermes_relay_route(base, "sk-real")
    host = relay_base.removeprefix("http://").removesuffix("/v1")
    conn = http.client.HTTPConnection(host, timeout=timeout_s)
    try:
        conn.request("POST", "/v1/chat/completions",
                     body=json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}],
                                      "stream": True}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        try:
            return resp.status, resp.read()
        except http.client.IncompleteRead as e:
            # an answer the relay cut short on purpose: the caller sees what did arrive, marked
            return resp.status, e.partial + b"<<INCOMPLETE>>"
    finally:
        conn.close()
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_connection_dropped_before_the_answer_becomes_a_502_the_client_can_read():
    """Not a closed socket: an HTTP response with the provider's failure in it. The relay retries a
    bare drop once (it costs nothing upstream), then reports."""
    up = _Upstream("drop")
    try:
        status, body = _relay_call(up.port)
    finally:
        up.close()
    assert status == 502, (status, body[:200])
    doc = json.loads(body)
    assert doc["error"]["code"] == "upstream_unavailable"
    assert "did not answer" in doc["error"]["message"]
    assert up.requests == 2, "a connection dropped before any byte is worth ONE more attempt"


def test_a_drop_that_does_not_repeat_is_retried_and_the_answer_goes_through():
    """The retry is not cosmetic: an aggregator that sheds one connection still serves the turn."""
    up = _Upstream("drop_then_ok")
    try:
        status, body = _relay_call(up.port)
    finally:
        up.close()
    assert status == 200 and b"served/by-the-stub" in body
    assert up.requests == 2


def test_a_refused_connection_is_reported_rather_than_dropping_the_socket():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()                                    # nothing listens there now
    status, body = _relay_call(dead_port)
    assert status == 502
    assert json.loads(body)["error"]["type"] == "upstream_unavailable"


def test_a_provider_that_goes_silent_is_reported_as_a_timeout_not_waited_on_forever(monkeypatch):
    """THE TOUR'S SHAPE. The wait is bounded well under any turn cap, and what comes back says so;
    before this the relay waited 600 s — the same as the cap above it — so the cap always fired
    first and the turn was recorded as cancelled with no reason at all."""
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    up = _Upstream("silent")
    try:
        status, body = _relay_call(up.port, timeout_s=20)
    finally:
        up.close()
    assert status == 504, (status, body[:200])
    doc = json.loads(body)
    assert doc["error"]["code"] == "upstream_unavailable"
    assert "timed out" in doc["error"]["message"]
    assert up.requests == 1, "a timeout is not retried: the provider may be generating, and billing"


def test_the_upstream_wait_is_bounded_below_the_turn_cap_and_no_shorter_than_it_ever_was(monkeypatch):
    """Under the cap, so a silent provider is reported by the relay rather than discovered by the
    cap; and not under the 600 s this relay always waited, because a model that thinks without
    sending anything is an answer on its way. Measured 2026-10-06: OpenAI's Chat Completions API sent
    no event in 430 s in 5 of 5 calls at the highest level, and most bases speak it. The default was
    180 s for one release and cut exactly those. An instance with a shorter cap of its own (the
    support-matrix suite's 600 s) sets the variable."""
    monkeypatch.delenv("HR_RELAY_UPSTREAM_TIMEOUT_S", raising=False)
    assert rs._relay_upstream_timeout() == 600
    assert rs._relay_upstream_timeout() < rs.MAX_TURN_SECONDS
    monkeypatch.setenv("HR_RELAY_UPSTREAM_TIMEOUT_S", "180")
    assert rs._relay_upstream_timeout() == 180
    for junk in ("", "0", "-5", "soon"):
        monkeypatch.setenv("HR_RELAY_UPSTREAM_TIMEOUT_S", junk)
        assert rs._relay_upstream_timeout() == 600, junk


def test_a_stream_that_stalls_is_not_ended_as_a_complete_answer(monkeypatch):
    """One event, then silence. The relay cannot change the 200 it already sent, so it says why in
    the stream's own error event and leaves the chunked body unterminated: a client must not be
    able to read this as an answer that simply had nothing more to say."""
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    up = _Upstream("stall_mid_stream")
    try:
        status, body = _relay_call(up.port, timeout_s=20)
    finally:
        up.close()
    assert status == 200
    assert body.endswith(b"<<INCOMPLETE>>"), body[-120:]
    assert b'"code": "upstream_unavailable"' in body and b"mid-stream" in body
    assert up.requests == 1


def test_a_body_that_stops_arriving_is_a_provider_failure_not_an_empty_200(monkeypatch):
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    up = _Upstream("stall_mid_body")
    try:
        status, body = _relay_call(up.port, timeout_s=20)
    finally:
        up.close()
    assert status == 504, (status, body[:200])
    assert json.loads(body)["error"]["code"] == "upstream_unavailable"


def test_keep_alive_lines_alone_are_a_provider_that_stopped_answering(monkeypatch):
    """An aggregator trickles comment lines while its own upstream says nothing. The socket never
    goes quiet, so the socket's timeout never fires, and a read that waits for 4096 bytes never
    returns either: the client got nothing at all and nothing ended the call but the turn's cap.
    Reproduced here at a stub; not caught on a live provider (the long turns that prompted the look,
    2026-10-04, turned out to be a model streaming reasoning without end, which sends events and is
    not this). No EVENT for the relay's wait is the provider having stopped, whatever else arrives."""
    import time
    monkeypatch.setattr(rs, "HR_RELAY_UPSTREAM_TIMEOUT_S", 1.0)
    up = _Upstream("keepalive_forever")
    t0 = time.time()
    try:
        status, body = _relay_call(up.port, timeout_s=15)
    finally:
        up.close()
    assert time.time() - t0 < 6, "the relay must end the call itself, near its own wait"
    assert status == 200
    assert body.endswith(b"<<INCOMPLETE>>"), body[-160:]
    assert b'"code": "upstream_unavailable"' in body and b"no data" in body
    assert up.requests == 1


def test_an_event_reaches_the_client_when_it_arrives_not_when_4096_bytes_have(monkeypatch):
    """The stream is forwarded as it is read. A read for 4096 bytes held a short first event in the
    relay until the rest of the answer filled the block, so a person watched nothing and then
    everything, and a first event followed by a stall never arrived at all."""
    import time
    up = _Upstream("first_event_then_pause")
    base = f"http://127.0.0.1:{up.port}/v1"
    relay_base, tok = rs._hermes_relay_route(base, "sk-real")
    conn = http.client.HTTPConnection(relay_base.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        t0 = time.time()
        conn.request("POST", "/v1/chat/completions",
                     body=json.dumps({"model": "m", "messages": [], "stream": True}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        first = resp.read1(4096)
        waited = time.time() - t0
        rest = resp.read()
    finally:
        conn.close(); up.close(); rs._HERMES_RELAY["routes"].pop(tok, None)
    assert b'"first"' in first and waited < 1.0, (waited, first[:80])
    assert b"second" in rest and b"[DONE]" in rest


def test_a_field_cut_across_several_reads_is_still_read_off_the_stream():
    """The relay reads the served model and the finish reason off the bytes as they pass. Forwarding
    what has arrived means a read can be a few bytes, so the field is looked for in the tail of the
    stream so far, not in the tail of the one read before."""
    up = _Upstream("split_fields")
    base = f"http://127.0.0.1:{up.port}/v1"
    relay_base, tok = rs._hermes_relay_route(base, "sk-real")
    conn = http.client.HTTPConnection(relay_base.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        conn.request("POST", "/v1/chat/completions",
                     body=json.dumps({"model": "m", "messages": [], "stream": True}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        body = resp.read()
        flags = rs._HERMES_RELAY["routes"][tok][2]
        assert b'"model":"served/in-three-reads"' in body and body.endswith(b"data: [DONE]\n\n")
        assert flags.get("served_model") == "served/in-three-reads"
        assert flags.get("last_finish") == "stop"
    finally:
        conn.close(); up.close(); rs._HERMES_RELAY["routes"].pop(tok, None)
