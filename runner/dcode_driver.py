"""One deepagents-code turn, over ACP, as a runner subprocess.

WHY ACP AND NOT ITS HEADLESS FLAG. `dcode -n "<task>"` cannot continue a conversation: its own
source says so ("`run_non_interactive` takes no resume or thread-id argument, so it always starts a
fresh thread"), and five turns passing `-r <thread_id>` for a thread with 22 checkpoints in the
store produced five NEW threads and five "this thread has no earlier message" answers. A base on
that path passes a first turn and fails follow-up, switch and recycle.

`dcode --acp` is the same agent behind the Agent Client Protocol, and its server is constructed
with `load_sessions=True`, so `session/load` restores a conversation **in a different process** —
which is what one-process-per-turn needs. MEASURED on 0.1.84 (2026-10-19), two processes against a
live provider: process two loaded process one's session id, the server replayed the conversation as
updates, the model answered the recall correctly, and a file the turn was asked for was written.

What this driver does, and why each part is here (every claim measured on that build):

  * `initialize` → the server answers `agentCapabilities.loadSession: true`. The client advertises
    NO filesystem capability, so the agent uses its own tools rather than asking us to read and
    write files.
  * `session/new` makes the id; we do not choose it. `session/load` takes it back, and REQUIRES the
    same cwd the session was created with (it answers invalid_params otherwise) — which is the
    session directory here, so that holds across a sandbox recycle.
  * A LOADED session replays its whole history as `session/update` notifications before the prompt
    is sent. Nothing is recorded until `session/prompt` goes out, or a turn's record would open
    with every earlier turn's reply (the shape fast-agent's trajectory has, in another protocol).
  * The model is NOT the `-M` flag once a session exists: the session carries its own, and
    `session/set_config_option(configId="model")` is the door. The flag still matters because the
    server's valid-model list is built from the model THIS process resolved, so `-M` is what puts
    our id in it.
  * The agent asks the client for permission (`session/request_permission`). The sandbox is the
    trust boundary and nobody is attached to answer, so this allows — the grant claude gets with
    --dangerously-skip-permissions.
  * Tool calls arrive as `tool_call` (toolCallId, title, rawInput) and `tool_call_update` (status,
    content), which is a better trace than the `-q` text path could ever carry.

Protocol out: claude's stream-json on stdout, one object per line, which is why this backend's
normaliser in server.py is the passthrough.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

# A client that never answers would hang the agent; a client that waits forever would hang the
# turn. Both are bounded, under the runner's own wall-clock cap.
_RPC_TIMEOUT = float(os.environ.get("HR_DCODE_RPC_TIMEOUT", "120"))
_PROMPT_TIMEOUT = float(os.environ.get("HR_DCODE_PROMPT_TIMEOUT", "7200"))


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class Acp:
    """A newline-delimited JSON-RPC client for one `dcode --acp` process."""

    def __init__(self, argv: list[str], cwd: str, env: dict) -> None:
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, text=True, bufsize=1,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True)
        self._id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, list] = {}
        self.updates: list[dict] = []
        self.recording = False      # see the module docstring: a load replays the conversation
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
                self._answer(msg)
                continue
            if msg.get("method") == "session/update" and self.recording:
                self.updates.append((msg.get("params") or {}).get("update") or {})
        # the agent's stdout closed: wake anything still waiting rather than letting it time out
        with self._lock:
            for slot in self._pending.values():
                slot[1] = {"error": {"code": -32000, "message": "the agent closed its stream"}}
                slot[0].set()

    def _read_err(self) -> None:
        for raw in self.proc.stderr:        # type: ignore[union-attr]
            self.errtail.append(raw.rstrip()[:400])
            del self.errtail[:-40]

    def _answer(self, msg: dict) -> None:
        """The agent's own requests. It asks for permission; it must not be left waiting."""
        method = str(msg.get("method") or "")
        if method == "session/request_permission":
            opts = ((msg.get("params") or {}).get("options") or [])
            pick = next((o for o in opts
                         if "allow" in str(o.get("kind", "")).lower()
                         or "allow" in str(o.get("optionId", "")).lower()), None)
            pick = pick or (opts[0] if opts else None)
            result = ({"outcome": {"outcome": "selected", "optionId": pick["optionId"]}}
                      if pick else {"outcome": {"outcome": "cancelled"}})
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            return
        # Anything else — a filesystem or terminal request — is refused by name rather than
        # ignored: this client advertises neither capability, and silence would hang the agent.
        self._send({"jsonrpc": "2.0", "id": msg["id"],
                    "error": {"code": -32601, "message": f"this client does not implement {method}"}})


# The tools whose own name the server sends as the call's title. Everything else it renames for a
# reader, and _tool_name puts the name back.
_DCODE_TOOLS = ("ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute",
                "task", "compact_conversation", "update_goal", "ask_user", "fetch_url",
                "get_current_thread_id", "write_todos")


def _tool_name(title: str, kind: str) -> str:
    """The tool's own id, recovered from what ACP carries.

    ACP's `tool_call` has no field for the tool's name: it has a `title` for a human and a `kind`
    from a fixed vocabulary. deepagents' server (_create_tool_call_start) rewrites the title for
    exactly four tools and passes `title = tool_name` for every other one, so the id comes back
    whole — a record that said 'Write /ws/out.txt' where every other base says write_file
    would be a tool nothing could count (the matrix's custom-harness dimension reads these names,
    and an unrecognised one is a CUSTOM tool to it, not a write)."""
    if title in _DCODE_TOOLS:
        return title
    if kind == "read":
        return "read_file"
    if kind == "edit":
        return "edit_file" if title.startswith("Edit ") else "write_file"
    if kind == "execute":
        return "execute"
    return title or kind or "tool"


def error_text(err: dict) -> str:
    """The readable reason inside a JSON-RPC error, which is not its `message`.

    A provider refusal arrives as -32603 "Internal error" with the real thing in `data.details`,
    and that string is this agent's own traceback with its frames joined by " / " — MEASURED on a
    401 through the relay: `Error code: 401 - {...'Authentication failed'...} / raise
    OpenAIAuthenticationError( / langchain_openai...OpenAIAuthenticationError: ... / During task
    with name 'model'`. The first segment is the reason; the rest is the agent's internals, and a
    turn's record is not where they belong."""
    if not isinstance(err, dict):
        return "the agent reported an error"
    data = err.get("data") if isinstance(err.get("data"), dict) else {}
    text = str(data.get("details") or err.get("message") or "").strip()
    if not text:
        return "the agent reported an error"
    return text.split(" / ")[0].strip().splitlines()[0][:600]


def translate(updates: list[dict]) -> tuple[list[dict], str]:
    """ACP session updates → canonical claude events, and the turn's answer.

    Text arrives in chunks; they are joined into one block per run of them and flushed when a tool
    call interrupts, so the transcript keeps the order the reader saw."""
    evs: list[dict] = []
    buf: list[str] = []
    final: list[str] = []
    calls: dict[str, str] = {}

    def flush() -> None:
        text = "".join(buf).strip()
        buf.clear()
        if text:
            final.append(text)
            evs.append({"type": "assistant", "message": {"content": [
                {"type": "text", "text": text}]}})

    for u in updates:
        kind = str(u.get("sessionUpdate") or "")
        if kind == "agent_message_chunk":
            buf.append(str((u.get("content") or {}).get("text") or ""))
        elif kind == "tool_call":
            flush()
            cid = str(u.get("toolCallId") or "tool")
            name = _tool_name(str(u.get("title") or ""), str(u.get("kind") or ""))
            calls[cid] = name
            args = u.get("rawInput")
            evs.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": cid, "name": name,
                 "input": args if isinstance(args, dict) else {"input": args}}]}})
        elif kind == "tool_call_update":
            status = str(u.get("status") or "")
            if status not in ("completed", "failed"):
                continue                      # pending / in_progress: the call row already said so
            cid = str(u.get("toolCallId") or "tool")
            calls.pop(cid, None)
            parts = []
            for item in (u.get("content") or []):
                if not isinstance(item, dict):
                    continue
                inner = item.get("content") if isinstance(item.get("content"), dict) else {}
                parts.append(str(inner.get("text") or item.get("text") or ""))
            evs.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": cid, "is_error": status == "failed",
                 "content": "\n".join(p for p in parts if p)[:8000]}]}})
        # agent_thought_chunk, plan, user_message_chunk, current_mode_update: progress, not the
        # turn's record. The thought chunks are deliberately not rendered as the answer.
    flush()
    for cid, name in calls.items():
        # One call in this protocol never gets a completion: an edit_file with a full diff is sent
        # through the server's `start_edit_tool_call` branch, which emits the call and nothing
        # after it (measured on a six-tool turn — the edit landed, the status stayed `pending`).
        # A tool_use with no tool_result is a hole in the record, so it is closed by saying exactly
        # that rather than by claiming an outcome nobody reported.
        evs.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": cid, "is_error": False,
             "content": f"(the agent reported no completion for this {name} call)"}]}})
    return evs, "\n".join(final).strip()


def main() -> int:
    job = json.loads(sys.argv[1])
    cwd = str(job["cwd"])
    env = {**os.environ, **{str(k): str(v) for k, v in (job.get("env") or {}).items()}}
    model_spec = str(job.get("model_spec") or "")
    resume = str(job.get("resume") or "")
    started = time.time()
    try:
        acp = Acp(list(job["argv"]), cwd, env)
    except OSError as e:
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": f"dcode did not start: {e}", "usage": {}})
        return 0

    def fail(reason: str, with_tail: bool = False) -> int:
        """End the turn with a reason. The agent's stderr is added ONLY when nothing else said
        why: this CLI prints a full Python traceback there on a provider refusal, and a turn whose
        reason already names the refusal ("Error code: 401 - …") is worse off with three frames of
        langchain_openai glued to it (measured — it is what this did at first)."""
        tail = " / ".join(acp.errtail[-3:]) if with_tail else ""
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": (reason + (f": {tail}" if tail else ""))[:2000], "usage": {}})
        try:
            acp.proc.terminate()
        except OSError:
            pass
        return 0

    try:
        init = acp.call("initialize", {"protocolVersion": 1,
                                       "clientCapabilities": {"fs": {"readTextFile": False,
                                                                     "writeTextFile": False}},
                                       "clientInfo": {"name": "harnessrouter", "version": "1"}})
        if "error" in init:
            return fail(f"ACP initialize refused: {error_text(init['error'])}", with_tail=True)
        loadable = bool(((init.get("result") or {}).get("agentCapabilities")
                         or {}).get("loadSession"))
        session_id = ""
        # `known`: the store this turn runs on holds the thread (the runner asked it). A thread the
        # store does NOT have is not an error here: the turn runs as a new conversation and
        # _resume_lost (which asked the same store before this ran) tells the user it was gone.
        known = bool(job.get("resume_known"))
        if resume and loadable:
            got = acp.call("session/load", {"cwd": cwd, "sessionId": resume, "mcpServers": []})
            if "error" in got and known:
                # A thread the store HAS that will not load is never answered as a new
                # conversation: measured 2026-10-25 (kimi-k2.7-code, Vercel, four matrix columns
                # at once), turn 2 of a session ran on a NEW thread while the first one sat in the
                # store with its 23 checkpoints, nothing said so, and the recycle check found a
                # conversation that began at the second message. Asked once more, then the turn
                # fails with the agent's own reason.
                print(f"[dcode] session/load of a stored thread failed: {error_text(got['error'])}; asking once more",
                      file=sys.stderr, flush=True)
                time.sleep(1.0)
                got = acp.call("session/load", {"cwd": cwd, "sessionId": resume, "mcpServers": []})
                if "error" in got:
                    return fail("the conversation could not be continued: its thread is stored but "
                                f"the agent would not load it ({error_text(got['error'])})", with_tail=True)
            if "error" not in got:
                session_id = resume
        if not session_id:
            new = acp.call("session/new", {"cwd": cwd, "mcpServers": []})
            if "error" in new:
                return fail(f"ACP session/new refused: {error_text(new['error'])}", with_tail=True)
            session_id = str((new.get("result") or {}).get("sessionId") or "")
        if not session_id:
            return fail("the agent returned no session id", with_tail=True)
        emit({"type": "system", "subtype": "init", "session_id": session_id,
              "model": job.get("model") or ""})
        if model_spec:
            # The session carries its own model once it exists, so a switch has to be asked for.
            # Refusals are not fatal: the served model is read off the relay either way, and the
            # record then shows what actually answered.
            res = acp.call("session/set_config_option",
                           {"sessionId": session_id, "configId": "model", "value": model_spec})
            if "error" in res:
                emit({"type": "system", "subtype": "notice",
                      "text": f"this turn's model could not be set on the session: {model_spec}"})
        acp.recording = True        # everything before this is the loaded conversation's replay
        out = acp.call("session/prompt",
                       {"sessionId": session_id,
                        "prompt": [{"type": "text", "text": str(job["prompt"])}]},
                       timeout=min(_PROMPT_TIMEOUT, max(60.0, float(job.get("timeout") or _PROMPT_TIMEOUT))))
    except TimeoutError as e:
        return fail(f"the agent did not answer {e} in time", with_tail=True)
    evs, answer = translate(acp.updates)
    for ev in evs:
        emit(ev)
    if "error" in out:
        err = out["error"] if isinstance(out.get("error"), dict) else {}
        blob = json.dumps(err)
        if "ask_user" in blob or "free-form" in blob:
            # The one tool this surface declares and cannot carry: `ask_user` raises a free-form
            # LangGraph interrupt, which ACP has no shape for, and the server answers -32600. Say
            # what happened rather than handing back a protocol complaint.
            return fail("the agent tried to ask the user a question mid-turn, which this "
                        "connection cannot carry; re-send the task with the answer in it")
        reason = error_text(err)
        # The reason is the provider's sentence and nothing else: the GATEWAY frames a failed turn
        # ("The turn failed: <reason>", _turn_failure_message), so a driver that frames it too puts
        # the words in front of the person twice. MEASURED on the family tour (2026-10-20): the
        # muse family's refusal reached the console as "The turn failed: the turn failed: Error
        # code: 400 - …". Every other base here hands up the reason alone.
        return fail(reason, with_tail=reason == "the agent reported an error")
    stop = str((out.get("result") or {}).get("stopReason") or "")
    ok = stop == "end_turn"
    why = {"cancelled": "the turn was cancelled",
           "refusal": "the model refused the request",
           "max_tokens": "the model hit its token limit",
           "max_turn_requests": "the turn hit its request limit"}.get(stop, stop or "no stop reason")
    if ok and not answer.strip():
        # `end_turn` with NOTHING said. The protocol's normal end and an empty answer together are
        # not a completed turn: an empty string in the result slot reaches the person as a done
        # pill over a blank reply (docker-agent's eof refuses the same thing, for the same reason).
        # MEASURED in this base's first column (2026-10-20), on grok-4.5 through Vercel, TWICE in
        # three runs of that pair and on a different scenario each time: the turn's own record
        # held `output: []` — no content, no tool call — with 18 output tokens billed, all
        # reasoning, while the ACP server reported stopReason end_turn. Before this branch the
        # first one was recorded as a COMPLETED turn whose answer was "", which the console shows
        # as a done pill over a blank reply; with it, the second was recorded as failed and the
        # console showed the reason. The same shape was measured once on docker-agent
        # (gemini-3.5-flash-lite), which is why its eof refuses it too.
        #
        # This says nothing about WHY a provider answers with reasoning and no content — that is
        # the model's behaviour on this route, recorded as a row-level finding in
        # docs/support-matrix-notes.md. ACP carries no usage, so the reason here cannot name the
        # finish reason the way docker-agent's can; the relay's stamp is where that lives.
        ok = False
        why = "the agent ended the turn without answering"
    emit({"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
          # usage is the relay's to stamp (_fill_relay_usage): ACP carries none.
          "result": answer if ok else (why + (f" after {int(time.time() - started)}s" if not ok else "")),
          "usage": {}})
    try:
        acp.proc.terminate()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
