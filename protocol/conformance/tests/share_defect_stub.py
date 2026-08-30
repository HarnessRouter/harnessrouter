"""A deliberately wrong UHP server, with one toggleable defect per rule in Sessions §5.

The R-series checks what a shared view REFUSES, and a check that only ever passes proves
nothing about a refusal. So this stub implements just enough of the protocol for those checks
to run, and takes a DEFECT environment variable naming one thing to get wrong.
test_session_sharing_checks.py drives it once per defect and asserts the diagonal.

It answers every task itself, so the matrix needs no credentials, no network and no agent
tokens, and finishes in seconds.

    DEFECT=revoke_lies PORT=8931 python3 share_defect_stub.py
"""
from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8931"))
KEY = "stub-key"

DEFECTS = {
    "none",
    "view_needs_auth",       # the "published" view demands the owner's credential
    "get_share_disagrees",   # GET /share reports a different link from the one POST minted
    "share_id_is_token",     # the share id authenticates the real API
    "view_accepts_writes",   # the shared view accepts a write from a link holder
    "leaks_credentials",     # the view carries the harness's MCP auth and headers
    "revoke_lies",           # revocation answers 200 and revokes nothing
    "multi_mint",            # every POST mints a new link; revocation kills only the newest
    "share_outlives_session",  # the link survives the deletion of its session
}
assert DEFECT in DEFECTS, f"unknown defect {DEFECT!r}; one of {sorted(DEFECTS)}"

SESSIONS: dict[str, dict] = {}          # session_id -> {"deleted": bool}
SHARES: dict[str, str] = {}             # share_id   -> session_id
BY_SESSION: dict[str, list[str]] = {}   # session_id -> [share_id] in mint order


def view_of(session_id: str) -> dict:
    v = {"object": "session.shared", "session": {"id": session_id, "object": "session"},
         "harness": {"id": "h1", "name": "stub", "base": "stub"}}
    if DEFECT == "leaks_credentials":
        v["harness"]["mcpServers"] = [{"name": "internal", "url": "https://mcp.example.invalid",
                                       "auth": {"type": "bearer", "token": "sk-live-not-yours"},
                                       "headers": {"x-api-key": "sk-live-not-yours"}}]
    return v


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    # ── plumbing ──────────────────────────────────────────────────────────────────────
    def send(self, status: int, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("uhp-version", "2026-08-11")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def bearer(self) -> str:
        return (self.headers.get("authorization") or "").removeprefix("Bearer ").strip()

    def authed(self) -> bool:
        tok = self.bearer()
        if tok == KEY:
            return True
        return DEFECT == "share_id_is_token" and tok in SHARES

    def read_body(self):
        n = int(self.headers.get("content-length") or 0)
        if n:
            self.rfile.read(n)

    def path_parts(self):
        return [p for p in urlsplit(self.path).path.split("/") if p]

    # ── routing ───────────────────────────────────────────────────────────────────────
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method: str):
        self.read_body()
        p = self.path_parts()

        # Discovery, unauthenticated.
        if method == "GET" and p == ["v1", "uhp"]:
            return self.send(200, {
                "object": "uhp.discovery", "versions": ["2026-08-11"],
                "default_version": "2026-08-11", "conformance_class": "full",
                "capabilities": {"streaming": True, "sessions": True, "cancellation": True,
                                 "files_input": True, "files_output": True,
                                 "session_listing": True, "harness_management": True,
                                 "session_sharing": True}})

        # The shared view: reached by whoever holds the link.
        if p[:2] == ["v1", "shares"] and len(p) >= 3:
            return self.shared_view(method, p[2])

        # Everything else needs the API credential.
        if not self.authed():
            return self.send(401, {"error": {"code": "unauthorized", "message": "no credential"}})

        if method == "GET" and p == ["v1", "harnesses"]:
            return self.send(200, {"harnesses": [{"id": "h1", "name": "stub", "base": "stub"}]})
        if method == "GET" and p in (["v1", "sessions"], ["v1", "responses"]):
            return self.send(200, {p[1]: []})
        if method == "POST" and p == ["v1", "responses"]:
            sid = f"sess_{uuid.uuid4().hex[:10]}"
            SESSIONS[sid] = {"deleted": False}
            return self.send(200, {
                "id": f"resp_{uuid.uuid4().hex[:10]}", "object": "response", "status": "completed",
                "model": "stub-1", "usage": None, "created_at": int(time.time()),
                "output": [{"type": "message", "role": "assistant",
                            "content": [{"type": "output_text", "text": "ok"}]}],
                "metadata": {"session_id": sid, "harness_id": "h1"}})
        if p[:2] == ["v1", "sessions"] and len(p) >= 4 and p[3] == "share":
            return self.share_endpoint(method, p[2], p[4:])
        if method == "DELETE" and p[:2] == ["v1", "traces"] and len(p) == 3:
            return self.delete_session(p[2])
        return self.send(404, {"error": {"code": "not_found", "message": "no such endpoint"}})

    # ── Sessions §5 ───────────────────────────────────────────────────────────────────
    def share_endpoint(self, method: str, sid: str, rest: list[str]):
        if sid not in SESSIONS or SESSIONS[sid]["deleted"]:
            return self.send(404, {"error": {"code": "session_not_found", "message": "gone"}})
        existing = BY_SESSION.get(sid) or []

        if method == "POST" and not rest:
            if existing and DEFECT != "multi_mint":
                return self.send(200, self.share_body(existing[-1], sid))
            share_id = f"share_{uuid.uuid4().hex[:12]}"
            SHARES[share_id] = sid
            BY_SESSION.setdefault(sid, []).append(share_id)
            return self.send(200, self.share_body(share_id, sid))

        if method == "GET" and not rest:
            if not existing:
                return self.send(404, {"error": {"code": "share_not_found", "message": "none"}})
            if DEFECT == "get_share_disagrees":
                return self.send(200, {**self.share_body(existing[-1], sid),
                                       "url": f"http://127.0.0.1:{PORT}/v1/shares/share_elsewhere"})
            return self.send(200, self.share_body(existing[-1], sid))

        if method == "DELETE" and not rest:
            if not existing:
                return self.send(404, {"error": {"code": "share_not_found", "message": "none"}})
            newest = existing[-1]
            if DEFECT != "revoke_lies":
                doomed = [newest] if DEFECT == "multi_mint" else list(existing)
                for s in doomed:
                    SHARES.pop(s, None)
                BY_SESSION[sid] = [s for s in existing if s not in doomed]
            return self.send(200, {"id": newest, "object": "session.share", "deleted": True})

        return self.send(405, {"error": {"code": "method_not_allowed", "message": "no"}})

    def share_body(self, share_id: str, sid: str) -> dict:
        return {"id": share_id, "object": "session.share", "session_id": sid,
                "url": f"http://127.0.0.1:{PORT}/v1/shares/{share_id}",
                "created_at": int(time.time())}

    def shared_view(self, method: str, share_id: str):
        if DEFECT == "view_needs_auth" and self.bearer() != KEY:
            return self.send(401, {"error": {"code": "unauthorized", "message": "sign in"}})
        sid = SHARES.get(share_id)
        if not sid:
            return self.send(404, {"error": {"code": "not_found", "message": "no such share"}})
        if SESSIONS.get(sid, {}).get("deleted") and DEFECT != "share_outlives_session":
            return self.send(404, {"error": {"code": "not_found", "message": "no such share"}})
        if method == "GET":
            return self.send(200, view_of(sid))
        if DEFECT == "view_accepts_writes":
            return self.send(200, {"ok": True})
        return self.send(405, {"error": {"code": "method_not_allowed", "message": "read-only"}})

    # ── Sessions §6 ───────────────────────────────────────────────────────────────────
    def delete_session(self, sid: str):
        if sid not in SESSIONS:
            return self.send(404, {"error": {"code": "session_not_found", "message": "gone"}})
        SESSIONS[sid]["deleted"] = True
        if DEFECT != "share_outlives_session":
            for s in BY_SESSION.pop(sid, []):
                SHARES.pop(s, None)
        return self.send(200, {"id": sid, "object": "session", "deleted": True})


if __name__ == "__main__":
    print(f"stub: defect={DEFECT} port={PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
