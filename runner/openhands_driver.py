"""One OpenHands turn, as a runner subprocess.

Spawned per turn by server.py, the same one-process-per-turn contract every other backend keeps:
the runner reads NDJSON off stdout and cancel is a process-group kill. Inside, this starts an
`openhands-agent-server` on loopback, drives ONE turn over its HTTP + WebSocket API, and exits.

WHY A SERVER AT ALL. The base runs OpenHands V1 through `openhands-agent-server`, the REST/WebSocket
interface its vendor maintains (OpenHands/agent-sdk). The CLI that used to be the obvious choice —
PyPI `openhands`, from OpenHands/openhands-cli — opens its README with "This project is no longer
actively maintained" and last released 1.16.0 on 2026-05-08. The agent server released 1.49.2 on
2026-09-17.

WHY ONE SERVER PER TURN rather than one resident server. Measured on the pinned 1.49.2: cold start
to a serving `/alive` is 3.3-4.1 s, and a conversation created by one server process is read back
intact by a DIFFERENT process on a different port over the same on-disk store (verified by killing
the first and querying the second). That is what makes the per-turn shape work at all, and it is
the shape this product needs: sandboxes are recycled between turns, so a resident server would hold
conversation state for workspaces that no longer exist. The cost is that 3.7 s on every turn.

The event protocol is dsh_driver's: one {"m": method, "p": payload} JSON object per line on stdout,
normalised by _openhands_to_claude in server.py.
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

_T0 = time.time()

def _conversation_id(tools: list[str], mcp: dict | None = None, withheld: list[str] | None = None) -> str:
    """The conversation id the runner MINTS, for aider's and goose's reason: it has to be
    reproducible from the workspace alone after a sandbox recycle. The API takes `conversation_id`
    on the create call (a request field, not a server-assigned one), so a uuid5 is all it takes — a
    uuid rather than a name because the field is typed `uuid.UUID`.

    THE TOOL POLICY IS PART OF THE IDENTITY, and that is not decoration. The agent is frozen at the
    conversation's FIRST creation: measured on 1.49.2, a second create for the same id carrying
    `tools: []` left the persisted agent holding `['terminal', 'file_editor']` and the turn wrote
    its file anyway, and there is no endpoint that updates an agent (`PATCH /conversations/{id}` is
    metadata — "like title"). Keying the id on the policy means a changed policy is a new
    conversation, created with the tools it asks for. The cost is that changing the policy starts a
    new thread; the alternative is running with a tool the operator has since disabled, which is the
    overstatement UHP 4.3 forbids and the direction this must never fail in.

    The declared MCP servers are in the key for the same reason: they are part of the agent, and an
    agent that cannot be updated cannot learn about a server added after it was made.
    """
    # The withheld MCP tool names are part of the identity for the same reason the tool list is:
    # the filter is a property of the frozen agent.
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          "https://harnessrouter.dev/openhands/harness?tools=" + ",".join(tools)
                          + "&mcp=" + ",".join(sorted(mcp or {}))
                          + "&withheld=" + ",".join(sorted(withheld or []))))


def _emit(method: str, payload) -> None:
    sys.stdout.write(json.dumps({"m": method, "p": payload}, default=str) + "\n")
    sys.stdout.flush()


def _free_port() -> int:
    """A port the kernel just handed out and nobody else holds. Bound and released rather than
    guessed, because turns of different sessions run side by side on one host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_config(home: pathlib.Path, api_key: str) -> pathlib.Path:
    """The server's own config file, per turn.

    Every path is pointed under .harness/openhands/ so the conversation store travels in the
    checkpoint (and is excluded from produced files by the `.harness/` prefix), and VSCODE IS OFF:
    it defaults to on and binds port 8001, which one process per turn would collide on immediately.
    """
    cfg = {
        "session_api_keys": [api_key],
        "conversations_path": str(home / "conversations"),
        "workspace_path": str(home / "project"),
        "bash_events_dir": str(home / "bash_events"),
        "enable_vscode": False,
        # Tool preloading is Chromium preloading — the service's own docstring is "Service which
        # preloads chromium", and its start() constructs a BrowserToolExecutor. This image carries
        # no Chromium and this backend offers no browser tool, so on every server start it does the
        # work and then fails (`Error preloading … Exception: Chromium is …` in the server's log).
        # One server per turn means paying for that failure once per turn.
        "preload_tools": False,
        "allow_cors_origins": [],
    }
    path = home / "agent-server-config.json"
    path.write_text(json.dumps(cfg, indent=2))
    return path


# The phase the driver is in, so a socket timeout says WHICH wait ended rather than just
# `TimeoutError: timed out` — four calls here can raise that exact exception with that exact
# message, and a reason that does not separate them is a reason nobody can act on. Measured on
# vercel|openhands|claude-sonnet-4.6, whose recycle failed in 250 s saying only "timed out".
_STEP = "starting"


def _req(url: str, key: str, method: str = "GET", body: dict | None = None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"X-Session-API-Key": key,
                                        "content-type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode(errors="replace")
    return json.loads(raw) if raw.strip() else None


# `AttributeError: 'X' object has no attribute 'y'` — the shape of the one line worth keeping out
# of a rich-framed traceback. Anchored at the start of the stripped line so a mention inside a log
# message does not win over the exception itself.
_EXC_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception)\b\s*:")
# `[09/19/26 03:27:05] INFO …`, and the bare `INFO`/`ERROR` continuation rich writes under it: a
# new record, never the wrapped remainder of an exception message.
_LOG_LINE = re.compile(r"^\[\d\d/\d\d/\d\d |^(?:INFO|ERROR|WARNING|DEBUG)\s")


def _exc_text(lines: list[str], i: int) -> str:
    """One exception line plus the continuation of its message, and nothing after that.

    rich wraps a long message onto the next lines and then draws the next frame or writes its next
    record, so the stop condition is the box-drawing, the chaining sentence and a new log line.
    Taking a fixed three lines instead put `The above exception was … ╭────` behind one reason and
    the `SIGTERM … Shutting down` noise behind the other; both were caught by the tests below."""
    out = [lines[i].strip()]
    for ln in lines[i + 1:i + 4]:
        t = ln.strip()
        if (not t or t[0] in "╭╰│─" or _LOG_LINE.match(t) or _EXC_LINE.match(t)
                or t.startswith(("The above exception", "During handling"))):
            break
        out.append(t)
    return " ".join(out)


def _log_tail(path: pathlib.Path, limit: int = 1200) -> str:
    """Why the server failed, taken from what it wrote; its last lines only as a fallback.

    THE LAST LINES ARE USUALLY THE WRONG ONES. A turn that dies at second 3 and is then retried to
    exhaustion is terminated at second 190, so by the time this is read the tail of the file is
    `Received signal SIGTERM … Shutting down … Application shutdown complete` and the sentence that
    explains the failure is three minutes above it. Measured: the first version of this function
    put exactly that shutdown noise into the record, which is worse than the silence it replaced,
    because it reads like a reason. So the exception lines are looked for first."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # BOTH ENDS OF THE CHAIN, because neither alone is the answer. A chained traceback prints the
    # root cause first and the exception that wrapped it last, so reading from the end returns
    # `ConversationRunError: Conversation run failed for id=…` — true, and useless — while the
    # sentence that names the defect is the first one. Reporting the pair costs one line and
    # survives a chain in either direction.
    found = [_exc_text(lines, i) for i, ln in enumerate(lines) if _EXC_LINE.match(ln.strip())]
    if found:
        out = found[0] if len(found) == 1 or found[-1] == found[0] else f"{found[0]} … {found[-1]}"
        return out[:limit]
    return " | ".join(lines[-12:])[-limit:]


def _wait_alive(port: int, proc: subprocess.Popen, deadline: float) -> bool:
    """/alive needs no key and answers as soon as the app is mounted; measured 0.03 s ahead of the
    first authenticated call, so there is no second readiness gate worth waiting on."""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/alive", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    return False


def _agent_spec(job: dict) -> dict:
    """The agent, with NO CREDENTIAL IN IT. The key travels in the server's environment instead.

    MEASURED, and this is the whole reason for the shape: the conversation state persisted to disk
    carries the entire LLM spec — model, base_url, retries, timeouts — and `api_key: None`. The
    server keeps no key at rest, exactly as its docs claim. So a key passed here reaches the first
    turn and NOTHING after it: a later turn's server rebuilds the agent from that state, has no
    credential, and litellm's own retry/backoff then hides the failure for two minutes before the
    conversation lands in `error` with
    `Vercel_ai_gatewayException - Missing credentials. Please pass an api_key…`. Re-POSTing the
    create call with the agent does not fix it either; the history survives, the credential does not.

    Passing it in the environment makes it a property of THIS turn's process, which every turn sets
    afresh, so resume needs nothing persisted. `usage_id` names the row this turn's spend lands on
    and is not sent to the provider.
    """
    tools = [{"name": n} for n in _tools(job)]
    # MCP TOOLS ARE WITHHELD BY NAME TOO. The built-ins are omitted from the spec above; an MCP
    # tool is loaded from the server at agent start and is not in that list, so a disabled one
    # was called all the same (measured: probe_sse disabled, called, its token in the answer).
    # The SDK's own filter is a regex over every tool name after the MCP tools are added
    # (Agent.filter_tools_regex, base.py:153); a negative lookahead over the disabled names, the
    # bare name and the `server_tool` spelling a client may expose, is that filter.
    filter_regex = _filter_regex(_withheld_mcp(job))
    # NO BASE URL IN IT EITHER. The spec is persisted with the conversation, and the base url is
    # the loopback relay's, which binds a fresh port on every runner start: a conversation created
    # before a restart dialled the old port on its next turn and died on `Cannot connect to host
    # 127.0.0.1:39265` (hr-test, 2026-09-19, the first turn after a deploy). litellm reads
    # OPENAI_BASE_URL from the environment when the spec carries none, and the driver sets it for
    # this turn's server the way it sets the key, so every turn dials the relay it was given.
    # RETRIES BOUNDED IN SECONDS, NOT MINUTES. The SDK's defaults (5 retries, 8 s minimum wait,
    # 64 s maximum, multiplier 8) turn a provider that answers the same 503 every time into a
    # 270-310 s turn before the reason is reported (three switch scenarios, hr-test 2026-09-19);
    # every other base surfaces the same refusal in seconds. Two retries a few seconds apart
    # still cover a blip. Persisted with the agent like the rest of the spec.
    spec: dict = {"llm": {"model": job["model"], "base_url": None, "usage_id": "harness",
                          "num_retries": 2, "retry_min_wait": 2, "retry_max_wait": 8,
                          "retry_multiplier": 2},
                  "tools": tools,
                  # THE AGENT DOC IS CONTEXT, NOT A FILE THE MODEL MAY OR MAY NOT OPEN. The SDK
                  # loads the workspace's AGENTS.md (and .agents/skills/) as repo skills only when
                  # asked (AgentContext.load_project_skills, False by default), and it reads them
                  # afresh on each server's first run, so every turn sees the harness's current
                  # instructions, workspace contract and skills block. Without this the doc reached
                  # the model only when it chose to `cat AGENTS.md` (it did in the smoke turns; a
                  # model that does not never learns where deliverables go or which skills exist).
                  "agent_context": {"load_project_skills": True}}
    # The declared MCP servers ride the agent itself — the SDK dials them, so this base needs no
    # bridge of its own. Sent only when there ARE servers: the agent is frozen at creation, and an
    # empty mcp_config is not the same statement as none.
    if job.get("mcp_config"):
        spec["mcp_config"] = job["mcp_config"]
    if filter_regex:
        spec["filter_tools_regex"] = filter_regex
    return spec


def _withheld_mcp(job: dict) -> list[str]:
    """The disabled names that are not built-in tools: MCP tools, withheld by the SDK's filter."""
    return sorted({str(x) for x in (job.get("tools_disabled") or [])
                   if str(x) not in _TOOL_NAMES and str(x) not in _TOOLS})


def _filter_regex(disabled: list[str]) -> str:
    """A regex that admits every tool name except the disabled ones: the bare name, and the
    `<server>_<name>` and `<server>.<name>` spellings under which a client may expose an MCP
    tool. Empty when nothing is disabled, so the spec carries no filter at all."""
    names = [d.strip() for d in disabled if d and d.strip()]
    if not names:
        return ""
    alts = []
    for n in names:
        e = re.escape(n)
        alts.append(f"{e}$")
        alts.append(f"[^\\s]+[._]{e}$")
    return "^(?!(?:" + "|".join(alts) + "))"


# The tools this base gives the agent, by the names openhands-tools registers. An agent created
# without this list gets NONE — measured: asked to write a file it answered "I can't create files in
# this environment because no filesystem tool is available".
#
# `browser_tool_set` is in upstream's default preset and is deliberately NOT here: it needs a
# Chromium this image does not carry, and its absence already shows up as `Error preloading …
# Exception: Chromium is …` in the server's own log. A tool that cannot run is not offered.
_TOOLS = ("terminal", "file_editor", "task_tracker")
# What the console calls them. The catalog lists the console names; the disable list arrives in
# those, and enforcement is by OMISSION from the agent's tool list, which is as hard as it gets:
# a tool the agent was never given cannot be called.
_TOOL_NAMES = {"Shell": "terminal", "Edit": "file_editor", "Todo": "task_tracker"}


_CONSOLE_NAMES = {v: k for k, v in _TOOL_NAMES.items()}


def _action_input(action: dict) -> dict:
    """The action's arguments as the card's input: the SDK's `kind` and bookkeeping fields dropped,
    a terminal action's command under `command` as every other base's shell card carries it."""
    return {k: v for k, v in action.items()
            if k not in ("kind", "thought", "security_risk", "summary") and v not in (None, "", [], {})}


def _observation_text(obs: dict) -> str:
    """What the tool returned, as text: the observation's text blocks joined, the way the SDK's own
    visualiser reads them. The raw observation is a typed record (kind, content blocks with
    cache flags, the command, exit codes); rendered whole it put JSON on every result card."""
    parts = []
    for block in obs.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    text = "\n".join(p for p in parts if p)
    if text:
        return text
    return json.dumps({k: v for k, v in obs.items() if k != "content"}, default=str)


def _tools(job: dict) -> list[str]:
    off = {str(x) for x in (job.get("tools_disabled") or [])}
    off |= {_TOOL_NAMES[x] for x in off if x in _TOOL_NAMES}
    return [t for t in _TOOLS if t not in off]


def _set_turn_model(home: pathlib.Path, cid: str, model: str) -> bool:
    """The turn's model, written into the persisted agent before the server loads it.

    The agent is frozen at the conversation's creation, its LLM spec included, and the server
    offers no way to change it: a task that switched models kept calling the first one, the
    record saying claude-sonnet-5 while the relay served gpt-5.4 (hr-test, 2026-09-19). The
    conversation's store is a JSON file in this workspace that the server reads on first access,
    so the model rides the same door the conversation id does: the file is patched, then the
    server is asked. Only the model field changes; nothing else of the agent is touched."""
    path = home / "conversations" / cid.replace("-", "") / "base_state.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    llm = (doc.get("agent") or {}).get("llm")
    if not isinstance(llm, dict) or llm.get("model") == model:
        return False
    llm["model"] = model
    path.write_text(json.dumps(doc))
    return True


def _conversation(base: str, key: str, job: dict, cwd: str) -> tuple[str, bool]:
    """This turn's conversation: the minted id if the store already holds it, else created with it.

    Asking first is the goose lesson the 2026-09-13 decision generalised — the store answers whether
    the conversation is there, and the harness never infers it from its own argv.
    """
    cid = _conversation_id(_tools(job), job.get("mcp_config") or {}, _withheld_mcp(job))
    # before the server is asked, since it loads the conversation on first access
    _set_turn_model(pathlib.Path(cwd, ".harness", "openhands"), cid, job["model"])
    try:
        info = _req(f"{base}/api/conversations/{cid}", key)
        if info and info.get("id"):
            return cid, True
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    body: dict = {"conversation_id": cid,
                  "workspace": {"working_dir": cwd},
                  "agent": _agent_spec(job)}
    # THE OPERATOR'S STEP BUDGET. The server's own default is 500 iterations per run; a budget the
    # caller set and the backend ignored is the quiet lie this repo treats as a defect (kimi shipped
    # that bug at 1000 steps and turns ran for hours).
    budget = job.get("max_turns")
    if budget:
        body["max_iterations"] = max(1, int(budget))
    _req(f"{base}/api/conversations", key, method="POST", body=body, timeout=120)
    return cid, False


# What a turn's end looks like on the wire. The server reports execution status as an EVENT
# (ConversationStateUpdateEvent), so one WebSocket carries both the content and the terminal
# signal and nothing has to poll the conversation alongside it.
_TERMINAL = {"finished", "error", "stuck", "idle"}
_FAILED = {"error", "stuck"}


def _text_of(content) -> str:
    """A Message's content is a list of typed blocks; only text blocks are prose."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


def _on_event(ev: dict, state: dict) -> None:
    """One SDK event -> zero or more NDJSON lines.

    Only the shapes this product renders are translated. StreamingDeltaEvent is deliberately NOT:
    the final MessageEvent carries the same text whole, and emitting both would render the answer
    twice.
    """
    kind = str(ev.get("kind") or ev.get("type") or "")
    if kind == "MessageEvent":
        msg = ev.get("llm_message") or ev.get("message") or {}
        if str(msg.get("role") or "") == "assistant":
            text = _text_of(msg.get("content"))
            if text.strip():
                state["final"] = text
                _emit("text", {"text": text})
    elif kind == "ActionEvent":
        action = ev.get("action") or {}
        if str(action.get("kind") or "") == "FinishAction":
            # How a turn ENDS when the agent has tools: the answer rides the finish action rather
            # than a trailing assistant message (measured — turns that answer in prose alone emit a
            # MessageEvent and no finish, so both paths are real). Rendering it as a tool call would
            # show the user a "finish" step and leave the turn with no answer at all.
            text = str(action.get("message") or "")
            if text.strip():
                state["final"] = text
                _emit("text", {"text": text})
            return
        tuid = str(ev.get("tool_call_id") or ev.get("id") or len(state.setdefault("calls", [])))
        state.setdefault("calls", []).append(tuid)
        state["last_call"] = tuid
        # The console's names for the tools, the ones the catalog lists and the policy is written
        # in; the SDK's registry names (terminal, file_editor, task_tracker) are the wire.
        name = str(ev.get("tool_name") or "Tool")
        _emit("tool_call", {"id": tuid, "name": _CONSOLE_NAMES.get(name, name),
                            "input": _action_input(ev.get("action") or {})})
    elif kind == "ObservationEvent":
        obs = ev.get("observation") or {}
        if str(obs.get("kind") or "") == "FinishObservation":
            # Its action was suppressed above, so rendering this would leave an orphan tool result
            # under a call id the transcript never showed. Measured in a real artifact turn.
            return
        tuid = str(ev.get("tool_call_id") or state.get("last_call") or "t0")
        _emit("tool_result", {"id": tuid, "output": _observation_text(obs),
                              "is_error": bool(obs.get("is_error"))})
    elif kind in ("AgentErrorEvent", "ConversationErrorEvent"):
        # A REAL failure. Recorded, not rendered: it is the turn's reason, not part of its answer.
        #
        # READ code AND detail. This event carries neither `error` nor `message` — its fields are
        # `code` ("LLMServiceUnavailableError") and `detail`, which is where litellm puts the
        # provider's own sentence — so an extraction that read only `error`/`message` fell through
        # to the EVENT CLASS NAME and recorded that as the turn's reason. Three investigations here
        # began by opening the server's log for a sentence the record should already have carried.
        detail = str(ev.get("detail") or ev.get("error") or ev.get("message") or "")
        code = str(ev.get("code") or "")
        state["reported_error"] = True
        _emit("error", {"text": (f"{code}: {detail}" if code and detail
                                 else detail or code or kind)[:1500]})
    elif kind == "ConversationStateUpdateEvent":
        # The event is a generic key/value state update — `last_user_message_id` rides the same
        # shape — so the KEY has to be checked. Reading `value` alone once set the status to a
        # message uuid, which only failed to end the turn early because a uuid is not a status.
        if str(ev.get("key") or "") == "execution_status":
            value = ev.get("value")
            if isinstance(value, str) and value:
                state["status"] = value.lower()


def _run_turn(base: str, ws_base: str, key: str, cid: str, prompt: str, state: dict,
              max_seconds: float, proc: subprocess.Popen | None = None) -> None:
    """Send the message and read the conversation's events until the turn ends.

    The WebSocket is opened BEFORE the message is sent: the run starts the moment the POST lands,
    and a socket opened afterwards would miss whatever the agent did first.
    """
    from websockets.sync.client import connect

    url = f"{ws_base}/sockets/events/{cid}"
    # KEEPALIVE OFF. The client library pings every 20 s and closes the socket when a pong does not
    # come back in time; measured on a resumed conversation, that fired mid-turn and the turn died
    # with `sent 1011 (internal error) keepalive ping timeout` after 178 s with no answer. Nothing
    # here needs the client to prove the link: the server pushes, and this loop already has its own
    # deadline. A liveness check that ends healthy turns is worse than no liveness check.
    global _STEP
    _STEP = "opening the event socket"
    with connect(url, additional_headers={"X-Session-API-Key": key},
                 open_timeout=30, close_timeout=5, ping_interval=None) as ws:
        _STEP = "sending the message"
        _req(f"{base}/api/conversations/{cid}/events", key, method="POST",
             body={"role": "user", "content": [{"type": "text", "text": prompt}], "run": True},
             timeout=60)
        _STEP = "reading the conversation's events"
        deadline = time.time() + max_seconds
        while time.time() < deadline:
            try:
                raw = ws.recv(timeout=max(1.0, min(30.0, deadline - time.time())))
            except TimeoutError:
                # a server that died leaves the socket silent, not closed; asking the process is
                # what tells a dead server from a long tool call
                if proc is not None and proc.poll() is not None:
                    state["server_died"] = True
                    return
                continue
            try:
                ev = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(ev, dict):
                _on_event(ev, state)
                if state.get("status") in _TERMINAL and state.get("sent"):
                    return
                # the run is only over once it has started: the status is `idle` until the first
                # step lands, and returning on that would end the turn before it began
                if state.get("status") == "running":
                    state["sent"] = True
        state["timeout"] = True


def main() -> int:
    job = json.loads(sys.argv[1])
    cwd = job.get("cwd") or os.getcwd()
    os.chdir(cwd)
    home = pathlib.Path(cwd, ".harness", "openhands")
    home.mkdir(parents=True, exist_ok=True)

    key = secrets.token_urlsafe(24)
    port = _free_port()
    cfg = _write_config(home, key)

    env = dict(os.environ)
    env["OPENHANDS_AGENT_SERVER_CONFIG_PATH"] = str(cfg)
    # THE PROVIDER CREDENTIAL, and the only place it lives (see _agent_spec). The id is sent with an
    # `openai/` prefix by the builder so litellm routes through its openai provider verbatim instead
    # of INFERRING one from the base url — the inference is what produced `Vercel_ai_gatewayException
    # … set the VERCEL_AI_GATEWAY_API_KEY`, a provider-specific variable nothing here would set.
    if job.get("api_key"):
        env["OPENAI_API_KEY"] = str(job["api_key"])
    if job.get("base_url"):
        env["OPENAI_BASE_URL"] = str(job["base_url"])
    # The SDK prints a multi-line banner to STDOUT on import, which is this driver's NDJSON channel
    # for the server's own process; off by its own switch rather than by filtering lines.
    env["OPENHANDS_SUPPRESS_BANNER"] = "1"
    # The server logs through rich, which sizes itself to COLUMNS when it has no tty and defaults
    # to 80 — and a traceback panel inside an 80-wide log line leaves a message column about 27
    # characters across, so the one sentence worth reading arrives cut into six pieces. The tail
    # this driver attaches to a reasonless failure is only worth attaching if it is legible.
    env["COLUMNS"] = "200"
    # THE TURN DIES WITHOUT THIS, and the reason is a unix socket path limit rather than anything
    # about agents. The terminal tool runs commands in tmux, and tmux's socket lives under
    # TMUX_TMPDIR — which the server defaults to a directory INSIDE the working directory
    # ("TMUX_TMPDIR not set; defaulting to per-server tmux directory", api.py). A workspace here is
    # /data/workspaces/hsess<32 hex>, so the socket lands at
    #   /data/workspaces/hsess…/tmp/openhands-agent-server-<pid>/tmux-<uid>/openhands
    # at 106 characters, against the 108-byte sun_path limit — and tmux answers
    # `LibTmuxException: new-session: error connecting to … (File name too long)`. The agent then
    # retries the tool it cannot start, which is what turned a 10 s turn into 235 s and then into
    # 4,000 s. Measured through the gateway; a driver run from a short cwd never sees it.
    # A directory of THIS turn's own, not one named for the port: ports are reused, turns run
    # as different uids, and a directory left by an earlier turn on the same port answered
    # `couldn't create directory /tmp/oh58657/tmux-20167 (Permission denied)` (hr-test,
    # 2026-09-19). mkdtemp makes a fresh one owned by this uid; the name stays short for the
    # socket path limit above, and starts with /tmp/oh so the runner's sweep recognises it.
    env["TMUX_TMPDIR"] = tempfile.mkdtemp(prefix="oh", dir="/tmp")

    python = os.environ.get("HR_OPENHANDS_PYTHON", sys.executable)
    # The server's own output goes to a FILE, not to a pipe and not to nothing. A pipe nobody
    # drains fills its buffer and blocks the server mid-turn; DEVNULL throws away the one place a
    # 500 explains itself. Kept under .harness/ so it is neither a produced file nor a thing the
    # user sees, and its tail rides any failure this driver reports.
    logf = home / "agent-server.log"
    proc = subprocess.Popen(
        [python, "-m", "openhands.agent_server", "--host", "127.0.0.1", "--port", str(port)],
        cwd=cwd, env=env, stdout=logf.open("wb"), stderr=subprocess.STDOUT,
        start_new_session=False)

    base, ws_base = f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}"
    state: dict = {}
    try:
        global _STEP
        _STEP = "waiting for the agent-server to answer /alive"
        if not _wait_alive(port, proc, time.time() + 120):
            _emit("error", {"text": f"agent-server did not start: {_log_tail(logf) or 'no output'}"})
            _emit("result", {"final": "", "ok": False, "seconds": round(time.time() - _T0, 2)})
            return 1
        _STEP = "opening the conversation"
        cid, resumed = _conversation(base, key, job, cwd)
        _emit("init", {"model": job["model"], "conversation_id": cid, "resumed": resumed})
        _STEP = "running the turn"
        # No cap of this driver's own below the runner's: the runner kills the turn at the
        # harness's timeout (7200 s by default, up to MAX_TURN_SECONDS), and a second, lower
        # ceiling here ended a legitimate long turn as "timed out" while the operator's setting
        # said otherwise. The value is the runner's global ceiling, so this loop only ends what
        # the runner would have ended anyway.
        _run_turn(base, ws_base, key, cid, job["prompt"], state,
                  float(os.environ.get("HR_OPENHANDS_TURN_SECONDS", "21600")), proc=proc)
    except Exception as exc:  # noqa: BLE001 — the reason belongs in the record, not in a traceback
        tail = _log_tail(logf)
        _emit("error", {"text": f"{type(exc).__name__}: {exc} (while {_STEP})"
                                + (f" — agent-server said: {tail}" if tail else "")})
    finally:
        with contextlib.suppress(Exception):
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
        with contextlib.suppress(Exception):
            proc.kill()
        # the turn's tmux socket directory, on the normal path; a killed turn's is removed by
        # the runner's sweep, which finds it through the marker the tmux server carries
        with contextlib.suppress(Exception):
            subprocess.run(["tmux", "-L", "openhands", "kill-server"], env=env, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(env["TMUX_TMPDIR"], ignore_errors=True)

    status = state.get("status") or ""
    ok = (bool(state.get("final")) and status not in _FAILED and not state.get("timeout")
          and not state.get("server_died"))
    if state.get("server_died") and not state.get("reported_error"):
        _emit("error", {"text": "agent-server exited mid-turn: " + (_log_tail(logf) or "no output")})
        state["reported_error"] = True
    if not ok and not state.get("reported_error"):
        # A FAILED TURN CAN CARRY NO REASON AT ALL, and that is the server's design rather than a
        # gap here: event_service publishes an error event only for an exception that is NOT a
        # ConversationRunError, on the assumption that run()/arun() already emitted its own — and an
        # exception raised out of arun's error handling is precisely the case where nobody did. The
        # status flips to error and the websocket carries nothing else. Measured on the google
        # column, where every gemini follow-up died of `AttributeError:
        # 'PromptTokensDetailsWrapper' object has no attribute 'cache_creation_tokens'`, a sentence
        # that reached the server's log and no other place, leaving the record to say only "the
        # turn ended error" for eleven scenarios across five models.
        tail = _log_tail(logf)
        if tail:
            _emit("error", {"text": f"agent-server said: {tail}"})
    _emit("result", {"final": state.get("final") or "", "ok": ok, "status": status,
                     "seconds": round(time.time() - _T0, 2)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
