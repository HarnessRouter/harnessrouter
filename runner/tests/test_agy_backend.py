"""The Antigravity CLI (agy) as an opt-in base, driven over its ACP server (runner/agy_driver.py).

What each test holds was read off agy 1.5.8 on a Google AI Studio key, through a loopback relay that
held the key while the CLI held a placeholder (2026-11-13; the shapes are in fixtures/agy):
  * GEMINI_API_KEY with `modelProvider: "gemini"` runs the CLI on the Gemini API, GOOGLE_GEMINI_BASE_URL is
    honoured for every model call, and the key travels in x-goog-api-key, so the relay carries it.
  * `agy acp --disable-telemetry` sends no usage data; the print mode has no way to stop it.
  * The session's model id carries the thinking level; the prompt's usage counts thinking in the output.
  * Only a shell command asks the client; answering no withholds it.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import agy_driver as D  # noqa: E402
import server as rs  # noqa: E402
from server import Auth, HTTPException  # noqa: E402

FAKE = pathlib.Path(__file__).resolve().parent / "fixtures" / "agy" / "fake_agy_acp.py"
KEY = "AIzaSy-canary-not-a-key-0123456789abcd"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def _build(cwd=None, model="gemini-3.8-flash", effort="", **kw):
    cwd = cwd or tempfile.mkdtemp(prefix="agy-build-")
    env: dict = {"GOOGLE_API_KEY": "should-go", "PATH": "/usr/bin:/bin"}
    token = rs._TURN_THINKING.set({"asked": effort, "applied": "", "routes": [], "route": ""})
    try:
        cmd = rs._build_agy(kw.pop("provider", "google"),
                            kw.pop("auth", Auth(api_key=KEY, base_url="https://generativelanguage.googleapis.com/v1beta/openai")),
                            model, "hi", cwd, env, **kw)
        thinking = rs._TURN_THINKING.get()
    finally:
        rs._TURN_THINKING.reset(token)
    job = json.loads(env["HR_DRIVER_JOB"])
    return cmd, env, job, pathlib.Path(cwd), thinking


# ── the build ─────────────────────────────────────────────────────────────────────────────────
def test_the_turn_is_the_acp_server_with_telemetry_off_and_no_blanket_approval():
    cmd, env, job, _, _ = _build()
    assert cmd[1].endswith("agy_driver.py") and len(cmd) == 2           # the job rides the env, not argv
    assert job["argv"] == [rs.AGY_BIN, "acp", "--disable-telemetry"]
    assert "--dangerously-skip-permissions" not in job["argv"]
    assert env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"                 # "1" is not read by the CLI


def test_every_launch_switches_off_usage_reporting_updates_and_crash_reporting():
    _, env, job, _, _ = _build()
    assert job["argv"][1:] == ["acp", "--disable-telemetry"]           # usage reporting
    assert env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"                 # updates
    assert env["ANTIGRAVITY_SENTRY_SAMPLE_RATE"] == "0"                 # crash reporting


def test_the_cli_process_itself_is_started_with_all_three(tmp_path):
    """The built turn, run through the driver against the fake agy, which records its own environment and argv."""
    _, env, job, _, _ = _build(cwd=str(tmp_path))
    log = tmp_path / "asked.ndjson"
    job = {**job, "argv": [sys.executable, str(FAKE), *job["argv"][1:]]}
    run_env = {**env, "FAKE_AGY_MODE": "silent", "FAKE_AGY_LOG": str(log), "HR_DRIVER_JOB": json.dumps(job)}
    subprocess.run([sys.executable, str(pathlib.Path(D.__file__))], cwd=str(tmp_path), text=True,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=60, env=run_env)
    agent_env = json.loads(pathlib.Path(str(log) + ".env").read_text())
    assert agent_env["ANTIGRAVITY_SENTRY_SAMPLE_RATE"] == "0"
    assert agent_env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
    assert json.loads(pathlib.Path(str(log) + ".argv").read_text())[1:] == ["acp", "--disable-telemetry"]


def test_the_key_stays_in_the_relay_and_the_cli_gets_a_placeholder_and_the_relay():
    cmd, env, job, cwd, _ = _build()
    assert env["GEMINI_API_KEY"].startswith("hr-relay-") and env["GEMINI_API_KEY"] != KEY
    assert env["GOOGLE_GEMINI_BASE_URL"].startswith("http://127.0.0.1:")
    assert "GOOGLE_API_KEY" not in env                                  # it would win over GEMINI_API_KEY
    base, key, flags = rs._HERMES_RELAY["routes"][env["GEMINI_API_KEY"]]
    assert (base, key) == ("https://generativelanguage.googleapis.com", KEY)
    assert flags["google_native"] and flags["google_own"]
    # nowhere the agent can read: its environment, its command lines, the job, any file under the workspace
    seen = json.dumps(env) + json.dumps(cmd) + json.dumps(job)
    seen += "".join(f.read_text(errors="replace") for f in cwd.rglob("*") if f.is_file())
    assert KEY not in seen


def test_the_turns_level_is_the_clis_own_and_never_written_by_the_relay():
    _, env, job, _, thinking = _build(model="gemini-3.8-flash", effort="high")
    assert job["agy_model"] == "gemini-3.8-flash-high" and thinking["applied"] == "high"
    flags = rs._HERMES_RELAY["routes"][env["GEMINI_API_KEY"]][2]
    assert "effort" not in flags                                        # the helper model's calls keep their own


def test_settings_name_the_gemini_api_and_hold_no_key():
    _, _, _, cwd, _ = _build()
    s = json.loads((cwd / ".harness/home/.gemini/antigravity-cli/settings.json").read_text())
    assert s == {"modelProvider": "gemini"}


@pytest.mark.parametrize("model,effort,want", [
    ("gemini-3.8-flash", "", "gemini-3.8-flash-medium"),
    ("gemini-3.8-flash", "low", "gemini-3.8-flash-low"),
    ("gemini-3.8-flash", "none", "gemini-3.8-flash-low"),
    ("gemini-3.8-flash", "minimal", "gemini-3.8-flash-low"),
    ("gemini-3.8-flash", "xhigh", "gemini-3.8-flash-high"),
    ("gemini-4-hydrogen", "xhigh", "gemini-4-hydrogen-xhigh"),
    ("gemini-4-hydrogen", "", "gemini-4-hydrogen-medium"),
    ("gemini-3.1-pro-preview", "", "gemini-3.1-pro-low"),        # Google's id in, the CLI's id out
    ("gemini-3.1-pro-preview", "medium", "gemini-3.1-pro-low"),
    ("gemini-3.1-pro-preview", "high", "gemini-3.1-pro-high"),
    ("gemini-3.8-flash-high", "", "gemini-3.8-flash-high"),      # an id that already carries a level
])
def test_a_catalog_model_and_level_become_the_clis_model_id(model, effort, want):
    assert rs._agy_session_model(model, effort)[0] == want


def test_a_model_the_cli_does_not_offer_is_refused_before_anything_starts():
    for bad in ("gemini-9-nope", "gemini-3.8-flash-xhigh", "gpt-5.4", ""):
        with pytest.raises(HTTPException) as e:
            rs._agy_session_model(bad)
        assert e.value.status_code == 400


def test_only_googles_own_endpoint_and_a_key_build_a_turn():
    with pytest.raises(HTTPException):
        _build(auth=Auth(api_key=KEY, base_url="https://api.tokenrouter.com/v1"))
    with pytest.raises(HTTPException):
        _build(auth=Auth(base_url="https://generativelanguage.googleapis.com/v1beta/openai"))
    with pytest.raises(HTTPException):
        _build(provider="openai-api")
    _build(auth=Auth(api_key=KEY))                                  # no base: Google's own


# ── MCP ───────────────────────────────────────────────────────────────────────────────────────
def test_mcp_servers_are_written_in_the_clis_schema_every_turn(tmp_path):
    servers = [{"name": "plugs", "url": "http://127.0.0.1:41000/hr-mcp-" + "a" * 32 + "/mcp"},
               {"name": "local tool", "command": ["/usr/bin/python3", "-I", "srv.py"], "args": ["--x"],
                "env": {"TOKEN_FOR_IT": "v"}},
               {"name": "ext", "url": "https://mcp.example/mcp", "headers": {"X-Proj": "p"}}]
    _build(cwd=str(tmp_path), mcp_servers=servers, tools_disabled=["mcp__plugs__delete_all", "Edit"])
    cfg = json.loads((tmp_path / ".harness/home/.gemini/config/mcp_config.json").read_text())["mcpServers"]
    assert cfg["plugs"] == {"serverUrl": servers[0]["url"], "disabledTools": ["delete_all"]}
    assert cfg["local_tool"] == {"command": "/usr/bin/python3", "args": ["-I", "srv.py", "--x"],
                                 "env": {"TOKEN_FOR_IT": "v"}}
    assert cfg["ext"] == {"serverUrl": "https://mcp.example/mcp", "headers": {"X-Proj": "p"}}
    # the next turn without them leaves none behind
    _build(cwd=str(tmp_path))
    assert json.loads((tmp_path / ".harness/home/.gemini/config/mcp_config.json").read_text()) == {"mcpServers": {}}


def test_the_mcp_config_is_never_written_through_a_link(tmp_path):
    target = tmp_path / "outside.json"
    target.write_text("keep")
    d = tmp_path / "ws" / ".harness/home/.gemini/config"
    d.mkdir(parents=True)
    (d / "mcp_config.json").symlink_to(target)
    _build(cwd=str(tmp_path / "ws"))
    assert target.read_text() == "keep" and not (d / "mcp_config.json").is_symlink()


def test_an_sse_server_reaches_the_cli_through_the_stdio_bridge(tmp_path):
    out = rs._sse_bridges(str(tmp_path), [{"name": "old", "url": "http://h.example/sse", "transport": "sse"},
                                          {"name": "new", "url": "http://h.example/mcp"}], "agy")
    assert out[0]["command"].endswith(".harness/mcp-bridge/old.sh") and out[1] == {"name": "new", "url": "http://h.example/mcp"}


def test_the_mcp_config_and_the_clis_credential_store_never_ride_a_checkpoint():
    ex = set(rs.CHECKPOINT_EXCLUDE)
    for p in ("./.harness/home/.gemini/config/mcp_config.json", "./.harness/home/.config/antigravity",
              "./.harness/home/.gemini/antigravity-cli/log", "./.harness/home/.gemini/antigravity-cli/crashes"):
        assert p in ex, p
    # the conversation is what session/load reads: it travels
    assert not [p for p in ex if "antigravity-cli/conversations" in p or p.endswith("antigravity-cli/brain")]


# ── switched-off tools ────────────────────────────────────────────────────────────────────────
def test_a_switched_off_shell_is_answered_no_and_the_rest_are_asked_off():
    _, _, job, _, _ = _build(tools_disabled=["run_command", "write_file"])
    assert job["withheld"] == ["run_command"]
    note = rs._disabled_tools_note("agy", ["run_command", "write_file"])
    assert "write_file" in note and "run_command" in note
    _, _, job, _, _ = _build(tools_disabled=["write_file"])
    assert job["withheld"] == []


def test_the_shells_switch_is_one_the_cli_really_asks_about():
    assert set(rs.AGY_WITHHELD_BY_ANSWER) == {"run_command"} <= set(rs.AGY_TOOLS)


# ── resume ────────────────────────────────────────────────────────────────────────────────────
def test_a_conversation_is_known_by_its_own_database_in_the_clis_store(tmp_path):
    sid = "45233099-b000-438c-90c0-c5896a1c8f6d"
    _, _, job, _, _ = _build(cwd=str(tmp_path), resume_session_id=sid)
    assert job["resume"] == sid and job["resume_known"] is False
    conv = tmp_path / ".harness/home/.gemini/antigravity-cli/conversations"
    conv.mkdir(parents=True)
    (conv / f"{sid}.db").write_bytes(b"x")
    _, _, job, _, _ = _build(cwd=str(tmp_path), resume_session_id=sid)
    assert job["resume_known"] is True
    assert rs._SESSION_PRESENT["agy"](str(tmp_path), None, sid)
    for bad in ("../x", "..", "a/b", ""):
        assert not rs._agy_session_present(str(tmp_path), None, bad)


# ── wiring in the runner ──────────────────────────────────────────────────────────────────────
def test_the_base_is_registered_as_an_acp_driver_with_the_passthrough():
    spec = rs.BACKENDS["agy"]
    assert spec["providers"] == ["google"] and spec["default_model"] == "gemini-3.8-flash"
    assert spec["normalize"] is rs._claude_passthrough
    assert rs._agent_doc_path("/w", "agy") == pathlib.Path("/w/AGENTS.md")
    assert "agy" in rs._GENERIC_STEP_BUDGET and rs._BRIDGED_TRANSPORTS["agy"] == ("sse",)


def test_a_harness_variable_cannot_move_the_cli_off_the_relay():
    got = rs._caller_env({"AGY_LLM_GATEWAY_URL": "https://x.example", "AGY_CLI_DISABLE_AUTO_UPDATE": "false",
                          "ANTIGRAVITY_PROJECT_ID": "p", "MY_OWN": "ok"})
    assert got == {"MY_OWN": "ok"}


# ── the driver, against a fake agy that answers as the real one did ──────────────────────────────
def _drive(tmp_path, mode="ok", withheld=(), resume="", known=False, agy_model="gemini-3.8-flash-medium", extra_env=None):
    log = tmp_path / "asked.ndjson"
    job = {"argv": [sys.executable, str(FAKE), "acp", "--disable-telemetry"], "cwd": str(tmp_path), "prompt": "do it",
           "model": "gemini-3.8-flash", "agy_model": agy_model, "resume": resume, "resume_known": known,
           "withheld": list(withheld), "timeout": 60}
    env = {**os.environ, "FAKE_AGY_MODE": mode, "FAKE_AGY_LOG": str(log), "HR_DRIVER_JOB": json.dumps(job),
           **(extra_env or {})}
    proc = subprocess.run([sys.executable, str(pathlib.Path(D.__file__))], cwd=str(tmp_path), text=True,
                          capture_output=True, stdin=subprocess.DEVNULL, timeout=60, env=env)
    evs = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    asked = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return evs, asked, log


def _blocks(evs, kind):
    return [c for e in evs for c in (e.get("message") or {}).get("content") or [] if c.get("type") == kind]


def test_the_driver_maps_agys_updates_to_the_record(tmp_path):
    evs, asked, _ = _drive(tmp_path)
    calls = _blocks(evs, "tool_use")
    assert [c["name"] for c in calls] == ["write_file", "run_command", "mcp__probe_http__lucky_number"]
    assert calls[1]["input"]["CommandLine"] == "cat a.txt"
    results = _blocks(evs, "tool_result")
    assert "alpha" in results[0]["content"]                            # the write's diff, as text
    assert "alpha" in results[1]["content"] and results[2]["content"] == "4711"
    assert not any(r["is_error"] for r in results)
    res = evs[-1]
    assert res["type"] == "result" and res["subtype"] == "success" and res["result"] == "alpha and 4711"
    assert res["usage"] == {"input_tokens": 13579, "output_tokens": 306, "cache_read_tokens": 13949}
    assert res["model"] == "gemini-3.8-flash" and res["session_id"] == "45233099-b000-438c-90c0-c5896a1c8f6d"
    methods = [a.get("method") for a in asked if a.get("method")]
    assert methods[:4] == ["initialize", "session/new", "session/set_model", "session/prompt"]
    setm = next(a for a in asked if a.get("method") == "session/set_model")
    assert setm["params"]["modelId"] == "gemini-3.8-flash-medium"
    perm = next(a for a in asked if a.get("asked_client") == "session/request_permission")
    assert perm["reply"]["result"]["outcome"]["optionId"] == "allow"


def test_a_withheld_shell_is_answered_no_and_the_turn_says_why_it_stopped(tmp_path):
    evs, asked, _ = _drive(tmp_path, withheld=["run_command"])
    perm = next(a for a in asked if a.get("asked_client") == "session/request_permission")
    assert perm["reply"]["result"]["outcome"]["optionId"] == "deny"
    res = evs[-1]
    assert res["is_error"] and "run_command" in res["result"] and "switched off" in res["result"]
    assert _blocks(evs, "tool_result")[1]["is_error"] is True


def test_thinking_is_in_the_output_and_counted_as_its_reasoning(tmp_path):
    evs, _, _ = _drive(tmp_path, mode="thinking")
    assert evs[-1]["usage"] == {"input_tokens": 8254, "output_tokens": 2973, "cache_read_tokens": 0,
                                "reasoning_tokens": 2825}
    assert _blocks(evs, "thinking")[0]["thinking"] == "counting" and evs[-1]["result"] == "21"
    # a build that reported the thinking beside the output: added, never lost
    evs, _, _ = _drive(tmp_path, mode="apart")
    assert evs[-1]["usage"]["output_tokens"] == 148 + 2825 and evs[-1]["usage"]["reasoning_tokens"] == 2825


def test_usage_never_has_more_reasoning_than_output():
    for u in ({"inputTokens": 5, "outputTokens": 12, "thoughtTokens": 3, "totalTokens": 17},
              {"inputTokens": 5, "outputTokens": 9, "thoughtTokens": 3, "totalTokens": 17},
              {"inputTokens": 5, "outputTokens": 1, "thoughtTokens": 9, "totalTokens": 6}):
        got = D.usage(u)
        assert got["reasoning_tokens"] <= got["output_tokens"], (u, got)
    assert D.usage({"inputTokens": 5, "outputTokens": 9, "thoughtTokens": 3, "totalTokens": 17})["output_tokens"] == 12
    assert D.usage({"inputTokens": 5, "outputTokens": 12, "thoughtTokens": 3, "totalTokens": 17})["output_tokens"] == 12
    assert D.usage(None) == {} and "reasoning_tokens" not in D.usage({"inputTokens": 1, "outputTokens": 1})


def test_a_stored_conversation_is_loaded_and_its_replay_is_not_the_turns_record(tmp_path):
    evs, asked, _ = _drive(tmp_path, resume="45233099-b000-438c-90c0-c5896a1c8f6d", known=True)
    methods = [a.get("method") for a in asked if a.get("method")]
    assert "session/load" in methods and "session/new" not in methods
    assert methods.index("session/load") < methods.index("session/set_model") < methods.index("session/prompt")
    text = "".join(b["text"] for b in _blocks(evs, "text"))
    assert "AN OLD REPLY" not in text and evs[-1]["result"] == "alpha and 4711"


def test_a_stored_conversation_that_will_not_load_fails_rather_than_starting_over(tmp_path):
    evs, asked, _ = _drive(tmp_path, mode="load_fails", resume="45233099-b000-438c-90c0-c5896a1c8f6d", known=True)
    assert evs[-1]["is_error"] and "could not be continued" in evs[-1]["result"]
    assert "session/new" not in [a.get("method") for a in asked]


def test_a_model_the_cli_refuses_fails_the_turn_in_words(tmp_path):
    evs, asked, _ = _drive(tmp_path, mode="bad_model")
    assert evs[-1]["is_error"] and "would not run gemini-3.8-flash-medium" in evs[-1]["result"]
    assert "session/prompt" not in [a.get("method") for a in asked]


def test_a_turn_that_ends_with_nothing_said_is_not_a_completed_turn(tmp_path):
    evs, _, _ = _drive(tmp_path, mode="silent")
    assert evs[-1]["is_error"] and "without answering" in evs[-1]["result"]


def test_the_cli_never_sees_the_job_or_the_key(tmp_path):
    """The agent's own environment, as the fake agy recorded it: the driver pops the job before it starts
    the CLI, and the only key-shaped value is the relay's placeholder the runner put there."""
    _, _, log = _drive(tmp_path, extra_env={"GEMINI_API_KEY": "hr-relay-" + "0" * 32})
    agent_env = json.loads(pathlib.Path(str(log) + ".env").read_text())
    assert "HR_DRIVER_JOB" not in agent_env
    assert agent_env["GEMINI_API_KEY"].startswith("hr-relay-")
    assert KEY not in json.dumps(agent_env)
    argv = json.loads(pathlib.Path(str(log) + ".argv").read_text())
    assert argv[1:] == ["acp", "--disable-telemetry"]


# ── an MCP call, and the read of its definition ─────────────────────────────────────────────────
MCP_CALL = {"sessionUpdate": "tool_call", "toolCallId": "c1", "name": "call_mcp_tool", "status": "in_progress",
            "kind": "execute", "title": "MCP Tool uhp_steps",
            "rawInput": {"Arguments": {"nonce": "n1"}, "ServerName": "conformance_fixture", "ToolName": "uhp_steps"}}


def _calls(home=""):
    evs: list = []
    return evs, D._Calls(D.Stream(lambda title, kind: title or kind or "tool", out=D._Definitions(str(home), out=evs.append)))


def test_an_mcp_calls_input_is_the_tools_own_arguments():
    """agy routes every MCP tool through call_mcp_tool with the tool's arguments inside its own input; the call is
    named for the tool, so its input is the tool's, as every other base gives it."""
    for raw in ({"nonce": "n1"}, '{"nonce": "n1"}'):
        evs, calls = _calls()
        calls.update({**MCP_CALL, "rawInput": {**MCP_CALL["rawInput"], "Arguments": raw}})
        (use,) = _blocks(evs, "tool_use")
        assert use["name"] == "mcp__conformance_fixture__uhp_steps" and use["input"] == {"nonce": "n1"}
    # arguments that are not an object keep the call's whole input, so nothing it carried is lost
    for raw in ("not json", '["a"]', ["a"], None):
        wrapper = {**MCP_CALL["rawInput"], "Arguments": raw}
        assert D.mcp_arguments(wrapper) == wrapper
    # a failed call carries its input in `args` only: named and unwrapped the same
    evs, calls = _calls()
    calls.update({**{k: v for k, v in MCP_CALL.items() if k != "rawInput"}, "status": "failed",
                  "args": MCP_CALL["rawInput"]})
    (use,) = _blocks(evs, "tool_use")
    assert use["name"] == "mcp__conformance_fixture__uhp_steps" and use["input"] == {"nonce": "n1"}


def _read(cid, path):
    return {"sessionUpdate": "tool_call", "toolCallId": cid, "name": "read_file", "status": "in_progress",
            "kind": "read", "title": "Read", "rawInput": {"Path": str(path)}}


def test_the_first_read_of_a_tools_definition_is_not_a_step_and_a_second_one_is(tmp_path):
    home = tmp_path / ".harness" / "home"
    mcp = home / ".gemini" / "antigravity-cli" / "mcp"
    evs, calls = _calls(home)
    calls.update(_read("r1", mcp / "conformance_fixture" / "uhp_steps.json"))
    calls.update(_read("r2", f"{mcp}/./conformance_fixture//uhp_steps.json"))   # the same file again
    calls.update(_read("r3", tmp_path / "notes.json"))                          # a file of the workspace's
    calls.update(_read("r4", mcp / ".." / "settings.json"))                     # beside the definitions, not under them
    calls.update(_read("r5", mcp / "conformance_fixture" / "uhp_steps.txt"))    # not a definition
    calls.update(_read("r6", mcp / "harnessrouter" / "ask_user.json"))          # another tool's, read once
    uses = _blocks(evs, "tool_use")
    assert [u["id"] for u in uses] == ["r1", "r2", "r3", "r4", "r5", "r6"]      # every read stays in the record
    assert [bool(u.get("not_a_step")) for u in uses] == [True, False, False, False, False, True]
    state: dict = {}
    assert [rs._count_tool_calls({"type": "assistant", "message": {"content": [u]}}, state) for u in uses] == \
        [0, 1, 2, 3, 4, 4]


def _run_driver(tmp_path, mode, max_turns=None):
    """The real driver against the fake agy, through the runner's own turn loop."""
    home = tmp_path / ".harness" / "home"
    log = tmp_path / "asked.ndjson"
    job = {"argv": [sys.executable, str(FAKE), "acp", "--disable-telemetry"], "cwd": str(tmp_path), "prompt": "go",
           "model": "gemini-3.8-flash", "agy_model": "gemini-3.8-flash-medium", "resume": "", "resume_known": False,
           "withheld": [], "timeout": 60}
    env = {**os.environ, "HOME": str(home), "FAKE_AGY_MODE": mode, "FAKE_AGY_LOG": str(log),
           "HR_DRIVER_JOB": json.dumps(job)}
    tid = "agy-" + mode + "-" + os.urandom(6).hex()
    rs._turns[tid] = {"status": "running", "events": [], "result": "", "done": False, "started": time.time(),
                      "backend": "agy", "model": "gemini-3.8-flash"}
    try:
        rs._run_turn_bg(tid, [sys.executable, str(pathlib.Path(D.__file__))], env, str(tmp_path),
                        rs._claude_passthrough, "gemini-3.8-flash", timeout_seconds=60,
                        max_turns=max_turns, count_steps=bool(max_turns))
        return rs._turns[tid]
    finally:
        rs._turns.pop(tid, None)


def test_a_one_step_budget_answers_the_tool_once_and_stops_at_the_next_call(tmp_path):
    """T-12's shape: `max_step: 1` and a chain of three calls. The read of the tool's definition agy makes before
    its first call is part of that call, so the one step is the tool's: it is answered, and the turn stops at the
    second call, incomplete at its budget."""
    rec = _run_driver(tmp_path, "steps", max_turns=1)
    uses = _blocks(rec["events"], "tool_use")
    answered = {b["tool_use_id"] for b in _blocks(rec["events"], "tool_result")}
    steps = [b for b in uses if b["name"] == "mcp__conformance_fixture__uhp_steps"]
    assert steps[0]["input"] == {"nonce": "n1"}
    assert steps[0]["id"] in answered, "the one step the budget allows was stopped before the tool answered"
    assert len(steps) == 2 and steps[1]["id"] not in answered
    assert rec["status"] == "max_turns"
    read = next(b for b in uses if b["name"] == "read_file")
    assert read["not_a_step"] is True and read["id"] in answered           # in the record, spending nothing


# ── a question for the person (#476) ──────────────────────────────────────────────────────────
ASK_SCRIPT = str(pathlib.Path(rs.__file__).with_name("ask_user_mcp.py"))
QUESTION = {"kind": "choice", "prompt": "Which language?",
            "options": [{"id": "en", "label": "English"}, {"id": "zh", "label": "Chinese"}]}


def test_the_ask_server_is_in_the_clis_mcp_config_only_when_the_turn_takes_input_requests(tmp_path):
    servers = [{"name": "plugs", "url": "http://127.0.0.1:41000/hr-mcp-" + "a" * 32 + "/mcp"}]
    path = tmp_path / ".harness/home/.gemini/config/mcp_config.json"
    _build(cwd=str(tmp_path), mcp_servers=servers, input_requests=True)
    cfg = json.loads(path.read_text())["mcpServers"]
    assert cfg["harnessrouter"] == {"command": sys.executable, "args": [ASK_SCRIPT]}
    assert cfg["plugs"] == {"serverUrl": servers[0]["url"]}                 # the harness's own beside it
    # the name the CLI will give its call is the one the runner ends the turn at
    assert rs._is_ask_tool(D.tool_name({"name": "call_mcp_tool", "rawInput": {
        "Arguments": QUESTION, "ServerName": "harnessrouter", "ToolName": "ask_user"}}))
    _build(cwd=str(tmp_path), mcp_servers=servers)
    cfg = json.loads(path.read_text())["mcpServers"]
    assert "harnessrouter" not in cfg and "plugs" in cfg


def _wait_done(tid, seconds=30):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if rs._turns.get(tid, {}).get("done"):
            return rs._turns[tid]
        time.sleep(0.05)
    raise AssertionError(f"turn {tid} did not finish in {seconds}s")


def test_a_turn_that_takes_input_requests_ends_on_the_question_and_the_answer_continues_it(tmp_path, monkeypatch):
    """Through /turn, the driver and the fake agy: the turn is served ask_user, ends `incomplete` with reason
    `input_required` at the tool's answer, and the answer's turn resumes the same conversation with a secret
    answer in the CLI's environment."""
    from fastapi.testclient import TestClient
    wrapper = tmp_path / "agy"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    wrapper.chmod(0o755)
    monkeypatch.setattr(rs, "AGY_BIN", str(wrapper))
    monkeypatch.setattr(rs, "_SESSION_UIDS", False, raising=False)
    monkeypatch.setattr(rs, "WORKSPACE_ROOT", str(tmp_path / "root"), raising=False)
    log = tmp_path / "asked.ndjson"
    monkeypatch.setenv("FAKE_AGY_LOG", str(log))
    monkeypatch.setenv("FAKE_AGY_MODE", "ask")
    client = TestClient(rs.app)
    body = {"backend": "agy", "provider": "google", "model": "gemini-3.8-flash", "prompt": "ask me",
            "auth": {"api_key": KEY}, "input_requests": True}
    r = client.post("/turn", params={"identifier": "hsess-agy-ask"}, json=body)
    assert r.status_code == 200, r.text
    rec = _wait_done(r.json()["turn_id"])
    assert rec["asks"] is True
    assert rec["status"] == "incomplete" and rec["reason"] == "input_required", (rec["status"], rec.get("error"))
    assert rec["input_request"] == QUESTION
    asked = [b for b in _blocks(rec["events"], "tool_use") if b["name"] == "mcp__harnessrouter__ask_user"]
    assert asked and asked[0]["input"] == QUESTION
    ws = pathlib.Path(rs._ws("hsess-agy-ask"))
    cfg = json.loads((ws / ".harness/home/.gemini/config/mcp_config.json").read_text())["mcpServers"]
    assert cfg["harnessrouter"] == {"command": sys.executable, "args": [ASK_SCRIPT]}
    # the answer: the next turn's prompt on the same conversation, a secret one in the turn's environment
    secret = "secret-answer-" + os.urandom(8).hex()
    monkeypatch.setenv("FAKE_AGY_MODE", "thinking")
    r = client.post("/turn", params={"identifier": "hsess-agy-ask"}, json={
        **body, "prompt": "The answer is in HR_INPUT_INREQ_1.", "resume_session_id": rec["session_id"],
        "env": {"HR_INPUT_INREQ_1": secret}, "env_secret": ["HR_INPUT_INREQ_1"]})
    nxt = _wait_done(r.json()["turn_id"])
    assert nxt["status"] == "done" and nxt["session_id"] == rec["session_id"]
    methods = [json.loads(ln).get("method") for ln in log.read_text().splitlines() if ln.strip()]
    assert "session/load" in methods and "session/new" not in methods
    assert json.loads(pathlib.Path(str(log) + ".env").read_text())["HR_INPUT_INREQ_1"] == secret


# ── the install: opt-in, pinned by version and digest ──────────────────────────────────────────
ENTRY = (ROOT / "docker" / "entrypoint.sh").read_text()


def test_the_base_is_not_in_the_default_install():
    default = ENTRY[ENTRY.index('export HR_BACKENDS="${HR_BACKENDS:-'):].split("\n", 1)[0]
    assert ",agy" not in default and "agy," not in default
    assert '\n    agy)    echo "$TOOLS/bin/agy" ;;' in ENTRY
    order = ENTRY[ENTRY.index('INSTALL_UID_ORDER="'):].split("\n", 1)[0]
    assert order.rstrip('" ').endswith(" agy")                          # a new base goes at the END
    assert "if wanted agy && ! current agy" in ENTRY


def test_the_install_is_pinned_by_version_and_by_the_digest_of_each_archive():
    body = ENTRY[ENTRY.index("AGY_PIN="):ENTRY.index("\n}\n", ENTRY.index("install_agy() {"))]
    assert 'AGY_PIN="${HR_AGY_VERSION:-1.5.8}"' in body
    for digest in ("905d4accfbd61bc00bee84bfaf24c59b85d334cabd786cf99237b66cfe06ab98",
                   "0ca407357661aa244fbc3b0e79a1d1d2623b2ca1515d2e2f77a801c3676bd562"):
        assert digest in body
    assert 'check_sha "agy $AGY_PIN" "$ag_tmp/agy.tar.gz" "$AGY_SHA"' in body
    assert "pin_sha AGY 1.5.8" in body                                  # an override brings its own digest
    assert "install.sh" not in body.split("install_agy() {", 1)[1]      # never the vendor's script
    assert "| bash" not in body and "| sh" not in body
    assert 'iu_untar "$ag_tmp/agy.tar.gz" "$ag_x" antigravity' in body  # unpacked as the install uid
    # the install's own start of the CLI, to read its version, has updates and crash reporting off too
    assert 'iu env AGY_CLI_DISABLE_AUTO_UPDATE=true ANTIGRAVITY_SENTRY_SAMPLE_RATE=0 "$TOOLS/bin/agy" --version' in body
    assert "storage.googleapis.com/antigravity-public/antigravity-cli/${AGY_PIN}-${AGY_BUILD}/" in body


def test_the_install_pin_check_still_holds():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "check-install-pins.py")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
