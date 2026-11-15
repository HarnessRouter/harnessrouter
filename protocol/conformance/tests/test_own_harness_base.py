"""The suite's own harnesses (EN-07, F-09 and the rest that configure one) are made on a base that serves the model
the caller named. With --harness-id that is the named harness's base, never the first base the server lists: a
Gemini model sent to a harness the suite had made on Codex was refused as model_unavailable (2026-11-14).
Read against a stub server that lists one harness and answers the base probe with another base first."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from uhp_conformance import checks
from uhp_conformance.client import Client
from uhp_conformance.context import Context

PROBES: list[str] = []


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

    def do_GET(self):
        if self.path == "/v1/harnesses":
            return self._send(200, {"harnesses": [{"id": "chrn_named", "base": "gemini-only"}]})
        self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/v1/harnesses":
            if body.get("base") == "uhp-conformance-unknown-base":
                PROBES.append("probe")
                return self._send(422, {"error": {"code": "unsupported_base", "detail": {"supported": ["codex", "gemini-only"]}}})
            return self._send(200, {"id": "chrn_made", "base": body.get("base")})
        self._send(404, {})

    def do_DELETE(self):
        self._send(200, {"deleted": True})


@pytest.fixture(scope="module")
def stub():
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_with_a_named_harness_the_suites_own_harness_is_made_on_its_base(stub):
    PROBES.clear()
    ctx = Context(client=Client(stub, "k"), harness_id="chrn_named", model="gemini-3.8-flash")
    assert checks._supported_base(ctx) == "gemini-only"
    assert checks._managed_harness(ctx)["base"] == "gemini-only"
    assert PROBES == []                     # the server's own first base was never asked for


def test_without_a_named_harness_the_servers_first_base_is_used_as_before(stub):
    PROBES.clear()
    ctx = Context(client=Client(stub, "k"))
    assert checks._supported_base(ctx) == "codex"
    assert PROBES == ["probe"]
