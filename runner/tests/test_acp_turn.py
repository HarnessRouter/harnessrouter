"""The streamed ACP turn the drivers share (acp_turn), and fast-agent's driver on it (2026-10-26).

Until 0.37.1 deepagents-code's driver held every update until session/prompt returned and fast-agent
ran as `go --quiet` with its record read from a file at the end, so both showed "Thinking" for the
whole turn and then every step at once. These pin the streamed shape, the terminal fast-agent's
shell runs through, and the fast-agent driver against a fake agent."""
import json
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import acp_turn as A  # noqa: E402
import fast_agent_driver as F  # noqa: E402

AGENT = pathlib.Path(__file__).resolve().parent / "fixtures" / "batch4" / "fake_acp_agent.py"


def _blocks(evs, kind):
    return [c for e in evs for c in (e.get("message") or {}).get("content") or [] if c.get("type") == kind]


# ── the translator ─────────────────────────────────────────────────────────────────────────────
def test_a_call_is_shown_once_its_input_is_known_and_closed_by_its_result():
    """fast-agent's shape: the call first with no arguments, the command on its first progress update."""
    evs, answer = A.translate([
        {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "execute", "kind": "execute",
         "status": "pending", "content": []},
        {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "in_progress",
         "rawInput": {"command": "echo hi"}},
        {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed",
         "content": [{"type": "content", "content": {"type": "text", "text": "hi\n[Exit code: 0]"}}]},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "done"}},
    ], F._tool_name)
    calls, results = _blocks(evs, "tool_use"), _blocks(evs, "tool_result")
    assert [(c["name"], c["input"]) for c in calls] == [("bash", {"command": "echo hi"})]
    assert results[0]["tool_use_id"] == "t1" and "hi" in results[0]["content"]
    assert [e["type"] for e in evs] == ["assistant", "user", "assistant"] and answer == "done"


def test_a_call_that_never_reports_input_or_completion_is_still_closed():
    evs, _ = A.translate([{"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "execute",
                           "kind": "execute", "status": "pending"}], F._tool_name)
    assert _blocks(evs, "tool_use")[0]["input"] == {}
    assert "no completion" in _blocks(evs, "tool_result")[0]["content"]


def test_the_answer_is_its_text_runs_and_never_its_thinking():
    evs, answer = A.translate([
        {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "hmm"}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "one "}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "two"}},
        {"sessionUpdate": "tool_call", "toolCallId": "c", "title": "read_text_file", "kind": "read",
         "rawInput": {"path": "a"}},
        {"sessionUpdate": "tool_call_update", "toolCallId": "c", "status": "completed", "content": []},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "three"}},
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""}},
    ], F._tool_name)
    assert answer == "one two\nthree"
    assert _blocks(evs, "thinking")[0]["thinking"] == "hmm"


def test_fast_agents_names_come_back_as_the_harness_knows_them():
    assert F._tool_name("execute", "execute") == "bash"
    assert F._tool_name("write_text_file", "edit") == "write_text_file"
    assert F._tool_name("environment/write_text_file", "edit") == "write_text_file"
    assert F._tool_name("deepwiki__read_wiki_structure", "other") == "deepwiki__read_wiki_structure"
    assert F._tool_name("", "") == "tool"


# ── the terminal ───────────────────────────────────────────────────────────────────────────────
def test_the_terminal_keeps_the_end_of_a_long_output_and_says_it_was_cut(tmp_path):
    t = A._Terminal(["/bin/sh", "-c", "seq 1 5000; echo THE-END"], str(tmp_path), dict(os.environ), 2048)
    t.done.wait(10)
    out = t.output()
    assert out.rstrip().endswith("THE-END") and len(out.encode()) <= 2048 and t.truncated
    assert t.status() == {"exitCode": 0, "signal": None}


def test_the_terminal_runs_in_the_session_and_can_be_killed(tmp_path):
    t = A._Terminal(["/bin/sh", "-c", "pwd; sleep 30"], str(tmp_path), dict(os.environ), 16000)
    time.sleep(0.5)
    t.kill()
    assert t.done.wait(10)
    assert str(tmp_path.resolve()) in t.output() or str(tmp_path) in t.output()
    assert t.status()["signal"] == "SIGKILL"


# ── fast-agent's driver, against the fake agent ────────────────────────────────────────────────
def _drive(tmp_path, mode, terminal=True):
    log = tmp_path / "asked.ndjson"
    job = {"argv": [sys.executable, str(AGENT)], "cwd": str(tmp_path), "prompt": "do it",
           "model": "gpt-5.4", "resume": "", "resume_known": False, "terminal": terminal, "timeout": 60}
    proc = subprocess.run([sys.executable, str(pathlib.Path(F.__file__)), json.dumps(job)], cwd=str(tmp_path),
                          text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
                          env={**os.environ, "FAKE_ACP_MODE": mode, "FAKE_ACP_LOG": str(log)})
    evs = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    asked = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return evs, asked


def test_a_shell_call_runs_in_the_clients_terminal_and_streams_its_command_and_output(tmp_path):
    evs, asked = _drive(tmp_path, "terminal")
    calls, results = _blocks(evs, "tool_use"), _blocks(evs, "tool_result")
    assert [(c["name"], c["input"].get("command")) for c in calls] == [("bash", "echo T > t.txt; echo TERMINAL-OUT")]
    assert "TERMINAL-OUT" in results[0]["content"] and results[0]["is_error"] is False
    assert (tmp_path / "t.txt").read_text().strip() == "T"                 # run in the session directory
    init = next(a for a in asked if a.get("method") == "initialize")
    assert init["params"]["clientCapabilities"]["terminal"] is True
    made = next(a for a in asked if a.get("asked_client") == "terminal/create")
    assert made["reply"]["result"]["terminalId"]
    assert evs[-1]["type"] == "result" and evs[-1]["result"] == "THE NEW ANSWER"


def test_with_the_shell_off_the_terminal_is_not_offered_and_the_turn_still_ends(tmp_path):
    evs, asked = _drive(tmp_path, "terminal", terminal=False)
    init = next(a for a in asked if a.get("method") == "initialize")
    assert init["params"]["clientCapabilities"]["terminal"] is False
    refused = next(a for a in asked if a.get("asked_client") == "terminal/create")
    assert "error" in refused["reply"]
    assert not (tmp_path / "t.txt").exists()
    assert evs[-1]["type"] == "result"


def test_fast_agents_updates_stream_while_its_prompt_is_still_running(tmp_path):
    log = tmp_path / "asked.ndjson"
    job = {"argv": [sys.executable, str(AGENT)], "cwd": str(tmp_path), "prompt": "do it", "model": "m",
           "resume": "", "terminal": True, "timeout": 60}
    proc = subprocess.Popen([sys.executable, str(pathlib.Path(F.__file__)), json.dumps(job)], cwd=str(tmp_path),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            env={**os.environ, "FAKE_ACP_MODE": "slow_prompt", "FAKE_ACP_LOG": str(log)})
    t0, seen = time.time(), []
    for line in proc.stdout:
        if line.strip().startswith("{"):
            seen.append((time.time() - t0, json.loads(line)))
    proc.wait(timeout=30)
    first = next(t for t, e in seen if e["type"] == "assistant" and e["message"]["content"][0].get("text") == "FIRST ")
    done = next(t for t, e in seen if e["type"] == "result")
    assert done - first >= 1.5, (first, done)


def test_a_conversation_the_store_has_but_will_not_load_fails_rather_than_starting_over(tmp_path):
    log = tmp_path / "asked.ndjson"
    job = {"argv": [sys.executable, str(AGENT)], "cwd": str(tmp_path), "prompt": "do it", "model": "m",
           "resume": "s-old", "resume_known": True, "terminal": True, "timeout": 60}
    proc = subprocess.run([sys.executable, str(pathlib.Path(F.__file__)), json.dumps(job)], cwd=str(tmp_path),
                          text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
                          env={**os.environ, "FAKE_ACP_MODE": "load_fails", "FAKE_ACP_LOG": str(log)})
    res = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith("{")][-1]
    assert res["is_error"] and "could not be continued" in res["result"]
    asked = [json.loads(line)["method"] for line in log.read_text().splitlines() if line.strip() and "method" in line]
    assert "session/new" not in asked
