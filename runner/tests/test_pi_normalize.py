"""The pi normalizer, against the CLI's real behavior.

The error-path fixture below is a VERBATIM capture of `pi -p --mode json` (0.84.2) with an
invalid Anthropic key. The load-bearing fact it encodes: the process exited 0 — failure is
stopReason="error" on the assistant message, so the synthesized result event is the only place
status can truthfully come from.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import _build_pi, _pi_models_json, _pi_to_claude, Auth  # noqa: E402


def _run(events, model="claude-sonnet-4-6"):
    state = {"model": model, "final": ""}
    out = []
    for ev in events:
        out.append(_pi_to_claude(ev, state))
    return out, state


def _flat(chunks):
    return [e for evs in chunks for e in evs]


# ── error path: the verbatim bad-key capture ─────────────────────────────────────────
_ERR_MSG = {"role": "assistant", "content": [], "api": "anthropic-messages",
            "provider": "anthropic", "model": "claude-haiku-4-5",
            "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "stopReason": "error",
            "errorMessage": '401 {"type":"error","error":{"type":"authentication_error",'
                            '"message":"API key is invalid."},"request_id":null}'}
ERROR_STREAM = [
    {"type": "session", "version": 3, "id": "11111111-2222-3333-4444-555555555555",
     "timestamp": "2026-08-20T04:00:19.261Z", "cwd": "/ws"},
    {"type": "agent_start"},
    {"type": "turn_start"},
    {"type": "message_start", "message": {"role": "user", "content": [{"type": "text", "text": "say hi"}]}},
    {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "say hi"}]}},
    {"type": "message_start", "message": _ERR_MSG},
    {"type": "message_end", "message": _ERR_MSG},
    {"type": "turn_end", "message": _ERR_MSG, "toolResults": []},
    {"type": "agent_end", "messages": [_ERR_MSG], "willRetry": False},
    {"type": "agent_settled"},
]


def test_error_run_yields_error_result_despite_exit_zero():
    chunks, _ = _run(ERROR_STREAM)
    evs = _flat(chunks)
    results = [e for e in evs if e.get("type") == "result"]
    assert len(results) == 1
    assert results[0]["is_error"] is True
    assert "authentication_error" in results[0]["result"]


def test_session_header_becomes_init_with_session_id():
    chunks, _ = _run(ERROR_STREAM)
    init = _flat(chunks)[0]
    assert init["type"] == "system" and init["subtype"] == "init"
    assert init["session_id"] == "11111111-2222-3333-4444-555555555555"


def test_user_message_echo_is_not_reemitted():
    chunks, _ = _run(ERROR_STREAM)
    texts = [e for e in _flat(chunks) if e.get("type") == "assistant"]
    assert texts == []   # the prompt echo must not come back as assistant output


# ── happy path: deltas, tools, usage ─────────────────────────────────────────────────
def _ok_msg(text, usage):
    return {"role": "assistant", "content": [{"type": "text", "text": text}],
            "usage": usage, "stopReason": "stop"}


HAPPY = [
    {"type": "session", "version": 3, "id": "s1", "cwd": "/ws"},
    {"type": "agent_start"}, {"type": "turn_start"},
    {"type": "message_start", "message": {"role": "assistant", "content": []}},
    {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "Check"}},
    {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "ing."}},
    {"type": "message_end", "message": _ok_msg("Checking.", {"input": 10, "output": 2, "cacheRead": 5, "cacheWrite": 0})},
    {"type": "tool_execution_start", "toolCallId": "t1", "toolName": "bash", "args": {"command": "ls"}},
    {"type": "tool_execution_end", "toolCallId": "t1", "toolName": "bash",
     "result": {"content": [{"type": "text", "text": "file.txt"}]}, "isError": False},
    {"type": "turn_end"}, {"type": "turn_start"},
    {"type": "message_start", "message": {"role": "assistant", "content": []}},
    {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "Done"}},
    {"type": "message_end", "message": _ok_msg("Done. One file.", {"input": 20, "output": 4, "cacheRead": 0, "cacheWrite": 3})},
    {"type": "turn_end"},
    {"type": "agent_end", "messages": []},
    {"type": "agent_settled"},
]


def test_happy_path_streams_deltas_then_only_the_tail():
    chunks, state = _run(HAPPY)
    texts = [c["text"] for e in _flat(chunks) if e.get("type") == "assistant"
             for c in e["message"]["content"] if c.get("type") == "text"]
    # deltas stream as they arrive; message_end adds only what was never streamed
    assert texts == ["Check", "ing.", "Done", ". One file."]


def test_final_is_last_message_not_a_concatenation():
    _, state = _run(HAPPY)
    assert state["final"] == "Done. One file."


def test_tool_events_map_to_tool_use_and_tool_result():
    chunks, _ = _run(HAPPY)
    evs = _flat(chunks)
    use = next(c for e in evs if e.get("type") == "assistant"
               for c in e["message"]["content"] if c.get("type") == "tool_use")
    assert use["name"] == "bash" and use["input"] == {"command": "ls"}
    res = next(c for e in evs if e.get("type") == "user"
               for c in e["message"]["content"] if c.get("type") == "tool_result")
    assert res["tool_use_id"] == "t1" and res["content"] == "file.txt" and res["is_error"] is False


def test_usage_sums_across_messages():
    chunks, _ = _run(HAPPY)
    result = next(e for e in _flat(chunks) if e.get("type") == "result")
    assert result["subtype"] == "success"
    assert result["usage"] == {"input_tokens": 30, "output_tokens": 6,
                               "cache_read_tokens": 5, "cache_write_tokens": 3}
    assert result["result"] == "Done. One file."


def test_no_deltas_still_emits_full_text():
    stream = [
        {"type": "session", "id": "s2", "cwd": "/ws"},
        {"type": "message_end", "message": _ok_msg("Plain answer.", {"input": 1, "output": 1})},
        {"type": "agent_end"},
    ]
    chunks, state = _run(stream)
    texts = [c["text"] for e in _flat(chunks) if e.get("type") == "assistant"
             for c in e["message"]["content"] if c.get("type") == "text"]
    assert texts == ["Plain answer."]
    assert state["final"] == "Plain answer."


# ── builder ──────────────────────────────────────────────────────────────────────────
def _cmdline(tmp_path, provider="anthropic", base_url=None, model="claude-sonnet-4-6", **kw):
    env = {"HOME": str(tmp_path / "home")}
    auth = Auth(api_key="k-test", base_url=base_url)
    return _build_pi(provider, auth, model, "do it", str(tmp_path), env,
                     **kw), env


def test_build_native_anthropic_sets_env_not_models_json(tmp_path):
    cmd, env = _cmdline(tmp_path)
    assert env["ANTHROPIC_API_KEY"] == "k-test"
    assert "--provider" in cmd and cmd[cmd.index("--provider") + 1] == "anthropic"
    assert not (tmp_path / "home" / ".pi" / "agent" / "models.json").exists()
    assert "--approve" in cmd and "--no-extensions" in cmd
    assert cmd[-1] == "do it"


def test_build_tokenrouter_claude_family_uses_anthropic_messages(tmp_path):
    _cmdline(tmp_path, provider="tokenrouter", base_url="https://tr.example/v1")
    mj = json.loads((tmp_path / "home" / ".pi" / "agent" / "models.json").read_text())
    hr = mj["providers"]["hr"]
    assert hr["api"] == "anthropic-messages"
    assert hr["baseUrl"] == "https://tr.example"   # /v1 stripped: pi appends /v1/messages itself
    assert hr["apiKey"] == "k-test"


def test_build_tokenrouter_gpt5_uses_openai_responses(tmp_path):
    cmd, _ = _cmdline(tmp_path, provider="tokenrouter", base_url="https://tr.example",
                      model="gpt-5.4-mini")
    mj = json.loads((tmp_path / "home" / ".pi" / "agent" / "models.json").read_text())
    assert mj["providers"]["hr"]["api"] == "openai-responses"
    assert mj["providers"]["hr"]["baseUrl"] == "https://tr.example/v1"
    assert cmd[cmd.index("--provider") + 1] == "hr"


def test_build_openai_api_other_family_uses_completions(tmp_path):
    _cmdline(tmp_path, provider="openai-api", base_url="https://agg.example/v1",
             model="deepseek-v4-pro")
    mj = json.loads((tmp_path / "home" / ".pi" / "agent" / "models.json").read_text())
    assert mj["providers"]["hr"]["api"] == "openai-completions"


def test_build_resume_and_disabled_tools(tmp_path):
    cmd, _ = _cmdline(tmp_path, resume_session_id="abc-123",
                      tools_disabled=["bash (Shell)", "write"])
    assert cmd[cmd.index("--session-id") + 1] == "abc-123"
    assert cmd[cmd.index("--exclude-tools") + 1] == "bash,write"


def test_build_mcp_writes_config_and_flags_extension(tmp_path, monkeypatch):
    ext = tmp_path / "adapter"; ext.mkdir()
    monkeypatch.setenv("HR_PI_MCP_EXT", str(ext))
    cmd, _ = _cmdline(tmp_path, mcp_servers=[
        {"name": "wiki", "url": "https://mcp.example/mcp", "auth": "tok123",
         "headers": {"X-Org": "o1"}}])
    mcp = json.loads((tmp_path / "home" / ".pi" / "agent" / "mcp.json").read_text())
    assert mcp["mcpServers"]["wiki"]["url"] == "https://mcp.example/mcp"
    assert mcp["mcpServers"]["wiki"]["headers"]["Authorization"] == "Bearer tok123"
    assert mcp["mcpServers"]["wiki"]["headers"]["X-Org"] == "o1"
    assert cmd[cmd.index("--extension") + 1] == str(ext)


def test_models_json_v1_normalization():
    a = json.loads(_pi_models_json("anthropic-messages", "https://x.example/v1/", "k", "m"))
    assert a["providers"]["hr"]["baseUrl"] == "https://x.example"
    b = json.loads(_pi_models_json("openai-completions", "https://x.example", "k", "m"))
    assert b["providers"]["hr"]["baseUrl"] == "https://x.example/v1"


def test_build_text_only_model_declares_text_input(tmp_path):
    """A text-only channel (qwen3.7-max via TokenRouter) must get input:["text"] — pi then DROPS
    replayed image tool-results instead of sending a user+image message the channel 400s on.
    Mechanism verified against a capturing sink: vision=True serialized the session's image as
    a user message with an image part (the exact shape the provider rejected); vision=False
    omitted it and the turn completed."""
    cmd, _ = _cmdline(tmp_path, provider="tokenrouter", base_url="https://tr.example/v1",
                      model="qwen/qwen3.7-max", vision=False)
    mj = json.loads((tmp_path / "home" / ".pi" / "agent" / "models.json").read_text())
    assert mj["providers"]["hr"]["models"][0]["input"] == ["text"]


def test_build_vision_default_keeps_image_input(tmp_path):
    _cmdline(tmp_path, provider="tokenrouter", base_url="https://tr.example/v1",
             model="moonshotai/kimi-k3")
    mj = json.loads((tmp_path / "home" / ".pi" / "agent" / "models.json").read_text())
    assert mj["providers"]["hr"]["models"][0]["input"] == ["text", "image"]
