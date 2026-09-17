"""The kimi backend: Kimi Code CLI (MoonshotAI/kimi-code, MIT, pinned to 2.0.0).

0.18.0 wired this base to MoonshotAI/kimi-cli 1.50.0, the Python predecessor whose own README says
it "is evolving into Kimi Code CLI". The product is the TypeScript rewrite, a different integration
surface, and everything asserted here was measured on the 2.0.0 binary the installer pins (the VM
host, 2026-09-17), not read off the docs. Each test pins one thing that would otherwise fail
SILENTLY or loudly in production: the session id that only appears on the last line, the resume of
an id the store does not hold (a hard exit 1 on this CLI), the disabled tool that disables
nothing, the SSE server dialed as HTTP, the key written to disk.

Measured facts the code rests on:
  stream-json lines      meta system.version / assistant text / assistant tool_calls / tool / meta
                         session.resume_hint (LAST line, the only place the session id appears)
  model from env alone   KIMI_MODEL_NAME (+ _PROVIDER_TYPE, _BASE_URL, _API_KEY, _MAX_CONTEXT_SIZE):
                         a provider synthesised in memory, nothing persisted, no key at rest
  failures               exit 1 and one stderr line `error: failed to run prompt: <class>: <reason>`
                         (provider.auth_error, loop.max_steps_exceeded, Session "<id>" not found)
  tool policy            agent file (Markdown) `disallowedTools` by exact NAME, bound at session
                         creation; --agent-file is refused beside -r
  MCP                    $KIMI_CODE_HOME/mcp.json; url = streamable HTTP, transport "sse" explicit
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (Auth, BACKENDS, CHECKPOINT_EXCLUDE, _KIMI_TOOLS,  # noqa: E402
                    _kimi_mcp_unavailable, _clamp_max_tokens, _max_tokens_cap_from_refusal,
                    _agent_doc_path, _build_kimi, _failure_reason, _kimi_eof, _kimi_has_session,
                    _kimi_home, _kimi_to_claude, _normalize_openai_chat_body, _resume_lost)

SID = "session_ce4ef4a0-1606-430e-89fd-f228abfda9e7"


def _argv(d=None, **kw):
    d = d or tempfile.mkdtemp()
    env: dict = {}
    cmd = _build_kimi("openai-api", Auth(api_key="sk-t", base_url="https://up.example/v1"),
                      "kimi-k3", "do it", d, env, **kw)
    return cmd, d, env


def _norm(lines):
    state: dict = {"model": "kimi-k3"}
    out = []
    for line in lines:
        out += _kimi_to_claude(line, state)
    return out, state


def _store(d, sid=SID):
    """A session as 2.0.0 lays it down: sessions/<workdir key>/<session id>/…"""
    p = _kimi_home(pathlib.Path(d)) / "sessions" / "wd_ws_86f57a64234a" / sid
    (p / "agents" / "main").mkdir(parents=True)
    (p / "state.json").write_text("{}")
    return p


# ── the stream ───────────────────────────────────────────────────────────────────
def test_assistant_text_is_a_plain_string():
    out, state = _norm([{"role": "meta", "type": "system.version", "version": "2.0.0"},
                        {"role": "assistant", "content": "KC-ONE-5e1"}])
    assert out == [{"type": "assistant", "message": {"content": [{"type": "text", "text": "KC-ONE-5e1"}]}}]
    assert state["final"] == "KC-ONE-5e1"


def test_a_tool_call_has_no_content_key_and_does_not_overwrite_the_answer():
    """Captured live: the tool-carrying message has NO `content` key at all and the answer arrives
    after the tool result."""
    out, state = _norm([
        {"role": "assistant", "tool_calls": [{"type": "function", "id": "call_1", "function": {
            "name": "Write", "arguments": '{"path":"kc.txt","content":"HELLO\\n"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "Wrote 6 bytes to kc.txt"},
        {"role": "assistant", "content": "DONE"},
    ])
    assert state["final"] == "DONE"
    call = out[0]["message"]["content"][0]
    assert call == {"type": "tool_use", "id": "call_1", "name": "Write",
                    "input": {"path": "kc.txt", "content": "HELLO\n"}}
    res = out[1]["message"]["content"][0]
    assert res["type"] == "tool_result" and res["tool_use_id"] == "call_1"
    assert res["content"] == "Wrote 6 bytes to kc.txt"


def test_unparseable_tool_arguments_keep_the_raw_text_instead_of_dropping_the_call():
    out, _ = _norm([{"role": "assistant", "tool_calls": [{"id": "c", "function": {
        "name": "Bash", "arguments": "{not json"}}]}])
    assert out[0]["message"]["content"][0]["input"] == {"arguments": "{not json"}


def test_the_session_id_arrives_on_the_last_line_and_is_announced_from_it():
    """The resume hint is the only line that names the session. Without an init event carrying it
    the run loop records no conversation id and every follow-up starts a new conversation."""
    out, _ = _norm([{"role": "assistant", "content": "hi"},
                    {"role": "meta", "type": "session.resume_hint", "session_id": SID,
                     "command": f"kimi -r {SID}", "content": f"To resume this session: kimi -r {SID}"}])
    assert out[-1] == {"type": "system", "subtype": "init", "session_id": SID, "model": "kimi-k3"}
    assert sum(1 for e in out if e.get("subtype") == "init") == 1


def test_version_and_unknown_lines_are_dropped_not_crashed():
    out, _ = _norm([{"role": "meta", "type": "system.version", "version": "2.0.0"},
                    {"role": "meta", "type": "something.new"}, {"role": "system"}, {}])
    assert out == []


def test_the_exit_code_is_the_status_and_a_failure_leaves_the_reason_to_the_cli_s_own_line():
    ok = _kimi_eof({"final": "answer"}, 0)[0]
    assert ok["is_error"] is False and ok["result"] == "answer" and ok["usage"] == {}
    bad = _kimi_eof({"final": "half an answer"}, 1)[0]
    assert bad["is_error"] is True and bad["result"] == ""      # never report a failure as an answer


def test_the_failure_reason_drops_the_cli_s_notes_to_a_person_at_its_terminal():
    tail = ("error: failed to run prompt: provider.auth_error: 401 Invalid API-key provided.\n"
            "See log: /data/workspaces/hsess1/.harness/home/.kimi-code/logs/kimi-code.log")
    assert _failure_reason("", "", tail, 1) == \
        "error: failed to run prompt: provider.auth_error: 401 Invalid API-key provided."
    assert _failure_reason("", "", "To resume this session: kimi -r session_x", 1) == \
        "exit_code=1, no diagnostic output"


# ── the command and its environment ──────────────────────────────────────────────
def test_the_model_is_defined_from_the_environment_and_nothing_is_written_with_a_key():
    cmd, d, env = _argv()
    assert cmd[:5] == ["kimi", "-p", "do it", "--output-format", "stream-json"]
    assert env["KIMI_MODEL_NAME"] == "kimi-k3" and env["KIMI_MODEL_PROVIDER_TYPE"] == "openai"
    assert env["KIMI_CODE_HOME"] == str(_kimi_home(pathlib.Path(d)))
    assert env["KIMI_DISABLE_TELEMETRY"] == "1" and env["KIMI_CODE_NO_AUTO_UPDATE"] == "1"
    assert int(env["KIMI_MODEL_MAX_CONTEXT_SIZE"]) > 0
    # the relay stands between the CLI and the provider: neither the real key nor the real base
    assert env["KIMI_MODEL_API_KEY"] != "sk-t" and "up.example" not in env["KIMI_MODEL_BASE_URL"]
    for f in pathlib.Path(d).rglob("*"):
        if f.is_file():
            assert "sk-t" not in f.read_text(errors="replace"), f"the key was written to {f}"
    assert not list(pathlib.Path(d).rglob("config.toml"))       # no config file at all
    # -p refuses --yolo/--auto beside it, and there is no work-dir flag: the process cwd is the workspace
    assert not {"--yolo", "--auto", "-y", "-w"} & set(cmd)


def test_the_operators_step_budget_reaches_the_cli_and_none_means_no_variable():
    assert _argv(max_turns=40)[2]["KIMI_LOOP_MAX_STEPS_PER_TURN"] == "40"
    assert "KIMI_LOOP_MAX_STEPS_PER_TURN" not in _argv()[2]


def test_a_session_the_store_holds_is_resumed_and_one_it_does_not_hold_is_never_passed():
    """`kimi -r <unknown id>` is exit 1 on this CLI (`Session "<id>" not found`), so passing an id
    the store lost would fail the whole turn. The builder asks the store; the lost conversation is
    reported through _resume_lost instead, and the turn runs fresh."""
    d = tempfile.mkdtemp(); _store(d)
    cmd, _, _ = _argv(d, resume_session_id=SID)
    assert cmd[cmd.index("-r") + 1] == SID
    assert _resume_lost("kimi", cmd, SID, d) is None
    lost, d2, _ = _argv(resume_session_id=SID)
    assert "-r" not in lost
    assert _resume_lost("kimi", lost, SID, d2) == SID
    assert _resume_lost("kimi", lost, None, d2) is None


def test_the_store_lookup_refuses_an_id_that_is_a_path():
    d = tempfile.mkdtemp(); _store(d)
    home = _kimi_home(pathlib.Path(d))
    assert _kimi_has_session(home, SID)
    for bad in ("", "../..", "a/b", ".hidden", "session_nope"):
        assert not _kimi_has_session(home, bad)


def test_resume_lost_keeps_the_other_backends_unchanged():
    assert _resume_lost("claude", ["claude", "--resume", "abc"], "abc", "/x") is None
    assert _resume_lost("claude", ["claude"], "abc", "/x") == "abc"
    assert _resume_lost("goose", ["goose", "-n", "harness", "-r"], "harness", "/x") is None
    assert _resume_lost("goose", ["goose", "-n", "harness"], "harness", "/x") == "harness"
    assert _resume_lost("codex", ["codex"], "abc", "/x") is None      # carries its own note


# ── tool policy ──────────────────────────────────────────────────────────────────
def test_disabled_tools_become_an_agent_file_by_name_on_a_new_session():
    cmd, d, _ = _argv(tools_disabled=["Bash", "NotATool"])
    path = pathlib.Path(cmd[cmd.index("--agent-file") + 1])
    text = path.read_text()
    assert text.startswith("---\n") and "disallowedTools:\n  - Bash\nsubagents: []\n---" in text
    # a withheld tool must not come back by delegation: a built-in subagent carries its own tools
    assert "NotATool" not in text               # an unknown name "never matches anything": not written
    assert text.rstrip().endswith("${base_prompt}")     # the default prompt's injections stay


def test_no_agent_file_when_nothing_is_disabled_or_when_resuming():
    assert "--agent-file" not in _argv()[0]
    assert "--agent-file" not in _argv(tools_disabled=["NotATool"])[0]
    d = tempfile.mkdtemp(); _store(d)
    cmd, _, _ = _argv(d, resume_session_id=SID, tools_disabled=["Bash"])
    assert "-r" in cmd and "--agent-file" not in cmd     # the CLI refuses the two together


def test_the_tool_names_are_the_captured_array():
    assert {"Bash", "Read", "Write", "Edit", "Grep", "Glob", "FetchURL", "Skill", "Agent"} <= set(_KIMI_TOOLS)
    assert "WebSearch" not in _KIMI_TOOLS and len(set(_KIMI_TOOLS)) == len(_KIMI_TOOLS)


# ── MCP, skills, instructions ────────────────────────────────────────────────────
def _mcp(d):
    return json.loads((_kimi_home(pathlib.Path(d)) / "mcp.json").read_text())["mcpServers"]


def test_mcp_servers_carry_the_transport_the_harness_declared():
    _, d, _ = _argv(mcp_servers=[
        {"name": "events", "transport": "sse", "url": "https://example.test/events"},
        {"name": "api", "transport": "http", "url": "https://example.test/mcp", "headers": {"X-K": "v"}},
        {"name": "local", "command": "/ws/launch.sh", "args": ["--root", "/p"], "env": {"A": "1"}, "cwd": "/p"}])
    got = _mcp(d)
    assert got["events"] == {"url": "https://example.test/events", "transport": "sse"}
    assert got["api"] == {"url": "https://example.test/mcp", "headers": {"X-K": "v"}}   # no transport = HTTP
    assert got["local"] == {"command": "/ws/launch.sh", "args": ["--root", "/p"], "env": {"A": "1"}, "cwd": "/p"}


def test_the_mcp_file_is_rewritten_every_turn_so_a_removed_server_is_gone():
    d = tempfile.mkdtemp()
    _argv(d, mcp_servers=[{"name": "api", "url": "https://example.test/mcp"}])
    assert "api" in _mcp(d)
    _argv(d)
    assert _mcp(d) == {}


def test_a_plugins_stdio_server_reaches_kimi_as_command_and_args():
    """_plugin_launchers hands every writer {name, command, args}; that is mcp.json's stdio entry."""
    _, d, _ = _argv(mcp_servers=[{"name": "probe", "command": "/ws/.harness/plugins/x/launch-probe.sh", "args": []}])
    assert _mcp(d)["probe"] == {"command": "/ws/.harness/plugins/x/launch-probe.sh", "args": []}


def test_skills_dir_is_named_only_when_there_are_skills():
    assert "--skills-dir" not in _argv()[0]
    cmd, _, _ = _argv(skills_dir="/ws/.harness/skills")
    assert cmd[cmd.index("--skills-dir") + 1] == "/ws/.harness/skills"


def test_agent_doc_is_agents_md():
    assert _agent_doc_path("/ws", "kimi").name == "AGENTS.md"


# ── the rest of the wiring ───────────────────────────────────────────────────────
def test_registry_and_checkpoint():
    assert BACKENDS["kimi"]["normalize"] is _kimi_to_claude and hasattr(_kimi_to_claude, "eof")
    assert "./.harness/home/.kimi-code/logs" in CHECKPOINT_EXCLUDE
    assert not any(e.rstrip("/").endswith(".kimi-code/sessions") or e.rstrip("/").endswith(".kimi-code")
                   for e in CHECKPOINT_EXCLUDE), "sessions must travel or a resume dies with the sandbox"


def test_null_reasoning_effort_is_still_dropped_in_the_relay():
    """Kimi Code CLI 2.0.0 sends no reasoning_effort at all (captured at a stub); the repair stays
    for any client that sends the null, and a real value is the caller's choice."""
    assert "reasoning_effort" not in json.loads(_normalize_openai_chat_body(
        json.dumps({"model": "m", "reasoning_effort": None, "messages": []}).encode()))
    assert json.loads(_normalize_openai_chat_body(
        json.dumps({"model": "m", "reasoning_effort": "high", "messages": []}).encode()))["reasoning_effort"] == "high"


def test_an_mcp_server_the_cli_silently_ran_without_is_said_out_loud():
    """2.0.0 runs the turn without an unreachable server and prints nothing anywhere but its log.
    Only this turn's lines count: an older failure is not this reply's news."""
    import datetime, time
    d = tempfile.mkdtemp(); logs = _kimi_home(pathlib.Path(d)) / "logs"; logs.mkdir(parents=True)
    now = time.time()
    iso = lambda ts: datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    (logs / "kimi-code.log").write_text(
        f'{iso(now - 3600)} ERROR mcp server unavailable  server=old transport=http status=failed reason="fetch failed"\n'
        f'{iso(now + 1)} INFO something else entirely\n'
        f'{iso(now + 1)} ERROR mcp server unavailable  server=dead transport=http status=failed reason="fetch failed"\n')
    state = {"cwd": d, "started": now, "final": "HELLO"}
    assert _kimi_mcp_unavailable(state) == [{"name": "dead", "reason": "fetch failed"}]
    evs = _kimi_eof(state, 0)
    assert evs[0] == {"type": "system", "subtype": "mcp_unavailable", "servers": [{"name": "dead", "reason": "fetch failed"}]}
    assert evs[-1]["type"] == "result" and evs[-1]["result"] == "HELLO" and evs[-1]["is_error"] is False
    assert _kimi_eof({"final": "x"}, 0)[0]["type"] == "result"          # no cwd, no log: just the result


def test_the_relay_learns_a_model_s_output_limit_from_the_refusal_that_states_it():
    """Kimi Code CLI sends max_tokens 131072 on every request; these are the three refusals the
    product run collected, verbatim. The limit is read from the message, never guessed."""
    sent = json.dumps({"model": "m", "max_tokens": 131072, "messages": []}).encode()
    cases = [
        (b'{"error":{"message":"max_tokens is too large: 131072. This model supports at most 128000 completion tokens, whereas you provided 131072."}}', 128000),
        (b'{"error":{"message":"max_tokens: 131072 > 128000, which is the maximum allowed number of output tokens for claude-sonnet-4-6"}}', 128000),
        (b'{"error":{"message":"Unable to submit request because it has a maxOutputTokens value of 131072 but the supported range is from 1 (inclusive) to 65537 (exclusive)."}}', 65536),
    ]
    for data, want in cases:
        assert _max_tokens_cap_from_refusal(data, sent) == want
    # a refusal about something else, or one that names no usable number, teaches nothing
    assert _max_tokens_cap_from_refusal(b'{"error":{"message":"Invalid API key 12345"}}', sent) is None
    assert _max_tokens_cap_from_refusal(b'{"error":{"message":"max_tokens is invalid"}}', sent) is None
    assert _max_tokens_cap_from_refusal(cases[0][0], json.dumps({"model": "m", "messages": []}).encode()) is None
    assert json.loads(_clamp_max_tokens(sent, 128000))["max_tokens"] == 128000
    small = json.dumps({"model": "m", "max_tokens": 4096}).encode()
    assert _clamp_max_tokens(small, 128000) is small                   # asking for less is left alone


def test_a_hard_refusal_does_not_burn_ten_attempts():
    assert _argv()[2]["KIMI_LOOP_MAX_ATTEMPTS_PER_STEP"] == "3"

