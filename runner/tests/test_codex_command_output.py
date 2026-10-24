"""A codex command's stored output is what the model was given (openai/codex#28207).

codex drops a command's output printed before it opens the command item: for
`echo FIRST-LINE; sleep 3; echo LAST-LINE` the model got both lines, while the item's outputDelta
and aggregatedOutput carried only LAST-LINE, and the record kept only that (codex-cli 0.154.0,
reproduced on the test VM 2026-10-24). codex's own record of the thread, the rollout file, holds
the answer the model was given, so the output is read from there, by call id. A command whose
record never arrives is stored marked incomplete, never passed off as whole.

The record lines below are the shapes codex 0.154.0 wrote on the test VM.
"""
import json
import os
import pathlib
import sys
import threading
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import _turns  # noqa: E402

THREAD = "01a16c3d-9116-7920-bea4-edb0a4a4f7a8"


def _answer(output: str, *, running: str | None = None, code: int = 0, tokens: int = 6) -> str:
    """codex's answer to an exec_command or write_stdin call, header and all."""
    state = f"Process running with session ID {running}" if running else f"Process exited with code {code}"
    return f"Chunk ID: 72e949\nWall time: 2.8587 seconds\n{state}\nOriginal token count: {tokens}\nOutput:\n{output}"


def _call(call_id: str, name: str, args: dict) -> dict:
    return {"timestamp": "2026-10-24T04:49:01.000Z", "type": "response_item",
            "payload": {"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": call_id}}


def _out(call_id: str, output: str) -> dict:
    return {"timestamp": "2026-10-24T04:49:02.319Z", "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": call_id, "output": output}}


def _rollout_file(codex_home: pathlib.Path, thread: str = THREAD) -> pathlib.Path:
    d = codex_home / "sessions" / "2026" / "10" / "24"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"rollout-2026-10-24T04-48-56-{thread}.jsonl"


def _write(path: pathlib.Path, *records: dict) -> None:
    with open(path, "a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_the_output_is_the_answer_the_model_was_given(tmp_path):
    path = _rollout_file(tmp_path)
    _write(path, {"type": "session_meta", "payload": {"id": THREAD}},
           _call("call_A", "exec_command", {"cmd": "echo FIRST-LINE; sleep 3; echo LAST-LINE"}),
           _out("call_A", _answer("FIRST-LINE\nLAST-LINE\n")))
    ro = rs._CodexRollout(tmp_path, THREAD)
    assert rs._codex_command_output(ro, "call_A", wait_s=0) == ("FIRST-LINE\nLAST-LINE\n", True)


def test_a_record_that_lands_after_the_item_is_waited_for(tmp_path):
    """The record trails item/completed by a few ms (measured); the same read is made again."""
    path = _rollout_file(tmp_path)
    _write(path, _call("call_A", "exec_command", {"cmd": "x"}))
    later = threading.Timer(0.3, _write, args=(path, _out("call_A", _answer("FIRST-LINE\nLAST-LINE\n"))))
    later.start()
    t0 = time.monotonic()
    got = rs._codex_command_output(rs._CodexRollout(tmp_path, THREAD), "call_A", wait_s=5)
    later.join()
    assert got == ("FIRST-LINE\nLAST-LINE\n", True)
    assert 0.25 < time.monotonic() - t0 < 2


def test_a_record_that_never_lands_is_reported_missing(tmp_path):
    path = _rollout_file(tmp_path)
    _write(path, _call("call_A", "exec_command", {"cmd": "x"}))
    assert rs._codex_command_output(rs._CodexRollout(tmp_path, THREAD), "call_A", wait_s=0.2) == (None, False)
    # and no rollout at all
    assert rs._codex_command_output(rs._CodexRollout(tmp_path, "no-such-thread"), "call_A", wait_s=0.1) == (None, False)


def test_two_calls_in_a_turn_each_get_their_own_output(tmp_path):
    path = _rollout_file(tmp_path)
    _write(path, _call("call_A", "exec_command", {"cmd": "a"}), _out("call_A", _answer("A-FIRST\nA-LAST\n")),
           _call("call_B", "exec_command", {"cmd": "b"}), _out("call_B", _answer("B-FIRST\nB-LAST\n")))
    ro = rs._CodexRollout(tmp_path, THREAD)
    assert rs._codex_command_output(ro, "call_B", wait_s=0) == ("B-FIRST\nB-LAST\n", True)
    assert rs._codex_command_output(ro, "call_A", wait_s=0) == ("A-FIRST\nA-LAST\n", True)


def test_a_large_output_is_kept_as_codex_cut_it_for_the_model(tmp_path):
    """codex cut 169 KB to about 1 KB for the model, and says so in the output; that is the record."""
    cut = ("Warning: truncated output (original token count: 42228)\nBIG-START\n1\n2\n"
           "…42028 tokens truncated…\n29999\n30000\nBIG-END\n")
    path = _rollout_file(tmp_path)
    _write(path, _call("call_A", "exec_command", {"cmd": "seq"}), _out("call_A", _answer(cut, tokens=42228)))
    assert rs._codex_command_output(rs._CodexRollout(tmp_path, THREAD), "call_A", wait_s=0) == (cut, True)


def test_a_polled_command_joins_the_answers_for_its_session(tmp_path):
    """A command that outlives its first wait: the model polls it with write_stdin, and each answer
    carries the next part. Another session's poll in between is not this command's."""
    path = _rollout_file(tmp_path)
    _write(path,
           _call("call_A", "exec_command", {"cmd": "echo P-FIRST; sleep 8; echo P-MID; sleep 8; echo P-LAST"}),
           _out("call_A", _answer("P-FIRST\n", running="28925")),
           _call("call_X", "write_stdin", {"session_id": 99, "chars": ""}),
           _out("call_X", _answer("OTHER\n", running="99")),
           _call("call_B", "write_stdin", {"session_id": 28925, "chars": ""}),
           _out("call_B", _answer("P-MID\n", running="28925")))
    ro = rs._CodexRollout(tmp_path, THREAD)
    assert rs._codex_command_output(ro, "call_A", wait_s=0.1) == ("P-FIRST\nP-MID\n", False)
    _write(path, _call("call_C", "write_stdin", {"session_id": 28925, "chars": ""}),
           _out("call_C", _answer("P-LAST\n")))
    assert rs._codex_command_output(ro, "call_A", wait_s=0) == ("P-FIRST\nP-MID\nP-LAST\n", True)


def test_a_line_codex_is_still_writing_is_read_once_it_is_whole(tmp_path):
    path = _rollout_file(tmp_path)
    line = json.dumps(_out("call_A", _answer("FIRST-LINE\n")))
    _write(path, _call("call_A", "exec_command", {"cmd": "x"}))
    with open(path, "a") as f:
        f.write(line[:40])
    ro = rs._CodexRollout(tmp_path, THREAD)
    assert rs._codex_command_output(ro, "call_A", wait_s=0) == (None, False)
    with open(path, "a") as f:
        f.write(line[40:] + "\n")
    assert rs._codex_command_output(ro, "call_A", wait_s=0) == ("FIRST-LINE\n", True)


def test_an_answer_of_another_shape_is_kept_whole():
    assert rs._codex_exec_answer("Exit code: 0\nhello\n") == ("Exit code: 0\nhello\n", None)
    assert rs._codex_output_text([{"type": "input_text", "text": "a"}, {"type": "input_text", "text": "b"}]) == "ab"
    assert rs._codex_output_text({"content": "c", "success": True}) == "c"


def test_the_exec_path_marks_a_command_output_incomplete():
    """`codex exec` names its items item_0, item_1, ...: nothing ties the output to the record."""
    evs = rs._codex_to_claude({"type": "item.completed", "item": {
        "id": "item_2", "type": "command_execution", "command": "echo E-FIRST; sleep 3; echo E-LAST",
        "aggregated_output": "E-LAST\n", "exit_code": 0}}, {})
    res = evs[1]["message"]["content"][0]
    assert res["type"] == "tool_result" and res["content"] == "E-LAST\n" and res["incomplete"] is True


_FAKE = '''
import json, os, pathlib, sys, threading, time
home = pathlib.Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "10" / "24"
home.mkdir(parents=True, exist_ok=True)
rollout = home / "rollout-2026-10-24T04-48-56-th1.jsonl"
cmds = json.loads(os.environ["FAKE_CMDS"])
def out(o):
    print(json.dumps(o), flush=True)
def record(*recs):
    with open(rollout, "a") as f:
        for r in recs:
            f.write(json.dumps(r) + "\\n")
for line in sys.stdin:
    m = json.loads(line)
    meth, mid = m.get("method"), m.get("id")
    if meth == "initialize":
        out({"id": mid, "result": {}})
    elif meth in ("thread/start", "thread/resume"):
        out({"id": mid, "result": {"thread": {"id": "th1"}}})
    elif meth == "turn/start":
        out({"id": mid, "result": {"turn": {"id": "tu1"}}})
        for c in cmds:
            record({"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                    "arguments": json.dumps({"cmd": c["cmd"]}), "call_id": c["id"]}})
            out({"method": "item/started", "params": {"item": {"type": "commandExecution", "id": c["id"],
                 "command": c["cmd"], "aggregatedOutput": None}}})
            out({"method": "item/commandExecution/outputDelta", "params": {"itemId": c["id"], "delta": c["seen_by_item"]}})
            answer = {"type": "response_item", "payload": {"type": "function_call_output", "call_id": c["id"],
                      "output": "Chunk ID: 1\\nWall time: 3.0 seconds\\nProcess exited with code 0\\nOriginal token count: 4\\nOutput:\\n" + c["model_saw"]}}
            if c.get("record") == "late":
                threading.Timer(0.2, record, args=(answer,)).start()
            elif c.get("record") != "never":
                record(answer)
            out({"method": "item/completed", "params": {"item": {"type": "commandExecution", "id": c["id"],
                 "command": c["cmd"], "aggregatedOutput": c["seen_by_item"], "exitCode": 0}}})
        time.sleep(0.4)
        out({"method": "item/agentMessage/delta", "params": {"delta": "DONE"}})
        out({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
'''


def _turn(tmp_path, cmds: list[dict]) -> dict:
    """codex on the app-server path (the image's default) against a fake app-server that writes a
    rollout the way codex does and drops the first chunk from the item the way codex does."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "codex"
    fake.write_text(f"#!{sys.executable}\n" + _FAKE)
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
           "CODEX_HOME": str(tmp_path / "codex-home"), "FAKE_CMDS": json.dumps(cmds)}
    turn_id = "codex-out-" + uuid.uuid4().hex
    _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                       "started": time.time(), "backend": "codex", "model": "m"}
    try:
        rs._run_codex_appserver_bg(turn_id, str(tmp_path), env, "m", "go", None, 30, None)
        return _turns[turn_id]
    finally:
        _turns.pop(turn_id, None)


def _results(rec: dict) -> dict:
    return {b["tool_use_id"]: b for ev in rec["events"] if ev.get("type") == "user"
            for b in ev["message"]["content"] if b.get("type") == "tool_result"}


def test_the_app_server_turn_stores_what_the_model_saw(tmp_path):
    rec = _turn(tmp_path, [
        {"id": "call_A", "cmd": "echo A-FIRST; sleep 2; echo A-LAST", "seen_by_item": "A-LAST\n",
         "model_saw": "A-FIRST\nA-LAST\n"},
        {"id": "call_B", "cmd": "echo B-FIRST; sleep 2; echo B-LAST", "seen_by_item": "B-LAST\n",
         "model_saw": "B-FIRST\nB-LAST\n", "record": "late"}])
    res = _results(rec)
    assert rec["status"] == "done"
    assert res["call_A"]["content"] == "A-FIRST\nA-LAST\n" and "incomplete" not in res["call_A"]
    assert res["call_B"]["content"] == "B-FIRST\nB-LAST\n" and "incomplete" not in res["call_B"]


def test_a_command_with_no_record_is_stored_marked_incomplete(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rs, "_CODEX_RECORD_WAIT_S", 0.3)
    rec = _turn(tmp_path, [{"id": "call_A", "cmd": "echo FIRST; sleep 3; echo LAST", "seen_by_item": "LAST\n",
                            "model_saw": "FIRST\nLAST\n", "record": "never"}])
    res = _results(rec)["call_A"]
    assert res["incomplete"] is True and res["content"] == "LAST\n"
    log = capsys.readouterr().out
    assert "command call_A: no record of its output within 0.3 s; stored marked incomplete" in log
    assert "1 command output(s) stored marked incomplete" in log
