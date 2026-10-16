"""The bases added in batch 4. First of them: vibe (mistral-vibe).

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

Pinned build: mistral-vibe 2.26.1
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (ALL_VIBE_TOOLS, Auth, BACKENDS, CHECKPOINT_EXCLUDE,  # noqa: E402
                    _agent_doc_path, _build_vibe,
                    _BRIDGED_TRANSPORTS, _vibe_eof, _vibe_home, _vibe_out,
                    _vibe_session_present, _vibe_to_claude, _resume_lost, _write_skills)

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
