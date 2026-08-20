"""The dsh normalizer and driver pieces, against live-captured wire shapes.

Every fixture below is verbatim from `deepseek-harness-sdk==0.1.0rc7` runs on 2026-08-20:
the bad-key run (error terminal), the TokenRouter tool run (tool/call + tool/result +
usage + retry ladder), and the raw TokenRouter SSE whose empty-string id/name fields are
the reason the driver's relay exists.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import _build_dsh, _dsh_to_claude, Auth  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402


def _run(lines, model="deepseek-v4-pro"):
    state = {"model": model, "final": ""}
    out = [_dsh_to_claude(ln, state) for ln in lines]
    return out, state


def _flat(chunks):
    return [e for evs in chunks for e in evs]


def _ev(t, seq, data, sid="s1"):
    return {"m": "session.event", "p": {"sessionId": sid, "event": {"type": t, "seq": seq, "time": 0, "data": data}}}


# ── error terminal: the CLI-exits-0 lesson, dsh edition ─────────────────────────────
ERROR_RUN = [
    {"m": "__hr_init", "p": {"session_id": "spike-001"}},
    {"m": "session.status", "p": {"sessionId": "spike-001", "status": "running"}},
    _ev("turn/start", 1, {"turn": 1}, "spike-001"),
    _ev("assistant/chunk", 8, {"turn": 1, "step": 1, "chunk": {"type": "finish", "reason": {"kind": "error", "failure": {
        "message": "Authentication Fails, Your api key: ****-key is invalid", "code": "AUTH", "status": 401}}}}, "spike-001"),
    _ev("turn/end", 10, {"turn": 1, "reason": {"kind": "error", "error": {
        "message": "Authentication Fails, Your api key: ****-key is invalid", "code": "AUTH", "status": 401}}}, "spike-001"),
    {"m": "session.status", "p": {"sessionId": "spike-001", "status": "idle"}},
    {"m": "__hr_result", "p": {"final": "", "reason": "error", "session_id": "spike-001"}},
]


def test_error_run_yields_error_result():
    chunks, _ = _run(ERROR_RUN)
    results = [e for e in _flat(chunks) if e.get("type") == "result"]
    assert len(results) == 1
    assert results[0]["is_error"] is True
    assert "Authentication Fails" in results[0]["result"]


def test_init_comes_from_hr_init():
    chunks, _ = _run(ERROR_RUN)
    init = _flat(chunks)[0]
    assert init["type"] == "system" and init["session_id"] == "spike-001"


def test_init_falls_back_to_first_event_session_id():
    lines = [{"m": "__hr_init", "p": {"session_id": ""}},
             _ev("turn/start", 1, {"turn": 1}, "generated-sid"),
             {"m": "__hr_result", "p": {"final": "hi", "reason": "completed"}}]
    chunks, _ = _run(lines)
    init = next(e for e in _flat(chunks) if e.get("type") == "system")
    assert init["session_id"] == "generated-sid"


# ── happy path with tools, streaming, usage dedup ───────────────────────────────────
HAPPY = [
    {"m": "__hr_init", "p": {"session_id": "t4"}},
    _ev("turn/start", 1, {"turn": 1}),
    _ev("assistant/chunk", 20, {"turn": 1, "step": 1, "chunk": {"type": "block-start", "index": 0, "blockType": "reasoning"}}),
    _ev("assistant/chunk", 21, {"turn": 1, "step": 1, "chunk": {"type": "reasoning-delta", "index": 0, "text": "The user wants echo."}}),
    _ev("assistant/chunk", 30, {"turn": 1, "step": 1, "chunk": {"type": "block-end", "index": 0, "block": {"type": "reasoning", "text": "The user wants echo."}}}),
    _ev("assistant/chunk", 32, {"turn": 1, "step": 1, "chunk": {"type": "usage", "usage": {"inputTokens": 210, "outputTokens": 87, "cacheReadTokens": 1024, "reasoningTokens": 17}}}),
    # a retry re-reports the same (turn, step): REPLACED, not summed
    _ev("assistant/chunk", 33, {"turn": 1, "step": 1, "chunk": {"type": "usage", "usage": {"inputTokens": 215, "outputTokens": 90, "cacheReadTokens": 1024}}}),
    _ev("tool/call", 35, {"turn": 1, "step": 1, "callId": "call_1", "name": "bash",
                          "arguments": "{\"command\": \"echo hola-dsh\"}"}),
    _ev("tool/result", 36, {"turn": 1, "step": 1, "message": {"role": "user", "source": {"kind": "tool", "callId": "call_1"},
        "content": [{"type": "tool-result", "toolCallId": "call_1", "isError": False,
                     "content": [{"type": "text", "text": "hola-dsh"}]}]}}),
    _ev("assistant/chunk", 40, {"turn": 1, "step": 2, "chunk": {"type": "text-delta", "index": 0, "text": "hola"}}),
    _ev("assistant/chunk", 41, {"turn": 1, "step": 2, "chunk": {"type": "text-delta", "index": 0, "text": "-dsh"}}),
    _ev("assistant/message", 42, {"turn": 1, "step": 2, "message": {"role": "assistant",
        "content": [{"type": "text", "text": "hola-dsh"}], "source": {"kind": "model"}}}),
    _ev("assistant/chunk", 43, {"turn": 1, "step": 2, "chunk": {"type": "usage", "usage": {"inputTokens": 300, "outputTokens": 5}}}),
    _ev("turn/end", 44, {"turn": 1, "reason": {"kind": "completed"}}),
    {"m": "__hr_result", "p": {"final": "hola-dsh", "reason": "completed", "session_id": "t4"}},
]


def test_happy_path_thinking_text_and_result():
    chunks, state = _run(HAPPY)
    evs = _flat(chunks)
    thinking = [c["thinking"] for e in evs if e.get("type") == "assistant"
                for c in e["message"]["content"] if c.get("type") == "thinking"]
    assert thinking == ["The user wants echo."]
    texts = [c["text"] for e in evs if e.get("type") == "assistant"
             for c in e["message"]["content"] if c.get("type") == "text"]
    assert texts == ["hola", "-dsh"]   # committed message matched the stream: no re-paint
    result = next(e for e in evs if e.get("type") == "result")
    assert result["subtype"] == "success" and result["result"] == "hola-dsh"


def test_usage_replaced_per_step_then_summed():
    chunks, _ = _run(HAPPY)
    result = next(e for e in _flat(chunks) if e.get("type") == "result")
    # step1 replaced to 215/90 + step2 300/5; cacheRead from the replacement
    assert result["usage"] == {"input_tokens": 515, "output_tokens": 95, "cache_read_tokens": 1024}


def test_tool_events_map():
    chunks, _ = _run(HAPPY)
    evs = _flat(chunks)
    use = next(c for e in evs if e.get("type") == "assistant"
               for c in e["message"]["content"] if c.get("type") == "tool_use")
    assert use["id"] == "call_1" and use["name"] == "bash" and use["input"] == {"command": "echo hola-dsh"}
    res = next(c for e in evs if e.get("type") == "user"
               for c in e["message"]["content"] if c.get("type") == "tool_result")
    assert res["tool_use_id"] == "call_1" and res["content"] == "hola-dsh" and res["is_error"] is False


def test_max_tokens_maps_to_max_turns_subtype():
    lines = [{"m": "__hr_init", "p": {"session_id": "s"}},
             _ev("turn/end", 5, {"turn": 1, "reason": {"kind": "max-tokens"}}),
             {"m": "__hr_result", "p": {"final": "partial", "reason": "max-tokens"}}]
    chunks, _ = _run(lines)
    result = next(e for e in _flat(chunks) if e.get("type") == "result")
    assert result["subtype"] == "error_max_turns" and result["result"] == "partial"


# ── the relay rewrite: the exact TokenRouter delta shapes ───────────────────────────
def test_relay_drops_empty_id_and_name_only():
    first = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_617","type":"function",'
             b'"function":{"name":"bash","arguments":""}}]},"finish_reason":null,"index":0}]}')
    cont = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"","type":"function",'
            b'"function":{"name":"","arguments":"{\\"command\\""}}]},"finish_reason":null,"index":0}]}')
    out1 = json.loads(dsh_driver._rewrite_sse_line(first)[6:])
    tc1 = out1["choices"][0]["delta"]["tool_calls"][0]
    assert tc1["id"] == "call_617" and tc1["function"]["name"] == "bash"
    out2 = json.loads(dsh_driver._rewrite_sse_line(cont)[6:])
    tc2 = out2["choices"][0]["delta"]["tool_calls"][0]
    assert "id" not in tc2 and "name" not in tc2["function"]
    assert tc2["function"]["arguments"] == '{"command"'


def test_relay_leaves_non_data_lines_alone():
    assert dsh_driver._rewrite_sse_line(b"data: [DONE]") == b"data: [DONE]"
    assert dsh_driver._rewrite_sse_line(b"") == b""


# ── builder ─────────────────────────────────────────────────────────────────────────
def test_build_dsh_stages_creds_out_of_argv(tmp_path):
    env = {"HOME": str(tmp_path)}
    cmd = _build_dsh("deepseek", Auth(api_key="k-secret", base_url="https://tr.example/v1"),
                     "deepseek/deepseek-v4-pro", "do it", str(tmp_path), env,
                     resume_session_id="sid-9",
                     mcp_servers=[{"name": "wiki", "url": "https://mcp.example/mcp"}])
    assert env["HR_DSH_BASE_URL"] == "https://tr.example/v1"
    assert env["HR_DSH_API_KEY"] == "k-secret"
    assert "k-secret" not in " ".join(cmd)   # the key travels in env, never argv (ps-visible)
    job = json.loads(cmd[2])
    assert job["session_id"] == "sid-9"
    assert job["mcp_servers"][0]["url"] == "https://mcp.example/mcp"
    assert "system_prompt" not in job
