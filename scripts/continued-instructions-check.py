#!/usr/bin/env python3
"""Does an edit to a harness's instructions reach a task that is continued?

A person changes a harness's instructions (PUT /v1/harnesses/{id}) and continues a task with
previous_response_id. The runner rewrites the base's instruction file every turn, but a CLI that
resumes its own conversation may keep what it read when the conversation started. This runs real
turns of each base against a stand-in model it starts itself, and judges the REQUEST the base sent
the model on the continued turn, never the answer:

    docker cp scripts/continued-instructions-check.py hr:/tmp/cic.py
    docker exec --privileged -i hr python3 -I /tmp/cic.py [--only claude-code,codex] [--via auto]

Per base: instructions carrying marker A; turn 1, whose message carries H1; the instructions
changed to carry marker B; turn 2 continuing turn 1, whose message carries H2. The model request
that carries H2 is the one judged:

    PASS   B is in it, A is not, and H1 is (the edit arrived and turn 1 is remembered)
    SUPERSEDED  A is still in turn 1's part of the history, and B comes after it, saying it replaces
           the earlier copy (how Claude Code, Codex and dsh carry an edited file into a resumed session)
    STALE  A is in it and B is not, or B is not said to replace it (the continued task still
           reads the instructions it started with)
    NO-B / NO-HISTORY  neither copy reached turn 2, or turn 1 is not in it (continuity lost)
    BLIND  turn 1's request did not carry A: the instructions never reach the model this way,
           so turn 2 cannot be judged

A base's turn may end as failed against the stand-in (one that expects a protocol of its own) and
still be judged: what it sent is what is looked at.

Two ways to run a base:

    gateway  the whole path: a harness, PUT /v1/harnesses/{id}, previous_response_id. The model is
             served by an org's own connection in a throwaway org, so no other caller's policy
             changes. Used only where the instance's integrations would not claim the model:
             integrations are tried before any connection, and a claimed model would go to a real
             provider instead of the stand-in.
    runner   the runner's /turn, sent what the gateway sends a continued turn (the CURRENT agent
             doc, the session's resume id, and for a base that cannot resume, the conversation in
             the prompt): for a base whose every model an integration claims on this instance.

The internal key is read from the gateway's environment, and the gateway is not dumpable after it
drops to its own uid, so this needs `docker exec --privileged` (CAP_SYS_PTRACE for this process
only; the container is not changed). Everything made is removed in a finally: the harnesses, the
sessions and their folders, the key, and the throwaway org's connections and policies; the
instance's orgs, connections and policies are listed by name before and after, and must match.

Prints labels, markers and where a marker sat in the request, never a key. Exit 0 when every base
run is PASS or SUPERSEDED. Stdlib only, since this runs on the image's own python.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import http.server
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

GATEWAY = "http://127.0.0.1:8080"
RUNNER = "http://127.0.0.1:8081"
SECRETS_ROOT = "/data/secrets"
TURN_S = 240
# The provider each base's connection names (the secret canary gate's choices, which drive every
# base against an OpenAI- or Anthropic-shaped stand-in); a base not named takes openai-api.
PROVIDER = {"claude": "anthropic", "gemini": "google", "codex": "openai", "systemone": "openrouter",
            "dsh": "tokenrouter", "kimi": "tokenrouter", "minimax": "tokenrouter", "grok": "tokenrouter",
            "qwen": "tokenrouter"}
# Bases that take a provider-native Claude id on an Anthropic connection: an id no integration's
# model map holds (they hold canonical ids), so the gateway path can run them on any instance.
CLAUDE_NATIVE = ("claude", "hermes", "pi", "dsh", "omp")
CLAUDE_NATIVE_ID = "claude-sonnet-4-6"
# Bases that cannot resume a CLI session: the gateway hands them the conversation in the prompt.
NO_RESUME = {"cline"}
NOT_RUN = {"qoder": "its runtime is the vendor's cloud, and no agent runs on this machine"}


# ── the stand-in model ────────────────────────────────────────────────────────────────────────

class Stand:
    lock = threading.Lock()
    seen: list[tuple[float, str, str, bytes]] = []      # (time, tag, path, body)


def _sse(events: list[str]) -> bytes:
    return "".join(events).encode()


def _model_body(path: str, body: dict) -> tuple[str, bytes]:
    """What a provider answers, "OK", in the shape the path asks for (the canary gate's stand-in)."""
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
        # Every field the stricter clients validate (the AI SDK's and litellm's Responses parsers):
        # created_at, the usage details, sequence numbers and logprobs.
        item = {"id": "msg_stand", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "OK", "annotations": [], "logprobs": []}]}
        done = {"id": "resp_stand", "object": "response", "created_at": int(time.time()), "status": "completed",
                "model": model, "output": [item], "error": None, "incomplete_details": None, "instructions": None,
                "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "text": {"format": {"type": "text"}},
                "usage": {"input_tokens": 1, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 1,
                          "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 2}}
        if not stream:
            return "application/json", json.dumps(done).encode()
        ev = [{"type": "response.created", "response": {**done, "status": "in_progress", "output": []}},
              {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
              {"type": "response.content_part.added", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []}},
              {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "delta": "OK", "logprobs": []},
              {"type": "response.output_text.done", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "text": "OK", "logprobs": []},
              {"type": "response.content_part.done", "output_index": 0, "content_index": 0, "item_id": "msg_stand", "part": item["content"][0]},
              {"type": "response.output_item.done", "output_index": 0, "item": item},
              {"type": "response.completed", "response": done}]
        ev = [{**e, "sequence_number": i} for i, e in enumerate(ev)]
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
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        return


class StandHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a) -> None:
        return

    def _send(self, status: int, ctype: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _handle(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        path = self.path.split("?")[0]
        tag = path.strip("/").split("/")[0]
        if path.endswith("/models"):
            self._send(200, "application/json", json.dumps({"object": "list", "data": [{"id": "stand-in", "object": "model"}]}).encode())
            return
        if self.command != "POST":
            self._send(404, "application/json", b"{}")
            return
        with Stand.lock:
            Stand.seen.append((time.time(), tag, path, raw))
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        ctype, data = _model_body(path, body if isinstance(body, dict) else {})
        self._send(200, ctype, data)

    do_GET = do_POST = do_DELETE = do_HEAD = _handle  # noqa: N815


# ── calls ─────────────────────────────────────────────────────────────────────────────────────

def call(method: str, url: str, headers: dict, body: dict | None = None, timeout: int = 60) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json", **headers})
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


def internal_key() -> str:
    for d in glob.glob("/proc/[0-9]*"):
        try:
            with open(f"{d}/environ", "rb") as fh:
                env = fh.read().split(b"\0")
        except OSError:
            continue
        for kv in env:
            k, _, v = kv.partition(b"=")
            if k == b"HARNESS_INTERNAL_KEY" and v:
                return v.decode()
    return ""


def snapshot() -> dict[str, list[str]]:
    """The instance's orgs (secret-store tenants) and the names of their connections and policies.
    Names only: compared before and after the run, so whatever this run made and did not take
    away is said, and nothing the instance had is changed unseen."""
    out: dict[str, list[str]] = {}
    try:
        for t in sorted(os.listdir(SECRETS_ROOT)):
            d = os.path.join(SECRETS_ROOT, t)
            if os.path.isdir(d):
                out[t] = sorted(n for n in os.listdir(d) if n.startswith(("harness-conn-", "harness-policy-")))
    except OSError:
        pass
    return out


def err_of(d: dict) -> str:
    e = d.get("error") if isinstance(d, dict) else None
    if isinstance(e, dict):
        return str(e.get("message") or e)[:160]
    return str(e or (d.get("detail") if isinstance(d, dict) else "") or "")[:160]


# ── judging ───────────────────────────────────────────────────────────────────────────────────

def where(obj, needle: str, path: str = "") -> list[str]:
    """The JSON paths whose string holds `needle` (at most a few): says whether a marker sat in a
    system field, in the first user message, or in a later one."""
    out: list[str] = []
    if isinstance(obj, str):
        if needle in obj:
            out.append(path or "$")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += where(v, needle, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += where(v, needle, f"{path}[{i}]")
    return out[:4]


def _excerpt(doc, at: str, needle: str, width: int = 260) -> str:
    """The text around a marker, at the path `where` gave, on one line."""
    node = doc
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", at):
        try:
            node = node[int(part[1:-1])] if part.startswith("[") else node[part]
        except (KeyError, IndexError, TypeError, ValueError):
            return ""
    text = str(node)
    i = text.find(needle)
    return " ".join(text[max(0, i - width):i + len(needle) + 40].split())


def _superseding(doc, at: str, needle: str) -> bool:
    """Whether the text just before a marker says it replaces an earlier copy of the instructions:
    Codex's "replace all previously provided", Claude Code's "replaces its earlier copy", dsh's
    "instead of the previously loaded"."""
    before = _excerpt(doc, at, needle, width=400).split(needle)[0].lower()
    return "replace" in before or "instead of the previously" in before


def requests_with(tag: str, since: float, needle: str) -> list[tuple[str, bytes]]:
    with Stand.lock:
        return [(p, b) for t, g, p, b in Stand.seen if g == tag and t >= since and needle.encode() in b]


def judge(row: dict, tag: str, t1: float, t2: float, m: dict) -> None:
    first = requests_with(tag, t1, m["H1"])
    first = [x for x in first if m["H2"].encode() not in x[1]]
    second = requests_with(tag, t2, m["H2"])
    row["reqs1"], row["reqs2"] = len(first), len(second)
    row["A1"] = any(m["A"].encode() in b for _, b in first)
    if not second:
        row["verdict"] = "NO-REQUEST"
        return
    p, b = second[-1]          # the last request of the continued turn: what the model answered from
    try:
        doc = json.loads(b)
    except ValueError:
        doc = b.decode(errors="replace")
    row["A2"], row["B2"], row["H1in2"] = m["A"].encode() in b, m["B"].encode() in b, m["H1"].encode() in b
    row["A_at"], row["B_at"] = where(doc, m["A"]), where(doc, m["B"])
    row["show"] = [(k, at, _excerpt(doc, at, m[k])) for k in ("A", "B") for at in row[f"{k}_at"]]
    row["path2"] = p
    if not row["A1"]:
        row["verdict"] = "BLIND"
    elif row["A2"] and row["B2"] and b.rfind(m["B"].encode()) > b.rfind(m["A"].encode()) \
            and all(_superseding(doc, at, m["B"]) for at in row["B_at"]):
        # The base keeps turn 1's copy in its history and adds the edited one AFTER it, saying it
        # replaces the earlier copy: Claude Code and Codex do this on a resumed session. The edit
        # reached the task and is the copy in force; the old one is history, marked superseded.
        row["verdict"] = "SUPERSEDED"
    elif row["A2"]:
        row["verdict"] = "STALE+B" if row["B2"] else "STALE"
    elif not row["B2"]:
        row["verdict"] = "NO-B"
    elif not row["H1in2"]:
        row["verdict"] = "NO-HISTORY"
    else:
        row["verdict"] = "PASS"


def markers() -> dict:
    h = uuid.uuid4().hex[:10]
    return {"A": f"MARKA{h}", "B": f"MARKB{h}", "H1": f"FIRSTMSG{h}", "H2": f"SECONDMSG{h}"}


def instructions(marker: str) -> str:
    return f"Project rule: start every answer with the code word {marker}."


def _channel(backend: str) -> str:
    """A path segment the stand-in's address carries for one base. gemini-cli talks to Google's own
    endpoint unless its base is a channel that serves Google's API under its own root (the runner's
    _gemini_channel, a host match on the address), so the address names that host in its path and
    the turn reaches the stand-in and nothing else."""
    return "/api.tokenrouter.com" if backend == "gemini" else ""


# ── the gateway path ──────────────────────────────────────────────────────────────────────────

def run_gateway(x: dict, ctx: dict) -> dict:
    base, backend = x["id"], x.get("backend") or x["id"]
    row = {"base": base, "via": "gateway", "verdict": "", "error": ""}
    m, tag = markers(), "g" + uuid.uuid4().hex[:10]
    org, ih, api, stand = ctx["org"], ctx["internal"], ctx["api"], ctx["stand"]
    conn = f"cic-{backend}-{uuid.uuid4().hex[:6]}"
    model = ctx["models"][base]
    provider = "anthropic" if model == CLAUDE_NATIVE_ID else PROVIDER.get(backend, "openai-api")
    hid = sid = ""
    try:
        code, d = call("PUT", f"{GATEWAY}/v1/orgs/{org}/connections/{conn}", ih,
                       {"backend": backend, "provider": provider, "api_key": f"standin-{uuid.uuid4().hex}",
                        "base_url": f"{stand}/{tag}{_channel(backend)}/v1", "model": model})
        if code != 200:
            row["error"] = f"connection {code} {err_of(d)}"
            return row
        code, d = call("PUT", f"{GATEWAY}/v1/orgs/{org}/policy/{backend}", ih, {"connections": [conn]})
        if code != 200:
            row["error"] = f"policy {code} {err_of(d)}"
            return row
        spec = {"name": f"cic {base} {tag[-6:]}", "base": base, "default_model": model,
                "timeout_seconds": TURN_S - 40, "system_prompt": instructions(m["A"])}
        code, h = call("POST", f"{GATEWAY}/v1/harnesses", api, spec)
        if code not in (200, 201):
            row["error"] = f"harness {code} {err_of(h)}"
            return row
        hid = str(h.get("id") or "")
        t1 = time.time()
        code, r1 = call("POST", f"{GATEWAY}/v1/responses", api,
                        {"model": model, "input": f"Reply OK. ({m['H1']})", "metadata": {"harness_id": hid}}, timeout=TURN_S)
        sid = str(r1.get("session_id") or (r1.get("metadata") or {}).get("session_id") or "")
        row["turn1"] = str(r1.get("status") or code)
        if r1.get("status") != "completed":
            row["error"] = f"turn 1: {err_of(r1)}"
        code, h2 = call("PUT", f"{GATEWAY}/v1/harnesses/{hid}", api, {**spec, "system_prompt": instructions(m["B"])})
        if code != 200 or m["B"] not in str(h2.get("system_prompt") or h2.get("systemPrompt") or ""):
            row["error"] = f"harness edit {code} {err_of(h2)}"
            return row
        t2 = time.time()
        code, r2 = call("POST", f"{GATEWAY}/v1/responses", api,
                        {"model": model, "input": f"Reply OK. ({m['H2']})", "previous_response_id": r1.get("id"),
                         "metadata": {"harness_id": hid}}, timeout=TURN_S)
        row["turn2"] = str(r2.get("status") or code)
        sid2 = str(r2.get("session_id") or (r2.get("metadata") or {}).get("session_id") or "")
        row["same_session"] = bool(sid) and sid == sid2
        if r2.get("status") != "completed":
            row["error"] = (row["error"] + " | " if row["error"] else "") + f"turn 2: {err_of(r2)}"
        judge(row, tag, t1, t2, m)
        return row
    finally:
        left = []
        if sid and call("DELETE", f"{GATEWAY}/v1/sessions/{sid}", api)[0] != 200:
            left.append("session")
        if hid and call("DELETE", f"{GATEWAY}/v1/harnesses/{hid}", api)[0] != 200:
            left.append("harness")
        if left:
            row["error"] += f" | NOT REMOVED: {', '.join(left)}"


# ── the runner path ───────────────────────────────────────────────────────────────────────────

def runner_turn(ident: str, body: dict, rh: dict) -> dict:
    code, st = call("POST", f"{RUNNER}/turn?identifier={ident}", rh, body, timeout=120)
    if code != 200 or not st.get("turn_id"):
        return {"status": f"start {code}", "error": err_of(st)}
    tid, since, deadline = st["turn_id"], 0, time.time() + TURN_S
    while time.time() < deadline:
        code, d = call("GET", f"{RUNNER}/turn/{tid}?identifier={ident}&since={since}&wait=20", rh, timeout=60)
        if code == 200:
            since = int(d.get("n_total") or since)
            if d.get("done"):
                return d
        else:
            time.sleep(2)
    call("POST", f"{RUNNER}/turn/{tid}/cancel?identifier={ident}", rh, {})
    return {"status": "timed out here", "error": ""}


def run_runner(x: dict, ctx: dict) -> dict:
    base, backend = x["id"], x.get("backend") or x["id"]
    row = {"base": base, "via": "runner", "verdict": "", "error": ""}
    m, tag = markers(), "r" + uuid.uuid4().hex[:10]
    ident = "hsesscic" + uuid.uuid4().hex[:16]
    model = ctx["models"][base]
    auth = {"api_key": f"standin-{uuid.uuid4().hex}", "base_url": f"{ctx['stand']}/{tag}{_channel(backend)}/v1"}
    common = {"backend": backend, "provider": PROVIDER.get(backend, "openai-api"), "model": model,
              "native_model": model if backend == "gemini" else None, "max_turns": 8,
              "timeout_seconds": TURN_S - 40, "auth": auth, "codex_appserver": backend == "codex" and ctx["appserver"]}
    try:
        t1 = time.time()
        r1 = runner_turn(ident, {**common, "prompt": f"Reply OK. ({m['H1']})", "agent_doc": instructions(m["A"]),
                                 "idempotency_key": f"{ident}:1"}, ctx["internal_runner"])
        row["turn1"] = str(r1.get("status"))
        if r1.get("error"):
            row["error"] = f"turn 1: {str(r1.get('error'))[:140]}"
        resume = r1.get("session_id") or None
        row["resume"] = bool(resume)
        prompt2 = f"Reply OK. ({m['H2']})"
        if backend in NO_RESUME and resume:
            # what the gateway hands a base that cannot resume (gateway.app _history_prompt)
            prompt2 = ("<conversation_so_far>\nThis is the conversation in this session so far. Continue it; do not "
                       f"repeat it.\nuser: Reply OK. ({m['H1']})\nassistant: {r1.get('result') or 'OK'}\n"
                       "</conversation_so_far>\n\n" + prompt2)
        t2 = time.time()
        r2 = runner_turn(ident, {**common, "prompt": prompt2, "agent_doc": instructions(m["B"]),
                                 "resume_session_id": resume, "idempotency_key": f"{ident}:2"}, ctx["internal_runner"])
        row["turn2"] = str(r2.get("status"))
        if r2.get("error"):
            row["error"] = (row["error"] + " | " if row["error"] else "") + f"turn 2: {str(r2.get('error'))[:140]}"
        judge(row, tag, t1, t2, m)
        return row
    finally:
        code, d = call("DELETE", f"{RUNNER}/workspace?identifier={ident}", ctx["internal_runner"], {})
        if code != 200 or os.path.isdir(os.path.join("/data/workspaces", ident)):
            row["error"] += " | NOT REMOVED: session folder"


# ── the run ───────────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated base ids")
    ap.add_argument("--via", default="auto", choices=("auto", "gateway", "runner"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--dry", action="store_true", help="say what would run, and how, and run nothing")
    ap.add_argument("--show", action="store_true", help="print the text around each marker in the judged request")
    args = ap.parse_args()

    key = internal_key()
    if not key:
        print("BLIND: the internal key was not found (run with docker exec --privileged)")
        return 1
    before = snapshot()
    org = "cic-" + uuid.uuid4().hex[:10]
    tenant_dir = os.path.join(SECRETS_ROOT, org)
    internal = {"x-harness-internal": key, "x-harness-org": org, "x-harness-member": "owner"}
    local = {"x-harness-internal": key, "x-harness-org": "local", "x-harness-member": "owner"}
    code, b = call("GET", f"{GATEWAY}/v1/bases", local)
    items = b.get("data") or b.get("bases") or []
    only = {s for s in args.only.split(",") if s}
    items = [x for x in items if (not only or x.get("id") in only) and x.get("status") != "not_installed"]
    code, integ = call("GET", f"{GATEWAY}/v1/admin/integrations", local)
    claimed = {str(k).lower() for k in (integ.get("model_map") or {})} if code == 200 else None
    if claimed is None:
        print(f"the instance's model map could not be read ({code}); every base runs through the runner")
    appserver = True     # the image's default (HARNESS_CODEX_APPSERVER=1); the gateway sends it per turn

    models: dict[str, str] = {}
    plan: list[tuple[dict, str]] = []
    for x in items:
        base, backend = x["id"], x.get("backend") or x["id"]
        if base in NOT_RUN:
            print(f"not run  {base:14} {NOT_RUN[base]}")
            continue
        ms = x.get("models") or []
        default = next((mm.get("id") for mm in ms if isinstance(mm, dict) and mm.get("default")), None) \
            or (ms[0].get("id") if ms and isinstance(ms[0], dict) else "stand-in")
        via = args.via
        if via in ("auto", "gateway"):
            if claimed is not None and str(default).lower() not in claimed:
                models[base] = default
                via = "gateway"
            elif claimed is not None and backend in CLAUDE_NATIVE:
                models[base] = CLAUDE_NATIVE_ID
                via = "gateway"
            elif via == "gateway":
                print(f"not run  {base:14} every model it takes is claimed by an integration here (--via runner runs it)")
                continue
            else:
                via = "runner"
        if via == "runner":
            models[base] = default
        plan.append((x, via))
    turns = 2 * len(plan)
    print(f"bases {len(plan)} | real turns against the stand-in {turns} | "
          f"gateway {sum(v == 'gateway' for _, v in plan)} runner {sum(v == 'runner' for _, v in plan)}", flush=True)
    for x, v in plan:
        print(f"  plan {x['id']:14} via {v:7} model {models[x['id']]}", flush=True)
    if args.dry or not plan:
        return 0

    srv = QuietServer(("127.0.0.1", 0), StandHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    kid = ""
    try:
        code, k = call("POST", f"{GATEWAY}/v1/orgs/{org}/keys", internal,
                       {"name": "continued-instructions-check", "workspace": "default", "member_id": "cic",
                        "workspace_default": True})
        tok, kid = k.get("key") or "", str(k.get("id") or "")
        if not tok and any(v == "gateway" for _, v in plan):
            print(f"BLIND: no API key for the throwaway org ({code})")
            return 1
        ctx = {"org": org, "internal": internal, "api": {"authorization": f"Bearer {tok}"},
               "internal_runner": {"x-harness-internal": key}, "stand": f"http://127.0.0.1:{srv.server_address[1]}",
               "models": models, "appserver": appserver}
        t0 = time.time()
        with cf.ThreadPoolExecutor(max(1, args.jobs)) as ex:
            rows = list(ex.map(lambda p: (run_gateway if p[1] == "gateway" else run_runner)(p[0], ctx), plan))
    finally:
        if kid and call("DELETE", f"{GATEWAY}/v1/orgs/{org}/keys/{kid}", internal)[0] != 200:
            print("NOT REMOVED: the run's API key", flush=True)
        # The throwaway org's connections and policies: only ever this run's own tenant folder.
        if re.fullmatch(r"cic-[0-9a-f]{10}", org) and os.path.dirname(tenant_dir) == SECRETS_ROOT and os.path.isdir(tenant_dir):
            shutil.rmtree(tenant_dir, ignore_errors=True)
        srv.shutdown()
    print(f"turns took {round(time.time() - t0)}s | model requests recorded {len(Stand.seen)}", flush=True)
    bad = 0
    for r in rows:
        bad += r["verdict"] not in ("PASS", "SUPERSEDED")
        print(f"{r['verdict'] or 'ERROR':10} {r['base']:14} via {r['via']:7} turn1 {r.get('turn1', '-'):10} "
              f"turn2 {r.get('turn2', '-'):10} reqs {r.get('reqs1', 0)}/{r.get('reqs2', 0)} "
              f"A1 {'y' if r.get('A1') else 'n'} A2 {'y' if r.get('A2') else 'n'} B2 {'y' if r.get('B2') else 'n'} "
              f"H1in2 {'y' if r.get('H1in2') else 'n'} {r['error'][:200]}", flush=True)
        if r.get("A_at") or r.get("B_at"):
            print(f"           A at {r.get('A_at')} | B at {r.get('B_at')} | {r.get('path2', '')}", flush=True)
        if args.show:
            for k, at, text in r.get("show") or []:
                print(f"           {k} {at}: ...{text}", flush=True)
    after = snapshot()
    if after == before:
        print(f"instance unchanged: orgs {len(after)} ({', '.join(after)}), connections and policies "
              f"{sum(len(v) for v in after.values())}, the same names as before the run", flush=True)
    else:
        bad += 1
        print(f"INSTANCE CHANGED: before {before} | after {after}", flush=True)
    print(f"SUMMARY {len(rows) - (bad - (after != before))} pass of {len(rows)}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
