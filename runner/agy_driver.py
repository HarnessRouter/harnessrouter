"""One Antigravity CLI turn, over its ACP server, streamed, as a runner subprocess.

WHY ACP AND NOT `agy -p`. Both run the same agent. MEASURED on agy 1.5.8 (2026-11-13, against Google's
Gemini API through a loopback relay holding the key, the agent holding a placeholder):

  * `agy -p` posts usage data to https://play.googleapis.com/log every few seconds and at exit, and
    nothing switches that off: not `enableTelemetry` or `telemetry` in settings.json, not an
    environment variable, and the print mode refuses `--disable-telemetry`. `agy acp` takes
    `--disable-telemetry`, and with it the same session posted nothing (without it, six posts in
    fourteen seconds), measured through a proxy that logged every connection the process opened.
  * `session/set_model` takes agy's own model ids, which carry the thinking level
    (`gemini-3.8-flash-high`); the level reaches Google as thinkingConfig.thinkingLevel.
  * `session/load` in a SECOND process continues the conversation from the store under HOME
    (`~/.gemini/antigravity-cli/conversations/<id>.db`), replayed as updates before the prompt.
  * `session/prompt` answers with the turn's usage: inputTokens (the uncached part), outputTokens
    (thinking INCLUDED: 75 with thoughtTokens 74 for a one-word answer), cachedReadTokens,
    thoughtTokens and totalTokens, for this prompt alone, never the conversation's.
  * Every tool call carries the tool's own id in `name` beside ACP's title and kind, with its
    arguments in `rawInput`; an MCP tool is the generic `call_mcp_tool` with ServerName and ToolName.
  * The ACP server reads no settings.json (its `model`, `agentMode`, `toolPermission` and
    `permissions.deny` were all ignored). Without `--dangerously-skip-permissions` it asks the
    client before a shell command (`run_command`) and nothing else; a rejected command fails the
    call and ends the turn. That answer is the switch for the shell, here; the file tools never ask.

Protocol out: claude's stream-json on stdout, one object per line (the passthrough normaliser).
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acp_turn import Acp, Stream, emit, error_text, _PROMPT_TIMEOUT  # noqa: E402


def tool_name(update: dict) -> str:
    """A call's tool, as agy names it: its own id in `name`, and an MCP call as mcp__<server>__<tool>
    (agy routes every MCP tool through one tool, call_mcp_tool, with the two names in its input)."""
    name = str(update.get("name") or "")
    if name == "call_mcp_tool":
        args = update.get("rawInput") if isinstance(update.get("rawInput"), dict) else {}
        srv, tool = str(args.get("ServerName") or ""), str(args.get("ToolName") or "")
        if srv and tool:
            return f"mcp__{srv}__{tool}"
    return name or str(update.get("title") or update.get("kind") or "tool")


def usage(u) -> dict:
    """A prompt's usage, in the runner's contract: fresh input, output with thinking in it, the cache
    split, and the thinking as `reasoning_tokens`, never more than the output it is part of.

    agy 1.5.8 counts thinking inside outputTokens (75 = 1 + 74, and totalTokens = input + cached +
    output). Should a later build report them apart, the total says so (it would then hold output and
    thinking both), and the thinking is added rather than lost."""
    if not isinstance(u, dict):
        return {}

    def n(k: str) -> int:
        try:
            return max(int(u.get(k) or 0), 0)
        except (TypeError, ValueError):
            return 0

    inp, out, cached, written, thought, total = (n("inputTokens"), n("outputTokens"), n("cachedReadTokens"),
                                                 n("cachedWriteTokens"), n("thoughtTokens"), n("totalTokens"))
    if thought and total and total >= inp + cached + written + out + thought:
        out += thought
    got = {"input_tokens": inp, "output_tokens": out, "cache_read_tokens": cached}
    if written:
        got["cache_write_tokens"] = written
    if thought:
        got["reasoning_tokens"] = min(thought, out)
    return got


class _Calls:
    """What the record shows of a call: agy's own name for it, put where acp_turn's Stream reads one."""

    def __init__(self, stream: Stream) -> None:
        self.stream = stream

    def update(self, u: dict) -> None:
        if str(u.get("sessionUpdate") or "") in ("tool_call", "tool_call_update"):
            u = {**u, "title": tool_name(u)}
            if not isinstance(u.get("rawInput"), dict) and isinstance(u.get("args"), dict):
                u["rawInput"] = u["args"]          # agy carries the arguments in both; a failed call in `args` only
            diffs = [c for c in u.get("content") or [] if isinstance(c, dict) and c.get("type") == "diff"]
            if diffs:
                # A file write reports what it wrote as a diff, which has no text block of its own.
                u["content"] = [{"type": "content", "content": {"type": "text", "text": "\n".join(
                    f"{d.get('path') or ''}\n{d.get('newText') or ''}" for d in diffs)}}]
        self.stream.update(u)


def main() -> int:
    job = json.loads(sys.argv[1] if len(sys.argv) > 1 else os.environ.pop("HR_DRIVER_JOB"))
    cwd = os.path.realpath(str(job["cwd"]))
    env = {**os.environ, **{str(k): str(v) for k, v in (job.get("env") or {}).items()}}
    resume = str(job.get("resume") or "")
    withheld = {str(t) for t in job.get("withheld") or []}
    refused: list[str] = []
    started = time.time()
    stream = Stream(lambda title, kind: title or kind or "tool")
    calls = _Calls(stream)

    def permit(params: dict) -> bool:
        """The shell is switched off by answering its permission request no (see the module docstring)."""
        call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
        name = str(call.get("name") or "")
        if name in withheld:
            refused.append(name)
            return False
        return True

    try:
        acp = Acp(list(job["argv"]), cwd, env, on_update=calls.update, terminal=False, permit=permit)
    except OSError as e:
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": f"the Antigravity CLI did not start: {e}", "usage": {}})
        return 0

    def fail(reason: str, with_tail: bool = False) -> int:
        tail = " / ".join(acp.errtail[-3:]) if with_tail else ""
        emit({"type": "result", "subtype": "error", "is_error": True,
              "result": (reason + (f": {tail}" if tail else ""))[:2000], "usage": {}})
        acp.close()
        return 0

    try:
        init = acp.call("initialize", {"protocolVersion": 1,
                                       "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                                              "terminal": False},
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
        agy_model = str(job.get("agy_model") or "")
        if agy_model:
            # the session's model and its thinking level, in one id; a loaded session is moved to it too
            got = acp.call("session/set_model", {"sessionId": session_id, "modelId": agy_model})
            if "error" in got:
                return fail(f"the Antigravity CLI would not run {agy_model}: {error_text(got['error'])}")
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
        return fail(reason, with_tail=reason == "the agent reported an error")
    res = out.get("result") or {}
    stop = str(res.get("stopReason") or "")
    ok = stop == "end_turn"
    why = {"cancelled": "the turn was cancelled",
           "refusal": "the model refused the request",
           "max_tokens": "the model hit its token limit",
           "max_turn_requests": "the turn hit its request limit"}.get(stop, stop or "no stop reason")
    if ok and not answer.strip():
        # `end_turn` with nothing said is not a completed turn. agy ends a turn that way when a shell
        # command it asked for is refused, so the reason names the switched-off tool when there was one.
        ok = False
        why = (f"the agent tried to use {', '.join(sorted(set(refused)))}, which is switched off for this "
               "harness, and the turn stopped there" if refused else "the agent ended the turn without answering")
    elif not ok:
        why = f"{why} after {int(time.time() - started)}s"
    # The model the session was set to: the relay's first served model on a new conversation is the CLI's
    # title helper, never the turn's.
    emit({"type": "result", "subtype": "success" if ok else "error", "is_error": not ok,
          "result": answer if ok else why, "usage": usage(res.get("usage")),
          "model": job.get("model") or "", "session_id": session_id})
    acp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
