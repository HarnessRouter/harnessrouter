"""One Aider turn, as a runner subprocess.

Spawned per turn by server.py (the same one-process-per-turn contract as every other backend: the
runner reads NDJSON off stdout, cancel is a process-group kill). Inside, aider is DRIVEN IN PROCESS
through `aider.main.main(..., return_coder=True)`, which hands back the constructed Coder without
running the interactive loop — rather than launched as a CLI whose printed text we would parse. That
entry point is aider's own: its GUI calls it (`gui.py:71`) and its test suite covers it. It is NOT a
supported API, and saying so would be a lie upstream has already contradicted — aider's scripting
page states that "the python scripting API is not officially supported or documented, and could
change in future releases without providing backwards compatibility". This is why the version is
pinned EXACTLY and why install-time checks assert the symbols this driver reaches for.

WHY THIS EXISTS AT ALL, measured on the pinned 0.86.2. Aider has no machine-readable output mode,
and its stdout is ONE channel carrying both the model's prose and aider's own diagnostics. A stub
was made to return model prose whose second line began `litellm.AuthenticationError:`; on stdout it
was BYTE-IDENTICAL to a real 401 on the same stream, same exit code 0, no colour under --no-pretty.
So no anchored regex can separate "the provider failed" from "the agent wrote about an error", and a
text-parsing normaliser for this backend would invent failures on ordinary answers. In process the
two are never mixed: a real failure reaches io.tool_error/io.tool_warning and leaves
`coder.usage_report` None, while prose reaches io.assistant_output only.

WHAT ELSE ONLY WORKS IN PROCESS:
  * The shell intercept (see _Gate). Upstream's --yes-always deliberately auto-DECLINES every shell
    command the model proposes, and in driver mode aider forces yes_always on itself
    (main.py:546-547), so wrapping io.confirm_ask is the only way to let a skill's script run — and
    the only place a per-harness tool policy can be applied to a command before it executes.
  * Relocating the repo-map tags cache out of the workspace root (see main), which has no CLI flag
    and would otherwise hand the user a `.aider.tags.cache.v4/` directory as a deliverable.

The event protocol is dsh_driver's: one {"m": method, "p": payload} JSON object per line on stdout,
normalised by _aider_to_claude in server.py.
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import shlex
import sys
import time

_T0 = time.time()

# A SEARCH/REPLACE block as aider's editblock format writes it: the file name alone on the line
# before the fence, the fence (with or without a language), the three markers. The markers'
# lengths follow editblock_coder.py (5 to 9 characters). This is aider's wire format for an edit,
# and the edit is reported as a card of its own; the prose around the block is the answer.
_EDIT_BLOCK = re.compile(r"(?:^\S+\n)?```[^\n]*\n<{5,9} SEARCH\n.*?^>{5,9} REPLACE\n```\n?",
                         re.S | re.M)


def strip_edit_blocks(text: str) -> str:
    return _EDIT_BLOCK.sub("", text or "").strip()


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    sys.stdout.flush()


class _Gate:
    """The policy gate on every shell command the model proposes.

    It is NOT a blanket yes. It receives the exact command aider is about to run, checks it against
    the harness's disabled-tool list, and refuses with the policy as the reason — which is what
    makes `tool_enforcement` on this backend a gate that exists rather than a claim that passes
    because the harness has no tools at all.

    The model chooses the command; the harness never injects one. (`--message "/run <cmd>"` would be
    US choosing it, and is deliberately not used anywhere in this backend.)

    Two kinds of name are matched against the policy:
      * `hr-mcp call <server> <tool>` — the MCP bridge's call form, so a disabled MCP tool is
        refused by the tool's own name;
      * the command's argv[0], so a disabled `Shell` withholds shell execution outright.
    """

    def __init__(self, disabled: list[str]) -> None:
        self.disabled = {d.strip().lower() for d in (disabled or []) if d and d.strip()}
        self.calls: list[dict] = []

    def mcp_tool_of(self, command: str) -> tuple[str, str]:
        """('server', 'tool') when this command is an hr-mcp call, ('', '') otherwise."""
        try:
            parts = shlex.split(command)
        except ValueError:
            return "", ""
        # hr-mcp call <server> <tool> [--params …] — the exact form the runner documents to the
        # model in the bridge block, so recognising it here is reading our own contract back.
        # `hr-mcp tools <server>` is discovery, not a tool call, and is deliberately NOT matched:
        # recording it as one would invent an MCP call in the turn record.
        if len(parts) >= 4 and os.path.basename(parts[0]) == "hr-mcp" and parts[1] == "call":
            return parts[2], parts[3]
        return "", ""

    def decide(self, command: str) -> tuple[bool, str, str]:
        """(approved, tool_name, reason). tool_name is what the turn record will call this."""
        server, tool = self.mcp_tool_of(command)
        if tool:
            name = f"{server}.{tool}"
            for d in (tool.lower(), name.lower()):
                if d in self.disabled:
                    return False, name, f"the harness disabled the tool '{tool}'"
            return True, name, ""
        if "shell" in self.disabled or "bash" in self.disabled:
            return False, "Shell", "the harness disabled shell commands"
        return True, "Shell", ""


def _install(coder, gate: _Gate) -> None:
    """Replace the Coder's IO with one that reports on separate channels and gates confirmations."""
    io = coder.io
    orig_confirm = io.confirm_ask
    orig_assistant = io.assistant_output
    orig_error = io.tool_error
    orig_warning = io.tool_warning

    def assistant_output(message, pretty=None):
        # WHAT ARRIVES HERE IS AIDER'S DISPLAY STRING, NOT THE MODEL'S ANSWER. For a reasoning
        # model base_coder.py:1882-1890 prepends the chain of thought and rewrites its tags into
        # terminal furniture (`► **THINKING**` ... `► **ANSWER**`, reasoning_tags.py:10-11) before
        # handing it here. MEASURED on vercel|aider|grok-4.20 (2026-09-18, the column's only id
        # whose provider returns a reasoning field): its cards carried the model deliberating --
        # `...(wait, no, that's not how it works)... So my response should be: ► ANSWER ...` -- and
        # were scored against text the model never addressed to the user.
        #
        # The answer is `partial_response_content`, set from the completion's own `content`
        # (base_coder.py:1866) and never decorated; aider's own helper covers the other shape, a
        # provider that inlines the tags in content instead of sending a separate field. The
        # display string is the fallback only when there is no content, so a call site off the send
        # path still reports something.
        try:
            from aider.reasoning_tags import remove_reasoning_content
            body = remove_reasoning_content(coder.partial_response_content or "",
                                            coder.reasoning_tag_name)
        except Exception:
            body = ""
        _emit("text", {"text": strip_edit_blocks(body or str(message))})
        return orig_assistant(message, pretty)

    def tool_error(message="", strip=True):
        # A REAL failure lands here and nowhere else. This is the whole reason the driver exists:
        # on stdout this text and the model's own prose are the same bytes.
        _emit("error", {"text": str(message)})
        return orig_error(message, strip)

    def tool_warning(message="", strip=True):
        _emit("warning", {"text": str(message)})
        return orig_warning(message, strip)

    def confirm_ask(question, default="y", subject=None, explicit_yes_required=False,
                    group=None, allow_never=False):
        # explicit_yes_required is set by exactly ONE call site in the whole 0.86.2 tree —
        # handle_shell_commands (coders/base_coder.py) — so this branch is the shell gate and
        # nothing else. Every other confirmation keeps aider's own --yes-always behaviour by
        # falling through to the original.
        if explicit_yes_required:
            command = str(subject or question)
            approved, name, reason = gate.decide(command)
            gate.calls.append({"command": command, "tool": name, "approved": approved,
                               "reason": reason})
            _emit("shell_decision", {"command": command, "tool": name,
                                     "approved": approved, "reason": reason})
            return approved
        return orig_confirm(question, default=default, subject=subject,
                            explicit_yes_required=explicit_yes_required, group=group,
                            allow_never=allow_never)

    io.assistant_output = assistant_output
    io.tool_error = tool_error
    io.tool_warning = tool_warning
    io.confirm_ask = confirm_ask


def _run_shell_commands_reporting(coder, gate: _Gate, reflect: bool = True):
    """Wrap Coder.run_shell_commands so each approved command's OUTPUT is reported too.

    aider runs the command itself and appends the output to the next message's context; it exposes
    no per-command result hook, so the pairing here is: the gate records the call as aider asks, and
    this wrapper reports what the whole batch produced. Without it the turn record would show a
    tool_use with no tool_result."""
    orig = coder.run_shell_commands

    def wrapped():
        before = len(gate.calls)
        out = orig()
        for call in gate.calls[before:]:
            if call["approved"]:
                _emit("shell_result", {"tool": call["tool"], "command": call["command"],
                                       "output": str(out or "")})
        # MUST clear, and this is not tidiness: init_before_message() empties shell_commands ONCE
        # per turn, not once per reflection, and run_shell_commands iterates whatever is in it. With
        # a reflection set below, the next pass would RE-RUN every command already executed —
        # measured: one proposed command ran four times and the turn made four provider round trips
        # instead of two, with the side effects repeated each time.
        coder.shell_commands = []
        if reflect and out:
            # MEASURED, and the reason this is not the default everywhere: aider stashes shell
            # output in cur_messages for the NEXT user message and sets no reflection of its own
            # (base_coder.py:1609-1614), unlike lint and test results which DO set
            # reflected_message. So within one turn the model never sees what its command printed —
            # it cannot report a token the script produced, and every other backend here can.
            # Setting the reflection gives aider the same in-turn loop, using aider's own mechanism
            # and its own max_reflections bound rather than a loop of ours.
            coder.reflected_message = str(out)
        return out

    coder.run_shell_commands = wrapped


def _run_turn(coder, prompt: str) -> None:
    """aider's own reflection loop (Coder.run_one), driven directly.

    run_stream is run_one without the loop: it sends ONE message and stops. Reproducing the loop
    here is what lets a reflection — aider's mechanism for "there is more to do before this turn
    ends", used by its lint and test paths — carry a shell command's output back to the model in the
    SAME turn. The bound is aider's own max_reflections, not one invented here."""
    coder.io.user_input(prompt)
    coder.init_before_message()
    message = prompt
    reflections = 0
    reported: set = set()
    while message:
        coder.reflected_message = None
        list(coder.send_message(message))
        # aider_edited_files accumulates over the turn; what this pass added is reported now, so
        # the cards sit beside the prose that produced them.
        edited = sorted(set(coder.aider_edited_files or []) - reported)
        if edited:
            reported.update(edited)
            _emit("edits", {"files": edited})
        if not coder.reflected_message:
            break
        if reflections >= coder.max_reflections:
            _emit("warning", {"text": f"stopped after {coder.max_reflections} reflections"})
            break
        reflections += 1
        message = coder.reflected_message


def _write_model_metadata(cwd: str, model: str) -> str | None:
    """Give aider back the model record that the `openai/` prefix hides from it.

    server.py prefixes every id with `openai/` on purpose, so aider resolves it through litellm's
    openai provider verbatim instead of through aider's MODEL_ALIASES table, which rewrites 21 ids.
    The cost went unmeasured until the google column: litellm's lookup for a prefixed name only
    falls back to the bare id when that id's own `litellm_provider` IS openai (models.py:228-231).
    So `openai/gpt-5.6-sol` keeps its full 66-key record while EVERY gemini, claude, grok and qwen
    id resolves to an empty dict.

    Empty info is not cosmetic. aider reads its limits off that record, so a turn runs with
    max_input_tokens and max_output_tokens of 0 and REPORTS them: measured on
    google|aider|gemini-3-flash-preview (2026-09-16), a truncated answer died with
    `Input tokens: ~45,356 of 0 -- possibly exhausted context window!`, an accusation about a
    1,048,576-token model built entirely out of the absent record. base_coder.py:1492 reads
    `supports_assistant_prefill` off the same dict to decide whether a `finish_reason: length` may
    be continued by prefilling the assistant turn, and an empty dict always answers no.

    The fix asks the info manager for the BARE id: the same lookup aider would have done without the
    prefix, and no alias rewriting, because this queries the manager rather than constructing a
    Model. Whatever litellm ships is what aider gets -- no limit is hardcoded here -- and an id
    litellm does not know (claude-opus-4.8, grok-4.6, qwen3.8-max and kimi-k3 among them) writes
    nothing and leaves the turn exactly as it behaves today.

    WHAT THIS DOES NOT DO is change whether a turn passes, and the temptation to claim otherwise was
    measured away. litellm records no `supports_assistant_prefill` for the gemini family either, so
    the abandon-on-length path is identical with and without this file, and an A/B of that one pair
    -- three runs each way, 2026-09-16 -- put every recycle in the same band whichever driver ran:
    19.9s / 209.0s with it, 210.8s / 222.8s / 229.2s without, and the original 399.1s failure is the
    tail of that same distribution rather than a defect this repaired. This makes the limits real
    and the failure legible. Nothing more.
    """
    bare = model.split("/", 1)[1] if model.startswith("openai/") else model
    try:
        from aider.models import model_info_manager
        # get_model_info prints to stdout on a failed cache refresh (models.py:203) and stdout is
        # this driver's NDJSON channel, so the lookup is fenced off it.
        with contextlib.redirect_stdout(sys.stderr):
            info = model_info_manager.get_model_info(bare)
    except Exception:
        info = None
    if not info:
        return None
    path = pathlib.Path(cwd, ".harness", "aider", "model-metadata.json")
    try:
        path.write_text(json.dumps({model: dict(info)}, default=str))
    except OSError:
        return None
    return str(path)


def _history_budget(meta_path: str | None) -> int:
    """How much of the conversation aider keeps verbatim before summarising it away.

    aider caps it at min(max(window/16, 1024), 8192) tokens (models.py:346), and 1024 for an id
    litellm has no record of, which is most of this catalog. Past that cap the restored history is
    SUMMARISED by a model call on every turn, and the summary is lossy: measured in the console
    matrix (hr-test, 2026-09-18), after four short turns the fifth could no longer say what the
    first message asked for, on ids that answered the same question one turn earlier. The other
    bases keep the whole transcript until the window is near full; aider gets the same here.
    Half the window when the record says it, else HR_AIDER_HISTORY_TOKENS, 96,000, which fits the
    128k windows at the small end of the catalog with the map, the doc and a reply beside it."""
    fallback = int(os.environ.get("HR_AIDER_HISTORY_TOKENS", "96000"))
    if not meta_path:
        return fallback
    try:
        record = next(iter(json.loads(pathlib.Path(meta_path).read_text()).values()))
        window = int(record.get("max_input_tokens") or 0)
    except (OSError, ValueError, StopIteration, AttributeError, TypeError):
        return fallback
    return max(window // 2, 8192) if window else fallback


def main() -> int:
    job = json.loads(sys.argv[1])
    cwd = job.get("cwd") or os.getcwd()
    os.chdir(cwd)

    # The repo-map tags cache is `Path(root) / RepoMap.TAGS_CACHE_DIR` with no CLI flag, so the
    # stock value drops a `.aider.tags.cache.v4/` directory in the workspace ROOT — which this
    # product collects and hands back to the user as a produced file on every turn. Under .harness/
    # it is excluded by _PRODUCED_EXCLUDE_PREFIX and still checkpointed. Set BEFORE any Coder is
    # constructed, because RepoMap reads it in __init__.
    from aider.repomap import RepoMap
    RepoMap.TAGS_CACHE_DIR = ".harness/aider/tags.cache.v4"
    pathlib.Path(cwd, ".harness", "aider").mkdir(parents=True, exist_ok=True)

    from aider.main import main as aider_main

    hist = pathlib.Path(cwd, ".harness", "aider")
    argv = [
        "--model", job["model"],
        # The edit format decides whether a skill's script can run AT ALL: shell commands are
        # extracted in editblock_coder.get_edits(), and wholefile/udiff/patch never populate
        # shell_commands, so a ```bash block is inert on those formats. Pinned, not left to the
        # per-model default.
        "--edit-format", "diff",
        "--yes-always",
        "--no-pretty", "--no-fancy-input", "--no-stream",
        "--no-check-update", "--no-show-release-notes", "--no-show-model-warnings",
        "--no-analytics",
        # WITHOUT THIS A TURN CAN HANG FOREVER. aider's --timeout defaults to None, so a provider
        # that accepts the connection and never finishes the stream leaves the API call waiting with
        # no bound; aider's own retry loop cannot help, because it only fires on an exception and is
        # itself bounded (retry_delay doubles until it passes RETRY_TIMEOUT=60, ~63s in total).
        # Measured in the support matrix's vercel column: single scenarios ran 3,621s, 6,040s,
        # 16,071s and 27,360s — against 7-30s for the same scenarios on a healthy call — and only
        # the runner's 6-hour MAX_TURN_SECONDS eventually killed them. Every other backend surfaced
        # the same provider flakiness as a fast error ("Upstream stream ended before terminal
        # chunk"); on aider it was an unbounded wait.
        "--timeout", os.environ.get("HR_AIDER_TIMEOUT", "300"),
        # The workspace is this product's checkpoint repo. aider committing into it would interleave
        # its commits with the harness's own, so aider keeps the repo map and leaves committing to
        # the harness. --no-gitignore stops it appending .aider* patterns to the .gitignore the
        # runner writes and owns.
        "--no-auto-commits", "--no-dirty-commits", "--no-gitignore",
        "--chat-history-file", str(hist / "chat.history.md"),
        "--input-history-file", str(hist / "input.history"),
        # aider's ONLY continuation mechanism: it replays that file into the context. Passed on
        # EVERY turn, not just a resume — on a first turn the file does not exist and aider starts
        # fresh — and the file travels in the checkpoint, which is what lets a follow-up after a
        # sandbox recycle still know what was said. Without it every aider turn is a new thread.
        "--restore-chat-history",
    ]
    meta = _write_model_metadata(cwd, job["model"])
    if meta:
        argv += ["--model-metadata-file", meta]
    argv += ["--max-chat-history-tokens", str(_history_budget(meta))]
    # aider's URL scrape (a URL in the user's message is fetched into the chat after a
    # confirmation) stays off: the web is reached through a shell command like everything else,
    # under the one gate, and the catalog lists no separate Web Fetch tool for that reason.
    argv += ["--no-detect-urls"]
    for path in job.get("read_files") or []:
        argv += ["--read", path]

    coder = aider_main(argv, input=None, output=None, return_coder=True)
    if not hasattr(coder, "run_stream"):
        _emit("error", {"text": f"aider did not return a coder (exit {coder!r})"})
        return 1

    # THE OPERATOR'S STEP BUDGET. aider has no CLI flag for it: its loop is Coder.max_reflections,
    # a class attribute defaulting to 3, and the driver holds the object. Unlike kimi (1000 steps)
    # and openhands (500 iterations) aider's default is already small, so this is about honouring a
    # budget that was set rather than about bounding a runaway — but a budget the caller set and the
    # backend ignores is the kind of quiet lie this repo treats as a defect.
    budget = job.get("max_turns")
    if budget:
        coder.max_reflections = max(1, int(budget))

    disabled = job.get("tools_disabled") or []
    gate = _Gate(disabled)
    _install(coder, gate)
    _run_shell_commands_reporting(coder, gate, reflect=bool(job.get("reflect_shell_output", True)))

    _emit("init", {"model": coder.main_model.name, "edit_format": coder.edit_format})
    try:
        _run_turn(coder, job["prompt"])
    except Exception as exc:  # noqa: BLE001 — the turn's failure is the product here, not a crash
        _emit("error", {"text": f"{type(exc).__name__}: {exc}"})
        _emit("result", {"final": "", "ok": False, "edited": [], "reason": str(exc)[:500]})
        return 1

    # usage_report is None when no completion came back — the in-process failure signal that
    # stdout cannot give. num_error_outputs counts what reached io.tool_error this turn.
    failed = coder.usage_report is None or int(getattr(coder.io, "num_error_outputs", 0) or 0) > 0
    _emit("result", {
        "final": coder.partial_response_content or "",
        "ok": not failed,
        "edited": sorted(coder.aider_edited_files or []),
        "shell_calls": gate.calls,
        "usage_report": coder.usage_report,
        "seconds": round(time.time() - _T0, 2),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
