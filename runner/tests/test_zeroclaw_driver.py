"""runner/zeroclaw_driver.py and the zeroclaw backend in server.py (zeroclaw-labs/zeroclaw,
Apache-2.0, pinned to 0.8.5).

zeroclaw is not installed in the test environment (the entrypoint puts the binary on the data
volume), so a FAKE `zeroclaw acp` stands in for it: a script that speaks JSON-RPC over stdio and
answers each request with lines captured from the real 0.8.5 server (fixtures/zeroclaw/, recorded
against OpenRouter on 2026-10-13; the answer text of write-file.ndjson is shortened to DONE).

What each test pins is one thing that would otherwise be wrong SILENTLY:
  * a follow-up turn that starts a NEW conversation instead of resuming the stored one
  * a provider failure (a JSON-RPC error) reported as a turn that completed with no answer
  * a turn that hangs because zeroclaw asked a client question nobody answers
  * a provider key written into config.toml, or a relay that is not in the environment
  * the instruction file and skills written where zeroclaw never reads them
"""
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as srv  # noqa: E402

DRIVER = pathlib.Path(__file__).resolve().parents[1] / "zeroclaw_driver.py"
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "zeroclaw"

# The fake `zeroclaw`: `zeroclaw acp --config-dir <d>` reading requests off stdin. The scenario (a
# JSON file named by FAKE_ZC) says which session ids the store holds, what the prompt answers with
# (a fixture file whose response line carries "id":"PROMPT"), and whether to ask the client a
# question first. Every request is appended to the scenario's log so a test can read what was sent.
_FAKE = r'''
import json, sys
sc = json.load(open(sys.argv[-1]))
log = open(sc["log"], "a")
def out(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    req = json.loads(line)
    if "method" not in req:
        log.write(json.dumps({"answer": req}) + "\n"); log.flush(); continue
    log.write(json.dumps(req) + "\n"); log.flush()
    m, rid = req["method"], req["id"]
    if m == "initialize":
        o = json.loads(open(sc["init"]).read()); o["id"] = rid; out(o)
    elif m == "session/new":
        out({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "new-session-uuid", "workspaceDir": req["params"]["cwd"]}})
    elif m == "session/resume":
        if req["params"]["sessionId"] in sc.get("known", []):
            out({"jsonrpc": "2.0", "id": rid, "result": {}})
        else:
            out({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "Session not found: " + req["params"]["sessionId"]}})
    elif m == "session/prompt":
        if sc.get("ask"):
            out({"jsonrpc": "2.0", "id": 900, "method": "session/request_permission", "params": {}})
            log.write(json.dumps({"answer": json.loads(sys.stdin.readline())}) + "\n"); log.flush()   # hangs if none comes
        if sc.get("eof"):
            sys.exit(3)
        for l in open(sc["prompt"]):
            o = json.loads(l)
            if o.get("id") == "PROMPT":
                o["id"] = rid
            out(o)
'''


def _run(tmp: pathlib.Path, scenario: dict, resume: str = "") -> tuple[list[dict], list[dict], int]:
    fake = tmp / "fake_zeroclaw.py"
    fake.write_text(_FAKE)
    launcher = tmp / "zeroclaw"
    sc = {"log": str(tmp / "requests.log"), "init": str(FIX / "initialize.json"), **scenario}
    (tmp / "scenario.json").write_text(json.dumps(sc))
    launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {fake} \"$@\" {tmp / 'scenario.json'}\n")
    launcher.chmod(0o755)
    job = {"zeroclaw": str(launcher), "config_dir": str(tmp / "cfg"), "cwd": str(tmp),
           "model": "claude-haiku-4.5", "prompt": "write hello.txt", "resume_session_id": resume}
    p = subprocess.run([sys.executable, str(DRIVER), json.dumps(job)], capture_output=True, text=True,
                       timeout=30)
    events = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    sent = [json.loads(x) for x in (tmp / "requests.log").read_text().splitlines()] \
        if (tmp / "requests.log").exists() else []
    return events, sent, p.returncode


def test_a_turn_becomes_claude_stream_json():
    with tempfile.TemporaryDirectory() as d:
        events, sent, rc = _run(pathlib.Path(d), {"prompt": str(FIX / "write-file.ndjson")})
    assert rc == 0
    assert [r["method"] for r in sent] == ["initialize", "session/new", "session/prompt"]
    assert sent[1]["params"] == {"cwd": d, "agentAlias": "hr"}
    assert sent[2]["params"]["prompt"] == [{"type": "text", "text": "write hello.txt"}]
    init = events[0]
    assert init == {"type": "system", "subtype": "init", "session_id": "new-session-uuid", "model": "claude-haiku-4.5"}
    blocks = [b for e in events if e["type"] in ("assistant", "user") for b in e["message"]["content"]]
    tool_use = [b for b in blocks if b["type"] == "tool_use"]
    assert tool_use == [{"type": "tool_use", "id": "bb50e99c-0a6a-4d4b-b6b2-80c449003cbc", "name": "file_write",
                         "input": {"newText": "HELLO", "path": "hello.txt"}}]
    result = [b for b in blocks if b["type"] == "tool_result"]
    assert result == [{"type": "tool_result", "tool_use_id": "bb50e99c-0a6a-4d4b-b6b2-80c449003cbc",
                       "is_error": False, "content": "Written 5 bytes to hello.txt"}]
    # the final answer is the prompt's own `content`, not every chunk of the turn run together
    assert events[-1] == {"type": "result", "subtype": "success", "is_error": False, "result": "DONE", "usage": {}}


def test_a_follow_up_resumes_the_stored_session_rather_than_starting_another():
    with tempfile.TemporaryDirectory() as d:
        events, sent, rc = _run(pathlib.Path(d), {"prompt": str(FIX / "write-file.ndjson"),
                                                  "known": ["old-session-uuid"]}, resume="old-session-uuid")
    assert rc == 0
    assert [r["method"] for r in sent] == ["initialize", "session/resume", "session/prompt"]
    assert sent[2]["params"]["sessionId"] == "old-session-uuid"
    assert events[0]["session_id"] == "old-session-uuid"


def test_a_session_the_store_does_not_hold_starts_a_new_one():
    """zeroclaw answers -32000 "Session not found"; the turn still runs, on a new session, and
    server.py's _resume_lost (tested below) is what tells the person the history is gone."""
    with tempfile.TemporaryDirectory() as d:
        events, sent, rc = _run(pathlib.Path(d), {"prompt": str(FIX / "write-file.ndjson")}, resume="gone-uuid")
    assert rc == 0
    assert [r["method"] for r in sent] == ["initialize", "session/resume", "session/new", "session/prompt"]
    assert events[0]["session_id"] == "new-session-uuid"


def test_a_provider_failure_is_a_failed_turn_with_the_reason():
    with tempfile.TemporaryDirectory() as d:
        events, _, rc = _run(pathlib.Path(d), {"prompt": str(FIX / "provider-401.ndjson")})
    assert rc == 1
    assert events[-1]["is_error"] is True and events[-1]["subtype"] == "error"
    assert "rejected its credentials" in events[-1]["result"]


def test_a_stream_that_ends_without_an_answer_is_not_a_success():
    with tempfile.TemporaryDirectory() as d:
        events, _, rc = _run(pathlib.Path(d), {"prompt": str(FIX / "write-file.ndjson"), "eof": True})
    assert rc == 1
    assert events[-1] == {"type": "result", "subtype": "error", "is_error": True, "result": "", "usage": {}}


def test_a_question_from_the_agent_is_answered_rather_than_left_to_hang_the_turn():
    with tempfile.TemporaryDirectory() as d:
        events, sent, rc = _run(pathlib.Path(d), {"prompt": str(FIX / "write-file.ndjson"), "ask": True})
    assert rc == 0 and events[-1]["result"] == "DONE"
    answers = [r["answer"] for r in sent if "answer" in r]
    assert answers == [{"jsonrpc": "2.0", "id": 900, "result": {"outcome": {"outcome": "cancelled"}}}]


# ── server.py: the builder, the store lookup, where files land ─────────────────────────────────

def _build(tmp: str, **kw) -> tuple[list[str], dict, dict]:
    env = {"PATH": "/usr/bin:/data/agent-tools/bin", "STAMP_NONCE": "n-1"}
    cmd = srv._build_zeroclaw("openrouter", srv.Auth(api_key="sk-or-real", base_url="https://openrouter.ai/api/v1"),
                              "anthropic/claude-haiku-4.5", "hi", tmp, env, **kw)
    cfg = tomllib.loads((pathlib.Path(tmp) / ".harness" / "zeroclaw" / "config.toml").read_text())
    return cmd, env, cfg


def test_the_key_rides_the_relay_and_is_never_written_to_the_config():
    with tempfile.TemporaryDirectory() as d:
        cmd, env, cfg = _build(d)
        text = (pathlib.Path(d) / ".harness" / "zeroclaw" / "config.toml").read_text()
    assert "sk-or-real" not in text and "sk-or-real" not in json.dumps(cmd)
    tok = env[srv._ZEROCLAW_KEY_ENV]
    assert tok.startswith("hr-relay-") and tok in srv._HERMES_RELAY["routes"]
    assert cfg["providers"]["models"]["custom"]["hr"]["uri"].startswith("http://127.0.0.1:")
    assert cfg["providers"]["models"]["custom"]["hr"]["model"] == "anthropic/claude-haiku-4.5"
    # without it a custom endpoint gets prompt-guided tools: calls written as text, arguments lost
    assert cfg["providers"]["models"]["custom"]["hr"]["native_tools"] is True
    assert srv._relay_served_model(env) == ""   # found by the placeholder in env; nothing served yet
    job = json.loads(cmd[2])
    assert cmd[:2] == [sys.executable, srv.ZEROCLAW_DRIVER]
    assert job["config_dir"] == str(pathlib.Path(d) / ".harness" / "zeroclaw") and job["cwd"] == d


def test_the_risk_profile_runs_unattended_and_withholds_what_it_must():
    with tempfile.TemporaryDirectory() as d:
        _, _, cfg = _build(d, tools_disabled=["web_fetch (Web Fetch)"], max_turns=7)
    rp = cfg["risk_profiles"]["hr"]
    assert rp["level"] == "full" and rp["allowed_commands"] == ["*"] and rp["block_high_risk_commands"] is False
    assert set(rp["excluded_tools"]) == {"web_fetch", *srv._ZEROCLAW_NEVER}
    assert cfg["runtime_profiles"]["hr"]["max_tool_iterations"] == 7
    # the shell gets the variables it needs by name: PATH and the harness's own
    assert "PATH" in rp["shell_env_passthrough"]
    assert cfg["agents"]["hr"]["workspace"]["path"].endswith(".harness/zeroclaw/agent")
    assert "mcp" not in cfg and "acp_enable_mcp" not in cfg["agents"]["hr"]


def test_the_harness_variables_reach_the_shell_by_name():
    with tempfile.TemporaryDirectory() as d:
        _, _, cfg = _build(d, caller_keys=["STAMP_NONCE"])
    assert "STAMP_NONCE" in cfg["risk_profiles"]["hr"]["shell_env_passthrough"]


def test_mcp_needs_all_three_switches_or_no_server_connects():
    servers = [{"name": "probe", "command": ["node", "srv.js"], "args": ["--x"], "env": {"TOKEN": "t"}},
               {"name": "remote", "url": "https://mcp.example/sse", "headers": {"Authorization": "Bearer b"}}]
    with tempfile.TemporaryDirectory() as d:
        _, _, cfg = _build(d, mcp_servers=servers)
    agent = cfg["agents"]["hr"]
    assert agent["acp_enable_mcp"] is True and agent["mcp_bundles"] == ["hr"]
    assert cfg["mcp_bundles"]["hr"]["servers"] == ["probe", "remote"]
    stdio, sse = cfg["mcp"]["servers"]
    assert stdio == {"name": "probe", "transport": "stdio", "command": "node", "args": ["srv.js", "--x"],
                     "env": {"TOKEN": "t"}}
    assert sse["transport"] == "sse" and sse["url"] == "https://mcp.example/sse"
    # a file that can hold a server's bearer token never rides the checkpoint
    assert "./.harness/zeroclaw/config.toml" in srv.CHECKPOINT_EXCLUDE


def test_a_lost_conversation_is_reported_and_a_kept_one_is_not():
    with tempfile.TemporaryDirectory() as d:
        db = pathlib.Path(d) / ".harness" / "zeroclaw" / "data" / "sessions" / "acp-sessions.db"
        assert srv._resume_lost("zeroclaw", [], "abc", d) == "abc"   # no store at all
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE acp_sessions (id INTEGER PRIMARY KEY, session_uuid TEXT NOT NULL UNIQUE)")
        con.execute("INSERT INTO acp_sessions (session_uuid) VALUES ('abc')")
        con.commit(); con.close()
        assert srv._resume_lost("zeroclaw", [], "abc", d) is None
        assert srv._resume_lost("zeroclaw", [], "other", d) == "other"


def test_instructions_and_skills_land_where_zeroclaw_reads_them():
    with tempfile.TemporaryDirectory() as d:
        assert srv._agent_doc_path(d, "zeroclaw") == pathlib.Path(d, ".harness", "zeroclaw", "agent", "AGENTS.md")
        installed = srv._write_skills(d, [{"name": "probe-skill", "content": "# probe\n\nSay PROBE.\n"}],
                                      backend="zeroclaw")
        assert (pathlib.Path(d) / ".harness" / "zeroclaw" / "agent" / "skills" / "probe-skill" / "SKILL.md").is_file()
    assert installed


def test_the_backend_is_registered_with_the_passthrough_normaliser():
    spec = srv.BACKENDS["zeroclaw"]
    assert spec["normalize"] is srv._claude_passthrough
    assert set(spec["providers"]) == srv.ZEROCLAW_PROVIDERS
    assert not set(srv._ZEROCLAW_NEVER) & set(srv.ALL_ZEROCLAW_TOOLS)
