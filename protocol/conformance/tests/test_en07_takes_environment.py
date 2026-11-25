"""EN-07 reads an environment on a base that can mount one. A base that runs elsewhere refuses an
environment before the task starts (environment_unsupported); that is an answer, not a defect, and the
environment is the server's, so the check reads it on another base the server lists, on that base's own
default model. Read against a stub server whose named harness runs remotely."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from uhp_conformance import checks
from uhp_conformance.client import Client
from uhp_conformance.context import Context
from uhp_conformance.registry import Skip

ENV = {"id": "henv_1", "mount": "/env/uhp"}
STATE: dict = {"bases": {}, "sent": [], "local_can_mount": True}


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
            return self._send(200, {"harnesses": [{"id": "chrn_named", "base": "remote-agent"}]})
        if self.path.startswith("/v1/sessions/"):
            return self._send(200, {"id": "hsess_1", "environment": ENV["id"]})
        self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/v1/harnesses":
            base = body.get("base")
            if base == "uhp-conformance-unknown-base":
                return self._send(422, {"error": {"code": "unsupported_base", "detail": {"supported": ["remote-agent", "local-cli"]}}})
            hid = f"chrn_{base}_{len(STATE['bases'])}"
            STATE["bases"][hid] = base
            return self._send(200, {"id": hid, "base": base})
        if self.path == "/v1/responses":
            hid = (body.get("metadata") or {}).get("harness_id")
            STATE["sent"].append((STATE["bases"].get(hid), body.get("model")))
            if STATE["bases"].get(hid) == "remote-agent" or not STATE["local_can_mount"]:
                return self._send(400, {"error": {"code": "environment_unsupported", "message": "cannot mount"}})
            return self._send(200, {"status": "completed", "metadata": {"session_id": "hsess_1", "environment": ENV["id"]},
                                    "output": [{"content": [{"text": "hello from the environment\ntouch: Read-only file system\nWRITE_RC=1"}]}]})
        self._send(404, {})

    def do_DELETE(self):
        self._send(200, {"deleted": True})


@pytest.fixture(scope="module")
def stub():
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _ctx(stub) -> Context:
    ctx = Context(client=Client(stub, "k"), harness_id="chrn_named", model="gemini-4-hydrogen")
    ctx.state["discovery"] = {"capabilities": {"environments": True}}
    ctx.state["environment"] = ctx.state["environment_built"] = ENV
    return ctx


def test_a_remote_named_base_is_read_on_a_base_that_mounts_on_its_own_model(stub):
    STATE["sent"].clear()
    STATE["local_can_mount"] = True
    out = checks.en07(_ctx(stub))
    assert out.startswith("read /env/uhp/data/hello.txt")
    assert STATE["sent"] == [("remote-agent", "gemini-4-hydrogen"), ("local-cli", None)]


def test_no_base_that_mounts_is_a_skip_not_a_pass(stub):
    STATE["sent"].clear()
    STATE["local_can_mount"] = False
    with pytest.raises(Skip):
        checks.en07(_ctx(stub))


def test_en07_is_registered_as_the_check_itself_and_passes_through_the_registry(stub):
    """The suite runs a check through its registry, not by name: EN-07's entry is en07, and it passes there."""
    from uhp_conformance.registry import REGISTRY, Outcome
    (c,) = [c for c in REGISTRY if c.id == "EN-07"]
    assert c.fn is checks.en07
    STATE["sent"].clear()
    STATE["local_can_mount"] = True
    assert c.run(_ctx(stub)).outcome is Outcome.PASS


def test_every_check_is_a_function_of_the_context_alone():
    import inspect
    from uhp_conformance.registry import REGISTRY
    wrong = [c.id for c in REGISTRY if len([p for p in inspect.signature(c.fn).parameters.values()
                                            if p.default is inspect.Parameter.empty]) != 1]
    assert wrong == []
