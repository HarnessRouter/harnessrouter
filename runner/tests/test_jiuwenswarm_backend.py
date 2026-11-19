"""The jiuwenswarm base (openJiuwen-ai/jiuwenswarm, PyPI `workswarm`), pinned at 0.2.8.

Everything asserted here was MEASURED against that build on 2026-11-18 — through a proxy that
recorded what the CLI actually sent, and through the runner's own builder and relay against a live
provider — not read off documentation. `fixtures/batch5/jiuwenswarm-denied-and-mcp.ndjson` is the
captured stream of one real turn (a tool this harness switched off, refused at the call, and an MCP
server called in the same turn), replayed through the shipped normaliser, which is the cheapest
defence against a hand-written event that agrees with the implementation and with nothing else. Two
things were dropped from that capture to keep it readable, and nothing else: the three `context.usage`
events (5.6 KB of routing identifiers each, which the normaliser ignores) and all but the first
three of its 41 `chat.delta` events, which are the same shape and are not what the answer is read
from.

Each test pins one thing that would otherwise fail SILENTLY:

  * the tool policy's DOOR — `agent.tools` is the exact hard allowlist, a per-run `deny` costs this
    base its shell, and neither can be used beside an MCP server, where only the config door reaches
    (and a budget must be left off entirely)
  * the config, which must START from the package's own template: a partial one takes `skill_tool`
    away and a declared skill is then unreachable
  * the machinery this runtime writes into the workspace, which is otherwise handed to the user as
    the task's output
  * the credential in the ENVIRONMENT, which is what makes served-model and usage readable
  * a run document that carries ONLY the fields its schema knows, since an unknown one is refused
"""
import json
import pathlib
import sys
import tempfile

import pytest
import yaml
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (ALL_JIUWENSWARM_TOOLS, Auth, BACKENDS,  # noqa: E402
                    CHECKPOINT_EXCLUDE, JIUWENSWARM_BIN, _agent_doc_path,
                    _build_jiuwenswarm, _jiuwenswarm_config, _jiuwenswarm_eof,
                    _jiuwenswarm_home, _jiuwenswarm_session_dir,
                    _jiuwenswarm_session_present, _jiuwenswarm_to_claude,
                    _resume_lost, _write_skills)

UP = "https://up.example/v1"
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "batch5"

# What `protocol.capabilities` reported on 0.2.8 (measured, free, --query-json): every field a `run`
# may carry. The builder must emit a subset of these, because the protocol's own
# `compatibility.unknown_input_fields` is "reject" — an extra field fails the run INVALID_INPUT with
# a JSON pointer rather than being ignored.
RUN_FIELDS = {"schema_version", "type", "request_id", "session_id", "input", "agent", "mode",
              "model", "skills", "mcp", "permissions", "output_schema", "max_turns",
              "max_budget_usd", "host_tools", "workspace", "timeout_seconds"}


@pytest.fixture(autouse=True)
def _a_template_is_installed(monkeypatch):
    """Every builder call needs the package's own config template, as the image's environment
    provides it: without one the builder stops the turn rather than writing a partial config, which
    is what the three cases in test_a_template_that_cannot_be_read_stops_the_turn assert."""
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", _template())


def _ws() -> str:
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / ".harness" / "home").mkdir(parents=True)
    return d


def _template(body: dict | None = None) -> str:
    """A stand-in for the package's own resources/config.yaml, named through the environment."""
    d = tempfile.mkdtemp()
    p = pathlib.Path(d) / "config.yaml"
    p.write_text(yaml.safe_dump(body if body is not None else {
        # the two keys of the real template this base depends on
        "progressive_tool_enabled": True,
        # the optional toolkits the config door drops from (the real template's own list)
        "modes": {"code": {"tools": ["web_fetch_webpage", "user_todos", "skill_toolkit"]}},
        "models": {"defaults": [{"model_client_config": {"api_base": "${API_BASE}",
                                                         "api_key": "${API_KEY}",
                                                         "model_name": "${MODEL_NAME}",
                                                         "client_provider": "${MODEL_PROVIDER}"}}]},
    }))
    return str(p)


def _build(ws: str, monkeypatch=None, **kw) -> tuple[list[str], dict]:
    env: dict = {}
    argv = _build_jiuwenswarm("openai-api", Auth(base_url=UP, api_key=""), kw.pop("model", "gpt-5.4"),
                              kw.pop("prompt", "say the word"), ws, env, **kw)
    return argv, env


def _doc(ws: str) -> dict:
    return json.loads((_jiuwenswarm_home(ws) / "run.json").read_text())


def _fixture(name: str) -> list[dict]:
    return [json.loads(l) for l in (FIX / name).read_text().splitlines() if l.strip()]


def _norm(lines, model="gpt-5.4", cwd=""):
    state: dict = {"model": model, "final": "", "cwd": cwd}
    out = []
    for ln in lines:
        out += _jiuwenswarm_to_claude(ln, state)
    return out, state


def _tool_rows(events) -> list[str]:
    names = []
    for ev in events:
        for block in ((ev.get("message") or {}).get("content") or []):
            if block.get("type") == "tool_use":
                names.append(block.get("name"))
    return names


# ── registration ──────────────────────────────────────────────────────────────────────────────

def test_the_base_is_registered():
    assert "jiuwenswarm" in BACKENDS
    assert BACKENDS["jiuwenswarm"]["providers"]
    assert BACKENDS["jiuwenswarm"]["normalize"] is _jiuwenswarm_to_claude
    assert getattr(BACKENDS["jiuwenswarm"]["normalize"], "eof", None) is _jiuwenswarm_eof


def test_the_instruction_file_is_its_own_name():
    # PROJECT_MEMORY_FILES is ("JIUWENSWARM.md", ".jiuwen/JIUWENSWARM.md"); CLAUDE.md appears only in
    # a rail's description. Measured from a turn's own request bytes: a token written in this file
    # was in the system prompt.
    ws = _ws()
    assert _agent_doc_path(ws, "jiuwenswarm") == pathlib.Path(ws) / "JIUWENSWARM.md"


def test_skills_land_in_the_one_loader_path_under_the_excluded_tree():
    ws = _ws()
    meta = _write_skills(ws, [{"name": "stamp", "content": "---\nname: stamp\n---\nrun it\n"}],
                         backend="jiuwenswarm")
    assert meta, "the bundle was not installed"
    # get_agent_skills_dir() is <data>/agent/workspace/skills and takes no override
    assert (_jiuwenswarm_home(ws) / "agent" / "workspace" / "skills" / "stamp" / "SKILL.md").is_file()
    # ...and nothing in the workspace, where it would come back as a deliverable
    assert not (pathlib.Path(ws) / "skills").exists()


def test_the_per_turn_config_and_run_document_never_ride_a_checkpoint():
    # The config carries each MCP server's headers as written; the run document carries the person's
    # prompt. The SESSION STORE beside them must travel, so the exclusions are the files.
    assert "./.harness/jiuwenswarm/config/config.yaml" in CHECKPOINT_EXCLUDE
    assert "./.harness/jiuwenswarm/run.json" in CHECKPOINT_EXCLUDE


# ── the command line, and what is not on it ───────────────────────────────────────────────────

def test_the_argv_names_the_run_document_and_not_the_prompt():
    ws = _ws()
    argv, _ = _build(ws, prompt="SECRET-PROMPT-TOKEN")
    assert argv[0] == JIUWENSWARM_BIN
    assert argv[1] == "--run-json"
    assert argv[2] == str(_jiuwenswarm_home(ws) / "run.json")
    # every process on the box can read a command line; the prompt travels in the file
    assert not any("SECRET-PROMPT-TOKEN" in part for part in argv)
    assert _doc(ws)["input"] == "SECRET-PROMPT-TOKEN"


def test_the_route_rides_the_environment_so_served_model_and_usage_are_readable():
    ws = _ws()
    env: dict = {}
    _build_jiuwenswarm("openai-api", Auth(base_url=UP, api_key=""), "gpt-5.4", "hi", ws, env)
    assert env["JIUWENSWARM_DATA_DIR"] == str(_jiuwenswarm_home(ws))
    # its OpenAI-compatible client's own four variables, which the config template's placeholders
    # read — _relay_served_model and _relay_usage find the route by the bearer in the ENVIRONMENT
    assert env["API_BASE"] == UP
    assert env["MODEL_NAME"] == "gpt-5.4"
    assert env["MODEL_PROVIDER"] == "OpenAI"
    assert "API_KEY" in env


def test_a_keyed_turn_gets_the_relays_placeholder_and_not_the_connections_key():
    ws = _ws()
    env: dict = {}
    _build_jiuwenswarm("openai-api", Auth(base_url=UP, api_key="sk-the-real-key"), "gpt-5.4",
                       "hi", ws, env)
    assert env["API_KEY"] != "sk-the-real-key"
    assert env["API_BASE"].startswith("http://127.0.0.1:")


# ── the run document ──────────────────────────────────────────────────────────────────────────

def test_the_document_carries_only_fields_the_schema_knows():
    ws = _ws()
    _build(ws, max_turns=7, tools_disabled=["bash"])
    doc = _doc(ws)
    assert set(doc) <= RUN_FIELDS, sorted(set(doc) - RUN_FIELDS)
    assert doc["type"] == "run" and doc["schema_version"] == "0.1"
    # single-agent code mode: the only mode a non-interactive run supports
    assert doc["mode"] == "agent.code.normal"
    assert doc["max_turns"] == 7


def test_no_turn_budget_rides_a_turn_that_declares_a_server():
    # _JW_MAX_TURNS_AND_MCP: `max_turns` is what makes the CLI call configure_process_cli_run, whose
    # first line walks `card.name` over an ability list that also holds McpServerConfig objects, so
    # EVERY MCP turn died with "'McpServerConfig' object has no attribute 'name'" before the first
    # model call. Measured as a single-variable A/B: the same document minus `mcp` answered.
    ws = _ws()
    _build(ws, max_turns=400, mcp_servers=[{"name": "probe", "url": "https://mcp.example/mcp"}])
    doc = _doc(ws)
    assert "max_turns" not in doc, "a budget here kills the turn before its first model call"
    assert doc["mcp"] == ["probe"]
    assert doc["timeout_seconds"] > 0, "the turn is still bounded, by the wall clock"


def test_the_workspace_the_user_collects_is_the_agents_working_directory():
    ws = _ws()
    _build(ws)
    doc = _doc(ws)
    resolved = str(pathlib.Path(ws).resolve())
    assert doc["workspace"]["cwd"] == resolved
    assert doc["workspace"]["project_dir"] == resolved


def test_the_policy_is_the_runtimes_own_allowlist_and_never_a_per_run_deny():
    # _JW_TOOL_DOORS. `agent.tools` is exact and hard (measured: `[]` produced no tool call at all).
    # The per-run `permissions.tools: deny` door refuses the named tool AND costs the shell: any run
    # permission puts the permission rail in the path of a machine run that cannot answer it, and
    # the skill's own `python3 …/stamp.py` came back `用户拒绝` on every attempt. So nothing is ever
    # written to `permissions` here.
    ws = _ws()
    _build(ws, tools_disabled=["bash", "fetch_webpage"])
    doc = _doc(ws)
    assert "permissions" not in doc, "a run permission costs this base its shell"
    assert doc["agent"]["tools"] == [t for t in ALL_JIUWENSWARM_TOOLS
                                     if t not in ("bash", "fetch_webpage")]


def test_a_turn_with_nothing_switched_off_declares_no_allowlist():
    # The sensitivity half of the test above: the key is absent because nothing was withheld, and a
    # turn that declares `tools: [...]` of everything would still install the wrapper that cannot
    # live beside an MCP server.
    ws = _ws()
    _build(ws)
    assert "tools" not in _doc(ws)["agent"]


def test_a_tool_id_this_base_does_not_have_is_not_written_into_the_policy():
    # A tool id matching nothing is dropped on the way through and disables nothing, while the
    # console reports it as off — which UHP §4.3 forbids. Only this base's own ids are withheld,
    # and a foreign one leaves the allowlist whole.
    ws = _ws()
    _build(ws, tools_disabled=["WebSearch", "bash"])
    assert _doc(ws)["agent"]["tools"] == [t for t in ALL_JIUWENSWARM_TOOLS if t != "bash"]


def test_every_offered_tool_can_really_be_withheld():
    ws = _ws()
    _build(ws, tools_disabled=list(ALL_JIUWENSWARM_TOOLS))
    assert _doc(ws)["agent"]["tools"] == []


def test_a_server_turn_withholds_fetch_webpage_in_the_config_instead():
    # The one id the config door reaches (_JW_TOOL_DOORS): `web_fetch_webpage` is simply not built,
    # so `fetch_webpage` is not in the runtime's registry and cannot be declared or called — read
    # off that registry, with the MCP server declared and the turn answering.
    ws = _ws()
    _build(ws, monkeypatch=None, tools_disabled=["fetch_webpage"],
           mcp_servers=[{"name": "probe", "url": "https://mcp.example/mcp"}])
    doc = _doc(ws)
    assert "tools" not in doc["agent"] and "permissions" not in doc
    cfg = yaml.safe_load((_jiuwenswarm_home(ws) / "config" / "config.yaml").read_text())
    assert cfg["modes"]["code"]["tools"] == ["user_todos", "skill_toolkit"]


def test_a_server_turn_refuses_a_policy_it_cannot_honour():
    # Neither door reaches `bash` while a server is declared, and the honest answer is the turn's
    # reason: reporting the tool as off while it is callable is what UHP §4.3 forbids, and dropping
    # the person's server would be the same overstatement one layer down.
    ws = _ws()
    with pytest.raises(HTTPException) as caught:
        _build(ws, tools_disabled=["bash", "fetch_webpage"],
               mcp_servers=[{"name": "probe", "url": "https://mcp.example/mcp"}])
    assert caught.value.status_code == 400
    # the reason names the tool it could NOT honour, and not the one the config door covers
    assert "switch off bash on a turn" in caught.value.detail
    assert "MCP server" in caught.value.detail


def test_ask_user_is_not_offered_because_nobody_can_answer_it():
    # The runtime declares it; a one-shot machine run has nobody attached to answer, and the
    # normaliser reports an interaction request as a turn that cannot continue.
    assert "ask_user" not in ALL_JIUWENSWARM_TOOLS


def test_a_declared_server_is_also_enabled_for_the_turn():
    # DECLARED IS NOT ENABLED: config.yaml declares a server and `run.mcp` turns it on.
    ws = _ws()
    _build(ws, mcp_servers=[{"name": "probe", "url": "https://mcp.example/mcp"},
                            {"name": "nourl"}])
    assert _doc(ws)["mcp"] == ["probe"]


def test_the_skills_in_the_library_are_named_one_by_one():
    ws = _ws()
    _write_skills(ws, [{"name": "stamp", "content": "---\nname: stamp\n---\nrun it\n"}],
                  backend="jiuwenswarm")
    _build(ws)
    assert _doc(ws)["agent"]["skills"] == ["stamp"]


# ── the config this turn writes ───────────────────────────────────────────────────────────────

def test_the_config_starts_from_the_packages_own_template(monkeypatch):
    # A partial config of our own changed which rails the runtime mounted and took `skill_tool` away
    # entirely (measured on the wire: 29 declared tools and no skill loader), so a declared skill
    # became unreachable while every test passed.
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", _template())
    ws = _ws()
    path, names = _jiuwenswarm_config(ws, None)
    written = yaml.safe_load(path.read_text())
    assert written["progressive_tool_enabled"] is True
    assert names == []
    # the model is NOT written: the placeholders resolve from the environment at read time, so the
    # relay's token never lands on disk
    entry = written["models"]["defaults"][0]["model_client_config"]
    assert entry["api_key"] == "${API_KEY}" and entry["api_base"] == "${API_BASE}"


def test_the_servers_are_asserted_as_structure_and_not_as_text(monkeypatch):
    # PARSE THE DOCUMENT, NEVER GREP IT: on another base `assert 'transport: "http"' in cfg` was
    # true at any indentation, and the indentation was wrong — the servers loaded as sibling keys
    # and the CLI refused to start, with a passing test.
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", _template())
    ws = _ws()
    path, names = _jiuwenswarm_config(ws, [{"name": "probe", "url": "https://mcp.example/mcp",
                                            "auth": "Bearer t0ken"}])
    written = yaml.safe_load(path.read_text())
    assert names == ["probe"]
    servers = written["mcp"]["servers"]
    assert isinstance(servers, list) and len(servers) == 1
    assert servers[0]["name"] == "probe"
    assert servers[0]["transport"] == "streamable-http"
    assert servers[0]["url"] == "https://mcp.example/mcp"
    assert servers[0]["enabled"] is True
    # `auth` is the bearer the gateway resolved for the harness, and its own client reads a server's
    # `headers` into the auth headers the remote server sees — eight writers once dropped `auth`
    # and left those bases with no browser at all.
    assert servers[0]["headers"]["Authorization"] == "Bearer t0ken"


def test_the_answer_follows_the_console_rather_than_the_packages_own_language(monkeypatch):
    """The template ships `preferred_language: zh` and the runtime turns it into an instruction to
    reply in that language, so this base answered in Chinese whatever language the task was written
    in — measured by hand in the console, where an English task came back "缺少 fetch_webpage 工具"
    and, with this default, "I created hello-browser.txt containing exactly HELLO." A Chinese task
    still gets a Chinese answer (measured in the same conversation): the rail is an instruction, and
    the person's own words win."""
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", _template({"preferred_language": "zh"}))
    ws = _ws()
    path, _ = _jiuwenswarm_config(ws, [])
    assert yaml.safe_load(path.read_text())["preferred_language"] == "en"
    # an operator who wants the upstream behaviour says so
    monkeypatch.setenv("HR_JIUWENSWARM_LANGUAGE", "zh")
    path, _ = _jiuwenswarm_config(ws, [])
    assert yaml.safe_load(path.read_text())["preferred_language"] == "zh"
    # and a value the runtime does not take is left to the runtime, not written through
    monkeypatch.setenv("HR_JIUWENSWARM_LANGUAGE", "fr")
    path, _ = _jiuwenswarm_config(ws, [])
    assert yaml.safe_load(path.read_text())["preferred_language"] == "zh"   # the template's own


def test_a_plugins_stdio_server_is_written_as_stdio_and_enabled(monkeypatch):
    # A plugin package's server is a COMMAND, not a url, and `build_mcp_server_config` reads
    # `command`/`args`/`env` only when the transport says stdio — an entry it cannot read is
    # dropped and returns None, which is a declared server that is silently absent. The previous
    # writer kept url servers only, so the whole plugin path went nowhere.
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", _template())
    ws = _ws()
    path, names = _jiuwenswarm_config(ws, [{"name": "fixture", "command": "/bin/server",
                                            "args": ["--stdio", "1"], "env": {"TOKEN": "t"}}])
    written = yaml.safe_load(path.read_text())
    assert names == ["fixture"]
    entry = written["mcp"]["servers"][0]
    assert entry["transport"] == "stdio" and entry["command"] == "/bin/server"
    assert entry["args"] == ["--stdio", "1"] and entry["env"] == {"TOKEN": "t"}
    assert entry["enabled"] is True and "url" not in entry
    # ...and the run document names it, because declared is not enabled on this base
    _build(ws, mcp_servers=[{"name": "fixture", "command": "/bin/server"}])
    assert _doc(ws)["mcp"] == ["fixture"]


def test_an_sse_server_keeps_the_transport_it_was_declared_with(monkeypatch):
    # This runtime has an SSE client of its own (`client_type: sse`), so relabelling one
    # streamable-http would point its client at an endpoint that speaks neither.
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", _template())
    ws = _ws()
    path, _ = _jiuwenswarm_config(ws, [{"name": "probe", "url": "https://mcp.example/sse",
                                        "transport": "sse"}])
    assert yaml.safe_load(path.read_text())["mcp"]["servers"][0]["transport"] == "sse"


def test_a_template_that_cannot_be_read_stops_the_turn(monkeypatch):
    # It does NOT fall back to a config of our own: a partial one takes `skill_tool` away, so the
    # fallback would be a turn whose declared skill is silently unreachable. A step that cannot run
    # is not a pass.
    ws = _ws()
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", "/nonexistent/config.yaml")
    with pytest.raises(HTTPException) as caught:
        _jiuwenswarm_config(ws, [{"name": "probe", "url": "https://mcp.example/mcp"}])
    assert "not found" in str(caught.value.detail)

    broken = pathlib.Path(tempfile.mkdtemp()) / "config.yaml"
    broken.write_text("a: [unclosed\n")
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", str(broken))
    with pytest.raises(HTTPException) as caught:
        _jiuwenswarm_config(ws, None)
    assert "could not be read" in str(caught.value.detail)

    notamap = pathlib.Path(tempfile.mkdtemp()) / "config.yaml"
    notamap.write_text("- just\n- a\n- list\n")
    monkeypatch.setenv("HR_JIUWENSWARM_CONFIG_TEMPLATE", str(notamap))
    with pytest.raises(HTTPException) as caught:
        _jiuwenswarm_config(ws, None)
    assert "not a mapping" in str(caught.value.detail)


# ── the machinery this runtime writes into the workspace ──────────────────────────────────────

def test_its_memory_store_and_logs_are_kept_out_of_the_produced_files_list():
    # Its machine entrypoint chdirs into workspace.cwd, so the memory store's `memory.db` and the
    # log handlers' `logs/` resolve inside the directory the user collects: a turn asked to write
    # NOTHING left fourteen of them. /produced is `git status --porcelain -uall` over that
    # directory, and .git/info/exclude is the door the agent cannot read or edit.
    ws = _ws()
    _build(ws)
    exclude = (pathlib.Path(ws) / ".git" / "info" / "exclude").read_text()
    for name in ("daily_memory/", "logs/", "memory.db", "memory.db-shm", "memory.db-wal"):
        assert name in exclude.splitlines(), name


# ── continuity ────────────────────────────────────────────────────────────────────────────────

def test_the_session_id_is_passed_only_when_the_store_has_the_conversation():
    ws = _ws()
    _build(ws, resume_session_id="process_cli_nope")
    assert "session_id" not in _doc(ws)
    assert not _jiuwenswarm_session_present(ws, [], "process_cli_nope")
    # ...and the runner reports it rather than answering from an empty history
    assert _resume_lost("jiuwenswarm", [], "process_cli_nope", ws) == "process_cli_nope"

    sid = "process_cli_1a1edf3bad0_17c672717371"
    store = _jiuwenswarm_session_dir(ws, sid)
    store.mkdir(parents=True)
    (store / "metadata.json").write_text("{}")
    assert _jiuwenswarm_session_present(ws, [], sid)
    _build(ws, resume_session_id=sid)
    assert _doc(ws)["session_id"] == sid
    assert _resume_lost("jiuwenswarm", [], sid, ws) is None


# ── the stream ────────────────────────────────────────────────────────────────────────────────

def test_a_real_turn_reports_the_session_the_answer_and_the_usage():
    ws = _ws()
    events, state = _norm(_fixture("jiuwenswarm-denied-and-mcp.ndjson"), cwd=ws)
    first = events[0]
    assert first["type"] == "system" and first["subtype"] == "init"
    assert first["session_id"] == "process_cli_1a1edfa1281_f6918bc71a9f"
    result = events[-1]
    assert result["type"] == "result" and result["subtype"] == "success"
    # the ANSWER is read off `result.output`: `chat.final` carries final_mode "patch_segment", which
    # says it is a segment of the reply rather than the reply
    assert "LOOPBACK-MCP-STAMP-404" in result["result"]
    assert result["usage"]["input_tokens"] == 97000
    assert result["usage"]["output_tokens"] == 862
    assert result["usage"]["cache_read_input_tokens"] == 64152


def test_every_call_in_a_real_turn_is_recorded_as_the_record_names_it():
    # This capture is the turn the per-run deny door was measured on: its `write_file` call came
    # back `[PERMISSION_DENIED] run policy`, and the same turn reached an MCP server through the
    # dispatchers. That door is no longer used (_JW_TOOL_DOORS: it costs the shell), so no call is
    # held back and no notice is invented — a refusal that still arrives is the tool's own result,
    # which is what every other base's rows mean too.
    ws = _ws()
    events, _ = _norm(_fixture("jiuwenswarm-denied-and-mcp.ndjson"), cwd=ws)
    rows = _tool_rows(events)
    assert "write_file" in rows, rows
    assert "mcp_hrprobe_probe_stamp" in rows
    assert not [e for e in events if e.get("subtype") == "notice"]
    refused = [b for e in events for b in ((e.get("message") or {}).get("content") or [])
               if b.get("type") == "tool_result" and "PERMISSION_DENIED" in str(b.get("content"))]
    assert refused, "the refusal the runtime reported is in the record"


def test_a_conversation_that_is_gone_is_reported_rather_than_answered_from_nothing():
    events, _ = _norm([
        {"schema_version": "0.1", "type": "result", "status": "failed", "exit_code": 1,
         "output": None, "usage": {},
         "error": {"code": "SESSION_NOT_FOUND", "message": "Session not found.",
                   "retryable": False, "details": {}}}])
    assert events[0]["type"] == "system" and events[0]["subtype"] == "resume_lost"
    assert events[-1]["is_error"] is True


def test_a_provider_failure_keeps_the_providers_own_sentence():
    # Measured with a deliberately invalid key: nothing is narrated as assistant text, so there is
    # no prefix to strip; the sentence is in error.message and the driver frames it no further
    # (the gateway already prefixes one).
    reason = ("[181001] model call failed, reason: openAI API async stream error: "
              "AuthenticationError: Error code: 401 - Authentication failed.")
    events, _ = _norm([
        {"schema_version": "0.1", "type": "event", "event_type": "chat.error",
         "payload": {"error": reason}},
        {"schema_version": "0.1", "type": "result", "status": "failed", "exit_code": 1,
         "output": None, "usage": {},
         "error": {"code": "RUNTIME_ERROR", "message": reason, "retryable": False, "details": {}}}])
    assert events[-1]["subtype"] == "error" and events[-1]["is_error"] is True
    assert events[-1]["result"] == reason
    assert not events[-1]["result"].lower().startswith("the turn failed")


def test_success_with_no_answer_is_not_a_pass():
    # Two other bases presented exactly this as a completed turn with an empty result before it was
    # caught.
    events, _ = _norm([{"schema_version": "0.1", "type": "result", "status": "completed",
                        "exit_code": 0, "output": "", "error": None, "usage": {}}])
    assert events[-1]["is_error"] is True
    assert "no answer" in events[-1]["result"]


def test_a_step_budget_reached_ends_the_turn_incomplete():
    events, _ = _norm([{"schema_version": "0.1", "type": "result", "status": "failed",
                        "exit_code": 1, "output": None, "usage": {},
                        "error": {"code": "TURN_LIMIT_EXCEEDED", "message": "turn limit",
                                  "retryable": False, "details": {}}}])
    assert events[-1]["subtype"] == "error_max_turns"


def test_an_interaction_request_is_reported_in_words():
    # The agent asked the caller a question in a run with nobody to answer it. Reported as that,
    # never as the protocol's own complaint.
    events, state = _norm([
        {"schema_version": "0.1", "type": "event", "event_type": "interaction.requested",
         "payload": {"event_type": "interaction.requested"}},
        {"schema_version": "0.1", "type": "result", "status": "completed", "exit_code": 0,
         "output": "ignored", "error": None, "usage": {}}])
    assert events[-1]["is_error"] is True
    assert "asked for input" in events[-1]["result"]


def test_a_stream_that_ends_with_no_terminal_line_fails_with_room_for_the_stderr_tail():
    state: dict = {"model": "gpt-5.4", "final": ""}
    events = _jiuwenswarm_eof(state, 1)
    assert events[-1]["is_error"] is True
    # EMPTY, so the run loop's own stderr tail is the reason: this CLI writes a short line there
    # naming its per-run diagnostic log, which is a better reason than anything invented here.
    assert events[-1]["result"] == ""


def test_an_open_tool_call_is_closed_when_the_turn_ends():
    state: dict = {"model": "gpt-5.4", "final": "done", "_jw_open": {"c1": "bash"}}
    events = _jiuwenswarm_eof(state, 0)
    assert any(b.get("type") == "tool_result" and b.get("is_error")
               for ev in events for b in ((ev.get("message") or {}).get("content") or []))
