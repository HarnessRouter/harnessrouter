"""A UHP server that gets the step-budget rule wrong, one way at a time.

Tasks §1.1 makes `max_step` a budget: a server must stop the task at or after the budget, must
report `incomplete`, and must not report `completed` for work it truncated. Each defect below is
one way of getting that wrong, and the last few are the answers the check has to accept: a server
that cannot bound a base names `max_step` in `metadata.ignored_fields`, and a task whose chain
never began needs no budget at all.

The stub answers with the fixture's own answers, and its tool calls are the items a real server
would put in the response, so the check counts the rounds the way it counts a real server's.

    DEFECT=ignores_budget PORT=8942 PYTHONPATH=.. python3 step_budget_stub.py
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from uhp_conformance.fixture import step_answer

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8942"))
KEY = "stub-key"
BASE = "stub-base"

DEFECTS = {
    "none",             # stops at the budget and says so
    "ignores_budget",   # runs the whole chain and reports `completed`
    "ignores_budget_two_calls",  # runs the chain past the budget and reports `completed`
    "model_ended_the_turn",      # the chain stays inside the budget and the model ends the turn
    "no_reason",       # reports `incomplete` with no reason at all
    "wrong_reason",    # names a budget the request never carried
    "rounds_reason",   # names the budget in the spec's other word for it
    "reports_ignored", # cannot bound a base, and says so
    "no_tool_call",    # the agent never called the tool, so nothing needed a budget
    "incomplete_never_started",  # reports `incomplete` without the work ever starting
    "failed_status",   # runs past the budget and reports `failed`
    "prefixed_tool",   # stops at the budget; names the tool the way claude-family bases name MCP tools
}
assert DEFECT in DEFECTS, f"unknown defect {DEFECT!r}; one of {sorted(DEFECTS)}"

# How many rounds of the chain this defect's server lets through.
CALLS = {"none": 1, "ignores_budget": 3, "ignores_budget_two_calls": 2,
         "model_ended_the_turn": 1, "no_reason": 1, "wrong_reason": 1, "rounds_reason": 1,
         "reports_ignored": 1, "no_tool_call": 0, "incomplete_never_started": 0,
         "failed_status": 3, "prefixed_tool": 1}

# The nonce the check puts in the task's prompt, so the stub answers as the fixture would.
NONCE_RE = re.compile(r"set to ([0-9a-f]+)")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, status: int, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("uhp-version", "2026-10-19")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        if p == ["v1", "uhp"]:
            return self.send(200, {
                "object": "uhp.discovery", "versions": ["2026-10-19"],
                "default_version": "2026-10-19", "conformance_class": "full",
                "capabilities": {"streaming": True, "sessions": True, "cancellation": True,
                                 "files_input": True, "files_output": True,
                                 "session_listing": True, "harness_management": True}})
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.send(401, {"error": {"code": "unauthorized", "message": "no credential"}})
        if p == ["v1", "harnesses"]:
            return self.send(200, {"harnesses": [{"id": "h1", "name": "stub", "base": BASE,
                                                 "defaultModel": "stub-model"}]})
        return self.send(404, {"error": {"code": "not_found", "message": "no such endpoint"}})

    def do_DELETE(self):
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.send(401, {"error": {"code": "unauthorized", "message": "no credential"}})
        return self.send(200, {"id": "h2", "object": "harness", "deleted": True})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.send(401, {"error": {"code": "unauthorized", "message": "no credential"}})
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = {}
        if p == ["v1", "harnesses"]:
            return self._harness(body)
        if p == ["v1", "responses"]:
            return self.send(200, self._response(body))
        return self.send(404, {"error": {"code": "not_found", "message": "no such endpoint"}})

    def _harness(self, body: dict):
        if body.get("base") == "uhp-conformance-unknown-base":
            return self.send(422, {"error": {"code": "unsupported_base",
                                             "message": "no such base",
                                             "detail": {"supported": [BASE]}}})
        return self.send(200, {"id": "h2", "object": "harness", "name": body.get("name"),
                               "base": BASE, "defaultModel": "stub-model",
                               "mcpServers": body.get("mcp_servers") or [],
                               "disabledTools": []})

    def _response(self, body: dict):
        nonce = (NONCE_RE.search(str(body.get("input") or "")) or [None, "nonce"])[1]
        out = []
        # A server that honours the budget stops after the first step; one that ignores it runs
        # the chain on, and the chain is longer than the budget either way.
        for i in range(1, CALLS[DEFECT] + 1):
            out.append({"id": f"fc_{i}", "type": "function_call", "call_id": f"call_{i}",
                        "name": ("mcp__conformance-fixture__uhp_steps" if DEFECT == "prefixed_tool"
                                 else "uhp_steps"), "arguments": json.dumps({"nonce": nonce}),
                        "status": "completed"})
            out.append({"id": f"fco_{i}", "type": "function_call_output", "call_id": f"call_{i}",
                        "output": step_answer(i, nonce), "status": "completed"})
        status, details = "completed", None
        if DEFECT in ("none", "incomplete_never_started", "prefixed_tool"):
            status, details = "incomplete", {"reason": "max_steps"}
        elif DEFECT == "no_reason":
            status = "incomplete"
        elif DEFECT == "wrong_reason":
            status, details = "incomplete", {"reason": "timeout"}
        elif DEFECT == "rounds_reason":
            status, details = "incomplete", {"reason": "maximum tool-call rounds reached"}
        elif DEFECT == "failed_status":
            status = "failed"
        meta = {"session_id": f"sess_{uuid.uuid4().hex[:10]}", "harness_id": "h2"}
        if DEFECT == "reports_ignored":
            meta["ignored_fields"] = ["max_step"]
        return {"id": f"resp_{uuid.uuid4().hex[:10]}", "object": "response", "status": status,
                "model": "stub-model", "usage": None, "created_at": int(time.time()),
                "error": None, "incomplete_details": details, "previous_response_id": None,
                "store": True, "output": out, "metadata": meta}


if __name__ == "__main__":
    print(f"stub: defect={DEFECT} port={PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
