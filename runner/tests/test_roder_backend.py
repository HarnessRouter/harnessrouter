"""Roder routing and typed app-server notifications, independent of a model provider."""
import json
import os
import pathlib
import sys
import time
import tomllib
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server
from roder_events import Events


def relay(base, key, **flags):
    return ("http://127.0.0.1:9999/v1", "hr-relay-placeholder")


def build(tmp_path, **kwargs):
    env = {"HOME": str(tmp_path / ".harness/home")}
    cmd = server.roder_backend.build("openai", server.Auth(api_key="real-secret", base_url="https://api.openai.com/v1"),
        "vendor/model", "-a prompt", str(tmp_path), env, relay=relay, driver_cmd=server._driver_cmd, **kwargs)
    return cmd, env


def config(tmp_path):
    return tomllib.loads((tmp_path / ".harness/roder/config.toml").read_text())


def test_provider_key_and_prompt_never_enter_argv_or_config(tmp_path):
    cmd, env = build(tmp_path)
    text = (tmp_path / ".harness/roder/config.toml").read_text()
    assert "real-secret" not in text + json.dumps(cmd) + json.dumps(env)
    assert "-a prompt" not in json.dumps(cmd)
    cfg = config(tmp_path)
    assert cfg["provider"] == "hr" and cfg["model"] == "vendor/model"
    assert cfg["providers"]["hr"]["api_key_env"] == "HR_RODER_KEY"
    assert env["HR_RODER_KEY"].startswith("hr-relay-")
    assert json.loads(env["HR_DRIVER_JOB"])["prompt"] == "-a prompt"


def test_the_job_travels_as_every_drivers_does(tmp_path):
    """Through server._driver_cmd, into HR_DRIVER_JOB, which every driver pops before it starts
    anything; the driver pops it the same way. Never on the command line."""
    cmd, env = build(tmp_path, mcp_servers=[{"name": "r", "url": "https://mcp.example/x",
                                             "headers": {"Authorization": "Bearer b-419"}}])
    assert cmd == [sys.executable, server.roder_backend.DRIVER]
    assert "b-419" in env["HR_DRIVER_JOB"] and "b-419" not in json.dumps(cmd)
    driver = (pathlib.Path(server.__file__).with_name("roder_driver.py")).read_text()
    assert 'os.environ.pop("HR_DRIVER_JOB")' in driver and "HR_RODER_JOB" not in driver


def test_model_resume_mcp_and_policy_reach_driver(tmp_path):
    _, env = build(tmp_path, resume_session_id="thread1", tools_disabled=["update_plan"],
                   mcp_servers=[{"name": "x", "command": "example"}], thinking={"asked": "high"})
    job = json.loads(env["HR_DRIVER_JOB"])
    assert (job["model"], job["resume"], job["reasoning"]) == ("vendor/model", "thread1", "high")
    assert job["tools_disabled"] == ["update_plan"] and job["mcp_servers"][0]["name"] == "x"


@pytest.mark.parametrize("provider,fmt", [("bedrock", None), ("openai", "anthropic"), ("openai", "openai")])
def test_unsupported_connection_is_refused(tmp_path, provider, fmt):
    with pytest.raises(server.HTTPException):
        server.roder_backend.build(provider, server.Auth(api_key="k", api_format=fmt),
            "m", "p", str(tmp_path), {}, relay=relay, driver_cmd=server._driver_cmd)


def test_openrouter_and_custom_connections_build_as_dcodes_do(tmp_path):
    """The gateway sends them as openai-api, dcode's provider for both."""
    assert "openai-api" in server.roder_backend.PROVIDERS and "openai-api" in server.DCODE_PROVIDERS
    env: dict = {}
    server.roder_backend.build("openai-api", server.Auth(api_key="k", base_url="https://openrouter.ai/api/v1"),
                               "openai/gpt-6.1-sol", "p", str(tmp_path), env, relay=relay,
                               driver_cmd=server._driver_cmd)
    assert config(tmp_path)["model"] == "openai/gpt-6.1-sol"


def test_the_relay_route_replays_earlier_turns_as_content_as_dcodes_does(tmp_path):
    """Roder's OpenAI profile asks for reasoning.encrypted_content with store:false and replays it
    on later turns: after a model switch that is what another model minted, so its route asks for
    turn_reasoning_only, as dcode's does (test_relay_turn_reasoning.py)."""
    env: dict = {}
    server.roder_backend.build("openai", server.Auth(api_key="k", base_url="https://up.example/v1"),
                               "gpt-6.1-sol", "hi", str(tmp_path), env, relay=server._hermes_relay_route,
                               driver_cmd=server._driver_cmd)
    route = server._HERMES_RELAY["routes"].get(env["HR_RODER_KEY"])
    assert route is not None and route[2].get("turn_reasoning_only") is True


# ── the tool policy ───────────────────────────────────────────────────────────────────────────────

def test_every_offered_tool_is_allowed_and_no_withheld_one_ever_is(tmp_path):
    build(tmp_path)
    allowed = config(tmp_path)["tools"]["allowlist"]
    assert set(allowed) == {n for names in server.roder_backend.TOOLS.values() for n in names}
    assert not set(allowed) & server.roder_backend.WITHHELD
    assert "web_search" not in config(tmp_path)


@pytest.mark.parametrize("off", ["exec_command", "shell", "unified_exec", "write_stdin"])
def test_switching_the_shell_off_by_any_of_its_names_removes_all_four(tmp_path, off):
    build(tmp_path, tools_disabled=[off])
    allowed = set(config(tmp_path)["tools"]["allowlist"])
    assert not allowed & {"exec_command", "shell", "unified_exec", "write_stdin"}
    assert "read_file" in allowed


def test_switching_file_edit_off_leaves_no_file_writer_for_any_model(tmp_path):
    build(tmp_path, tools_disabled=["apply_patch"])
    allowed = set(config(tmp_path)["tools"]["allowlist"])
    assert not allowed & {"apply_patch", "edit", "multi_edit", "write_file"}
    build(tmp_path, tools_disabled=["write_file"])      # a raw Roder name turns its switch off too
    assert not set(config(tmp_path)["tools"]["allowlist"]) & {"apply_patch", "edit", "multi_edit", "write_file"}


def test_every_switch_off_is_the_no_tool_sentinel_never_an_empty_list(tmp_path):
    """An empty Roder allowlist means every tool."""
    build(tmp_path, tools_disabled=list(server.roder_backend.TOOLS))
    cfg = config(tmp_path)
    assert cfg["tools"]["allowlist"] == ["hr_no_builtin_tools"]
    assert cfg["web_search"]["mode"] == "disabled"


def test_web_search_is_switched_off_through_roders_own_mode(tmp_path):
    build(tmp_path, tools_disabled=["web_search"])
    cfg = config(tmp_path)
    assert cfg["web_search"] == {"mode": "disabled"}
    assert "read_file" in cfg["tools"]["allowlist"]


def test_an_mcp_tool_name_does_not_touch_the_builtin_policy(tmp_path):
    build(tmp_path, tools_disabled=["mcp__probe__echo"])
    assert set(config(tmp_path)["tools"]["allowlist"]) == {
        n for names in server.roder_backend.TOOLS.values() for n in names}


# ── the stream ────────────────────────────────────────────────────────────────────────────────────

def item(kind, **kwargs):
    return {"event": {"type": kind, "item": kwargs}}


def test_streaming_and_completion_do_not_duplicate_text():
    events = Events()
    delta = {"event": {"type": "itemDelta", "itemId": "a", "delta": {
        "type": "agentMessageText", "delta": "hello"}}}
    assert events.notification("item/agentMessage/delta", delta)[0]["message"]["content"][0]["text"] == "hello"
    assert events.notification("item/completed", item("itemCompleted", id="a", type="agentMessage", text="hello")) == []
    assert events.final == "hello"


def test_completed_message_backfills_a_missing_delta():
    events = Events()
    out = events.notification("item/completed", item("itemCompleted", id="a", type="agentMessage", text="hello"))
    assert out[0]["message"]["content"][0]["text"] == "hello"


def test_tool_call_and_complete_output_are_linked_once():
    events = Events()
    tool = {"id": "i", "type": "toolExecution", "toolCallId": "c", "toolName": "shell",
            "input": {"command": "printf hi"}, "status": "inProgress"}
    out = events.notification("item/started", item("itemStarted", **tool))
    out += events.notification("item/completed", item("itemCompleted", **{**tool, "status": "completed", "output": "hi"}))
    assert len(out) == 2
    assert out[0]["message"]["content"][0]["input"] == {"command": "printf hi"}
    assert out[1]["message"]["content"][0] == {"type": "tool_result", "tool_use_id": "c", "content": "hi", "is_error": False}


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_failed_or_cancelled_turn_is_never_success(status):
    result = Events().notification("turn/completed", {"turn": {"status": status, "error": "provider 401"}})[0]
    assert result["is_error"] and result["result"] == "provider 401"


def test_cache_subsets_are_not_billed_twice():
    result = Events().notification("turn/completed", {"turn": {"status": "completed", "usage": {
        "prompt_tokens": 100, "cached_prompt_tokens": 60, "cache_creation_prompt_tokens": 10, "completion_tokens": 8}}})[0]
    assert result["usage"] == {"input_tokens": 30, "output_tokens": 8, "cache_read_tokens": 60, "cache_write_tokens": 10}


def test_truncated_stream_fails_even_when_process_exit_is_zero():
    assert server.roder_backend.normalize.eof({}, 0)[0]["is_error"]


def test_a_turn_the_runner_stopped_is_not_reported_as_a_crash():
    for stop in ("max_turns", "input_required"):
        assert server.roder_backend.normalize.eof({"_stop": stop}, -9) == []


def test_the_step_budget_stops_a_roder_turn_as_it_stops_every_other_base(tmp_path):
    """Killed at its budget, the driver never writes turn/completed: the turn ends error_max_turns
    with the text it had, as codex's and the generic bases' do, never "exited without
    turn/completed (exit -9)"."""
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "t1", "model": "m"}),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Working on it."}]}})]
    for i in range(5):
        lines.append(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"c{i}", "name": "shell", "input": {"command": "true"}}]}}))
        lines.append(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"c{i}", "content": "", "is_error": False}]}}))
    script = tmp_path / "driver.py"
    script.write_text("import sys,time\n" + "".join(f"print({line!r}, flush=True)\n" for line in lines)
                      + "time.sleep(30)\n")
    turn_id = "roder-budget-" + uuid.uuid4().hex
    server._turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                              "started": time.time(), "backend": "roder", "model": "m"}
    try:
        server._run_turn_bg(turn_id, [sys.executable, str(script)], os.environ.copy(), str(tmp_path),
                            server.roder_backend.normalize, "m", timeout_seconds=30, max_turns=2,
                            count_steps=True)
        rec = server._turns[turn_id]
        final = [e for e in rec["events"] if e.get("type") == "result"][-1]
        assert rec["status"] == "max_turns"
        assert final["subtype"] == "error_max_turns" and final["is_error"] is False
        assert "exited without" not in json.dumps(final)
        assert final["result"] == "Working on it."
    finally:
        server._turns.pop(turn_id, None)


# ── registration and what a checkpoint carries ────────────────────────────────────────────────────

def test_registration_skills_instructions_and_credential_exclusion(tmp_path):
    assert server.BACKENDS["roder"]["normalize"] is server.roder_backend.normalize
    assert server._agent_doc_path(str(tmp_path), "roder").name == "AGENTS.md"
    assert "./.harness/roder/auth" in server.CHECKPOINT_EXCLUDE
    assert "./.harness/roder/config.toml" in server.CHECKPOINT_EXCLUDE
    assert "roder" in server._GENERIC_STEP_BUDGET


def test_roders_rebuilt_caches_stay_out_of_the_checkpoint_and_its_conversation_stays_in():
    """Read off 0.4.8's own paths under RODER_DATA_DIR (and a real turn's tree in the container):
    the code index, the discovery catalog and the models cache are made again when missing."""
    for cache in (".harness/roder/code-index", ".harness/roder/discovery", ".harness/roder/models-cache.json"):
        assert cache in server._REBUILT_CACHES and f"./{cache}" in server.CHECKPOINT_EXCLUDE
    for kept in ("threads", "memory", "knowledge"):
        assert not any(c.startswith(f".harness/roder/{kept}") for c in server.CHECKPOINT_EXCLUDE), kept
    # the store changes every turn, so it travels in the tar and never in the workspace's git
    assert ".harness/roder/" in server._STATE_DIRS


def test_skill_bundle_uses_the_native_user_root(tmp_path):
    meta = server._write_skills(str(tmp_path), [{"name": "demo", "content": "# Demo"}], backend="roder")
    assert (tmp_path / ".harness/home/.codex/skills/demo/SKILL.md").read_text() == "# Demo"
    assert meta[0]["entry"].startswith(".harness/")
