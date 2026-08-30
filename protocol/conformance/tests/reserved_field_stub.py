"""A UHP server that gets the reserved-field rules wrong, one way at a time.

Tasks §1.4 makes `tools` and `include` reserved, which is two requirements: accept them, and say
you ignored them. Each has a distinct way of being broken, and a third way exists that looks like
compliance — reporting fields the request never sent. This stub can do all three.

    DEFECT=silent_ignore PORT=8941 python3 reserved_field_stub.py
"""
from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8941"))
KEY = "stub-key"

DEFECTS = {
    "none",
    "rejects_reserved",   # 400s a request carrying `tools`, breaking ignore-don't-reject
    "silent_ignore",      # drops them and says nothing, so the client cannot tell
    "partial_report",     # reports `tools` but not `include`
    "hardcoded_report",   # always reports both, even when the request sent neither
}
assert DEFECT in DEFECTS, f"unknown defect {DEFECT!r}; one of {sorted(DEFECTS)}"

RESERVED = ("tools", "include")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, status: int, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("uhp-version", "2026-08-11")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        if p == ["v1", "uhp"]:
            return self.send(200, {
                "object": "uhp.discovery", "versions": ["2026-08-11"],
                "default_version": "2026-08-11", "conformance_class": "core",
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
        sent = [f for f in RESERVED if body.get(f) is not None]

        if sent and DEFECT == "rejects_reserved":
            return self.send(400, {"error": {"code": "invalid_request",
                                             "message": "unsupported field: tools"}})

        meta = {"session_id": f"sess_{uuid.uuid4().hex[:10]}", "harness_id": "h1"}
        if DEFECT == "hardcoded_report":
            meta["ignored_fields"] = list(RESERVED)
        elif DEFECT == "partial_report":
            if sent:
                meta["ignored_fields"] = ["tools"]
        elif DEFECT != "silent_ignore":
            if sent:
                meta["ignored_fields"] = sent

        return self.send(200, {
            "id": f"resp_{uuid.uuid4().hex[:10]}", "object": "response", "status": "completed",
            "model": "stub-1", "usage": None, "created_at": int(time.time()),
            "error": None, "incomplete_details": None, "previous_response_id": None, "store": True,
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}]}],
            "metadata": meta})


if __name__ == "__main__":
    print(f"stub: defect={DEFECT} port={PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
