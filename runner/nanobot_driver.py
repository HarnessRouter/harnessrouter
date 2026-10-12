"""One nanobot turn, as a runner subprocess.

Spawned per turn by server.py (the same one-process-per-turn contract every backend has: the runner
reads NDJSON off stdout, cancel is a process-group kill). Inside, nanobot's own agent loop is
DRIVEN IN PROCESS through its published Python SDK — `Nanobot.from_config(...).stream(...)`, the
surface its docs/python-sdk.md documents — and the events it yields are re-emitted as CLAUDE'S
stream-json, which is why this backend's normaliser in server.py is the passthrough (the
systemone_driver precedent).

WHY THE SDK AND NOT `nanobot agent -m`, measured on the pinned 0.3.5:

  * The CLI prints prose. One-shot `-m` writes the final answer and a tool line to the terminal;
    there is no JSON stream, no usage, no tool ids, so a turn record built from it could not show
    what the agent did or what it cost.
  * The CLI SEEDS THE WORKSPACE. Its path calls `sync_workspace_templates()`, which creates
    AGENTS.md, SOUL.md, USER.md, HEARTBEAT.md, memory/MEMORY.md, memory/history.jsonl,
    prompts/README.md and skills/ and then `GitStore.init()`s a git repository in the workspace.
    Measured on a bare directory: all eight appeared. Every one of them would be handed to the user
    as a file their task produced, and the git repo is a second one in the directory the runner's
    checkpoint already keeps a repo in. The SDK path calls NEITHER (grepped: the function is reached
    only from cli/, gateway_runtime and webui) — only `.nanobot/workspace-id` is created.
  * An AGENTS.md written by the runner would have been one of those eight. The runner writes the
    workspace contract there before the turn starts, and `sync_workspace_templates` only creates
    files that are missing, so the contract would have survived — but only by luck of ordering.

WHAT THIS DRIVER OWES THE TURN, and where each answer comes from:

  * the served model and the token split — the relay's taps. nanobot reports usage itself and this
    driver passes it on, netted (see `_usage`); the model it names is the one it was ASKED for, so
    rule 2 is the relay's to answer, which is why the key reaches it through the ENVIRONMENT.
  * continuity — `session_key`. nanobot keeps sessions beside its CONFIG file
    (`get_data_dir()` is `get_config_path().parent`), so server.py puts the config under
    .harness/nanobot/ and the conversation is checkpointed and excluded from produced files for
    free. Verified across two separate processes with the same key.
  * the tool policy — the SESSION's policy, not the registry. The loop filters tools per turn from
    `session.policy.disabled_tools` AFTER the MCP provider has registered its own tools, so this is
    the one door that covers both tool sources (the openhands lesson: built-in and MCP tools load on
    different code paths, and a filter in front of only one of them is half a policy).
  * a failure that reads as a failure — `run.failed`, and a `run.completed` whose RunResult carries
    an `error` or a non-completed `stop_reason`. Both end the turn as an error with the reason.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import time

# The NDJSON channel. nanobot logs through loguru, whose default sink is stderr, and the level is
# raised below — but a stray print from a tool must still be unable to land inside the lines the
# runner parses, so stdout is captured here and nothing else is allowed to write to it.
_OUT = sys.stdout


def _emit(ev: dict) -> None:
    _OUT.write(json.dumps(ev, default=str) + "\n")
    _OUT.flush()


def _text(t: str) -> None:
    if t:
        _emit({"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}})


def _usage(u: object) -> dict:
    """nanobot's LLMUsage, netted to this product's contract.

    `input_tokens` is GROSS: one measured turn reported input_tokens 11107 with
    cache_read_tokens 5503, and its two requests reported 5506 and 5601 — the cached read is a
    SUBSET of the input, not a sibling of it. Billing charges fresh input at the input rate and the
    cached subset at the cache-read rate, so a gross number here is the ~10x overcharge
    _norm_token_usage's own comment describes. `cache_write_tokens` is None on an endpoint that
    reports no write, which is why every field is read defensively rather than assumed present."""
    if u is None:
        return {}
    get = (lambda k: getattr(u, k, None)) if not isinstance(u, dict) else (lambda k: u.get(k))

    def n(k: str) -> int:
        v = get(k)
        return int(v) if isinstance(v, (int, float)) and v > 0 else 0

    read, write = n("cache_read_tokens"), n("cache_write_tokens")
    out = {"input_tokens": max(n("input_tokens") - read - write, 0),
           "output_tokens": n("output_tokens")}
    if read:
        out["cache_read_tokens"] = read
    if write:
        out["cache_write_tokens"] = write
    return {k: v for k, v in out.items() if v}


def _quiet() -> None:
    """Raise nanobot's own log level so the runner's bounded stderr tail holds the turn's real
    failure rather than 40 lines of DEBUG. The tail is what the gateway shows when a turn fails, and
    it keeps 80 lines: on the first probe every one of them was `Stage <x> completed in 0.2ms`."""
    try:
        from loguru import logger
        logger.remove()
        logger.add(sys.stderr, level=os.environ.get("HR_NANOBOT_LOG_LEVEL", "WARNING"))
    except Exception:  # noqa: BLE001 — logging is not worth failing a turn over
        pass


async def _run(job: dict) -> int:
    from nanobot import (  # imported here so _quiet() runs before nanobot configures logging
        STREAM_EVENT_REASONING_DELTA,
        STREAM_EVENT_RUN_COMPLETED,
        STREAM_EVENT_RUN_FAILED,
        STREAM_EVENT_TEXT_DELTA,
        STREAM_EVENT_TOOL_COMPLETED,
        STREAM_EVENT_TOOL_FAILED,
        STREAM_EVENT_TOOL_STARTED,
        Nanobot,
    )

    session_key = str(job.get("session_key") or "harness")
    prompt = str(job.get("prompt") or "")
    disabled = sorted({str(x).split(" (")[0].strip() for x in (job.get("tools_disabled") or []) if x})
    started = time.time()
    final = ""
    result_sent = False

    # The process cwd is the SESSION directory, and nanobot's workspace is a directory inside it
    # (runner/server.py, _NANOBOT_WS, with the reason). Its file tools resolve a relative path
    # against the configured workspace, but its shell does not have to, and a tool that writes
    # `report.md` must not land one level above the workspace the model was told it has. Agent
    # Zero's artifact failures were exactly this — the driver left the cwd at the framework's base,
    # so a model that passed a relative path wrote outside what the user collects — so the two are
    # made to agree here rather than left to the tool.
    os.chdir(job["workspace"])
    async with Nanobot.from_config(config_path=job["config_path"],
                                   workspace=job["workspace"]) as bot:
        _emit({"type": "system", "subtype": "init", "session_id": session_key,
               "model": str(job.get("model") or "")})
        if disabled:
            # The session's policy, deliberately, and NOT a filtered ToolRegistry built here: the
            # loop re-reads `session.policy.disabled_tools` on every turn and applies it to the
            # registry it is about to use, which by then also holds the MCP provider's tools. A
            # registry filtered at construction would withhold the built-ins and let every MCP tool
            # through — the exact half-policy openhands shipped. `get_or_create` returns the cached
            # object the loop will itself fetch, so mutating it here is the same session.
            sess = bot._loop.sessions.get_or_create(session_key)   # noqa: SLF001
            sess.policy = dataclasses.replace(sess.policy, disabled_tools=frozenset(disabled))
            # And CHECK that it took. A tool policy that quietly fails to apply is the worst shape
            # of this defect: the console reports the tool as off, the model is offered it anyway,
            # and nothing anywhere says so. The policy object is upstream's, pinned by the
            # entrypoint, so this can only fire if a release changed its type — and then the turn
            # fails with the reason instead of running with the policy missing.
            if frozenset(disabled) - set(getattr(sess.policy, "disabled_tools", ()) or ()):
                raise RuntimeError(
                    "nanobot's session policy did not take the disabled tools "
                    f"({', '.join(disabled)}); refusing to run the turn with the tool policy missing")

        async for ev in bot.stream(prompt, session_key=session_key):
            t = ev.type
            if t == STREAM_EVENT_TEXT_DELTA:
                final += ev.delta or ""
                _text(ev.delta or "")
            elif t == STREAM_EVENT_REASONING_DELTA:
                if ev.delta:
                    _emit({"type": "assistant", "message": {"content": [
                        {"type": "thinking", "thinking": ev.delta}]}})
            elif t == STREAM_EVENT_TOOL_STARTED:
                _emit({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": str(ev.tool_call_id or "tool"),
                     "name": str(ev.name or "tool"),
                     "input": ev.arguments if isinstance(ev.arguments, dict) else {}}]}})
            elif t in (STREAM_EVENT_TOOL_COMPLETED, STREAM_EVENT_TOOL_FAILED):
                failed = t == STREAM_EVENT_TOOL_FAILED
                meta = ev.metadata if isinstance(ev.metadata, dict) else {}
                body = str(meta.get("detail") or meta.get("result") or ev.error or "")
                _emit({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": str(ev.tool_call_id or "tool"),
                     "is_error": failed, "content": body[:8000]}]}})
            elif t == STREAM_EVENT_RUN_FAILED:
                _emit({"type": "result", "subtype": "error", "is_error": True,
                       "result": str(ev.error or "nanobot run failed")[:1000],
                       "usage": _usage(ev.usage)})
                result_sent = True
            elif t == STREAM_EVENT_RUN_COMPLETED:
                res = ev.result
                # The RunResult's `content` is the FINAL answer on its own (measured: "DONE", not
                # the whole turn's prose), so it is authoritative over what the deltas assembled.
                answer = str(getattr(res, "content", "") or final)
                err = str(getattr(res, "error", "") or "")
                stop = str(getattr(res, "stop_reason", "") or "")
                ok = not err and stop in ("", "completed", "stop", "end_turn")
                ev_out = {"type": "result",
                          "subtype": "success" if ok else "error", "is_error": not ok,
                          "result": answer if ok else (err or answer),
                          "usage": _usage(getattr(res, "usage", None))}
                if not ok and stop and not err:
                    # A stop reason that is not completion is the reason, and it is reported as
                    # one rather than silently passed off as an answer.
                    ev_out["reason"] = stop
                _emit(ev_out)
                result_sent = True
    if not result_sent:
        # The stream ended without either terminal event. That is not a success: say so, and leave
        # the text empty so the runner's stderr tail is the reason rather than a sentence invented
        # here (the same rule _kimi_eof follows).
        _emit({"type": "result", "subtype": "error", "is_error": True, "result": "", "usage": {}})
        return 1
    return 0


def main() -> int:
    _quiet()
    try:
        job = json.loads(sys.argv[1])
    except Exception as e:  # noqa: BLE001
        print(f"nanobot driver: bad job: {e}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_run(job))
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001
        # The exception text is the only reason anybody will have, so it goes to stderr (which the
        # runner collects into the turn's failure reason) AND the turn is failed explicitly, so a
        # crashed driver never reads as a turn that completed with no answer.
        print(f"nanobot driver: {type(e).__name__}: {e}", file=sys.stderr)
        _emit({"type": "result", "subtype": "error", "is_error": True,
               "result": f"{type(e).__name__}: {e}"[:1000], "usage": {}})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
