"""The cline backend, against facts measured on the shipped 3.0.60 binary.

Every assertion here encodes something verified live against a stub upstream, not read from
documentation: the settings file is the only auth wiring that works (the env vars the binary
carries are ignored for openai-compatible), a whitespace-free prompt is parsed as a subcommand,
--json --id refuses every way of passing a prompt, and the event stream's tool round trip.
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (Auth, BACKENDS, _agent_doc_path, _build_cline, _cline_eof,  # noqa: E402
                    _cline_to_claude)


def _argv(prompt="do the thing", **kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_cline("openai-api", Auth(api_key="", base_url="https://relay.example/v1"),
                       "gpt-5.4", prompt, d, env, **kw)
    return cmd, d, env


def test_argv_is_headless_json_with_auto_approve():
    cmd, d, env = _argv()
    assert cmd[0] == "cline" and cmd[1] == "do the thing"
    assert "--json" in cmd and "--auto-approve" in cmd
    assert "-P" in cmd and "openai-compatible" in cmd
    assert "-z" not in cmd, "the background hub daemon must never be part of a turn"


def test_home_is_redirected_and_settings_land_inside_the_workspace():
    """The credentials file is the ONLY wiring cline honours for openai-compatible: the binary
    carries CLINE_API_KEY/CLINE_API_BASE_URL but a live probe showed them ignored (the stub
    upstream never saw the request; api.openai.com did). So the settings file must exist, inside
    the checkpointed workspace, before the process starts."""
    cmd, d, env = _argv()
    assert env["HOME"] == str(pathlib.Path(d) / ".harness" / "home")
    p = pathlib.Path(env["HOME"]) / ".cline" / "data" / "settings" / "providers.json"
    assert p.exists()
    cfg = json.loads(p.read_text())
    st = cfg["providers"]["openai-compatible"]["settings"]
    assert st["baseUrl"] == "https://relay.example/v1"
    assert st["model"] == "gpt-5.4"
    # updatedAt is REQUIRED by 3.0.60's settings schema. Bisected live: the identical file
    # without it is silently rejected wholesale, the entry is rewritten down to
    # {provider, model}, and the turn dies on api.openai.com's keyless 401.
    assert cfg["providers"]["openai-compatible"].get("updatedAt"), \
        "updatedAt missing: cline will silently discard the whole provider entry"


def test_a_whitespace_free_prompt_gets_a_trailing_newline():
    """A single-token prompt is parsed as a SUBCOMMAND ('Unknown command or unquoted prompt: hi')
    and `--` does not rescue it. A trailing newline does — verified on 3.0.60 both ways."""
    cmd, _, _ = _argv(prompt="hi")
    assert cmd[1] == "hi\n"
    cmd2, _, _ = _argv(prompt="hi there")
    assert cmd2[1] == "hi there"


def test_resume_is_deliberately_not_wired():
    """3.0.60's `--json --id` refuses every way of passing a prompt (argument, =form, piped
    stdin — each verified individually, and the identical argv without --id runs). Passing a
    resume id must therefore change nothing rather than produce a turn that cannot start."""
    cmd, _, _ = _argv(resume_session_id="1788124440212_6s446")
    assert "--id" not in cmd


def test_mcp_servers_land_in_clines_own_settings_file():
    d = tempfile.mkdtemp()
    env: dict = {}
    _build_cline("openai-api", Auth(api_key="", base_url="https://r.example/v1"), "gpt-5.4",
                 "go", d, env,
                 mcp_servers=[{"name": "graph", "url": "https://mcp.example/mcp",
                               "headers": {"x-k": "v"}},
                              {"name": "off", "url": "https://x.example", "enabled": False}])
    p = pathlib.Path(env["HOME"]) / ".cline" / "data" / "settings" / "cline_mcp_settings.json"
    servers = json.loads(p.read_text())["mcpServers"]
    assert servers["graph"]["transport"] == {"type": "streamableHttp",
                                             "url": "https://mcp.example/mcp",
                                             "headers": {"x-k": "v"}}
    assert "off" not in servers, "a disabled server must not be contacted, so it is not written"


def test_agent_doc_is_agents_md():
    assert _agent_doc_path("/w", "cline").name == "AGENTS.md"


def test_registered_with_a_normalizer_and_an_eof():
    assert BACKENDS["cline"]["normalize"] is _cline_to_claude
    assert getattr(_cline_to_claude, "eof", None) is _cline_eof


# ── the event stream, exactly as 3.0.60 emitted it against a stub upstream ──────────

def _ev(line, state):
    return _cline_to_claude(json.loads(line), state)


def test_the_verified_tool_round_trip_normalizes():
    state = {"model": "gpt-5.4"}
    out = []
    for line in [
        '{"ts":"t","type":"hook_event","hookEventName":"agent_start","taskId":"conv_1","parentAgentId":null}',
        '{"ts":"t","type":"agent_event","event":{"type":"iteration_start","iteration":1}}',
        '{"ts":"t","type":"agent_event","event":{"type":"content_start","contentType":"tool","toolName":"run_commands","toolCallId":"call_1","input":{"commands":["echo hi"]}}}',
        '{"ts":"t","type":"agent_event","event":{"type":"content_end","contentType":"tool","toolName":"run_commands","toolCallId":"call_1","output":[{"query":"echo hi","result":"","success":true}],"durationMs":3}}',
        '{"ts":"t","type":"agent_event","event":{"type":"content_start","contentType":"text","text":"Done.","accumulated":"Done."}}',
        '{"ts":"t","type":"agent_event","event":{"type":"content_end","contentType":"text","text":"Done."}}',
        '{"ts":"t","type":"run_result","finishReason":"completed","iterations":2,"usage":{"inputTokens":21,"outputTokens":11,"cacheReadTokens":0,"cacheWriteTokens":0,"totalCost":0},"durationMs":29,"text":"Done.","model":{"id":"gpt-5.4"}}',
    ]:
        out.extend(_ev(line, state))
    types = [(e["type"], (e.get("message") or {}).get("content", [{}])[0].get("type"))
             for e in out]
    assert types[0] == ("system", None)
    assert ("assistant", "tool_use") in types
    assert ("user", "tool_result") in types
    # text arrives whole on content_start AND content_end; only content_end may emit, once
    assert sum(1 for t in types if t == ("assistant", "text")) == 1
    final = out[-1]
    assert final["type"] == "result" and final["is_error"] is False
    assert final["result"] == "Done."
    assert final["usage"] == {"input_tokens": 21, "output_tokens": 11,
                              "cache_read_tokens": 0, "cache_write_tokens": 0}
    assert _cline_eof(state, 0) == [], "a healthy turn already has its result; eof must add nothing"


def test_the_verified_error_shape_fails_the_turn():
    """Captured live: a bad credential emits agent_event{type:error} and run_result
    finishReason 'error' whose text restates the message."""
    state = {}
    _ev('{"ts":"t","type":"agent_event","event":{"type":"error","error":{"name":"Error","message":"no key"},"errorClass":"unknown","recoverable":false,"iteration":1}}', state)
    out = _ev('{"ts":"t","type":"run_result","finishReason":"error","iterations":1,"usage":{"inputTokens":0,"outputTokens":0},"text":"no key","model":{"id":"m"}}', state)
    assert out[-1]["type"] == "result" and out[-1]["is_error"] is True
    assert "no key" in out[-1]["result"]


def test_a_crash_before_run_result_still_yields_a_result():
    state = {"final": "partial answer"}
    out = _cline_eof(state, 1)
    assert out and out[0]["is_error"] is True
    assert "exited 1" in out[0]["result"] or state.get("_cl_error", "") in out[0]["result"]
