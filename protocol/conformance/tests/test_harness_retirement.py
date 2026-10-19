"""F-09 (Harnesses §5.3, 2026-10-19): a server keeps a deleted harness's sessions unless it reports
`harness_retirement`, and one that does says so in the delete response with the restore window.
Each verdict is read against a stub server that answers one way."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from uhp_conformance import checks
from uhp_conformance.client import Client
from uhp_conformance.context import Context
from uhp_conformance.registry import Skip

MODE = {"delete": {}, "session_after": 200}


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/v1/harnesses":
            if body.get("base") == "uhp-conformance-unknown-base":
                return self._send(422, {"error": {"code": "unsupported_base", "detail": {"supported": ["stub-base"]}}})
            return self._send(200, {"id": "chrn_retire", "base": body.get("base")})
        if self.path == "/v1/responses":
            return self._send(200, {"status": "completed", "metadata": {"session_id": "hsess_retire"}})
        self._send(404, {})

    def do_DELETE(self):
        if self.path == "/v1/harnesses/chrn_retire":
            return self._send(200, {"id": "chrn_retire", "deleted": True, **MODE["delete"]})
        self._send(200, {"deleted": True})

    def do_GET(self):
        if self.path == "/v1/sessions/hsess_retire":
            return self._send(MODE["session_after"], {"id": "hsess_retire"})
        self._send(404, {})


@pytest.fixture(scope="module")
def stub():
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _run(stub, *, retires, delete, session_after=200):
    MODE["delete"], MODE["session_after"] = delete, session_after
    ctx = Context(client=Client(stub, "k"))
    ctx.state["discovery"] = {"capabilities": {"harness_retirement": retires}}
    return checks.f09(ctx)


def test_a_server_that_keeps_sessions_passes_when_the_session_still_reads(stub):
    assert _run(stub, retires=False, delete={}).startswith("kept")
    assert _run(stub, retires=False, delete={"sessions": "kept"}).startswith("kept")


def test_a_kept_session_that_no_longer_reads_fails(stub):
    with pytest.raises(AssertionError, match="stay readable"):
        _run(stub, retires=False, delete={}, session_after=404)


def test_retiring_sessions_without_reporting_the_capability_fails(stub):
    with pytest.raises(AssertionError, match="must report the capability"):
        _run(stub, retires=False, delete={"sessions": "retired", "restorableUntil": int(time.time()) + 86400})


def test_a_retiring_server_passes_with_the_window_stated_and_may_answer_404_inside_it(stub):
    until = int(time.time()) + 30 * 86400
    out = _run(stub, retires=True, delete={"sessions": "retired", "restorableUntil": until}, session_after=404)
    assert out == f"retired with the harness, restorable until {until}"


def test_a_retiring_server_fails_without_the_window_or_with_one_in_the_past(stub):
    with pytest.raises(AssertionError, match="sessions: \"retired\""):
        _run(stub, retires=True, delete={})
    with pytest.raises(AssertionError, match="in the future"):
        _run(stub, retires=True, delete={"sessions": "retired"})
    with pytest.raises(AssertionError, match="in the future"):
        _run(stub, retires=True, delete={"sessions": "retired", "restorableUntil": int(time.time()) - 1})


def test_no_session_to_retire_is_a_skip_not_a_verdict(stub, monkeypatch):
    orig = _Stub.do_POST

    def no_session(self):
        if self.path == "/v1/responses":
            self.rfile.read(int(self.headers.get("content-length") or 0))
            return self._send(200, {"status": "completed", "metadata": {}})
        return orig(self)
    monkeypatch.setattr(_Stub, "do_POST", no_session)
    with pytest.raises(Skip):
        _run(stub, retires=False, delete={})
