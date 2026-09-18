"""A deliberately wrong UHP server for the files chapter, one toggleable defect at a time.

X-05 sends its file inline and X-09 uploads it; a server whose `POST /v1/files` fails outright
passes X-05, which is how HarnessRouter CE 0.17.3 shipped with every upload answering 500 (#198).
This stub implements Files §1 in memory, correctly by default, and takes a DEFECT environment
variable naming one thing to get wrong; test_files_checks.py asserts which check catches it.
The "agent" here echoes the attached file's text, so a task that reaches it with the file shows
the token and one that does not shows nothing.

    DEFECT=upload_500 PORT=8933 python3 files_stub.py
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from email.parser import BytesParser
from email.policy import default as _email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8933"))
KEY = "stub-key"
VERSION = "2026-09-12"
DEFECTS = {
    "none",
    "upload_500",        # POST /v1/files raises: the endpoint exists and never works (#198)
    "upload_no_id",      # the file object comes back without an id, so nothing can reference it
    "upload_truncates",  # the object reports (and the store keeps) fewer bytes than were sent
}
assert DEFECT in DEFECTS, DEFECT

FILES: dict[str, dict] = {}
HARNESS = {"id": "h1", "object": "harness", "name": "stub", "base": "stub", "defaultModel": "stub-1"}


def _error(status, code, message):
    return status, {"error": {"type": "invalid_request_error" if status < 500 else "server_error",
                              "code": code, "message": message, "param": None, "detail": None}}


def _parts(content_type: str, raw: bytes):
    msg = BytesParser(policy=_email_default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode() + b"\r\n\r\n" + raw)
    for part in msg.iter_parts():
        yield (part.get_param("name", header="content-disposition"), part.get_filename(),
               part.get_payload(decode=True) or b"")


def upload(content_type: str, raw: bytes):
    if DEFECT == "upload_500":
        return _error(500, "internal", "'FileBlobStore' object has no attribute 'headers'")
    filename, data = "upload.bin", b""
    for name, fn, payload in _parts(content_type, raw):
        if name == "file":
            filename, data = fn or filename, payload
    if DEFECT == "upload_truncates":
        data = data[: max(0, len(data) - 4)]
    fid = f"file_{uuid.uuid4().hex[:12]}"
    FILES[fid] = {"filename": filename, "data": data}
    obj = {"id": fid, "object": "file", "filename": filename, "bytes": len(data),
           "created_at": int(time.time())}
    if DEFECT == "upload_no_id":
        obj.pop("id")
    return 200, obj


def respond(body: dict):
    texts = []
    items = body.get("input")
    if isinstance(items, str):
        items = [{"role": "user", "content": [{"type": "input_text", "text": items}]}]
    for item in items or []:
        for part in item.get("content") or []:
            if part.get("type") != "input_file":
                continue
            if part.get("file_data", "").startswith("data:"):
                texts.append(base64.b64decode(part["file_data"].split(",", 1)[1]).decode("utf-8", "replace"))
            elif part.get("file_id") in FILES:
                texts.append(FILES[part["file_id"]]["data"].decode("utf-8", "replace"))
    answer = " ".join(texts) if texts else "no file was attached"
    return 200, {"id": f"resp_{uuid.uuid4().hex[:12]}", "object": "response", "created_at": int(time.time()),
                 "status": "completed", "model": "stub-1", "error": None,
                 "output": [{"id": f"msg_{uuid.uuid4().hex[:8]}", "type": "message", "role": "assistant",
                             "status": "completed",
                             "content": [{"type": "output_text", "text": answer, "annotations": []}]}],
                 "metadata": {"session_id": "sess_stub"}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def send(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def route(self, method: str):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        p = [x for x in urlsplit(self.path).path.split("/") if x]
        if method == "GET" and p == ["v1", "uhp"]:
            return self.send(200, {"object": "uhp.discovery", "protocol": "uhp", "versions": [VERSION],
                                   "default_version": VERSION, "conformance_class": "extended",
                                   "capabilities": {"streaming": False, "sessions": True, "cancellation": False,
                                                    "files_input": True, "files_output": False}})
        if (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() != KEY:
            return self.send(*_error(401, "missing_credential", "no credential"))
        if method == "GET" and p == ["v1", "harnesses"]:
            return self.send(200, {"harnesses": [HARNESS]})
        if method == "POST" and p == ["v1", "files"]:
            return self.send(*upload(self.headers.get("content-type") or "", raw))
        if method == "POST" and p == ["v1", "responses"]:
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                body = {}
            return self.send(*respond(body))
        return self.send(*_error(404, "not_found", "no such endpoint"))

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
