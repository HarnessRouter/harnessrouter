"""The grok backend: Grok Build (xai-org/grok-build, Apache-2.0), the `grok` binary pinned to 1.0.41.

Every fixture line below was captured from the 1.0.41 binary at a local logging stub (no xAI
account, no login, no key) — see the PR body for the probe set. Each test pins one thing that would
otherwise fail SILENTLY in production: a provider failure read as an answer, an answer that talks
about an error read as a failure, the xAI login that `-r <unknown id>` starts, the shell tool whose
wire name disables nothing, the side calls that go to a hard-coded xAI model, the key at rest.

Measured facts the code rests on:
  stream           --output-format streaming-messages-json = Claude Code stream-json: system/init
                   (session_id; `model` is the catalog KEY), assistant, user(tool_result), result
  failures         result subtype error_during_execution, is_error true, NO `result`, reason in
                   errors[]; exit 1 (401, 500 after retries, dead endpoint)
  usage            result.usage excludes side calls (session title) -> the relay's count is the bill
  resume           -s <uuid> creates, -r <id> continues; store sessions/<enc cwd>/<id>/summary.json;
                   -r of an id the store lacks starts an xAI device-code login unless the session
                   registry is off
  tool policy      --disallowed-tools by INTERNAL id: the shell is run_terminal_cmd on the policy side
                   and run_terminal_command on the wire
"""
import json
import pathlib
import sys
import tempfile
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (Auth, BACKENDS, CHECKPOINT_EXCLUDE, _GROK_ALWAYS_WITHHELD,  # noqa: E402
                    _GROK_TOOL_POLICY_IDS, _agent_doc_path, _build_grok, _grok_eof,
                    _grok_has_session, _grok_home, _grok_to_claude, _resume_lost, _write_skills)

SID = "01a0e068-8817-78d3-a3cf-8f2b9d6ba285"

# Captured from 1.0.41 (trimmed: tools lists shortened, uuids kept as they came).
INIT = {"type": "system", "subtype": "init", "session_id": SID, "apiKeySource": "user", "model": "harness",
        "cwd": "/data/workspaces/s1", "permissionMode": "bypassPermissions",
        "tools": ["run_terminal_command", "read_file"], "mcp_servers": [], "skills": [], "uuid": "u0"}
TEXT = {"type": "assistant", "message": {"id": "msg_0", "type": "message", "role": "assistant", "model": "harness",
        "content": [{"type": "text", "text": "PROBE-OK"}], "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 60, "output_tokens": 5, "cache_read_input_tokens": 40,
                  "cache_creation_input_tokens": 0}}, "parent_tool_use_id": None, "session_id": SID, "uuid": "u1"}
TOOL_USE = {"type": "assistant", "message": {"id": "msg_0", "type": "message", "role": "assistant", "model": "harness",
            "content": [{"type": "tool_use", "id": "call_1", "name": "run_terminal_command",
                         "input": {"command": "echo TOOLRAN > t.txt && cat t.txt", "description": "probe"}}],
            "stop_reason": "tool_use"}, "parent_tool_use_id": None, "session_id": SID, "uuid": "u2"}
BASH_ENVELOPE = json.dumps({"type": "Bash", "output": [84, 79, 79, 76, 82, 65, 78, 10],
                            "output_for_prompt": "exit: 0\nTOOLRAN\n", "exit_code": 0,
                            "command": "echo TOOLRAN > t.txt && cat t.txt", "truncated": False,
                            "signal": None, "timed_out": False, "description": "probe"})
TOOL_RESULT = {"type": "user", "message": {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "call_1", "content": BASH_ENVELOPE, "is_error": False}]},
    "parent_tool_use_id": None, "session_id": SID, "uuid": "u3"}
REFUSED_CALL = {"type": "user", "message": {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "call_1", "is_error": True, "content": json.dumps(
        [{"type": "content", "content": {"type": "text",
                                         "text": "Failed to parse arguments for tool `run_terminal_command`: missing field `description`"}}])}]},
    "session_id": SID, "uuid": "u4"}
OK = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 124, "duration_api_ms": 6,
      "num_turns": 1, "result": "PROBE-OK", "stop_reason": "end_turn", "total_cost_usd": 0.0,
      "usage": {"input_tokens": 60, "output_tokens": 5, "cache_read_input_tokens": 40,
                "cache_creation_input_tokens": 0, "server_tool_use": {"web_search_requests": 0}},
      "modelUsage": {"stub-served": {"inputTokens": 60, "outputTokens": 5}}, "session_id": SID, "uuid": "u5"}
FAIL_401 = {"type": "result", "subtype": "error_during_execution", "is_error": True, "duration_ms": 216,
            "duration_api_ms": 0, "num_turns": 0, "stop_reason": None, "total_cost_usd": 0.0,
            "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}, "modelUsage": {},
            "errors": ["Internal error: \"Unauthorized (401) from http://127.0.0.1:18777/v1/chat/completions: "
                       "invalid_request_error: Incorrect API key provided: sk-bad\\n\\n  Model:     stub-model\""],
            "session_id": SID, "uuid": "u6"}


def _argv(d=None, **kw):
    d = d or tempfile.mkdtemp()
    env: dict = {"XAI_API_KEY": "xai-real-should-not-survive"}
    cmd = _build_grok("openai-api", Auth(api_key="sk-real-key-1234", base_url="https://up.example/v1"),
                      "gpt-5.4", "do it", d, env, **kw)
    return cmd, d, env


def _norm(lines, **state):
    st: dict = {"model": "gpt-5.4", **state}
    out = []
    for line in lines:
        out += _grok_to_claude(line, st)
    return out, st


def _store(d, sid=SID):
    """A session as 1.0.41 lays it down: sessions/<url-encoded cwd>/<id>/summary.json …"""
    p = _grok_home(pathlib.Path(d)) / "sessions" / "%2Fdata%2Fworkspaces%2Fs1" / sid
    p.mkdir(parents=True)
    (p / "summary.json").write_text("{}")
    return p


# ── the stream ───────────────────────────────────────────────────────────────────
def test_a_successful_turn_passes_through_with_the_answer_and_leaves_usage_to_the_relay():
    out, _ = _norm([INIT, TEXT, OK])
    assert out[0]["type"] == "system" and out[0]["session_id"] == SID
    # The init's `model` is the runner's catalog key; the event says what was asked for instead.
    assert out[0]["model"] == "gpt-5.4"
    assert out[1]["message"]["content"][0]["text"] == "PROBE-OK"
    res = out[-1]
    assert res["type"] == "result" and res["is_error"] is False and res["result"] == "PROBE-OK"
    # grok's own figure excludes side calls; {} is what makes the run loop stamp the relay's count.
    assert res["usage"] == {} and "modelUsage" not in res and "model" not in res


def test_a_provider_failure_is_a_failed_turn_with_the_providers_sentence():
    out, _ = _norm([INIT, FAIL_401])
    res = out[-1]
    assert res["is_error"] is True
    assert "Unauthorized (401)" in res["result"] and "Incorrect API key" in res["result"]


def test_an_answer_that_merely_talks_about_an_error_is_an_answer():
    """grok never narrates a failure as assistant text, so no prefix is matched in an answer."""
    words = "Error: the build failed because API Error: 401 was returned by the mock. Fixed it."
    text = {**TEXT, "message": {**TEXT["message"], "content": [{"type": "text", "text": words}]}}
    out, _ = _norm([INIT, text, {**OK, "result": words}])
    assert out[-1]["is_error"] is False and out[-1]["result"] == words
    assert any(e.get("type") == "assistant" for e in out)


def test_a_failure_with_no_errors_still_says_how_it_ended():
    out, _ = _norm([{**FAIL_401, "errors": [], "subtype": "error_max_turns"}])
    assert out[-1]["is_error"] is True and "error_max_turns" in out[-1]["result"]


def test_the_shell_card_shows_what_the_command_printed_not_the_envelope():
    out, _ = _norm([TOOL_USE, TOOL_RESULT])
    assert out[0]["message"]["content"][0]["name"] == "run_terminal_command"
    assert out[1]["message"]["content"][0]["content"] == "exit: 0\nTOOLRAN\n"


def test_a_refused_call_shows_the_text_the_model_was_given():
    out, _ = _norm([REFUSED_CALL])
    c = out[0]["message"]["content"][0]
    assert c["is_error"] is True and c["content"].startswith("Failed to parse arguments")


def test_eof_without_a_result_is_a_failure_whose_reason_the_stderr_tail_fills():
    assert _grok_eof({}, 1) == [{"type": "result", "subtype": "error", "is_error": True, "result": "", "usage": {}}]
    assert _grok_eof({"final": "x"}, 0)[0]["is_error"] is False


# ── the builder ──────────────────────────────────────────────────────────────────
def test_the_key_rides_the_environment_as_the_relays_placeholder_and_is_never_at_rest():
    cmd, d, env = _argv()
    tok = env["HR_GROK_API_KEY"]
    assert tok.startswith("hr-relay-")           # _relay_served_model/_relay_usage find the route by it
    assert "sk-real-key-1234" not in json.dumps(cmd) and "sk-real-key-1234" not in json.dumps(env)
    assert "XAI_API_KEY" not in env              # never the fallback grok reads for xAI models
    cfg = (_grok_home(pathlib.Path(d)) / "config.toml").read_text()
    assert "sk-real-key-1234" not in cfg and tok not in cfg
    doc = tomllib.loads(cfg)
    m = doc["model"]["harness"]
    assert m["model"] == "gpt-5.4" and m["env_key"] == "HR_GROK_API_KEY"
    assert m["base_url"].startswith("http://127.0.0.1:") and m["api_backend"] == "chat_completions"
    assert env["GROK_HOME"] == str(_grok_home(pathlib.Path(d)))


def test_the_config_shuts_the_side_calls_the_phone_home_and_the_login_doors():
    _, d, env = _argv()
    doc = tomllib.loads((_grok_home(pathlib.Path(d)) / "config.toml").read_text())
    f = doc["features"]
    assert f["telemetry"] is False and f["remote_fetch"] is False and f["managed_config"] is False
    assert f["turn_summary"] is False and f["title_refresh"] is False and f["session_recap"] is False
    # the title call would otherwise go to a hard-coded grok-4.6 at this endpoint
    assert doc["models"]["session_summary"] == "harness" and doc["models"]["default"] == "harness"
    assert doc["models"]["max_retries"] == 2
    assert doc["cli"]["session_registry"] is False and doc["cli"]["use_leader"] is False
    assert doc["cli"]["auto_update"] is False
    assert all(v is False for v in doc["compat"]["claude"].values())
    assert all(v is False for v in doc["compat"]["cursor"].values())
    for k, v in (("GROK_SESSION_REGISTRY", "0"), ("GROK_TURN_TRANSIENT_RETRY", "0"),
                 ("GROK_DISABLE_AUTOUPDATER", "1"), ("GROK_FOLDER_TRUST", "0")):
        assert env[k] == v


def test_the_argv_is_headless_claude_stream_json_and_a_dash_prompt_stays_the_prompt():
    d = tempfile.mkdtemp()
    cmd = _build_grok("openai-api", Auth(api_key="k", base_url="https://up.example/v1"), "m",
                      "-rf is not a flag here", d, {})
    assert cmd[0] == "grok" and "--single=-rf is not a flag here" in cmd
    i = cmd.index("--output-format")
    assert cmd[i + 1] == "streaming-messages-json" and "--always-approve" in cmd
    assert cmd[cmd.index("-m") + 1] == "harness"


def test_a_session_the_store_holds_is_resumed_and_one_it_does_not_hold_is_never_passed():
    d = tempfile.mkdtemp()
    cmd, _, _ = _argv(d, resume_session_id=SID)
    assert "-r" not in cmd and "-s" in cmd and SID not in cmd   # -r here would start an xAI login
    assert _resume_lost("grok", cmd, SID, d) == SID
    _store(d)
    cmd, _, _ = _argv(d, resume_session_id=SID)
    assert cmd[cmd.index("-r") + 1] == SID and "-s" not in cmd
    assert _resume_lost("grok", cmd, SID, d) is None


def test_the_store_lookup_asks_for_summary_json_and_refuses_what_is_not_a_uuid():
    d = tempfile.mkdtemp()
    p = _grok_home(pathlib.Path(d)) / "sessions" / "x" / SID
    p.mkdir(parents=True)                         # a directory without summary.json is not a session
    assert not _grok_has_session(_grok_home(pathlib.Path(d)), SID)
    (p / "summary.json").write_text("{}")
    assert _grok_has_session(_grok_home(pathlib.Path(d)), SID)
    assert not _grok_has_session(_grok_home(pathlib.Path(d)), "../" + SID)
    assert not _grok_has_session(_grok_home(pathlib.Path(d)), "*")


def test_a_new_conversation_gets_a_fresh_uuid_every_time():
    a, _, _ = _argv()
    b, _, _ = _argv()
    assert a[a.index("-s") + 1] != b[b.index("-s") + 1]


def test_disabled_tools_map_to_the_clis_internal_ids_and_the_media_tools_are_always_withheld():
    cmd, _, _ = _argv(tools_disabled=["run_terminal_command", "spawn_subagent", "NotAGrokTool"])
    withheld = cmd[cmd.index("--disallowed-tools") + 1].split(",")
    assert "run_terminal_cmd" in withheld and "run_terminal_command" not in withheld
    assert "Agent" in withheld and "NotAGrokTool" not in withheld
    for t in _GROK_ALWAYS_WITHHELD:
        assert t in withheld
    assert "read_file" not in _GROK_TOOL_POLICY_IDS   # cannot be withheld alone (session refuses to start)


def test_budget_and_partial_flags():
    cmd, _, _ = _argv(max_turns=7, partial=True)
    assert cmd[cmd.index("--max-turns") + 1] == "7" and "--include-partial-messages" in cmd
    cmd, _, _ = _argv()
    assert "--max-turns" not in cmd and "--include-partial-messages" not in cmd


def test_mcp_servers_carry_their_transport_and_auth_and_a_removed_one_is_gone():
    servers = [{"name": "probe", "command": ["python3", "probe.py"], "args": ["--x"], "env": {"A": "1"}},
               {"name": "remote sse", "url": "https://mcp.example/sse", "transport": "sse", "auth": "tok"},
               {"name": "http", "url": "https://mcp.example/mcp", "headers": {"X-K": 'v"q'}}]
    _, d, _ = _argv(mcp_servers=servers)
    doc = tomllib.loads((_grok_home(pathlib.Path(d)) / "config.toml").read_text())
    ms = doc["mcp_servers"]
    assert ms["probe"] == {"command": "python3", "args": ["probe.py", "--x"], "env": {"A": "1"}}
    assert ms["remote_sse"]["type"] == "sse" and ms["remote_sse"]["headers"]["Authorization"] == "Bearer tok"
    assert "type" not in ms["http"] and ms["http"]["headers"]["X-K"] == 'v"q'
    _build_grok("openai-api", Auth(api_key="k", base_url="https://up.example/v1"), "m", "p", d, {})
    assert "mcp_servers" not in tomllib.loads((_grok_home(pathlib.Path(d)) / "config.toml").read_text())


def test_the_builder_refuses_without_a_key_or_an_endpoint():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _build_grok("openai-api", Auth(api_key="", base_url="https://up.example/v1"), "m", "p", tempfile.mkdtemp(), {})
    with pytest.raises(HTTPException):
        _build_grok("openai-api", Auth(api_key="k", base_url=""), "m", "p", tempfile.mkdtemp(), {})


# ── registration ─────────────────────────────────────────────────────────────────
def test_registry_agent_doc_skills_and_checkpoint():
    assert BACKENDS["grok"]["normalize"] is _grok_to_claude
    assert BACKENDS["grok"]["default_model"] == "grok-4.6"
    assert _agent_doc_path("/w", "grok").name == "AGENTS.md"
    d = tempfile.mkdtemp()
    got = _write_skills(d, [{"name": "probe-skill", "content": "---\nname: probe-skill\ndescription: x\n---\n"}], "grok")
    assert got and (_grok_home(pathlib.Path(d)) / "skills" / "probe-skill" / "SKILL.md").is_file()
    for p in ("./.harness/home/.grok/config.toml", "./.harness/home/.grok/auth.json",
              # the MCP OAuth token store: the runner starts no such flow (measured — a 401 server
              # does not escalate in a headless session), but a token at rest must not travel
              "./.harness/home/.grok/mcp_credentials.json",
              "./.harness/home/.grok/logs"):
        assert p in CHECKPOINT_EXCLUDE
    assert not any(p.startswith("./.harness/home/.grok/sessions") for p in CHECKPOINT_EXCLUDE)


# ── the relay repairs grok's tool declarations need on a gemini model ───────────
def test_a_gemini_model_on_a_grok_route_gets_the_normalised_declarations():
    """Captured grok 1.0.41 declarations; through Vercel a gemini model refused both shapes."""
    from server import _HERMES_RELAY, _gemini_schema
    timeout = {"description": "Optional timeout", "type": ["integer", "null"], "format": "uint64",
               "minimum": 0, "default": 120000, "maximum": 36000000}
    status = {"type": ["string", "null"], "enum": ["pending", "in_progress", "completed", "cancelled", None]}
    t = _gemini_schema(timeout)
    assert t["type"] == "integer" and t["nullable"] is True and "anyOf" not in t
    s = _gemini_schema(status)
    assert s["enum"] == ["pending", "in_progress", "completed", "cancelled"] and s["nullable"] is True
    _, _, env = _argv()
    route = _HERMES_RELAY["routes"][env["HR_GROK_API_KEY"]]
    assert route[2]["gemini_schemas"] is True


def test_cancel_kills_the_commands_grok_runs_in_their_own_session():
    """grok runs each shell command under its own session (measured on Linux, 1.0.41): the group
    kill alone left `sleep` running after a cancel. The descendants are killed first."""
    import os
    import subprocess
    import time
    import pytest
    from server import _descendant_pids, _kill_proc_tree
    if not os.path.isdir("/proc") or not os.path.exists("/usr/bin/setsid"):
        pytest.skip("needs /proc and setsid (Linux)")
    proc = subprocess.Popen(["sh", "-c", "setsid sleep 97 & wait"], start_new_session=True)
    time.sleep(0.5)
    kids = _descendant_pids(proc.pid)
    assert kids
    _kill_proc_tree(proc)
    proc.wait()
    time.sleep(0.3)
    for pid in kids:
        assert not os.path.exists(f"/proc/{pid}") or "Z" in open(f"/proc/{pid}/stat").read().split(")")[1][:3]


# ── Anthropic's input_schema: no combinator at the root ──────────────────────────
# Grok Build's `use_tool` declares a root `oneOf` over its three call forms, and Anthropic refuses
# it: `tools.14.custom.input_schema: input_schema does not support oneOf, allOf, or anyOf at the top
# level` (measured 2026-09-28 on claude-haiku-4.5 and claude-sonnet-4.6 through Vercel, where every
# claude id failed its first turn). These tests CONSTRUCT that schema rather than pin a version.
USE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {"description": "Discovered MCP target name", "type": "string"},
        "tool_input": {"description": "Inline remote arguments", "type": "object",
                       "additionalProperties": True},
        "tool_input_file": {"description": "UTF-8 JSON file", "type": "string", "minLength": 1},
        "file": {"description": "UTF-8 JSON document", "type": "string", "minLength": 1},
    },
    "oneOf": [
        {"type": "object", "properties": {"tool_name": {"type": "string"}, "tool_input": {"type": "object"}},
         "required": ["tool_name", "tool_input"],
         "not": {"anyOf": [{"required": ["tool_input_file"]}, {"required": ["file"]}]}},
        {"type": "object", "properties": {"tool_name": {"type": "string"}, "tool_input_file": {"type": "string"}},
         "required": ["tool_name", "tool_input_file"],
         "not": {"anyOf": [{"required": ["tool_input"]}, {"required": ["file"]}]}},
        {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"],
         "not": {"anyOf": [{"required": ["tool_name"]}, {"required": ["tool_input"]}]}},
    ],
}


def _has_root_combinator(schema: dict) -> bool:
    return any(k in schema for k in ("oneOf", "anyOf", "allOf"))


def test_the_root_combinator_is_flattened_and_the_call_the_model_makes_stays_declared():
    from server import _anthropic_tool_schema
    assert _has_root_combinator(USE_TOOL_SCHEMA)          # the defect, constructed
    flat = _anthropic_tool_schema(USE_TOOL_SCHEMA)
    assert not _has_root_combinator(flat) and "not" not in flat
    assert flat["type"] == "object"
    # every property a caller may send is still declared, with the root's own description kept
    assert set(flat["properties"]) == {"tool_name", "tool_input", "tool_input_file", "file"}
    assert flat["properties"]["tool_name"]["description"] == "Discovered MCP target name"
    # `required` is what EVERY branch requires — here nothing, because two forms take no tool_name.
    # Demanding one branch's key would refuse the other two forms outright.
    assert "required" not in flat
    assert _has_root_combinator(USE_TOOL_SCHEMA)          # the caller's schema is not mutated


def test_a_required_key_every_branch_shares_survives_the_flattening():
    from server import _anthropic_tool_schema
    schema = {"type": "object", "properties": {"id": {"type": "string"}},
              "anyOf": [{"required": ["id", "a"]}, {"required": ["id", "b"]}]}
    assert _anthropic_tool_schema(schema)["required"] == ["id"]


def test_a_nested_combinator_is_left_alone_because_anthropic_accepts_it():
    from server import _anthropic_tool_schema
    schema = {"type": "object", "properties": {"n": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}}
    assert _anthropic_tool_schema(schema) == schema


def test_both_wire_shapes_are_repaired_and_an_untouched_body_is_byte_identical():
    import json as _json
    from server import _with_anthropic_schemas
    openai = _json.dumps({"model": "anthropic/claude-haiku-4.5", "messages": [],
                          "tools": [{"type": "function", "function": {"name": "use_tool",
                                                                     "parameters": USE_TOOL_SCHEMA}}]}).encode()
    got = _json.loads(_with_anthropic_schemas(openai))
    assert not _has_root_combinator(got["tools"][0]["function"]["parameters"])
    native = _json.dumps({"model": "claude-haiku-4.5", "messages": [],
                          "tools": [{"name": "use_tool", "input_schema": USE_TOOL_SCHEMA}]}).encode()
    got = _json.loads(_with_anthropic_schemas(native))
    assert not _has_root_combinator(got["tools"][0]["input_schema"])
    clean = _json.dumps({"model": "claude-haiku-4.5", "messages": [],
                         "tools": [{"name": "grep", "input_schema": {"type": "object",
                                                                    "properties": {"q": {"type": "string"}}}}]}).encode()
    assert _with_anthropic_schemas(clean) == clean
    assert _with_anthropic_schemas(b'{"messages": []}') == b'{"messages": []}'


def test_the_family_test_reads_the_vendor_prefixed_id_and_the_bare_one():
    from server import _anthropic_family
    for m in ("claude-haiku-4.5", "anthropic/claude-sonnet-4.6", "CLAUDE-OPUS-5"):
        assert _anthropic_family(m)
    for m in ("", "gemini-3.5-flash", "spacexai/grok-4.6", "gpt-5.4"):
        assert not _anthropic_family(m)


def test_the_repair_is_idempotent_so_the_relays_retry_terminates():
    """The relay repairs on the provider's complaint and sends again; if the second body still
    carried the combinator the loop would burn all three attempts and fail anyway. MEASURED against
    a stub that refuses the shape exactly as Anthropic does: call 1 the session title (1 tool, no
    combinator), call 2 the answer (20 tools, root combinator at index 14) refused, call 3 the same
    request repaired and answered — one extra request, not a ladder."""
    import json as _json
    from server import _with_anthropic_schemas
    body = _json.dumps({"model": "vendor/opus-x", "messages": [],
                        "tools": [{"type": "function", "function": {"name": "use_tool",
                                                                   "parameters": USE_TOOL_SCHEMA}}]}).encode()
    once = _with_anthropic_schemas(body)
    assert once != body
    assert _with_anthropic_schemas(once) == once


def test_withholding_the_shell_withholds_every_other_command_surface():
    """A/B-measured on 2026-09-28 (real model, real turn): with only run_terminal_command withheld the
    agent ran the same command through `monitor` and read it back through
    get_command_or_subagent_output, and the file it wrote was there — so the tool list alone did not
    earn `tool_enforcement: "hard"`. With monitor and the CLI's `Agent` entry withheld too (the
    subagent family and the scheduler), the agent answered that it had no shell and nothing ran."""
    from server import _GROK_TOOL_IMPLIES
    cmd, _, _ = _argv(tools_disabled=["run_terminal_command"])
    withheld = cmd[cmd.index("--disallowed-tools") + 1].split(",")
    assert "run_terminal_cmd" in withheld and "monitor" in withheld and "Agent" in withheld
    assert _GROK_TOOL_IMPLIES["run_terminal_command"] == ("monitor", "Agent")
    # withholding something else does not drag the command surfaces with it
    cmd, _, _ = _argv(tools_disabled=["grep"])
    withheld = cmd[cmd.index("--disallowed-tools") + 1].split(",")
    assert "grep" in withheld and "monitor" not in withheld and "Agent" not in withheld


def test_the_config_stays_valid_toml_with_characters_outside_the_bmp():
    """json.dumps with ensure_ascii writes an emoji as a surrogate pair of \\u escapes, which TOML
    refuses; one such character in an MCP argument left the whole config unparseable."""
    import tomllib
    from server import _toml_str
    for text in ("plain", "x\U0001F600y", 'quote " and \\ slash', "tab\there", "del\x7f", "中文"):
        assert tomllib.loads("v = " + _toml_str(text))["v"] == text


def test_a_null_token_count_in_usage_reaches_grok_as_zero():
    """kimi-k3 through TokenRouter ends its stream with `"audio_tokens":null`; grok parses counts as
    u32 and failed every turn on it after the answer had arrived. Only counts inside usage change."""
    from server import _usage_without_nulls
    line = (b'data: {"id":"c","choices":[],"service_tier":null,"usage":{"prompt_tokens":93,'
            b'"completion_tokens":98,"prompt_tokens_details":{"audio_tokens":null,"cached_tokens":0}}}')
    out = _usage_without_nulls(line)
    assert b'"audio_tokens":0' in out and b'"service_tier":null' in out and out.count(b"null") == 1
    for same in (b'data: {"choices":[{"delta":{"content":"null"},"finish_reason":null}],"usage":null}',
                 b'data: [DONE]', b''):
        assert _usage_without_nulls(same) == same


def test_the_relay_rewrites_the_count_in_a_live_stream_and_passes_the_rest_through():
    import http.client, http.server, threading
    import server as rs
    events = (b'data: {"choices":[{"index":0,"delta":{"content":"OK"},"finish_reason":null}],"usage":null}\n\n'
              b'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":1,'
              b'"prompt_tokens_details":{"audio_tokens":null,"cached_tokens":0}}}\n\n'
              b'data: [DONE]\n\n')

    class Up(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            self.send_response(200); self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(events))); self.end_headers()
            self.wfile.write(events)

        def log_message(self, *a):
            pass

    up = http.server.HTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base, tok = rs._hermes_relay_route(f"http://127.0.0.1:{up.server_port}/v1", "sk-real", usage_no_nulls=True)
    conn = http.client.HTTPConnection(base.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        conn.request("POST", "/v1/chat/completions",
                     body=json.dumps({"model": "moonshotai/kimi-k3", "messages": [], "stream": True}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        got = conn.getresponse().read()
    finally:
        conn.close(); up.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)
    assert got == events.replace(b'"audio_tokens":null', b'"audio_tokens":0')
