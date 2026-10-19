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

import codecs
import contextlib
import copy
import json
import os
import pathlib
import re
import subprocess
import sys
import time

_T0 = time.time()

# A SEARCH/REPLACE block as aider's editblock format writes it: the file name alone on the line
# before the fence, the fence (with or without a language), the three markers. The markers'
# lengths follow editblock_coder.py (5 to 9 characters). This is aider's wire format for an edit,
# and the edit is reported as a card of its own; the prose around the block is the answer.
# The file name sits on the line before the fence or on the first line inside it; aider's
# parser takes both (editblock_coder.find_filename), and gpt-5.5 writes the second
# ("```python\nbuild_sfo_one_pager.py\n<<<<<<< SEARCH", hr-test 2026-09-19).
# Fences are three OR MORE backticks: aider's own parser takes any length (a block whose content
# holds ``` is fenced with ````), and gpt-5.4 closes with four. A stripper that took exactly three
# left the fourth behind as the whole answer (an answer card reading "`", hosted 2026-09-19).
_EDIT_BLOCK = re.compile(r"(?:^\S+\n)?`{3,}[^\n]*\n(?:\S+\n)?<{5,9} SEARCH\n.*?^>{5,9} REPLACE\n`{3,}[ \t]*\n?",
                         re.S | re.M)


# `hr-mcp call <server> <tool>` wherever it stands in COMMAND position: at the start of the line
# or after &&, ||, ;, |, ( or a backtick, by its bare name or a path ending in it. Not after a
# plain space, so `echo hr-mcp call x y` stays the prose it is. Server and tool are one shell
# word each.
_HR_MCP_CALL = re.compile(r"(?:^|[\n;&|(`])\s*(?:\S*/)?hr-mcp\s+call\s+([^\s;&|)`'\"]+)\s+([^\s;&|)`'\"]+)",
                          re.M)


# The fences editblock_coder.py:452 extracts shell commands from. Every such block becomes a
# shell_decision card (approved or refused), so the prose does not repeat it.
_SHELL_FENCES = ("```bash", "```sh", "```shell", "```cmd", "```batch", "```powershell", "```ps1",
                 "```zsh", "```fish", "```ksh", "```csh", "```tcsh")


def _strip_shell_blocks(text: str) -> str:
    """Drop the shell blocks the way aider reads them: a block opens on a shell fence and closes on
    the next line that STARTS with a fence, whatever follows on that line (a model that writes
    "```An improved style…" has closed the block and started a sentence; aider treats it so,
    editblock_coder.py:478, and the sentence is kept here)."""
    out, lines, i = [], (text or "").splitlines(), 0
    while i < len(lines):
        line = lines[i]
        # a fence of any length, read as three; a line that does not start with one is prose, even
        # when it starts with a shell's name ("bash build.sh" in an answer is not a block)
        opener = ("```" + line.strip().lstrip("`")) if line.strip().startswith("```") else ""
        if opener.strip() in _SHELL_FENCES or any(opener.startswith(f + " ") for f in _SHELL_FENCES):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            if i < len(lines):
                rest = lines[i].strip().lstrip("`").strip()
                if rest:
                    out.append(rest)
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def strip_edit_blocks(text: str) -> str:
    return _strip_shell_blocks(_EDIT_BLOCK.sub("", text or "")).strip()


NO_ANSWER = "The model wrote only its reasoning; there was no answer this turn."


def _after_answer_banner(display: str) -> str:
    """The answer half of aider's display string, or the statement that the model wrote none.

    This is the fallback when `partial_response_content` is empty, and `remove_reasoning_content`
    cannot serve it: that helper looks for `<tag>`/`</tag>`, and `replace_reasoning_tags` has
    already rewritten them into the `► **THINKING**` / `► **ANSWER**` furniture (reasoning_tags.py:8-11)
    that the reader then saw as the answer. MEASURED on kimi-k3, about one aider turn in three
    returned reasoning and no content at all (#395), so the furniture is what came back. Everything
    after aider's own ANSWER banner IS the answer; when nothing follows, the model wrote none and
    this says so rather than quoting the banner. A display string with no banner at all is some other
    call site off the send path and still reports what it passed, as it did before this helper.
    """
    try:
        from aider.reasoning_tags import REASONING_END
    except Exception:
        return display
    if REASONING_END not in display:
        return display
    return display.split(REASONING_END)[-1].strip() or NO_ANSWER


def is_text_file(path: str, sniff: int = 65536) -> bool:
    """Whether aider could read this file as text. aider adds a file the model names and reads it
    as UTF-8; a binary one (a .pptx the model was asked to restyle, 2026-09-19 on hr-test) fails
    with "Use --encoding to set the unicode encoding.", is dropped, and is added again on the next
    mention, an error and a reflection each time. Refusing the add up front is what aider itself
    does when the operator answers no: the name goes on ignore_mentions and is not asked again."""
    try:
        with open(path, "rb") as f:
            head = f.read(sniff)
    except OSError:
        return False
    if b"\x00" in head:
        return False
    try:
        # A cut inside a multi-byte sequence at the sniff boundary is not a binary file, so a head
        # that filled the sniff may end mid-character. A file read whole may not: dropping its last
        # bytes passed any file of four bytes or fewer, and any whose only bad byte was near its end.
        codecs.getincrementaldecoder("utf-8")().decode(head, final=len(head) < sniff)
    except UnicodeDecodeError:
        return False
    return True


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    sys.stdout.flush()


# aider's two confirmations that name a file the model wants in the chat or wants to edit.
_FILE_PROMPTS = ("Add file to the chat?", "Allow edits to file that has not been added to the chat?")


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
        # True while the last thing that happened was an error: set by tool_error, cleared by the
        # next assistant output. What decides whether the turn failed (see main).
        self.error_after_output = False

    def mcp_calls_in(self, command: str) -> list[tuple[str, str]]:
        """Every ('server', 'tool') an hr-mcp call in this command names, in order.

        `hr-mcp call <server> <tool> [--params …]` is the form the runner documents to the model,
        so recognising it is reading our own contract back; `hr-mcp tools <server>` is discovery,
        not a call, and is deliberately not matched. The WHOLE command is scanned, not its first
        words: with a tool disabled, gpt-5.4 proposed `hr-mcp tools probe && hr-mcp call probe
        probe_sse` and a gate that read argv[0..3] saw a discovery and let the call through
        (hr-test, 2026-09-18). The bridge refuses a disabled tool as well, by name, whatever the
        shell around it looks like; this gate is what names the call in the turn record."""
        return [(m.group(1), m.group(2)) for m in _HR_MCP_CALL.finditer(command)]

    def decide(self, command: str) -> tuple[bool, str, str]:
        """(approved, tool_name, reason). tool_name is what the turn record will call this."""
        calls = self.mcp_calls_in(command)
        if calls:
            for server, tool in calls:
                name = f"{server}.{tool}"
                for d in (tool.lower(), name.lower()):
                    if d in self.disabled:
                        return False, name, f"the harness disabled the tool '{tool}'"
            server, tool = calls[0]
            return True, f"{server}.{tool}", ""
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
        # An empty content field is the only case aider's decorated display string may be shown for;
        # it goes through the banner's own marker rather than being handed over whole (#395).
        gate.error_after_output = False
        _emit("text", {"text": strip_edit_blocks(body or _after_answer_banner(str(message)))})
        return orig_assistant(message, pretty)

    def tool_error(message="", strip=True):
        # A REAL failure lands here and nowhere else. This is the whole reason the driver exists:
        # on stdout this text and the model's own prose are the same bytes.
        gate.error_after_output = True
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
        # A file the model named, which aider offers to add to the chat (base_coder.py:1773), or
        # wrote an edit block for without it being in the chat (allowed_to_edit). Binary files
        # are refused at both: aider reads a chat file as UTF-8 text, and a .pptx or an image
        # fails that read every time it is mentioned; an edit block aimed at one reads it the
        # same way and then dies on its own None content (`'NoneType' object has no attribute
        # 'splitlines'`, hr-test 2026-09-19: gpt-5.5 had built the deck with officecli and put
        # its closing answer inside a SEARCH/REPLACE block for the .pptx). The model works on
        # such files with commands, as the doc says, and the reflection below tells it so.
        if question in _FILE_PROMPTS and subject:
            path = str(subject) if os.path.isabs(str(subject)) else os.path.join(coder.root, str(subject))
            if not is_text_file(path):
                _emit("warning", {"text": f"{subject} is not a text file and stays out of the chat"})
                # aider's prompt tells the model to ask the user for the file and stop; when the
                # user says no, a person types what to do instead. Nobody is at that prompt here,
                # so the answer goes back as a reflection and the turn goes on (measured: without
                # it, "improve the ppt style" ended on "Please add this file to the chat").
                note = (f"`{subject}` is a binary file: it cannot be added to the chat or edited "
                        "with a SEARCH/REPLACE block. Inspect and change it with shell commands in "
                        "a ```bash block (the installed skills cover documents, decks, "
                        "spreadsheets and PDFs), then report what you did.")
                coder.reflected_message = ((coder.reflected_message + "\n\n") if coder.reflected_message else "") + note
                return False
        return orig_confirm(question, default=default, subject=subject,
                            explicit_yes_required=explicit_yes_required, group=group,
                            allow_never=allow_never)

    io.assistant_output = assistant_output
    io.tool_error = tool_error
    io.tool_warning = tool_warning
    io.confirm_ask = confirm_ask


REFLECT_ASK = ("Continue the task with this output. If more commands or edits are needed, propose "
               "them now; otherwise write your answer for the user, stating what the output shows.")


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
            # With an ask, as aider's own lint and test reflections carry one ("Fix any errors
            # below"): the bare output reflected as the next message got "Ok" from gpt-5.4 after
            # the browser column's tool calls, and the person's answer was the plan plus "Ok"
            # (hosted, 2026-09-28).
            coder.reflected_message = str(out).rstrip() + "\n\n" + REFLECT_ASK
        return out

    coder.run_shell_commands = wrapped


# A reply that announces work instead of doing it: "I'll create…", "Let me…", "Sure, I will…".
# Anchored at the start, after an optional acknowledgement, so an answer that happens to contain
# the words ("The file I'll need is…") is not one. The apostrophe is either kind: gpt-5.4 writes
# "I’ll open the page in the browser" with the typographic one, and a match on the straight one
# alone let that turn end with the plan and nothing done (hr-test 0.25.13, 2026-09-28).
_ANNOUNCES = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|sure|certainly|got it|understood|alright|right)[,.!:]?\s*)?"
    r"(?:i(?:['’]ll| will| am going to|['’]m going to| can go ahead| (?:still |also )?need to)|let me|"
    r"first,? i(?:['’]ll| will)|here(?:['’]s| is) (?:the|my) plan)\b", re.I)
# A reply that stops short and says so in a paragraph of its own: "To complete the task, I still
# need to click the link" after the first browser output (gpt-5.4, hr-test 0.25.13, 2026-09-28).
_STOPS_SHORT = re.compile(r"(?:^|\n)\s*to (?:complete|finish) (?:the|this) task,?\s*i (?:still |also )?need to\b", re.I)
# A reply that asks the person something: a "?" ending a phrase, not one inside a URL's query.
_ASKS_PERSON = re.compile(r"\?(?=[\s)\]*_\"'”]|\Z)")
NUDGE = ("Nothing was run or edited. If the task needs files or commands, produce them now in "
         "this reply; otherwise give your final answer.")


def _announces_without_acting(text: str) -> bool:
    return bool(_ANNOUNCES.match(text or "") or _STOPS_SHORT.search(text or ""))


# A request that names a file to create or write: "Create a file named hello-aider.txt containing
# exactly the word HELLO, then reply DONE." gpt-5.4 answered that with "DONE", 4 output tokens and
# no file, 4 of 4, and gpt-5.5 the same; without ", then reply DONE" gpt-5.4 wrote it 3 of 3
# (issue #379, 2026-10-04). aider gives the model one response per turn and the edit block IS that
# response, so a request ending on a word to send back gets the word. Keyed on the REQUEST, since
# the reply ("DONE") reads as a finished answer: the verb opens a clause (the start, after a
# sentence or a comma, "and", "then", "now", "please", "can you") and a file name with a lettered
# extension follows in the same sentence. So "how do I create config.yaml?" and "what would
# hello.txt contain?" are questions and never match, and "Reply with exactly: M1-gpt-5.4" names
# no file (5.4 is a version, not an extension).
_CREATE_VERB = re.compile(
    r"(?:^|[.;:!?]\s+|\n\s*|,\s*|\b(?:and|then|please|kindly|now|also|just|first)\s+"
    r"|\b(?:can|could|would|will) you\s+(?:please\s+)?|\bi (?:want|need) you to\s+)"
    r"(?:create|write|make|save|generate|produce|build|draft|put|store|export)\b"
    r"(?!\s+(?:sure|certain)\b)", re.I)                 # "make sure the output goes to x.json"
# The rest of the verb's clause, bounded so a long unpunctuated paste costs a short scan: a dot
# followed by a letter or a slash is inside a file name, not the sentence's end. The clause ends
# where it starts describing what the thing does: "write a script that parses config.yaml", "write
# a script to parse config.yaml" ask for a script, not for config.yaml.
_SENTENCE_END = re.compile(
    r"[.!?](?![\w/])|\n|\b(?:that|which|who|whose|because|while|if)\b"
    r"|\bto\s+(?!(?:the|a|an|my|your|this|its|their|our)\b)[a-z]+\b(?![\w./`-])", re.I)
_SCAN = 300
# A name ending in a text file type, whole: "report.final.md", "notes.v2.txt". The types are
# listed, so a module or a method ("subprocess.run", "requests.Session") is not a name, and they are
# text, since the nudge asks for an edit block and a .pptx or .png written that way is a corrupt
# file. Or a lowercase dotfile (".env", not ".NET"), or a file named without an extension
# ("Dockerfile"). A leading "./" is the workspace itself.
_FILE_TYPES = (
    "txt|md|markdown|rst|adoc|tex|bib|log|py|ipynb|js|mjs|cjs|ts|tsx|jsx|vue|svelte|astro|json|"
    "jsonl|yaml|yml|toml|ini|cfg|conf|env|csv|tsv|xml|html|htm|css|scss|sass|less|sql|sh|bash|zsh|"
    "fish|ps1|bat|rb|go|rs|java|kt|kts|swift|c|h|cc|cpp|hpp|cs|php|pl|lua|r|jl|dart|scala|ex|exs|"
    "erl|hs|ml|proto|graphql|gql|tf|hcl|patch|diff|svg|pem|crt")
_FILE_NAME = re.compile(
    r"(?<![\w/.@-])(?:\./)?((?:[\w-]+/)*(?:[\w-]+(?:\.[\w-]+)*\.(?i:" + _FILE_TYPES + r")|\.[a-z][a-z0-9_.-]*"
    r"|(?:Dockerfile|Makefile|Procfile|Gemfile|Rakefile|Jenkinsfile|Vagrantfile|Containerfile)))"
    r"(?![\w/@.-]*[\w/@-])")
# A file the request reads from, or that the thing asked for is for, is not one it asks for:
# "write a summary of `notes.md`", "write a scraper for wikipedia.org" (a site whose ending is also
# a file type: .org is left off the list, and .sh, .rs, .go, .pl, .ml and .cs are code). A file
# that exists is left out below, which covers "export the table in data.csv" without refusing
# "save it in out.md" or "a project with main.py and utils.py".
_READS_FROM = re.compile(r"\b(?:of|from|about|than|for)\s*[`'\"]?\Z", re.I)
# A framework's name is not a file: "a Next.js app". The frameworks are named, so "create App.js"
# is still a file.
_NOT_A_FILE = re.compile(
    r"(?:Node|Next|Nuxt|Vue|React|Angular|Ember|Backbone|Express|Nest|Three|D3|Chart|Moment|Alpine|"
    r"Solid|Svelte|Deno|Bun)\.js\Z", re.I)
_WALK_CAP = 200000


def _workspace_names(root: str) -> "set | None":
    """Every file in the workspace, by path and by bare name, read once per turn. "Write tests for
    utils.py" means src/utils.py when that is where it is, so a bare name anywhere is that file.
    git's own list is complete in a tree of any size (the workspace is aider's repo); without git,
    a walk blind to dot-folders and node_modules, which a request does not mean. None when neither
    can say: then a bare name counts as present, since no nudge is the turn as it was and a wrong
    one makes a stray file."""
    paths = _workspace_paths(root)
    return None if paths is None else paths | {p.rsplit("/", 1)[-1] for p in paths}


def _workspace_paths(root: str) -> "set | None":
    """The workspace's files by path, as _workspace_names reads them; None when neither git nor a
    bounded walk can say."""
    try:
        out = subprocess.run(["git", "-c", "safe.directory=*", "-C", root, "ls-files", "-z",
                              "--cached", "--others", "--exclude-standard"],
                             capture_output=True, timeout=10, check=True).stdout
        paths = [p for p in out.decode("utf-8", "replace").split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        paths = []
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x != "node_modules"]
            paths += [os.path.relpath(os.path.join(d, f), root) for f in files]
            if len(paths) > _WALK_CAP:
                return None
    return set(paths)


def _edits_sentence(edited: list, before: "set | None") -> str:
    """What a turn changed, said from the edits themselves, for a turn whose model wrote only edit
    blocks: its answer is empty once they are cards. Measured 2026-10-19 on "Create a file named
    hello.txt containing hi, then say done.": the reply was the edit block alone in 6 of 24 runs
    (gpt-5.4 4 of 6), and 11 of 24 on 0.35.2. A file absent from the workspace before the turn was
    created; one that was there was edited. With no listing to tell them apart, every file is
    "edited", which a written file also is. Names up to two files, then counts; nothing else."""
    created = sorted(p for p in edited if before is not None and p not in before)
    changed = sorted(p for p in edited if p not in created)

    def files(ps: list) -> str:
        return " and ".join(ps) if len(ps) <= 2 else f"{len(ps)} files"
    if created and changed:
        return f"Created {files(created)}{', and' if len(created) == 2 else ' and'} edited {files(changed)}."
    return f"Created {files(created)}." if created else f"Edited {files(changed)}."


def _exists_in(root: str, name: str, names: "set | None") -> bool:
    """The name is in the workspace already: at its path, or for a bare name anywhere in it."""
    if os.path.exists(os.path.join(root, name)):
        return True
    if "/" in name:
        return False
    return names is None or name in names


def _files_asked_for(prompt: str, root: str = ".", names: "set | None | bool" = False) -> list:
    """The files this turn's request asks to have created or written that do not exist yet.

    A file that exists is left out: the nudge's new-file block would append to it, and a file an
    earlier turn already made is not this turn's to make again. Earlier turns the gateway puts
    ahead of the request (for a backend that lost its history) are left out the same way."""
    text = prompt or ""
    if names is False:
        names = _workspace_names(root)
    if text.startswith("<conversation_so_far>\n"):
        text = text.rpartition("</conversation_so_far>\n\n")[2]
    found: list = []
    for verb in _CREATE_VERB.finditer(text):
        rest = text[verb.end():verb.end() + _SCAN]
        stop = _SENTENCE_END.search(rest)
        # a name the window's cut runs through is half a name
        cut = not stop and verb.end() + _SCAN < len(text)
        rest = rest[:stop.start()] if stop else rest
        for m in _FILE_NAME.finditer(rest):
            name = m.group(1)
            if ((cut and m.end() == len(rest)) or _NOT_A_FILE.match(name)
                    or _READS_FROM.search(rest[:m.start()])
                    or name in found or _exists_in(root, name, names)):
                continue
            found.append(name)
    return found


def _file_nudge(names: list) -> str:
    listed = ", ".join(f"`{n}`" for n in names)
    one = len(names) == 1
    return (f"The request asks for {listed}, and {'it is' if one else 'they are'} not written yet. "
            f"Write {'it' if one else 'them'} now in this reply with a SEARCH/REPLACE block "
            "each: the path, an empty SEARCH section and the contents in the REPLACE section. A "
            "new file does not need to be added to the chat first. Then give the reply the request "
            "asks for.")


# A request that asks for words back once the work is done: "Create a file named hello.txt
# containing hi, then say done." gpt-5.4-mini answered it with the edit block and nothing else (21
# output tokens, its chat history shows no other words; the runner read-back on 0.35.3's driver,
# 2026-10-18): the file was written and the person's answer was the driver's "The task ended
# without a written answer" sentence. aider gives the model one response per turn, and the block
# was that response, the mirror of #379's "DONE" with no file. Keyed on the request, like the file
# nudge: the verb opens a clause, so "the answer is in notes.md" asks for nothing. ENGLISH ONLY: the
# openers are English words, so a request in another language never gets this nudge. Such a turn
# still ends with words, the sentence _edits_sentence builds from its edits, which is also the answer
# whenever this nudge is not sent or was already spent on another one this turn.
_ASKS_REPLY = re.compile(
    r"(?:^|[.;:!?]\s+|\n\s*|,\s*|\b(?:and|then|please|now|also|just|finally|afterwards)\s+)"
    r"(?:say|reply|respond|answer|confirm|report|tell me|let me know)\b", re.I)
REPLY_NUDGE = ("What this turn wrote and ran is done, so do not write or run it again. Now give the "
               "reply the request asks for, in words, with no SEARCH/REPLACE block and no command.")


def _asks_for_reply(prompt: str) -> bool:
    """Whether this turn's request asks for words back (earlier turns put ahead of it are not it)."""
    text = prompt or ""
    if text.startswith("<conversation_so_far>\n"):
        text = text.rpartition("</conversation_so_far>\n\n")[2]
    return bool(_ASKS_REPLY.search(text))


NEW_FILE_NOTE = ("If the request asks for a new file, it needs no adding to the chat: write it with "
                 "a SEARCH/REPLACE block that has its path, an empty SEARCH section and the contents "
                 "in REPLACE, then give the reply the request asks for. A question about a file is "
                 "answered in words, without creating it.")


def _new_files_need_no_add(coder) -> None:
    """aider's word for a chat with no files in it is "I am not sharing any files that you can
    edit yet.", sent as the user every turn. gpt-5.4-mini took it at its word (#379): asked to
    create hello-aider.txt it answered "I can't create or edit files yet because you haven't
    shared any editable files in the chat", and said it again after the nudge, and after a second
    nudge tried for measuring. With the workspace notes' line and the nudge it wrote the file 12 of
    17 times and 6 answered that way; with this message as well, 21 of 24 and none (2026-10-18).

    When the workspace has files aider sends another: "Don't try and edit any existing code without
    asking me to add the files to the chat! ... then stop so I can add them", answered for the
    model with "I will suggest which files need to be edited and then stop and wait for your
    approval". With notes.md and src/app.py in the workspace gpt-5.4-mini wrote the file 1 of 6
    (0 of 3 on the build before this change). That one keeps its rule for existing files, which
    the driver's adding of named files answers, and says a new file is written directly: 4 of 6,
    gpt-5.4 2 of 2, and appending to notes.md still worked (gpt-5.4 2 of 2). The prompts object is
    the coder class's own, shared, so it is copied first."""
    prompts = copy.copy(coder.gpt_prompts)
    prompts.files_no_full_files = "No files are in the chat yet. " + NEW_FILE_NOTE
    if getattr(prompts, "files_no_full_files_with_repo_map", None):
        prompts.files_no_full_files_with_repo_map = (
            "No files are in the chat yet. " + NEW_FILE_NOTE + "\n"
            "An existing file has to be in the chat before you edit it: to change existing files, "
            "name the ones that need changes and stop, and they will be added. Name only files "
            "that need to be edited, not ones that are only context.\n")
        prompts.files_no_full_files_with_repo_map_reply = (
            "Ok. If a request asks for a new file I will write it directly; for existing files I "
            "will name the ones that need changes and stop so they can be added.")
    coder.gpt_prompts = prompts


def _repo_map_after_the_conversation(coder) -> None:
    """THE CONVERSATION STARTS WITH WHAT THE USER SAID, with files in the workspace as without.
    aider sends the repo map as a user message, answered for the model with "Ok, I won't try and
    edit those files without asking first.", AHEAD of the restored conversation (format_chat_chunks
    puts repo before done), so once the workspace holds a file the first exchange the model sees is
    aider's. Asked what word the first message of the task asked for, gpt-5.4 answered "Ok" or
    "exactly" 5 of 6 times after it had written hello-aider.txt, and "M1-gpt-5.4" 6 of 6 with the
    map moved (0.35.3-rc.4, 2026-10-18). The examples were moved out of the conversation for the
    same reason. The map now opens the files message that follows
    the conversation, where the note on what is in the chat already sits: what the model is told
    about the workspace is the same, only its place moves."""
    repo_messages = coder.get_repo_messages
    files_messages = coder.get_chat_files_messages

    def chat_files():
        files, repo = files_messages(), repo_messages()
        if not repo:
            return files
        if files and files[0]["role"] == "user" and isinstance(files[0]["content"], str):
            return [dict(files[0], content=repo[0]["content"] + "\n\n" + files[0]["content"])] + files[1:]
        return repo + files

    coder.get_repo_messages = lambda: []
    coder.get_chat_files_messages = chat_files


def _run_turn(coder, prompt: str, gate: "_Gate | None" = None) -> None:
    """aider's own reflection loop (Coder.run_one), driven directly.

    run_stream is run_one without the loop: it sends ONE message and stops. Reproducing the loop
    here is what lets a reflection — aider's mechanism for "there is more to do before this turn
    ends", used by its lint and test paths — carry a shell command's output back to the model in the
    SAME turn. The bound is aider's own max_reflections, not one invented here.

    ONE NUDGE when a pass announced work and did none. aider reflects only on something to feed
    back (a command's output, a lint result); a reply that says "I'll create a one-page deck" and
    proposes neither an edit nor a command ends the turn with nothing done, because at a terminal
    the person would type "go ahead" (gpt-5.5 on the hosted service, 2026-09-19: that sentence
    and zero commands; gpt-5.4 twice ended after one message). The nudge is that "go ahead", once
    per turn, only when the reply reads as an announcement, so a plain answer never pays for a
    second call. Counted against aider's max_reflections like any reflection.

    The same one nudge when the request names a file to create or write that the turn has not
    written (#379): the reply ("DONE") reads as an answer, so the request decides. It names the
    files and asks for the edit blocks, since the general nudge's "otherwise give your final
    answer" is the way out the model already took. A reply that asks the person
    something is not nudged. A command counts only by what it left on disk: a turn that read a
    skill with `cat` and answered "DONE" made no file.

    And the same one nudge the other way round: a request that asks for words back ("then say
    done") answered by a pass that edited or ran something and said nothing besides. Without it the
    answer is the driver's "ended without a written answer" sentence over a task that is done. One
    nudge per turn in every case."""
    coder.io.user_input(prompt)
    coder.init_before_message()
    message = prompt
    reflections = 0
    reported: set = set()
    nudged = False
    root = getattr(coder, "root", None) or "."
    wanted = _files_asked_for(prompt, root)
    wants_reply = _asks_for_reply(prompt)
    while message:
        coder.reflected_message = None
        calls_before = len(gate.calls) if gate is not None else 0
        list(coder.send_message(message))
        # aider_edited_files accumulates over the turn; what this pass added is reported now, so
        # the cards sit beside the prose that produced them.
        edited = sorted(set(coder.aider_edited_files or []) - reported)
        if edited:
            reported.update(edited)
            _emit("edits", {"files": edited})
        acted = bool(edited) or (gate is not None and len(gate.calls) > calls_before)
        if not coder.reflected_message and not nudged:
            reply = (coder.partial_response_content or "").rstrip()
            # Asked for and still not at its path: a turn that wrote a.txt of "a.txt and b.txt" is
            # nudged for b.txt alone, and a command that wrote the file left it there. A reply that
            # asks the person something is waiting for them, and an empty one is a failed call
            # (a provider error, a timeout) that a second call would only repeat.
            missing = [n for n in wanted if n not in reported
                       and not os.path.exists(os.path.join(root, n))]
            if missing and reply and not _ASKS_PERSON.search(strip_edit_blocks(reply)):
                nudged = True
                coder.reflected_message = _file_nudge(missing)
            elif not acted and _announces_without_acting(reply):
                nudged = True
                coder.reflected_message = NUDGE
            elif acted and reply and wants_reply and not strip_edit_blocks(reply):
                nudged = True
                coder.reflected_message = REPLY_NUDGE
        if not coder.reflected_message:
            break
        if reflections >= coder.max_reflections:
            _emit("warning", {"text": f"stopped after {coder.max_reflections} reflections"})
            break
        reflections += 1
        message = coder.reflected_message
        # A reflection is a user message the model sees, and aider writes only the turn's first
        # one to its chat history, which is what a recycled sandbox restores the conversation
        # from. Logged here, the restored history is the one the model saw: on 0.35.3-rc.1, after
        # a nudged turn and a recycle, the history held two replies in a row with no message
        # between, and gpt-5.4-mini answered "what did my first message ask for" with "HELLO".
        coder.io.user_input(message)


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
    # The harness's own files stay out of aider's repo map: .harness/ holds the skill bundles
    # (their scripts would otherwise be summarised into every request), aider's own state and the
    # MCP shim, none of which is the user's project. The map then describes the task's files
    # alone, and an empty workspace gets no map at all.
    ignore = hist / "aiderignore"
    ignore.write_text(".harness/\nAGENTS.md\n.gitignore\n")
    argv = [
        "--aiderignore", str(ignore),
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
    coder = aider_main(argv, input=None, output=None, return_coder=True)
    if not hasattr(coder, "run_stream"):
        _emit("error", {"text": f"aider did not return a coder (exit {coder!r})"})
        return 1

    # THE HARNESS'S INSTRUCTIONS ARE SYSTEM-LEVEL, as on every other base. aider composes its own
    # system message and its CLI offers no way in, but the Model object it built carries a
    # `system_prompt_prefix` that format_chat_chunks puts ahead of that message (base_coder.py:1229,
    # aider's own hook for "Formatting re-enabled." and "/no_think"). The agent doc goes there.
    # The alternative, --read, sent the doc as a USER message ("Here are some READ ONLY files,
    # provided for your reference") ahead of the conversation, so the model's first user message
    # was aider's preamble: asked what the first message of the task said, gpt-5.4 answered
    # "reference" (hr-test, 2026-09-18). With the doc in the system message the conversation holds
    # the user's turns and nothing else before them (the repo map, when the workspace has files,
    # is aider's own user-role message and stays).
    prefix = []
    for path in job.get("system_files") or []:
        try:
            prefix.append(pathlib.Path(path).read_text())
        except OSError:
            continue
    if prefix:
        coder.main_model.system_prompt_prefix = (
            "\n\n".join(p.strip() for p in prefix if p.strip()) + "\n\n"
            + (coder.main_model.system_prompt_prefix or ""))

    # THE OPERATOR'S STEP BUDGET. aider has no CLI flag for it: its loop is Coder.max_reflections,
    # a class attribute defaulting to 3, and the driver holds the object. Unlike kimi (1000 steps)
    # and openhands (500 iterations) aider's default is already small, so this is about honouring a
    # budget that was set rather than about bounding a runaway — but a budget the caller set and the
    # backend ignores is the kind of quiet lie this repo treats as a defect.
    budget = job.get("max_turns")
    if budget:
        coder.max_reflections = max(1, int(budget))

    # THE CONVERSATION HOLDS ONLY WHAT THE USER SAID. aider's few-shot examples for the edit
    # format are, by default for most ids, injected as REAL user/assistant turns ahead of the
    # user's own, so the first user message the model sees is "Change get_factorial() to use
    # math.factorial". Asked what the first message of the task asked for, the gpt-5 family
    # answered "Change" (console matrix, hr-test 2026-09-18, once the history was kept intact).
    # aider's own switch folds the examples into the system prompt instead (base_coder.py:1233);
    # a per-model settings file would replace every other setting of the model with the class
    # defaults, so the attribute is set on the object, which is what format_chat_chunks reads.
    coder.main_model.examples_as_sys_msg = True
    _new_files_need_no_add(coder)
    _repo_map_after_the_conversation(coder)
    # NO TEMPERATURE. aider sends `temperature: 0` for every id its settings do not know, and a
    # provider that has retired the field refuses the whole turn: claude-fable-5-1 on TokenRouter
    # answered "`temperature` is deprecated for this model" and the turn died after 171 s of
    # retries (console matrix, hr-test 2026-09-18). No other base sets a temperature; aider's own
    # per-model switch leaves it out.
    coder.main_model.use_temperature = False

    disabled = job.get("tools_disabled") or []
    gate = _Gate(disabled)
    _install(coder, gate)
    _run_shell_commands_reporting(coder, gate, reflect=bool(job.get("reflect_shell_output", True)))

    _emit("init", {"model": coder.main_model.name, "edit_format": coder.edit_format})
    before = _workspace_paths(cwd)        # what was there, so the turn's edits say created or edited
    try:
        _run_turn(coder, job["prompt"], gate)
    except Exception as exc:  # noqa: BLE001 — the turn's failure is the product here, not a crash
        _emit("error", {"text": f"{type(exc).__name__}: {exc}"})
        _emit("result", {"final": "", "ok": False, "edited": [], "reason": str(exc)[:500]})
        return 1

    # usage_report is None when no completion came back — the in-process failure signal that
    # stdout cannot give. Otherwise the turn failed when an error was the LAST thing that
    # happened: a provider refusal ends the turn on io.tool_error with nothing after it. An error
    # the turn recovered from (a file it could not read, an edit block it retried) followed by
    # more of the model's work is not a failed turn: measured 2026-09-19, a restyled .pptx and an
    # edited hello.md were reported FAILED for a decode error twelve commands earlier.
    failed = coder.usage_report is None or gate.error_after_output
    # The result's text is what the gateway stores as the answer, so it is stripped of the
    # edit markup exactly as the text events were; the edits were reported as cards.
    final = strip_edit_blocks(coder.partial_response_content or "")
    if not final.strip() and not failed and (gate.calls or coder.aider_edited_files):
        # A response that was commands or edit blocks and nothing else leaves no answer once the
        # blocks are cards: the model's last word was a command or an edit, and aider gives it no
        # further turn when that printed nothing. Measured on the hosted service (an officecli
        # that was not installed ran seven times and the task ended with no text and no file;
        # gpt-5.4 ended after one edit block). Said as what happened, not as an answer the model
        # gave: the files it changed, by name, or the commands it ran. The same on the hosted service.
        edited = sorted(coder.aider_edited_files or [])
        if edited:
            final = _edits_sentence(edited, before) + (
                " The commands and their output are above." if gate.calls else "")
        else:
            final = ("The task ended without a written answer after running commands. The commands "
                     "and their output are above.")
    _emit("result", {
        "final": final,
        "ok": not failed,
        "edited": sorted(coder.aider_edited_files or []),
        "shell_calls": gate.calls,
        "usage_report": coder.usage_report,
        "seconds": round(time.time() - _T0, 2),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
