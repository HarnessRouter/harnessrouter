"""The goose backend (aaif-goose/goose, Apache-2.0, pinned to v1.50.0).

Every shape asserted here was read off the v1.50.0 source tree the installer pins, not the docs:
goose's docs name the stream-json event TYPES and publish no field-level example, which is the gap
that made the first gemini normalizer guess id/name/input and render every tool call as a
content-free row on a live turn. Each test below pins one thing that would otherwise fail
SILENTLY — the tool call that never renders, the cache counter billed as zero, the disabled tool
that disables nothing, the skills folder handed to the user as a deliverable.

Source anchors (all v1.50.0):
  StreamEvent / emit_stream_event  crates/goose-cli/src/session/mod.rs
  Message / MessageContentBlock    crates/goose-provider-types/src/conversation/message.rs
  tool_result_serde                crates/goose-provider-types/src/conversation/tool_result_serde.rs
  Paths::get_dir                   crates/goose/src/config/paths.rs
  is_tool_available gate           crates/goose/src/agents/extension_manager.rs
  permission inspector auto path   crates/goose/src/permission/permission_inspector.rs
  get_or_create_session_id         crates/goose-cli/src/cli.rs
  skill discovery roots            crates/goose/src/skills/mod.rs
"""
import pathlib
import sqlite3
import sys
import tempfile

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (Auth, ALL_GOOSE_TOOLS, BACKENDS, _agent_doc_path, _build_goose,  # noqa: E402
                    _goose_extensions, _goose_has_session, _goose_root, _goose_split_base,
                    _goose_to_claude, _goose_usage, _norm_token_usage, _resume_lost,
                    _GOOSE_SESSION_NAME)


def _argv(**kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_goose("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                       "gpt-5.4", "do it", d, env, **kw)
    return cmd, d, env


def _norm(events):
    """Feed a whole stream through the normalizer, as _run_turn_bg does."""
    state: dict = {"model": "gpt-5.4"}
    out = []
    for e in events:
        out += _goose_to_claude(e, state)
    return out, state


def _msg(*content, role="assistant", inference=None):
    meta: dict = {"userVisible": True, "agentVisible": True}
    if inference:
        meta["inference"] = inference
    return {"type": "message",
            "message": {"id": "m1", "role": role, "created": 0, "content": list(content),
                        "metadata": meta}}


# ── argv ──────────────────────────────────────────────────────────────────────────────────────
def test_argv_is_headless_stream_json():
    cmd, _, _ = _argv()
    assert cmd[:2] == ["goose", "run"]
    assert ["--output-format", "stream-json"] == cmd[2:4]
    assert ["--model", "gpt-5.4"] == cmd[4:6]
    assert ["-t", "do it"] == cmd[8:10]


def test_auto_mode_and_no_session_naming():
    """GOOSE_MODE=auto is the trust-boundary grant (nobody is attached to approve a tool), and
    session naming otherwise spends an extra background model call per turn on a name we set
    ourselves with -n."""
    _, _, env = _argv()
    assert env["GOOSE_MODE"] == "auto"
    assert env["GOOSE_DISABLE_SESSION_NAMING"] == "true"


def test_step_budget_reaches_the_cli():
    """The gateway sends the harness's max_step as max_turns (default 40). goose's own default is
    1000, so an unpassed budget is not a small drift — it is the operator's cap replaced by one 25
    times larger, and nothing says so."""
    cmd, _, _ = _argv(max_turns=40)
    assert ["--max-turns", "40"] == cmd[cmd.index("--max-turns"):cmd.index("--max-turns") + 2]


def test_no_step_budget_leaves_the_flag_off():
    """Absent or zero means "not configured": pass nothing and let the CLI's own default stand,
    rather than inventing a cap the caller never asked for."""
    for cmd, _, _ in (_argv(), _argv(max_turns=0)):
        assert "--max-turns" not in cmd


def test_no_session_flag_is_never_passed():
    """--no-session would switch off the conversation store, which is what follow-up and recycle
    both depend on. It conflicts with -n/-r in goose's own clap group, so passing it would also
    make every resume argv invalid."""
    cmd, _, _ = _argv(resume_session_id="sess_a")
    assert "--no-session" not in cmd


# ── the relay, and the two-piece endpoint ─────────────────────────────────────────────────────
def test_key_never_reaches_the_cli_and_host_is_the_relay():
    """Every turn rides the loopback relay, as qwen's and cline's do: goose takes its credential
    ONLY via env, so the real key must not be the thing in that env."""
    _, _, env = _argv()
    assert env["OPENAI_API_KEY"].startswith("hr-relay-")
    assert env["OPENAI_API_KEY"] != "sk-t"
    assert env["OPENAI_HOST"].startswith("http://127.0.0.1:")


def test_base_is_split_into_host_and_path_not_pasted_whole():
    """goose's OpenAI provider takes OPENAI_HOST (origin) and OPENAI_BASE_PATH (path) separately.
    Pasting the relay's whole URL into OPENAI_HOST sends every turn to /v1/v1/chat/completions,
    a 404 with no body — a failure that reads like the CLI simply dying."""
    assert _goose_split_base("http://127.0.0.1:5000/v1") == ("http://127.0.0.1:5000", "v1/chat/completions")
    assert _goose_split_base("http://127.0.0.1:5000") == ("http://127.0.0.1:5000", "chat/completions")
    _, _, env = _argv()
    assert env["OPENAI_BASE_PATH"] == "v1/chat/completions"
    assert "/v1" not in env["OPENAI_HOST"]


# ── one root for config, sessions and skills ──────────────────────────────────────────────────
def test_everything_lives_under_the_harness_dir():
    """GOOSE_PATH_ROOT relocates config/, data/ and state/ in one move. Inside .harness/ so the
    conversation travels in the checkpoint AND nothing goose writes is collected as a deliverable
    (_PRODUCED_EXCLUDE_PREFIX already excludes that prefix)."""
    _, d, env = _argv()
    root = pathlib.Path(env["GOOSE_PATH_ROOT"])
    assert root == _goose_root(d)
    assert root.is_absolute(), "Paths::validated_path_root drops a relative GOOSE_PATH_ROOT"
    assert ".harness" in root.parts


def test_config_names_the_provider_and_model():
    _, d, env = _argv()
    cfg = yaml.safe_load((pathlib.Path(env["GOOSE_PATH_ROOT"]) / "config" / "config.yaml").read_text())
    assert cfg["GOOSE_PROVIDER"] == "openai"
    assert cfg["GOOSE_MODEL"] == "gpt-5.4"


# ── disabled tools: a HARD block, and why it survives auto mode ───────────────────────────────
def test_disabling_a_tool_writes_an_allowlist_without_it():
    """available_tools is an allowlist, and extension_manager's fetch_all_tools skips any tool
    outside it when BUILDING THE MODEL'S TOOL LIST — so the tool never reaches the model and never
    reaches the permission inspector either. That is why GOOSE_MODE=auto returning Allow before
    consulting the permission table does not weaken this: the two are independent paths."""
    ext = _goose_extensions(None, ["shell (Shell)"])
    dev = ext["developer"]
    assert dev["type"] == "platform" and dev["enabled"] is True
    assert "shell" not in dev["available_tools"]
    assert set(dev["available_tools"]) == set(ALL_GOOSE_TOOLS) - {"shell"}


def test_no_allowlist_when_nothing_is_disabled():
    """An empty available_tools means every tool is available, so the key is written only when it
    actually restricts something — a needless allowlist would freeze the tool set against a CLI
    bump that adds one."""
    assert _goose_extensions(None, None) == {}
    assert _goose_extensions(None, ["NotAGooseTool"]) == {}


def test_extensions_map_is_partial_so_platform_defaults_survive():
    """goose seeds an entry for every platform extension this map does not mention, from that
    definition's own default_enabled, and preserves available_tools on the ones it does. Writing a
    COMPLETE map would switch off Skills, Todo and Analyze — and a harness whose skills silently
    stopped loading still passes every routing scenario."""
    ext = _goose_extensions([{"name": "deepwiki", "url": "https://mcp.example/mcp"}], ["shell"])
    assert set(ext) == {"developer", "deepwiki"}, "only what we restrict or add is named"


# ── MCP ───────────────────────────────────────────────────────────────────────────────────────
def test_remote_mcp_carries_headers():
    """UHP §4.1 puts headers/auth in the contract. goose's --with-streamable-http-extension flag
    parses only a url and timeout=N and DROPS every other k=v, so the config file — which has a
    real headers map — is the only door that can honour it. Advertising MCP support the runtime
    cannot deliver is what §4.1 forbids outright."""
    ext = _goose_extensions([{"name": "vault", "url": "https://mcp.example/mcp",
                              "headers": {"Authorization": "Bearer t"}}], None)
    assert ext["vault"]["type"] == "streamable_http"
    assert ext["vault"]["uri"] == "https://mcp.example/mcp"
    assert ext["vault"]["headers"] == {"Authorization": "Bearer t"}


def test_stdio_mcp_splits_command_and_args():
    ext = _goose_extensions([{"name": "local", "command": ["npx", "-y", "srv"],
                              "env": {"K": "v"}}], None)
    assert ext["local"] == {"enabled": True, "type": "stdio", "name": "local",
                            "cmd": "npx", "args": ["-y", "srv"], "timeout": 300,
                            "envs": {"K": "v"}}


def test_mcp_entry_without_url_or_command_is_dropped():
    assert _goose_extensions([{"name": "empty"}], None) == {}


# ── resume ────────────────────────────────────────────────────────────────────────────────────
def test_every_run_names_the_session_so_it_can_be_resumed():
    """The name is the handle in both directions. A fresh run that did not name its session could
    never be resumed: goose emits no init event, so a generated id is invisible to us."""
    cmd, _, _ = _argv()
    assert ["-n", _GOOSE_SESSION_NAME] == cmd[6:8]
    assert "-r" not in cmd


def test_the_reported_session_id_is_the_one_the_next_turn_resumes_with():
    """THE round-trip. _run_turn_bg records a conversation id only from a normalized system/init
    event, and that recorded id comes back as the next turn's resume_session_id. goose emits no
    init of its own, so the normalizer synthesizes one — and if its session_id were empty the
    gateway would store nothing and every follow-up would silently start a new conversation."""
    out, _ = _norm([_msg({"type": "text", "text": "hi"})])
    init = out[0]
    assert init["subtype"] == "init"
    assert init["session_id"] == _GOOSE_SESSION_NAME, "an empty id here breaks every follow-up"
    # and that id is exactly what the builder names the session
    cmd, _, _ = _argv(resume_session_id=init["session_id"])
    assert cmd[cmd.index("-n") + 1] == init["session_id"]


def _sessions_db(cwd: str, *rows: tuple[str, str]) -> pathlib.Path:
    """A sessions.db with goose's own schema, holding (id, name) for each row given."""
    d = _goose_root(cwd) / "data" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(d / "sessions.db")
    db.execute("CREATE TABLE IF NOT EXISTS sessions ("
               "id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', working_dir TEXT)")
    db.executemany("INSERT INTO sessions (id, name, working_dir) VALUES (?, ?, ?)",
                   [(i, n, cwd) for i, n in rows])
    db.commit()
    db.close()
    return d / "sessions.db"


def test_resume_only_once_the_session_is_in_this_workspace():
    cmd, d, env = _argv(resume_session_id=_GOOSE_SESSION_NAME)
    assert "-r" not in cmd, "nothing in the database yet, so -r would fail the turn outright"
    _sessions_db(d, ("01J-generated-id", _GOOSE_SESSION_NAME))
    cmd2 = _build_goose("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                        "gpt-5.4", "again", d, {}, resume_session_id=_GOOSE_SESSION_NAME)
    assert "-r" in cmd2


def test_session_lookup_asks_the_database():
    """THE check, and it must be exact in both directions.

    goose matches s.name == name || s.id == name (get_or_create_session_id), so both columns
    count. A schema drift on a pin bump fails HERE rather than on a live turn — which is the
    whole reason the lookup queries rather than searching bytes."""
    d = tempfile.mkdtemp()
    _sessions_db(d, ("01J-generated-id", _GOOSE_SESSION_NAME))
    assert _goose_has_session(_goose_root(d), _GOOSE_SESSION_NAME)
    assert _goose_has_session(_goose_root(d), "01J-generated-id"), "id matches too"
    assert not _goose_has_session(_goose_root(d), "some-other-session")
    assert not _goose_has_session(_goose_root(d), "")


def test_a_message_mentioning_the_workspace_path_is_not_a_session():
    """Why the byte search had to go. The session name occurs inside the workspace path that tool
    output and the AGENTS.md contract carry (/data/workspaces/<sid>/.harness/...), so a database
    holding one message and NO session matched it — and the false positive added -r, which fails
    the turn outright with "No session found": exactly what the check exists to prevent."""
    d = tempfile.mkdtemp()
    db_path = _sessions_db(d)          # schema, no rows
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE messages (session_id TEXT, content TEXT)")
    db.execute("INSERT INTO messages VALUES (?, ?)",
               ("s1", f"wrote /data/workspaces/s1/.{_GOOSE_SESSION_NAME}/goose/config/config.yaml"))
    db.commit()
    db.close()
    assert _GOOSE_SESSION_NAME.encode() in db_path.read_bytes(), "the bytes DO contain the name"
    assert not _goose_has_session(_goose_root(d), _GOOSE_SESSION_NAME), "but the session does not"


def test_a_session_still_in_the_write_ahead_log_is_visible():
    """A session the previous turn wrote can be sitting in the WAL rather than in the database
    file — that is why the old byte search read sessions.db-wal too. The query does not have to:
    sqlite reads the WAL itself. Pinned with the WAL deliberately UNCHECKPOINTED (the writer is
    still open, as goose's would be mid-run), because closing the last connection checkpoints it
    and would make this pass for the wrong reason."""
    d = tempfile.mkdtemp()
    db_path = _sessions_db(d)
    writer = sqlite3.connect(db_path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("INSERT INTO sessions (id, name, working_dir) VALUES (?, ?, ?)",
                   ("01J-b", "sess_b", d))
    writer.commit()
    try:
        wal = db_path.parent / "sessions.db-wal"
        assert wal.exists() and wal.stat().st_size > 0, "the row must really be in the WAL"
        assert _goose_has_session(_goose_root(d), "sess_b")
        assert not _goose_has_session(_goose_root(d), "sess_c")
    finally:
        writer.close()


def test_an_unreadable_database_starts_fresh_rather_than_crashing():
    """A database mid-write, truncated, or from a schema we do not know is "no session": the turn
    restarts loudly (see _resume_lost) instead of raising inside the builder."""
    d = tempfile.mkdtemp()
    base = _goose_root(d) / "data" / "sessions"
    base.mkdir(parents=True, exist_ok=True)
    (base / "sessions.db").write_bytes(b"not a database at all")
    assert not _goose_has_session(_goose_root(d), _GOOSE_SESSION_NAME)


def test_a_lost_conversation_is_reported_not_silently_restarted():
    """goose carries the id as -n on EVERY turn, so "is the id in cmd" cannot tell a fresh run
    from a resumed one — -r is the flag that means continue. Four hosted opencode sessions once
    answered three recalls each with "there is no earlier message" as COMPLETED turns because
    nothing said the history was gone."""
    cmd, _, _ = _argv(resume_session_id=_GOOSE_SESSION_NAME)
    assert _resume_lost("goose", cmd, _GOOSE_SESSION_NAME) == _GOOSE_SESSION_NAME
    assert _resume_lost("goose", cmd + ["-r"], _GOOSE_SESSION_NAME) is None


# ── the stream ────────────────────────────────────────────────────────────────────────────────
def test_assistant_text_becomes_the_answer():
    out, state = _norm([_msg({"type": "text", "text": "hello"}), {"type": "complete"}])
    assert out[0] == {"type": "system", "subtype": "init",
                      "session_id": _GOOSE_SESSION_NAME, "model": "gpt-5.4"}
    assert {"type": "text", "text": "hello"} in out[1]["message"]["content"]
    assert out[-1]["result"] == "hello"
    assert state["final"] == "hello"


def test_tool_call_fields_are_two_levels_down():
    """THE trap. The call is under toolCall.value, not on the block: `name`/`arguments`, never the
    id/name/input a claude-shaped guess would reach for. Reading the block directly yields a
    content-free "Tool" row — exactly what a live gemini turn produced before its field names were
    read off the binary."""
    out, _ = _norm([_msg({"type": "toolRequest", "id": "t1",
                          "toolCall": {"status": "success",
                                       "value": {"name": "shell", "arguments": {"command": "ls"}}}})])
    block = out[1]["message"]["content"][0]
    assert block == {"type": "tool_use", "id": "t1", "name": "shell",
                     "input": {"command": "ls"}}


def test_content_block_tags_are_camel_case_not_snake():
    """Two naming conventions in ONE stream: the top-level event tag is snake_case (message,
    complete) while the content-block tag is camelCase (toolRequest, toolResponse). Guessing one
    from the other drops every tool call and nothing errors."""
    out, _ = _norm([_msg({"type": "tool_request", "id": "t1",
                          "toolCall": {"status": "success", "value": {"name": "shell"}}})])
    assert all(b.get("type") != "tool_use"
               for e in out for b in e.get("message", {}).get("content", [])), \
        "snake_case is NOT the content-block spelling; if this ever matches, re-read the source"


def test_tool_result_text_is_unwrapped_from_the_mcp_shape():
    out, _ = _norm([_msg({"type": "toolResponse", "id": "t1",
                          "toolResult": {"status": "success",
                                         "value": {"content": [{"type": "text", "text": "out"}]}}},
                         role="user")])
    res = out[1]["message"]["content"][0]
    assert res["tool_use_id"] == "t1" and res["content"] == "out" and res["is_error"] is False


def test_failed_tool_result_carries_a_string_error():
    """tool_result_serde renders Rust's Result as {status:"error", error:"<string>"} — error is a
    STRING, not an object, so reading .message off it yields nothing."""
    out, _ = _norm([_msg({"type": "toolResponse", "id": "t1",
                          "toolResult": {"status": "error", "error": "boom"}}, role="user")])
    res = out[1]["message"]["content"][0]
    assert res["is_error"] is True and res["content"] == "boom"


def test_thinking_is_carried():
    out, _ = _norm([_msg({"type": "thinking", "thinking": "hmm", "signature": "s"})])
    assert out[1]["message"]["content"][0] == {"type": "thinking", "thinking": "hmm"}


def test_served_model_rides_the_message_metadata():
    """message.metadata.inference states what the provider actually ran, per message. The support
    matrix's rule 2 (a served model other than the one asked for is a finding) reads this."""
    out, _ = _norm([_msg({"type": "text", "text": "hi"},
                         inference={"provider": "openai", "requestedModel": "gpt-5.4",
                                    "resolvedModel": "gpt-5.4-mini"}),
                    {"type": "complete"}])
    assert out[-1]["model"] == "gpt-5.4-mini"


def test_error_event_is_terminal_and_becomes_the_result():
    """handle_agent_error emits {type:"error"} and then ends the run, so unlike gemini's
    non-fatal error this one IS the turn's cause of death."""
    out, _ = _norm([{"type": "error", "error": "provider refused"}, {"type": "complete"}])
    assert out[-1]["is_error"] is True
    assert out[-1]["result"] == "provider refused"


def test_a_provider_error_narrated_as_prose_fails_the_turn():
    """THE miss this backend had, measured on the PR-164 matrix column.

    goose does not emit StreamEvent::Error when the upstream fails mid-turn: it pushes the
    provider's sentence as ASSISTANT TEXT and then ends the run normally with `complete`. The
    turn therefore completed, its answer was the error, and the next turn in the session answered
    from a history carrying that prose. UHP asks that a turn which failed reads as failed."""
    out, state = _norm([
        _msg({"type": "text",
              "text": "Ran into this error: Server error: 503 system disk overloaded"}),
        {"type": "complete", "total_tokens": 12}])
    res = out[-1]
    assert res["subtype"] == "error" and res["is_error"] is True, "this turn FAILED"
    assert "503 system disk overloaded" in res["result"], "the provider's reason is the reason"
    assert state.get("final") in (None, ""), "the error must never become the answer"
    assert not [e for e in out if e.get("type") == "assistant"], \
        "and it is not rendered as something the model said"


def test_the_compaction_error_prefix_is_caught_too():
    """Both prefixes are verbatim in the pinned v1.50.0 binary; catching one and not the other
    would leave the same silent success on the path that is harder to reproduce."""
    out, _ = _norm([_msg({"type": "text",
                          "text": "Ran into this error trying to compact: context too large"}),
                    {"type": "complete"}])
    assert out[-1]["is_error"] is True
    assert "context too large" in out[-1]["result"]


def test_an_answer_that_merely_mentions_an_error_is_still_an_answer():
    """The match is anchored at the start of the block, so a turn that TALKS about errors — which
    a coding agent does constantly — is not turned into a failure."""
    out, state = _norm([_msg({"type": "text",
                              "text": "The build failed. Ran into this error: in their log, not "
                                      "mine — fixed by pinning the version."}),
                        {"type": "complete"}])
    assert out[-1]["subtype"] == "success" and out[-1]["is_error"] is False
    assert state["final"].startswith("The build failed.")


def test_a_failed_run_that_never_reached_complete_reports_the_error_not_the_prose():
    """Same reason on the eof path: the CLI dying after the error line must not report whatever
    text arrived earlier as the turn's result."""
    state: dict = {"model": "gpt-5.4"}
    _goose_to_claude(_msg({"type": "text", "text": "working on it"}), state)
    _goose_to_claude(_msg({"type": "text", "text": "Ran into this error: upstream 503"}), state)
    out = _goose_to_claude.eof(state, 1)
    assert out[0]["is_error"] is True
    assert "upstream 503" in out[0]["result"]


def test_notifications_render_nothing():
    out, _ = _norm([{"type": "notification", "extension_id": "developer",
                     "log": {"message": "chatter"}}])
    assert out == []


def test_complete_suppresses_the_eof_result():
    """Both would otherwise emit a result and the turn would carry two."""
    state: dict = {"model": "gpt-5.4"}
    _goose_to_claude(_msg({"type": "text", "text": "done"}), state)
    res = _goose_to_claude({"type": "complete"}, state)
    assert len(res) == 1
    assert _goose_to_claude.eof(state, 0) == []


def test_eof_without_complete_still_reports():
    """`complete` is emitted only on the normal path, so a killed or crashed CLI would otherwise
    end the turn with no result event at all — which reads as "finished, said nothing"."""
    state: dict = {"model": "gpt-5.4", "final": "partial"}
    out = _goose_to_claude.eof(state, 1)
    assert out[0]["is_error"] is True and out[0]["result"] == "partial"


# ── usage ─────────────────────────────────────────────────────────────────────────────────────
def test_cache_write_counter_is_not_dropped():
    """goose emits cache_write_input_tokens (snake). _norm_token_usage's picker knows the READ
    name but its write list carries only the camel cacheWriteInputTokens, so without the wrapper
    the write count silently bills as zero — the same class of gap as gemini's `cached`."""
    ev = {"type": "complete", "input_tokens": 100, "output_tokens": 20,
          "cache_read_input_tokens": 30, "cache_write_input_tokens": 7}
    assert _norm_token_usage(ev).get("cache_write_tokens") is None, \
        "if the shared picker learns this name, drop the wrapper instead of keeping both"
    u = _goose_usage(ev)
    assert u["cache_write_tokens"] == 7
    assert u["cache_read_tokens"] == 30
    assert u["output_tokens"] == 20


def test_usage_makes_no_unmeasured_cache_subtraction():
    """Whether input_tokens is gross or net is the provider's choice and goose passes it through,
    so no subtraction is invented here. Inventing one would under-report input on a provider that
    already reports net — the mirror of the bug the codex subtraction exists to fix. Revisit with
    a measured turn, not a guess."""
    u = _goose_usage({"input_tokens": 100, "output_tokens": 5, "cache_read_input_tokens": 30})
    assert u["input_tokens"] == 70, "this is _norm_token_usage's shared netting, not a goose rule"


# ── registration ──────────────────────────────────────────────────────────────────────────────
def test_backend_is_registered_with_its_own_normalizer():
    assert BACKENDS["goose"]["normalize"] is _goose_to_claude
    assert BACKENDS["goose"]["default_model"]


def test_agent_doc_is_agents_md():
    """goose's default context-file list is ["AGENTS.md", ".goosehints"]. Falling through to
    CLAUDE.md is silent: the file is written either way and goose never reads it, so the workspace
    contract — save deliverables to a relative path — would never reach the model."""
    assert _agent_doc_path("/w", "goose").name == "AGENTS.md"
