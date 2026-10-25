"""The dsh normalizer and driver pieces, against live-captured wire shapes.

Every fixture below is verbatim from `deepseek-harness-sdk==0.1.0rc7` runs on 2026-08-20; the
relay and event shapes were re-verified against 0.1.2rc1 on 2026-09-08 (same envelope, same types):
the bad-key run (error terminal), the TokenRouter tool run (tool/call + tool/result +
usage + retry ladder), and the raw TokenRouter SSE whose empty-string id/name fields are
the reason the dsh route on the runner's relay carries tool_call_deltas_no_empty.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import _build_dsh, _dsh_to_claude, Auth  # noqa: E402
from server import _tool_call_delta_without_empty_fields as _strip_empty  # noqa: E402
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


# ── the route's rewrite (tool_call_deltas_no_empty): the exact TokenRouter delta shapes ──
def test_relay_drops_empty_id_and_name_only():
    first = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_617","type":"function",'
             b'"function":{"name":"bash","arguments":""}}]},"finish_reason":null,"index":0}]}')
    cont = (b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"","type":"function",'
            b'"function":{"name":"","arguments":"{\\"command\\""}}]},"finish_reason":null,"index":0}]}')
    out1 = json.loads(_strip_empty(first)[6:])
    tc1 = out1["choices"][0]["delta"]["tool_calls"][0]
    assert tc1["id"] == "call_617" and tc1["function"]["name"] == "bash"
    out2 = json.loads(_strip_empty(cont)[6:])
    tc2 = out2["choices"][0]["delta"]["tool_calls"][0]
    assert "id" not in tc2 and "name" not in tc2["function"]
    assert tc2["function"]["arguments"] == '{"command"'


def test_relay_leaves_non_data_lines_alone():
    assert _strip_empty(b"data: [DONE]") == b"data: [DONE]"
    assert _strip_empty(b"") == b""
    assert _strip_empty(b"event: delta") == b"event: delta"
    assert _strip_empty(b"data:[DONE]") == b"data:[DONE]"


def test_relay_rewrites_a_data_line_with_no_space_after_the_colon():
    """The space after an SSE field's colon is optional, so `data:{...}` is a conformant
    delta and its empty id/name must be stripped exactly as the spaced form's are."""
    cont = (b'{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"","type":"function",'
            b'"function":{"name":"","arguments":"{\\"command\\""}}]},"finish_reason":null,"index":0}]}')
    spaced = _strip_empty(b"data: " + cont)
    tight = _strip_empty(b"data:" + cont)
    assert tight == spaced
    tc = json.loads(tight[6:])["choices"][0]["delta"]["tool_calls"][0]
    assert "id" not in tc and "name" not in tc["function"]
    assert tc["function"]["arguments"] == '{"command"'


# ── builder ─────────────────────────────────────────────────────────────────────────
def test_build_dsh_stages_creds_out_of_argv(tmp_path):
    env = {"HOME": str(tmp_path)}
    cmd = _build_dsh("deepseek", Auth(api_key="k-secret", base_url="https://tr.example/v1"),
                     "deepseek/deepseek-v4-pro", "do it", str(tmp_path), env,
                     resume_session_id="sid-9",
                     mcp_servers=[{"name": "wiki", "url": "https://mcp.example/mcp"}])
    assert "k-secret" not in " ".join(cmd)   # never argv (ps-visible)
    # ...and never the driver's env either: the key stays on the runner relay's route (#382)
    assert "k-secret" not in json.dumps(env)
    base, key, flags = _route(env)
    assert (base, key) == ("https://tr.example/v1", "k-secret")
    assert flags["tool_call_deltas_no_empty"] is True
    job = json.loads(cmd[2])
    assert job["session_id"] == "sid-9"
    assert job["mcp_servers"][0]["url"] == "https://mcp.example/mcp"
    assert "system_prompt" not in job


def test_build_dsh_routes_by_family_not_provider(tmp_path):
    """deepseek models keep the verified launch adapter whatever the integration is called;
    claude/gpt/other families ride the pi-ai route with the api the pi backend proved."""
    env = {"HOME": str(tmp_path)}
    a = Auth(api_key="k", base_url="https://tr.example/v1")
    j = lambda cmd: json.loads(cmd[2])
    assert "llm" not in j(_build_dsh("tokenrouter", a, "deepseek/deepseek-v4-pro", "x", str(tmp_path), env))
    assert j(_build_dsh("tokenrouter", a, "claude-haiku-4-5", "x", str(tmp_path), env))["llm"]["api"] == "anthropic-messages"
    assert j(_build_dsh("tokenrouter", a, "gpt-5.4-mini", "x", str(tmp_path), env))["llm"]["api"] == "openai-responses"
    assert j(_build_dsh("tokenrouter", a, "moonshotai/kimi-k3", "x", str(tmp_path), env))["llm"]["api"] == "openai-completions"
    assert j(_build_dsh("tokenrouter", a, "qwen/qwen3.7-max", "x", str(tmp_path), env, vision=False))["llm"]["vision"] is False


def test_build_dsh_native_anthropic_default_base(tmp_path):
    env = {"HOME": str(tmp_path)}
    _build_dsh("anthropic", Auth(api_key="k"), "claude-sonnet-4-6", "x", str(tmp_path), env)
    assert _route(env)[0] == "https://api.anthropic.com/v1"


def _route(env):
    """The route _build_dsh registered on the runner's relay, by the placeholder it handed over."""
    assert env["HR_DSH_RELAY_BASE"] == f"http://127.0.0.1:{rs._HERMES_RELAY['port']}/v1"
    return rs._HERMES_RELAY["routes"][env["HR_DSH_RELAY_TOKEN"]]


def test_build_dsh_hands_the_driver_a_route_and_nothing_else(tmp_path):
    """The driver gets the relay's base and the route's placeholder: no key, no upstream, and no
    thinking level or wait of its own to apply, since it has no relay to apply them in (#382)."""
    env = {"HOME": str(tmp_path)}
    _build_dsh("tokenrouter", Auth(api_key="k-secret", base_url="https://tr.example/v1"),
               "deepseek/deepseek-v4-pro", "x", str(tmp_path), env)
    assert {k for k in env if k.startswith("HR_DSH_")} == {"HR_DSH_RELAY_BASE", "HR_DSH_RELAY_TOKEN"}
    assert "HR_RELAY_UPSTREAM_TIMEOUT_S" not in env
    assert env["HR_DSH_RELAY_TOKEN"].startswith("hr-relay-")


def test_build_dsh_joins_a_custom_base_exactly_as_it_was_stored(tmp_path):
    """A custom OpenAI endpoint carries its own path, versioned or not; the relay must not add /v1
    to it (the driver's relay joined onto it as-is, and so does this route: exact_base)."""
    for stored in ("https://host.example/api/coding/v3", "https://host.example/api"):
        env = {"HOME": str(tmp_path)}
        _build_dsh("openai-api", Auth(api_key="k", base_url=stored, api_format="openai"),
                   "deepseek-v4-pro", "x", str(tmp_path), env)
        assert _route(env)[0] == stored


def _patch(tmp_path, servers, llm=None, model="m"):
    import yaml
    home = tmp_path / "home"
    out = pathlib.Path(dsh_driver._compose_patch(home, servers, llm=llm, relay_base="http://127.0.0.1:9999/v1",
                                                 model=model, cwd=str(tmp_path / "ws")))
    return out.read_text(), yaml.safe_load(out.read_text())


def test_compose_patch_v1_normalization_per_api(tmp_path):
    """anthropic-messages appends /v1/messages itself — its relay base must be bare; the openai
    apis want /v1 present. The doubled /v1/v1/messages this guards against was measured live."""
    text_a, _ = _patch(tmp_path, [], llm={"api": "anthropic-messages"}, model="claude-haiku-4-5")
    assert "baseURL: http://127.0.0.1:9999\n" in text_a and "9999/v1" not in text_a
    text_o, _ = _patch(tmp_path, [], llm={"api": "openai-responses"}, model="gpt-5.4-mini")
    assert "baseURL: http://127.0.0.1:9999/v1" in text_o


def test_compose_patch_swaps_the_server_row_and_inserts_one_mcp_row_per_server(tmp_path):
    """The loader's patch grammar (0.1.2rc1): a row named by id is merged, `disabled: true` stops
    one, `insert` appends. A patch cannot rename a row, so the resume-or-create server is
    disable-plus-insert; every MCP server becomes one dsh-mcp-client row with its headers."""
    _, doc = _patch(tmp_path, [{"name": "deep wiki!", "url": "https://mcp.example/mcp", "auth": "tok",
                                "headers": {"X-Trace": "1"}},
                               {"name": "nourl"}])
    disabled = [e["id"] for e in doc if e.get("disabled") is True]
    # web-search-deepseek: the stock search calls DeepSeek's own API with the relay's placeholder key (401)
    assert disabled == ["sdk-jsonrpc-server", "sandbox", "sandbox-policy", "bash-sandbox", "fs-sandbox", "permission",
                        "web-search-deepseek"]
    rows = [e for e in doc if "insert" in e][0]["insert"]
    assert rows[0]["id"] == "hr-sdk-jsonrpc-server" and rows[0]["name"].endswith("/.dsh/hr_dsh_server.mjs")
    assert rows[0]["inject"] == ["sdkAppStartup", "loader"] and rows[0]["config"] == {"maxTokensAsSuccess": True}
    assert (tmp_path / "home" / ".dsh" / "hr_dsh_server.mjs").exists()
    # no sandboxing executor in the composition: the local executors, so no file tool advertises
    # the escalation fields GPT models fill on every call
    assert [(r["name"], r["config"]) for r in rows if r["id"] in ("hr-bash-local", "hr-fs-local")] == [
        ("@deepseek-ai/dsh-bash-local", {"cwd": str(tmp_path / "ws")}), ("@deepseek-ai/dsh-fs-local", {"cwd": str(tmp_path / "ws")})]
    mcp = [r for r in rows if r["name"] == "@deepseek-ai/dsh-mcp-client"]
    assert len(mcp) == 1, "a server without a url is not a server"
    assert mcp[0]["config"] == {"transport": "streamable-http", "serverName": "deepwiki",
                                "url": "https://mcp.example/mcp",
                                "headers": {"Authorization": "Bearer tok", "X-Trace": "1"}}
    assert not [e for e in doc if e.get("id") == "llm-pi-ai"], "the deepseek-official path merges nothing into llm-pi-ai"


def test_compose_patch_merges_the_route_into_the_stock_pi_ai_row(tmp_path):
    _, doc = _patch(tmp_path, [], llm={"api": "openai-completions", "vision": False}, model="qwen/qwen3.7-max")
    row = doc[-1]
    assert row["id"] == "llm-pi-ai" and "name" not in row, "a patch merges by id; naming the row is a rename, which the loader refuses"
    hr = row["config"]["providers"]["hr"]
    assert hr["apiKeyEnv"] == "HR_RELAY_TOKEN" and hr["models"][0] == {
        "id": "qwen/qwen3.7-max", "contextWindow": 200000, "maxTokens": 32000, "input": ["text"]}


# ── reasoning_effort strip-and-retry (conformance T-01 against LLMTR, 2026-08-20) ──────────────
# The deepseek-official adapter sends reasoning_effort unconditionally; aggregators serving
# deepseek/* over the OpenAI shape refuse the whole request. The runner's relay sends it again
# without the parameter and drops it for that model on the route (test_relay_dsh_route.py drives it).

def test_a_refusal_of_the_parameter_itself_is_recognised():
    assert rs._reasoning_effort_unsupported(
        b'{"error":{"message":"The \\"reasoning_effort\\" parameter is not supported by \\"deepseek/deepseek-v4-pro\\""}}')
    assert rs._reasoning_effort_unsupported(
        b'{"error":{"message":"Unsupported parameter: \'reasoning_effort\' is not supported with this model."}}')


def test_a_refusal_that_names_another_value_or_another_field_is_not():
    # gpt-5.6 asks for 'none' instead (_set_reasoning_effort_none): the parameter stays
    assert not rs._reasoning_effort_unsupported(
        b"Function tools with reasoning_effort are not supported for gpt-5.6 in /v1/chat/completions. "
        b"To use function tools, set reasoning_effort to 'none'.")
    assert not rs._reasoning_effort_unsupported(b'{"error":{"message":"The \\"seed\\" parameter is not supported"}}')
    assert not rs._reasoning_effort_unsupported(b"")
