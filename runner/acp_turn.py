"""One agent turn over the Agent Client Protocol, STREAMED: the client the ACP drivers share, and the
translation of each `session/update` into claude's stream-json the moment it arrives.

WHY STREAMED. A turn's record used to be built after `session/prompt` returned: every update was
held, translated in one pass and written out at the end. The protocol was carrying each text chunk,
each tool call and each result live, and the person saw "Thinking" for the whole turn and then all
of it at once (Richard, 2026-10-26, on deepagents-code and fast-agent). Now each update is written
as it arrives: a text chunk as a small assistant text event (the gateway renders it as an
incremental output_text delta, the shape claude's partial mode takes), a thought as thinking, a
tool call as soon as its input is known, and its result when the call completes.

A loaded session replays its history as updates before the prompt is sent, so nothing is written
until `session/prompt` goes out (`Acp.recording`): a turn's record never opens with an earlier
turn's reply.

THE TERMINAL. A client that advertises `terminal` runs the agent's shell commands itself, through
`terminal/create`, `terminal/wait_for_exit`, `terminal/output`, `terminal/release` and
`terminal/kill`. fast-agent reports a command's progress and result over ACP only on that path:
measured on 0.10.47, its own local shell sends a `tool_call` with no arguments and no completion at
all, while the terminal path sends the command, then its output and exit code. The command runs
here, in the session directory, with the agent's own environment plus what the request names, as
the agent's local shell would have run it.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from typing import Callable

_RPC_TIMEOUT = float(os.environ.get("HR_ACP_RPC_TIMEOUT", os.environ.get("HR_DCODE_RPC_TIMEOUT", "120")))
# How long the agent has to exit once its input ends, before it is killed (see Acp.close).
_END_GRACE = float(os.environ.get("HR_ACP_END_GRACE", os.environ.get("HR_DCODE_END_GRACE", "10")))
_PROMPT_TIMEOUT = float(os.environ.get("HR_ACP_PROMPT_TIMEOUT", os.environ.get("HR_DCODE_PROMPT_TIMEOUT", "7200")))
_EMIT_LOCK = threading.Lock()


def emit(obj: dict) -> None:
    with _EMIT_LOCK:
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        sys.stdout.flush()


class _Terminal:
    """One command the agent asked this client to run."""

    def __init__(self, argv: list[str], cwd: str, env: dict, limit: int) -> None:
        self.limit = max(1024, int(limit or 16000))
        self.chunks: list[bytes] = []
        self.size = 0
        self.truncated = False
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        self.done = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for chunk in iter(lambda: self.proc.stdout.read(4096), b""):   # type: ignore[union-attr]
            self.chunks.append(chunk)
            self.size += len(chunk)
            # The protocol's limit keeps the END of the output: that is where a failing command says why.
            while self.size > self.limit and len(self.chunks) > 1:
                self.size -= len(self.chunks.pop(0))
                self.truncated = True
        self.proc.wait()
        self.done.set()

    def output(self) -> str:
        data = b"".join(self.chunks)
        if len(data) > self.limit:
            data, self.truncated = data[-self.limit:], True
        return data.decode("utf-8", "replace")

    def status(self) -> dict | None:
        rc = self.proc.poll()
        if rc is None:
            return None
        return {"exitCode": rc if rc >= 0 else None, "signal": signal.Signals(-rc).name if rc < 0 else None}

    def kill(self) -> None:
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except OSError:
                pass


class Acp:
    """A newline-delimited JSON-RPC client for one ACP agent process.

    `on_update` receives each `session/update` while `recording` is set. With `terminal=True` the
    client runs the agent's shell commands (see the module docstring); without it every request the
    agent makes but the permission one is refused by name."""

    def __init__(self, argv: list[str], cwd: str, env: dict,
                 on_update: Callable[[dict], None] | None = None, terminal: bool = False) -> None:
        self.cwd = cwd
        self.env = env
        self.terminal = terminal
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, text=True, bufsize=1,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True)
        self._id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, list] = {}
        self._terms: dict[str, _Terminal] = {}
        self.on_update = on_update
        self.recording = False
        self.errtail: list[str] = []
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    # ── wire ──────────────────────────────────────────────────────────────────────────────────
    def _send(self, obj: dict) -> None:
        with self._lock:
            try:
                self.proc.stdin.write(json.dumps(obj) + "\n")   # type: ignore[union-attr]
                self.proc.stdin.flush()                          # type: ignore[union-attr]
            except (BrokenPipeError, ValueError):
                pass

    def call(self, method: str, params: dict, timeout: float = _RPC_TIMEOUT) -> dict:
        with self._lock:
            self._id += 1
            rid = self._id
            slot = [threading.Event(), None]
            self._pending[rid] = slot
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not slot[0].wait(timeout):
            raise TimeoutError(method)
        with self._lock:
            self._pending.pop(rid, None)
        return slot[1] or {}

    def _read_out(self) -> None:
        for raw in self.proc.stdout:        # type: ignore[union-attr]
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                with self._lock:
                    slot = self._pending.get(msg["id"])
                if slot:
                    slot[1] = msg
                    slot[0].set()
                continue
            if "id" in msg and "method" in msg:
                # Answered off this thread: a command's wait must not stop the updates behind it.
                threading.Thread(target=self._answer, args=(msg,), daemon=True).start()
                continue
            if msg.get("method") == "session/update" and self.recording and self.on_update:
                self.on_update((msg.get("params") or {}).get("update") or {})
        # the agent's stdout closed: wake anything still waiting rather than letting it time out
        with self._lock:
            for slot in self._pending.values():
                slot[1] = {"error": {"code": -32000, "message": "the agent closed its stream"}}
                slot[0].set()

    def close(self) -> None:
        """End the agent and WAIT until it has exited. dcode 0.2 keeps a lock on its thread for as
        long as its process lives (deepagents_code/thread_ownership.py), and the next turn of the
        conversation is another process loading that thread. MEASURED 2026-10-25, four matrix
        columns at once: a driver that sent SIGTERM and returned at once left an idle agent 1.3 to
        1.7 s to go, two caught the signal and were still running minutes later, orphaned, and the
        turn after them was refused its own thread ("Thread … is open elsewhere"). End of input is
        how an ACP client ends the agent; one that has not gone in _END_GRACE is killed with its
        group. The runner holds the turn's result until this process exits, so the next turn starts
        only once the agent is gone. A command still running in the client's terminal goes too."""
        for t in list(self._terms.values()):
            t.kill()
        p = self.proc
        if p.poll() is None:
            try:
                p.stdin.close()     # type: ignore[union-attr]  (a write racing it is dropped: _send)
            except (OSError, ValueError):
                pass
            try:
                p.wait(timeout=_END_GRACE)
                return
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        p.wait()

    def _read_err(self) -> None:
        for raw in self.proc.stderr:        # type: ignore[union-attr]
            self.errtail.append(raw.rstrip()[:400])
            del self.errtail[:-40]

    def _reply(self, msg: dict, result: dict | None = None, error: str = "") -> None:
        if error:
            self._send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32602, "message": error}})
        else:
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result or {}})

    def _answer(self, msg: dict) -> None:
        """The agent's own requests. It must never be left waiting."""
        method = str(msg.get("method") or "")
        params = msg.get("params") or {}
        if method == "session/request_permission":
            # The sandbox is the trust boundary and nobody is attached to answer, so this allows:
            # the grant claude gets with --dangerously-skip-permissions.
            opts = params.get("options") or []
            pick = next((o for o in opts
                         if "allow" in str(o.get("kind", "")).lower()
                         or "allow" in str(o.get("optionId", "")).lower()), None)
            pick = pick or (opts[0] if opts else None)
            self._reply(msg, {"outcome": {"outcome": "selected", "optionId": pick["optionId"]}}
                        if pick else {"outcome": {"outcome": "cancelled"}})
            return
        if self.terminal and method.startswith("terminal/"):
            self._terminal(msg, method, params)
            return
        # Anything else is refused by name rather than ignored: silence would hang the agent.
        self._send({"jsonrpc": "2.0", "id": msg["id"],
                    "error": {"code": -32601, "message": f"this client does not implement {method}"}})

    def _terminal(self, msg: dict, method: str, params: dict) -> None:
        if method == "terminal/create":
            cmd = str(params.get("command") or "")
            if not cmd:
                self._reply(msg, error="terminal/create needs a command")
                return
            env = dict(self.env)
            for e in params.get("env") or []:
                if isinstance(e, dict) and e.get("name"):
                    env[str(e["name"])] = str(e.get("value") or "")
            try:
                t = _Terminal([cmd, *[str(a) for a in (params.get("args") or [])]],
                              str(params.get("cwd") or self.cwd), env, int(params.get("outputByteLimit") or 16000))
            except OSError as e:
                self._reply(msg, error=f"the command could not start: {e}")
                return
            tid = f"term-{len(self._terms) + 1}"
            self._terms[tid] = t
            self._reply(msg, {"terminalId": tid})
            return
        t = self._terms.get(str(params.get("terminalId") or ""))
        if t is None:
            self._reply(msg, error="no such terminal")
            return
        if method == "terminal/wait_for_exit":
            t.done.wait()
            self._reply(msg, t.status() or {})
        elif method == "terminal/output":
            self._reply(msg, {"output": t.output(), "truncated": t.truncated, "exitStatus": t.status()})
        elif method == "terminal/kill":
            t.kill()
            self._reply(msg, {})
        elif method == "terminal/release":
            t.kill()
            self._terms.pop(str(params.get("terminalId") or ""), None)
            self._reply(msg, {})
        else:
            self._send({"jsonrpc": "2.0", "id": msg["id"],
                        "error": {"code": -32601, "message": f"this client does not implement {method}"}})


def _text_of(u: dict) -> str:
    c = u.get("content")
    return str(c.get("text") or "") if isinstance(c, dict) else ""


def _content_text(content) -> str:
    """The text of an ACP tool call's content blocks ({"type": "content", "content": {"type":
    "text", "text": ...}}), "" when there is none."""
    parts = []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        inner = item.get("content") if isinstance(item.get("content"), dict) else {}
        parts.append(str(inner.get("text") or item.get("text") or ""))
    return "\n".join(p for p in parts if p)


class Stream:
    """`session/update` → claude stream-json, written as each update arrives.

    `tool_name(title, kind)` gives a call its tool's own id: ACP carries a title for a human and a
    kind from a fixed vocabulary, and each agent fills them its own way."""

    def __init__(self, tool_name: Callable[[str, str], str], out: Callable[[dict], None] = emit) -> None:
        self.tool_name = tool_name
        self.out = out
        self.runs: list[list[str]] = [[]]     # the answer's text, one list per run between tool calls
        self.calls: dict[str, dict] = {}       # toolCallId → {"name", "shown", "closed"}

    def answer(self) -> str:
        return "\n".join("".join(r).strip() for r in self.runs if "".join(r).strip()).strip()

    def _call(self, cid: str, name: str, args) -> None:
        self.out({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": cid, "name": name,
             "input": args if isinstance(args, dict) else {"input": args} if args is not None else {}}]}})

    def update(self, u: dict) -> None:
        kind = str(u.get("sessionUpdate") or "")
        if kind == "agent_message_chunk":
            t = _text_of(u)
            if t:
                self.runs[-1].append(t)
                self.out({"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}})
        elif kind == "agent_thought_chunk":
            t = _text_of(u)
            if t:
                # Thinking, shown as thinking: never the answer.
                self.out({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": t}]}})
        elif kind == "tool_call":
            cid = str(u.get("toolCallId") or "tool")
            if self.runs[-1]:
                self.runs.append([])
            c = self.calls.setdefault(cid, {"name": self.tool_name(str(u.get("title") or ""), str(u.get("kind") or "")),
                                            "shown": False, "closed": False})
            args = u.get("rawInput")
            if isinstance(args, dict) and args:
                # The call is written once its input is known: some agents send the arguments with
                # the call (deepagents-code), others only on its first progress update (fast-agent).
                self._call(cid, c["name"], args)
                c["shown"] = True
            if str(u.get("status") or "") in ("completed", "failed"):
                self._close(cid, u)
        elif kind == "tool_call_update":
            cid = str(u.get("toolCallId") or "tool")
            c = self.calls.get(cid)
            if c is None:
                c = self.calls[cid] = {"name": self.tool_name(str(u.get("title") or ""), str(u.get("kind") or "")),
                                       "shown": False, "closed": False}
            args = u.get("rawInput")
            if not c["shown"] and isinstance(args, dict) and args:
                self._call(cid, c["name"], args)
                c["shown"] = True
            if str(u.get("status") or "") in ("completed", "failed"):
                self._close(cid, u)
        # plan, user_message_chunk, session_info_update, available_commands_update and the rest are
        # an IDE's progress, not the turn's record.

    def _close(self, cid: str, u: dict) -> None:
        c = self.calls[cid]
        if c["closed"]:
            return
        if not c["shown"]:
            self._call(cid, c["name"], u.get("rawInput"))
            c["shown"] = True
        c["closed"] = True
        status = str(u.get("status") or "")
        body = _content_text(u.get("content"))
        if not body and isinstance(u.get("rawOutput"), str):
            body = u["rawOutput"]
        self.out({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": cid, "is_error": status == "failed",
             "content": body[:8000]}]}})

    def finish(self) -> None:
        """A call that was never completed is closed by saying exactly that: a tool_use with no
        tool_result is a hole in the record, and claiming an outcome nobody reported is worse.
        (deepagents-code sends an edit_file with a full diff through a branch that emits the call
        and nothing after it: measured on a six-tool turn, the edit landed and the status stayed
        `pending`.)"""
        for cid, c in self.calls.items():
            if c["closed"]:
                continue
            if not c["shown"]:
                self._call(cid, c["name"], None)
            c["closed"] = True
            self.out({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": cid, "is_error": False,
                 "content": f"(the agent reported no completion for this {c['name']} call)"}]}})


def translate(updates: list[dict], tool_name: Callable[[str, str], str]) -> tuple[list[dict], str]:
    """The events a list of updates streams, and the turn's answer: Stream, collected."""
    evs: list[dict] = []
    s = Stream(tool_name, out=evs.append)
    for u in updates:
        s.update(u)
    s.finish()
    return evs, s.answer()


def error_text(err: dict) -> str:
    """The readable reason inside a JSON-RPC error, which is not its `message`.

    A provider refusal can arrive as -32603 "Internal error" with the real thing in `data.details`,
    and that string may be the agent's own traceback with its frames joined by " / " (deepagents-code,
    MEASURED on a 401 through the relay). The first segment is the reason; the rest is the agent's
    internals, and a turn's record is not where they belong."""
    if not isinstance(err, dict):
        return "the agent reported an error"
    data = err.get("data") if isinstance(err.get("data"), dict) else {}
    text = str(data.get("details") or err.get("message") or "").strip()
    if not text:
        return "the agent reported an error"
    return text.split(" / ")[0].strip().splitlines()[0][:600]

