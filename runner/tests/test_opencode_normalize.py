"""The opencode normalizer, against the CLI's real emitter.

Event shapes here are taken from opencode source, not from docs:
  - the emitter is `packages/opencode/src/cli/cmd/run.ts`, which writes
    {type, timestamp, sessionID, ...data} per line and emits exactly six types
  - `tokens` on step-finish is Session.getUsage()'s shape from
    `packages/opencode/src/session/session.ts` -> {total, input, output, reasoning, cache:{read,write}}

The load-bearing fact these fixtures encode: the stream is CHUNK level, not token level. The
emitter gates text and reasoning on `part.time?.end`, so each arrives once, whole. There is no
delta stream to self-heal against, unlike pi and codex.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import _opencode_mcp, _opencode_to_claude, _opencode_usage_add  # noqa: E402

SID = "ses_01hzz9k3"


def _run(events, model="gpt-5.4"):
    state = {"model": model, "final": ""}
    out = []
    for ev in events:
        out.extend(_opencode_to_claude(ev, state))
    return out, state


def _ev(t, **data):
    return {"type": t, "timestamp": 1787541564000, "sessionID": SID, **data}


def test_session_is_captured_from_the_first_line():
    """Every event carries sessionID, so init needs no separate lookup — and must fire ONCE."""
    out, _ = _run([_ev("step_start", part={"type": "step-start"}),
                   _ev("text", part={"type": "text", "text": "hi"})])
    inits = [e for e in out if e.get("type") == "system" and e.get("subtype") == "init"]
    assert len(inits) == 1
    assert inits[0]["session_id"] == SID
    assert inits[0]["model"] == "gpt-5.4"


def test_completed_text_part_is_emitted_once_and_replaces_final():
    """A later part REPLACES final rather than accumulating: a mid-run aside is not the answer."""
    out, state = _run([_ev("text", part={"type": "text", "text": "let me look"}),
                       _ev("text", part={"type": "text", "text": "the answer"})])
    texts = [c["text"] for e in out if e.get("type") == "assistant"
             for c in e["message"]["content"] if c["type"] == "text"]
    assert texts == ["let me look", "the answer"]
    assert state["final"] == "the answer"


def test_reasoning_maps_to_thinking():
    out, _ = _run([_ev("reasoning", part={"type": "reasoning", "text": "considering"})])
    think = [c["thinking"] for e in out if e.get("type") == "assistant"
             for c in e["message"]["content"] if c["type"] == "thinking"]
    assert think == ["considering"]


def test_tool_use_carries_name_and_input():
    out, _ = _run([_ev("tool_use", part={"type": "tool", "id": "prt_1", "tool": "bash",
                                         "state": {"status": "completed", "input": {"cmd": "ls"}}})])
    tools = [c for e in out if e.get("type") == "assistant"
             for c in e["message"]["content"] if c["type"] == "tool_use"]
    assert len(tools) == 1
    assert tools[0]["name"] == "bash" and tools[0]["id"] == "prt_1"
    assert tools[0]["input"] == {"cmd": "ls"}


def test_tool_error_status_is_recorded():
    _, state = _run([_ev("tool_use", part={"type": "tool", "id": "p", "tool": "bash",
                                           "state": {"status": "error", "error": "boom"}})])
    assert state["_oc_tool_errors"] == ["boom"]


def test_error_event_is_the_only_truthful_failure_signal():
    """The CLI can exit 0 on a provider error, so this event must set the error state."""
    _, state = _run([_ev("error", error={"message": "401 invalid key"})])
    assert "401 invalid key" in state["_oc_error"]


def test_usage_input_is_taken_as_cache_exclusive():
    """opencode already subtracts cache read+write from input, matching the canonical contract,
    so the accumulator must NOT subtract again."""
    state = {}
    _opencode_usage_add(state, {"total": 130, "input": 100, "output": 20, "reasoning": 5,
                                "cache": {"read": 7, "write": 3}})
    _opencode_usage_add(state, {"input": 1, "output": 2, "cache": {"read": 3, "write": 4}})
    assert state["_oc_usage"] == {"input_tokens": 101, "output_tokens": 22,
                                  "cache_read_tokens": 10, "cache_write_tokens": 7}


def test_usage_ignores_a_missing_or_malformed_payload():
    state = {}
    _opencode_usage_add(state, None)
    _opencode_usage_add(state, {"input": "nope"})
    assert state.get("_oc_usage", {}).get("input_tokens", 0) == 0


def test_mcp_remote_pins_oauth_off_and_keeps_headers():
    """An interactive OAuth dance has nowhere to happen in a sandbox."""
    out = _opencode_mcp([{"name": "docs", "url": "https://mcp.example/sse",
                          "headers": {"Authorization": "Bearer t"}}])
    assert out["docs"]["type"] == "remote"
    assert out["docs"]["oauth"] is False
    assert out["docs"]["headers"] == {"Authorization": "Bearer t"}


def test_mcp_local_builds_command_and_env():
    out = _opencode_mcp([{"name": "fs", "command": "npx", "args": ["-y", "server-fs"],
                          "env": {"ROOT": "/ws"}}])
    assert out["fs"] == {"type": "local", "command": ["npx", "-y", "server-fs"],
                         "environment": {"ROOT": "/ws"}}


def test_mcp_skips_entries_with_neither_url_nor_command():
    assert _opencode_mcp([{"name": "empty"}]) == {}


# ── permissions: opencode enforces deny HARD, unlike codex/hermes ────────────────────
from server import _opencode_denies  # noqa: E402


def test_disabled_tools_become_deny_rules():
    assert _opencode_denies(["bash", "webfetch"]) == {"bash": "deny", "webfetch": "deny"}


def test_catalog_label_suffix_is_stripped_to_the_real_key():
    """Labels arrive "bash (Shell)"-style; a label written verbatim would match no tool and
    silently disable nothing — the failure mode the claude notes call out."""
    assert _opencode_denies(["bash (Shell)", "Read"]) == {"bash": "deny", "read": "deny"}


def test_unknown_tool_names_are_dropped_not_written():
    """The config schema accepts arbitrary extra keys, so an unknown name would be stored and then
    match nothing. Dropping it keeps the written config honest about what is enforced."""
    assert _opencode_denies(["not_a_tool", "bash"]) == {"bash": "deny"}
    assert _opencode_denies([]) == {}
    assert _opencode_denies(None) == {}


# ── argv, checked against the shipped binary's own --help (opencode 1.18.23) ──────────
import json as _json  # noqa: E402
import tempfile  # noqa: E402

from server import Auth, _build_opencode  # noqa: E402


def _argv(**kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    auth = Auth(api_key="sk-test", base_url="https://relay.example/v1")
    return _build_opencode("openai-api", auth, "gpt-5.4", "do it", d, env, **kw), d, env


def test_argv_is_a_headless_json_run():
    cmd, _, _ = _argv()
    assert cmd[:4] == ["opencode", "run", "--format", "json"]
    assert "--model" in cmd and "hr/gpt-5.4" in cmd
    assert cmd[-1] == "do it"


def test_argv_disables_plugins():
    """--pure empties cfg.plugin_origins. Project config lives IN the workspace, so without this a
    task could write plugin_origins into opencode.json and have the next turn execute it."""
    cmd, _, _ = _argv()
    assert "--pure" in cmd


def test_argv_requests_thinking_or_reasoning_never_arrives():
    """run.ts gates the reasoning emit on the --thinking flag; without it the normalizer's
    reasoning branch is unreachable."""
    cmd, _, _ = _argv()
    assert "--thinking" in cmd


def test_resume_passes_the_session_id():
    cmd, _, _ = _argv(resume_session_id="ses_abc")
    assert "--session" in cmd and "ses_abc" in cmd


def test_key_goes_to_the_environment_and_never_into_the_config_file():
    cmd, d, env = _argv()
    assert env["HR_OPENCODE_KEY"] == "sk-test"
    cfg = _json.loads(open(f"{d}/opencode.json").read())
    assert cfg["provider"]["hr"]["options"]["apiKey"] == "{env:HR_OPENCODE_KEY}"
    assert "sk-test" not in open(f"{d}/opencode.json").read()
    assert cfg["provider"]["hr"]["options"]["baseURL"] == "https://relay.example/v1"


def test_a_prompt_starting_with_a_dash_is_not_read_as_a_flag():
    d = tempfile.mkdtemp()
    auth = Auth(api_key="k", base_url="https://relay.example/v1")
    cmd = _build_opencode("openai-api", auth, "gpt-5.4", "--version", d, {})
    assert cmd[-2:] == ["--", "--version"]


def test_opencode_instructions_go_to_agents_md_not_claude_md():
    """opencode's discovery targets are literally ["AGENTS.md"] (core/src/instruction-context.ts).
    Writing CLAUDE.md instead fails SILENTLY: the file lands, and the backend never reads it, so
    the harness's instructions vanish with no error anywhere."""
    from server import _agent_doc_path  # noqa: PLC0415
    assert _agent_doc_path("/ws", "opencode").name == "AGENTS.md"
    assert _agent_doc_path("/ws", "claude").name == "CLAUDE.md"


# ── the ai-sdk package is chosen per turn from the model family ───────────────────────
from server import _opencode_config  # noqa: E402


def _npm_for(model, provider):
    d = tempfile.mkdtemp()
    _opencode_config(Auth(api_key="k", base_url="https://relay.example/v1"), model, d, None, None,
                     None, provider)
    return _json.loads(open(f"{d}/opencode.json").read())["provider"]["hr"]["npm"]


def test_claude_on_an_anthropic_connection_uses_the_messages_package():
    """A claude model on an anthropic-native connection speaks Messages, not chat/completions.
    Sending it to the openai-compatible package fails at the first call."""
    assert _npm_for("claude-sonnet-5", "anthropic") == "@ai-sdk/anthropic"


def test_claude_through_the_router_also_uses_the_messages_package():
    assert _npm_for("claude-opus-5", "tokenrouter") == "@ai-sdk/anthropic"


def test_a_gpt_model_through_the_router_uses_the_responses_package():
    assert _npm_for("gpt-5.4", "tokenrouter") == "@ai-sdk/openai"


def test_everything_else_falls_to_openai_compatible():
    assert _npm_for("qwen3.7-max", "openai-api") == "@ai-sdk/openai-compatible"
    assert _npm_for("deepseek-v4-pro", "openai-api") == "@ai-sdk/openai-compatible"
