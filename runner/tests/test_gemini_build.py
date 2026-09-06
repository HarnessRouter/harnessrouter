"""The gemini backend (Path A: Gemini API Key only). The normalizer's event field names are
verified against the shipped 0.58.0 binary's own source (see _gemini_to_claude's docstring);
_build_gemini's CLI flags (--approval-mode, --skip-trust, --resume latest) are live-turn
verified end to end (2026-09-06) but not against every code path — see its docstring."""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (Auth, _agent_doc_path, _build_gemini, _gemini_to_claude,  # noqa: E402
                    _gemini_usage, _norm_token_usage, BACKENDS)


def _argv(**kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_gemini("google", Auth(api_key="AIza-t"), "gemini-3.6-flash", "do it", d, env, **kw)
    return cmd, d, env


def test_argv_is_headless_stream_json():
    cmd, _, _ = _argv()
    assert cmd[:3] == ["gemini", "-p", "do it"]
    assert ["-o", "stream-json"] == cmd[3:5]
    assert ["-m", "gemini-3.6-flash"] == cmd[5:7]


def test_approval_and_trust_flags_present():
    """Both are load-bearing the same way qwen's --yolo is: without an approval mode headless
    runs cannot answer the tool-confirmation prompt, and without --skip-trust a never-before-seen
    workspace (every turn here is one) hits the folder-trust gate. Live-verified 2026-09-06."""
    cmd, _, _ = _argv()
    assert "--approval-mode" in cmd and "yolo" in cmd
    assert "--skip-trust" in cmd


def test_resume_uses_latest_not_the_tracked_id():
    """gemini-cli's --resume only accepts "latest" or a numeric index, never an arbitrary id, so
    the turn's own resume_session_id cannot be passed through literally."""
    cmd, _, _ = _argv(resume_session_id="8e039a38-f91f")
    assert cmd[-2:] == ["--resume", "latest"]
    assert "8e039a38-f91f" not in cmd


def test_no_resume_flag_on_a_fresh_turn():
    cmd, _, _ = _argv()
    assert "--resume" not in cmd


def test_auth_is_environment_only_no_relay():
    """Unlike qwen, gemini has no OpenAI-compatible mode to ride a loopback relay through — the
    real key goes straight into GEMINI_API_KEY. (Whether/how this gets brokered in hosted mode is
    a gateway-side decision — see gateway's _BROKERABLE_PROVIDERS comment.)"""
    _, d, env = _argv()
    assert env["GEMINI_API_KEY"] == "AIza-t"
    st = pathlib.Path(d, ".harness", "home", ".gemini", "settings.json").read_text()
    assert "AIza-t" not in st


def test_home_is_redirected_into_the_workspace():
    _, d, env = _argv()
    assert env["HOME"] == f"{d}/.harness/home"


def test_settings_pin_the_auth_type_explicitly():
    """gemini-cli has no non-interactive CLI flag for auth type (unlike qwen's --auth-type), so
    settings.json is the only documented way to pin it instead of relying on GEMINI_API_KEY
    auto-detection."""
    _, d, _ = _argv()
    cfg = json.loads(pathlib.Path(d, ".harness", "home", ".gemini", "settings.json").read_text())
    assert cfg["security"]["auth"]["selectedType"] == "gemini-api-key"


def test_unknown_provider_rejected():
    d = tempfile.mkdtemp()
    env: dict = {}
    try:
        _build_gemini("vertex", Auth(api_key="k"), "gemini-3.6-flash", "hi", d, env)
        assert False, "expected HTTPException"
    except Exception as e:  # noqa: BLE001 — HTTPException import path differs by context
        assert "unknown gemini provider" in str(getattr(e, "detail", e))


def test_missing_api_key_rejected():
    d = tempfile.mkdtemp()
    env: dict = {}
    try:
        _build_gemini("google", Auth(), "gemini-3.6-flash", "hi", d, env)
        assert False, "expected HTTPException"
    except Exception as e:  # noqa: BLE001
        assert "api_key" in str(getattr(e, "detail", e))


def test_mcp_settings_use_the_gemini_schema():
    d = tempfile.mkdtemp()
    env: dict = {}
    _build_gemini("google", Auth(api_key="k"), "gemini-3.6-flash", "hi", d, env,
                  mcp_servers=[{"name": "docs", "url": "https://mcp.example/sse",
                                "headers": {"Authorization": "Bearer t"}},
                               {"name": "fs", "command": "npx", "args": ["-y", "server-fs"]}])
    cfg = json.loads(pathlib.Path(d, ".harness", "home", ".gemini", "settings.json").read_text())
    assert cfg["mcpServers"]["docs"] == {"httpUrl": "https://mcp.example/sse",
                                         "headers": {"Authorization": "Bearer t"}}
    assert cfg["mcpServers"]["fs"] == {"command": "npx", "args": ["-y", "server-fs"]}


def test_normalizer_is_gemini_specific_not_the_claude_passthrough():
    """Unlike qwen, gemini's native stream-json is NOT claude's schema (different event type
    names — see _gemini_to_claude's docstring), so it needs its own normalizer registered."""
    assert BACKENDS["gemini"]["normalize"] is _gemini_to_claude


def test_normalizer_maps_init_message_and_result():
    """Field names here are the shipped 0.58.0 binary's real ones (grepped from its own
    StreamJsonFormatter.emitEvent call sites), not guesses — see the module docstring."""
    state = {"model": "gemini-3.6-flash"}
    init = _gemini_to_claude({"type": "init", "session_id": "abc"}, state)
    assert init == [{"type": "system", "subtype": "init", "session_id": "abc",
                     "model": "gemini-3.6-flash"}]
    msg = _gemini_to_claude({"type": "message", "role": "assistant", "content": "hi"}, state)
    assert msg == [{"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}]
    # A real success `result` event carries NO text field at all (no `response` key) — the
    # final answer only ever arrives via accumulated `message` deltas, which is why state["final"]
    # (built from the "hi" message above) is what should come back here, not something read
    # off the result event itself.
    result = _gemini_to_claude({"type": "result", "status": "success", "stats": {}}, state)
    assert result == [{"type": "result", "subtype": "success", "is_error": False,
                       "result": "hi", "usage": _norm_token_usage({})}]


def test_normalizer_uses_the_real_tool_use_field_names():
    """Regression test for the bug an actual failed turn caught (slides kit, 2026-09-06): the
    first version of this function guessed id/name/input, which don't exist on the wire — every
    tool call rendered as a content-free generic "Tool" row. Real fields: tool_id/tool_name/
    parameters."""
    ev = _gemini_to_claude({"type": "tool_use", "tool_id": "call_1", "tool_name": "read_file",
                            "parameters": {"path": "deck.json"}}, {})
    assert ev == [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "call_1", "name": "read_file",
         "input": {"path": "deck.json"}}]}}]


def test_normalizer_uses_the_real_tool_result_field_names():
    ok = _gemini_to_claude({"type": "tool_result", "tool_id": "call_1", "status": "success",
                            "output": "file contents"}, {})
    assert ok == [{"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "call_1", "is_error": False,
         "content": "file contents"}]}}]
    err = _gemini_to_claude({"type": "tool_result", "tool_id": "call_2", "status": "error",
                             "error": {"type": "ToolError", "message": "file not found"}}, {})
    assert err == [{"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "call_2", "is_error": True,
         "content": "file not found"}]}}]


def test_normalizer_surfaces_the_real_error_message_on_a_failed_result():
    """Regression test for the other half of the same bug: a failed turn's `result` event has
    NO `response` field — the failure reason lives at error.message — but the old code fell back
    to state["final"], which is whatever assistant text happened to stream before the failure
    (in the real failed turn this caught, that was the FIRST sentence of a 5-minute task,
    rendered as if it were the error)."""
    state = {"final": "I will activate the slide-design skill to retrieve the schema."}
    result = _gemini_to_claude({"type": "result", "status": "error", "stats": {},
                                "error": {"type": "FatalToolExecutionError",
                                          "message": "tool call exceeded the turn budget"}}, state)
    assert result == [{"type": "result", "subtype": "error", "is_error": True,
                       "result": "tool call exceeded the turn budget",
                       "usage": _norm_token_usage({})}]


def test_normalizer_drops_non_fatal_error_events():
    """`error` is documented as non-fatal, and every fatal path in the source emits its own
    terminal `result` event separately — promoting `error` into a synthetic result (what v1 of
    this function did) risks ending a turn early on a warning the CLI itself would have
    continued past."""
    assert _gemini_to_claude({"type": "error", "severity": "warning", "message": "retrying"}, {}) == []


def test_instruction_file_is_gemini_md():
    assert _agent_doc_path("/ws", "gemini").name == "GEMINI.md"


def test_the_result_carries_the_served_model_and_the_fresh_input_beside_the_cached():
    """Measured on the pinned 0.58.0 (2026-09-06): `-m gemini-3.6-flash` answered with stats keyed
    "gemini-3.5-flash", because the CLI rewrites every "-flash" id on the API-key auth path. The
    gateway can only record that substitution if the result says which model ran. The stats'
    input_tokens include the cached prefix; the usage contract wants the fresh input and the cached
    part apart."""
    stats = {"total_tokens": 10835, "input_tokens": 10532, "output_tokens": 2, "cached": 8118,
             "input": 2414, "duration_ms": 2919, "tool_calls": 0,
             "models": {"gemini-3.5-flash": {"total_tokens": 10835, "input_tokens": 10532,
                                             "output_tokens": 2, "cached": 8118, "input": 2414}}}
    out = _gemini_to_claude({"type": "result", "status": "success", "stats": stats}, {"final": "PONG"})
    assert out == [{"type": "result", "subtype": "success", "is_error": False, "result": "PONG",
                    "usage": {"input_tokens": 2414, "output_tokens": 2, "cache_read_tokens": 8118},
                    "model": "gemini-3.5-flash"}]
    assert _gemini_usage({}) == _norm_token_usage({})          # the same shape as every other normalizer
    assert _gemini_usage({"input_tokens": 100, "output_tokens": 5})["input_tokens"] == 100
