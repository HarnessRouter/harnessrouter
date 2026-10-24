"""The harness's own account of a failure survives to the trace (#504).

A turn that failed keeps the exception and the stack frames the harness printed, and the name of
the tool that failed. The one line in rec["error"] is for a person — a message may not carry a
stack trace (UHP errors §1) — and the raw text is what a debugger needs. It is read from the
stream every base emits (a tool_use carries the name, the tool_result that follows carries
is_error), so it reads the same for claude and for codex.
"""
import json
import os
import pathlib
import sys
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import _run_turn_bg, _turns  # noqa: E402


TRACEBACK = ("Traceback (most recent call last):\n"
             '  File "/app/tools.py", line 42, in run\n'
             '    raise ValueError("the tool blew up")\n'
             "ValueError: the tool blew up\n")


def _claude_cli(tool: str = "Read", stderr_text: str = TRACEBACK) -> str:
    """A claude-shaped CLI: a tool call whose result came back an error, the CLI's own result
    event, then the traceback it printed when the tool raised."""
    lines = [
        "import json,sys",
        "print(json.dumps({'type':'system','subtype':'init','session_id':'s1'}), flush=True)",
        "print(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','id':'t1',"
        + "'name':" + json.dumps(tool) + ",'input':{'file_path':'/etc/hosts'}}]}}), flush=True)",
        "print(json.dumps({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'t1',"
        "'is_error':True,'content':'ValueError: the tool blew up'}]}}), flush=True)",
        "print(json.dumps({'type':'result','subtype':'error','is_error':True,"
        "'result':'the CLI own sentence'}), flush=True)",
        f"sys.stderr.write({json.dumps(stderr_text)})",
        "sys.exit(1)",
    ]
    return "\n".join(lines) + "\n"


def _codex_cli() -> str:
    """A codex-shaped CLI: a command that failed, the turn's own failure, and the traceback."""
    lines = [
        "import json,sys",
        "print(json.dumps({'type':'thread.started','thread_id':'th1'}), flush=True)",
        "print(json.dumps({'type':'item.completed','item':{'type':'commandExecution','id':'c1',"
        "'command':'boom','aggregatedOutput':'ValueError: the tool blew up','exitCode':1}}), flush=True)",
        "print(json.dumps({'type':'turn.failed','error':{'message':'the CLI own sentence'}}), flush=True)",
        f"sys.stderr.write({json.dumps(TRACEBACK)})",
        "sys.exit(1)",
    ]
    return "\n".join(lines) + "\n"


def _run(tmp_path, script: str, backend: str, normalize, secrets: list[str] | None = None) -> dict:
    turn_id = "err-detail-" + uuid.uuid4().hex
    path = tmp_path / "stream.py"
    path.write_text(script)
    _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                       "started": time.time(), "backend": backend, "model": "m",
                       "secrets": list(secrets or [])}
    try:
        _run_turn_bg(turn_id, [sys.executable, str(path)], os.environ.copy(), str(tmp_path),
                     normalize, "m", timeout_seconds=30)
        return _turns[turn_id]
    finally:
        _turns.pop(turn_id, None)


def _detail(rec: dict) -> dict:
    """The detail on the trace's result event — the turn's own ending, with the failure on it."""
    results = [ev for ev in rec["events"] if ev.get("type") == "result"]
    assert results, "the turn left no result event: " + json.dumps(rec["events"])
    return results[-1].get("error_detail") or {}


def test_a_failed_turn_keeps_the_exception_and_the_stack_frames(tmp_path):
    rec = _run(tmp_path, _claude_cli(), "claude", rs._claude_passthrough)
    assert rec["status"] == "failed"
    detail = _detail(rec)
    assert "ValueError: the tool blew up" in detail["exception"]
    assert 'File "/app/tools.py", line 42, in run' in detail["exception"]
    assert detail["base"] == "claude"
    assert detail["tool"] == "Read"          # the tool whose result came back an error
    # the record's own line stays a line: a message may not carry a stack trace (errors §1)
    assert rec["error"] == "the CLI own sentence"
    assert "Traceback" not in rec["error"]


def test_another_base_reads_the_same_detail_from_its_own_stream(tmp_path):
    """The same code, on codex's stream: the tool's name is codex's own, and the exception and
    the stack frames are as whole as claude's."""
    rec = _run(tmp_path, _codex_cli(), "codex", rs._codex_to_claude)
    assert rec["status"] == "failed"
    detail = _detail(rec)
    assert detail["base"] == "codex"
    assert detail["tool"] == "Bash"          # codex's name for the command it ran
    assert "ValueError: the tool blew up" in detail["exception"]
    assert 'File "/app/tools.py", line 42, in run' in detail["exception"]


def test_a_cli_that_died_before_it_said_anything_still_leaves_a_result_event(tmp_path):
    script = f"import sys\nsys.stderr.write({json.dumps(TRACEBACK)})\nsys.exit(3)\n"
    rec = _run(tmp_path, script, "claude", rs._claude_passthrough)
    assert rec["status"] == "failed"
    detail = _detail(rec)
    assert "ValueError: the tool blew up" in detail["exception"]
    assert detail["tool"] == ""              # no tool ran: nothing to name


def test_the_result_made_for_a_cli_that_said_nothing_is_not_an_answer(tmp_path):
    """The gateway shows a result's text as the turn's answer when nothing was said before it
    (_RespTranslator), so the result the runner makes for a dead CLI carries the reason as `error`:
    with it as `result`, the failure was drawn as the agent's own reply."""
    script = f"import sys\nsys.stderr.write({json.dumps(TRACEBACK)})\nsys.exit(3)\n"
    rec = _run(tmp_path, script, "claude", rs._claude_passthrough)
    ev = [e for e in rec["events"] if e.get("type") == "result"][-1]
    assert not ev.get("result")
    assert ev["error"] == rec["error"] and "ValueError: the tool blew up" in ev["error"]


def test_the_diagnostic_is_capped(tmp_path):
    tail = TRACEBACK + ("padding line\n" * 2000)
    rec = _run(tmp_path, _claude_cli(stderr_text=tail), "claude", rs._claude_passthrough)
    assert len(_detail(rec)["exception"]) <= rs._DIAG_MAX


def test_a_secret_in_the_diagnostic_is_redacted(tmp_path):
    secret = "sk-the-calls-own-secret"
    tail = TRACEBACK.replace("the tool blew up", "the tool blew up " + secret)
    rec = _run(tmp_path, _claude_cli(stderr_text=tail), "claude", rs._claude_passthrough,
               secrets=[secret])
    # the answer leaves the runner with the secret redacted — in the detail and in the trace's
    # own copy of it (the runner's own record keeps it, like every other thing the agent wrote)
    out = rs._turn_answer(rec["turn_id"], rec, 0, False)
    assert secret not in json.dumps(out)
    assert "[redacted]" in out["error_detail"]["exception"]
    assert "[redacted]" in out["events"][-1]["error_detail"]["exception"]


def _agentzero_cli(diagnostic: str) -> str:
    """The agentzero driver's stream: it handles the exception in-process and prints nothing the runner
    reads as a diagnostic, so its own result event is the only place the frames can come from (#546)."""
    lines = [
        "import json,sys",
        "print(json.dumps({'m':'init','p':{'session_id':'harness'}}), flush=True)",
        "print(json.dumps({'m':'result','p':{'ok':False,'final':'','error':'ValueError: the tool blew up',"
        "'diagnostic':" + json.dumps(diagnostic) + "}}), flush=True)",
        "sys.exit(1)",
    ]
    return "\n".join(lines) + "\n"


def test_agentzero_hands_over_the_frames_it_handled_in_process(tmp_path):
    """Every other base prints its exception and the runner reads it from the output's tail. Agent
    Zero's is handled inside the driver, which cut it at the traceback, so the trace's detail had the
    message and no frames. The driver now hands the whole text over on its result event."""
    whole = "ValueError: the tool blew up\n\n" + TRACEBACK
    rec = _run(tmp_path, _agentzero_cli(whole), "agentzero", rs._agentzero_to_claude)
    assert rec["status"] == "failed"
    detail = _detail(rec)
    assert detail["base"] == "agentzero"
    assert 'File "/app/tools.py", line 42, in run' in detail["exception"]
    assert "ValueError: the tool blew up" in detail["exception"]
    # the record keeps its one line, and the trace's result event carries no second copy
    assert rec["error"] == "ValueError: the tool blew up" and "Traceback" not in rec["error"]
    ev = [e for e in rec["events"] if e.get("type") == "result"][-1]
    assert "diagnostic" not in ev and "Traceback" not in str(ev.get("result"))


def test_a_secret_in_agentzeros_diagnostic_is_redacted(tmp_path):
    secret = "sk-the-calls-own-secret"
    whole = "ValueError: the tool blew up " + secret + "\n\n" + TRACEBACK
    rec = _run(tmp_path, _agentzero_cli(whole), "agentzero", rs._agentzero_to_claude, secrets=[secret])
    out = rs._turn_answer(rec["turn_id"], rec, 0, False)
    assert secret not in json.dumps(out)

