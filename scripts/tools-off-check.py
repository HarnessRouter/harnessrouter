#!/usr/bin/env python3
"""Does switching a built-in tool off reach the model request? Runs INSIDE the container, as the
gateway's own user, with no provider key of its own:

    docker cp scripts/tools-off-check.py hr:/tmp/tools-off-check.py
    docker exec -u agent -i hr python3 -I /tmp/tools-off-check.py --only qwen,cline,claude-code

For each base it starts one real turn with every built-in tool the catalog offers switched off (or the
ones named with --disable) against a stand-in model server it starts itself, and reads what the CLI
sent there. Two questions per base:

    withheld     none of the switched-off tools is in the request's tool list (a hard block)
    instruction  the request carries the "Disabled tools" block (a request to the model)

A base whose request still offers a switched-off tool and carries no block ignores the switch.

With --baseline each base also runs once with nothing switched off, which tells a tool the switch
withheld from a name the CLI never offered at all (a catalog name that is not one of its tools).

The turn is started on the runner directly (POST /turn), with the list the gateway would pass it: the
gateway hands a harness's disabled_tools to the runner as they are stored (tools_disabled), so this
is the same turn a harness starts, minus the gateway's routing. That is the point: on an instance
with integrations, the gateway runs a catalog model on the integration that serves it before any
connection of its own, so a turn started there would reach a real provider instead of the stand-in.
The model requests still go through the runner's own relay, so what is recorded is what a provider
would have received.

The stand-in answers every call with a plain "OK" and no tool call, so a turn is one model call
plus whatever helper calls the CLI makes on its own.

Footprint: nothing is written to the gateway. Each turn's workspace is removed through the runner
(DELETE /workspace) when the turn is over. The internal key is read from the gateway's environment
and held in memory; nothing is printed but names and verdicts.

The gateway's user, not root: root in a default container has no CAP_SYS_PTRACE, so it cannot read
another user's process environment, and that is where the internal key is.

Stdlib only, since this runs on the image's own python.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import http.server
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

GATEWAY = "http://127.0.0.1:8080"
RUNNER = "http://127.0.0.1:8081"
TURN_S = 240
BLOCK = "## Disabled tools"
# The provider a base's connection needs, where it isn't an OpenAI-compatible endpoint (the release
# gate's own table, scripts/secret-canary-gate.py).
PROVIDER = {"claude": "anthropic", "gemini": "google", "codex": "openai", "systemone": "openrouter",
            "dsh": "tokenrouter", "kimi": "tokenrouter", "minimax": "tokenrouter", "grok": "tokenrouter",
            "qwen": "tokenrouter"}
NOT_RUN = {"qoder": "its runtime is the vendor's cloud"}


# ── the stand-in model ────────────────────────────────────────────────────────────────────────

class Seen:
    lock = threading.Lock()
    calls: dict[str, list[dict]] = {}      # backend -> one record per model request


def tool_names(body: dict) -> list[str]:
    """The tool names one request offers the model, whatever the wire: OpenAI chat
    (function.name), Responses and Anthropic (name, or the type of a built-in), Gemini
    (functionDeclarations[].name, or the key of a built-in such as googleSearch)."""
    out: list[str] = []
    tools = body.get("tools")
    if not isinstance(tools, list):
        return out
    for t in tools:
        if not isinstance(t, dict):
            continue
        if isinstance(t.get("functionDeclarations"), list):
            out += [str(f.get("name")) for f in t["functionDeclarations"] if isinstance(f, dict)]
        elif isinstance(t.get("function"), dict):
            out.append(str(t["function"].get("name")))
        elif t.get("name"):
            out.append(str(t["name"]))
        elif t.get("type"):
            out.append(str(t["type"]))
        else:
            out += [str(k) for k in t]
    return out


def _sse(events: list[str]) -> bytes:
    return "".join(events).encode()


def model_body(path: str, body: dict) -> tuple[str, bytes]:
    """A plain "OK" in the shape the caller asked for: the release gate's stand-in answer."""
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
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        path = self.path.split("?")[0]
        backend = path.strip("/").split("/")[0]
        if path.endswith("/models"):
            self._send(200, "application/json", json.dumps({"object": "list", "data": [{"id": "stand-in", "object": "model"}]}).encode())
            return
        if self.command != "POST":
            self._send(404, "application/json", b"{}")
            return
        body = body if isinstance(body, dict) else {}
        with Seen.lock:
            Seen.calls.setdefault(backend, []).append({
                "path": "/" + "/".join(path.strip("/").split("/")[1:]),
                "tools": tool_names(body),
                "block": BLOCK.encode() in raw})
        ctype, data = model_body(path, body)
        self._send(200, ctype, data)

    do_GET = do_POST = do_HEAD = _handle  # noqa: N815


# ── the run ───────────────────────────────────────────────────────────────────────────────────

def gateway_env() -> dict[str, str]:
    """The two values this needs from the gateway's environment, held in memory."""
    found: dict[str, str] = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            with open(f"{d}/environ", "rb") as fh:
                env = fh.read().split(b"\0")
        except OSError:
            continue
        for kv in env:
            k, _, v = kv.partition(b"=")
            if k in (b"HARNESS_INTERNAL_KEY", b"POOL_MGMT_ENDPOINT") and v:
                found.setdefault(k.decode(), v.decode())
    return found


def call(method: str, path: str, headers: dict, body: dict | None = None, timeout: int = 60,
         origin: str = GATEWAY) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(origin + path, data=data, method=method,
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


def run_base(x: dict, stand: str, key: str, runner: str, made: list, disable: list[str],
             baseline: bool = False) -> dict:
    base, backend = x["id"], x.get("backend") or x["id"]
    off = [] if baseline else (disable or [str(t.get("name")) for t in (x.get("tools") or [])
                                           if isinstance(t, dict) and t.get("name")])
    # the stand-in tells the turns apart by the first segment of the path they call
    tag = backend + ("~baseline" if baseline else "")
    row = {"base": base, "backend": backend, "tag": tag, "off": off, "status": "", "error": "",
           "enforcement": sorted({str(t.get("enforcement")) for t in (x.get("tools") or []) if isinstance(t, dict)})}
    model = x.get("defaultModel") or next((m.get("id") for m in x.get("models") or [] if isinstance(m, dict)), "stand-in")
    base_url = f"{stand}/{tag}/v1"
    if backend == "gemini":
        # The runner sends gemini to Google's native API unless the base is a provider that serves
        # it under its own root, which it reads off the address (_gemini_channel); the stand-in is
        # named so, or the request would go to Google itself.
        base_url = f"{stand}/{tag}/api.tokenrouter.com/v1"
    ident = f"tools-off-check-{backend}-{uuid.uuid4().hex[:10]}"
    hdr = {"x-harness-internal": key}
    body = {"backend": backend, "provider": PROVIDER.get(backend, "openai-api"), "model": model,
            "prompt": "Reply OK.", "timeout_seconds": TURN_S - 30, "max_turns": 5,
            "auth": {"api_key": f"tools-off-check-{uuid.uuid4().hex}", "base_url": base_url},
            "tools_disabled": off, "agent_doc": "", "idempotency_key": uuid.uuid4().hex,
            # the gateway's default for codex on this image (HARNESS_CODEX_APPSERVER=1)
            "codex_appserver": backend == "codex"}
    made.append(ident)
    code, t = call("POST", f"/turn?identifier={ident}", hdr, body, origin=runner)
    if code != 200 or not t.get("turn_id"):
        row["error"] = f"turn {code}: {str(t.get('detail') or t.get('error'))[:120]}"
        return row
    tid, since, end = t["turn_id"], 0, time.time() + TURN_S
    while time.time() < end:
        code, r = call("GET", f"/turn/{tid}?identifier={ident}&since={since}&wait=10", hdr, timeout=30, origin=runner)
        if code != 200:
            row["error"] = f"poll {code}"
            break
        since = int(r.get("n_total") or since)
        if r.get("done"):
            row["status"] = str(r.get("status") or "")
            if r.get("error"):
                row["error"] = str(r.get("error"))[:160]
            break
    else:
        row["status"] = "timed out"
        call("POST", f"/turn/{tid}/cancel?identifier={ident}", hdr, {}, origin=runner)
    return row


def offered_by(tag: str) -> list[str]:
    offered: list[str] = []
    for c in Seen.calls.get(tag) or []:
        offered += [t for t in c["tools"] if t not in offered]
    return offered


def verdict(row: dict) -> tuple[str, list[str], list[str], bool]:
    calls = Seen.calls.get(row["tag"]) or []
    offered = offered_by(row["tag"])
    off = row["off"]
    still = [t for t in off if t in offered]
    block = any(c["block"] for c in calls)
    if not calls:
        return "NO REQUEST", offered, still, block
    if not still:
        return "hard" + (" (+instruction)" if block else ""), offered, still, block
    return ("instruction" if block else "NOTHING"), offered, still, block


def cleanup(key: str, runner: str, made: list) -> list[str]:
    left: list[str] = []
    for ident in made:
        code, r = call("DELETE", f"/workspace?identifier={ident}", {"x-harness-internal": key}, origin=runner)
        if code != 200:
            left.append(f"workspace {ident} ({code})")
    return left


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated base ids")
    ap.add_argument("--disable", default="", help="comma-separated tool names to switch off (default: every tool the base offers)")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--baseline", action="store_true", help="also run each base once with nothing switched off")
    args = ap.parse_args()

    for _ in range(90):
        if call("GET", "/healthz", {}, timeout=5)[0] == 200:
            break
        time.sleep(2)
    env = gateway_env()
    if "HARNESS_INTERNAL_KEY" not in env:
        print("the instance's internal key was not found: run this as the gateway's user (docker exec -u agent)")
        return 1
    key = env["HARNESS_INTERNAL_KEY"]
    runner = (env.get("POOL_MGMT_ENDPOINT") or RUNNER).rstrip("/")
    made: list[str] = []
    base_rows: dict[str, dict] = {}
    # The catalog, read only: which tools each base offers and how far the console says switching
    # one off goes. An organization of its own, so no one's connections colour the read.
    code, b = call("GET", "/v1/bases", {"x-harness-internal": key, "x-harness-org": "tools-off-check",
                                        "x-harness-member": "reader"})
    items = b.get("data") or b.get("bases") or []
    only = [x for x in args.only.split(",") if x]
    items = [x for x in items if (not only or x.get("id") in only) and x.get("id") not in NOT_RUN
             and x.get("status") != "not_installed"]
    print(f"bases {[x.get('id') for x in items]}", flush=True)
    srv = QuietServer(("127.0.0.1", 0), StandHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    stand = f"http://127.0.0.1:{srv.server_address[1]}"
    rows: list[dict] = []
    try:
        disable = [t for t in args.disable.split(",") if t]
        t0 = time.time()
        work = [(x, False) for x in items] + ([(x, True) for x in items] if args.baseline else [])
        print(f"turns: {len(work)}", flush=True)
        with cf.ThreadPoolExecutor(max(1, args.jobs)) as ex:
            done = list(ex.map(lambda w: run_base(w[0], stand, key, runner, made, disable, baseline=w[1]), work))
        rows = [r for r in done if not r["tag"].endswith("~baseline")]
        base_rows = {r["backend"]: r for r in done if r["tag"].endswith("~baseline")}
        print(f"turns took {round(time.time() - t0)}s", flush=True)
    finally:
        left = cleanup(key, runner, made)
        srv.shutdown()
    for r in rows:
        v, offered, still, block = verdict(r)
        calls = Seen.calls.get(r["tag"]) or []
        print(f"{v:22} {r['base']:12} catalog says {'/'.join(r['enforcement']) or '-'} | turn {r['status'] or '-'} "
              f"| requests {len(calls)} | block {'yes' if block else 'no'} {r['error'][:80]}", flush=True)
        print(f"    switched off ({len(r['off'])}): {', '.join(r['off'])}", flush=True)
        print(f"    still offered ({len(still)}): {', '.join(still) or '-'}", flush=True)
        b = base_rows.get(r["backend"])
        if b:
            full = offered_by(b["tag"])
            withheld = [t for t in r["off"] if t in full and t not in offered]
            never = [t for t in r["off"] if t not in full]
            print(f"    withheld ({len(withheld)}): {', '.join(withheld) or '-'}", flush=True)
            print(f"    never offered, even with nothing off ({len(never)}): {', '.join(never) or '-'}", flush=True)
            print(f"    request tools, nothing off ({len(full)}): {', '.join(full) or '-'} "
                  f"[turn {b['status'] or '-'} {b['error'][:60]}]", flush=True)
        print(f"    request tools ({len(offered)}): {', '.join(offered) or '-'}", flush=True)
    print("cleanup: " + ("nothing left" if not left else "; ".join(left)), flush=True)
    return 0 if all(verdict(r)[0] not in ("NOTHING", "NO REQUEST") for r in rows) and not left else 1


if __name__ == "__main__":
    sys.exit(main())
