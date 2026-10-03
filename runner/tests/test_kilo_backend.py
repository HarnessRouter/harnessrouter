"""The kilo backend (Kilo CLI 7.8.1, an opencode fork), against what the pinned binary was measured
to do. Every fixture below is a shape captured from the real binary at a logging stub (2026-09-26),
not a guess from docs:

  - `kilo run --format json` writes {type, timestamp, sessionID, part|error} per line, opencode's
    six event types;
  - a provider 401/503 is ONE structural error event (APIError, data.message, statusCode) and exit 1;
  - a run with no assistant output is an error event whose `error` is a bare STRING;
  - the session store is SQLite `session(id TEXT PRIMARY KEY, directory, ...)` in
    $HOME/.local/share/kilo/kilo.db, and an unknown --session exits 1 with nothing on stdout.
"""
import http.server
import json
import pathlib
import socket
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from server import (Auth, _agent_doc_path, _build_kilo, _kilo_denies, _kilo_eof,  # noqa: E402
                    _kilo_has_session, _kilo_npm, _kilo_to_claude, _resume_lost)

SID = "ses_f1f94c802ffe8og0Qkxjz0Z8e0"


def _ev(t, **data):
    return {"type": t, "timestamp": 1790471497741, "sessionID": SID, **data}


def _run(events, rc=0):
    state = {"model": "gpt-5.4", "final": ""}
    out = []
    for ev in events:
        out.extend(_kilo_to_claude(ev, state))
    out.extend(_kilo_eof(state, rc))
    return out, state


def _result(out):
    return [e for e in out if e.get("type") == "result"][-1]


# ── the normaliser ────────────────────────────────────────────────────────────────────────────

def test_a_turn_announces_its_session_and_answers():
    """system/init with session_id is what makes the next turn resume (the recycle lesson)."""
    out, _ = _run([
        _ev("step_start", part={"type": "step-start"}),
        _ev("text", part={"type": "text", "text": "PROBE-OK", "time": {"start": 1, "end": 2}}),
        _ev("step_finish", part={"type": "step-finish", "reason": "stop", "cost": 0,
                                 "tokens": {"total": 118, "input": 100, "output": 7, "reasoning": 0,
                                            "cache": {"read": 11, "write": 0}}}),
    ])
    init = out[0]
    assert init["type"] == "system" and init["subtype"] == "init" and init["session_id"] == SID
    res = _result(out)
    assert res["is_error"] is False and res["result"] == "PROBE-OK"
    assert res["usage"] == {"input_tokens": 100, "output_tokens": 7,
                            "cache_read_tokens": 11, "cache_write_tokens": 0}


def test_a_provider_401_fails_the_turn_with_the_providers_sentence():
    """The exact line 7.8.1 printed for a 401 from the stub."""
    err = {"name": "APIError", "data": {"message": "Incorrect API key provided: sk-bad. (stub)",
                                        "statusCode": 401, "isRetryable": False}}
    out, _ = _run([_ev("error", error=err)], rc=1)
    res = _result(out)
    assert res["is_error"] is True
    assert res["result"] == "Incorrect API key provided: sk-bad. (stub)"
    assert not any(e.get("type") == "assistant" for e in out), "a failure is not rendered as an answer"


def test_an_empty_run_is_a_failure_even_though_the_error_is_a_string():
    msg = "run ended without an assistant message; the model returned no output"
    out, _ = _run([_ev("step_start", part={"type": "step-start"}), _ev("error", error=msg)], rc=1)
    res = _result(out)
    assert res["is_error"] is True and res["result"] == msg


def test_an_answer_that_mentions_an_error_is_still_an_answer():
    """Kilo reports provider failures structurally, so no text prefix may be read as one: a coding
    agent writes 'Error: ...' about its own work all the time."""
    txt = "Error: the test failed because `x` was None. I fixed it in main.py."
    out, _ = _run([_ev("text", part={"type": "text", "text": txt, "time": {"start": 1, "end": 2}})])
    res = _result(out)
    assert res["is_error"] is False and res["result"] == txt


def test_a_silent_nonzero_exit_names_kilo_not_opencode():
    res = _result(_run([], rc=1)[0])
    assert res["is_error"] is True and res["result"] == "kilo exited 1 without reporting an error"
    # and opencode's own message is unchanged by the shared code
    oc = server._opencode_eof({"final": ""}, 1)[0]
    assert oc["result"] == "opencode exited 1 without reporting an error"


def test_the_run_loop_finds_kilos_eof():
    assert getattr(server.BACKENDS["kilo"]["normalize"], "eof", None) is _kilo_eof


def test_tool_calls_render_as_tool_use_and_result():
    part = {"id": "prt_1", "type": "tool", "tool": "bash",
            "state": {"status": "completed", "input": {"command": "ls"}, "output": "a.txt\n",
                      "time": {"start": 1790471497000, "end": 1790471498000}}}
    out, _ = _run([_ev("tool_use", part=part)])
    call = next(e for e in out if e["type"] == "assistant")
    assert call["message"]["content"][0] == {"type": "tool_use", "id": "prt_1", "name": "bash",
                                             "input": {"command": "ls"}}
    res = next(e for e in out if e["type"] == "user")
    assert res["message"]["content"][0]["content"] == "a.txt\n"


# ── the builder ───────────────────────────────────────────────────────────────────────────────

def _build(auth=None, provider="openai-api", **kw):
    d = tempfile.mkdtemp()
    env = {"HOME": f"{d}/.harness/home"}
    auth = auth or Auth(api_key="sk-real", base_url="https://gateway.example/v1")
    cmd = _build_kilo(provider, auth, "gpt-5.4", "do it", d, env, **kw)
    cfg = json.loads(pathlib.Path(d, ".harness", "kilo.json").read_text())
    return cmd, cfg, env, d


def test_argv_is_a_headless_json_run_with_the_measured_flags():
    cmd, _, _, _ = _build()
    assert cmd[:6] == ["kilo", "run", "--format", "json", "--model", "hr/gpt-5.4"]
    for flag in ("--auto", "--pure", "--thinking"):
        assert flag in cmd
    assert cmd[-1] == "do it"


def test_a_prompt_that_looks_like_a_flag_is_not_read_as_one():
    d = tempfile.mkdtemp()
    cmd = _build_kilo("openai-api", Auth(api_key="k", base_url="https://g.example/v1"), "gpt-5.4",
                      "--version", d, {"HOME": d})
    assert cmd[-2:] == ["--", "--version"]


def test_the_real_key_never_reaches_the_sandbox():
    """OpenAI-shape turns ride the loopback relay: the CLI gets a per-turn placeholder, and the
    config names the variable rather than holding a value."""
    _, cfg, env, d = _build()
    assert env["HR_KILO_KEY"].startswith("hr-relay-")
    assert "sk-real" not in json.dumps(env)
    assert "sk-real" not in pathlib.Path(d, ".harness", "kilo.json").read_text()
    assert cfg["provider"]["hr"]["options"]["apiKey"] == "{env:HR_KILO_KEY}"
    assert cfg["provider"]["hr"]["options"]["baseURL"].startswith("http://127.0.0.1:")


def test_the_relay_token_is_in_env_where_served_model_and_usage_are_found():
    """checklist #19: _relay_served_model/_relay_usage look the route up by the bearer in ENV."""
    _, _, env, _ = _build()
    tok = env["HR_KILO_KEY"]
    assert tok in server._HERMES_RELAY["routes"]
    server._HERMES_RELAY["routes"][tok][2]["served_model"] = "openai/gpt-5.4"
    server._HERMES_RELAY["routes"][tok][2]["usage"] = {"input_tokens": 5}
    assert server._relay_served_model(env) == "openai/gpt-5.4"
    assert server._relay_usage(env) == {"input_tokens": 5}


def test_a_claude_id_on_an_aggregator_rides_the_relay():
    """The observability defect this fixes, pinned. opencode sends a claude id on an aggregator
    through @ai-sdk/anthropic, which cannot ride the relay (route lookup is by the placeholder
    BEARER; a Messages client sends x-api-key), and the turn then records NO served model: measured
    2026-09-27/28 on integration:vercel, one session, gpt-5.4-mini -> 'openai/gpt-5.4-mini' and
    claude-haiku-4.5 -> None. Through the relay the same id records
    'anthropic/claude-haiku-4.5' (measured 2026-09-28, same rig)."""
    for model in ("claude-haiku-4.5", "claude-opus-5.5", "anthropic/claude-fable-5"):
        assert _kilo_npm(Auth(), model, "tokenrouter") == "@ai-sdk/openai-compatible", model
    _, cfg, env, _ = _build(provider="tokenrouter",
                            auth=Auth(provider="tokenrouter", api_key="sk-real",
                                      base_url="https://gateway.example/v1"))
    assert cfg["provider"]["hr"]["options"]["baseURL"].startswith("http://127.0.0.1:")
    assert env["HR_KILO_KEY"].startswith("hr-relay-")
    assert server._relay_served_model(env) == ""      # the route exists; nothing has answered yet


def test_only_a_direct_anthropic_connection_keeps_messages():
    """A direct Anthropic endpoint speaks nothing else, and the relay cannot front it until it
    speaks x-api-key upstream (the general fix, proposed in the PR body, not done here)."""
    assert _kilo_npm(Auth(), "claude-haiku-4.5", "anthropic") == "@ai-sdk/anthropic"
    assert _kilo_npm(Auth(api_format="anthropic"), "claude-haiku-4.5", "tokenrouter") == "@ai-sdk/anthropic"
    # and everything else keeps opencode's choice
    assert _kilo_npm(Auth(), "gpt-5.4-mini", "tokenrouter") == "@ai-sdk/openai"          # /responses
    assert _kilo_npm(Auth(), "qwen3.8-max", "tokenrouter") == "@ai-sdk/openai-compatible"
    assert _kilo_npm(Auth(), "gpt-5.4", "azure") == "@ai-sdk/openai"
    assert _kilo_npm(Auth(api_format="openai"), "claude-haiku-4.5", "tokenrouter") == "@ai-sdk/openai-compatible"


def test_a_messages_shape_turn_rides_the_relay_too_and_the_cli_never_holds_the_key():
    """A direct Anthropic connection used to keep its own base, which put the real key in the CLI's
    environment where the agent's shell can read it. The relay reads x-api-key and sends Anthropic
    the key that way, so this turn gets a placeholder like every other."""
    auth = Auth(provider="anthropic", api_key="sk-ant", base_url="https://api.anthropic.com")
    _, cfg, env, _ = _build(auth=auth, provider="anthropic")
    assert cfg["provider"]["hr"]["npm"] == "@ai-sdk/anthropic"
    assert cfg["provider"]["hr"]["options"]["baseURL"].startswith("http://127.0.0.1:")
    assert cfg["provider"]["hr"]["options"]["baseURL"].endswith("/v1")
    assert env["HR_KILO_KEY"].startswith("hr-relay-") and "sk-ant" not in json.dumps(env)


def test_config_and_env_switch_off_every_phone_home_measured():
    """Default 7.8.1 made CONNECTs to us.i.posthog.com, models.dev and api.kilo.ai on a turn whose
    provider was local; these four switches took that to zero (proxy A/B, 2026-09-26)."""
    _, cfg, env, d = _build()
    assert cfg["enabled_providers"] == ["hr"]
    assert env["KILO_TELEMETRY_LEVEL"] == "off"
    assert env["KILO_DISABLE_MODELS_FETCH"] == "1"
    for k in ("KILO_DISABLE_AUTOUPDATE", "KILO_DISABLE_SESSION_INGEST", "KILO_NO_DAEMON",
              "KILO_DISABLE_CLAUDE_CODE"):
        assert env[k] == "1", k
    assert cfg["snapshot"] is False
    assert env["KILO_CONFIG"] == f"{d}/.harness/kilo.json"
    assert not pathlib.Path(d, "kilo.json").exists(), "config at the root is handed back as a deliverable"


def test_scheduling_tools_are_always_denied():
    _, cfg, _, _ = _build()
    for t in ("schedule_wakeup", "cancel_wakeup", "cron_create", "cron_delete", "cron_list", "goal"):
        assert cfg["permission"][t] == "deny", t


def test_write_and_apply_patch_are_withheld_through_edit():
    """Measured: deny `write` left write AND apply_patch in the request; deny `edit` removed edit,
    write and apply_patch. So the only honest translation of either is the edit key."""
    assert _kilo_denies(["write"])["edit"] == "deny"
    assert _kilo_denies(["apply_patch"])["edit"] == "deny"
    assert "write" not in _kilo_denies(["write"])


def test_withholding_the_shell_withholds_every_door_to_it():
    """background_process takes a `command` and runs it: bash off must mean both are off.

    MEASURED both ways on a live instance (2026-09-28, gpt-5.4-mini, vercel), with an oracle no
    answer can fake — a file whose content is a stamp that exists only in the turn's shell
    environment: with bash allowed, `background_process` action monitor ran the command and wrote
    the stamp; with bash disabled, four prompts that pushed for a shell (plain, via
    background_process, via a subagent, and a subagent the model was ordered to use) produced no
    stamp anywhere. A subagent DID create an empty proof.txt with apply_patch, which is why the
    oracle is the stamp and not the file."""
    assert _kilo_denies(["bash"])["background_process"] == "deny"
    assert "background_process" not in _kilo_denies(["webfetch"])


def test_unknown_tool_names_are_dropped_not_stored():
    out = _kilo_denies(["bash (Bash)", "not_a_tool", "WebFetch"])
    assert out["bash"] == "deny" and out["webfetch"] == "deny"
    assert "not_a_tool" not in out


# The gateway's _BASE_CATALOG["kilo"] tool ids; gateway/tests/test_kilo_catalog.py pins the same
# list from the other side, so neither can drift alone.
KILO_CATALOG_TOOLS = ["bash", "read", "edit", "glob", "grep", "webfetch", "task", "todowrite", "skill",
                      "background_process", "kilo_local_recall", "board_post", "board_read", "link_pr",
                      "agent_manager_models"]


def test_every_catalog_tool_is_one_the_runner_can_deny():
    """A catalog switch that matches no permission key would report a tool as off and disable
    nothing (registration point 9)."""
    for tid in KILO_CATALOG_TOOLS:
        assert _kilo_denies([tid]).get(tid) == "deny", tid


def test_mcp_and_skills_use_the_released_shapes():
    _, cfg, _, d = _build(mcp_servers=[{"name": "docs", "url": "https://mcp.example/mcp"},
                                       {"name": "fs", "command": "npx", "args": ["-y", "srv"]}],
                          skills_dir="/ws/.harness/skills")
    assert cfg["mcp"]["docs"] == {"type": "remote", "url": "https://mcp.example/mcp", "oauth": False}
    assert cfg["mcp"]["fs"] == {"type": "local", "command": ["npx", "-y", "srv"]}
    assert cfg["skills"] == {"paths": ["/ws/.harness/skills"]}


def test_instructions_go_to_agents_md():
    assert _agent_doc_path("/ws", "kilo").name == "AGENTS.md"


def test_skills_land_under_harness():
    d = tempfile.mkdtemp()
    got = server._write_skills(d, [{"name": "demo", "files": [{"path": "SKILL.md",
                                                            "content": "---\nname: demo\n---\nhi"}]}],
                               backend="kilo")
    assert got and pathlib.Path(d, ".harness", "skills", "demo", "SKILL.md").exists()


# ── resume: ask the store ─────────────────────────────────────────────────────────────────────

_SCHEMA = ("CREATE TABLE session (id text PRIMARY KEY, project_id text NOT NULL, parent_id text, "
           "slug text NOT NULL, directory text NOT NULL, title text NOT NULL, version text NOT NULL, "
           "time_created integer NOT NULL, time_updated integer NOT NULL)")


def _db(home: pathlib.Path, rows=(), wal=False):
    p = home / ".local" / "share" / "kilo"
    p.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p / "kilo.db")
    if wal:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
    db.execute(_SCHEMA)
    for sid, directory in rows:
        db.execute("INSERT INTO session VALUES (?, 'p', NULL, 's', ?, 't', '7.8.1', 0, 0)", (sid, directory))
    db.commit()
    return db


def test_a_session_in_the_database_is_resumed(tmp_path):
    db = _db(tmp_path, [(SID, "/data/workspaces/x")], wal=True)   # writer still open: rows in the WAL
    try:
        assert _kilo_has_session({"HOME": str(tmp_path)}, SID)
        cmd = _build_kilo("openai-api", Auth(api_key="k", base_url="https://g.example/v1"), "gpt-5.4",
                          "again", str(tmp_path), {"HOME": str(tmp_path)}, resume_session_id=SID)
        assert cmd[cmd.index("--session") + 1] == SID
        assert _resume_lost("kilo", cmd, SID) is None
    finally:
        db.close()


def test_an_id_that_only_appears_in_another_column_is_not_a_session(tmp_path):
    """The goose lesson: a byte search would match the id inside a path. The query cannot."""
    _db(tmp_path, [("ses_other", f"/data/workspaces/{SID}")]).close()
    assert not _kilo_has_session({"HOME": str(tmp_path)}, SID)


def test_a_lost_session_starts_fresh_and_says_so(tmp_path):
    _db(tmp_path).close()
    cmd = _build_kilo("openai-api", Auth(api_key="k", base_url="https://g.example/v1"), "gpt-5.4",
                      "again", str(tmp_path), {"HOME": str(tmp_path)}, resume_session_id=SID)
    assert "--session" not in cmd
    assert _resume_lost("kilo", cmd, SID) == SID


def test_no_database_is_no_session(tmp_path):
    assert not _kilo_has_session({"HOME": str(tmp_path)}, SID)
    assert not _kilo_has_session({}, SID)


# ── the relay answers an unreachable upstream instead of dropping the socket ─────────────────

def test_relay_answers_502_when_the_upstream_cannot_be_reached():
    """Measured on 7.8.1: a dropped connection sends Kilo into its offline loop and the turn never
    ends. The relay must turn "cannot connect" into an HTTP error the CLI reports."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()   # nothing listens here now
    base, tok = server._hermes_relay_route(f"http://127.0.0.1:{dead}/v1", "sk-x")
    req = urllib.request.Request(base + "/chat/completions", method="POST",
                                 data=b'{"model":"m","messages":[]}',
                                 headers={"authorization": f"Bearer {tok}",
                                          "content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
        raise AssertionError("expected an HTTP error")
    except urllib.error.HTTPError as e:
        assert e.code == 502
        assert b"the provider did not answer" in e.read()


def test_the_per_turn_config_files_that_carry_mcp_credentials_never_travel():
    """kilo.json holds each MCP server's Authorization header. It is rewritten every turn, so it is
    out of the checkpoint tarball and out of the workspace repo, as are opencode's config, Claude
    Code's --mcp-config file and the bridge launchers, which had the same hole."""
    import subprocess, tempfile, pathlib
    for path in ("./.harness/kilo.json", "./.harness/opencode.json", "./.harness/mcp.json",
                 "./.harness/mcp-bridge"):
        assert path in server.CHECKPOINT_EXCLUDE, path
    ws = tempfile.mkdtemp()
    server._git_ensure(ws)
    hd = pathlib.Path(ws, ".harness"); (hd / "mcp-bridge").mkdir(parents=True)
    for rel in ("kilo.json", "opencode.json", "mcp.json", "mcp-bridge/x.sh"):
        (hd / rel).write_text("Authorization: Bearer secret")
    out = subprocess.run(["git", "-C", ws, "status", "--porcelain", "-uall"], capture_output=True, text=True).stdout
    assert ".harness/" not in out, out
    # ...and a session that tracked one before the rule lets go of it on the next turn
    subprocess.run(["git", "-C", ws, "add", "-f", ".harness/kilo.json"], check=True)
    server._git_ensure(ws)
    assert subprocess.run(["git", "-C", ws, "ls-files", "--", ".harness"], capture_output=True, text=True).stdout == ""
