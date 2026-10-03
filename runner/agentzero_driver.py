"""One Agent Zero turn, as a runner subprocess.

Spawned per turn by server.py, the same one-process-per-turn contract every other backend keeps: the
runner reads NDJSON off stdout and cancel is a process-group kill. Inside, Agent Zero
(agent0ai/agent-zero, MIT) is DRIVEN IN PROCESS: the driver builds an `AgentContext`, hands it the
turn's message through `context.communicate(UserMessage(...))` and awaits the task — exactly what
Agent Zero's own `/api_message` endpoint does (api/api_message.py), minus the web server around it.

WHY IN PROCESS. Agent Zero has no CLI and no headless mode: it is a Flask/uvicorn web UI shipped as
a Docker image, and its programmatic surfaces (`/api_message`, the A0 connector, ACP) all need that
server running. One server per turn would pay its whole startup (preload, job loop, plugin
watchdogs, a Socket.IO transport) to answer one message. The framework itself is plain Python —
initialize.initialize_agent() builds the config, AgentContext owns the loop — so the driver imports
it and runs the one message. Measured on the pinned v2.13: the import takes ~2 s and a trivial turn
~5 s end to end.

WHAT IS REDIRECTED, AND BY WHICH OF AGENT ZERO'S OWN DOORS. Agent Zero keeps every piece of state
under `<its base dir>/usr` and computes that base from its own `__file__`. The install is shared and
read-only here, so each workspace gets a BASE of its own at .harness/agentzero/base: symlinks to the
install's code directories, and a real `usr/` beside them. Python keeps the symlinked path in
`__file__`, so Agent Zero finds `usr/` in the workspace, and its conversation store
(usr/chats/<id>/chat.json) travels in the checkpoint like every other backend's. Everything else is
configuration Agent Zero reads itself:
  * the model: usr/plugins/_model_config/presets.yaml, provider `other` (OpenAI-compatible) pointed
    at the loopback relay, the key in OTHER_API_KEY — the `<PROVIDER>_API_KEY` name models.py reads;
  * the workdir, MCP servers and update check: `A0_SET_<setting>` environment defaults (settings.py);
  * the tool policy: the _tool_access plugin's config — Agent Zero's own gate, which strips a
    blocked tool from the prompt AND refuses its execution, local and MCP alike;
  * the harness's AGENTS.md: the _promptinclude plugin, pointed at that file name, which puts
    matching workdir files into the system prompt;
  * the environment description: a usr/prompts override of agent.system.main.environment.md, which
    upstream writes for its own Kali container ("agent zero framework is python project in /a0").
Two things are patched rather than configured, both said here so a pin bump re-checks them:
`helpers.files.normalize_a0_path` is made the identity (Agent Zero rewrites every path under its base
dir to `/a0/...`, a directory that exists only in its image, so a skill's path would name a file the
agent's shell cannot open), and `sentence_transformers` is a stub module (models.py imports it at
the top for LOCAL embeddings, which pull torch; the only consumer, the memory plugin, is off).

The event protocol is dsh_driver's: one {"m": method, "p": payload} JSON object per line on stdout,
normalised by _agentzero_to_claude in server.py. Agent Zero prints its own console output with
print(), so fds 1 and 2 are re-pointed at a console log in the workspace scratch for the whole run
and the events go to a duplicate of the real fd 1.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import sys
import time
import types
import uuid

_T0 = time.time()
_OUT = os.fdopen(os.dup(1), "w", buffering=1)   # the event channel; fd 1 itself goes to stderr below


def _emit(method: str, payload) -> None:
    _OUT.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    _OUT.flush()


# The conversation's context id. Constant per workspace, the goose/openhands precedent: the store is
# in the workspace, so the one conversation a workspace holds needs no id minted anywhere else, and a
# follow-up after a sandbox recycle finds it by the same name.
SESSION_ID = "harness"

# The install's top-level entries that are STATE rather than code: never linked into a base, so a
# workspace's usr/ and tmp/ are its own.
_STATE_DIRS = {"usr", "tmp", ".git", ".github"}

# Plugins that cannot work in this sandbox, or that would do work nobody asked for, switched off by
# the plugin's own toggle file (usr/plugins/<name>/.toggle-0). Each one here is a capability NOT
# offered, not a capability hidden:
#   _memory          FAISS + local sentence-transformers embeddings (torch): not installed
#   _document_query  FAISS + unstructured, and it pip-installs liteparse through `uv` at startup
#   _browser         Playwright + a Chromium this image does not carry for this base
#   _office          LibreOffice
#   _desktop         an Xpra/Xfce desktop
#   _a0_connector    remote tools that need Agent Zero's CLI connected to a running server
#   _time_travel     snapshots workspaces inside /a0/usr, a path that exists only in its image
#   _email_integration / _telegram_integration / _whatsapp_integration / _kokoro_tts / _whisper_stt /
#   _oauth / _migrate_agents / _orchestrator: server-side integrations with no place in one turn
DISABLED_PLUGINS = ("_memory", "_document_query", "_browser", "_office", "_desktop", "_a0_connector",
                    "_time_travel", "_email_integration", "_telegram_integration",
                    "_whatsapp_integration", "_kokoro_tts", "_whisper_stt", "_oauth",
                    "_migrate_agents", "_orchestrator")

# Agent Zero's tools, by the names its loader resolves (tools/<name>.py, plugins/*/tools/<name>.py),
# with the canonical id its _tool_access policy keys on: `plugin:<plugin>:<name>` for a plugin's tool,
# `local:<name>` for a core one (helpers/tool_policy._canonical_from_path). The keys are the names
# the catalog offers and the console disables by; the values are every id that name withholds.
#
# `input` IS THE SHELL TOO, so it goes with code_execution_tool and is not offered on its own: it
# "sends keyboard input to an interactive terminal program" by calling CodeExecution with
# runtime=terminal and the text as the command (plugins/_code_execution/tools/input.py), so a model
# denied code_execution_tool could still run any command through it.
TOOLS = {
    "code_execution_tool": ("plugin:_code_execution:code_execution_tool",
                            "plugin:_code_execution:input"),
    "text_editor": ("plugin:_text_editor:text_editor",),
    "call_subordinate": ("local:call_subordinate",),
    "skills_tool": ("local:skills_tool",),
    "parallel": ("local:parallel",),
    "wait": ("local:wait",),
    "goal": ("plugin:_goal:goal",),
}
# Core tools that are always blocked, because they cannot do their job here and a tool the prompt
# lists but that fails every call teaches the model nothing but a detour:
#   search_engine   queries a SearXNG at localhost:55510 that only Agent Zero's image runs
#   document_query  imports faiss, which is not installed
#   scheduler       creates tasks for a job loop that only the web server runs
#   notify_user     notifications for a web UI nobody is watching
#   a2a_chat        dials other agents over Agent Zero's A2A protocol, a network surface of its own
ALWAYS_BLOCKED = ("local:search_engine", "local:document_query", "local:scheduler",
                  "local:notify_user", "local:a2a_chat")


def tool_policy(tools_disabled: list[str] | None) -> dict:
    """The _tool_access config for this turn: custom mode, everything allowed by default, the
    always-blocked core tools and whatever the harness disabled blocked by canonical id.

    An MCP tool is blocked by `mcp:<server>:<tool>` when named that way; a bare MCP tool name is
    handled in mcp_config instead (the server's own `disabled_tools`), since the policy's ids need
    the server. A disabled name that is neither is dropped here, and the gateway only offers the
    names in TOOLS, so nothing reaches here that matches nothing."""
    blocked = list(ALWAYS_BLOCKED)
    for name in tools_disabled or []:
        n = str(name).strip()
        ids = TOOLS.get(n) or ((n,) if n.startswith(("plugin:", "local:", "mcp:")) else ())
        blocked.extend(i for i in ids if i not in blocked)
    return {"mode": "custom", "default": "allow", "mcp_default": "allow",
            "allowed": [], "blocked": blocked}


def mcp_config(servers: list[dict] | None, tools_disabled: list[str] | None = None) -> str:
    """The harness's MCP servers as Agent Zero's `mcp_servers` setting ({"mcpServers": {...}}).

    Agent Zero's own client dials them (helpers/mcp_handler.py: stdio through the MCP SDK, `sse` and
    `streamable-http` by `type`), so this base needs no bridge. The declared transport travels: a
    remote server's `type` is the harness's `transport`, never guessed from the url. A disabled
    tool that is not one of Agent Zero's own goes into every server's `disabled_tools`, which the
    client both hides from the prompt and refuses at call time (MCPServerRemote.call_tool)."""
    local_names = set(TOOLS)
    withheld = sorted({str(x).strip() for x in (tools_disabled or [])
                       if str(x).strip() and str(x).strip() not in local_names
                       and not str(x).startswith(("plugin:", "local:"))})
    out: dict = {}
    for i, sv in enumerate(servers or []):
        if not isinstance(sv, dict):
            continue
        name = str(sv.get("name") or sv.get("id") or f"server{i}")
        entry: dict = {}
        url = str(sv.get("url") or "").strip()
        if url:
            entry["url"] = url
            transport = str(sv.get("transport") or "").lower()
            # An undeclared transport is streamable HTTP, this repo's rule; Agent Zero's own
            # default for a url entry is SSE.
            entry["type"] = "sse" if transport == "sse" else "streamable-http"
            hdrs = sv.get("headers")
            if isinstance(hdrs, dict) and hdrs:
                entry["headers"] = {str(k): str(v) for k, v in hdrs.items()}
        elif sv.get("command"):
            cmd = sv["command"]
            argv = cmd if isinstance(cmd, list) else [str(cmd)]
            entry["command"] = str(argv[0])
            entry["args"] = [str(x) for x in argv[1:]] + [str(x) for x in (sv.get("args") or [])]
            envv = sv.get("env")
            if isinstance(envv, dict) and envv:
                entry["env"] = {str(k): str(v) for k, v in envv.items()}
        else:
            continue
        mine = [w.split(".", 1)[1] if w.startswith(name + ".") else w for w in withheld]
        if mine:
            entry["disabled_tools"] = mine
        out[name] = entry
    return json.dumps({"mcpServers": out})


# The provider call's timeout, in seconds. Agent Zero sets none, so litellm's default applies and an
# endpoint that accepts the connection and never answers held a turn for 900 s with nothing in its
# record (measured: killed at the probe's 900 s alarm, no result). With the retries below that is
# four attempts at most before the reason is reported. 300 s is the read budget
# cheetahclaws and aider run on; passed as the preset's litellm kwargs, Agent Zero's own door for
# per-model call parameters.
PROVIDER_TIMEOUT = int(os.environ.get("HR_AGENTZERO_TIMEOUT", "300") or 300)


def presets(model: str, base_url: str, timeout: int | None = None) -> list[dict]:
    """The one preset every turn runs on: main and utility model both the turn's model, through the
    relay. Provider `other` is Agent Zero's "Other OpenAI compatible" (litellm's openai provider with
    an api_base), so the id reaches the provider as written. The embedding slot names Agent Zero's
    default and is never called: its only consumer, the memory plugin, is off.

    Written on every turn, so a model switch is a new file and not a frozen agent: Agent Zero
    resolves the model from this file at call time (_model_config), and the chat stores no model."""
    timeout = timeout or PROVIDER_TIMEOUT
    slot = {"provider": "other", "name": model, "api_base": base_url,
            "kwargs": {"timeout": timeout, "stream_timeout": timeout,
                       # ONE retry ladder, not three nested ones: the OpenAI client's own two
                       # retries sat under Agent Zero's two transient retries, under its
                       # _error_retry plugin's one — 18 calls for one refusal. Measured with a 5 s
                       # timeout against an endpoint that never answers: 110 s before the reason.
                       "max_retries": 0, "a0_retry_attempts": 1}}
    return [{"name": "Default",
             "chat": {**slot, "ctx_length": 128000, "ctx_history": 0.7, "vision": False},
             "utility": {**slot, "ctx_length": 128000, "ctx_input": 0.7},
             "embedding": {"provider": "huggingface",
                           "name": "sentence-transformers/all-MiniLM-L6-v2",
                           "api_base": "", "kwargs": {}}}]


def environment_prompt(cwd: str) -> str:
    """Replaces upstream's agent.system.main.environment.md, which describes Agent Zero's own Kali
    image (/a0, /opt/venv, root). Every line there is false here and the model acts on it."""
    return ("## Environment\n"
            "you run in a linux sandbox as an unprivileged user, not in a docker image of your own\n"
            f"your working directory is {cwd}; the terminal starts there and relative paths resolve there\n"
            "files you are asked to produce must be written inside the working directory\n"
            "prefer a path relative to the working directory, in your tool calls and when you name a "
            "file to the user: the sandbox path means nothing to them\n"
            "use python3 and the tools already installed; there is no root access\n")


def prepare_base(src: pathlib.Path, home: pathlib.Path, scratch: pathlib.Path) -> pathlib.Path:
    """The workspace's Agent Zero base: every code entry of the install as a symlink, `usr/` real,
    `tmp/` pointing into the workspace scratch (never checkpointed). Idempotent, and it repairs a
    base whose links point at an older install."""
    base = home / "base"
    base.mkdir(parents=True, exist_ok=True)
    wanted = {e.name: e for e in src.iterdir() if e.name not in _STATE_DIRS}
    for entry in base.iterdir():
        if entry.name == "usr":
            continue
        if entry.is_symlink() and (entry.name not in wanted or os.readlink(entry) != str(wanted[entry.name])):
            entry.unlink()
    for name, target in wanted.items():
        link = base / name
        if not link.is_symlink():
            link.symlink_to(target)
    (base / "usr").mkdir(exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = base / "tmp"
    if tmp.is_symlink() and os.readlink(tmp) != str(scratch):
        tmp.unlink()
    if not tmp.is_symlink():
        tmp.symlink_to(scratch)
    return base


def write_atomic(path: pathlib.Path, text: str) -> None:
    """Write a per-turn file the way a file ANOTHER process may be importing has to be written.

    Two turns of one session can run at once: the gateway starts the next turn without stopping a
    turn still in flight, and both drivers then share this workspace (measured 2026-10-01 on a local
    instance — a second turn completed in 3.9 s while the first was still running its shell, and the
    orphan lived on to the runner's own cap). `Path.write_text` truncates first, so the other
    driver's import could read an EMPTY extension module and lose that turn's tool cards without a
    word. A rename is atomic: a reader sees the old file or the new one."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# A bash with no PS1 of its own prints `bash-5.2$`, which none of upstream's prompt patterns match;
# without a match the tool cannot tell a finished command from a quiet one and waits out its
# 15-second no-output timeout on EVERY call (measured: a one-line `echo > file` took 15 s).
_BARE_BASH_PROMPT = r"^bash-[0-9.]+[$#] ?$"


def code_execution_config(src: pathlib.Path) -> dict:
    """The _code_execution plugin's config: upstream's defaults, with two changes.

    A config.json REPLACES the defaults rather than merging with them (plugins.get_plugin_config
    reads the first file it finds), so the whole default is carried and only these two differ:
    local TTY rather than SSH (upstream's `auto` means SSH whenever the framework is not inside its
    own image, into a container this sandbox does not have), and the bare-bash prompt pattern."""
    import yaml  # Agent Zero's own dependency, in its venv
    try:
        cfg = yaml.safe_load((src / "plugins" / "_code_execution" / "default_config.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        cfg = {}
    cfg["ssh_enabled"] = False
    patterns = str(cfg.get("prompt_patterns") or "").rstrip("\n")
    if _BARE_BASH_PROMPT not in patterns:
        cfg["prompt_patterns"] = (patterns + "\n" if patterns else "") + _BARE_BASH_PROMPT + "\n"
    return cfg


def write_config(base: pathlib.Path, job: dict, src: pathlib.Path) -> None:
    """Everything Agent Zero reads from usr/, rewritten on every turn from the job."""
    usr = base / "usr"
    plug = usr / "plugins"
    (plug / "_model_config").mkdir(parents=True, exist_ok=True)
    # JSON is YAML, and Agent Zero reads this file with its YAML loader; written as JSON so this
    # module needs nothing beyond the standard library outside Agent Zero's venv.
    write_atomic(plug / "_model_config" / "presets.yaml",
        json.dumps(presets(job["model"], job["base_url"], job.get("provider_timeout")), indent=1))
    for p in DISABLED_PLUGINS:
        (plug / p).mkdir(parents=True, exist_ok=True)
        write_atomic(plug / p / ".toggle-0", "")
    # _chat_naming is ALWAYS-ENABLED (its toggle file is ignored), and by default it makes a
    # utility-model call at the end of every turn to name the chat for a sidebar nobody sees —
    # measured at a recorder: a one-word turn was two provider calls, the second this one. Its own
    # switch turns the automatic naming off.
    (plug / "_chat_naming").mkdir(parents=True, exist_ok=True)
    write_atomic(plug / "_chat_naming" / "config.json", json.dumps(
        {"automatic_naming": False, "automatic_naming_mode": "always"}))
    (plug / "_code_execution").mkdir(parents=True, exist_ok=True)
    write_atomic(plug / "_code_execution" / "config.json", json.dumps(code_execution_config(src)))
    # The harness's AGENTS.md reaches the system prompt through Agent Zero's own include plugin:
    # files matching the pattern anywhere in the workdir are inlined, each to max_file_tokens.
    (plug / "_promptinclude").mkdir(parents=True, exist_ok=True)
    write_atomic(plug / "_promptinclude" / "config.json", json.dumps({
        "name_pattern": job.get("agent_doc_name") or "AGENTS.md", "max_depth": 1,
        "max_file_tokens": 16000, "max_file_count": 4, "max_total_tokens": 24000,
        "gitignore": ".harness/**\ntmp/**\n**/node_modules/**\n**/.git/**\n"}))
    # The tool policy, GLOBAL (usr/plugins/_tool_access/config.json): _tool_access resolves a profile's
    # own policy first and falls back to this one, and no bundled profile carries its own, so the
    # main agent and every subordinate profile call_subordinate can spawn read the same policy.
    # Per-profile would miss a profile, and delegation would hand a withheld tool back (kimi's
    # lesson with built-in subagents).
    (plug / "_tool_access").mkdir(parents=True, exist_ok=True)
    write_atomic(plug / "_tool_access" / "config.json", json.dumps(tool_policy(job.get("tools_disabled"))))
    (usr / "prompts").mkdir(parents=True, exist_ok=True)
    write_atomic(usr / "prompts" / "agent.system.main.environment.md", environment_prompt(job["cwd"]))
    # Settings come from A0_SET_* defaults; a settings.json would override them, and nothing in a
    # turn has a reason to write one.
    with contextlib.suppress(OSError):
        (usr / "settings.json").unlink()


def _workdir_gitignore(src: pathlib.Path) -> str:
    try:
        base = (src / "conf" / "workdir.gitignore").read_text()
    except OSError:
        base = ""
    return base.rstrip("\n") + "\n\n# harness state and scratch\n.harness/**\ntmp/**\n"


def ipython_on_path(home: pathlib.Path) -> str:
    """A directory holding ONLY `ipython`, for the shell's PATH.

    code_execution_tool's python runtime types `ipython -c <code>` into the terminal
    (plugins/_code_execution/tools/code_execution_tool.py); upstream's image has an ipython on PATH,
    this sandbox does not. The installer puts one in Agent Zero's venv, and this exposes that one
    binary and nothing else — putting the venv's bin/ on PATH would also make its python3 and pip
    the agent's, shadowing the sandbox's own for every task command."""
    d = home / "bin"
    d.mkdir(parents=True, exist_ok=True)
    target = pathlib.Path(sys.executable).parent / "ipython"
    link = d / "ipython"
    if link.is_symlink() and os.readlink(link) != str(target):
        link.unlink()
    if target.exists() and not link.is_symlink():
        link.symlink_to(target)
    return str(d)


def _set_env(job: dict, src: pathlib.Path) -> None:
    os.environ["A0_SET_workdir_path"] = job["cwd"]
    os.environ["A0_SET_workdir_gitignore"] = _workdir_gitignore(src)
    os.environ["A0_SET_mcp_servers"] = mcp_config(job.get("mcp_servers"), job.get("tools_disabled"))
    os.environ["A0_SET_update_check_enabled"] = "false"
    # litellm fetches its model price map from raw.githubusercontent.com on import unless told to
    # use the copy it ships (measured through a logging proxy: the only non-provider host a turn hit).
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["OTHER_API_KEY"] = job.get("api_key") or os.environ.get("OTHER_API_KEY") or ""
    os.environ["PAGER"] = "cat"
    os.environ["PATH"] = ipython_on_path(pathlib.Path(job["cwd"]) / ".harness" / "agentzero") \
        + os.pathsep + os.environ.get("PATH", "")


# ── the turn's event hooks ─────────────────────────────────────────────────────────────────────
# Installed as Agent Zero extensions (usr/extensions/python/<point>/), the framework's own hook for
# observing a tool call: tool_execute_before carries the name and arguments, tool_execute_after the
# Response. They call back into this module through sys.modules, so the extension files hold no logic.
_HOOK_SRC = {
    "tool_execute_before": (
        "import sys\nfrom helpers.extension import Extension\n\n"
        "class HrToolBefore(Extension):\n"
        "    async def execute(self, tool_name='', tool_args=None, **kwargs):\n"
        "        sys.modules['hr_agentzero_driver'].on_tool_before(self.agent, tool_name, tool_args or {})\n"),
    "tool_execute_after": (
        "import sys\nfrom helpers.extension import Extension\n\n"
        "class HrToolAfter(Extension):\n"
        "    async def execute(self, response=None, tool_name='', **kwargs):\n"
        "        sys.modules['hr_agentzero_driver'].on_tool_after(self.agent, tool_name, response)\n"),
    "message_loop_start": (
        "import sys\nfrom helpers.extension import Extension\n\n"
        "class HrLoopStart(Extension):\n"
        "    async def execute(self, loop_data=None, **kwargs):\n"
        "        sys.modules['hr_agentzero_driver'].on_loop_start(self.agent, loop_data)\n"),
    "message_loop_result": (
        "import sys\nfrom helpers.extension import Extension\n\n"
        "class HrLoopResult(Extension):\n"
        "    async def execute(self, loop_data=None, result_data=None, **kwargs):\n"
        "        sys.modules['hr_agentzero_driver'].on_loop_result(self.agent, result_data or {})\n"),
}


# Agent Zero opens every fresh conversation with a FABRICATED exchange: its agent_init extension
# adds a user message "Hello!" (prompts/fw.initial_user_message.md) and an assistant greeting, so
# the web UI never starts empty. In a harness that message is a lie about the user: the transcript's
# first user message is one the person never sent, and the gateway's record does not have it.
# MEASURED on the support matrix (2026-09-28): asked "what exact word did I ask you to reply with in
# my very first message", five model/run pairs answered "Hello", "Hello!", "none" or "you did not ask
# me to reply with any specific word" — the injected message, quoted back — while the real first
# message sat in the same prompt. It read as intermittent because only some models take "the very
# first message" literally.
#
# Overridden through the framework's own mechanism rather than patched: extension classes are merged
# by FILE NAME with the first occurrence winning (helpers/extension._get_extension_classes), and
# usr/extensions comes before the bundled extensions in the search order, so a file of the same name
# here replaces the bundled one. The name is therefore load-bearing, and a pin bump must re-check it.
_INITIAL_MESSAGE_OVERRIDE = (
    "from helpers.extension import Extension\n\n\n"
    "class InitialMessage(Extension):\n"
    "    \"\"\"Overrides extensions/python/agent_init/_10_initial_message.py by file name: a harness\n"
    "    conversation starts with the user's own first message.\"\"\"\n\n"
    "    def execute(self, **kwargs):\n"
    "        return\n")


def install_hooks(base: pathlib.Path) -> None:
    for point, code in _HOOK_SRC.items():
        d = base / "usr" / "extensions" / "python" / point
        d.mkdir(parents=True, exist_ok=True)
        write_atomic(d / "_99_harnessrouter.py", code)
    d = base / "usr" / "extensions" / "python" / "agent_init"
    d.mkdir(parents=True, exist_ok=True)
    write_atomic(d / "_10_initial_message.py", _INITIAL_MESSAGE_OVERRIDE)


_STATE: dict = {"pending": {}, "final": "", "steps": 0, "max_turns": None}


def on_loop_start(agent, loop_data) -> None:
    """The step budget. Agent Zero's loop has none of its own (it runs until the response tool), so
    an operator's max_turns is counted here over the main agent's LLM calls and ends the turn the
    way any failure does: an exception out of the loop, which Agent Zero reports as the turn's error."""
    if getattr(agent, "number", 0) != 0:
        return
    _STATE["steps"] += 1
    cap = _STATE.get("max_turns")
    if cap and _STATE["steps"] > cap:
        raise RuntimeError(f"the turn used its step budget ({cap} model calls) without finishing")


def on_loop_result(agent, result_data: dict) -> None:
    """The model's own reasoning for this step: Agent Zero's JSON reply carries `thoughts` (a list)
    and a `headline`. Shown as thinking, never as the answer — the answer is the response tool's."""
    llm = result_data.get("llm_result")
    text = str(getattr(llm, "response", "") or "")
    if not text:
        return
    try:
        from helpers import dirty_json
        obj = dirty_json.try_parse(text)
    except Exception:  # noqa: BLE001
        obj = None
    if not isinstance(obj, dict):
        return
    thoughts = obj.get("thoughts")
    if isinstance(thoughts, list):
        thoughts = "\n".join(str(t) for t in thoughts if t)
    if isinstance(thoughts, str) and thoughts.strip():
        _emit("thinking", {"text": thoughts.strip(), "agent": getattr(agent, "number", 0)})


def on_tool_before(agent, tool_name: str, tool_args: dict) -> None:
    number = getattr(agent, "number", 0)
    if tool_name == "response":
        return   # the answer, not a tool: taken from the response tool's Response below
    tid = "a0-" + uuid.uuid4().hex[:12]
    _STATE["pending"].setdefault(number, []).append(tid)
    _emit("tool_call", {"id": tid, "name": tool_name, "input": dict(tool_args or {}), "agent": number})


def on_tool_after(agent, tool_name: str, response) -> None:
    number = getattr(agent, "number", 0)
    message = str(getattr(response, "message", "") or "")
    if tool_name == "response":
        if number == 0:
            _STATE["final"] = message
        return
    stack = _STATE["pending"].get(number) or []
    tid = stack.pop() if stack else "a0-" + uuid.uuid4().hex[:12]
    _emit("tool_result", {"id": tid, "name": tool_name, "output": message, "agent": number})


def _flush_pending(reason: str) -> None:
    """A tool that raised never reaches tool_execute_after; its card is closed with the reason, so
    the record does not show a call with no result."""
    for number, stack in list(_STATE["pending"].items()):
        while stack:
            _emit("tool_result", {"id": stack.pop(), "output": reason, "is_error": True,
                                  "agent": number})


def _last_log(ctx, kinds: tuple[str, ...]) -> str:
    for item in reversed(getattr(ctx.log, "logs", []) or []):
        if item.type in kinds and (item.content or "").strip():
            return str(item.content).strip()
    return ""


def _error_reason(ctx, exc: BaseException) -> str:
    """The failure as Agent Zero recorded it: the `error` log item its critical-exception handler
    writes (errors.format_error: the exception's text, then a traceback), cut at the traceback. The
    exception itself is the fallback — HandledException wraps the original and repeats its text."""
    text = _last_log(ctx, ("error",))
    if text:
        text = text.split("\n\nTraceback", 1)[0].split("\nTraceback", 1)[0].strip()
    if not text:
        inner = getattr(exc, "exception", None) or exc
        text = f"{type(inner).__name__}: {inner}"
    return text[:2000]


def _mcp_down() -> list[dict]:
    try:
        from helpers.mcp_handler import MCPConfig
        inst = MCPConfig.get_instance()
        return [{"name": str(s.get("name") if isinstance(s, dict) else getattr(s, "name", s)),
                 "reason": str(s.get("error") if isinstance(s, dict) else "")[:200]}
                for s in (getattr(inst, "disconnected_servers", None) or [])]
    except Exception:  # noqa: BLE001
        return []


async def _run(job: dict) -> int:
    import initialize
    from agent import AgentContext, AgentContextType, UserMessage
    from helpers import persist_chat

    initialize.initialize_migration()
    from helpers import settings as a0_settings
    from helpers.mcp_handler import initialize_mcp
    initialize_mcp(a0_settings.get_settings()["mcp_servers"])
    down = _mcp_down()
    if down:
        _emit("mcp_unavailable", {"servers": down})

    ctx = None
    resumed = False
    chat = pathlib.Path(persist_chat._get_chat_file_path(SESSION_ID))
    if chat.is_file():
        data = json.loads(chat.read_text())
        ctx = persist_chat._deserialize_context(data)
        resumed = True
    if ctx is None:
        cfg = initialize.initialize_agent()
        ctx = AgentContext(config=cfg, id=SESSION_ID, type=AgentContextType.USER)
    AgentContext.use(ctx.id)
    _emit("init", {"session_id": SESSION_ID, "resumed": resumed,
                   "import_s": round(time.time() - _T0, 2)})

    task = ctx.communicate(UserMessage(message=job["prompt"], attachments=[], id=str(uuid.uuid4())))
    ok, reason = True, ""
    try:
        result = await task.result()
    except BaseException as e:  # noqa: BLE001 — HandledException, CancelledError, the step budget
        ok, result, reason = False, None, _error_reason(ctx, e)
    final = _STATE["final"] or (str(result) if isinstance(result, str) else "")
    if ok and not final:
        ok, reason = False, "the turn ended without an answer"
    _flush_pending(reason or "the tool did not return")
    try:
        persist_chat.save_tmp_chat(ctx)
    except Exception as e:  # noqa: BLE001
        _emit("warning", {"text": f"the conversation could not be saved: {e}"})
    _emit("result", {"ok": ok, "final": final if ok else "", "error": reason,
                     "seconds": round(time.time() - _T0, 2)})
    return 0 if ok else 1


def keep_children_in_group() -> None:
    """Keep Agent Zero's terminal in the driver's process group.

    Its terminal is a bash on a pty spawned with start_new_session=True
    (plugins/_code_execution/helpers/tty_session.py), which takes it OUT of the group the runner
    kills on cancel and timeout — the shape of the openhands tmux defect (checklist item 21). A
    FOREGROUND command dies anyway (the driver's death closes the pty master and the session gets
    SIGHUP), but anything the agent put in the background with nohup outlived the kill. Measured
    with a scripted provider that asked for `nohup sleep 188 … & sleep 60`, the runner's own
    killpg on the driver's group: without this, `sleep 188` survived; with it, nothing did. The
    runner's marker sweep is only a second net: it reads other uids' /proc/<pid>/environ, which
    default Docker (no CAP_SYS_PTRACE) refuses. So the new session is simply not created: the
    shell still runs on its pty (prompt detection and output reading are unchanged), without a
    controlling terminal and therefore without job control, so everything it starts stays in the
    group the runner's killpg reaches. tty_session is the only caller of create_subprocess_shell in
    the pinned tree."""
    real = asyncio.create_subprocess_shell

    async def create_subprocess_shell(cmd, *a, **k):
        k["start_new_session"] = False
        return await real(cmd, *a, **k)

    asyncio.create_subprocess_shell = create_subprocess_shell


def main(argv: list[str]) -> int:
    # The job rides the environment (see _build_agentzero: argv is world-readable in the container)
    # and is taken OUT of it here, so the agent's own shell does not inherit it.
    job = json.loads(argv[1]) if len(argv) > 1 else json.loads(os.environ.pop("HR_AGENTZERO_JOB"))
    src = pathlib.Path(job["a0_src"])
    cwd = pathlib.Path(job["cwd"])
    home = cwd / ".harness" / "agentzero"
    base = prepare_base(src, home, cwd / "tmp" / "agentzero")
    write_config(base, job, src)
    install_hooks(base)
    _STATE["max_turns"] = job.get("max_turns") or None
    _set_env(job, src)
    # Agent Zero's console goes to a log in the workspace scratch (never checkpointed), NOT to the
    # runner's stderr: it prints every exception with its full traceback, and the runner takes the
    # first stderr line that looks like a provider refusal as the turn's reason — measured with a
    # wrong key, the record's reason became `File ".../litellm/llms/openai/openai.py", line 1113,
    # in async_streaming` while the result event carried the real sentence. The driver's result
    # event states the reason; fd 1 is the event channel.
    # ONE LOG PER TURN PROCESS, not one per workspace: a second turn of the same session can start
    # while this one still runs (the gateway does not stop the first), and a shared name opened
    # O_TRUNC means the newcomer empties the log of the turn still writing it — which is exactly
    # what a hung turn leaves behind, a 0-byte file nobody can read (seen on the family tour's
    # workspace, 2026-10-01). tmp/ is never checkpointed and the sandbox is recycled, so these do
    # not accumulate beyond a session's life.
    console = os.open(str(cwd / "tmp" / "agentzero" / f"console-{os.getpid()}.log"),
                      os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(console, 1)
    os.dup2(console, 2)
    sys.stdout = sys.stderr = open(console, "w", buffering=1, closefd=False)
    sys.modules["hr_agentzero_driver"] = sys.modules[__name__]
    keep_children_in_group()
    stub = types.ModuleType("sentence_transformers")

    class SentenceTransformer:   # noqa: D401 — see the module docstring
        def __init__(self, *a, **k):
            raise RuntimeError("local embeddings are not installed for this harness")

    stub.SentenceTransformer = SentenceTransformer   # type: ignore[attr-defined]
    sys.modules.setdefault("sentence_transformers", stub)
    # `--dockerized=true`: Agent Zero's development mode forwards file and shell work over RFC to a
    # container; "dockerized" is its name for "do it here". runtime.initialize parses sys.argv.
    try:
        sys.argv = [argv[0], "--dockerized=true"]
        sys.path.insert(0, str(base))
        os.chdir(str(base))
        from helpers import dotenv, files, runtime
        runtime.initialize()
        dotenv.load_dotenv()
        files.normalize_a0_path = lambda p: p   # see the module docstring
        # THE TURN'S WORKING DIRECTORY IS THE WORKSPACE, not the base the framework was imported from.
        # Agent Zero resolves its OWN paths against its base dir (helpers/files.get_abs_path), so the
        # import above is unaffected — but a tool that takes a path from the model resolves it against
        # the process cwd: text_editor writes with a bare `open(path)` (plugins/_text_editor/helpers/
        # file_ops.write_file). With the cwd left at the base, a model that asked for
        # "hello-agentzero.txt" had its file written to .harness/agentzero/base/ — inside the prefix
        # /produced excludes, so the turn produced a file the user never saw. MEASURED on the support
        # matrix (2026-09-28): every artifact failure said "Edited a file" and delivered nothing, and it
        # was the models that pass a RELATIVE path that failed, which is why it read as intermittent.
        os.chdir(str(cwd))
        return asyncio.run(_run(job))
    except Exception as e:  # noqa: BLE001 — an import or setup failure is still a turn result
        _emit("result", {"ok": False, "final": "", "error": f"{type(e).__name__}: {e}"[:2000],
                         "seconds": round(time.time() - _T0, 2)})
        return 1


if __name__ == "__main__":
    code = main(sys.argv)
    _OUT.flush()
    # Agent Zero starts non-daemon threads (DeferredTask loops, MCP sessions); the turn is over.
    os._exit(code)
