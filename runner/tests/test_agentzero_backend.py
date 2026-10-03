"""The agentzero backend (Agent Zero v2.13, MIT, driven in process by runner/agentzero_driver.py).

What was measured against the pinned v2.13 (2026-09-26/27) and is pinned here:

  a provider failure is STRUCTURAL — with a wrong key (401) and a dead base url the task raised
      HandledException and the only text was an `error` log item; no response-tool text at all.
      So the answer that merely mentions an error is an ordinary answer.
  a config.json REPLACES a plugin's defaults — with only {"ssh_enabled": false} the terminal lost
      every prompt pattern and waited out its 15 s no-output timeout on each command.
  `input` types into the terminal — a model denied code_execution_tool could run commands through it.
  the terminal is spawned with start_new_session=True — out of the group the runner kills.
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import agentzero_driver as drv  # noqa: E402


# ── the tool policy ──
def test_the_tools_that_cannot_run_here_are_always_blocked():
    pol = drv.tool_policy([])
    assert pol["mode"] == "custom" and pol["default"] == "allow"
    for tid in ("local:search_engine", "local:document_query", "local:scheduler",
                "local:notify_user", "local:a2a_chat"):
        assert tid in pol["blocked"]


def test_disabling_the_shell_withholds_input_too():
    """input.py calls CodeExecution with runtime=terminal and the keyboard text as the command, so
    leaving it allowed would leave the shell allowed."""
    blocked = drv.tool_policy(["code_execution_tool"])["blocked"]
    assert "plugin:_code_execution:code_execution_tool" in blocked
    assert "plugin:_code_execution:input" in blocked


def test_a_disabled_tool_is_blocked_by_the_canonical_id_the_policy_keys_on():
    blocked = drv.tool_policy(["text_editor", "call_subordinate", "goal"])["blocked"]
    assert {"plugin:_text_editor:text_editor", "local:call_subordinate",
            "plugin:_goal:goal"} <= set(blocked)


def test_an_unknown_name_blocks_nothing_extra():
    assert drv.tool_policy(["WebSearch"])["blocked"] == list(drv.ALWAYS_BLOCKED)


# ── MCP ──
def test_a_url_server_carries_its_declared_transport():
    cfg = json.loads(drv.mcp_config([{"name": "probe", "url": "https://x/sse", "transport": "sse"},
                                      {"name": "h", "url": "https://x/mcp", "transport": "http"}]))
    assert cfg["mcpServers"]["probe"] == {"url": "https://x/sse", "type": "sse"}
    assert cfg["mcpServers"]["h"]["type"] == "streamable-http"


def test_a_stdio_server_is_command_and_args():
    cfg = json.loads(drv.mcp_config([{"name": "s", "command": ["node", "srv.js"], "args": ["-v"],
                                      "env": {"A": "1"}}]))
    assert cfg["mcpServers"]["s"] == {"command": "node", "args": ["srv.js", "-v"], "env": {"A": "1"}}


def test_a_disabled_mcp_tool_goes_to_the_servers_own_disabled_tools():
    """Agent Zero's MCP client hides a server's disabled_tools from the prompt and refuses them at
    call time; a built-in name must not land there."""
    cfg = json.loads(drv.mcp_config([{"name": "probe", "url": "https://x", "transport": "sse"}],
                                    ["probe_sse", "code_execution_tool"]))
    assert cfg["mcpServers"]["probe"]["disabled_tools"] == ["probe_sse"]


def test_no_servers_is_an_empty_config():
    assert json.loads(drv.mcp_config(None)) == {"mcpServers": {}}


# ── the model ──
def test_the_model_is_provider_other_through_the_given_base():
    p = drv.presets("openai/gpt-5.4", "http://127.0.0.1:1/v1")
    assert p[0]["name"] == "Default"
    for slot in ("chat", "utility"):
        assert p[0][slot]["provider"] == "other"
        assert p[0][slot]["name"] == "openai/gpt-5.4"
        assert p[0][slot]["api_base"] == "http://127.0.0.1:1/v1"
    assert "api_key" not in json.dumps(p)


def test_every_provider_call_is_bounded_and_retried_once():
    """MEASURED: with no timeout an endpoint that never answers held a turn past 900 s, and with a
    5 s timeout but the three nested retry ladders the reason came after 110 s; with these, 29 s."""
    kw = drv.presets("m", "http://r/v1", 300)[0]["chat"]["kwargs"]
    assert kw["timeout"] == 300 and kw["stream_timeout"] == 300
    assert kw["max_retries"] == 0 and kw["a0_retry_attempts"] == 1


# ── the terminal ──
def _fake_src(tmp: pathlib.Path) -> pathlib.Path:
    src = tmp / "src"
    (src / "plugins" / "_code_execution").mkdir(parents=True)
    (src / "plugins" / "_code_execution" / "default_config.yaml").write_text(
        "ssh_enabled: auto\ncode_exec_max_exec_timeout: 240\nprompt_patterns: |\n  root@[^:]+:[^#]+# ?$\n")
    for d in ("helpers", "plugins", "prompts", "conf"):
        (src / d).mkdir(exist_ok=True)
    (src / "agent.py").write_text("")
    (src / "usr").mkdir()
    return src


def test_the_terminal_config_keeps_upstreams_defaults(tmp_path):
    import pytest
    pytest.importorskip("yaml")   # the driver runs in Agent Zero's venv, which has it
    cfg = drv.code_execution_config(_fake_src(tmp_path))
    assert cfg["ssh_enabled"] is False
    assert cfg["code_exec_max_exec_timeout"] == 240
    assert "root@" in cfg["prompt_patterns"] and drv._BARE_BASH_PROMPT in cfg["prompt_patterns"]


def test_the_bare_bash_prompt_matches():
    import re
    assert re.search(drv._BARE_BASH_PROMPT, "bash-5.2$ ")
    assert re.search(drv._BARE_BASH_PROMPT, "bash-3.2$")


def test_the_terminal_stays_in_the_drivers_process_group():
    import asyncio
    seen = {}

    async def fake(cmd, *a, **k):
        seen.update(k)

    real = asyncio.create_subprocess_shell
    asyncio.create_subprocess_shell = fake
    try:
        drv.keep_children_in_group()
        asyncio.run(asyncio.create_subprocess_shell("bash", start_new_session=True))
    finally:
        asyncio.create_subprocess_shell = real
    assert seen["start_new_session"] is False


# ── the base ──
def test_the_base_links_code_and_keeps_state_its_own(tmp_path):
    src = _fake_src(tmp_path)
    ws = tmp_path / "ws"
    base = drv.prepare_base(src, ws / ".harness" / "agentzero", ws / "tmp" / "agentzero")
    assert (base / "helpers").is_symlink() and (base / "agent.py").is_symlink()
    assert (base / "usr").is_dir() and not (base / "usr").is_symlink()
    assert (base / "tmp").is_symlink()
    # a second call repairs a link to an old install and is otherwise a no-op
    (base / "helpers").unlink(); (base / "helpers").symlink_to(tmp_path)
    drv.prepare_base(src, ws / ".harness" / "agentzero", ws / "tmp" / "agentzero")
    assert (base / "helpers").resolve() == (src / "helpers").resolve()


def test_the_config_files_land_where_agent_zero_reads_them(tmp_path):
    import pytest
    pytest.importorskip("yaml")
    src = _fake_src(tmp_path)
    ws = tmp_path / "ws"
    base = drv.prepare_base(src, ws / ".harness" / "agentzero", ws / "tmp" / "agentzero")
    drv.write_config(base, {"cwd": str(ws), "model": "m", "base_url": "http://r/v1",
                            "tools_disabled": ["text_editor"], "api_key": "hr-relay-x"}, src)
    usr = base / "usr"
    assert (usr / "plugins" / "_model_config" / "presets.yaml").is_file()
    assert (usr / "plugins" / "_memory" / ".toggle-0").is_file()
    pol = json.loads((usr / "plugins" / "_tool_access" / "config.json").read_text())
    assert "plugin:_text_editor:text_editor" in pol["blocked"]
    inc = json.loads((usr / "plugins" / "_promptinclude" / "config.json").read_text())
    assert inc["name_pattern"] == "AGENTS.md"
    env = (usr / "prompts" / "agent.system.main.environment.md").read_text()
    assert str(ws) in env and "/a0" not in env
    assert "hr-relay-x" not in "".join(p.read_text() for p in usr.rglob("*") if p.is_file())


def test_the_workdir_tree_hides_the_harness_state(tmp_path):
    assert ".harness/**" in drv._workdir_gitignore(_fake_src(tmp_path))


# ── what the support matrix found, and what fixed it (2026-09-28) ──
def test_the_turn_runs_in_the_workspace_not_in_the_frameworks_base():
    """The two defects the matrix found were both about WHERE something lands.

    A tool that takes a path from the model resolves it against the PROCESS cwd: text_editor writes
    with a bare open(path) (plugins/_text_editor/helpers/file_ops.write_file). With the cwd left at
    Agent Zero's base — where the framework has to be imported from — a model that asked for
    "hello-agentzero.txt" had its file written inside .harness/, the prefix /produced excludes, so
    the turn delivered nothing while its card said "Edited a file". Measured on the support matrix:
    every artifact failure was a model that passed a RELATIVE path, which is why it read as
    intermittent. The chdir must happen after the framework is importable and before the turn."""
    src = pathlib.Path(drv.__file__).read_text()
    on_path = src.index("sys.path.insert(0, str(base))")
    into_ws = src.index("os.chdir(str(cwd))")
    run = src.index("asyncio.run(_run(job))")
    assert on_path < into_ws < run
    # and the base is still what the framework computes its own paths from
    assert src.index("os.chdir(str(base))") < into_ws


def test_the_conversation_starts_with_the_users_own_first_message(tmp_path):
    """Agent Zero opens a fresh conversation with a FABRICATED exchange — a user message "Hello!"
    and an assistant greeting — so its web UI never starts empty. In a harness that is a lie about
    the user. Measured: asked "what exact word did I ask you to reply with in my very first
    message", five model/run pairs on the matrix answered the INJECTED message back ("Hello",
    "Hello!", "none", "you did not ask me to reply with any specific word") while the real first
    message sat in the same prompt.

    The override is by FILE NAME (helpers/extension._get_extension_classes merges by file name,
    first occurrence winning, and usr/extensions comes first), so the name is load-bearing: this
    test is what fails if a pin bump renames the bundled extension."""
    base = drv.prepare_base(_fake_src(tmp_path), tmp_path / "ws" / ".harness" / "agentzero",
                            tmp_path / "ws" / "tmp")
    drv.install_hooks(base)
    f = base / "usr" / "extensions" / "python" / "agent_init" / "_10_initial_message.py"
    assert f.is_file()
    body = f.read_text()
    assert "class InitialMessage(Extension)" in body   # the bundled class's name, by contract
    assert "return" in body.split("def execute")[1]


def test_the_model_is_told_to_name_files_the_way_the_reader_sees_them():
    """The workdir is an absolute sandbox path (/data/workspaces/hsess…), and a model that repeats
    it in its answer shows the reader a path that means nothing to them. A nudge, not a guarantee:
    the turn's cwd is the workspace, so a relative path is all the agent needs."""
    env = drv.environment_prompt("/data/workspaces/hsess1/x")
    assert "relative to the working directory" in env


def test_a_per_turn_file_is_replaced_whole(tmp_path):
    """Two turns of one session can run at once — the gateway starts the next without stopping a
    turn still in flight (measured 2026-10-01: a second turn completed in 3.9 s while the first was
    still running, and the orphan lived to the runner's own cap). Both drivers then write this
    workspace's config and hook files, and a truncate-then-write would let the other one import an
    EMPTY extension module and lose that turn's tool cards silently."""
    f = tmp_path / "x.py"
    f.write_text("old")
    drv.write_atomic(f, "new")
    assert f.read_text() == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["x.py"]   # no .tmp left behind


def test_the_console_log_is_this_turns_own():
    """A shared name opened O_TRUNC lets a newcomer empty the log of the turn still writing it —
    the 0-byte console.log a hung turn left behind on the family tour."""
    src = pathlib.Path(drv.__file__).read_text()
    assert 'f"console-{os.getpid()}.log"' in src


# ── the event hooks ──
def test_the_response_tool_is_the_answer_not_a_card(capsys):
    drv._STATE.update({"pending": {}, "final": ""})
    lines = []
    drv._emit, real = (lambda m, p: lines.append((m, p))), drv._emit
    try:
        agent = type("A", (), {"number": 0})()
        drv.on_tool_before(agent, "response", {"text": "done"})
        drv.on_tool_after(agent, "response", type("R", (), {"message": "done"})())
        drv.on_tool_before(agent, "code_execution_tool", {"code": "ls"})
        drv.on_tool_after(agent, "code_execution_tool", type("R", (), {"message": "a b"})())
    finally:
        drv._emit = real
    assert drv._STATE["final"] == "done"
    assert [m for m, _ in lines] == ["tool_call", "tool_result"]
    assert lines[0][1]["id"] == lines[1][1]["id"]


def test_a_subordinates_response_is_not_the_answer():
    drv._STATE.update({"pending": {}, "final": ""})
    drv.on_tool_after(type("A", (), {"number": 1})(), "response",
                      type("R", (), {"message": "to superior"})())
    assert drv._STATE["final"] == ""


def test_the_step_budget_ends_the_turn():
    drv._STATE.update({"steps": 0, "max_turns": 2})
    agent = type("A", (), {"number": 0})()
    drv.on_loop_start(agent, None); drv.on_loop_start(agent, None)
    import pytest
    with pytest.raises(RuntimeError, match="step budget"):
        drv.on_loop_start(agent, None)
    drv._STATE.update({"steps": 0, "max_turns": None})


def test_the_error_reason_is_cut_at_the_traceback():
    item = type("I", (), {"type": "error",
                          "content": "litellm.AuthenticationError: bad key\n\nTraceback (most recent call last):\n  x"})()
    ctx = type("C", (), {"log": type("L", (), {"logs": [item]})()})()
    assert drv._error_reason(ctx, Exception("x")) == "litellm.AuthenticationError: bad key"


# ── the runner side ──
from server import (Auth, _agent_doc_path, _agentzero_to_claude, _build_agentzero,  # noqa: E402
                    _resume_lost, BACKENDS, CHECKPOINT_EXCLUDE)


def _norm(lines):
    state = {"model": "m"}
    out = []
    for ln in lines:
        out += _agentzero_to_claude(ln, state)
    return out, state


def test_init_announces_the_conversation_the_next_turn_resumes():
    out, _ = _norm([{"m": "init", "p": {"session_id": "harness"}}])
    assert out[0]["type"] == "system" and out[0]["subtype"] == "init"
    assert out[0]["session_id"] == "harness"


def test_a_provider_failure_fails_the_turn_with_its_reason():
    out, _ = _norm([{"m": "result", "p": {"ok": False, "final": "",
                                          "error": "litellm.AuthenticationError: 401"}}])
    assert out[-1]["is_error"] is True and "401" in out[-1]["result"]
    assert not any(e["type"] == "assistant" for e in out)


def test_an_answer_that_mentions_an_error_is_an_answer():
    text = "API Error: litellm.AuthenticationError: that is what your log shows."
    out, _ = _norm([{"m": "result", "p": {"ok": True, "final": text, "error": ""}}])
    assert out[-1]["subtype"] == "success" and out[-1]["result"] == text
    assert out[0]["message"]["content"][0]["text"] == text


def test_a_shell_call_renders_as_a_shell_card_with_its_command():
    out, _ = _norm([{"m": "tool_call", "p": {"id": "a0-1", "name": "code_execution_tool",
                                             "input": {"runtime": "terminal", "code": "ls"}}},
                    {"m": "tool_result", "p": {"id": "a0-1", "output": "a.txt"}}])
    use = out[0]["message"]["content"][0]
    assert use["name"] == "Shell" and use["input"]["command"] == "ls"
    res = out[1]["message"]["content"][0]
    assert res["tool_use_id"] == "a0-1" and res["content"] == "a.txt" and res["is_error"] is False


def test_an_mcp_tool_keeps_its_own_name():
    out, _ = _norm([{"m": "tool_call", "p": {"id": "a0-2", "name": "probe.probe_sse", "input": {}}}])
    assert out[0]["message"]["content"][0]["name"] == "probe.probe_sse"


def test_a_crash_before_the_result_is_a_failure():
    _, state = _norm([{"m": "init", "p": {}}])
    eof = _agentzero_to_claude.eof(state, 1)
    assert eof[0]["is_error"] is True


def test_the_relay_token_rides_the_environment_and_the_key_never_does():
    d = tempfile.mkdtemp(); env: dict = {}
    cmd = _build_agentzero("openai-api", Auth(api_key="sk-real", base_url="https://up.example/v1"),
                           "openai/gpt-5.4", "hi", d, env, tools_disabled=["text_editor"],
                           max_turns=7)
    job = json.loads(env["HR_AGENTZERO_JOB"])
    assert env["OTHER_API_KEY"].startswith("hr-relay-") and "api_key" not in job
    assert "sk-real" not in json.dumps(cmd) and "sk-real" not in json.dumps(env)
    # argv is readable by every uid in the container: it names the interpreter and the driver, and
    # neither the relay route's token nor anything else of the job
    assert len(cmd) == 2 and env["OTHER_API_KEY"] not in json.dumps(cmd)
    assert job["model"] == "openai/gpt-5.4" and job["base_url"].startswith("http://127.0.0.1:")
    assert job["tools_disabled"] == ["text_editor"] and job["max_turns"] == 7


def test_an_unknown_provider_is_refused():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _build_agentzero("bedrock", Auth(api_key="k", base_url="https://x/v1"), "m", "p",
                         tempfile.mkdtemp(), {})


def test_registration():
    assert BACKENDS["agentzero"]["normalize"] is _agentzero_to_claude
    assert _agent_doc_path("/w", "agentzero").name == "AGENTS.md"
    assert "./.harness/agentzero/base/usr/.env" in CHECKPOINT_EXCLUDE
    assert "./.harness/agentzero/base/usr/secrets.env" in CHECKPOINT_EXCLUDE


def test_a_lost_conversation_is_reported(tmp_path):
    d = str(tmp_path)
    assert _resume_lost("agentzero", ["py"], "harness", d) == "harness"
    chat = tmp_path / ".harness" / "agentzero" / "base" / "usr" / "chats" / "harness" / "chat.json"
    chat.parent.mkdir(parents=True)
    chat.write_text(json.dumps({"agents": [{"history": ""}]}))
    assert _resume_lost("agentzero", ["py"], "harness", d) == "harness"
    chat.write_text(json.dumps({"agents": [{"history": "{\"x\": 1}"}]}))
    assert _resume_lost("agentzero", ["py"], "harness", d) is None


def test_skills_land_in_agent_zeros_user_skills_root(tmp_path):
    from server import _write_skills
    _write_skills(str(tmp_path), [{"name": "demo", "content": "---\nname: demo\ndescription: d\n---\nx"}],
                  backend="agentzero")
    assert (tmp_path / ".harness" / "agentzero" / "base" / "usr" / "skills" / "demo" / "SKILL.md").is_file()


def test_the_base_is_not_committed_to_the_workspace_repo(tmp_path):
    from server import _git_ensure
    _git_ensure(str(tmp_path))
    assert ".harness/agentzero/" in (tmp_path / ".gitignore").read_text().splitlines()


def test_a_servers_auth_reaches_agent_zero_as_its_authorization_header_and_never_argv():
    """The plugs server (browser, GitHub) carries `auth` and no headers. A writer that copied
    `headers` alone handed Agent Zero a url with no credential, and the base had no browser."""
    import agentzero_driver as drv
    d = tempfile.mkdtemp(); env: dict = {}
    cmd = _build_agentzero("openai-api", Auth(api_key="sk-real", base_url="https://up.example/v1"),
                           "gpt-5.4", "hi", d, env,
                           mcp_servers=[{"name": "plugs", "url": "https://gw.example/mcp",
                                         "transport": "http", "auth": "tok-123"},
                                        {"name": "bare", "url": "https://x.example/mcp"}])
    assert "tok-123" not in json.dumps(cmd)
    job = json.loads(env["HR_AGENTZERO_JOB"])
    cfg = json.loads(drv.mcp_config(job["mcp_servers"]))
    servers = cfg.get("mcpServers", cfg)
    assert servers["plugs"]["headers"] == {"Authorization": "Bearer tok-123"}
    assert servers["plugs"]["type"] == "streamable-http"
    # an undeclared transport is streamable HTTP here, whatever Agent Zero's own default is
    assert servers["bare"]["type"] == "streamable-http"
