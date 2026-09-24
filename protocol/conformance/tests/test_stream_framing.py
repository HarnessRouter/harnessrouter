"""The suite reads a stream as Server-Sent Events are specified, not as one server writes it.

Streaming §1 makes each event an SSE message, and SSE (WHATWG HTML, "Parsing an event stream")
ends a line with CRLF, LF or CR, and joins an event's `data:` lines with LF. sse-starlette, the
usual SSE library under FastAPI and Starlette, frames with CRLF by default. The client once split
only on LF-LF and parsed each `data:` line alone, so a CRLF server's stream parsed to zero events:
S-01 failed with "the stream produced no events (HTTP 200: )", the rest of the streaming chapter
skipped, and a correct server was reported non-conformant. A stdlib server writes the same three
events under every framing here; no real agent runs.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from uhp_conformance import checks  # noqa: F401 — importing populates the registry
from uhp_conformance import client
from uhp_conformance.client import Client
from uhp_conformance.context import Context
from uhp_conformance.registry import REGISTRY, Outcome

EVENTS = [
    {"type": "response.created", "sequence_number": 0},
    {"type": "response.output_text.delta", "sequence_number": 1, "delta": "a"},
    {"type": "response.completed", "sequence_number": 2},
]
TYPES = [e["type"] for e in EVENTS]
FRAMINGS = {
    "lf": (b"\n", False),
    "crlf": (b"\r\n", False),          # sse-starlette's default
    "cr": (b"\r", False),
    "lf-multiline": (b"\n", True),     # JSON pretty-printed across several data: lines
    "crlf-multiline": (b"\r\n", True),
}


def _frames(eol: bytes, multiline: bool) -> bytes:
    out = b""
    for ev in EVENTS:
        body = json.dumps(ev, indent=1) if multiline else json.dumps(ev)
        out += b"".join(b"data: " + ln.encode() + eol for ln in body.split("\n")) + eol
    return out


@pytest.fixture
def server():
    """A server whose POST answers with `payload["body"]` as text/event-stream, then closes."""
    payload: dict[str, bytes] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            self.wfile.write(payload["body"])

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", payload
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("framing", FRAMINGS)
def test_stream_parses_every_sse_framing(server, framing):
    base, payload = server
    payload["body"] = _frames(*FRAMINGS[framing])
    evs = Client(base).stream("/v1/responses", {"stream": True}, max_seconds=10)
    assert [e["type"] for e in evs] == TYPES
    assert all(isinstance(e["__t"], float) for e in evs)


def test_s01_passes_a_crlf_stream(server):
    """The whole symptom: S-01 against a server that frames exactly as sse-starlette does."""
    base, payload = server
    payload["body"] = _frames(b"\r\n", False)
    ctx = Context(client=Client(base), task_timeout=10.0, state={"harness": {"id": "h1"}})
    r = next(c for c in REGISTRY if c.id == "S-01").run(ctx)
    assert r.outcome is Outcome.PASS, r.detail
    assert r.detail == "3 events"


def test_a_crlf_split_across_reads_is_one_line_break():
    """A read that ends on CR may be half of a CRLF; it must not count as a blank line."""
    events: list[dict] = []
    t0 = time.time()
    rest = client._drain_sse(b'data: {"type": "a"}\r', events, t0)
    assert events == []
    rest = client._drain_sse(rest + b'\n\r\ndata: {"type": "b"}\r\n\r\n', events, t0)
    assert [e["type"] for e in events] == ["a", "b"]
    assert rest == b""


def test_a_trailing_cr_ends_the_last_event_only_at_end_of_stream():
    events: list[dict] = []
    rest = client._drain_sse(b'data: {"type": "a"}\r\r', events, time.time())
    assert events == []
    client._drain_sse(rest, events, time.time(), final=True)
    assert [e["type"] for e in events] == ["a"]


def test_comments_other_fields_and_non_object_data_are_ignored():
    events: list[dict] = []
    rest = client._drain_sse(b': keep-alive\n\n'
                             b'event: response.created\nid: 1\nretry: 10\ndata:{"type": "a"}\n\n'
                             b'data: [DONE]\n\n'
                             b'data: [1, 2]\n\n'
                             b'data: {"type": "b"}\n', events, time.time(), final=True)
    assert [e["type"] for e in events] == ["a"]
    assert rest == b'data: {"type": "b"}\n'   # no blank line yet, so not dispatched
