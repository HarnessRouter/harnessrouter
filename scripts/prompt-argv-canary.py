#!/usr/bin/env python3
"""Does a CLI that is handed its prompt in-process ever put it back on a command line? Runs INSIDE the container, as
the product's own user (uid 10001), against the runner, with no provider key of its own:

    docker cp scripts/prompt-argv-canary.py hr:/tmp/prompt-argv-canary.py
    docker exec -u agent -i hr python3 -I /tmp/prompt-argv-canary.py                  # kimi and jcode
    docker exec -u agent -i hr python3 -I /tmp/prompt-argv-canary.py --bases jcode --interval 0.05

Kimi Code and jcode take their prompt only as an argument, so the runner sets that argument inside the CLI's own
process (runner/prompt_preload.cjs, runner/prompt_argv.c) and the command line it is started with holds only a
placeholder. In-process, though, the CLI's own argv now holds the text: a CLI that started itself again, or a worker
or a daemon, from its own argv would put the prompt back on a command line. Stand-ins can't show that; the real
binaries can.

For each base: a first and a continued turn in one session, each prompt carrying a canary of its own, and the
continued turn's instructions edited to carry a third (an edit is handed over with the message). From before each
turn is started until it is done, every /proc/<pid>/cmdline is read about every --interval seconds as this script's
user, never the session's, children included. A turn passes when no sample held any canary and its answer is its own
canary: the stand-in model this starts answers "Reply with exactly: X" with X, so the CLI was handed the prompt.

Also printed per turn: the samples taken, and every process seen under a CLI process (one whose command line holds
the placeholder): its pid, parent, the first word of its command line, and whether that pid's command line changed
while it ran (an exec of itself, or a title it set).

The stand-in answers every model call itself, so nothing reaches a real provider. Exit 0 when every turn passes.
"""
from __future__ import annotations

import argparse
import glob
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

RUNNER = "http://127.0.0.1:8081"
PLACEHOLDER = b"{hr:prompt}"
ASKED = re.compile(r"Reply with exactly: ([A-Za-z0-9-]+)")
TURN_S = 300


# ── the stand-in model ──────────────────────────────────────────────────────────────────────────────────────────────
class Stand(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict] = []

    def log_message(self, *_a) -> None:
        return

    def _send(self, status: int, ctype: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.split("?")[0].endswith("/models"):
            self._send(200, "application/json", json.dumps({"object": "list", "data": [{"id": "stand-in"}]}).encode())
        else:
            self._send(404, "application/json", b"{}")

    def do_POST(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        Stand.requests.append(body)
        asked = ASKED.findall(json.dumps(body.get("messages") or body.get("input") or []))
        text = asked[-1] if asked else "DONE"
        model = str(body.get("model") or "stand-in")
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if not body.get("stream"):
            self._send(200, "application/json", json.dumps({
                "id": "chatcmpl-stand", "object": "chat.completion", "created": 1, "model": model, "usage": usage,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}]}).encode())
            return
        chunk = lambda delta, fin, **kw: {"id": "chatcmpl-stand", "object": "chat.completion.chunk", "created": 1,  # noqa: E731
                                          "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": fin}], **kw}
        events = [chunk({"role": "assistant", "content": text}, None), chunk({}, "stop", usage=usage)]
        data = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        self._send(200, "text/event-stream", data.encode())


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        return


# ── the walk ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _read(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _parent(pid: str) -> int:
    status = _read(f"/proc/{pid}/status") or b""
    m = re.search(rb"^PPid:\s+(\d+)", status, re.M)
    return int(m.group(1)) if m else 0


class Walk:
    """Every /proc/<pid>/cmdline, about every `interval` seconds, until stopped."""

    def __init__(self, canaries: list[str], interval: float) -> None:
        self.canaries = [c.encode() for c in canaries]
        self.interval = interval
        self.samples = 0
        self.hits: list[str] = []
        self.seen: dict[int, dict] = {}         # pid -> {"parent", "first", "lines": set of command lines}
        self.roots: set[int] = set()            # the CLI processes: the placeholder on their command line, or named so
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            lines: dict[int, bytes] = {}
            for d in glob.glob("/proc/[0-9]*"):
                raw = _read(f"{d}/cmdline")
                if raw:
                    lines[int(d.rsplit("/", 1)[1])] = raw
            self.samples += 1
            parents = {pid: _parent(str(pid)) for pid in lines}
            # a CLI may set its own title over its command line once started (Kimi Code does), so a CLI process is
            # remembered once seen, and known by its name as well as by the placeholder
            self.roots |= {pid for pid, raw in lines.items()
                           if PLACEHOLDER in raw or re.match(rb"(?:[^\0]*/)?(?:kimi|jcode[^\0/]*)\0", raw)}
            roots = self.roots
            for pid, raw in lines.items():
                held = [c.decode() for c in self.canaries if c in raw]
                first = raw.split(b"\0", 1)[0].decode(errors="replace").rsplit("/", 1)[-1]
                if held:
                    self.hits.append(f"pid {pid} ({first}): {', '.join(held)}")
                p, under = pid, False
                for _ in range(64):            # under a CLI process: the CLI itself, or anything it started
                    if p in roots:
                        under = True
                        break
                    p = parents.get(p, 0)
                    if p <= 1:
                        break
                if under or pid in self.seen:
                    row = self.seen.setdefault(pid, {"parent": parents.get(pid, 0), "first": first, "lines": set()})
                    row["lines"].add(raw.replace(b"\0", b" ").decode(errors="replace").strip()[:200])
            self.stop.wait(self.interval)

    def __enter__(self) -> "Walk":
        self.thread.start()
        return self

    def __exit__(self, *_a) -> None:
        self.stop.set()
        self.thread.join(timeout=5)


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def runner_env() -> dict[str, str]:
    """The internal key and the runner's address: from this environment, or the gateway's (the same user's)."""
    found = {k: os.environ[k] for k in ("HARNESS_INTERNAL_KEY", "POOL_MGMT_ENDPOINT") if os.environ.get(k)}
    for d in glob.glob("/proc/[0-9]*"):
        env = _read(f"{d}/environ")
        for kv in (env or b"").split(b"\0"):
            k, _, v = kv.partition(b"=")
            if k in (b"HARNESS_INTERNAL_KEY", b"POOL_MGMT_ENDPOINT") and v:
                found.setdefault(k.decode(), v.decode())
    return found


def call(method: str, url: str, key: str, body: dict | None = None, timeout: int = 60) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"content-type": "application/json", "x-harness-internal": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError) as e:
        return 0, {"error": type(e).__name__}


def turn(runner: str, key: str, stand: str, base: str, ident: str, prompt: str, doc: str, resume: str,
         walk: Walk) -> dict:
    body = {"backend": base, "provider": "openai-api", "model": "stand-in", "prompt": prompt,
            "timeout_seconds": TURN_S - 30, "max_turns": 3, "agent_doc": doc, "tools_disabled": [],
            "auth": {"api_key": f"canary-{uuid.uuid4().hex}", "base_url": f"{stand}/{base}/v1"},
            "idempotency_key": uuid.uuid4().hex, "mcp_servers": []}
    if resume:
        body["resume_session_id"] = resume
    with walk:
        code, t = call("POST", f"{runner}/turn?identifier={ident}", key, body)
        if code != 200 or not t.get("turn_id"):
            return {"error": f"turn {code}: {str(t)[:160]}"}
        since, end = 0, time.time() + TURN_S
        while time.time() < end:
            code, r = call("GET", f"{runner}/turn/{t['turn_id']}?identifier={ident}&since={since}&wait=10", key, timeout=30)
            if code != 200:
                return {"error": f"poll {code}"}
            since = int(r.get("n_total") or since)
            if r.get("done"):
                return {"status": r.get("status"), "session_id": r.get("session_id") or "",
                        "result": str(r.get("result") or "").strip(), "error": str(r.get("error") or "")[:160]}
        call("POST", f"{runner}/turn/{t['turn_id']}/cancel?identifier={ident}", key, {})
        return {"error": "timed out"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bases", default="kimi,jcode")
    ap.add_argument("--interval", type=float, default=0.05, help="seconds between two walks of /proc")
    args = ap.parse_args()
    env = runner_env()
    if not env.get("HARNESS_INTERNAL_KEY"):
        print("No internal key: run this as the product's own user inside the container (or set HARNESS_INTERNAL_KEY).")
        return 2
    key, runner = env["HARNESS_INTERNAL_KEY"], (env.get("POOL_MGMT_ENDPOINT") or RUNNER).rstrip("/")
    srv = Server(("127.0.0.1", 0), Stand)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    stand = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"walking /proc as uid {os.getuid()} every {args.interval * 1000:.0f} ms; runner {runner}")
    ok = True
    for base in [b.strip() for b in args.bases.split(",") if b.strip()]:
        ident = f"prompt-argv-canary-{base}-{uuid.uuid4().hex[:10]}"
        h = uuid.uuid4().hex[:12]
        first, second, rules = f"CANARY1-{h}", f"CANARY2-{h}", f"CANARYRULES-{h}"
        canaries = [first, second, rules]
        sid = ""
        try:
            for n, prompt, doc in ((1, f"Reply with exactly: {first}", "Keep replies short."),
                                   (2, f"Reply with exactly: {second}", f"Keep replies short. {rules}")):
                walk = Walk(canaries, args.interval)
                r = turn(runner, key, stand, base, ident, prompt, doc, sid, walk)
                sid = r.get("session_id") or sid
                want = first if n == 1 else second
                passed = not walk.hits and r.get("result") == want and not r.get("error")
                ok = ok and passed
                label = "first" if n == 1 else "continued"
                print(f"{base} {label} turn: {'PASS' if passed else 'FAIL'}  status={r.get('status')} "
                      f"answer={r.get('result')!r} (wanted {want!r}) samples={walk.samples} "
                      f"canary on a command line={walk.hits or 'never'}" + (f" error={r['error']}" if r.get("error") else ""))
                for pid, row in sorted(walk.seen.items()):
                    changed = " (command line changed while it ran)" if len(row["lines"]) > 1 else ""
                    print(f"    pid {pid} <- {row['parent']}: {row['first']}{changed}")
                    for line in sorted(row["lines"]):
                        print(f"        {line}")
        finally:
            call("DELETE", f"{runner}/workspace?identifier={ident}", key)
    srv.shutdown()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
