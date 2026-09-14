"""The kimi backend (MoonshotAI/kimi-cli, Apache-2.0, pinned to 1.50.0).

Every shape asserted here was read off the 1.50.0 artifact the installer pins, or captured from a
live turn — not from the docs. Each test pins one thing that would otherwise fail SILENTLY: the
tool call that never renders, the disabled tool that disables nothing, the lost session that
answers from an empty history as a completed turn, the provider 400 that kills every turn on one
gateway.

Source anchors (all 1.50.0):
  JsonPrinter.feed (the only emitter)  kimi_cli/ui/print/visualize.py
  _classify_provider_error             kimi_cli/ui/print/__init__.py
  openai_legacy env override           kimi_cli/llm.py:305-311
  exclude_tools (paths, not names)     kimi_cli/soul/agent.py:447-450
  Session.find / md5(work_dir)         kimi_cli/session.py, kimi_cli/metadata.py:36
  telemetry default + endpoint         kimi_cli/telemetry/transport.py:22
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (Auth, BACKENDS, _KIMI_SESSION_NAME, _KIMI_TOOL_PATHS,  # noqa: E402
                    _agent_doc_path,
                    _build_kimi, _kimi_eof, _kimi_to_claude, _normalize_openai_chat_body,
                    _resume_lost)


def _argv(**kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_kimi("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                      "kimi-k3", "do it", d, env, **kw)
    return cmd, d, env


def _norm(lines):
    state: dict = {}
    out = []
    for line in lines:
        out += _kimi_to_claude(line, state)
    return out, state


def _body(lines):
    """The turn's events with the system/init one dropped — it is asserted on its own below."""
    out, state = _norm(lines)
    return [e for e in out if e.get("subtype") != "init"], state


# ── the stream's four line shapes ────────────────────────────────────────────────
def test_assistant_text_is_a_plain_string_not_a_part_list():
    """Captured live: a text-only message carries `content` as a STRING. A normalizer that assumes
    claude's list-of-blocks (the flag name is the same, `stream-json`) renders nothing at all."""
    out, state = _body([{"role": "assistant", "content": "Created hello.txt. DONE"}])
    assert out == [{"type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Created hello.txt. DONE"}]}}]
    assert state["final"] == "Created hello.txt. DONE"


def test_tool_call_message_carries_a_list_content_and_does_not_overwrite_the_answer():
    """Captured live: the tool-carrying message has `content: []` and the answer arrives after it.
    Taking `final` from the last assistant LINE rather than the last assistant TEXT would leave the
    turn's result empty."""
    out, state = _body([
        {"role": "assistant", "content": [],
         "tool_calls": [{"type": "function", "id": "call_1",
                         "function": {"name": "WriteFile",
                                      "arguments": '{"path": "hello.txt", "content": "hi"}'}}]},
        {"role": "tool", "content": "<system>File successfully overwritten.</system>",
         "tool_call_id": "call_1"},
        {"role": "assistant", "content": "done. DONE"},
    ])
    assert state["final"] == "done. DONE"
    call = out[0]["message"]["content"][0]
    assert call["type"] == "tool_use" and call["name"] == "WriteFile" and call["id"] == "call_1"
    # arguments arrive as a JSON STRING (OpenAI's shape) and must reach the trace as an object
    assert call["input"] == {"path": "hello.txt", "content": "hi"}
    res = out[1]["message"]["content"][0]
    assert res["type"] == "tool_result" and res["tool_use_id"] == "call_1"
    assert "File successfully overwritten" in res["content"]


def test_unparseable_tool_arguments_keep_the_raw_text_instead_of_dropping_the_call():
    out, _ = _body([{"role": "assistant", "content": [],
                     "tool_calls": [{"id": "c9", "function": {"name": "Shell",
                                                              "arguments": "{not json"}}]}])
    assert out[0]["message"]["content"][0]["input"] == {"arguments": "{not json"}


def test_unknown_line_shapes_are_dropped_not_crashed():
    """Notifications and plan displays share the stream and carry no role we render."""
    seen = {"_kimi_init": True}      # the init event is emitted once, before these
    assert _kimi_to_claude({"id": "n1", "category": "task", "title": "done"}, seen) == []
    assert _kimi_to_claude({"content": "a plan", "file_path": "/tmp/p.md"}, seen) == []


# ── the turn's end: exit code is the status, and the reason comes from stdout ─────
def test_failure_exit_codes_are_the_signal():
    """kimi classifies provider failures ITSELF (Print._classify_provider_error): 75 EX_TEMPFAIL for
    connection/timeout/empty-response and 429/500/502/503/504, 1 for every other APIStatusError.
    So this backend needs no error-prose regex — unlike claude's `API Error:` and goose's `Ran into
    this error:`, a failed turn here never reads as a completed one. Registration point 6 is
    satisfied by the exit code, and this test is what pins that claim."""
    assert _kimi_eof({"final": "hi"}, 0) == [
        {"type": "result", "subtype": "success", "is_error": False, "result": "hi", "usage": {}}]
    for rc in (75, 1):
        ev = _kimi_eof({"final": "partial text"}, rc)[0]
        assert ev["is_error"] is True and ev["subtype"] == "error"
        # EMPTY on purpose: _run_turn_bg fills an empty result from the errbuf tail, where kimi's
        # bare stdout line ("Error code: 401 - {…}") is. A placeholder sentence would shadow the
        # real reason; the partial assistant text would report a 401 as if the model had answered.
        assert ev["result"] == ""


def test_usage_is_empty_because_the_stream_carries_none():
    """kimi's stream-json has no token counts at all (JsonPrinter drops StatusUpdate). Per the
    2026-09-13 decision no harness PR builds its own usage pipeline: `_relay_usage` stamps these
    rows from the provider's own bytes. goose's eof emits {} for the same reason."""
    assert _kimi_eof({"final": "x"}, 0)[0]["usage"] == {}
    assert BACKENDS["kimi"]["normalize"] is _kimi_to_claude
    assert getattr(BACKENDS["kimi"]["normalize"], "eof", None) is _kimi_eof


# ── a lost session must not answer from an empty history ─────────────────────────
def test_resume_lost_asks_the_store_because_argv_cannot_tell():
    """kimi MINTS a session with whatever id it is handed (find -> None -> create), so --session is
    on the command line whether or not the conversation exists. The argv heuristic every other
    backend uses would report "present" for a session that is gone — and the turn would answer from
    an empty history as a completed turn."""
    cmd, d, _ = _argv(resume_session_id="11111111-2222-3333-4444-555555555555")
    assert "--session" in cmd and "11111111-2222-3333-4444-555555555555" in cmd
    # the id IS in argv, and the session is still absent: the store is what decides
    assert _resume_lost("kimi", cmd, "11111111-2222-3333-4444-555555555555", d) == \
        "11111111-2222-3333-4444-555555555555"

    import hashlib
    share = pathlib.Path(d) / ".harness" / "home" / ".kimi"
    sdir = share / "sessions" / hashlib.md5(d.encode()).hexdigest() / \
        "11111111-2222-3333-4444-555555555555"
    sdir.mkdir(parents=True)
    (sdir / "context.jsonl").write_text("{}\n")
    assert _resume_lost("kimi", cmd, "11111111-2222-3333-4444-555555555555", d) is None


def test_resume_lost_keeps_the_other_backends_unchanged():
    """The generalisation must not move claude/opencode/goose off their builders' own conclusion."""
    assert _resume_lost("opencode", ["opencode", "run", "hi"], "ses_a") == "ses_a"
    assert _resume_lost("opencode", ["opencode", "--session", "ses_a", "hi"], "ses_a") is None
    assert _resume_lost("goose", ["goose", "-n", "harness"], "harness") == "harness"
    assert _resume_lost("goose", ["goose", "-n", "harness", "-r"], "harness") is None
    assert _resume_lost("hermes", ["hermes"], "s1") is None   # says so itself, not in the table


# ── argv, config and environment ─────────────────────────────────────────────────
def test_model_reaches_the_provider_through_the_config_not_the_m_flag():
    """-m names an ALIAS in config.models; the id that goes upstream is models.<alias>.model. A
    builder that put the model id on -m would be resolving it against a table that does not contain
    it, and kimi raises KeyError on that rather than substituting."""
    cmd, d, _ = _argv()
    assert cmd[cmd.index("-m") + 1] == "hr"
    cfg = (pathlib.Path(d) / ".harness" / "kimi-config.toml").read_text()
    assert 'model = "kimi-k3"' in cfg
    assert 'type = "openai_legacy"' in cfg
    assert "max_context_size = " in cfg
    # telemetry is ON by default and posts to telemetry-logs.kimi.com; there is no env kill switch,
    # which is why the config file is mandatory rather than a convenience.
    assert "telemetry = false" in cfg
    # no credential on disk: the placeholders exist only so the provider block parses
    assert "sk-t" not in cfg


def test_the_real_key_never_reaches_the_cli_and_home_is_not_touched():
    cmd, d, env = _argv()
    assert env["OPENAI_API_KEY"].startswith("hr-relay-")      # the relay bearer, not sk-t
    assert env["OPENAI_BASE_URL"] != "https://up.example/v1"
    assert env["KIMI_SHARE_DIR"] == str(pathlib.Path(d) / ".harness" / "home" / ".kimi")
    assert "HOME" not in env      # a dedicated share dir, so unlike qwen this never redirects HOME
    # rich.print hard-wraps at 80 in a non-tty, and a wrapped "Error code: 400 - {…}" reaches
    # errbuf as three fragments _failure_reason cannot match a refusal in.
    assert env["COLUMNS"] == "400"
    assert "--print" in cmd and cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[-2] == "-p" and cmd[-1] == "do it"


def test_agent_doc_is_agents_md():
    assert _agent_doc_path("/ws", "kimi").name == "AGENTS.md"


# ── tool policy: the trap that makes "hard" enforcement real or a lie ────────────
def test_excluded_tools_are_written_as_paths_never_bare_names():
    """MEASURED on 1.50.0: exclude_tools matches tool PATHS. In one probe both "Shell" (bare name)
    and "kimi_cli.tools.web:FetchURL" (path) were excluded — FetchURL disappeared from the tools
    array the model received and Shell did NOT. A bare name is a silent no-op, and the console
    would report the tool as off while the model still had it."""
    cmd, d, _ = _argv(tools_disabled=["Shell", "FetchURL"])
    spec = json.loads((pathlib.Path(d) / ".harness" / "kimi-agent.yaml").read_text())
    assert spec["agent"]["extend"] == "default"
    assert spec["agent"]["exclude_tools"] == ["kimi_cli.tools.shell:Shell",
                                              "kimi_cli.tools.web:FetchURL"]
    assert "Shell" not in spec["agent"]["exclude_tools"]
    assert "--agent-file" in cmd


def test_no_agent_file_when_nothing_is_disabled():
    cmd, d, _ = _argv()
    assert "--agent-file" not in cmd
    assert not (pathlib.Path(d) / ".harness" / "kimi-agent.yaml").exists()


def test_every_tool_path_is_a_module_path():
    for name, path in _KIMI_TOOL_PATHS.items():
        assert path.startswith("kimi_cli.tools.") and ":" in path, (name, path)


# ── MCP ──────────────────────────────────────────────────────────────────────────
def test_mcp_streamable_http_uses_url_not_httpurl():
    """The one field that differs from _qwen_settings, which inherited gemini-cli's `httpUrl`.
    kimi parses the config with fastmcp's MCPConfig, where streamable HTTP is `url`."""
    cmd, d, _ = _argv(mcp_servers=[{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp",
                                    "headers": {"X-K": "v"}}])
    cfg = json.loads((pathlib.Path(d) / ".harness" / "kimi-mcp.json").read_text())
    assert cfg == {"mcpServers": {"deepwiki": {"url": "https://mcp.deepwiki.com/mcp",
                                               "headers": {"X-K": "v"}}}}
    assert "--mcp-config-file" in cmd


def test_no_mcp_flag_when_no_servers():
    cmd, _, _ = _argv()
    assert "--mcp-config-file" not in cmd


# ── the relay repair kimi needs ──────────────────────────────────────────────────
def test_null_reasoning_effort_is_dropped_before_the_provider_sees_it():
    """kimi sends `reasoning_effort: null` on every request and Vercel's AI Gateway answers HTTP
    400 ("Invalid option: expected one of …"), measured twice in one live turn — so without this
    every kimi turn on that gateway fails before it begins. Null means "unset"; deleting the key
    says the same thing in a shape every endpoint accepts."""
    body = json.dumps({"model": "m", "reasoning_effort": None,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    out = json.loads(_normalize_openai_chat_body(body))
    assert "reasoning_effort" not in out
    assert out["messages"] == [{"role": "user", "content": "hi"}]


def test_a_real_reasoning_effort_is_left_alone():
    """Only null is touched: a chosen effort is the caller's, and _set_reasoning_effort_none sets
    "none" deliberately elsewhere."""
    for value in ("none", "minimal", "high"):
        body = json.dumps({"reasoning_effort": value,
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
        assert json.loads(_normalize_openai_chat_body(body))["reasoning_effort"] == value


# ── conversation continuity: the bug the support matrix found ────────────────────
def test_the_first_turn_names_the_session_so_the_second_can_continue_it():
    """MEASURED FAILURE this pins: with --session added only on a resume, the first turn wrote its
    history under an id nobody could name again, so every follow-up silently started a new
    conversation in the same workspace. The support matrix's recycle scenario failed on every kimi
    row while first/follow-up/switch passed — those three never ask the agent to remember
    anything, so nothing else noticed."""
    cmd, _, _ = _argv()                     # a FIRST turn: no resume id
    assert "--session" in cmd
    assert cmd[cmd.index("--session") + 1] == _KIMI_SESSION_NAME


def test_the_normalizer_reports_the_session_id_or_nothing_can_resume():
    """_run_turn_bg records the conversation id ONLY from a system/init event, and that recorded id
    is what the next turn resumes with. kimi's own stream carries no session id anywhere, so the
    runner mints one and announces it here."""
    out, _ = _norm([{"role": "assistant", "content": "hi"}])
    init = out[0]
    assert init["type"] == "system" and init["subtype"] == "init"
    assert init["session_id"] == _KIMI_SESSION_NAME


def test_the_init_event_is_emitted_once_per_turn():
    out, _ = _norm([{"role": "assistant", "content": "one"},
                    {"role": "assistant", "content": "two"}])
    assert len([e for e in out if e.get("subtype") == "init"]) == 1
