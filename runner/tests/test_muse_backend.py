"""The muse backend: Meta's Muse Code, pinned to 1.4.0-R4161.1, driven by `muse exec --json`.

Everything asserted here was measured against Meta's Model API (2026-09-23..25), not read off the
docs: on 1.4.0-R4161.1, except the wire protocol and the 402 terminal, first seen on 1.3.0-R3401.1
(the wire re-confirmed on 1.4.0). Each test pins one thing that would otherwise fail SILENTLY:

  catalog at the root    the CLI's first request of every turn is GET /muse-code/models relative to
                         the HOST ROOT; Meta serves it only there (/v1/muse-code/models is a 404)
  Responses usage        input_tokens is GROSS with input_tokens_details.cached_tokens inside it, and
                         the stream carries it under response.completed's `response`
  observers              every turn is >= 3 model calls (answer + skill and verify reminders); the
                         CLI reports none of their usage anywhere, only the relay sees them
  unknown session id     `--session-id <unknown>` silently CREATES a session, so the builder may pass
                         the caller's id only when the store holds it
  failures               a provider refusal is a structured run.terminal.failed with a reason, and
                         the answer text is empty — never narrated as assistant prose
  a rejected key         fails at the catalog fetch BEFORE the run: no record at all, exit 1 and
                         one stderr line, which the run loop turns into the reason
  arguments              the JSONL names each tool call's tool and output but carries NO arguments
"""
import json
import pathlib
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import (Auth, BACKENDS, CHECKPOINT_EXCLUDE, _agent_doc_path, _build_muse,  # noqa: E402
                    _muse_eof, _muse_has_session, _muse_sessions_root, _muse_to_claude,
                    _relay_upstream_url, _resume_lost, _write_skills)

SID = "211d86aa-d59e-40ea-8d70-25046dde3846"
RUN = {"kind": "run", "id": "bf70c1e4-606c-419a-b081-0741c442aa93"}


def _argv(d=None, **kw):
    d = d or tempfile.mkdtemp()
    env: dict = {"XDG_CONFIG_HOME": "/elsewhere", "MUSE_HOME": "/elsewhere"}
    cmd = _build_muse("meta", Auth(api_key="LLM-real-key", base_url="https://api.meta.ai/v1"),
                      "muse-spark-1.3", "do it", d, env, **kw)
    return cmd, d, env


def _store(d, sid=SID):
    """A session as 1.3.0-R3401.1 lays it down: sessions/<yyyy>/<mm>/<dd>/<id>/session.jsonl."""
    p = _muse_sessions_root(pathlib.Path(d)) / "2026" / "09" / "25" / sid
    p.mkdir(parents=True)
    (p / "session.jsonl").write_text("{}\n")
    return p


def _rec(payload_type, payload, stream=None):
    return {"schema_version": 1, "stream": stream or {"kind": "session", "id": SID},
            "payload_type": payload_type, "payload": payload}


def _norm(recs, partial=False):
    state: dict = {"model": "muse-spark-1.3", "partial": partial}
    out = []
    for r in recs:
        out += _muse_to_claude(r, state)
    return out, state


# ── the argv and the environment ─────────────────────────────────────────────────
def test_argv_is_headless_trusted_and_the_prompt_is_last_behind_a_separator():
    cmd, _, _ = _argv()
    assert cmd[:3] == ["muse", "exec", "--json"]
    assert "--yolo" in cmd, "without trust the project AGENTS.md and skills are ignored"
    assert "--no-foreign-personal-context" in cmd
    assert cmd[cmd.index("--model") + 1] == "muse-spark-1.3"
    assert cmd[-2:] == ["--", "do it"], "a prompt that begins with '-' must not parse as a flag"


def test_the_key_never_rides_argv_and_the_relay_placeholder_rides_the_documented_variable():
    cmd, _, env = _argv()
    assert "LLM-real-key" not in " ".join(cmd) and "LLM-real-key" not in json.dumps(env)
    tok = env["META_API_KEY"]
    assert tok.startswith("hr-relay-"), "_relay_usage/_relay_served_model find the route by env"
    base = cmd[cmd.index("--base-url") + 1]
    assert base.startswith("http://127.0.0.1:") and base.endswith("/v1")
    assert rs._HERMES_RELAY["routes"][tok][:2] == ("https://api.meta.ai/v1", "LLM-real-key")


def test_nothing_redirects_settings_or_sessions_out_of_the_checkpointed_home():
    _, _, env = _argv()
    assert "XDG_CONFIG_HOME" not in env and "MUSE_HOME" not in env


def test_the_step_budget_reaches_the_cli():
    assert "--max-model-steps" not in _argv()[0]
    cmd, _, _ = _argv(max_turns=40)
    assert cmd[cmd.index("--max-model-steps") + 1] == "40"


@pytest.mark.parametrize("bad", ["openai-api", "tokenrouter", "anthropic"])
def test_only_metas_model_api_can_drive_it(bad):
    with pytest.raises(Exception) as e:
        _build_muse(bad, Auth(api_key="k", base_url="https://x/v1"), "m", "p", tempfile.mkdtemp(), {})
    assert "unknown muse provider" in str(e.value.detail)


def test_settings_file_is_valid_and_carries_the_declared_transports():
    d = tempfile.mkdtemp()
    _argv(d, mcp_servers=[{"name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp",
                           "headers": {"x-k": "v"}},
                          {"name": "local", "command": ["node", "srv.js"], "args": ["--x"],
                           "env": {"A": "1"}},
                          {"name": "legacy", "url": "https://old.example/sse", "transport": "sse"}])
    doc = json.loads((pathlib.Path(d) / ".harness/home/.config/muse/settings.json").read_text())
    assert doc["schema_version"] == 1, "a settings file without it fails every command"
    assert doc["telemetry"] == {"enabled": False}
    s = doc["mcp_servers"]
    assert s["deepwiki"] == {"transport": "streamable_http", "url": "https://mcp.deepwiki.com/mcp",
                             "headers": {"x-k": "v"}, "enabled": True, "mode": "optional"}
    assert s["local"] == {"transport": "stdio", "command": "node", "args": ["srv.js", "--x"],
                          "env": {"A": "1"}, "enabled": True, "mode": "optional"}
    assert "legacy" not in s, "Muse Code has no SSE transport; never dial one as the wrong protocol"


def test_a_servers_auth_becomes_its_authorization_header():
    d = tempfile.mkdtemp()
    _argv(d, mcp_servers=[{"name": "a", "url": "https://a.example/mcp", "auth": "tok"},
                          {"name": "b", "url": "https://b.example/mcp", "auth": "Bearer t2",
                           "headers": {"x-k": "v"}}])
    s = json.loads((pathlib.Path(d) / ".harness/home/.config/muse/settings.json").read_text())["mcp_servers"]
    assert s["a"]["headers"] == {"Authorization": "Bearer tok"}
    assert s["b"]["headers"] == {"Authorization": "Bearer t2", "x-k": "v"}


def test_an_sse_server_reaches_muse_through_the_runners_bridge():
    """Muse Code has no SSE transport, so the runner hands it the stdio bridge, the codex/dsh/goose
    path: the server is not dropped, it arrives as a launcher Muse Code spawns."""
    d = tempfile.mkdtemp()
    servers = rs._sse_bridges(d, [{"name": "probe", "url": "https://probe.example/sse", "transport": "sse",
                                   "auth": "tok"}], "muse")
    assert servers[0]["command"].endswith(".harness/mcp-bridge/probe.sh") and "url" not in servers[0]
    _argv(d, mcp_servers=servers)
    s = json.loads((pathlib.Path(d) / ".harness/home/.config/muse/settings.json").read_text())["mcp_servers"]
    assert s["probe"]["transport"] == "stdio" and s["probe"]["command"] == servers[0]["command"]
    launcher = pathlib.Path(servers[0]["command"]).read_text()
    assert "HR_MCP_TRANSPORT=sse" in launcher and "tok" not in json.dumps(s), "credentials ride the launcher's env, not settings"


def test_a_server_removed_from_the_harness_is_gone_next_turn():
    d = tempfile.mkdtemp()
    _argv(d, mcp_servers=[{"name": "a", "url": "https://a.example/mcp"}])
    _argv(d)
    doc = json.loads((pathlib.Path(d) / ".harness/home/.config/muse/settings.json").read_text())
    assert doc["mcp_servers"] == {}


# ── resume ───────────────────────────────────────────────────────────────────────
def test_a_new_conversation_gets_a_fresh_uuid():
    cmd, _, _ = _argv()
    sid = cmd[cmd.index("--session-id") + 1]
    assert rs._MUSE_SESSION_ID_RE.match(sid)


def test_a_stored_session_is_continued_under_its_own_id():
    d = tempfile.mkdtemp()
    _store(d)
    assert _muse_has_session(pathlib.Path(d), SID)
    cmd, _, _ = _argv(d, resume_session_id=SID)
    assert cmd[cmd.index("--session-id") + 1] == SID
    assert _resume_lost("muse", cmd, SID, d) is None


def test_an_id_the_store_does_not_hold_starts_fresh_and_says_the_history_was_lost():
    """The CLI would CREATE a session under the unknown id and answer from nothing, as a completed
    turn. The builder mints a new one instead, and _resume_lost names the id that was lost."""
    d = tempfile.mkdtemp()
    cmd, _, _ = _argv(d, resume_session_id=SID)
    assert cmd[cmd.index("--session-id") + 1] != SID
    assert _resume_lost("muse", cmd, SID, d) == SID


@pytest.mark.parametrize("bad", ["../../etc", "*", "", "not-a-uuid", SID + "/x"])
def test_the_store_lookup_matches_an_exact_uuid_only(bad):
    d = tempfile.mkdtemp()
    _store(d)
    assert not _muse_has_session(pathlib.Path(d), bad)


def test_a_session_directory_without_its_log_is_not_a_conversation():
    d = tempfile.mkdtemp()
    p = _store(d)
    (p / "session.jsonl").unlink()
    assert not _muse_has_session(pathlib.Path(d), SID)


# ── the stream ───────────────────────────────────────────────────────────────────
def test_the_session_id_is_announced_once_from_the_session_stream():
    out, _ = _norm([_rec("runtime.command.accepted", {}),
                    _rec("run.model.configured", {"model_id": "muse-spark-1.3"})])
    inits = [e for e in out if e.get("subtype") == "init"]
    assert inits == [{"type": "system", "subtype": "init", "session_id": SID, "model": "muse-spark-1.3"}]


def test_a_completed_run_is_the_answer_and_a_success():
    out, state = _norm([_rec("run.output.delta", {"text": "4"}, RUN),
                        _rec("run.output.delta", {"text": "2"}, RUN),
                        _rec("run.terminal.completed", {"terminal": "completed", "text": "42",
                                                        "reason": None}, RUN)])
    texts = [c["text"] for e in out if e["type"] == "assistant" for c in e["message"]["content"]]
    assert texts == ["42"], "batch mode: one answer, not one block per delta"
    res = out[-1]
    assert res["type"] == "result" and not res["is_error"] and res["result"] == "42"
    assert res["usage"] == {}, "exec reports none; the run loop stamps the relay's count"
    assert state["final"] == "42"


def test_partial_mode_streams_the_deltas_and_does_not_render_the_answer_twice():
    out, _ = _norm([_rec("run.output.delta", {"text": "4"}, RUN),
                    _rec("run.output.delta", {"text": "2"}, RUN),
                    _rec("run.terminal.completed", {"terminal": "completed", "text": "42"}, RUN)],
                   partial=True)
    texts = [c["text"] for e in out if e["type"] == "assistant" for c in e["message"]["content"]]
    assert texts == ["4", "2"] and out[-1]["result"] == "42"


def test_a_provider_failure_is_a_failed_turn_with_the_providers_reason():
    reason = ("API error 402 [request_id=8fab4ad4-e41d-4c2e-a450-a025997e8cab]: Billing verification "
              "failed. Please check your payment method. (billing_error)")
    out, state = _norm([_rec("run.terminal.failed", {"terminal": "failed", "text": "",
                                                     "reason": reason}, RUN)])
    assert out == [{"type": "result", "subtype": "error", "is_error": True, "result": reason, "usage": {}}]
    assert not state.get("final")


def test_a_terminal_that_is_neither_completed_nor_failed_is_not_a_success():
    out, _ = _norm([_rec("run.terminal.cancelled", {"terminal": "cancelled"}, RUN)])
    assert out[-1]["is_error"] and "cancelled" in out[-1]["result"]


def test_a_rejected_key_fails_before_any_record_and_its_line_becomes_the_reason():
    """Measured on 1.4.0-R4161.1 with a bad key: no JSONL at all, exit 1, one stderr line. The run
    loop has collected that line; the empty result lets _failure_reason pick it."""
    line = ("failed to fetch model catalog: authentication failed: your API key from META_API_KEY "
            "was rejected — update or unset it")
    out, _ = _norm([])
    assert out == []
    res = _muse_eof({}, 1)[0]
    assert res["is_error"] and res["result"] == ""
    assert rs._failure_reason("", res["result"], line, 1) == line


def test_no_terminal_record_is_a_failure_whose_reason_the_cli_lines_supply():
    assert _muse_eof({}, 0) == [{"type": "result", "subtype": "error", "is_error": True,
                                 "result": "", "usage": {}}]
    assert BACKENDS["muse"]["normalize"].eof is _muse_eof


BASH_OUT = json.dumps({"chunk_id": "exec-1-1", "command": "cat hello.txt",
                       "description": "Display hello.txt contents", "exit_code": 0,
                       "terminal_status": "completed", "output": "hi"}, indent=2)


def test_a_tool_call_is_a_card_whose_input_is_only_what_the_result_states():
    out, _ = _norm([
        _rec("task.lifecycle.proposed", {"event": {"kind": "proposed", "task_kind": "tool.write_file"}}, RUN),
        _rec("tool.result", {"call_id": "call_w", "text": "wrote 2 bytes to /data/ws/hello.txt",
                             "edit_facts": {"tool_name": "write_file", "path": "hello.txt", "added": 1},
                             "correlation_facts": {"tool_name": "write_file", "outcome": "success"}}, RUN),
        _rec("tool.result", {"call_id": "call_b", "text": BASH_OUT,
                             "correlation_facts": {"tool_name": "bash", "outcome": "success"}}, RUN),
        _rec("tool.result", {"call_id": "call_s", "text": "3 matches",
                             "correlation_facts": {"tool_name": "search", "outcome": "success"}}, RUN),
    ])
    uses = [c for e in out if e["type"] == "assistant" for c in e["message"]["content"]
            if c["type"] == "tool_use"]
    assert [(u["id"], u["name"], u["input"]) for u in uses] == [
        ("call_w", "write_file", {"path": "hello.txt"}),
        ("call_b", "bash", {"command": "cat hello.txt", "description": "Display hello.txt contents"}),
        ("call_s", "search", {}),   # no argument the record states: nothing is guessed
    ]
    results = [c for e in out if e["type"] == "user" for c in e["message"]["content"]]
    assert [r["tool_use_id"] for r in results] == ["call_w", "call_b", "call_s"]
    # the card shows what the command printed, not Muse Code's envelope (chunk_id, byte counts, …)
    assert results[1]["content"] == "hi" and not any(r["is_error"] for r in results)
    assert results[0]["content"] == "wrote 2 bytes to /data/ws/hello.txt"


def test_a_failed_or_truncated_command_says_so_on_its_card():
    env = json.dumps({"chunk_id": "exec-1-1", "command": "false", "exit_code": 2, "output": "boom",
                      "truncated": True})
    out, _ = _norm([_rec("tool.result", {"call_id": "c", "text": env,
                                         "correlation_facts": {"tool_name": "bash", "outcome": "error"}}, RUN)])
    res = out[-1]["message"]["content"][0]
    assert res["content"] == "boom\n[exit code 2]\n[output truncated]" and res["is_error"]
    # an envelope that does not parse is shown as it came
    out, _ = _norm([_rec("tool.result", {"call_id": "d", "text": "not json",
                                         "correlation_facts": {"tool_name": "bash", "outcome": "success"}}, RUN)])
    assert out[-1]["message"]["content"][0]["content"] == "not json"


def test_a_skill_read_names_the_skill_it_read():
    txt = '<read-skill-result name="officecli" status="ok">\n<metadata>\npath: /ws/.harness/home/.agents/skills/officecli/SKILL.md'
    out, _ = _norm([_rec("tool.result", {"call_id": "k", "text": txt,
                                         "correlation_facts": {"tool_name": "read_skill", "outcome": "success"}}, RUN)])
    assert out[0]["message"]["content"][0]["input"] == {"name": "officecli"}
    assert out[1]["message"]["content"][0]["content"] == txt


def test_a_failed_tool_call_is_marked_as_one():
    out, _ = _norm([_rec("tool.result", {"call_id": "c", "text": "denied",
                                         "correlation_facts": {"tool_name": "bash", "outcome": "error"}}, RUN)])
    assert out[-1]["message"]["content"][0]["is_error"] is True


def test_runtime_bookkeeping_renders_nothing():
    out, _ = _norm([_rec("task.lifecycle.proposed", {"event": {"task_kind": "reminder.agent.skill-reminder"}}, RUN),
                    _rec("task.lifecycle.rejected", {"event": {"reason": "skip_if_running"}}, RUN),
                    _rec("session.workspace_branch.observed", {"record": {"vcs": "git"}})])
    assert [e for e in out if e.get("subtype") != "init"] == []


# ── the relay: the root-level catalog, and Responses usage ───────────────────────
def test_the_catalog_goes_beside_the_version_segment_and_everything_else_under_it():
    assert _relay_upstream_url("https://api.meta.ai/v1", "/muse-code/models") == "https://api.meta.ai/muse-code/models"
    assert _relay_upstream_url("https://api.meta.ai/v1/", "/responses") == "https://api.meta.ai/v1/responses"
    # through the hosted broker the base is /v1/llm: joined as usual, the broker applies the rule
    assert (_relay_upstream_url("https://hr.example/v1/llm", "/muse-code/models")
            == "https://hr.example/v1/llm/muse-code/models")
    assert _relay_upstream_url("https://up.example/v1", "/chat/completions") == "https://up.example/v1/chat/completions"


def test_responses_usage_is_netted_to_fresh_input():
    u = rs._usage_fields({"input_tokens": 31868, "input_tokens_details": {"cached_tokens": 26451},
                          "output_tokens": 1279, "output_tokens_details": {"reasoning_tokens": 900},
                          "total_tokens": 33147})
    assert u == {"input_tokens": 5417, "output_tokens": 1279, "cache_read_tokens": 26451}


def test_the_streamed_usage_is_found_under_response_completed():
    line = (b'data: {"type":"response.completed","response":{"id":"resp_1","model":"muse-spark-1.3",'
            b'"status":"completed","usage":{"input_tokens":18318,"input_tokens_details":{"cached_tokens":0},'
            b'"output_tokens":86,"output_tokens_details":{"reasoning_tokens":75},"total_tokens":18404}}}')
    assert rs._usage_in_sse_line(line) == {"input_tokens": 18318, "output_tokens": 86, "cache_read_tokens": 0}


def _sse(model, usage):
    ev = [{"type": "response.created", "response": {"id": "r", "model": model, "status": "in_progress",
                                                     "usage": None}},
          {"type": "response.output_text.delta", "delta": "hi"},
          {"type": "response.completed", "response": {"id": "r", "model": model, "status": "completed",
                                                       "usage": usage}}]
    return b"".join(b"event: " + e["type"].encode() + b"\ndata: " + json.dumps(e).encode() + b"\n\n" for e in ev)


def test_a_muse_turn_through_the_live_relay_counts_every_call_and_reads_the_served_model():
    """The catalog GET at the root, then three Responses calls (the answer and two observers), as
    one turn does. The relay must reach the root-level catalog, label the turn from an ANSWER and
    not from the listing, and sum all three calls' usage — the CLI reports only the first."""
    calls = [{"input_tokens": 18833, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 17},
             {"input_tokens": 9425, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 242},
             {"input_tokens": 3170, "input_tokens_details": {"cached_tokens": 1000}, "output_tokens": 289}]
    seen: list[str] = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, ctype, data):
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            seen.append("GET " + self.path)
            if self.path == "/muse-code/models":
                # a listing that names a model the turn will NOT run, to prove it labels nothing
                self._send(200, "application/json", json.dumps(
                    {"object": "list", "data": [{"id": "muse-spark-1.2", "model": "muse-spark-1.2"}]}).encode())
            else:
                self._send(404, "application/json", b"{}")

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            seen.append("POST " + self.path)
            assert self.headers.get("authorization") == "Bearer LLM-real"
            self._send(200, "text/event-stream", _sse("muse-spark-1.3-contributor", calls[len(seen) - 2]))

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    tok = ""
    try:
        base, tok = rs._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "LLM-real")
        root = base[: -len("/v1")]
        hdr = {"authorization": f"Bearer {tok}", "content-type": "application/json"}
        cat = json.loads(urllib.request.urlopen(urllib.request.Request(root + "/muse-code/models", headers=hdr),
                                                timeout=10).read())
        assert cat["data"][0]["id"] == "muse-spark-1.2"
        for _ in calls:
            body = json.dumps({"model": "muse-spark-1.3-contributor", "stream": True, "input": []}).encode()
            urllib.request.urlopen(urllib.request.Request(base + "/responses", data=body, method="POST",
                                                          headers=hdr), timeout=10).read()
        assert seen == ["GET /muse-code/models"] + ["POST /v1/responses"] * 3
        env = {"META_API_KEY": tok}
        assert rs._relay_served_model(env) == "muse-spark-1.3-contributor"
        assert rs._relay_usage(env) == {"input_tokens": 18833 + 9425 + 2170,
                                        "output_tokens": 17 + 242 + 289, "cache_read_tokens": 1000}
    finally:
        up.shutdown()
        rs._HERMES_RELAY["routes"].pop(tok, None)


# ── the rest of the wiring ───────────────────────────────────────────────────────
def test_registry_agent_doc_skills_and_checkpoint():
    assert BACKENDS["muse"]["providers"] == ["meta"]
    assert BACKENDS["muse"]["normalize"] is _muse_to_claude
    assert _agent_doc_path("/ws", "muse").name == "AGENTS.md"
    d = tempfile.mkdtemp()
    _write_skills(d, [{"name": "probe", "files": [{"path": "SKILL.md", "content": "---\nname: probe\n---\n"}]}],
                  backend="muse")
    assert (pathlib.Path(d) / ".harness/home/.agents/skills/probe/SKILL.md").is_file()
    assert "./.harness/home/.config/muse/auth.json" in CHECKPOINT_EXCLUDE
    assert "./.harness/home/.config/muse/settings.json" in CHECKPOINT_EXCLUDE, "it carries MCP auth headers"
    assert "./.harness/home/.local/share/muse/skills/bundled" in CHECKPOINT_EXCLUDE
    assert not any(e.rstrip("/").endswith("muse/sessions") or e.rstrip("/").endswith("share/muse")
                   for e in CHECKPOINT_EXCLUDE), "sessions must travel or a resume dies with the sandbox"


# ── cancel ───────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not pathlib.Path("/proc/self/stat").exists(), reason="needs /proc (Linux)")
def test_cancel_kills_a_command_the_cli_put_in_its_own_session():
    """Muse Code runs each shell command under setsid, outside the CLI's process group. The group
    kill alone left `sleep 300 && echo … > slept.txt` alive as an orphan of pid 1 after Stop
    (measured in the image, 2026-09-25); the descendants must go first, while the tree still links
    them to the CLI."""
    import os
    import subprocess
    import time
    cli = subprocess.Popen(["sh", "-c", "setsid sh -c 'sleep 60' & wait"], start_new_session=True)
    for _ in range(50):
        kids = rs._descendant_pids(cli.pid)
        if any(pathlib.Path(f"/proc/{p}/cmdline").read_bytes().startswith(b"sleep") for p in kids
               if pathlib.Path(f"/proc/{p}/cmdline").exists()):
            break
        time.sleep(0.1)
    sleeper = [p for p in rs._descendant_pids(cli.pid)
               if pathlib.Path(f"/proc/{p}/cmdline").read_bytes().startswith(b"sleep")]
    assert sleeper, "the fixture did not start its detached command"
    assert os.getsid(sleeper[0]) != os.getsid(cli.pid), "the command must be outside the CLI's session"
    rs._kill_proc_tree(cli)
    cli.wait(timeout=5)
    time.sleep(0.3)
    alive = pathlib.Path(f"/proc/{sleeper[0]}").exists() and \
        "Z" not in pathlib.Path(f"/proc/{sleeper[0]}/stat").read_text().split(")")[-1].split()[:1]
    assert not alive, "the detached command outlived the cancel"
