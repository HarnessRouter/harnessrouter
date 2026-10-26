"""One fast-agent turn, over its ACP server, streamed, as a runner subprocess.

WHY ACP AND NOT `go`. `fast-agent go ... --quiet` prints the answer and nothing else, and its `go`
command has no machine-readable stream; the turn's record was the ATIF trajectory it wrote, read
once the process had exited. So a fast-agent turn showed "Thinking" for its whole length and then
every step at once (Richard, 2026-10-26). `fast-agent-acp` is the same agent behind the Agent Client
Protocol, and it sends each text chunk and tool call as it happens. MEASURED on 0.10.47 (2026-10-26),
against a stand-in model:

  * `initialize` answers `loadSession: true`, and `session/load` in a SECOND process restores the
    conversation from the session store under `--home` (replayed as updates first, see acp_turn);
    the model was sent the whole history.
  * The session keeps the model it started on: a second process started with another `--model`
    still asked for the first, and `session/set_config_option` answers "method not found". The
    runner points the stored session at this turn's model before the process starts
    (server._fast_agent_set_model), as it did for `go --resume`.
  * Offered a terminal, the agent runs its shell commands through it and reports each one: a
    `tool_call` (no arguments yet), an `in_progress` update with the command, then `completed`
    with the output and exit code. Its own local shell reports a call with no arguments and no
    completion at all. So this client offers the terminal and runs the commands (acp_turn).
  * With the terminal its shell tool is named `execute` (with its own shell, `bash`); `process`
    is not declared. It is the same tool behind the same switch (`-x` / `--no-shell`), so the
    record keeps the name the harness's tool list has always used for it: `bash`.
  * `--workspace` is still what makes the session directory the tools' root; without it the
    commands ran in the agent's own home.

Protocol out: claude's stream-json on stdout, one object per line, which is why this backend's
normaliser in server.py is the passthrough. Usage is the relay's to stamp (_fill_relay_usage): ACP
carries none that prices.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acp_turn import Acp, Stream, emit, error_text, _PROMPT_TIMEOUT  # noqa: E402


def _tool_name(title: str, kind: str) -> str:
    """The tool's id from what ACP carries. The server's title IS the tool's name for its own file
    tools and for MCP tools; its shell tool is `execute` on this path and `bash` in the harness's
    tool list (see the module docstring)."""
    if title == "execute" or (kind == "execute" and not title):
        return "bash"
    return title.split("/")[-1] if title.startswith("environment/") else (title or kind or "tool")


def main() -> int:
    job = json.loads(sys.argv[1])
    # resolved as --workspace is, so the session the agent opens and the shell's directory are the same path
    cwd = os.path.realpath(str(job["cwd"]))
    env = {**os.environ, **{str(k): str(v) for k, v in (job.get("env") or {}).items()}}
    resume = str(job.get("resume") or "")
    terminal = bool(job.get("terminal", True))
    started = time.time()
    stream = Stream(_tool_name)
    try:
        acp = Acp(list(job["argv"]), cwd, env, on_update=stream.update, terminal=terminal)
    except OSError as e:
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": f"fast-agent did not start: {e}", "usage": {}})
        return 0

    def fail(reason: str, with_tail: bool = False) -> int:
        tail = " / ".join(acp.errtail[-3:]) if with_tail else ""
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": (reason + (f": {tail}" if tail else ""))[:2000], "usage": {}})
        acp.close()
        return 0

    try:
        init = acp.call("initialize", {"protocolVersion": 1,
                                       "clientCapabilities": {"fs": {"readTextFile": False,
                                                                     "writeTextFile": False},
                                                              "terminal": terminal},
                                       "clientInfo": {"name": "harnessrouter", "version": "1"}})
        if "error" in init:
            return fail(f"ACP initialize refused: {error_text(init['error'])}", with_tail=True)
        loadable = bool(((init.get("result") or {}).get("agentCapabilities") or {}).get("loadSession"))
        session_id = ""
        known = bool(job.get("resume_known"))
        if resume and loadable:
            got = acp.call("session/load", {"cwd": cwd, "sessionId": resume, "mcpServers": []})
            if "error" in got and known:
                # A conversation the store HAS that will not load is never answered as a new one.
                return fail("the conversation could not be continued: it is stored but the agent "
                            f"would not load it ({error_text(got['error'])})", with_tail=True)
            if "error" not in got:
                session_id = resume
        if not session_id:
            new = acp.call("session/new", {"cwd": cwd, "mcpServers": []})
            if "error" in new:
                return fail(f"ACP session/new refused: {error_text(new['error'])}", with_tail=True)
            session_id = str((new.get("result") or {}).get("sessionId") or "")
        if not session_id:
            return fail("the agent returned no session id", with_tail=True)
        emit({"type": "system", "subtype": "init", "session_id": session_id, "model": job.get("model") or ""})
        acp.recording = True        # everything before this is the loaded conversation's replay
        out = acp.call("session/prompt",
                       {"sessionId": session_id, "prompt": [{"type": "text", "text": str(job["prompt"])}]},
                       timeout=min(_PROMPT_TIMEOUT, max(60.0, float(job.get("timeout") or _PROMPT_TIMEOUT))))
    except TimeoutError as e:
        return fail(f"the agent did not answer {e} in time", with_tail=True)
    acp.recording = False
    stream.finish()
    answer = stream.answer()
    if "error" in out:
        reason = error_text(out["error"] if isinstance(out.get("error"), dict) else {})
        # The reason alone: the gateway frames a failed turn ("The turn failed: <reason>").
        return fail(reason, with_tail=reason == "the agent reported an error")
    stop = str((out.get("result") or {}).get("stopReason") or "")
    ok = stop == "end_turn"
    why = {"cancelled": "the turn was cancelled",
           "refusal": "the model refused the request",
           "max_tokens": "the model hit its token limit",
           "max_turn_requests": "the turn hit its request limit"}.get(stop, stop or "no stop reason")
    if ok and not answer.strip():
        # `end_turn` with nothing said is not a completed turn (dcode_driver says why at length).
        ok = False
        why = "the agent ended the turn without answering"
    emit({"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
          "result": answer if ok else f"{why} after {int(time.time() - started)}s",
          "usage": {}})
    acp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
