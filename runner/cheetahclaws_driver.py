"""One CheetahClaws turn, as a runner subprocess.

Spawned per turn by server.py (the same one-process-per-turn contract as every other backend: the
runner reads NDJSON off stdout, cancel is a process-group kill). Inside, CheetahClaws's own agent
loop is DRIVEN IN PROCESS — `cheetahclaws.agent.run`, the generator its REPL and its headless
bridge runner (`cli._start_headless_bridges`) both consume — rather than launched as
`cheetahclaws -p` whose printed text we would parse. Everything that loop yields is re-emitted the
moment it is yielded, as one {"m": method, "p": payload} line (the dsh_driver shape), normalised by
_cheetahclaws_to_claude in server.py. The version is pinned EXACTLY (docker/entrypoint.sh) because
the loop is the package's internal API rather than a documented one.

WHY NOT THE CLI, measured on the pinned 3.5.88:
  * No event stream. `-p` prints the final answer and ANSI tool cards, and the session file is the
    only structured record. That file is rewritten ONCE PER USER TURN — `autosave_session` runs
    after `run_query` returns (cli.py, "Silent autosave"), never between messages — so tailing it
    gives a silent turn and then everything at once, the stream S-09 measures as not progressive.
  * A provider failure is prose on stdout and exit 0. `cheetahclaws -p` against a dead endpoint, a
    bad key and a 429 printed `[Failed — APIConnectionError: …]`, `[Failed — AuthenticationError:
    Error code: 401 …]` and `[Failed — RateLimitError: Error code: 429 …]` and exited 0 each time.
    In process the verdict is structural instead: the loop appends an assistant message only when a
    completion came back, so a turn whose history ends on the user's message (or a tool result) had
    its last provider call fail, whatever the text said. The printed sentence is kept as the reason.
  * No resume flag. `-p` always starts from an empty AgentState; continuing is the REPL's `/resume`,
    which loads session_latest.json into the state. The driver does the same load (the CLI's own
    `_migrate_session`) before the turn and writes the file back after it with the CLI's own
    `autosave_session`, so the file the CLI would have written is the file on disk.
  * MCP connects in a background thread started at import (mcp_client/tools.py), so a `-p` turn can
    make its first model call before any MCP tool is registered. The driver waits for it.
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import sys
import time
import uuid

_T0 = time.time()
# The NDJSON channel. Everything CheetahClaws prints goes to stderr instead (see main), so a stray
# print from a tool can never land inside, or between, the lines the runner parses.
_OUT = sys.stdout

# The notices the agent loop yields as TextChunks of its own, outside the provider stream (agent.py
# on 3.5.88: the retry ladder, the final failure, an open circuit breaker, compaction, the read-only
# dedup and the two loop guards). They are the CLI talking, not the model, so they are reported as
# notices rather than as answer text. Each is yielded as ONE chunk that starts with "\n[".
_NOTICE = re.compile(r"^\n\[(?:Retry \d+/\d+ after \d+s — |Failed — |Circuit breaker OPEN |"
                     r"Context too long — |Context overflow — |NIM rate-limited |deduped |"
                     r"Loop guard\] )")
# The one a failed provider call ends on: `[Failed — <ExceptionType>: <message>.<hint>]`.
FAILED_RE = re.compile(r"^\s*\[Failed — (?P<body>.+)\]\s*$", re.S)
# A sentence that sends the reader to the CLI's own slash commands ("Hint: Check your API key:
# /config …", "Try /clear and rephrase …"). The person reading the turn record has no such prompt:
# the rule kimi's "To resume this session" line and aider's "Use /drop" advice already follow. The
# sentences around it are the reason and stay.
_SLASH_CMD = re.compile(r"(?:^|\s)/[a-z][\w-]*\b")
LOOP_GUARD = "[Loop guard]"

# Withheld on every turn, because none of them can do its job here. AskUserQuestion blocks on the
# terminal's stdin (tools/interaction.py, ask_input_interactive) and nobody is at it: a question
# goes into the answer instead, where the person reads it. ReadEmail and SendEmail need a mailbox
# the CLI reads from its own config (email_address, email_password, email_*_host), which this
# product never sets; offered, they are a tool that fails on every call.
ALWAYS_WITHHELD = ("AskUserQuestion", "ReadEmail", "SendEmail")
# Tools whose module is an OPTIONAL extra of the package, withheld while it is not installed in the
# venv. The pinned install is the bare package (docker/entrypoint.sh): the `files` extra brings
# pymupdf, which is AGPL-3.0, and `browser` brings playwright with a browser of its own. A tool the
# model is offered and cannot run is the overstatement UHP 4.3 forbids; an operator who installs
# an extra into the venv gets its tool back without a code change.
OPTIONAL_TOOLS = {"WebBrowse": "playwright", "ReadPDF": "fitz", "ReadSpreadsheet": "openpyxl",
                  "ReadImage": "PIL"}


def bound_provider_calls(read_seconds: float) -> None:
    """Give every OpenAI client the CLI builds a timeout, and let the loop's own ladder retry.

    WITHOUT THIS A TURN CAN HANG FOR AN HOUR. `custom/` builds `OpenAI(api_key=…, base_url=…)` per
    call (providers.py, stream_openai_compat) with the SDK's defaults: a 600 s timeout and two
    retries of its own, and the agent loop retries each failed call three more times on top
    (agent.py). Measured on the live instance: a turn aimed at an endpoint whose packets are
    dropped was still running after 600 s with nothing in its record. The read timeout here is the
    same budget aider's --timeout carries (HR_CHEETAHCLAWS_TIMEOUT, 300 s by default); the SDK's
    own retries are turned off so the loop's ladder — the one that says `[Retry n/3 …]` and ends
    on the `[Failed — …]` the record keeps — is the only one, bounding a dead endpoint to four
    attempts. `from openai import OpenAI` runs inside that function on every call, so replacing
    the module attribute reaches it."""
    import httpx
    import openai

    base = openai.OpenAI
    if getattr(base, "_hr_bounded", False):
        return

    class _Bounded(base):  # type: ignore[misc, valid-type]
        _hr_bounded = True

        def __init__(self, *a, **kw):
            kw.setdefault("timeout", httpx.Timeout(read_seconds, connect=30.0, write=60.0, pool=30.0))
            kw.setdefault("max_retries", 0)
            super().__init__(*a, **kw)

    openai.OpenAI = _Bounded


def unavailable_tools() -> list[str]:
    import importlib.util
    return sorted(t for t, mod in OPTIONAL_TOOLS.items() if importlib.util.find_spec(mod) is None)


def _emit(method: str, payload) -> None:
    _OUT.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    _OUT.flush()


def is_notice(text: str) -> bool:
    return bool(_NOTICE.match(text or ""))


def failure_reason(notice: str) -> str:
    """The sentence a failed call is reported with: the CLI's own words, minus the brackets and
    minus a hint that names a slash command."""
    text = (notice or "").strip()
    m = FAILED_RE.match(text)
    if m:
        text = "Failed — " + m.group("body").strip()
    elif text.startswith(LOOP_GUARD):
        text = "Loop guard: " + text[len(LOOP_GUARD):].strip()
    elif text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    sentences = re.split(r"(?<=[.!?)])\s+", text)
    return " ".join(s for s in sentences if not _SLASH_CMD.search(s)).strip()


def disabled_names(requested, registered) -> list[str]:
    """The registry names to withhold for a harness's disabled list.

    A built-in is named as the CLI names it (`Bash`, `Write`). An MCP tool is registered as
    `mcp__<server>__<tool>` and the harness names it by its bare tool name or `<server>.<tool>`, the
    two forms the aider bridge and the openhands filter already accept; both are matched here, so a
    disabled MCP tool is withheld by the same mechanism as a built-in rather than merely described."""
    want = ({str(x).strip() for x in (requested or []) if str(x).strip()}
            | set(ALWAYS_WITHHELD) | set(unavailable_tools()))
    out = set()
    for name in registered or []:
        if name in want:
            out.add(name)
            continue
        if name.startswith("mcp__"):
            parts = name.split("__", 2)
            if len(parts) == 3 and (parts[2] in want or f"{parts[1]}.{parts[2]}" in want):
                out.add(name)
    # Names that match nothing registered are passed through as well: the loop ignores them, and a
    # tool that registers late (an MCP server that connected after this call) is still covered.
    return sorted(out | want)


def session_file(home: pathlib.Path) -> pathlib.Path:
    """Where the CLI autosaves: config.MR_SESSION_DIR / session_latest.json (3.5.88)."""
    return home / ".cheetahclaws" / "sessions" / "mr_sessions" / "session_latest.json"


def load_session(path: pathlib.Path, session_id: str) -> dict | None:
    """The saved conversation when it is the one asked for, else None."""
    if not session_id:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("session_id") != session_id:
        return None
    if not isinstance(data.get("messages"), list) or not data["messages"]:
        return None
    return data


class Pairing:
    """Gives each ToolStart/ToolEnd the id of the tool call it belongs to.

    The loop's ToolStart and ToolEnd carry a name and no id, and the ends of a batch arrive after
    all of its starts (parallel calls first, then sequential ones, agent.py). The assistant message
    the loop appended just before (its TurnDone) holds the batch's calls with their real ids, in
    the order the starts follow, so a start takes the first unclaimed call of its name and an end
    takes the first unfinished start of its name. The ids are then the ones in the session file."""

    def __init__(self) -> None:
        self.pending: list[dict] = []
        self.started: list[dict] = []
        self.n = 0

    def batch(self, assistant_msg: dict | None) -> None:
        calls = (assistant_msg or {}).get("tool_calls") or []
        self.pending = [dict(c) for c in calls if isinstance(c, dict)]

    def start(self, name: str, inputs) -> str:
        for i, c in enumerate(self.pending):
            if c.get("name") == name:
                call = self.pending.pop(i)
                tid = str(call.get("id") or "")
                break
        else:
            tid = ""
        if not tid:
            self.n += 1
            tid = f"cc{self.n}"
        self.started.append({"id": tid, "name": name})
        return tid

    def end(self, name: str) -> str:
        for i, c in enumerate(self.started):
            if c["name"] == name:
                return self.started.pop(i)["id"]
        self.n += 1
        return f"cc{self.n}"


def verdict(messages: list, start: int, notices: list[str], budget_hit: bool) -> dict:
    """How the turn ended, read off the history the loop left behind.

    `start` is the index of the user message this turn appended. The loop appends an assistant
    message only for a completion that came back, and its own loop guards append one of their own
    whose text is the guard's notice; anything else that ends the loop (a failed provider call, an
    open circuit breaker) leaves the history ending on the user's message or on a tool result."""
    last = messages[-1] if len(messages) > start else None
    role = (last or {}).get("role")
    content = (last or {}).get("content")
    text = content if isinstance(content, str) else ""
    if budget_hit:
        return {"ok": False, "subtype": "error_max_turns", "final": text if role == "assistant" else "",
                "reason": "the operator's step budget was reached"}
    if role == "assistant" and not text.startswith(LOOP_GUARD):
        return {"ok": True, "subtype": "success", "final": text, "reason": ""}
    if role == "assistant":
        # The loop guard stopped a model that kept repeating itself: the CLI's sentence, not an
        # answer. The turn did not finish its task.
        return {"ok": False, "subtype": "error", "final": "", "reason": failure_reason(text)}
    failed = [n for n in notices if FAILED_RE.match(n.strip())]
    reason = failure_reason(failed[-1] if failed else (notices[-1] if notices else ""))
    return {"ok": False, "subtype": "error", "final": "",
            "reason": reason or "the turn ended without a completion from the provider"}


def main() -> int:
    job = json.loads(sys.argv[1])
    cwd = job.get("cwd") or os.getcwd()
    os.chdir(cwd)
    home = pathlib.Path(os.environ.get("HOME") or pathlib.Path.home())
    # Nobody is at the terminal. Anything that reads stdin gets end-of-file at once instead of
    # waiting on a pipe the runner never writes.
    sys.stdin = open(os.devnull, encoding="utf-8")
    logs = home / ".cheetahclaws" / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    with contextlib.redirect_stdout(sys.stderr):
        from cheetahclaws.config import load_config
        from cheetahclaws.bootstrap import bootstrap
        from cheetahclaws import runtime
        from cheetahclaws.agent import (AgentState, run, TextChunk, ThinkingChunk, ToolStart,
                                        ToolEnd, TurnDone, PermissionRequest)
        from cheetahclaws.commands import session as cc_session
        from cheetahclaws.context import build_system_prompt

        config = load_config()
        config.update({
            "model": job["model"],
            # The harness is the permission layer: its disabled tools are withheld from the schema
            # below, and nobody is at a prompt to approve anything else.
            "permission_mode": "accept-all",
            # CheetahClaws writes its structured log (one JSON object per line) to stderr unless
            # it has a file, and the runner merges stderr into the NDJSON stream it parses.
            "log_file": str(logs / "cheetahclaws.jsonl"),
            "quiet": True,
        })
        bootstrap(config)
        bound_provider_calls(float(os.environ.get("HR_CHEETAHCLAWS_TIMEOUT") or 300))

        # MCP: connect every configured server and register its tools BEFORE the tool list is
        # taken, instead of racing the background connect the import started.
        # A server that does not connect is left out and the turn runs without it, silently in the
        # CLI; here it becomes the runner's mcp_unavailable event, which the gateway renders as a
        # note on the reply (the kimi precedent).
        down: list[dict] = []
        try:
            from cheetahclaws.mcp_client.tools import initialize_mcp
            for server, error in (initialize_mcp() or {}).items():
                if error:
                    down.append({"name": str(server), "reason": str(error)[:200]})
        except Exception as exc:  # noqa: BLE001 — a broken MCP stack must not stop the turn
            down.append({"name": "mcp", "reason": f"{type(exc).__name__}: {exc}"[:200]})
        from cheetahclaws.tool_registry import get_all_tools
        config["disabled_tools"] = disabled_names(job.get("tools_disabled"),
                                                  [t.name for t in get_all_tools()])

        state = AgentState()
        path = session_file(home)
        saved = load_session(path, str(job.get("session_id") or ""))
        if saved is not None:
            saved = cc_session._migrate_session(saved)
            state.messages = saved.get("messages", [])
            state.turn_count = saved.get("turn_count", 0)
            state.total_input_tokens = saved.get("total_input_tokens", 0)
            state.total_output_tokens = saved.get("total_output_tokens", 0)
            sid = saved["session_id"]
        else:
            sid = uuid.uuid4().hex[:8]
        config["_session_id"] = sid
        runtime.get_session_ctx(sid).agent_state = state
        # autosave_session keeps one id per PROCESS (a module global minted on first use); a turn
        # is one process, so without this every turn would save the conversation under a new id
        # and the next turn could not ask for it.
        cc_session._autosave_sid = sid

        system_prompt = build_system_prompt(config)
        doc = pathlib.Path(cwd, "CLAUDE.md")
        if doc.is_file() and f"[Project CLAUDE.md: {doc}]" not in system_prompt:
            # get_claude_md drops the WHOLE file when a line matches one of its prompt-injection
            # patterns (context.py, _THREAT_PATTERNS) and says so only on stderr. The harness's
            # instructions then never reach the model; the record says so.
            _emit("warning", {"text": "CheetahClaws excluded CLAUDE.md from the system prompt "
                                      "(its prompt-injection scan matched), so the harness "
                                      "instructions did not reach the model"})

    _emit("__hr_init", {"session_id": sid, "resumed": saved is not None,
                        "messages": len(state.messages)})
    if down:
        _emit("mcp_unavailable", {"servers": down})

    budget = int(job.get("max_turns") or 0)
    calls = {"n": 0}
    pairing = Pairing()
    notices: list[str] = []
    start = len(state.messages)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            events = run(job["prompt"], state, config, system_prompt,
                         cancel_check=lambda: bool(budget) and calls["n"] >= budget)
            for ev in events:
                if isinstance(ev, TextChunk):
                    if is_notice(ev.text):
                        notices.append(ev.text.strip())
                        _emit("notice", {"text": ev.text.strip()})
                    elif ev.text:
                        _emit("text", {"text": ev.text})
                elif isinstance(ev, ThinkingChunk):
                    if ev.text:
                        _emit("thinking", {"text": ev.text})
                elif isinstance(ev, TurnDone):
                    calls["n"] += 1
                    pairing.batch(state.messages[-1] if state.messages else None)
                elif isinstance(ev, ToolStart):
                    tid = pairing.start(ev.name, ev.inputs)
                    _emit("tool_start", {"id": tid, "name": ev.name, "input": ev.inputs or {}})
                elif isinstance(ev, ToolEnd):
                    tid = pairing.end(ev.name)
                    _emit("tool_end", {"id": tid, "name": ev.name, "result": str(ev.result or ""),
                                       "permitted": bool(ev.permitted)})
                elif isinstance(ev, PermissionRequest):
                    # accept-all never asks; if a future version does, the harness answers as the
                    # permission mode it set. Withheld tools never reach this point.
                    ev.granted = True
                elif type(ev).__name__ == "QuotaPause":
                    notices.append(f"[Budget reached — {getattr(ev, 'reason', '')}]")
    except Exception as exc:  # noqa: BLE001 — the turn's failure is the product here, not a crash
        _save(cc_session, state, config)
        _emit("__hr_result", {"ok": False, "subtype": "error", "final": "", "session_id": sid,
                              "reason": f"{type(exc).__name__}: {exc}"[:500],
                              "seconds": round(time.time() - _T0, 2)})
        return 1

    budget_hit = bool(budget) and calls["n"] >= budget and (
        not state.messages or state.messages[-1].get("role") != "assistant"
        or bool(state.messages[-1].get("tool_calls")))
    out = verdict(state.messages, start, notices, budget_hit)
    _save(cc_session, state, config)
    _emit("__hr_result", {**out, "session_id": sid, "calls": calls["n"],
                          "seconds": round(time.time() - _T0, 2)})
    return 0


def _save(cc_session, state, config) -> None:
    """The CLI's own per-turn autosave: session_latest.json under the redirected HOME, which
    travels in the checkpoint."""
    with contextlib.redirect_stdout(sys.stderr):
        try:
            cc_session.autosave_session(state, config)
        except Exception:  # noqa: BLE001 — autosave is best-effort in the CLI too
            pass


if __name__ == "__main__":
    sys.exit(main())
