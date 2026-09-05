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


def test_mcp_is_a_flat_name_to_server_map_not_nested_under_servers():
    """The RELEASED schema (opencode.ai/config.json) is `mcp.<name>`. The repo source tree is ahead
    of the release and nests under `mcp.servers`; writing that shape makes the shipped binary
    refuse the whole config."""
    d = tempfile.mkdtemp()
    _opencode_config(Auth(api_key="k", base_url="https://relay.example/v1"), "gpt-5.4", d,
                     [{"name": "docs", "url": "https://mcp.example/sse"}], None, None, "openai-api")
    cfg = _json.loads(open(f"{d}/.harness/opencode.json").read())
    assert "servers" not in cfg["mcp"]
    assert cfg["mcp"]["docs"]["type"] == "remote"


def test_skills_is_an_object_with_paths_not_a_bare_array():
    """The released binary rejects a bare array: "Expected object | undefined, got [...] skills".
    This is the shape that actually failed a live turn."""
    d = tempfile.mkdtemp()
    _opencode_config(Auth(api_key="k", base_url="https://relay.example/v1"), "gpt-5.4", d, None,
                     "/ws/.harness/skills", None, "openai-api")
    cfg = _json.loads(open(f"{d}/.harness/opencode.json").read())
    assert cfg["skills"] == {"paths": ["/ws/.harness/skills"]}


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


def test_resume_passes_the_session_id_when_that_session_is_here():
    """The conversation is in this workspace's database, so resume it."""
    d = tempfile.mkdtemp()
    env: dict = {"HOME": d}
    db = pathlib.Path(d) / ".local" / "share" / "opencode"
    db.mkdir(parents=True, exist_ok=True)
    (db / "opencode.db").write_bytes(b"sqlite-ish bytes ses_abc more bytes")
    auth = Auth(api_key="sk-test", base_url="https://relay.example/v1")
    cmd = _build_opencode("openai-api", auth, "gpt-5.4", "do it", d, env, resume_session_id="ses_abc")
    assert "--session" in cmd and "ses_abc" in cmd


def test_resume_is_dropped_when_the_session_is_not_in_this_workspace():
    """opencode exits 1 with no output when told to resume a session its database does not hold,
    and every later turn passes the same dead id, so the conversation stays broken rather than
    failing once. Start a fresh CLI thread in the same workspace instead."""
    d = tempfile.mkdtemp()
    env: dict = {"HOME": d}          # no database at all: a recycled sandbox
    auth = Auth(api_key="sk-test", base_url="https://relay.example/v1")
    cmd = _build_opencode("openai-api", auth, "gpt-5.4", "do it", d, env, resume_session_id="ses_gone")
    assert "--session" not in cmd and "ses_gone" not in cmd
    assert cmd[-1] == "do it"        # the turn still runs


def test_resume_finds_a_session_still_sitting_in_the_write_ahead_log():
    """The previous turn's write may not have been checkpointed into the main database yet."""
    d = tempfile.mkdtemp()
    env: dict = {"HOME": d}
    db = pathlib.Path(d) / ".local" / "share" / "opencode"
    db.mkdir(parents=True, exist_ok=True)
    (db / "opencode.db").write_bytes(b"header only")
    (db / "opencode.db-wal").write_bytes(b"wal frame ses_wal payload")
    auth = Auth(api_key="sk-test", base_url="https://relay.example/v1")
    cmd = _build_opencode("openai-api", auth, "gpt-5.4", "do it", d, env, resume_session_id="ses_wal")
    assert "--session" in cmd and "ses_wal" in cmd


def test_key_goes_to_the_environment_and_never_into_the_config_file():
    cmd, d, env = _argv()
    assert env["HR_OPENCODE_KEY"] == "sk-test"
    cfg = _json.loads(open(f"{d}/.harness/opencode.json").read())
    assert cfg["provider"]["hr"]["options"]["apiKey"] == "{env:HR_OPENCODE_KEY}"
    assert "sk-test" not in open(f"{d}/.harness/opencode.json").read()
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
    return _json.loads(open(f"{d}/.harness/opencode.json").read())["provider"]["hr"]["npm"]


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


def test_error_message_is_read_from_the_real_nested_shape():
    """Captured from a live 401 against the relay: the message is under error.data.message, not
    error.message. Reading the flat key gave the user a stringified dict."""
    _, state = _run([_ev("error", error={"name": "APIError",
                                         "data": {"message": "Authentication failed.", "statusCode": 401}})])
    assert state["_oc_error"] == "Authentication failed."


def test_error_falls_back_to_the_flat_message_then_the_name():
    _, s1 = _run([_ev("error", error={"message": "flat form"})])
    assert s1["_oc_error"] == "flat form"
    _, s2 = _run([_ev("error", error={"name": "APIError"})])
    assert s2["_oc_error"] == "APIError"


# ── end of stream: opencode has no terminal event, the process exiting is the signal ──
from server import _opencode_eof, _opencode_to_claude  # noqa: E402


def test_the_run_loop_can_find_the_eof_hook():
    """_run_turn_bg looks for `normalize.eof`. If this attribute goes missing the turn silently
    loses its result event again."""
    assert getattr(_opencode_to_claude, "eof", None) is _opencode_eof


def test_clean_exit_reports_success_with_the_final_text_and_usage():
    state = {"final": "the answer", "_oc_usage": {"input_tokens": 5}}
    ev = _opencode_eof(state, 0)[0]
    assert ev["subtype"] == "success" and ev["is_error"] is False
    assert ev["result"] == "the answer" and ev["usage"] == {"input_tokens": 5}


def test_an_error_event_wins_over_the_exit_code():
    ev = _opencode_eof({"final": "", "_oc_error": "Authentication failed."}, 0)[0]
    assert ev["is_error"] is True and ev["result"] == "Authentication failed."


def test_a_bare_nonzero_exit_says_so_instead_of_going_blank():
    """This is the live failure: exit 1, no error event, nothing on stderr. The trace showed
    'exit_code=1, no diagnostic output', which tells the user nothing."""
    ev = _opencode_eof({"final": ""}, 1)[0]
    assert ev["is_error"] is True
    assert "exited 1" in ev["result"]


def test_a_failing_tool_is_quoted_when_the_process_dies_without_an_error_event():
    ev = _opencode_eof({"final": "", "_oc_tool_errors": ["bash: boom"]}, 1)[0]
    assert "bash: boom" in ev["result"]


def test_config_lives_under_harness_not_the_workspace_root():
    """Produced files are `git status` of the workspace. A root-level opencode.json was collected
    as a deliverable on every turn, handing the user internal config (relay URL, key env name,
    data-volume paths). .harness/ is excluded from collection; OPENCODE_CONFIG points the binary
    at it (verified on 1.18.23)."""
    import os
    d = tempfile.mkdtemp()
    env: dict = {}
    _build_opencode("openai-api", Auth(api_key="k", base_url="https://relay.example/v1"),
                    "gpt-5.4", "hi", d, env)
    assert not os.path.exists(f"{d}/opencode.json")
    assert os.path.exists(f"{d}/.harness/opencode.json")
    assert env["OPENCODE_CONFIG"] == f"{d}/.harness/opencode.json"


def test_a_finished_tool_keeps_its_own_clock_and_carries_its_result():
    """opencode reports a tool once it is done. Its state.time (ms) stamps the call at the start
    and the result at the end, so the seconds in between meter as agent work; the output rides
    on the result so the trace shows it."""
    out, _ = _run([_ev("tool_use", part={"type": "tool", "id": "prt_9", "tool": "bash",
                                         "state": {"status": "completed", "input": {"command": "sleep 25"},
                                                   "output": "done\n", "time": {"start": 1788600000000, "end": 1788600025300}}})])
    call = [e for e in out if e.get("type") == "assistant"][0]
    res = [e for e in out if e.get("type") == "user"][0]
    assert call["_ts"] == 1788600000.0 and res["_ts"] == 1788600025.3
    r = res["message"]["content"][0]
    assert r["type"] == "tool_result" and r["tool_use_id"] == "prt_9" and r["content"] == "done\n" and r["is_error"] is False


def test_a_failed_tool_carries_its_error_as_the_result():
    out, _ = _run([_ev("tool_use", part={"type": "tool", "id": "p2", "tool": "bash",
                                         "state": {"status": "error", "error": "boom", "time": {"start": 1000000, "end": 1002000}}})])
    res = [e for e in out if e.get("type") == "user"][0]["message"]["content"][0]
    assert res["is_error"] is True and res["content"] == "boom" and res["tool_use_id"] == "p2"


def test_a_tool_without_a_clock_is_stamped_on_arrival():
    out, _ = _run([_ev("tool_use", part={"type": "tool", "id": "p3", "tool": "bash", "state": {"status": "completed", "input": {}}})])
    assert all("_ts" not in e for e in out), "no clock of its own: the runner stamps it when it lands"
