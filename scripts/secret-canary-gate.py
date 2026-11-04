#!/usr/bin/env python3
"""The release gate for "nothing left to read in a session". Runs as root INSIDE a container on a
fresh volume, with no provider key of its own:

    docker cp scripts/secret-canary-gate.py smoke:/tmp/gate.py
    docker exec -i smoke python3 -I /tmp/gate.py

It plants a unique canary in every credential one turn can be given: the connection's key, an MCP
server's bearer, declared header, url path and url query, and the same in a package's mcp.json. Then
it runs one turn per base against a stand-in model and a stand-in MCP server, and looks for each
canary, raw, base64 and url-encoded, wherever a session could read it or carry it away:

    - the environment and command line of every process of a session uid, during the turn
    - every file in the session's folder, during and after the turn, git objects included
    - everything else on the volume after the turn: checkpoints, blobs, databases, the secret store
    - what a client reads back: the response, its input items, the session's turns

A scan that looks in the wrong place finds nothing, and nothing looks like a pass. So each place has
a control, a value that MUST be found there. Missing it fails the base as BLIND.

Prints labels and paths, never a value. Exit 0 only when every base is clean and no base is blind.
Stdlib only, since this runs on the image's own python.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import glob
import gzip
import http.server
import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

GATEWAY = "http://127.0.0.1:8080"
ORG = "local"
SESSION_UID_MIN = 20000             # the runner's per-session uids start here
SKIP_AT_REST = ("/data/agent-tools", "/data/environments")   # GBs of tool installs, written before any canary
SECRET_FILES = ("/data/secret-key", "/data/selfhost-initial-password")   # hold the instance's own, by design
MAX_FILE = 8 * 1024 * 1024
HOLD_S = 12                         # how long the first model call of a base waits, so its CLI is alive to scan
TURN_S = 180
MCP_ADDRESS = "hr-mcp-"
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

# The provider a base's connection needs, where it isn't an OpenAI-compatible endpoint.
PROVIDER = {"claude": "anthropic", "gemini": "google", "codex": "openai", "systemone": "openrouter",
            "dsh": "tokenrouter", "kimi": "tokenrouter", "minimax": "tokenrouter", "grok": "tokenrouter", "qwen": "tokenrouter"}
# Bases with no way to take a remote MCP server, so no relay address is expected in their session. A
# base not named here that shows no address fails as BLIND: it may simply have dropped the server.
NO_MCP: dict[str, str] = {}
# Bases the gate can't run without a vendor's own service, and why. Named here, or they fail.
NOT_RUN: dict[str, str] = {"qoder": "its runtime is the vendor's cloud, and no agent runs on this machine"}


def needles(value: str) -> list[bytes]:
    raw = value.encode()
    return [raw, base64.b64encode(raw), base64.urlsafe_b64encode(raw), urllib.parse.quote(value, safe="").encode()]


def expand(data: bytes) -> list[bytes]:
    """The bytes, and what they hold if they are a compressed stream or an archive. Two levels: a
    checkpoint is a compressed tar, and a tar can hold a compressed file."""
    out = [data]
    for _ in range(2):
        more: list[bytes] = []
        for blob in out[-1:] if len(out) > 1 else out:
            more.extend(_unwrap(blob))
        if not more:
            break
        out.extend(more)
    return out


def _unwrap(blob: bytes) -> list[bytes]:
    found: list[bytes] = []
    head = blob[:2]
    try:
        if head == b"\x1f\x8b":
            found.append(gzip.decompress(blob))
        elif len(blob) > 2 and head[0] == 0x78 and (head[0] * 256 + head[1]) % 31 == 0:
            found.append(zlib.decompress(blob))
        elif head == b"\x28\xb5":
            pass        # zstd is not in the stdlib; a checkpoint here is gzip, and the control would say otherwise
    except (OSError, EOFError, zlib.error):
        pass
    target = found[0] if found else blob
    if len(target) > 512 and target[257:262] == b"ustar":
        try:
            with tarfile.open(fileobj=io.BytesIO(target)) as tf:
                for m in tf:
                    if m.isreg() and m.size <= MAX_FILE:
                        f = tf.extractfile(m)
                        if f:
                            found.append(f.read())
        except (tarfile.TarError, OSError, EOFError):
            pass
    return found


class Table:
    """Every value to look for, by label. Holds them in memory only; reports the label."""

    def __init__(self) -> None:
        self.by_label: dict[str, list[bytes]] = {}
        self.hits: dict[str, set[str]] = {}
        self.lock = threading.Lock()

    def add(self, label: str, value: str) -> None:
        if value and len(value) >= 12:
            self.by_label[label] = needles(value)

    def scan(self, data: bytes, where: str, *, only: tuple[str, ...] | None = None) -> None:
        for blob in expand(data):
            for label, forms in list(self.by_label.items()):
                if only and not label.startswith(only):
                    continue
                if any(n in blob for n in forms):
                    with self.lock:
                        self.hits.setdefault(label, set()).add(where)

    def where(self, label: str) -> set[str]:
        return self.hits.get(label, set())


def scan_git(git_dir: str, table: Table, where: str) -> None:
    """Every object of a repository, packed or loose, through git itself."""
    try:
        r = subprocess.run(["git", "--git-dir", git_dir, "-c", "safe.directory=*", "cat-file", "--batch-all-objects",
                            "--batch"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return
    table.scan(r.stdout, f"{where} (git objects)")


def scan_tree(root: str, table: Table, where: str, *, skip: tuple[str, ...] = (), skip_files: tuple[str, ...] = ()) -> int:
    n = 0
    for dp, dns, fns in os.walk(root, followlinks=False):
        dns[:] = [d for d in dns if not os.path.join(dp, d).startswith(skip or ("\0",))]
        if os.path.basename(dp) == ".git" or (os.path.isdir(os.path.join(dp, "objects")) and os.path.isfile(os.path.join(dp, "HEAD"))):
            scan_git(dp, table, f"{where}:{os.path.relpath(dp, root)}")
        for fn in fns:
            p = os.path.join(dp, fn)
            if p in skip_files or os.path.islink(p):
                continue
            try:
                if not os.path.isfile(p) or os.path.getsize(p) > MAX_FILE:
                    continue
                with open(p, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            n += 1
            table.scan(data, f"{where}:{os.path.relpath(p, root)}")
    return n


def scan_session_processes(table: Table) -> int:
    n = 0
    for d in glob.glob("/proc/[0-9]*"):
        try:
            if os.stat(d).st_uid < SESSION_UID_MIN:
                continue
            with open(f"{d}/comm", "rb") as fh:
                comm = fh.read().strip().decode(errors="replace")
            for part in ("environ", "cmdline"):
                with open(f"{d}/{part}", "rb") as fh:
                    table.scan(fh.read(), f"process {comm} {part}")
            n += 1
        except OSError:
            continue
    return n


# ── the stand-ins ─────────────────────────────────────────────────────────────────────────────

class Stand:
    held: set[str] = set()
    model_reached: set[str] = set()
    mcp_reached: set[str] = set()
    lock = threading.Lock()
    expected: dict[str, dict] = {}


def _sse(events: list[str]) -> bytes:
    return "".join(events).encode()


def _model_body(path: str, body: dict) -> tuple[str, bytes]:
    stream = bool(body.get("stream")) or "streamGenerateContent" in path
    model = str(body.get("model") or "stand-in")
    if "generateContent" in path or "GenerateContent" in path:
        one = {"candidates": [{"content": {"role": "model", "parts": [{"text": "OK"}]}, "finishReason": "STOP", "index": 0}],
               "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}}
        return ("text/event-stream", f"data: {json.dumps(one)}\n\n".encode()) if stream else ("application/json", json.dumps(one).encode())
    if path.endswith("/messages"):
        msg = {"id": "msg_stand", "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None,
               "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
        if not stream:
            return "application/json", json.dumps({**msg, "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn"}).encode()
        ev = [("message_start", {"type": "message_start", "message": msg}),
              ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
              ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "OK"}}),
              ("content_block_stop", {"type": "content_block_stop", "index": 0}),
              ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
              ("message_stop", {"type": "message_stop"})]
        return "text/event-stream", _sse([f"event: {k}\ndata: {json.dumps(v)}\n\n" for k, v in ev])
    if path.endswith("/responses"):
        item = {"id": "msg_stand", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "OK", "annotations": []}]}
        done = {"id": "resp_stand", "object": "response", "status": "completed", "model": model, "output": [item],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
        if not stream:
            return "application/json", json.dumps(done).encode()
        ev = [{"type": "response.created", "response": {**done, "status": "in_progress", "output": []}},
              {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
              {"type": "response.content_part.added", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "part": {"type": "output_text", "text": "", "annotations": []}},
              {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "delta": "OK"},
              {"type": "response.output_text.done", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "text": "OK"},
              {"type": "response.content_part.done", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "part": item["content"][0]},
              {"type": "response.output_item.done", "output_index": 0, "item": item},
              {"type": "response.completed", "response": done}]
        return "text/event-stream", _sse([f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in ev])
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    if not stream:
        return "application/json", json.dumps({"id": "chatcmpl-stand", "object": "chat.completion", "created": 1, "model": model, "usage": usage,
                                               "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}]}).encode()
    chunk = {"id": "chatcmpl-stand", "object": "chat.completion.chunk", "created": 1, "model": model}
    return "text/event-stream", _sse([
        f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': None}]})}\n\n",
        f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}], 'usage': usage})}\n\n",
        "data: [DONE]\n\n"])


class QuietServer(http.server.ThreadingHTTPServer):
    """A CLI that hangs up mid-answer is ordinary here."""
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        return


class StandHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a) -> None:
        return

    def _send(self, status: int, ctype: str, data: bytes, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _mcp(self, backend: str, body: dict) -> None:
        want = Stand.expected.get(backend) or {}
        if (self.headers.get("authorization") == f"Bearer {want.get('bearer')}"
                and self.headers.get("x-canary") == want.get("header")
                and want.get("query", "\0") in self.path and want.get("path", "\0") in self.path):
            with Stand.lock:
                Stand.mcp_reached.add(backend)
        else:
            self._send(401, "application/json", b'{"error":"the configured credentials did not arrive"}')
            return
        if self.command != "POST":
            self._send(405, "application/json", b"{}")
            return
        method = body.get("method")
        if "id" not in body:
            self._send(202, "application/json", b"")
            return
        result = {"initialize": {"protocolVersion": (body.get("params") or {}).get("protocolVersion") or "2025-03-26",
                                 "capabilities": {"tools": {}}, "serverInfo": {"name": "stand-in", "version": "1"}},
                  "tools/list": {"tools": []}, "resources/list": {"resources": []}, "prompts/list": {"prompts": []},
                  "ping": {}}.get(str(method))
        out = {"jsonrpc": "2.0", "id": body.get("id"), "result": result} if result is not None else \
              {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "not here"}}
        self._send(200, "application/json", json.dumps(out).encode())

    def _handle(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts[0] == "mcp-stand" and len(parts) > 1:
            self._mcp(parts[1], body if isinstance(body, dict) else {})
            return
        backend = parts[0] if parts else ""
        if self.path.split("?")[0].endswith("/models"):
            self._send(200, "application/json", json.dumps({"object": "list", "data": [{"id": "stand-in", "object": "model"}]}).encode())
            return
        if self.command != "POST":
            self._send(404, "application/json", b"{}")
            return
        with Stand.lock:
            first = backend not in Stand.held
            Stand.held.add(backend)
            Stand.model_reached.add(backend)
        if first:
            time.sleep(HOLD_S)
        ctype, data = _model_body(self.path.split("?")[0], body if isinstance(body, dict) else {})
        self._send(200, ctype, data)

    do_GET = do_POST = do_DELETE = do_HEAD = _handle  # noqa: N815


# ── the run ───────────────────────────────────────────────────────────────────────────────────

def instance_secrets() -> dict[str, str]:
    """The instance's own secrets, read as root from the gateway's environment, and held in memory."""
    found: dict[str, str] = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            with open(f"{d}/environ", "rb") as fh:
                env = fh.read().split(b"\0")
        except OSError:
            continue
        for kv in env:
            k, _, v = kv.partition(b"=")
            if k in (b"HR_SECRET_KEY", b"HARNESS_INTERNAL_KEY", b"HR_AUTH_PASSWORD") and v:
                found.setdefault(k.decode(), v.decode())
    return found


def call(method: str, path: str, headers: dict, body: dict | None = None, timeout: int = 60) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(GATEWAY + path, data=data, method=method,
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (OSError, ValueError) as e:
        return 0, {"error": {"message": type(e).__name__}}


def run_base(x: dict, stand: str, table: Table, internal: dict, api: dict, seen: dict) -> dict:
    base, backend = x["id"], x.get("backend") or x["id"]
    tag = uuid.uuid4().hex
    c = {k: f"canary-{k}-{uuid.uuid4().hex}" for k in ("conn", "bearer", "header", "path", "query",
                                                       "pkg-bearer", "pkg-header", "pkg-path", "pkg-query")}
    ctrl = {k: f"control-{k}-{uuid.uuid4().hex}" for k in ("env", "file", "input")}
    for k, v in c.items():
        table.add(f"{base}:canary:{k}", v)
    for k, v in ctrl.items():
        table.add(f"{base}:control:{k}", v)
    Stand.expected[backend] = {"bearer": c["bearer"], "header": c["header"], "path": c["path"], "query": c["query"]}
    Stand.expected[f"{backend}-pkg"] = {"bearer": c["pkg-bearer"], "header": c["pkg-header"], "path": c["pkg-path"], "query": c["pkg-query"]}
    row = {"base": base, "backend": backend, "status": "", "error": ""}
    conn = f"canary-{backend}"
    models = x.get("models") or []
    marked = [m.get("id") for m in models if isinstance(m, dict) and (m.get("default") or m.get("is_default"))]
    model = (marked or [(models[0].get("id") if isinstance(models[0], dict) else models[0])] if models else ["stand-in"])[0]
    code, _ = call("PUT", f"/v1/orgs/global/connections/{conn}", internal,
                   {"backend": backend, "provider": PROVIDER.get(backend, "openai-api"), "api_key": c["conn"],
                    "base_url": f"{stand}/{backend}/v1", "model": model})
    if code != 200:
        row["error"] = f"connection {code}"
        return row
    code, _ = call("PUT", f"/v1/orgs/global/policy/{backend}", internal, {"connections": [conn]})
    if code != 200:
        row["error"] = f"policy {code}"
        return row
    # With its connection in place the catalog says what this base can serve: the default where it can,
    # or the first model it can. Which model it is changes nothing the gate looks at.
    code, b = call("GET", "/v1/bases", api)
    now = next((y for y in (b.get("data") or b.get("bases") or []) if y.get("id") == base), x)
    served = [m.get("id") for m in (now.get("models") or []) if isinstance(m, dict) and m.get("available") is not False]
    if served and model not in served:
        model = served[0]
    pkg = {"name": f"canary{tag[:8]}", "files": [
        {"path": "plugin.json", "content": json.dumps({"$schema": PLUGIN_SCHEMA, "name": f"canary{tag[:8]}", "version": "1.0.0", "description": "gate"})},
        {"path": "notes.txt", "content": ctrl["file"]},
        {"path": "mcp.json", "content": json.dumps({"$schema": MCP_SCHEMA, "mcpServers": {"pkgremote": {
            "type": "streamable-http", "url": f"{stand}/mcp-stand/{backend}-pkg/{c['pkg-path']}/mcp?key={c['pkg-query']}",
            "headers": {"Authorization": f"Bearer {c['pkg-bearer']}", "X-Canary": c["pkg-header"]}}}})}]}
    code, h = call("POST", "/v1/harnesses", api, {
        "name": f"canary {base} {tag[:6]}", "base": base, "default_model": model, "timeout_seconds": TURN_S - 30,
        "env": {"CANARY_CONTROL": ctrl["env"]}, "plugins": [pkg],
        "mcp_servers": [{"name": "standin", "url": f"{stand}/mcp-stand/{backend}/{c['path']}/mcp?key={c['query']}",
                         "transport": "http", "auth": c["bearer"], "headers": {"X-Canary": c["header"]}, "enabled": True}]})
    if code not in (200, 201):
        row["error"] = f"harness {code}: {str((h.get('error') or {}).get('message'))[:120]}"
        return row
    hid = h.get("id")
    code, r = call("POST", "/v1/responses", api, {"model": model, "input": f"Reply OK. {ctrl['input']}",
                                                  "metadata": {"harness_id": hid}}, timeout=TURN_S)
    row["status"] = str(r.get("status") or code)
    err = r.get("error")
    if err:
        row["error"] = str(err.get("message") if isinstance(err, dict) else err)[:160]
    rid, sid = r.get("id"), r.get("session_id") or (r.get("metadata") or {}).get("session_id")
    row["rid"], row["sid"] = rid, sid
    for path in ([f"/v1/responses/{rid}", f"/v1/responses/{rid}/input_items"] if rid else []) + \
                ([f"/v1/sessions/{sid}/turns", f"/v1/sessions/{sid}"] if sid else []):
        code, d = call("GET", path, api)
        if code == 200:
            table.scan(json.dumps(d).encode(), f"client read {path.split('/')[2]}/{path.split('/')[-1][:9]}")
    return row


def at_rest_allowed(kind: str, where: str) -> bool:
    """What is stored as it was written, by what it is, on the volume only. A session or a client read
    is never allowed any of it. A package is the customer's own upload, kept as uploaded, and a url
    is configuration the owner reads back. Credentials a harness holds are not on this list."""
    if not where.startswith("volume:"):
        return False
    if kind.startswith("pkg-"):
        return where.startswith(("volume:blobs/harness-sessions/plugins/", "volume:graph.db"))
    return kind in ("path", "query")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated base ids")
    ap.add_argument("--jobs", type=int, default=5)
    args = ap.parse_args()

    for _ in range(90):              # a container that has only just started
        if call("GET", "/healthz", {}, timeout=5)[0] == 200:
            break
        time.sleep(2)
    secrets = instance_secrets()
    if "HARNESS_INTERNAL_KEY" not in secrets:
        print("BLIND: the instance's internal key was not found")
        return 1
    table = Table()
    for k, v in secrets.items():
        table.add(f"instance:{k}", v)
    internal = {"x-harness-internal": secrets["HARNESS_INTERNAL_KEY"], "x-harness-org": ORG, "x-harness-member": "owner"}
    code, k = call("POST", f"/v1/orgs/{ORG}/keys", internal,
                   {"name": "secret-canary-gate", "workspace": "default", "member_id": "secret-canary-gate", "workspace_default": True})
    tok = k.get("key") or k.get("token") or k.get("secret") or ""
    if not tok:
        print(f"BLIND: no API key ({code})")
        return 1
    table.add("instance:api-key", tok)
    api = {"authorization": f"Bearer {tok}"}

    srv = QuietServer(("127.0.0.1", 0), StandHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    stand = f"http://127.0.0.1:{srv.server_address[1]}"

    code, b = call("GET", "/v1/bases", api)
    items = b.get("data") or b.get("bases") or []
    only = {x for x in args.only.split(",") if x}
    items = [x for x in items if (not only or x.get("id") in only)]
    run = [x for x in items if x.get("id") not in NOT_RUN]
    print(f"bases: {len(items)} | running {len(run)} | named as not run: {sorted(set(x.get('id') for x in items) & set(NOT_RUN))}", flush=True)
    if not run:
        print("BLIND: no base to run")
        return 1

    stop = threading.Event()
    seen: dict = {}
    procs = {"n": 0}

    def watch_processes() -> None:
        while not stop.is_set():
            procs["n"] += scan_session_processes(table)
            stop.wait(0.25)

    def watch_folders() -> None:
        while not stop.is_set():
            scan_tree("/data/workspaces", table, "session folder")
            stop.wait(2)
    watchers = [threading.Thread(target=watch_processes, daemon=True), threading.Thread(target=watch_folders, daemon=True)]
    for w in watchers:
        w.start()
    t0 = time.time()
    with cf.ThreadPoolExecutor(args.jobs) as ex:
        rows = list(ex.map(lambda x: run_base(x, stand, table, internal, api, seen), run))
    stop.set()
    for w in watchers:
        w.join(60)
    # After the turns: what stayed, and everything else on the volume.
    scan_tree("/data/workspaces", table, "session folder")
    files = scan_tree("/data", table, "volume", skip=SKIP_AT_REST + ("/data/workspaces",), skip_files=SECRET_FILES)
    print(f"turns took {round(time.time() - t0)}s | session processes scanned {procs['n']} | volume files {files}", flush=True)

    # A relay address in the session is the proof its MCP config was written at all. Each route's token
    # dies with its turn, so what is looked for is the shape, in the session's stored files.
    mcp_addr: set[str] = set()
    for r in rows:
        sid = r.get("sid")
        if not sid:
            continue
        for d in glob.glob(f"/data/workspaces/{sid}*"):
            for dp, _dns, fns in os.walk(d):
                for fn in fns:
                    try:
                        with open(os.path.join(dp, fn), "rb") as fh:
                            if MCP_ADDRESS.encode() in fh.read(MAX_FILE):
                                mcp_addr.add(r["base"])
                    except OSError:
                        pass

    failed = 0
    for r in rows:
        base = r["base"]
        leaks = {}
        for lab in table.by_label:
            if lab.startswith(f"{base}:canary:"):
                bad = sorted(w for w in table.where(lab) if not at_rest_allowed(lab.split(":")[-1], w))
                if bad:
                    leaks[lab] = bad[:4]
        env_seen = any(w.startswith("process ") for w in table.where(f"{base}:control:env"))
        file_seen = bool(table.where(f"{base}:control:file"))
        input_seen = any(w.startswith("client read") for w in table.where(f"{base}:control:input"))
        blind = [n for n, ok in (("env", env_seen), ("file", file_seen), ("stored", input_seen)) if not ok]
        if base not in NO_MCP and base not in mcp_addr and r["backend"] not in Stand.mcp_reached:
            blind.append("mcp-address")
        state = "LEAK" if leaks else "BLIND" if blind else "clean"
        failed += state != "clean"
        print(f"{state:5} {base:16} turn {r['status'] or '-':11} model {'y' if r['backend'] in Stand.model_reached else 'n'} "
              f"mcp {'y' if r['backend'] in Stand.mcp_reached else 'n'} blind {','.join(blind) or '-'} {r['error'][:90]}", flush=True)
        for lab, where in leaks.items():
            print(f"      {lab.split(':')[-1]}: {where}", flush=True)
    inst = {lab: sorted(table.where(lab))[:6] for lab in table.by_label if lab.startswith("instance:") and table.where(lab)}
    session_inst = {lab: [w for w in where if w.startswith(("process ", "session folder", "client read"))] for lab, where in inst.items()}
    session_inst = {k: v for k, v in session_inst.items() if v}
    if session_inst:
        failed += 1
        print(f"LEAK  instance secrets in a session or a client read: {session_inst}", flush=True)
    # The at-rest controls: the volume scan must be able to see a value that is stored in the clear.
    if not any(any(w.startswith("volume:") for w in table.where(f"{r['base']}:control:env")) for r in rows):
        failed += 1
        print("BLIND the volume scan found no harness variable, which is stored in the clear", flush=True)
    print(f"SUMMARY {len(rows) - failed} clean of {len(rows)} | model reached {len(Stand.model_reached)} | mcp reached {len(Stand.mcp_reached)}", flush=True)
    print("SECRET_CANARY_GATE " + ("FAIL" if failed else "PASS"), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
