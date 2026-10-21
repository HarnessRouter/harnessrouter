"""The bases added in batch 4: vibe (mistral-vibe), docker-agent and
fast-agent.

Everything asserted here was MEASURED against the pinned build named beside it, on 2026-10-14/15,
through a proxy that recorded what the CLI actually sent — not read off documentation. The fixtures
under fixtures/batch4/ are the captured streams and exports of those runs, replayed through the
shipped normaliser, which is the cheapest defence against a hand-written event that agrees with the
implementation and with nothing else.

Each test pins one thing that would otherwise fail SILENTLY:

  * the per-turn model, which a resumed session would otherwise take back (no --model flag exists)
  * the trust flag, without which the workspace's AGENTS.md is read by nobody
  * a provider failure that must not be scored as an answer
  * the export this turn wrote, never the one the last turn left behind
  * the credential in the ENVIRONMENT, which is what makes served-model and usage readable

Pinned builds: mistral-vibe 2.26.1 · docker-agent v1.150.0 · fast-agent-mcp 0.10.45
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (ALL_VIBE_TOOLS, Auth, BACKENDS,  # noqa: E402
                    CHECKPOINT_EXCLUDE, _PRODUCED_EXCLUDE_PREFIX,
                    _agent_doc_path, _build_vibe,
                    _BRIDGED_TRANSPORTS, _vibe_eof, _vibe_home, _vibe_out,
                    _vibe_session_present, _vibe_to_claude, _resume_lost, _write_skills,
                    ALL_DOCKER_AGENT_TOOLS, _build_docker_agent, _docker_agent_eof,
                    _docker_agent_home, _docker_agent_session_db, _sse_bridges,
                    _docker_agent_session_present, _docker_agent_to_claude,
                    ALL_FAST_AGENT_TOOLS, _build_fast_agent, _fast_agent_eof,
                    _record_cli_session_id,
                    _fast_agent_home, _fast_agent_session_file,
                    _fast_agent_session_present, _fast_agent_set_model,
                    _fast_agent_to_claude, _fast_agent_traj)

UP = "https://up.example/v1"
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "batch4"


def _ws() -> str:
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / ".harness" / "home").mkdir(parents=True)
    return d


def _norm(lines, model="gpt-5.4", cwd=""):
    state: dict = {"model": model, "final": "", "cwd": cwd}
    out = []
    for ln in lines:
        out += _vibe_to_claude(ln, state)
    return out, state


def _fixture(name: str) -> list[dict]:
    return [json.loads(l) for l in (FIX / name).read_text().splitlines() if l.strip()]


def _export(cwd: str, name: str) -> None:
    out = _vibe_out(cwd)
    out.mkdir(parents=True, exist_ok=True)
    (out / "export.json").write_text((FIX / name).read_text())


# ── registration ──────────────────────────────────────────────────────────────────────────────

def test_the_base_is_registered():
    assert "vibe" in BACKENDS
    assert BACKENDS["vibe"]["providers"]
    assert BACKENDS["vibe"]["normalize"] is _vibe_to_claude
    assert getattr(BACKENDS["vibe"]["normalize"], "eof", None) is _vibe_eof


def test_the_instruction_file_is_agents_md():
    ws = _ws()
    assert _agent_doc_path(ws, "vibe") == pathlib.Path(ws) / "AGENTS.md"


def test_skills_land_in_a_loader_path_under_the_excluded_tree():
    ws = _ws()
    meta = _write_skills(ws, [{"name": "stamp", "content": "---\nname: stamp\n---\nrun it\n"}],
                         backend="vibe")
    assert meta, "the bundle was not installed"
    # $VIBE_HOME/skills is one of its two global roots, and VIBE_HOME is .harness/vibe/home
    assert (_vibe_home(ws) / "skills" / "stamp" / "SKILL.md").is_file()
    # and nothing was written into the workspace, where it would come back as a deliverable
    assert not (pathlib.Path(ws) / "skills").exists()
    assert not (pathlib.Path(ws) / ".vibe").exists()


def test_only_sse_is_bridged():
    # its mcp_servers take http / streamable-http / stdio; the product's own servers are
    # streamable HTTP, so only an SSE server a harness declares needs the bridge
    assert _BRIDGED_TRANSPORTS["vibe"] == ("sse",)


# ── the two flags that are the whole difference between working and silently not ───────────────

def test_the_turn_carries_trust_and_a_profile_that_names_this_turns_model():
    ws = _ws()
    cmd = _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    assert "--trust" in cmd, "without it a programmatic run ignores the project's AGENTS.md"
    assert cmd[cmd.index("--agent") + 1] == "harness"
    profile = (_vibe_home(ws) / "agents" / "harness.toml").read_text()
    assert 'active_model = "gpt-5.4"' in profile
    # the config names the same model, so a FIRST turn (which has no session to restore from) runs
    # on it too
    assert 'active_model = "gpt-5.4"' in (_vibe_home(ws) / "config.toml").read_text()


def test_a_switch_rewrites_the_profile_rather_than_trusting_the_session():
    ws = _ws()
    _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "one", ws, {})
    _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "claude-haiku-5.5", "two", ws, {})
    profile = (_vibe_home(ws) / "agents" / "harness.toml").read_text()
    assert 'active_model = "claude-haiku-5.5"' in profile
    assert "gpt-5.4" not in profile


def test_the_credential_is_in_the_environment_not_only_in_a_file():
    # _relay_served_model and _relay_usage find the turn's route by the placeholder bearer among
    # the env values; a credential that lives only in config.toml leaves both unevaluable
    ws, env = _ws(), {}
    _build_vibe("openai-api", Auth(base_url=UP, api_key="real-key"), "gpt-5.4", "hi", ws, env)
    assert env["HR_VIBE_RELAY_KEY"].startswith("hr-relay-")
    assert "real-key" not in json.dumps(env), "the connection's own key reached the CLI"
    cfg = (_vibe_home(ws) / "config.toml").read_text()
    assert 'api_key_env_var = "HR_VIBE_RELAY_KEY"' in cfg
    assert "real-key" not in cfg
    assert env["VIBE_HOME"] == str(_vibe_home(ws))


def test_the_defaults_that_would_cost_money_or_leak_are_off():
    ws = _ws()
    _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    cfg = (_vibe_home(ws) / "config.toml").read_text()
    for line in ("enable_telemetry = false", "enable_update_checks = false",
                 "enable_auto_update = false", "generate_titles = false"):
        assert line in cfg, line


def test_resume_is_passed_only_when_the_store_holds_the_conversation():
    ws = _ws()
    sid = "dbd7c9b9-9af1-47e6-53a9-49dba340c915"
    cmd = _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                      resume_session_id=sid)
    assert "--resume" not in cmd
    # and the runner then TELLS the user the conversation was not continued
    assert _resume_lost("vibe", cmd, sid, ws) == sid
    (_vibe_home(ws) / "logs" / "session" / "unified" / sid).mkdir(parents=True)
    cmd = _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                      resume_session_id=sid)
    assert cmd[cmd.index("--resume") + 1] == sid
    assert _vibe_session_present(ws, cmd, sid) is True
    assert _resume_lost("vibe", cmd, sid, ws) is None


def test_a_disabled_tool_is_named_on_the_command_line():
    ws = _ws()
    cmd = _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                      tools_disabled=["web_search", "web_fetch"])
    assert cmd.count("--disabled-tools") == 2
    assert "web_search" in cmd and "web_fetch" in cmd


def test_the_previous_turns_export_cannot_answer_for_this_one():
    ws = _ws()
    _export(ws, "vibe-export-finished.json")
    # --output-dir also copies the session journal in beside the export; the whole directory is
    # cleared, so neither the verdict nor the copy can be last turn's
    (_vibe_out(ws) / "session" / "journal").mkdir(parents=True, exist_ok=True)
    _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    assert not (_vibe_out(ws) / "export.json").exists(), (
        "a turn that dies before writing an export would be scored by the last turn's outcome")
    assert not (_vibe_out(ws) / "session").exists()


def test_the_state_that_may_carry_a_credential_never_travels_in_a_checkpoint():
    # config.toml can hold an MCP server's Authorization header, and $VIBE_HOME/.env is where its
    # own setup wizard writes an API key
    for path in ("./.harness/vibe/home/config.toml", "./.harness/vibe/home/.env",
                 "./.harness/vibe/out"):
        assert path in CHECKPOINT_EXCLUDE, path
    # and the session store itself DOES travel, or --resume dies on every recycle
    assert not any("logs/session" in p for p in CHECKPOINT_EXCLUDE if "vibe" in p)


def test_an_mcp_server_carries_the_bearer_the_gateway_minted():
    ws = _ws()
    _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                mcp_servers=[{"name": "plugs", "url": "https://p.example/mcp", "transport": "http",
                              "auth": "tok-123"}])
    cfg = (_vibe_home(ws) / "config.toml").read_text()
    assert 'transport = "streamable-http"' in cfg
    assert 'url = "https://p.example/mcp"' in cfg
    assert '"Authorization" = "Bearer tok-123"' in cfg, "the auth the shared helper resolved"


# ── the normaliser, replaying the captured streams ─────────────────────────────────────────────

def test_a_tool_call_and_an_answer_come_off_the_real_stream():
    ws = _ws()
    _export(ws, "vibe-export-finished.json")
    evs, state = _norm(_fixture("vibe-write-file.ndjson"), cwd=ws)
    kinds = [(e.get("type"), e.get("subtype") or
              (e.get("message", {}).get("content") or [{}])[0].get("type")) for e in evs]
    assert ("system", "init") == kinds[0]
    assert evs[0]["session_id"] == "dbd7c9b9-9af1-47e6-53a9-49dba340c915"
    assert ("assistant", "tool_use") in kinds
    assert ("user", "tool_result") in kinds
    call = next(e for e in evs if (e.get("message", {}).get("content") or [{}])[0].get("type") == "tool_use")
    block = call["message"]["content"][0]
    assert block["name"] == "file_system.write_file"
    assert block["input"]["content"] == "SWITCHED"
    assert "READY" in state["final"]
    res = _vibe_eof(state, 0)[-1]
    assert res["subtype"] == "success" and res["is_error"] is False
    assert res["usage"]["input_tokens"] > 0 and res["usage"]["output_tokens"] > 0


def test_the_prompts_own_echo_is_never_rendered():
    # the first entry of every turn is the user's message played back. A judge that reads the
    # transcript tail must not be able to satisfy a recall check with the prompt's own copy of the
    # answer — the rig defect that passed 593 of 596 rows in batch 3.
    evs, _ = _norm(_fixture("vibe-write-file.ndjson"), cwd=_ws())
    for e in evs:
        if e.get("type") == "user":
            blocks = e["message"]["content"]
            assert all(b.get("type") == "tool_result" for b in blocks), blocks


def test_an_entry_seen_twice_is_counted_once():
    ws = _ws()
    lines = _fixture("vibe-write-file.ndjson")
    evs, _ = _norm(lines + lines, cwd=ws)
    tool_uses = [e for e in evs
                 if (e.get("message", {}).get("content") or [{}])[0].get("type") == "tool_use"]
    assert len(tool_uses) == 1


def test_a_refused_call_is_a_note_on_the_reply_and_not_a_tool_row():
    """Measured with write_file and edit disabled: the tool is still DECLARED to the model, the
    model called it, and the call came back `decision: "skip"` / `error.code: "tool_denied"` with
    nothing written.

    On every other base a disabled tool is withheld, so a turn's tool list means "what ran". The
    custom-harness dimension reads that list to decide whether a withheld tool stayed unused, so
    recording the attempt as a call would fail a row for something that never happened — while
    swallowing it would hide from the user that their own switch stopped the agent."""
    ws = _ws()
    _export(ws, "vibe-export-tool-denied.json")
    evs, state = _norm(_fixture("vibe-tool-denied.ndjson"), cwd=ws)
    assert not [e for e in evs
                if (e.get("message", {}).get("content") or [{}])[0].get("type") == "tool_use"]
    notes = [e for e in evs if e.get("type") == "system" and e.get("subtype") == "notice"]
    assert len(notes) == 1 and "file_system.write_file" in notes[0]["text"]
    assert "switched off" in notes[0]["text"]
    # the turn itself still completed, and the model's own account of it is the answer
    res = _vibe_eof(state, 0)[-1]
    assert res["subtype"] == "success"
    assert "denied" in state["final"].lower()


def test_a_tool_that_merely_failed_is_still_a_tool_row():
    # only a POLICY refusal becomes a note; a tool that ran and failed is a call that happened
    entry = {"id": "effect-1", "sessionId": "s1", "type": "effect",
             "detail": {"toolName": "bash", "input": {"command": "false"}},
             "state": {"status": "failed", "decision": "execute",
                       "error": {"message": "exit 1", "code": "tool_error"},
                       "outputText": "exit 1", "display": {"success": False}}}
    evs, _ = _norm([entry], cwd=_ws())
    kinds = [(e.get("message", {}).get("content") or [{}])[0].get("type") for e in evs]
    assert "tool_use" in kinds and "tool_result" in kinds
    assert not [e for e in evs if e.get("subtype") == "notice"]


def test_a_provider_failure_fails_the_turn_and_keeps_its_reason():
    ws = _ws()
    _export(ws, "vibe-export-provider-401.json")
    evs, state = _norm(_fixture("vibe-provider-401.ndjson"), cwd=ws)
    assert not [e for e in evs if e.get("type") == "assistant"], "a failed turn answered nothing"
    res = _vibe_eof(state, 1)[-1]
    assert res["subtype"] == "error" and res["is_error"] is True
    assert "Invalid API key" in res["result"], "the reason the CLI reported is the reason stored"


def test_a_run_killed_before_its_export_leaves_the_reason_to_stderr():
    # no export at all: an empty result lets _failure_reason's stderr tail through rather than
    # shadowing it with a placeholder of ours
    res = _vibe_eof({"model": "gpt-5.4", "final": "", "cwd": _ws()}, -9)[-1]
    assert res["is_error"] is True and res["result"] == ""


def test_a_limit_is_reported_as_what_it_was():
    ws = _ws()
    out = _vibe_out(ws)
    out.mkdir(parents=True, exist_ok=True)
    (out / "export.json").write_text(json.dumps(
        {"outcome": "turn_limit", "error": None, "usage": {"input_tokens": 10, "output_tokens": 2}}))
    res = _vibe_eof({"model": "gpt-5.4", "final": "partial work", "cwd": ws}, 3)[-1]
    assert res["is_error"] is True
    assert "turn limit" in res["result"]


def test_the_tool_list_is_the_one_the_catalog_publishes():
    # held to the gateway's own list by gateway/tests/test_vibe_tools.py; here it only has to be
    # the measured set rather than a guess
    assert "bash" in ALL_VIBE_TOOLS and "run_typescript" in ALL_VIBE_TOOLS
    assert "search_tool_functions" in ALL_VIBE_TOOLS


# ══ docker-agent (Docker Agent v1.150.0) ══════════════════════════════════════════════════════

def _da_norm(lines, model="gpt-5.4", cwd=""):
    state: dict = {"model": model, "final": "", "cwd": cwd}
    out = []
    for ln in lines:
        out += _docker_agent_to_claude(ln, state)
    return out, state


def _da_cfg(ws: str) -> str:
    return (_docker_agent_home(ws) / "agent.yaml").read_text()


def test_docker_agent_is_registered_and_reads_agents_md():
    assert "docker-agent" in BACKENDS
    assert BACKENDS["docker-agent"]["normalize"] is _docker_agent_to_claude
    assert getattr(BACKENDS["docker-agent"]["normalize"], "eof", None) is _docker_agent_eof
    ws = _ws()
    assert _agent_doc_path(ws, "docker-agent") == pathlib.Path(ws) / "AGENTS.md"


def test_the_config_needs_version_eight_for_a_provider_section():
    # version 2 is refused outright, with a hint naming the version that supports `providers`
    ws = _ws()
    _build_docker_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    cfg = _da_cfg(ws)
    assert 'version: "8"' in cfg
    assert "providers:" in cfg and 'api_type: openai_chatcompletions' in cfg
    assert 'token_key: "HR_DOCKER_AGENT_RELAY_KEY"' in cfg
    assert "add_prompt_files:" in cfg and "- AGENTS.md" in cfg


def test_the_harness_session_id_is_the_clis_own_and_the_store_is_asked_about_it():
    ws, env = _ws(), {}
    sid = "hr-e2e-session-1"
    cmd = _build_docker_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws,
                              env, resume_session_id=sid)
    assert cmd[cmd.index("--session") + 1] == sid, "no mapping: the id travels as it is"
    assert cmd[cmd.index("--session-db") + 1] == str(_docker_agent_session_db(ws))
    # --session CREATES an unknown id as a new conversation, so the store decides, not the argv
    assert _docker_agent_session_present(ws, cmd, sid) is False
    assert _resume_lost("docker-agent", cmd, sid, ws) == sid
    import sqlite3
    db = _docker_agent_session_db(ws)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT, title TEXT)")
    con.execute("INSERT INTO sessions VALUES (?, ?)", (sid, "t"))
    con.commit(); con.close()
    assert _docker_agent_session_present(ws, cmd, sid) is True
    assert _resume_lost("docker-agent", cmd, sid, ws) is None
    # and an id nothing wrote is still absent
    assert _docker_agent_session_present(ws, cmd, "hr-never-ran") is False


def test_a_turn_without_a_resume_id_gets_one_of_its_own():
    ws = _ws()
    cmd = _build_docker_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    assert cmd[cmd.index("--session") + 1].startswith("hr-")


def test_a_disabled_tool_is_withheld_by_narrowing_its_toolsets_include_list():
    ws = _ws()
    _build_docker_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                        tools_disabled=["write_file", "edit_file"])
    cfg = _da_cfg(ws)
    assert "      - type: filesystem" in cfg
    assert '"read_file"' in cfg and '"write_file"' not in cfg and '"edit_file"' not in cfg
    # a toolset with nothing left is left out entirely (an empty include list means "none")
    _build_docker_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                        tools_disabled=["shell"])
    cfg = _da_cfg(ws)
    assert "- type: shell" not in cfg
    assert "- type: filesystem" in cfg, "the other toolsets are untouched"


def test_the_defaults_that_phone_home_or_fetch_a_binary_are_off():
    ws, env = _ws(), {}
    _build_docker_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, env)
    # the CLI's own first-run message names this variable, and it is not DOCKER_AGENT_-prefixed
    assert env["TELEMETRY_ENABLED"] == "false"
    assert env["DOCKER_AGENT_AUTO_UPDATE"] == "false"
    assert env["DOCKER_AGENT_AUTO_INSTALL"] == "false"
    assert env["DOCKER_AGENT_DATA_DIR"].endswith("/.harness/docker-agent/data")


def test_its_real_stream_becomes_a_tool_call_an_answer_and_usage():
    evs, state = _da_norm(_fixture("docker-agent-write-file.ndjson"), cwd=_ws())
    assert evs[0]["subtype"] == "init" and evs[0]["session_id"] == "da-probe-1"
    calls = [b for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "tool_use"]
    results = [b for e in evs for b in (e.get("message", {}).get("content") or [])
               if b.get("type") == "tool_result"]
    assert [c["name"] for c in calls] == ["write_file"]
    assert calls[0]["input"] == {"path": "da.txt", "content": "DOCKER\n"}
    assert results[0]["tool_use_id"] == calls[0]["id"] and results[0]["is_error"] is False
    assert state["final"] == "DONE"
    res = _docker_agent_eof(state, 0)[-1]
    assert res["subtype"] == "success"
    # the SUM of the two requests' own numbers, not the last event's running context
    assert res["usage"]["input_tokens"] == 3059 + 3157
    assert res["usage"]["output_tokens"] == 76 + 5


def test_an_answer_that_arrives_in_fragments_is_one_message():
    """Its `agent_choice` is a DELTA: a two-sentence answer came in nineteen of them across two
    message ids. Read as whole messages, a turn's reply became its last fragment — "RST" for an
    answer of "DA-E2E-FIRST", measured end to end before this was fixed."""
    evs, state = _da_norm(_fixture("docker-agent-answer-deltas.ndjson"), cwd=_ws())
    texts = [b["text"] for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "text"]
    assert len(texts) == 2, texts            # two messages, nineteen fragments
    assert texts[0].startswith("E2EDA") and "read the file" in texts[0]
    assert 'single word, "MADE"' in texts[1]
    assert state["final"] == texts[1]
    # and the text that preceded a tool call comes BEFORE it in the stream
    kinds = [b.get("type") for e in evs for b in (e.get("message", {}).get("content") or [])]
    assert kinds.index("text") < kinds.index("tool_use")


def test_the_prompt_echo_and_the_tui_progress_are_not_rendered():
    evs, _ = _da_norm(_fixture("docker-agent-write-file.ndjson"), cwd=_ws())
    # user_message is the prompt played back; partial_tool_call is one call arriving in fragments
    assert not [e for e in evs if e.get("type") == "user"
                and any(b.get("type") == "text" for b in e["message"]["content"])]
    calls = [b for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "tool_use"]
    assert len(calls) == 1, "partial_tool_call must not put a row per fragment on the transcript"


def test_an_abnormal_stop_fails_the_turn_with_its_reason():
    state = {"model": "gpt-5.4", "final": "half an answer", "cwd": _ws()}
    _docker_agent_to_claude({"type": "stream_stopped", "reason": "max_iterations",
                             "finish_reason": "length"}, state)
    res = _docker_agent_eof(state, 0)[-1]
    assert res["is_error"] is True and "max_iterations" in res["result"]


def test_a_turn_that_never_said_anything_is_not_reported_as_an_answer():
    """MEASURED in its first column (2026-10-20, gemini-3.5-flash-lite, the recycle scenario): the
    CLI exited 0, reported no error, and not one `agent_choice` fragment arrived — one provider
    request, one tool call, its result, and the run ended. The record said `success` with
    `result: ""`, which the console renders as a done pill over a blank reply. It did not reproduce
    on a re-run, so nothing here claims why it stopped; what the result must not do is present
    nothing as the answer. The raw CLI stream of that turn was not captured, so the state is built
    the way the stream leaves it rather than replayed from a fixture."""
    state = {"model": "gemini-3.5-flash-lite", "cwd": _ws()}
    _docker_agent_to_claude({"type": "token_usage", "usage": {"last_message": {
        "input_tokens": 3950, "output_tokens": 54, "finish_reason": "tool_calls"}}}, state)
    res = _docker_agent_eof(state, 0)[-1]
    assert res["subtype"] == "error" and res["is_error"] is True
    assert "without answering" in res["result"]
    assert "tool_calls" in res["result"]          # the one fact about the stop that was in the stream
    assert res["usage"]["input_tokens"] == 3950   # and the turn's usage is still reported


def test_a_turn_that_did_answer_is_untouched_by_that_branch():
    state = {"model": "gpt-5.4", "final": "DONE", "cwd": _ws()}
    res = _docker_agent_eof(state, 0)[-1]
    assert res["subtype"] == "success" and res["result"] == "DONE"


def test_the_tools_are_the_ones_its_toolsets_declare():
    assert "write_file" in ALL_DOCKER_AGENT_TOOLS and "shell" in ALL_DOCKER_AGENT_TOOLS
    assert "think" in ALL_DOCKER_AGENT_TOOLS and "list_todos" in ALL_DOCKER_AGENT_TOOLS
    assert len(ALL_DOCKER_AGENT_TOOLS) == 15


# ── docker-agent refuses a loopback MCP url too, which is how the browser plugin reaches it ──
# MEASURED by the browser column (2026-10-21): it was the one base of four that made no browser
# call, and answered "unable to open the page or click the link interactively … If you enable the
# browser toolset, I can do it directly" — while its config held the server as a `type: mcp`
# toolset with the streamable url and the bearer. The A/B, same config and transport, host changed:
# a public https url gave mcp_init_started/finished and 16 tools; http://127.0.0.1:8080/v1/mcp/plugs
# gave NO mcp_init event at all and 15 (its four built-in toolsets), with nothing on stderr. What
# inside it refuses is not established, and the bridge does not need that answer.

def test_a_loopback_server_is_bridged_for_docker_agent():
    ws = _ws()
    out = _sse_bridges(ws, [{"name": "plugs", "url": "http://127.0.0.1:8080/v1/mcp/plugs",
                             "headers": {"Authorization": "Bearer t"}}], "docker-agent")
    assert out[0].get("command"), "it has to arrive as a stdio command, with no url to refuse"
    assert "url" not in out[0] and "headers" not in out[0]
    launcher = pathlib.Path(out[0]["command"]).read_text()
    assert "HR_MCP_URL" in launcher and "127.0.0.1:8080" in launcher


def test_a_loopback_server_is_bridged_for_fast_agent_too():
    """The same class, the other failure mode: fast-agent DOES try the loopback url and its MCP
    startup dies, taking the whole turn with it — "MCP Server: 'plugs': Failed to initialize …
    MCPError: Not Found", then "RuntimeError: Core not initialized". Three runs of the browser
    column, the same crash each time and no browser call in any of them; bridged, it passed in 12 s
    (2026-10-21)."""
    ws = _ws()
    out = _sse_bridges(ws, [{"name": "plugs", "url": "http://127.0.0.1:8080/v1/mcp/plugs",
                             "headers": {"Authorization": "Bearer t"}}], "fast-agent")
    assert out[0].get("command") and "url" not in out[0]


def test_a_public_server_still_goes_to_fast_agents_own_client():
    ws = _ws()
    out = _sse_bridges(ws, [{"name": "probe", "url": "https://probe.example/mcp"}], "fast-agent")
    assert out[0].get("url") == "https://probe.example/mcp" and "command" not in out[0]


def test_a_public_server_still_goes_to_docker_agents_own_client():
    # its own remote client handles a public server on both transports, measured by the plugin
    # matrix (sse and streamable-HTTP columns), so bridging those would add a hop for nothing
    ws = _ws()
    out = _sse_bridges(ws, [{"name": "probe", "url": "https://probe.example/mcp"}], "docker-agent")
    assert out[0].get("url") == "https://probe.example/mcp" and "command" not in out[0]


def test_the_bridged_server_is_written_as_a_stdio_toolset():
    """The config half, at the right layer: the BRIDGING happens in the dispatch (_sse_bridges
    runs over req.mcp_servers before any builder is called), so what the builder must get right is
    the stdio shape for a server that already arrived as a command. The first version of this test
    called the builder with a loopback URL and asserted it bridged — it does not, and should not."""
    import yaml
    ws = _ws()
    bridged = _sse_bridges(ws, [{"name": "plugs", "url": "http://127.0.0.1:8080/v1/mcp/plugs",
                                 "headers": {"Authorization": "Bearer t"}}], "docker-agent")
    _build_docker_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                        mcp_servers=bridged)
    doc = yaml.safe_load((_docker_agent_home(ws) / "agent.yaml").read_text())
    mcp = [t for t in doc["agents"]["root"]["toolsets"] if t.get("type") == "mcp"]
    assert len(mcp) == 1 and mcp[0].get("command"), mcp
    assert "remote" not in mcp[0], "a bridged server has no url to put in a remote block"


# ══ fast-agent (fast-agent-mcp 0.10.45) ═══════════════════════════════════════════════════════

FA_FIXTURE = "fast-agent-three-turns.atif.json"
# The three prompts of the captured conversation, in order. A turn's record must hold its own
# steps, and this turn's prompt is the boundary (see _fast_agent_eof).
FA_PROMPTS = (
    "Reply with exactly: FA-E2E-FIRST",
    "Create a file called e2e.txt containing the word MADE, then say in one sentence what word I "
    "asked you to reply with in my first message.",
    "Run the shell command `echo NOPE` and tell me what it printed.",
)


def _fa_ws() -> str:
    """A workspace whose trajectory file IS the captured three-turn conversation."""
    ws = _ws()
    traj = _fast_agent_traj(ws)
    traj.parent.mkdir(parents=True, exist_ok=True)
    traj.write_text((FIX / FA_FIXTURE).read_text())
    return ws


def _fa_eof(ws: str, prompt: str, rc: int = 0):
    state = {"model": "gpt-5.4", "final": "", "cwd": ws, "prompt": prompt}
    # the stream carries nothing on this base; everything comes out of the eof
    assert _fast_agent_to_claude({"anything": True}, state) == []
    return _fast_agent_eof(state, rc), state


def test_fast_agent_is_registered_with_an_eof_that_carries_the_turn():
    assert "fast-agent" in BACKENDS
    assert BACKENDS["fast-agent"]["normalize"] is _fast_agent_to_claude
    assert getattr(BACKENDS["fast-agent"]["normalize"], "eof", None) is _fast_agent_eof


def test_the_instruction_file_is_the_one_the_runner_writes_and_names():
    ws = _ws()
    # it has no instruction-file convention of its own: the file is passed with -i (aider's shape)
    assert _agent_doc_path(ws, "fast-agent") == pathlib.Path(ws) / "AGENTS.md"
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    assert cmd[cmd.index("-i") + 1] == str(pathlib.Path(ws) / "AGENTS.md")


def test_the_agent_works_in_the_session_and_keeps_its_store_out_of_it():
    """Both measured, and each was a defect first: the agent's working directory was its HOME, so a
    turn's deliverable landed in .harness/ where the produced-files list drops it; and once
    --workspace was given, the home resolved UNDER it and FAST_AGENT_HOME was ignored, so the
    session store moved into the directory the user collects."""
    ws, env = _ws(), {}
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, env)
    assert cmd[cmd.index("--workspace") + 1] == str(pathlib.Path(ws).resolve())
    assert cmd[cmd.index("--home") + 1] == str(_fast_agent_home(ws))
    assert str(_fast_agent_home(ws)).endswith("/.harness/fast-agent")
    assert env["FAST_AGENT_HOME"] == str(_fast_agent_home(ws))


def test_the_credential_is_in_the_two_variables_its_generic_client_reads():
    ws, env = _ws(), {}
    _build_fast_agent("openai-api", Auth(base_url=UP, api_key="real-key"), "gpt-5.4", "hi", ws, env)
    assert env["GENERIC_BASE_URL"].startswith("http://127.0.0.1:")   # the relay, not the upstream
    assert env["GENERIC_API_KEY"].startswith("hr-relay-")
    assert "real-key" not in json.dumps(env)


def test_the_model_rides_the_generic_prefix_and_the_trajectory_is_cleared_per_turn():
    ws = _fa_ws()
    assert _fast_agent_traj(ws).is_file()
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "claude-haiku-5.5",
                            "hi", ws, {})
    assert cmd[cmd.index("--model") + 1] == "generic.claude-haiku-5.5"
    assert not _fast_agent_traj(ws).exists(), (
        "last turn's trajectory would otherwise answer for this one")
    assert cmd[cmd.index("--trajectory-format") + 1] == "atif"


def test_the_shell_runtime_is_asked_for_and_withheld_by_NAME():
    """Measured on a resumed session: omitting -x left bash in place and the model ran the command;
    --no-shell made the request declare no bash at all."""
    ws = _ws()
    on = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    assert "-x" in on and "--no-shell" not in on
    off = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                            tools_disabled=["bash"])
    assert "--no-shell" in off and "-x" not in off


def test_the_two_file_tools_are_withheld_in_the_config_and_only_when_asked():
    ws = _ws()
    _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    cfg = (_fast_agent_home(ws) / "fastagent.config.yaml").read_text()
    assert "enable_read_text_file: true" in cfg
    assert 'write_text_file_mode: "auto"' in cfg
    _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                      tools_disabled=["read_text_file", "edit_file"])
    cfg = (_fast_agent_home(ws) / "fastagent.config.yaml").read_text()
    assert "enable_read_text_file: false" in cfg
    assert 'write_text_file_mode: "off"' in cfg
    # with the shell runtime withheld there is no shell section to write at all
    _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                      tools_disabled=["bash"])
    assert "shell:" not in (_fast_agent_home(ws) / "fastagent.config.yaml").read_text()


def test_resume_is_passed_only_when_the_session_file_is_there():
    ws = _ws()
    sid = "2610160220-7kil4q"
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                            resume_session_id=sid)
    assert "--resume" not in cmd
    assert _resume_lost("fast-agent", cmd, sid, ws) == sid
    f = _fast_agent_session_file(ws, sid)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"session_id": sid, "continuation": {"agents": {"harness": {
        "shell_enabled": True, "model": "gpt-5.4", "model_spec": "generic.gpt-5.4",
        "history_file": "history_harness.json"}}}}))
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                            resume_session_id=sid)
    assert cmd[cmd.index("--resume") + 1] == sid
    assert _fast_agent_session_present(ws, cmd, sid) is True
    assert _resume_lost("fast-agent", cmd, sid, ws) is None


def test_a_switch_rewrites_the_sessions_stored_model_and_nothing_else():
    """A resumed session restores its own model, so the store is pointed at this turn's first
    (measured). `shell_enabled` is deliberately NOT written: --no-shell does that job, and writing
    into another program's state without a measurement behind it is how a commit message came to
    claim a fix that changed nothing (opensquilla's `[memory] source`)."""
    ws = _ws()
    sid = "2610160220-7kil4q"
    f = _fast_agent_session_file(ws, sid)
    f.parent.mkdir(parents=True, exist_ok=True)
    before = {"session_id": sid, "metadata": {"title": "keep me"},
              "continuation": {"agents": {"harness": {
                  "shell_enabled": True, "model": "claude-haiku-5.5",
                  "model_spec": "generic.claude-haiku-5.5",
                  "history_file": "history_harness.json",
                  "resolved_prompt": "do not touch"}}}}
    f.write_text(json.dumps(before))
    assert _fast_agent_set_model(ws, sid, "gemini-3-flash") is True
    after = json.loads(f.read_text())
    agent = after["continuation"]["agents"]["harness"]
    assert agent["model"] == "gemini-3-flash"
    assert agent["model_spec"] == "generic.gemini-3-flash"
    assert agent["shell_enabled"] is True, "not ours to write"
    assert agent["resolved_prompt"] == "do not touch"
    assert agent["history_file"] == "history_harness.json"
    assert after["metadata"]["title"] == "keep me"
    # the same model again changes nothing, so a no-op turn does not rewrite the store
    assert _fast_agent_set_model(ws, sid, "gemini-3-flash") is False
    # and a session that is not there is not an error
    assert _fast_agent_set_model(ws, "nope", "gemini-3-flash") is False


def test_an_mcp_server_carries_its_bearer_and_its_transport():
    """PARSED, not substring-matched. The first version of this test asserted `'transport:
    "http"' in cfg`, which is true at ANY indentation — and the indentation was wrong: the server
    name and its fields were emitted at the same depth, so `mcp.servers` loaded as three sibling
    keys and the CLI refused to start ("3 validation errors for Settings / mcp: Invalid
    configuration value", one per key). Every turn of every harness that declared an MCP server on
    this base died before its first model call, and the support-matrix column could not see it
    because a column declares no MCP servers. Found by the custom-harness dimension, 2026-10-20."""
    import yaml
    ws = _ws()
    _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                      mcp_servers=[{"name": "plugs", "url": "https://p.example/mcp",
                                    "transport": "http", "auth": "tok-7"},
                                   {"name": "legacy", "url": "https://l.example/sse",
                                    "transport": "sse"},
                                   {"name": "local", "command": ["/bin/echo", "hi"],
                                    "args": ["more"]}])
    doc = yaml.safe_load((_fast_agent_home(ws) / "fastagent.config.yaml").read_text())
    servers = doc["mcp"]["servers"]
    assert sorted(servers) == ["legacy", "local", "plugs"], servers
    assert servers["plugs"] == {"transport": "http", "url": "https://p.example/mcp",
                                "headers": {"Authorization": "Bearer tok-7"}}
    # its client takes sse natively, so nothing is bridged
    assert servers["legacy"] == {"transport": "sse", "url": "https://l.example/sse"}
    assert servers["local"] == {"transport": "stdio", "command": "/bin/echo",
                                "args": ["hi", "more"]}
    assert "fast-agent" not in _BRIDGED_TRANSPORTS


def test_a_declared_server_is_also_enabled_on_the_command_line():
    """MEASURED by the custom-harness dimension (2026-10-20), after the indentation fix above made
    the config load at all: the turn ran, recorded ZERO tool calls, and the harness's own MCP
    server was never called. `go` builds an ad-hoc agent and its `--servers` is "a comma-separated
    list of server names to enable from config", so declaring a server in the file is not enough —
    the flag has to name it. The names come back from the writer, so this asserts the flag against
    the DOCUMENT rather than against a second copy of the naming rule."""
    import yaml
    ws = _ws()
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                            mcp_servers=[{"name": "one", "url": "https://a.example/mcp"},
                                         {"name": "two", "command": ["/bin/echo"]}])
    doc = yaml.safe_load((_fast_agent_home(ws) / "fastagent.config.yaml").read_text())
    named = cmd[cmd.index("--servers") + 1].split(",")
    assert sorted(named) == sorted(doc["mcp"]["servers"]), (named, doc["mcp"]["servers"])


def test_no_servers_means_no_servers_flag():
    ws = _ws()
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    assert "--servers" not in cmd
    assert "mcp:" not in (_fast_agent_home(ws) / "fastagent.config.yaml").read_text()


def test_every_server_body_sits_under_its_own_name():
    """The invariant the bug broke, asked of the DOCUMENT: a server's fields are its own, and
    `mcp.servers` holds nothing but server names."""
    import yaml
    ws = _ws()
    _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                      mcp_servers=[{"name": "one", "url": "https://a.example/mcp"},
                                   {"name": "two", "url": "https://b.example/mcp"}])
    doc = yaml.safe_load((_fast_agent_home(ws) / "fastagent.config.yaml").read_text())
    for name, body in doc["mcp"]["servers"].items():
        assert isinstance(body, dict) and body.get("transport"), (name, body)
        assert not set(body) - {"transport", "url", "command", "args", "headers"}, body


def test_a_turns_record_is_its_own_steps_and_not_the_whole_conversation():
    """Its trajectory holds every turn of a resumed session — eight steps across three here — and
    a turn that reported all of them arrived with every earlier reply glued in front of its own."""
    ws = _fa_ws()
    evs, state = _fa_eof(ws, FA_PROMPTS[2])
    texts = [b["text"] for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "text"]
    assert len(texts) == 1
    assert texts[0].startswith("E2EFA I can't run that command")
    assert "FA-E2E-FIRST" not in texts[0], "the first turn's answer is not this turn's"
    assert state["final"] == texts[0]


def test_the_middle_turns_tool_call_and_its_result_come_off_the_real_trajectory():
    ws = _fa_ws()
    evs, state = _fa_eof(ws, FA_PROMPTS[1])
    calls = [b for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "tool_use"]
    results = [b for e in evs for b in (e.get("message", {}).get("content") or [])
               if b.get("type") == "tool_result"]
    assert [c["name"] for c in calls] == ["bash"]
    assert calls[0]["id"] == "call_3379114"
    assert results[0]["tool_use_id"] == calls[0]["id"] and results[0]["is_error"] is False
    assert "process exit code was 0" in results[0]["content"]
    assert "FA-E2E-FIRST" in state["final"], "this turn's own answer, which recalls the first"
    assert "I can't run that command" not in state["final"], "the turn after it is not this one"


def test_the_session_id_and_the_usage_come_off_the_trajectory_too():
    ws = _fa_ws()
    evs, _state = _fa_eof(ws, FA_PROMPTS[0])
    init = evs[0]
    assert init["subtype"] == "init" and init["session_id"] == "2610160220-7kil4q"
    res = evs[-1]
    assert res["subtype"] == "success" and res["is_error"] is False
    # final_metrics, not a sum of our own: 4524 prompt / 715 completion / 0 cached
    assert res["usage"]["input_tokens"] == 4524
    assert res["usage"]["output_tokens"] == 715
    assert "cache_read_tokens" not in res["usage"]


def test_an_init_that_only_the_eof_emits_still_records_the_cli_session_id():
    """THE BUG THIS BASE'S FIRST COLUMN FOUND (2026-10-20). Its stream carries nothing — the ATIF
    trajectory is read at eof — so its `init` event only ever appears in the eof batch, and the
    capture that remembers the CLI's conversation id lived in the streaming loop alone. The id was
    never recorded, so the gateway had none to send back, so the builder never passed `--resume`,
    and every follow-up turn silently began a new conversation. `_resume_lost` stayed quiet because
    an EMPTY resume id is not a lost one.

    Four of the five matrix scenarios passed anyway: they ask the model to echo a token and never
    test the history. The recall scenario answered the literal word "word"; a clean two-turn probe
    with a word that is nowhere in the workspace answered "remember", 993 input tokens against the
    first turn's 989. The CLI was never at fault — by hand, `--resume` answered the word and the
    trajectory grew from three steps to five."""
    ws = _fa_ws()
    evs, _state = _fa_eof(ws, FA_PROMPTS[0])
    init = next(e for e in evs if e.get("subtype") == "init")
    rec: dict = {}
    for ev in evs:                      # exactly what the eof branch now does, in order
        _record_cli_session_id(rec, ev)
    assert rec["session_id"] == init["session_id"] == "2610160220-7kil4q"


def test_both_places_a_turns_events_are_produced_record_the_session_id():
    """The invariant, not the symptom: the streaming loop and the eof loop must BOTH capture it.
    One of them having the line and the other not is the whole of the bug above, and a reader
    adding a third place to produce events needs to see this failing rather than guess."""
    src = pathlib.Path(__file__).resolve().parents[1] / "server.py"
    body = src.read_text()
    assert body.count("_record_cli_session_id(rec, ev)") == 2, (
        "both the streaming loop and the eof loop call it, and nothing else does")
    # and the capture exists nowhere else in a hand-written form, which is how they drifted
    assert 'rec["session_id"] = ev["session_id"]' not in body.split("def _record_cli_session_id")[0]


def test_a_cumulative_message_contributes_only_its_new_text():
    # measured on this CLI: a two-step turn reported "FAOK" and then "FAOK\n\nDONE"
    ws = _ws()
    traj = _fast_agent_traj(ws)
    traj.parent.mkdir(parents=True, exist_ok=True)
    traj.write_text(json.dumps({"session_id": "s1", "steps": [
        {"step_id": 1, "source": "user", "message": "go"},
        {"step_id": 2, "source": "agent", "message": "FAOK"},
        {"step_id": 3, "source": "agent", "message": "FAOK\n\nDONE"}],
        "final_metrics": {"total_prompt_tokens": 10, "total_completion_tokens": 2}}))
    evs, state = _fa_eof(ws, "go")
    texts = [b["text"] for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "text"]
    assert texts == ["FAOK", "DONE"], texts
    assert state["final"] == "FAOK\nDONE"


def test_a_turn_that_wrote_no_trajectory_fails_and_leaves_the_reason_to_stderr():
    ws = _ws()   # no trajectory file at all: the CLI died before writing one
    evs, _state = _fa_eof(ws, "go", rc=1)
    res = evs[-1]
    assert res["subtype"] == "error" and res["is_error"] is True
    assert res["result"] == "", "the run loop's stderr tail is the reason, not a placeholder"


def test_the_tools_offered_are_the_three_with_a_switch():
    assert set(ALL_FAST_AGENT_TOOLS) == {"bash", "read_text_file", "edit_file"}
    assert "process" not in ALL_FAST_AGENT_TOOLS
