"""One DeepSeek Harness turn, as a runner subprocess.

Spawned per turn by server.py (the same one-process-per-turn contract as every other backend:
the runner reads NDJSON off stdout, cancel is a process-group kill). Inside, the official
Python SDK (`deepseek-harness-sdk`, pinned) drives the bundled JSON-RPC runtime executable
(`deepseek-harness-runtime-bin`, same pinned version); every `session.event` notification is
re-emitted on stdout as one JSON line for server.py's normalizer.

THE RELAY, and why it exists. The dsh LLM adapter accumulates streamed tool calls the OpenAI
way — id from `call.id`, name from `call.function.name`, guarded by `!== undefined`. OpenAI
OMITS those fields on continuation deltas; aggregators like TokenRouter send them as EMPTY
STRINGS, so the second delta overwrites the real id/name with "" and every tool call dies as
UNKNOWN_TOOL (captured live 2026-08-20 against deepseek/deepseek-v4-flash). The relay sits on
loopback between the runtime and the endpoint and drops those empty fields from tool_call
deltas — nothing else is touched. It also means the REAL key lives only in this process: the
runtime is launched with DEEPSEEK_BASE_URL pointing at the relay and a placeholder key, so the
credential never enters the dsh process env, its session log, or anything it could checkpoint.
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import socket
import sys
import threading
import urllib.request

UPSTREAM_BASE = ""   # set in main() from HR_DSH_BASE_URL, then scrubbed from the env
UPSTREAM_KEY = ""


def _rewrite_sse_line(line: bytes) -> bytes:
    """Drop empty-string id/name from tool_call deltas in one `data:` SSE line."""
    if not line.startswith(b"data: {"):
        return line
    try:
        obj = json.loads(line[6:])
        for ch in obj.get("choices") or []:
            for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                if tc.get("id") == "":
                    del tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name") == "":
                    del fn["name"]
        return b"data: " + json.dumps(obj, separators=(",", ":")).encode()
    except Exception:  # noqa: BLE001 — a line we cannot parse is a line we must not alter
        return line


class _Relay(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        # DEEPSEEK_BASE_URL carries /v1 and the adapter appends /chat/completions, so the
        # incoming path is /v1/...; the upstream base also ends in /v1 — join without doubling.
        tail = self.path.removeprefix("/v1") if self.path.startswith("/v1/") else self.path
        req = urllib.request.Request(
            UPSTREAM_BASE.rstrip("/") + tail,
            data=body, method="POST",
            headers={"content-type": self.headers.get("content-type") or "application/json",
                     "authorization": f"Bearer {UPSTREAM_KEY}",
                     "accept": self.headers.get("accept") or "*/*"})
        try:
            resp = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:  # pass provider errors through verbatim
            data = e.read()
            self.send_response(e.code)
            self.send_header("content-type", e.headers.get("content-type") or "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        ctype = resp.headers.get("content-type") or ""
        self.send_response(resp.status)
        self.send_header("content-type", ctype)
        if "text/event-stream" in ctype:
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            buf = b""
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    out = _rewrite_sse_line(line.rstrip(b"\r")) + b"\n"
                    self.wfile.write(f"{len(out):x}\r\n".encode() + out + b"\r\n")
                self.wfile.flush()
            if buf:
                out = _rewrite_sse_line(buf)
                self.wfile.write(f"{len(out):x}\r\n".encode() + out + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        else:
            data = resp.read()
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *a):  # diagnostics belong on stderr, never stdout
        pass


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    sys.stdout.flush()


def _mcp_cordis(home: pathlib.Path, servers: list[dict]) -> str | None:
    """Bundled default composition + one dsh-mcp-client entry per enabled server."""
    import deepseek_harness_runtime as runtime
    base = pathlib.Path(runtime.bundled_default_config_path()).read_text()
    blocks = []
    for i, s in enumerate(servers):
        url = (s or {}).get("url")
        if not url:
            continue
        name = "".join(c for c in str((s or {}).get("name") or f"mcp{i}") if c.isalnum() or c in "_-")[:32] or f"mcp{i}"
        entry = {"id": f"hr-mcp-{i}", "name": "@deepseek-ai/dsh-mcp-client",
                 "config": {"transport": "streamable-http", "serverName": name, "url": url}}
        hdrs: dict = {}
        auth = (s or {}).get("auth")
        if auth:
            hdrs["Authorization"] = auth if str(auth).lower().startswith("bearer ") else f"Bearer {auth}"
        if isinstance((s or {}).get("headers"), dict):
            hdrs.update({str(k): str(v) for k, v in s["headers"].items() if k and v is not None})
        if hdrs:
            entry["config"]["headers"] = hdrs
        blocks.append(entry)
    if not blocks:
        return None
    import yaml
    path = home / ".dsh" / "cordis.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(base + "\n" + yaml.safe_dump(blocks, sort_keys=False))
    return str(path)


def main() -> int:
    global UPSTREAM_BASE, UPSTREAM_KEY
    job = json.loads(sys.argv[1])
    UPSTREAM_BASE = os.environ.pop("HR_DSH_BASE_URL", "")
    UPSTREAM_KEY = os.environ.pop("HR_DSH_API_KEY", "")
    home = pathlib.Path(os.environ.get("HOME") or ".")
    cwd = job.get("cwd") or os.getcwd()
    sessions = home / ".dsh" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Relay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    os.environ["DEEPSEEK_API_KEY"] = "hr-relay"   # the real key never reaches the runtime

    from deepseek_harness import DeepSeekHarness

    kwargs = dict(provider="deepseek-official", model=job["model"],
                  cwd=cwd, session_root=str(sessions))
    cordis = _mcp_cordis(home, job.get("mcp_servers") or [])
    if cordis:
        kwargs["cordis"] = cordis
    sid = job.get("session_id") or None
    _emit("__hr_init", {"session_id": sid or "", "relay_port": srv.server_address[1]})
    with DeepSeekHarness(**kwargs) as h:
        r = h.run(job["prompt"], session_id=sid,
                  on_notification=lambda n: _emit(getattr(n, "method", ""), getattr(n, "payload", None)))
        _emit("__hr_result", {"final": r.final_response or "", "reason": r.finish_reason,
                              "session_id": r.session_id})
    return 0


if __name__ == "__main__":
    sys.exit(main())
