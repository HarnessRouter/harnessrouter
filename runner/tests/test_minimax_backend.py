"""The minimax backend: MiniMax Code (MiniMax-AI/minimax-code, MIT, the `mcode` CLI, pinned to 0.5.4).

Everything asserted here was measured on the 0.5.4 release archive (npm-installed from the GitHub
asset, 2026-09-26) against a logging stub, not read off the docs. Each test pins one thing that would
otherwise fail SILENTLY or loudly in production.

Measured facts the code rests on:
  exec stream       `mcode exec --output-format stream-json`: schemaVersion 1, every line carries
                    sessionId; item.completed agent_message | reasoning | tool_call; turn.completed |
                    turn.failed; exec.completed {result} always last
  failures          STRUCTURAL: a provider 401/503 is turn.failed + exec.completed status failed,
                    exit 4, and no agent_message at all (nothing narrated as assistant text)
  endpoint          config.yaml custom_provider.<id> with a literal apiKey (no env reference);
                    selector `custom_provider:<id>/<model>`; `<id>/<model>` is refused
  resume            --session <id>; an unknown id is a hard exit 4 `Session not found`; the store
                    is sqlite v2/sqlite/runtime-state.sqlite, table local_runtime_sessions
  instructions      global $MINIMAX_DATA_DIR/AGENTS.md + ONE project file (CLAUDE.md before AGENTS.md)
  tools             config agents.default.tools allowlist; features.delegation owns task/task_append
"""
import json
import pathlib
import sqlite3
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (Auth, BACKENDS, CHECKPOINT_EXCLUDE, _HERMES_RELAY, _MINIMAX_TOOLS,  # noqa: E402
                    _mcp_headers,
                    _agent_doc_path, _build_minimax, _failure_reason, _minimax_eof,
                    _minimax_has_session, _minimax_home, _minimax_mcp_config, _minimax_to_claude,
                    _relay_served_model, _relay_usage, _resume_lost, _status_from_result,
                    _write_skills)

SID = "mvs_6e331b835f8543baab7a7ca03db202e1"


def _line(seq, typ, **kw):
    """One line as 0.5.4 writes it (the envelope fields are on every line)."""
    return {"schemaVersion": 1, "sequence": seq, "timestampMs": 1790471308260 + seq,
            "runId": "exec_turn_muj4dza2_9ouqhl", "sessionId": SID,
            "turnId": "turn_muj4dza2_9ouqhl", "type": typ, **kw}


def _norm(lines):
    state: dict = {"model": "gpt-5.4-mini", "final": ""}
    out = []
    for line in lines:
        out += _minimax_to_claude(line, state)
    return out, state


def _argv(d=None, **kw):
    d = d or tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_minimax("openai-api", Auth(api_key="sk-real-provider-key", base_url="https://up.example/v1"),
                         "minimax/minimax-m3", "do it", d, env, **kw)
    return cmd, d, env


# Captured from a live 0.5.4 run against a stub that asked for one bash call (tool1.jsonl).
_TOOL_RUN = [
    _line(1, "exec.started"), _line(2, "session.started"), _line(3, "turn.started"),
    _line(4, "item.started", item={"id": "call_1", "type": "tool_call",
                                   "toolCall": {"id": "call_1", "name": "bash", "status": 4}}),
    _line(10, "item.completed", item={"id": "call_1", "type": "tool_call", "toolCall": {
        "id": "call_1", "name": "bash", "status": 2, "input": {"command": "echo STUB-TOOL-RAN"},
        "output": {"content": [{"type": "text", "text": "STUB-TOOL-RAN\n"}],
                   "details": {"execution": {"status": "succeeded", "exitCode": 0}}}}}),
    _line(11, "item.started", item={"id": "a43d:message", "type": "agent_message", "contentDelta": "STUB-OK"}),
    _line(12, "item.completed", item={"id": "a43d:message", "type": "agent_message", "content": "STUB-OK"}),
    _line(13, "turn.completed", model={"providerId": "custom_provider:hr", "modelId": "gpt-5.4-mini",
                                       "protocol": "openai-completions"},
          usage={"inputTokens": 468, "outputTokens": 10, "cacheReadTokens": 2000, "totalTokens": 478},
          usageSource="completed_responses", durationMs=261),
    _line(14, "exec.completed", result={"schemaVersion": 1, "type": "exec.result", "status": "succeeded",
                                        "output": "STUB-OK", "runId": "r", "sessionId": SID,
                                        "turnId": "t", "durationMs": 261}),
]

# Captured from a live 0.5.4 run against a stub answering 401 (f401.jsonl).
_401 = "BYOK provider custom_provider:hr upstream error: 401 Incorrect API key provided: sk-fa***"
_FAILED_RUN = [
    _line(1, "exec.started"), _line(2, "session.started"), _line(3, "turn.started"),
    _line(4, "turn.failed", status="failed", error={"category": "runtime", "message": _401, "retryable": True},
          durationMs=22104),
    _line(5, "exec.completed", result={"schemaVersion": 1, "type": "exec.result", "status": "failed",
                                       "error": {"category": "runtime", "message": _401, "retryable": True},
                                       "runId": "r", "sessionId": SID, "turnId": "t", "durationMs": 22104}),
]


# ── the stream ───────────────────────────────────────────────────────────────────
def test_the_session_id_is_announced_once_from_the_first_line():
    """_run_turn_bg records the conversation id only from system/init; without it every follow-up
    would silently start a new conversation (the recycle lesson)."""
    out, _ = _norm(_TOOL_RUN)
    inits = [e for e in out if e.get("type") == "system" and e.get("subtype") == "init"]
    assert inits == [{"type": "system", "subtype": "init", "session_id": SID, "model": "gpt-5.4-mini"}]
    assert out[0] is inits[0]


def test_a_tool_call_renders_as_use_and_result_once_with_its_text_output():
    out, state = _norm(_TOOL_RUN)
    uses = [c for e in out if e["type"] == "assistant" for c in e["message"]["content"] if c["type"] == "tool_use"]
    results = [c for e in out if e["type"] == "user" for c in e["message"]["content"]]
    assert uses == [{"type": "tool_use", "id": "call_1", "name": "bash", "input": {"command": "echo STUB-TOOL-RAN"}}]
    assert results == [{"type": "tool_result", "tool_use_id": "call_1", "is_error": False,
                        "content": "STUB-TOOL-RAN\n"}]


def test_a_tool_call_repeated_by_the_completed_message_is_not_rendered_twice():
    call = _TOOL_RUN[4]
    out, _ = _norm([call, call])
    assert sum(1 for e in out if e["type"] == "user") == 1


def test_a_failed_tool_call_is_an_error_result_with_the_error_text():
    out, _ = _norm([_line(5, "item.completed", item={"id": "c2", "type": "tool_call", "toolCall": {
        "id": "c2", "name": "read", "status": 3, "input": {"path": "nope"},
        "error": {"content": [{"type": "text", "text": "ENOENT: no such file"}]}}})])
    res = out[-1]["message"]["content"][0]
    assert res["is_error"] is True and res["content"] == "ENOENT: no such file"


def test_streaming_deltas_are_not_rendered_only_completed_items():
    out, _ = _norm([_line(11, "item.started", item={"id": "m", "type": "agent_message", "contentDelta": "ST"}),
                    _line(11, "item.updated", item={"id": "m", "type": "agent_message", "contentDelta": "UB"})])
    assert [e for e in out if e["type"] == "assistant"] == []


def test_reasoning_is_a_thinking_block_not_the_answer():
    out, state = _norm([_line(6, "item.completed", item={"id": "m:reasoning", "type": "reasoning",
                                                         "content": "let me think"})])
    assert out[-1]["message"]["content"] == [{"type": "thinking", "thinking": "let me think"}]
    assert state["final"] == ""


def test_the_answer_is_the_result_output_and_the_result_carries_no_model_and_no_usage():
    """The CLI's `model` is the REQUESTED id and a result that names one is never checked against
    the relay (_run_turn_bg fills only an empty one): rule 2 would compare the request with itself.
    usage is left for the relay, which reads the provider's own bytes."""
    out, state = _norm(_TOOL_RUN)
    res = out[-1]
    assert res == {"type": "result", "subtype": "success", "is_error": False, "result": "STUB-OK", "usage": {}}
    assert "model" not in res
    assert _status_from_result(res, 0) == "done"


def test_a_provider_failure_fails_the_turn_with_the_provider_s_sentence():
    """Checklist #8, measured with a 401 at a stub: the failure is STRUCTURAL (turn.failed, exit 4)
    and nothing is narrated as assistant text."""
    out, state = _norm(_FAILED_RUN)
    res = out[-1]
    assert res["is_error"] is True and res["subtype"] == "error" and res["result"] == _401
    assert [e for e in out if e["type"] == "assistant"] == []
    assert _status_from_result(res, 4) == "failed"
    assert _failure_reason("", res["result"], "mcode exec failed: The run failed: …", 4) == _401


def test_an_answer_that_merely_mentions_an_error_is_still_an_answer():
    """No prefix regex exists to misfire: an agent_message is an answer whatever it says."""
    txt = "BYOK provider custom_provider:hr upstream error: 401 — that is what a bad key looks like."
    out, state = _norm([_line(12, "item.completed", item={"id": "m", "type": "agent_message", "content": txt}),
                        _line(14, "exec.completed", result={"status": "succeeded", "output": txt})])
    assert out[-1]["is_error"] is False and out[-1]["result"] == txt


def test_the_step_budget_is_max_turns_and_a_timeout_says_so():
    out, _ = _norm([_line(9, "exec.completed", result={"status": "limit_exceeded"})])
    assert out[-1]["subtype"] == "error_max_turns"
    assert _status_from_result(out[-1], 7) == "max_turns"
    out, _ = _norm([_line(9, "exec.completed", result={"status": "timeout"})])
    assert out[-1]["is_error"] and "timed out" in out[-1]["result"]


def test_a_run_that_died_before_the_stream_leaves_the_reason_to_its_stderr_line():
    """`--session <unknown>` and an invalid config print one stderr line and exit non-zero with
    nothing on stdout; an empty result lets the run loop fill it from that line."""
    res = _minimax_eof({"final": ""}, 4)
    assert res == [{"type": "result", "subtype": "error", "is_error": True, "result": "", "usage": {}}]
    assert _minimax_to_claude.eof is _minimax_eof


# ── the builder ──────────────────────────────────────────────────────────────────
def test_argv_is_exec_stream_json_full_permission_and_the_custom_provider_selector():
    cmd, d, env = _argv(max_turns=40)
    assert cmd[:6] == ["mcode", "exec", "--output-format", "stream-json", "--permission", "full"]
    assert cmd[cmd.index("--model") + 1] == "custom_provider:hr/minimax/minimax-m3"
    assert cmd[cmd.index("--max-steps") + 1] == "40"
    assert cmd[-2:] == ["--", "do it"]          # a prompt starting with "-" stays the prompt
    assert "--session" not in cmd


def test_the_run_is_not_capped_with_the_cli_s_own_timeout_flag():
    """`--timeout` would bound this CLI's five-retry storm and REPLACE the reason: measured at a stub
    answering 401, `--timeout 8s` ended the run as `status: timeout` with an empty error message, so
    the provider's own sentence was lost. The turn's wall-clock cap is the runner's, which does not
    rewrite the reason."""
    cmd, _, _ = _argv()
    assert "--timeout" not in cmd


def test_the_real_key_never_reaches_the_sandbox_and_the_relay_token_is_in_env():
    """Checklist #19: _relay_served_model/_relay_usage find the route by the bearer in ENV."""
    cmd, d, env = _argv()
    home = _minimax_home(pathlib.Path(d))
    cfg_text = (home / "config.yaml").read_text()
    assert "sk-real-provider-key" not in cfg_text
    assert "sk-real-provider-key" not in json.dumps(env) and "sk-real-provider-key" not in " ".join(cmd)
    tok = env["MCODE_PROVIDER_API_KEY"]
    assert tok.startswith("hr-relay-") and tok in _HERMES_RELAY["routes"]
    cfg = yaml.safe_load(cfg_text)
    prov = cfg["custom_provider"]["hr"]
    assert prov["api"] == "openai-completions"
    assert prov["options"]["apiKey"] == tok
    assert prov["options"]["baseURL"].startswith("http://127.0.0.1:")
    assert list(prov["models"]) == ["minimax/minimax-m3"]
    assert cfg["defaultModel"] == "custom_provider:hr/minimax/minimax-m3"
    assert (home / "config.yaml").stat().st_mode & 0o077 == 0
    assert env["MINIMAX_DATA_DIR"] == str(home)
    assert env["MCODE_DISABLE_TELEMETRY"] == "1"
    # the relay route is what the served-model and usage readers resolve from this env
    _HERMES_RELAY["routes"][tok][2]["served_model"] = "minimax/minimax-m3"
    _HERMES_RELAY["routes"][tok][2]["usage"] = {"input_tokens": 5}
    assert _relay_served_model(env) == "minimax/minimax-m3"
    assert _relay_usage(env) == {"input_tokens": 5}


def test_unknown_provider_and_missing_base_url_are_refused():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _build_minimax("bedrock", Auth(api_key="k", base_url="https://x/v1"), "m", "p", tempfile.mkdtemp(), {})
    with pytest.raises(HTTPException):
        _build_minimax("openai-api", Auth(api_key="k"), "m", "p", tempfile.mkdtemp(), {})


def _policy(**kw):
    cmd, d, env = _argv(**kw)
    return yaml.safe_load((_minimax_home(pathlib.Path(d)) / "config.yaml").read_text())


def test_the_default_policy_offers_the_tools_and_never_minimax_account_services():
    cfg = _policy()
    pol = cfg["agents"]["default"]
    assert pol["tools"] == ["bash", "read", "write", "edit", "grep", "glob", "todowrite", "web_fetch",
                            "task_query", "task_output", "task_stop"]
    assert "website_deploy" not in pol["tools"]
    assert pol["builtinTools"] == [] and pol["skills"] == []
    assert pol["features"] == {"webSearch": False, "delegation": True}
    assert cfg["skills"] == {"external": {"enabled": False}}
    assert cfg["telemetry"] == {"enabled": False, "metrics": False, "diagnostics": False}


def test_a_disabled_tool_is_left_out_and_takes_its_companions_and_the_subagents_with_it():
    pol = _policy(tools_disabled=["bash"])["agents"]["default"]
    assert "bash" not in pol["tools"] and "task_output" not in pol["tools"]
    assert pol["features"]["delegation"] is False      # a subagent would bring bash back
    pol = _policy(tools_disabled=["task"])["agents"]["default"]
    assert "bash" in pol["tools"] and pol["features"]["delegation"] is False


def test_the_allowlist_always_names_one_task_control_tool_because_naming_none_returns_all_three():
    """The CLI's tolerant parser pushes ALL THREE task-control ids onto a list that names NONE of
    them (parseTolerantAgentCapabilityConfig, 0.5.4). Measured: a first version that simply dropped
    them with bash saw the CLI send task_query, task_output and task_stop to the provider anyway. So
    one is named on purpose and the other two are excluded — task_stop, the only one that can neither
    start nor read anything."""
    off = _policy(tools_disabled=["bash"])["agents"]["default"]["tools"]
    assert [t for t in off if t.startswith("task_")] == ["task_stop"]
    on = _policy()["agents"]["default"]["tools"]
    assert [t for t in on if t.startswith("task_")] == ["task_query", "task_output", "task_stop"]
    # and never the spawn tool, whose subagent carries its own shell
    assert "task" not in off and "task" not in on


def test_a_name_the_cli_does_not_know_disables_nothing_and_changes_nothing():
    assert _policy(tools_disabled=["WebSearch"])["agents"]["default"] == _policy()["agents"]["default"]


def _store(d, sid=SID, keep_open=False):
    """The session table as 0.5.4 creates it (its leading columns), written the way the CLI writes
    it: WAL mode, and optionally with the writer still OPEN so the row lives only in the WAL."""
    db = _minimax_home(pathlib.Path(d)) / "v2" / "sqlite" / "runtime-state.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE IF NOT EXISTS local_runtime_sessions (session_id TEXT PRIMARY KEY, "
                "record_json TEXT NOT NULL, updated_at_ms INTEGER NOT NULL, workspace_dir TEXT)")
    con.execute("INSERT INTO local_runtime_sessions VALUES (?, '{}', 1, ?)", (sid, str(d)))
    con.commit()
    if keep_open:
        return con
    con.close()
    return None


def test_a_session_the_store_holds_is_resumed_and_one_it_does_not_hold_is_never_passed():
    d = tempfile.mkdtemp()
    cmd, _, _ = _argv(d, resume_session_id=SID)
    assert "--session" not in cmd                       # no store yet: an unknown id is exit 4
    assert _resume_lost("minimax", cmd, SID, d) == SID
    _store(d)
    cmd, _, _ = _argv(d, resume_session_id=SID)
    assert cmd[cmd.index("--session") + 1] == SID
    assert cmd.index("--session") < cmd.index("--")
    assert _resume_lost("minimax", cmd, SID, d) is None
    cmd, _, _ = _argv(d, resume_session_id="mvs_00000000000000000000000000000000")
    assert "--session" not in cmd


def test_the_store_is_asked_through_the_wal_with_the_writer_still_open():
    """Checklist #10: closing the last connection checkpoints the WAL, so a test that closes it
    passes for the wrong reason. The row here exists only in the WAL."""
    d = tempfile.mkdtemp()
    con = _store(d, keep_open=True)
    try:
        assert _minimax_has_session(_minimax_home(pathlib.Path(d)), SID)
    finally:
        con.close()


def test_the_store_lookup_is_a_query_not_a_byte_search():
    """goose's lesson: the id occurring in some OTHER column (a workspace path, a transcript) is not
    a session."""
    d = tempfile.mkdtemp()
    _store(d, sid="mvs_other")
    home = _minimax_home(pathlib.Path(d))
    con = sqlite3.connect(str(home / "v2" / "sqlite" / "runtime-state.sqlite"))
    con.execute("UPDATE local_runtime_sessions SET record_json = ?", (json.dumps({"note": SID}),))
    con.commit(); con.close()
    assert not _minimax_has_session(home, SID)
    assert not _minimax_has_session(home, "")


def test_mcp_servers_carry_the_declared_transport_and_the_resolved_bearer():
    d = pathlib.Path(tempfile.mkdtemp())
    p = _minimax_mcp_config(d, [
        {"name": "deep wiki", "url": "https://mcp.deepwiki.com/sse", "transport": "sse"},
        {"name": "ctx", "url": "https://mcp.example/mcp", "auth": "tok123", "headers": {"X-A": "1"}},
        {"name": "probe", "command": ["python3", "probe.py"], "args": ["--x"], "env": {"A": "b"}},
        {"name": "nothing"},
    ])
    servers = json.loads(p.read_text())["mcpServers"]
    assert servers["deep_wiki"] == {"type": "sse", "url": "https://mcp.deepwiki.com/sse"}
    assert servers["ctx"] == {"type": "http", "url": "https://mcp.example/mcp",
                              "headers": {"Authorization": "Bearer tok123", "X-A": "1"}}
    # the bearer comes from the ONE helper every writer shares: eight writers that kept their own
    # copy dropped `auth` and lost the browser plug entirely (the browser column, 2026-09-27)
    assert servers["ctx"]["headers"] == _mcp_headers({"auth": "tok123", "headers": {"X-A": "1"}})
    assert servers["probe"] == {"command": "python3", "args": ["probe.py", "--x"], "env": {"A": "b"}}
    assert "nothing" not in servers


def test_the_mcp_file_is_rewritten_every_turn_so_a_removed_server_is_gone():
    d = tempfile.mkdtemp()
    _argv(d, mcp_servers=[{"name": "a", "url": "https://a.example/mcp"}])
    _argv(d)
    assert json.loads((_minimax_home(pathlib.Path(d)) / "mcp.json").read_text()) == {"mcpServers": {}}


# ── registration ─────────────────────────────────────────────────────────────────
def test_the_agent_doc_is_the_global_agents_md_that_no_workspace_claude_md_can_shadow():
    d = tempfile.mkdtemp()
    assert _agent_doc_path(d, "minimax") == _minimax_home(pathlib.Path(d)) / "AGENTS.md"


def test_skills_land_in_the_cli_s_own_skill_root_under_the_harness_dir():
    d = tempfile.mkdtemp()
    got = _write_skills(d, [{"name": "probe-skill", "files": [
        {"path": "SKILL.md", "content": "---\nname: probe-skill\ndescription: x\n---\nbody\n"}]}], "minimax")
    assert got and (_minimax_home(pathlib.Path(d)) / "skills" / "probe-skill" / "SKILL.md").is_file()


def test_registry_checkpoint_and_tool_names():
    assert BACKENDS["minimax"]["normalize"] is _minimax_to_claude
    assert BACKENDS["minimax"]["default_model"] == "minimax-m3"
    for p in ("./.harness/home/.minimax/config.yaml", "./.harness/home/.minimax/mcp.json",
              "./.harness/home/.minimax/auth", "./.harness/home/.local/share/Trash"):
        assert p in CHECKPOINT_EXCLUDE
    # the session store must travel, or a follow-up after a recycle forgets everything
    assert not any(x.startswith("./.harness/home/.minimax/v2/s") or x == "./.harness/home/.minimax"
                   for x in CHECKPOINT_EXCLUDE)
    assert _MINIMAX_TOOLS == ("bash", "read", "write", "edit", "grep", "glob", "todowrite", "web_fetch", "task")
