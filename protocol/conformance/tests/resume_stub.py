"""A UHP server that gets the refusals of a resume wrong, one way at a time (Tasks §3.3).

A `resume` item chained on a response that is not interrupted is `409 resume_not_pending`; a resume
with no `previous_response_id`, with another item beside it, or twice is `400 invalid_input`; a
server without the capability refuses the item `400 invalid_input`. Each defect below is one way of
getting that wrong, and the first two are the answers the checks have to accept.

    DEFECT=runs_finished PORT=8944 python3 resume_stub.py
"""
from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8944"))
KEY = "stub-key"

DEFECTS = {
    "none",                  # reports resume, refuses as §3.3 says
    "no_capability",         # reports no resume and refuses the item 400 invalid_input
    "capability_runs_it",    # reports no resume, and runs the item as an ordinary task
    "runs_finished",         # reports resume, and resumes a response that was not interrupted
    "not_pending_is_404",    # 404 where 409 resume_not_pending is required
    "wrong_code",            # 409 with another code
    "no_previous_runs",      # a resume with no previous_response_id runs
    "extra_item_runs",       # a resume with another item beside it runs
    "double_resume_runs",    # two resumes in one request run
    "refusal_changes_it",    # the refusal marks the response named as failed
}
assert DEFECT in DEFECTS, f"unknown defect {DEFECT!r}; one of {sorted(DEFECTS)}"

RESPONSES: dict[str, dict] = {}


def _response(prev: str | None, sid: str) -> dict:
    return {"id": f"resp_{uuid.uuid4().hex[:10]}", "object": "response", "status": "completed",
            "model": "stub-model", "usage": None, "created_at": int(time.time()), "error": None,
            "incomplete_details": None, "previous_response_id": prev, "store": True,
            "output": [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "ok", "annotations": []}]}],
            "metadata": {"session_id": sid, "harness_id": "h1"}}


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

    def refuse(self, status: int, code: str, message: str = "no"):
        return self.send(status, {"error": {"type": "invalid_request_error", "code": code,
                                            "message": message, "param": None, "detail": None}})

    def do_GET(self):
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        if p == ["v1", "uhp"]:
            return self.send(200, {
                "object": "uhp.discovery", "protocol": "uhp", "versions": ["2026-10-19"],
                "default_version": "2026-10-19", "conformance_class": "full",
                "capabilities": {"streaming": True, "sessions": True, "cancellation": True,
                                 "files_input": True, "files_output": True, "session_listing": True,
                                 "harness_management": True,
                                 "resume": DEFECT not in ("no_capability", "capability_runs_it")}})
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.refuse(401, "invalid_credential")
        if p == ["v1", "harnesses"]:
            return self.send(200, {"harnesses": [{"id": "h1", "name": "stub", "base": "stub-base",
                                                 "defaultModel": "stub-model"}]})
        if len(p) == 3 and p[:2] == ["v1", "responses"] and p[2] in RESPONSES:
            return self.send(200, RESPONSES[p[2]])
        return self.refuse(404, "not_found")

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.refuse(401, "invalid_credential")
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = {}
        if p != ["v1", "responses"]:
            return self.refuse(404, "not_found")
        inp = body.get("input")
        resumes = [i for i in inp if isinstance(i, dict) and i.get("type") == "resume"] \
            if isinstance(inp, list) else []
        prev = str(body.get("previous_response_id") or "")
        if not resumes:
            return self._run(prev)
        if DEFECT in ("no_capability",):
            return self.refuse(400, "invalid_input")
        if DEFECT == "capability_runs_it":
            return self._run(prev)
        if not prev and DEFECT != "no_previous_runs":
            return self.refuse(400, "invalid_input")
        if not prev:
            return self._run("")
        if len(inp) > len(resumes) and DEFECT != "extra_item_runs":
            return self.refuse(400, "invalid_input")
        if len(inp) > len(resumes):
            return self._run(prev)
        if len(resumes) > 1 and DEFECT != "double_resume_runs":
            return self.refuse(400, "invalid_input")
        if len(resumes) > 1:
            return self._run(prev)
        # one resume, chained on a response that is not interrupted (the stub never interrupts)
        if DEFECT == "runs_finished":
            return self._run(prev)
        if DEFECT == "refusal_changes_it" and prev in RESPONSES:
            RESPONSES[prev]["status"] = "failed"
        if DEFECT == "not_pending_is_404":
            return self.refuse(404, "not_found")
        return self.refuse(409, "conflict" if DEFECT == "wrong_code" else "resume_not_pending")

    def _run(self, prev: str):
        r = _response(prev or None, f"sess_{uuid.uuid4().hex[:10]}")
        RESPONSES[r["id"]] = r
        return self.send(200, r)


if __name__ == "__main__":
    print(f"stub: defect={DEFECT} port={PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
