"""The cheetahclaws backend (SAIL-Research-Lab/cheetahclaws, PyPI `cheetahclaws`, Apache-2.0, 3.5.88).

What these pin, each measured on the pinned version before it was written down:

  the provider failures `cheetahclaws -p` prints and still exits 0 on — an unreachable endpoint, a bad
      key and a 429 — end the turn FAILED with the CLI's own sentence as the reason; the verdict is
      the history's shape (no assistant message came back), never a match on prose
  the CLI's retry/failure notices are not rendered as the answer
  the live stream: every event is re-emitted as the loop yields it (text deltas, tool calls with the
      ids the session file carries)
  resume: the session is the CLI's own session_latest.json under the redirected HOME, loaded before
      the turn and written back after it; a follow-up whose file is gone is reported by _resume_lost
  a disabled tool is withheld from the tool schema the provider receives (`hard`), MCP tools by their
      bare or server.tool name, and AskUserQuestion always (nobody is at the terminal)
  the CLI reads CLAUDE.md only; skills go to the project-level .cheetahclaws/skills; the task tracker
      and that folder are CLI state, never produced files, and the tracker is never checkpointed
  the real key never reaches the CLI: it gets the loopback relay's address and a placeholder

Recorded fixtures (fixtures/cheetahclaws/) are the driver's own output against a stub endpoint on
3.5.88; the tests that run the driver itself skip where the package is not installed.
"""
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import cheetahclaws_driver as drv  # noqa: E402
import server  # noqa: E402
from server import (Auth, BACKENDS, CHECKPOINT_EXCLUDE, _PRODUCED_EXCLUDE_PREFIX,  # noqa: E402
                    _agent_doc_path, _build_cheetahclaws, _cheetahclaws_eof,
                    _cheetahclaws_to_claude, _resume_lost, _write_skills)

FX = pathlib.Path(__file__).parent / "fixtures" / "cheetahclaws"


def _lines(name: str) -> list[dict]:
    return [json.loads(x) for x in (FX / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def _normalise(lines: list[dict]) -> tuple[list[dict], dict]:
    state = {"model": "m", "final": ""}
    out: list[dict] = []
    for obj in lines:
        out += _cheetahclaws_to_claude(obj, state)
    return out, state


def _result(events: list[dict]) -> dict:
    return [e for e in events if e.get("type") == "result"][-1]


# ── provider failure: checklist item 6, measured on 3.5.88 ──
@pytest.mark.parametrize("fixture, prefix", [
    ("turn-unreachable.ndjson", "Failed — APIConnectionError: Connection error."),
    ("turn-401.ndjson", "Failed — AuthenticationError: Error code: 401"),
    ("turn-429.ndjson", "Failed — RateLimitError: Error code: 429"),
    ("turn-timeout.ndjson", "Failed — APITimeoutError: Request timed out."),
])
def test_a_provider_failure_fails_the_turn_with_the_clis_own_sentence(fixture, prefix):
    events, state = _normalise(_lines(fixture))
    res = _result(events)
    assert res["subtype"] == "error" and res["is_error"] is True
    assert res["result"].startswith(prefix)
    assert server._status_from_result(res, 0) == "failed"      # the CLI exits 0 on every one of these
    # the retry ladder and the failure are notices, not the answer
    assert not [e for e in events if e.get("type") == "assistant"]
    assert state["final"] == ""


def test_the_pinned_failure_texts_are_recognised_as_the_clis_notices():
    """Verbatim from `cheetahclaws -p` against a stub (3.5.88, exit 0 each time)."""
    for text in ("\n[Failed — APIConnectionError: Connection error.. Hint: Network error — check your "
                 "internet connection or the API endpoint URL.]\n",
                 "\n[Failed — AuthenticationError: Error code: 401 - {'error': {'message': 'Incorrect "
                 "API key provided: sk-bad. You can find your API key at https://pla.... Hint: Check your "
                 "API key: /config or set the appropriate env var (ANTHROPIC_API_KEY, OPENAI_API_KEY, "
                 "etc.)]\n",
                 "\n[Retry 1/3 after 6s — rate_limit: Error code: 429 - {'error': {'message': 'Rate "
                 "limit reached for requests', 'type': 'requests', 'param': None, 'code':...]\n",
                 "\n[Loop guard] Same tool call repeated 3 times — stopping to prevent a runaway loop.\n"):
        assert drv.is_notice(text), text
    assert not drv.is_notice("Hello from the model")
    assert not drv.is_notice("[Failed — this is the model quoting a log line]")   # no leading newline


def test_a_hint_that_names_the_clis_slash_commands_is_cut_from_the_reason():
    r = drv.failure_reason("[Failed — AuthenticationError: Error code: 401 - {...}. Hint: Check your "
                           "API key: /config or set the appropriate env var (OPENAI_API_KEY, etc.)]")
    assert r == "Failed — AuthenticationError: Error code: 401 - {...}."
    r = drv.failure_reason("[Failed — APIConnectionError: Connection error.. Hint: Network error — "
                           "check your internet connection or the API endpoint URL.]")
    assert r.endswith("check your internet connection or the API endpoint URL.")


def test_the_verdict_is_the_historys_shape_not_the_text():
    user = {"role": "user", "content": "hi"}
    # a model that WRITES a failure line is still an answer
    said = [user, {"role": "assistant", "content": "[Failed — AuthenticationError: quoted]"}]
    assert drv.verdict(said, 0, [], False)["ok"] is True
    # a call that never came back leaves the history on the user's message
    v = drv.verdict([user], 0, ["[Failed — APIConnectionError: Connection error.. Hint: x]"], False)
    assert v["ok"] is False and v["reason"].startswith("Failed — APIConnectionError")
    # or on a tool result, when the call after a tool failed
    tool = [user, {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "Bash", "input": {}}]},
            {"role": "tool", "tool_call_id": "1", "content": "x"}]
    assert drv.verdict(tool, 0, [], False)["ok"] is False
    # the loop guard's own message is the CLI stopping the model, not an answer
    lg = [user, {"role": "assistant", "content": "[Loop guard] Same tool call repeated 3 times — stopping."}]
    v = drv.verdict(lg, 0, [], False)
    assert v["ok"] is False and v["reason"].startswith("Loop guard")
    # a resumed history's earlier answer is not this turn's answer
    resumed = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "old answer"}, user]
    assert drv.verdict(resumed, 2, [], False)["ok"] is False


def test_the_step_budget_ends_the_turn_as_max_turns():
    events, _ = _normalise([{"m": "__hr_init", "p": {"session_id": "s"}},
                            {"m": "__hr_result", "p": {"ok": False, "subtype": "error_max_turns", "final": "",
                                                       "reason": "the operator's step budget was reached"}}])
    res = _result(events)
    assert res["subtype"] == "error_max_turns" and res["is_error"] is False
    assert server._status_from_result(res, 0) == "max_turns"


# ── the live stream ──
def test_the_recorded_turn_streams_calls_and_text_as_they_happen():
    events, state = _normalise(_lines("turn-tool.ndjson"))
    kinds = [(e["type"], (e.get("message") or {}).get("content", [{}])[0].get("type")) for e in events]
    assert kinds[0] == ("system", None) and events[0]["session_id"] == "426953bd"
    assert ("assistant", "tool_use") in kinds and ("user", "tool_result") in kinds
    use = next(e for e in events if e["type"] == "assistant" and e["message"]["content"][0]["type"] == "tool_use")
    res_ev = next(e for e in events if e["type"] == "user")
    # the id is the tool call's own, the one session_latest.json carries
    assert use["message"]["content"][0]["id"] == "call_1" == res_ev["message"]["content"][0]["tool_use_id"]
    assert use["message"]["content"][0]["name"] == "Bash"
    assert res_ev["message"]["content"][0]["content"] == "PROBE-OUT"
    texts = [e["message"]["content"][0]["text"] for e in events
             if e["type"] == "assistant" and e["message"]["content"][0]["type"] == "text"]
    assert texts == ["Hello ", "from ", "the stub."]          # three deltas, not one block at the end
    res = _result(events)
    assert res["subtype"] == "success" and res["result"] == "Hello from the stub." and res["usage"] == {}
    assert state["final"] == "Hello from the stub."


def test_a_refused_or_errored_tool_result_is_marked_as_an_error():
    out = _cheetahclaws_to_claude({"m": "tool_end", "p": {"id": "1", "name": "Bash", "result": "Denied: x",
                                                          "permitted": False}}, {})
    assert out[0]["message"]["content"][0]["is_error"] is True
    out = _cheetahclaws_to_claude({"m": "tool_end", "p": {"id": "1", "name": "Read",
                                                          "result": "Error: no such file", "permitted": True}}, {})
    assert out[0]["message"]["content"][0]["is_error"] is True


def test_tool_ids_are_paired_to_the_batch_the_model_asked_for():
    p = drv.Pairing()
    p.batch({"role": "assistant", "tool_calls": [{"id": "a", "name": "Read", "input": {}},
                                                 {"id": "b", "name": "Read", "input": {}},
                                                 {"id": "c", "name": "Bash", "input": {}}]})
    assert [p.start("Read", {}), p.start("Read", {}), p.start("Bash", {})] == ["a", "b", "c"]
    assert [p.end("Read"), p.end("Read"), p.end("Bash")] == ["a", "b", "c"]
    assert p.start("Write", {}).startswith("cc")                  # a start with no call gets its own id


def test_eof_speaks_only_when_the_driver_died_before_its_result():
    st = {"_cc_notices": ["[Failed — APIConnectionError: Connection error.. Hint: x]"]}
    ev = _cheetahclaws_eof(st, 1)
    assert ev[0]["is_error"] is True and ev[0]["result"].startswith("Failed — APIConnectionError")
    assert _cheetahclaws_eof({}, 137)[0]["is_error"] is True
    assert _cheetahclaws_to_claude.eof is _cheetahclaws_eof


# ── registration and the builder ──
def test_backend_is_registered():
    spec = BACKENDS["cheetahclaws"]
    assert spec["normalize"] is _cheetahclaws_to_claude
    assert set(spec["providers"]) == {"openai-api", "tokenrouter"}
    assert "cheetahclaws" in server._SESSION_PRESENT


def _build(**kw):
    d = tempfile.mkdtemp()
    env: dict = {}
    args = dict(provider="openai-api", auth=Auth(api_key="sk-real-key", base_url="https://api.example/v1"),
                model="some-model", prompt="hi", cwd=d, env=env)
    args.update(kw)
    cmd = _build_cheetahclaws(**args)
    return cmd, d, env, json.loads(cmd[2])


def test_the_real_key_never_reaches_the_cli():
    cmd, _, env, job = _build()
    assert env["CUSTOM_API_KEY"].startswith("hr-relay-") and env["CUSTOM_BASE_URL"].startswith("http://127.0.0.1:")
    assert "sk-real-key" not in json.dumps(env) and "sk-real-key" not in " ".join(cmd)
    assert cmd[0] == server.CHEETAHCLAWS_PYTHON and cmd[1].endswith("cheetahclaws_driver.py")
    assert job["model"] == "custom/some-model"      # the CLI's OpenAI-chat client, whatever the id


def test_an_unknown_provider_and_a_missing_base_url_are_refused():
    with pytest.raises(Exception, match="unknown cheetahclaws provider"):
        _build(provider="anthropic")
    with pytest.raises(Exception, match="needs a base_url"):
        _build(auth=Auth(api_key="k"))


def test_mcp_servers_are_written_where_the_cli_reads_them_and_cleared_when_gone():
    _, d, _, _ = _build(mcp_servers=[{"name": "probe", "url": "https://x/sse", "transport": "sse", "auth": "tok"},
                                     {"name": "local", "command": "python3", "args": ["s.py"]}])
    doc = json.loads(pathlib.Path(d, ".harness", "home", ".cheetahclaws", "mcp.json").read_text())
    assert doc["mcpServers"]["probe"] == {"type": "sse", "url": "https://x/sse",
                                          "headers": {"Authorization": "Bearer tok"}}
    assert doc["mcpServers"]["local"]["type"] == "stdio"
    # the next turn names none: the file is emptied, so a disabled server is not connected
    _build_cheetahclaws("openai-api", Auth(api_key="k", base_url="https://api.example/v1"), "m", "hi", d, {})
    doc = json.loads(pathlib.Path(d, ".harness", "home", ".cheetahclaws", "mcp.json").read_text())
    assert doc == {"mcpServers": {}}


def test_the_policy_and_the_budget_reach_the_driver():
    _, _, _, job = _build(tools_disabled=["Bash", "probe_sse"], max_turns=9)
    assert job["tools_disabled"] == ["Bash", "probe_sse"] and job["max_turns"] == 9


def test_disabled_names_withhold_mcp_tools_by_either_name_and_the_question_tool_always():
    reg = ["Bash", "Read", "AskUserQuestion", "mcp__probe__probe_sse", "mcp__probe__other", "mcp__db__query"]
    got = drv.disabled_names(["Bash", "probe_sse", "db.query"], reg)
    assert {"Bash", "mcp__probe__probe_sse", "mcp__db__query", "AskUserQuestion"} <= set(got)
    assert "mcp__probe__other" not in got and "Read" not in got
    assert "AskUserQuestion" in drv.disabled_names([], reg)
    assert {"ReadEmail", "SendEmail"} <= set(drv.disabled_names([], reg))


def test_a_tool_whose_optional_extra_is_not_installed_is_withheld(monkeypatch):
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "fitz" else real(name, *a))
    assert "ReadPDF" in drv.unavailable_tools() and "ReadPDF" in drv.disabled_names([], ["ReadPDF"])
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: object())
    assert drv.unavailable_tools() == []


# ── resume: checklist item 5 ──
def _seed_session(d: str) -> str:
    path = pathlib.Path(d, ".harness", "home", ".cheetahclaws", "sessions", "mr_sessions")
    path.mkdir(parents=True, exist_ok=True)
    (path / "session_latest.json").write_text((FX / "session_latest.json").read_text(encoding="utf-8"))
    return json.loads((FX / "session_latest.json").read_text(encoding="utf-8"))["session_id"]


def test_a_follow_up_resumes_from_the_recorded_session_file():
    d = tempfile.mkdtemp()
    sid = _seed_session(d)
    cmd, _, _, job = _build(cwd=d, resume_session_id=sid)
    assert job["session_id"] == sid
    assert _resume_lost("cheetahclaws", cmd, sid, d) is None


def test_a_follow_up_whose_session_is_gone_is_reported_lost():
    d = tempfile.mkdtemp()
    cmd, _, _, job = _build(cwd=d, resume_session_id="deadbeef")
    assert job["session_id"] == ""            # the driver starts a new conversation
    assert _resume_lost("cheetahclaws", cmd, "deadbeef", d) == "deadbeef"
    # a file that holds ANOTHER conversation is not this one
    _seed_session(d)
    assert _resume_lost("cheetahclaws", cmd, "deadbeef", d) == "deadbeef"
    # a first turn asks for nothing and loses nothing
    assert _resume_lost("cheetahclaws", cmd, None, d) is None


def test_the_driver_loads_only_the_session_it_was_asked_for():
    d = tempfile.mkdtemp()
    sid = _seed_session(d)
    path = drv.session_file(pathlib.Path(d, ".harness", "home"))
    assert drv.load_session(path, sid)["messages"][-1]["content"] == "Hello from the stub."
    assert drv.load_session(path, "other") is None and drv.load_session(path, "") is None


# ── hygiene: checklist items 3, 4 and 7 ──
def test_the_instruction_file_is_claude_md():
    assert _agent_doc_path("/w", "cheetahclaws").name == "CLAUDE.md"


def test_skills_land_in_the_project_level_folder_the_loader_reads_first():
    d = tempfile.mkdtemp()
    got = _write_skills(d, [{"name": "probe-skill", "files": [{"path": "SKILL.md", "content": "---\nname: probe-skill\n"
                                                                                               "description: d\n---\nbody"}]}],
                        "cheetahclaws")
    assert pathlib.Path(d, ".cheetahclaws", "skills", "probe-skill", "SKILL.md").is_file()
    assert got[0]["entry"] == ".cheetahclaws/skills/probe-skill/SKILL.md"


def test_the_clis_workspace_state_is_never_a_produced_file_and_the_tracker_never_travels():
    assert any(".cheetahclaws/skills/x/SKILL.md".startswith(p) for p in _PRODUCED_EXCLUDE_PREFIX)
    assert any(".cheetahclaws/tasks.json".startswith(p) for p in _PRODUCED_EXCLUDE_PREFIX)
    assert "./.cheetahclaws/tasks.json" in CHECKPOINT_EXCLUDE
    assert "./.harness/home/.cheetahclaws/mcp.json" in CHECKPOINT_EXCLUDE


# ── the driver itself, against a stub endpoint (needs the pinned package) ──
class _Stub(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list = []
    mode = "ok"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"object": "list", "data": [{"id": "stub-model", "object": "model"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        type(self).requests.append(req)
        if type(self).mode == "401":
            return self._send(401, {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error",
                                              "code": "invalid_api_key"}})
        base = {"id": "c", "object": "chat.completion.chunk", "model": "stub-model", "created": 0}
        if type(self).mode == "call_bash" and not any(m.get("role") == "tool" for m in req.get("messages", [])):
            # the model asks for a tool the harness withheld, the way a model that saw it in an
            # earlier turn's history would
            call = {"index": 0, "id": "call_x", "type": "function",
                    "function": {"name": "Bash", "arguments": json.dumps({"command": "echo pwned > PWNED.txt"})}}
            chunks = [{**base, "choices": [{"index": 0, "delta": {"tool_calls": [call]}, "finish_reason": None}]},
                      {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}]
            body = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
            return self._send(200, body, "text/event-stream")
        chunks = [{**base, "choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]}
                  for p in ("PONG-", "1")]
        chunks.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        body = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
        self._send(200, body, "text/event-stream")


@pytest.fixture
def stub():
    pytest.importorskip("cheetahclaws", reason="the pinned CheetahClaws lives in its own venv, not here")
    _Stub.requests = []
    _Stub.mode = "ok"
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _run_driver(ws: str, port: int, prompt: str, **job) -> list[dict]:
    home = pathlib.Path(ws, ".harness", "home")
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
           "CUSTOM_BASE_URL": f"http://127.0.0.1:{port}/v1", "CUSTOM_API_KEY": "hr-relay-placeholder"}
    out = subprocess.run([sys.executable, drv.__file__,
                          json.dumps({"cwd": ws, "model": "custom/stub-model", "prompt": prompt, **job})],
                         cwd=ws, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return [json.loads(x) for x in out.stdout.splitlines() if x.strip()]


def test_the_driver_streams_a_turn_and_resumes_it_on_the_next(stub):
    ws = tempfile.mkdtemp()
    first = _run_driver(ws, stub.server_address[1], "say PONG-1")
    assert first[0]["m"] == "__hr_init" and first[0]["p"]["resumed"] is False
    assert [x["p"]["text"] for x in first if x["m"] == "text"] == ["PONG-", "1"]
    assert first[-1]["m"] == "__hr_result" and first[-1]["p"]["ok"] is True and first[-1]["p"]["final"] == "PONG-1"
    sid = first[0]["p"]["session_id"]
    second = _run_driver(ws, stub.server_address[1], "what did you say?", session_id=sid)
    assert second[0]["p"] == {"session_id": sid, "resumed": True, "messages": 2}
    sent = _Stub.requests[-1]["messages"]
    assert [m["content"] for m in sent if m["role"] == "user"][-2:] == ["say PONG-1", "what did you say?"]


def test_the_driver_fails_a_turn_the_provider_refused(stub):
    _Stub.mode = "401"
    lines = _run_driver(tempfile.mkdtemp(), stub.server_address[1], "hi")
    res = lines[-1]["p"]
    assert res["ok"] is False and res["reason"].startswith("Failed — AuthenticationError: Error code: 401")
    assert "/config" not in res["reason"]
    assert not [x for x in lines if x["m"] == "text"]


def test_a_disabled_tool_is_not_in_the_schema_the_provider_receives(stub):
    _run_driver(tempfile.mkdtemp(), stub.server_address[1], "hi", tools_disabled=["Bash", "Write"])
    offered = {t["function"]["name"] for t in _Stub.requests[-1].get("tools") or []}
    assert offered and "Read" in offered
    assert not {"Bash", "Write", "AskUserQuestion"} & offered


def test_a_call_to_a_withheld_tool_is_refused_at_execution_too(stub):
    _Stub.mode = "call_bash"
    ws = tempfile.mkdtemp()
    lines = _run_driver(ws, stub.server_address[1], "hi", tools_disabled=["Bash"])
    end = next(x["p"] for x in lines if x["m"] == "tool_end")
    assert end["name"] == "Bash" and end["result"].startswith("Error: tool 'Bash' is not enabled")
    assert not pathlib.Path(ws, "PWNED.txt").exists()


def test_the_harness_instructions_reach_the_system_prompt_from_claude_md(stub):
    ws = tempfile.mkdtemp()
    pathlib.Path(ws, "CLAUDE.md").write_text("Always answer in the voice of PROBE-DOC-7.\n")
    pathlib.Path(ws, "AGENTS.md").write_text("Always answer in the voice of PROBE-AGENTS-9.\n")
    _run_driver(ws, stub.server_address[1], "hi")
    system = next(m["content"] for m in _Stub.requests[-1]["messages"] if m["role"] == "system")
    assert "PROBE-DOC-7" in system and "PROBE-AGENTS-9" not in system


# ── served model and usage: checklist item 5 ──
def test_the_relay_asks_for_stream_usage_on_this_route_only_and_counts_it():
    """The CLI's `custom/` client streams without stream_options (3.5.88), and an OpenAI-shaped
    provider then sends no usage at all, so the relay would have nothing to count. This route asks
    for it; a route that did not ask sends the body as the client wrote it."""
    import urllib.request
    seen: list = []

    class Upstream(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            seen.append(body)
            usage = ({"prompt_tokens": 40, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 30}}
                     if (body.get("stream_options") or {}).get("include_usage") else None)
            chunks = [{"id": "c", "object": "chat.completion.chunk", "model": "served-x",
                       "choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}]
            if usage:
                chunks.append({"id": "c", "object": "chat.completion.chunk", "model": "served-x",
                               "choices": [], "usage": usage})
            data = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            self.wfile.write(data)

    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    env: dict = {}
    other = None
    try:
        _build_cheetahclaws("openai-api", Auth(api_key="sk-real", base_url=f"http://127.0.0.1:{up.server_address[1]}/v1"),
                            "m", "hi", tempfile.mkdtemp(), env)
        base, tok = env["CUSTOM_BASE_URL"], env["CUSTOM_API_KEY"]
        other = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")[1]
        for bearer in (tok, other):
            body = json.dumps({"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode()
            req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                         headers={"authorization": f"Bearer {bearer}", "content-type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        assert seen[0]["stream_options"] == {"include_usage": True}
        assert "stream_options" not in seen[1]
        assert server._relay_usage(env) == {"input_tokens": 10, "output_tokens": 4, "cache_read_tokens": 30}
        assert server._relay_served_model(env) == "served-x"
    finally:
        up.shutdown()
        server._HERMES_RELAY["routes"].pop(env.get("CUSTOM_API_KEY"), None)
        server._HERMES_RELAY["routes"].pop(other, None)


def test_a_body_that_already_asks_or_does_not_stream_is_left_alone():
    same = json.dumps({"stream": True, "stream_options": {"include_usage": False}}).encode()
    assert server._request_stream_usage(same) == same
    plain = json.dumps({"stream": False}).encode()
    assert server._request_stream_usage(plain) == plain
    assert server._request_stream_usage(b"not json") == b"not json"


def test_an_mcp_server_that_did_not_connect_becomes_a_note_on_the_reply():
    out = _cheetahclaws_to_claude({"m": "mcp_unavailable", "p": {"servers": [{"name": "dead", "reason": "refused"}]}}, {})
    assert out == [{"type": "system", "subtype": "mcp_unavailable", "servers": [{"name": "dead", "reason": "refused"}]}]
    assert _cheetahclaws_to_claude({"m": "mcp_unavailable", "p": {"servers": []}}, {}) == []


# ── a provider that never answers: bounded, not an hour-long silent turn ──
def test_every_client_the_cli_builds_gets_a_timeout_and_no_retries_of_its_own():
    openai = pytest.importorskip("openai")
    before = openai.OpenAI
    try:
        drv.bound_provider_calls(7.0)
        c = openai.OpenAI(api_key="x", base_url="http://127.0.0.1:1/v1")
        assert c.timeout.read == 7.0 and c.timeout.connect == 30.0 and c.max_retries == 0
        drv.bound_provider_calls(9.0)                      # idempotent: not wrapped twice
        assert openai.OpenAI(api_key="x", base_url="http://127.0.0.1:1/v1").timeout.read == 7.0
    finally:
        openai.OpenAI = before


class _Hang(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-length", "11")
        self.end_headers()
        self.wfile.write(b'{"data":[]}')

    def do_POST(self):
        import time
        time.sleep(60)


def test_an_endpoint_that_accepts_and_never_answers_fails_the_turn_in_bounded_time():
    """Measured 2026-09-24 on 3.5.88 with HR_CHEETAHCLAWS_TIMEOUT=2: four attempts and the loop's
    2/4/8 s backoff, 23 s, ending on the CLI's own timeout sentence. Without the bound the SDK's
    600 s timeout and its own retries sat under the loop's (a live turn still running at 600 s)."""
    pytest.importorskip("cheetahclaws", reason="the pinned CheetahClaws lives in its own venv, not here")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hang)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ws = tempfile.mkdtemp()
        home = pathlib.Path(ws, ".harness", "home")
        home.mkdir(parents=True)
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "HR_CHEETAHCLAWS_TIMEOUT": "2",
               "CUSTOM_BASE_URL": f"http://127.0.0.1:{srv.server_address[1]}/v1", "CUSTOM_API_KEY": "hr-relay-placeholder"}
        out = subprocess.run([sys.executable, drv.__file__, json.dumps({"cwd": ws, "model": "custom/m", "prompt": "hi"})],
                             cwd=ws, env=env, capture_output=True, text=True, timeout=90)
        res = json.loads(out.stdout.splitlines()[-1])["p"]
        assert res["ok"] is False and res["reason"].startswith("Failed — APITimeoutError: Request timed out.")
        assert res["seconds"] < 60
    finally:
        srv.shutdown()
