"""The bases added in batch 4: vibe (mistral-vibe), vtcode (VT Code) and docker-agent.

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

Pinned builds: mistral-vibe 2.26.1 · vtcode 0.177.0 · docker-agent v1.150.0
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (ALL_VIBE_TOOLS, ALL_VTCODE_TOOLS, Auth, BACKENDS,  # noqa: E402
                    CHECKPOINT_EXCLUDE, _PRODUCED_EXCLUDE_PREFIX,
                    _agent_doc_path, _build_vibe, _build_vtcode,
                    _BRIDGED_TRANSPORTS, _vibe_eof, _vibe_home, _vibe_out,
                    _vibe_session_present, _vibe_to_claude, _resume_lost, _write_skills,
                    _vtcode_config_path, _vtcode_eof, _vtcode_home, _vtcode_is_summary,
                    _vtcode_session_present, _vtcode_to_claude, _vtcode_usage,
                    ALL_DOCKER_AGENT_TOOLS, _build_docker_agent, _docker_agent_eof,
                    _docker_agent_home, _docker_agent_session_db,
                    _docker_agent_session_present, _docker_agent_to_claude)

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


# ══ vtcode (VT Code 0.177.0) ══════════════════════════════════════════════════════════════════

def _vt_norm(lines, model="gpt-5.4", cwd=""):
    state: dict = {"model": model, "final": "", "cwd": cwd}
    out = []
    for ln in lines:
        out += _vtcode_to_claude(ln, state)
    return out, state


def test_vtcode_is_registered_with_its_own_normaliser():
    assert "vtcode" in BACKENDS
    assert BACKENDS["vtcode"]["normalize"] is _vtcode_to_claude
    assert getattr(BACKENDS["vtcode"]["normalize"], "eof", None) is _vtcode_eof
    # its frame is codex's and its items are not, so it must NOT share codex's normaliser
    from server import _codex_to_claude
    assert BACKENDS["vtcode"]["normalize"] is not _codex_to_claude


def test_vtcode_reads_agents_md_and_keeps_its_own_state_out_of_the_deliverables():
    ws = _ws()
    assert _agent_doc_path(ws, "vtcode") == pathlib.Path(ws) / "AGENTS.md"
    # its session store, snapshots and tracker files live in <workspace>/.vtcode
    assert ".vtcode/" in _PRODUCED_EXCLUDE_PREFIX
    assert _BRIDGED_TRANSPORTS["vtcode"] == ("sse",)
    meta = _write_skills(ws, [{"name": "stamp", "content": "---\nname: stamp\n---\nrun it\n"}],
                         backend="vtcode")
    assert meta
    assert (pathlib.Path(ws) / ".harness" / "home" / ".agents" / "skills" / "stamp" / "SKILL.md").is_file()
    assert not (pathlib.Path(ws) / ".agents").exists(), "a skill in the workspace is a deliverable"


def test_vtcode_names_the_provider_as_well_as_the_model_everywhere():
    """Its model→provider inference reads a vendor prefix, so `--model google/...` alone picked its
    BUILT-IN gemini provider and asked for a key nobody set (measured)."""
    ws, env = _ws(), {}
    cmd = _build_vtcode("openai-api", Auth(base_url=UP, api_key="k"), "google/gemini-3-flash",
                        "hi", ws, env)
    cfg = _vtcode_config_path(ws).read_text()
    assert 'provider = "harness"' in cfg
    assert 'name = "harness"' in cfg and 'base_url = "' in cfg
    assert 'default_model = "google/gemini-3-flash"' in cfg
    # the id must also be in the provider's own list, or a resumed turn naming it is refused
    assert 'models = ["google/gemini-3-flash"]' in cfg
    assert cmd[cmd.index("-c") + 1] == str(_vtcode_config_path(ws))
    assert "--skip-confirmations" in cmd
    # ten tool calls per session is its default; a real task passes that before it is done
    assert cmd[cmd.index("--max-tool-calls") + 1] == "120"
    assert env["VTCODE_TRUST_WORKSPACE"] == "full-auto", "exec refuses an untrusted workspace"
    assert env["VTCODE_DISABLE_KEYRING"] == "1"
    assert env["HR_VTCODE_RELAY_KEY"].startswith("hr-relay-")
    assert "k" != env["HR_VTCODE_RELAY_KEY"]
    assert env["VTCODE_DATA"].endswith("/.harness/vtcode/data")


def test_vtcode_turns_off_every_default_that_would_keep_a_turn_going_or_cost_a_model_call():
    ws = _ws()
    _build_vtcode("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {})
    cfg = _vtcode_config_path(ws).read_text()
    for line in ("memories = false", 'continuation_policy = "off"',
                 'orchestration_mode = "single"', "auto_continue_tracker = false",
                 "cross_turn_turns = 0", "atif_enabled = false", "enabled = false"):
        assert line in cfg, line


def test_vtcode_resume_names_the_session_the_provider_and_the_model():
    ws = _ws()
    sid = "session-ws-20261016T045735Z_182826-20828"
    cmd = _build_vtcode("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                        resume_session_id=sid)
    assert "resume" not in cmd, "the conversation is not in the store yet"
    assert _resume_lost("vtcode", cmd, sid, ws) == sid
    reg = _vtcode_home(ws) / "data" / "state" / "sessions"
    reg.mkdir(parents=True)
    (reg / f"{sid}.json").write_text("{}")
    cmd = _build_vtcode("openai-api", Auth(base_url=UP, api_key="k"), "claude-haiku-5.5", "hi",
                        ws, {}, resume_session_id=sid)
    assert cmd[-2:] == [sid, "hi"]
    assert cmd[cmd.index("--provider") + 1] == "harness"
    # the model on the RESUME, or the session's own model wins and the switch is dropped
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5.5"
    assert _vtcode_session_present(ws, cmd, sid) is True
    assert _resume_lost("vtcode", cmd, sid, ws) is None


def test_vtcode_withholds_a_disabled_tool_through_its_hard_allow_list():
    ws = _ws()
    _build_vtcode("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                  tools_disabled=["exec_command"])
    cfg = _vtcode_config_path(ws).read_text()
    allowed = [ln for ln in cfg.splitlines() if ln.startswith("allowed_tools = ")][0]
    assert "exec_command" not in allowed
    for keep in ("apply_patch", "search_tools", "write_stdin", "record_decision"):
        assert keep in allowed


def test_vtcode_mcp_server_carries_its_bearer_on_the_http_transport():
    ws = _ws()
    _build_vtcode("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", ws, {},
                  mcp_servers=[{"name": "plugs", "url": "https://p.example/mcp",
                                "transport": "http", "auth": "tok-9"}])
    cfg = _vtcode_config_path(ws).read_text()
    assert "[[mcp.providers]]" in cfg and 'endpoint = "https://p.example/mcp"' in cfg
    assert '"Authorization" = "Bearer tok-9"' in cfg


def test_vtcodes_real_first_turn_replays_into_an_answer_and_usage():
    ws = _ws()
    evs, state = _vt_norm(_fixture("vtcode-first-turn.ndjson"), cwd=ws)
    init = evs[0]
    assert init["subtype"] == "init" and init["session_id"].startswith("session-ws-")
    res = _vtcode_eof(state, 0)[-1]
    assert res["subtype"] == "success"
    assert res["usage"]["input_tokens"] > 0 and res["usage"]["output_tokens"] > 0
    assert "VT-E2E-FIRST" in state["final"]
    # the harness's closing summary is not the answer
    assert not state["final"].startswith("Task:")
    assert state.get("_vt_summary", "").startswith("Task:")


def test_vtcode_tool_calls_and_their_results_come_off_the_real_stream():
    ws = _ws()
    evs, state = _vt_norm(_fixture("vtcode-resume-write.ndjson"), cwd=ws)
    calls = [b for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "tool_use"]
    results = [b for e in evs for b in (e.get("message", {}).get("content") or [])
               if b.get("type") == "tool_result"]
    assert [c["name"] for c in calls] == ["exec_command"]
    assert calls[0]["input"].get("cmd")
    assert results and results[0]["tool_use_id"] == calls[0]["id"], "the result follows its call"
    assert results[0]["is_error"] is False
    # only item.completed is read: a partial agent_message must not become a second answer
    assert sum(1 for e in evs if e.get("type") == "assistant"
               and (e["message"]["content"] or [{}])[0].get("type") == "text") == 1


def test_a_withheld_vtcode_tool_is_a_note_and_not_a_tool_row():
    ws = _ws()
    evs, state = _vt_norm(_fixture("vtcode-tool-denied.ndjson"), cwd=ws)
    names = [b["name"] for e in evs for b in (e.get("message", {}).get("content") or [])
             if b.get("type") == "tool_use"]
    assert "exec_command" not in names, "a call the policy refused is not a call that ran"
    notes = [e["text"] for e in evs if e.get("subtype") == "notice"]
    assert any("exec_command was refused" in n for n in notes)
    # and its result row is gone with it
    assert not [b for e in evs for b in (e.get("message", {}).get("content") or [])
                if b.get("type") == "tool_result" and "denied" in str(b.get("content"))]


def test_the_summary_block_is_told_from_a_model_writing_about_a_task():
    assert _vtcode_is_summary("Task: Exec Task\nDescription: x\nAgent Type: Single\n")
    assert not _vtcode_is_summary("Task: write the file. I did that and verified it.")
    assert not _vtcode_is_summary("The task is complete.")


def test_the_usage_field_its_picker_does_not_know_is_mapped_by_hand():
    # cache_creation_tokens is vtcode's name and is NOT in _norm_token_usage's picker; a field name
    # nobody reads is a category billed at zero (the gemini-cli lesson)
    out = _vtcode_usage({"input_tokens": 100, "output_tokens": 10,
                         "cached_input_tokens": 30, "cache_creation_tokens": 7})
    assert out["cache_read_tokens"] == 30
    assert out["cache_write_tokens"] == 7
    assert out["input_tokens"] == 70, "input is read as gross, netting the cached read"


def test_vtcode_tools_are_the_five_its_own_schema_command_reports():
    assert set(ALL_VTCODE_TOOLS) == {"exec_command", "write_stdin", "apply_patch", "search_tools",
                                     "record_decision"}


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


def test_the_tools_are_the_ones_its_toolsets_declare():
    assert "write_file" in ALL_DOCKER_AGENT_TOOLS and "shell" in ALL_DOCKER_AGENT_TOOLS
    assert "think" in ALL_DOCKER_AGENT_TOOLS and "list_todos" in ALL_DOCKER_AGENT_TOOLS
    assert len(ALL_DOCKER_AGENT_TOOLS) == 15
