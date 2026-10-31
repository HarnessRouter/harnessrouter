"""Roder routing and typed app-server notifications, independent of a model provider."""
import json
import pathlib
import sys
import tomllib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server
from roder_events import Events


def build(tmp_path, **kwargs):
    env = {"HOME": str(tmp_path / ".harness/home")}
    cmd = server.roder_backend.build("openai", server.Auth(api_key="real-secret", base_url="https://api.openai.com/v1"),
        "vendor/model", "-a prompt", str(tmp_path), env,
        relay=lambda base, key: ("http://127.0.0.1:9999/v1", "hr-relay-placeholder"), **kwargs)
    return cmd, env


def test_provider_key_and_prompt_never_enter_argv_or_config(tmp_path):
    cmd, env = build(tmp_path)
    config = (tmp_path / ".harness/roder/config.toml").read_text()
    assert "real-secret" not in config + json.dumps(cmd) + json.dumps(env)
    assert "-a prompt" not in json.dumps(cmd)
    cfg = tomllib.loads(config)
    assert cfg["provider"] == "hr" and cfg["model"] == "vendor/model"
    assert cfg["providers"]["hr"]["api_key_env"] == "HR_RODER_KEY"
    assert env["HR_RODER_KEY"].startswith("hr-relay-")
    assert json.loads(env["HR_RODER_JOB"])["prompt"] == "-a prompt"


def test_model_resume_mcp_and_policy_reach_driver(tmp_path):
    _, env = build(tmp_path, resume_session_id="thread1", tools_disabled=["update_plan"],
                   mcp_servers=[{"name": "x", "command": "example"}], thinking={"asked": "high"})
    job = json.loads(env["HR_RODER_JOB"])
    assert (job["model"], job["resume"], job["reasoning"]) == ("vendor/model", "thread1", "high")
    assert job["tools_disabled"] == ["update_plan"] and job["mcp_servers"][0]["name"] == "x"


@pytest.mark.parametrize("provider,fmt", [("bedrock", None), ("openai", "anthropic"), ("openai", "openai")])
def test_unsupported_connection_is_refused(tmp_path, provider, fmt):
    with pytest.raises(server.HTTPException):
        server.roder_backend.build(provider, server.Auth(api_key="k", api_format=fmt),
            "m", "p", str(tmp_path), {}, relay=lambda b,k: (b,k))


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


def test_registration_skills_instructions_and_credential_exclusion(tmp_path):
    assert server.BACKENDS["roder"]["normalize"] is server.roder_backend.normalize
    assert server._agent_doc_path(str(tmp_path), "roder").name == "AGENTS.md"
    assert "./.harness/roder/auth" in server.CHECKPOINT_EXCLUDE
    assert "./.harness/roder/config.toml" in server.CHECKPOINT_EXCLUDE
    assert "roder" in server._GENERIC_STEP_BUDGET


def test_skill_bundle_uses_the_native_user_root(tmp_path):
    meta = server._write_skills(str(tmp_path), [{"name": "demo", "content": "# Demo"}], backend="roder")
    assert (tmp_path / ".harness/home/.codex/skills/demo/SKILL.md").read_text() == "# Demo"
    assert meta[0]["entry"].startswith(".harness/")
