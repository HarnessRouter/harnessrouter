"""One zeroclaw turn, as a runner subprocess.

Spawned per turn by server.py (the one-process-per-turn contract every backend has: the runner reads
NDJSON off stdout, cancel is a process-group kill). Inside, zeroclaw's own ACP server — `zeroclaw
acp`, JSON-RPC 2.0 over stdio — is started as a child, driven through ONE prompt, and the
`session/update` notifications it streams are re-emitted as CLAUDE'S stream-json, which is why this
backend's normaliser in server.py is the passthrough (the nanobot_driver precedent).

WHY ACP AND NOT `zeroclaw agent -m`, measured on the pinned 0.8.5:

  * `agent -m` prints the final answer as prose: no tool calls, no tool results, nothing a turn
    record can show the work from.
  * `agent -m` forgets. Its `--session-state-file` is read only by the interactive REPL; a one-shot
    run starts from the system prompt and the one message every time, so a follow-up turn would
    answer from an empty history.
  * ACP keeps the conversation in a SQLite store under the config's data dir
    (data/sessions/acp-sessions.db), and `session/resume` in a LATER process seeds the agent with
    that history. Measured across two processes: the second named the file the first had written.

WHAT THIS DRIVER OWES THE TURN, and where each answer comes from:

  * the served model and the token split — the relay's taps. zeroclaw's ACP stream carries no usage
    at all (its TurnEvent::Usage maps to no notification) and names only the model it was ASKED for,
    so the result is emitted without usage and server.py fills both from the relay
    (_fill_relay_usage, _relay_served_model), which is why the key reaches zeroclaw through the
    ENVIRONMENT rather than config.toml.
  * continuity — the ACP session id. zeroclaw mints it (a UUID) on `session/new`; it is reported as
    the init event's session_id, the gateway keeps it as the CLI session id, and the next turn asks
    `session/resume` for it. An id the store does not hold is answered "Session not found" (-32000);
    the turn then starts a new session and server.py's _resume_lost says the history was lost.
  * nobody to ask. A runner turn has no person on the other end, so the config excludes the tools
    that call back to the client (ask_user, escalate_to_human, reaction, poll) and the risk profile
    is `full`. A request zeroclaw sends anyway is answered at once — a permission request with
    `cancelled`, anything else with "method not found" — rather than left to hang the turn.
  * a failure that reads as a failure — a JSON-RPC error on any request, a `cancelled` stop reason,
    or a stream that ends without a response. Each ends the turn as an error with the reason.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading

_OUT = sys.stdout
_AGENT = "hr"           # the one [agents.<alias>] server.py writes
_SESSION_NOT_FOUND = -32000
# What zeroclaw appends to the answer when a turn reaches `max_tool_iterations` (its English locale,
# crates/zeroclaw-runtime/locales/en/cli.ftl `turn-max-iterations-reached`). It then asks the model
# for a summary and stops with `end_turn`, so the stop reason alone reads as a finished turn.
# MEASURED on 0.8.5 with a step budget of 2 and a five-file task: two files, the note, `end_turn`.
_MAX_ITERATIONS = re.compile(r"\*Turn stopped: reached maximum tool iterations \(\d+\)\.\*")


def _emit(ev: dict) -> None:
    _OUT.write(json.dumps(ev, default=str) + "\n")
    _OUT.flush()


def _fail(reason: str) -> None:
    _emit({"type": "result", "subtype": "error", "is_error": True, "result": reason[:1000], "usage": {}})


class _Acp:
    """A JSON-RPC 2.0 client on a child's stdio: requests out, and every line in until the response
    to that request — notifications are handed to `on_update`, requests from the agent are answered."""

    def __init__(self, proc: subprocess.Popen, on_update) -> None:
        self.proc, self.on_update, self.next_id = proc, on_update, 0

    def _send(self, obj: dict) -> None:
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def call(self, method: str, params: dict) -> dict:
        """→ the response object ({"result": …} or {"error": …}); {} when the stream ended first."""
        self.next_id += 1
        rid = self.next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue   # not protocol: zeroclaw logs to its trace file, but never trust that
            if not isinstance(msg, dict):
                continue
            if msg.get("id") == rid and "method" not in msg:
                return msg
            if "method" in msg and "id" in msg:
                self._answer(msg)
            elif msg.get("method") == "session/update":
                self.on_update((msg.get("params") or {}).get("update") or {})
        return {}

    def _answer(self, req: dict) -> None:
        if req.get("method") == "session/request_permission":
            self._send({"jsonrpc": "2.0", "id": req["id"], "result": {"outcome": {"outcome": "cancelled"}}})
        else:
            self._send({"jsonrpc": "2.0", "id": req["id"],
                        "error": {"code": -32601, "message": f"not supported by this client: {req.get('method')}"}})


class _Turn:
    """session/update → claude stream-json."""

    def __init__(self) -> None:
        self.text = ""

    def update(self, u: dict) -> None:
        kind = u.get("sessionUpdate")
        if kind == "agent_message_chunk":
            t = _chunk_text(u)
            if t:
                self.text += t
                _emit({"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}})
        elif kind == "agent_thought_chunk":
            t = _chunk_text(u)
            if t:
                _emit({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": t}]}})
        elif kind == "tool_call":
            raw = u.get("rawInput")
            _emit({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": str(u.get("toolCallId") or "tool"),
                 "name": str(u.get("name") or u.get("title") or "tool"),
                 "input": raw if isinstance(raw, dict) else {}}]}})
        elif kind == "tool_call_update" and u.get("status") in ("completed", "failed"):
            # Only the terminal update is a result; an in-progress update carries partial output the
            # final one repeats.
            body = u.get("rawOutput")
            if not isinstance(body, str):
                body = u.get("body") if isinstance(u.get("body"), str) else json.dumps(body, default=str)
            _emit({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": str(u.get("toolCallId") or "tool"),
                 "is_error": u.get("status") == "failed", "content": (body or "")[:8000]}]}})
        # plan, history_trimmed and the rest are progress for an IDE, not part of the transcript


def _chunk_text(u: dict) -> str:
    c = u.get("content")
    if isinstance(c, dict):
        return str(c.get("text") or "")
    if isinstance(c, list):
        return "".join(str(x.get("text") or "") for x in c if isinstance(x, dict))
    return ""


def _err(resp: dict) -> str:
    e = resp.get("error") or {}
    return str(e.get("message") or e or "zeroclaw returned an error")


def _run(job: dict) -> int:
    cwd = job["cwd"]
    proc = subprocess.Popen([job["zeroclaw"], "acp", "--config-dir", job["config_dir"]],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                            text=True, cwd=cwd, bufsize=1)
    turn = _Turn()
    acp = _Acp(proc, turn.update)
    try:
        r = acp.call("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        if "result" not in r:
            _fail(_err(r) if r else "")
            return 1
        sid = ""
        resume = str(job.get("resume_session_id") or "")
        if resume:
            r = acp.call("session/resume", {"sessionId": resume})
            if "result" in r:
                sid = resume
            elif (r.get("error") or {}).get("code") != _SESSION_NOT_FOUND:
                _fail(_err(r) if r else "")
                return 1
            # not found: a new session below, and server.py's _resume_lost says so on the turn
        if not sid:
            r = acp.call("session/new", {"cwd": cwd, "agentAlias": _AGENT})
            if "result" not in r:
                _fail(_err(r) if r else "")
                return 1
            sid = str(r["result"].get("sessionId") or "")
        _emit({"type": "system", "subtype": "init", "session_id": sid, "model": str(job.get("model") or "")})
        r = acp.call("session/prompt", {"sessionId": sid,
                                        "prompt": [{"type": "text", "text": str(job.get("prompt") or "")}]})
        if not r:
            # The stream ended without an answer. Empty text, so the runner's stderr tail is the
            # reason rather than a sentence invented here (nanobot_driver's rule).
            _fail("")
            return 1
        if "error" in r:
            _fail(_err(r))
            return 1
        res = r.get("result") or {}
        stop = str(res.get("stopReason") or "")
        # `content` is the turn's final answer (the text after its last tool call), so it is
        # authoritative over what the chunks assembled.
        answer = str(res.get("content") or turn.text)
        if stop not in ("", "end_turn"):
            _emit({"type": "result", "subtype": "error", "is_error": True, "result": answer or stop,
                   "reason": stop, "usage": {}})
            return 1
        if _MAX_ITERATIONS.search(answer):
            # the step budget, as every base reports it: the turn stopped, it did not fail
            _emit({"type": "result", "subtype": "error_max_turns", "is_error": False, "result": answer, "usage": {}})
            return 0
        _emit({"type": "result", "subtype": "success", "is_error": False, "result": answer, "usage": {}})
        return 0
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        _reap(proc)


def _reap(proc: subprocess.Popen) -> None:
    """zeroclaw exits when its stdin closes; one that does not is killed rather than outliving the turn."""
    t = threading.Timer(20, proc.kill)
    t.start()
    try:
        proc.wait()
    finally:
        t.cancel()


def main() -> int:
    try:
        job = json.loads(sys.argv[1])
    except Exception as e:  # noqa: BLE001
        print(f"zeroclaw driver: bad job: {e}", file=sys.stderr)
        return 2
    try:
        return _run(job)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        # The exception text is the only reason anybody will have, so it goes to stderr (which the
        # runner collects into the turn's failure reason) AND the turn is failed explicitly.
        print(f"zeroclaw driver: {type(e).__name__}: {e}", file=sys.stderr)
        _fail(f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
