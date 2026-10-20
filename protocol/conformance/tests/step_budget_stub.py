"""A UHP server whose agent always makes three tool calls, and which holds `max_step` or not.

Tasks §1.1 makes `max_step` a budget: stop at or after it, report `incomplete`, never `completed`
for truncated work, and name the field in `metadata.ignored_fields` when the base cannot be
bounded. Here the stub is the harness, so how many tool calls a turn makes is not up to a model.

    DEFECT=silent_ignore PORT=8942 python3 step_budget_stub.py
"""
from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8942"))
KEY = "stub-key"

DEFECTS = {
    "none",
    "reports_ignored",    # runs to the end but names max_step in ignored_fields, which §1.1 allows
    "silent_ignore",      # runs all three calls and says `completed`, as if there were no budget
    "rejects_max_step",   # 400s a request carrying max_step
    "unnamed_reason",     # stops at the budget but says `incomplete` without saying why
}
assert DEFECT in DEFECTS, f"unknown defect {DEFECT!r}; one of {sorted(DEFECTS)}"

TOOL_CALLS = 3


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
                "default_version": "2026-10-19", "conformance_class": "core",
                "capabilities": {"streaming": True, "sessions": True, "cancellation": True}})
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.send(401, {"error": {"code": "unauthorized", "message": "no credential"}})
        if p == ["v1", "harnesses"]:
            return self.send(200, {"harnesses": [{"id": "h1", "name": "stub", "base": "stub"}]})
        return self.send(404, {"error": {"code": "not_found", "message": "no such endpoint"}})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.send(401, {"error": {"code": "unauthorized", "message": "no credential"}})
        if [x for x in urlsplit(self.path).path.split("/") if x] != ["v1", "responses"]:
            return self.send(404, {"error": {"code": "not_found", "message": "no such endpoint"}})

        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = {}
        budget = body.get("max_step")

        if budget is not None and DEFECT == "rejects_max_step":
            return self.send(400, {"error": {"code": "invalid_request",
                                             "message": "unsupported field: max_step"}})

        meta = {"session_id": f"sess_{uuid.uuid4().hex[:10]}", "harness_id": "h1"}
        bounded = budget is not None and DEFECT in {"none", "unnamed_reason"}
        made = min(TOOL_CALLS, int(budget)) if bounded else TOOL_CALLS
        if budget is not None and DEFECT == "reports_ignored":
            meta["ignored_fields"] = ["max_step"]

        output = []
        for i in range(made):
            output += [
                {"id": f"fc_{i}", "type": "function_call", "call_id": f"call_{i}", "name": "shell",
                 "arguments": "{}", "status": "completed"},
                {"id": f"fco_{i}", "type": "function_call_output", "call_id": f"call_{i}",
                 "output": "ok", "status": "completed"}]
        truncated = made < TOOL_CALLS
        if not truncated:
            output.append({"type": "message", "role": "assistant",
                           "content": [{"type": "output_text", "text": "alpha ahpla"}]})
        details = None
        if truncated and DEFECT != "unnamed_reason":
            details = {"reason": "max_steps"}

        return self.send(200, {
            "id": f"resp_{uuid.uuid4().hex[:10]}", "object": "response",
            "status": "incomplete" if truncated else "completed",
            "model": "stub-1", "usage": None, "created_at": int(time.time()),
            "error": None, "incomplete_details": details, "previous_response_id": None,
            "store": True, "output": output, "metadata": meta})


if __name__ == "__main__":
    print(f"stub: defect={DEFECT} port={PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
