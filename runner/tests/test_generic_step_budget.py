"""The generic step budget (#471): a base with no limit flag of its own is bounded by the runner.

_run_turn_bg counts tool calls in the normalised stream (every normaliser emits the same
Claude-shaped tool_use blocks) and, past the budget, ends the turn error_max_turns — which the
gateway reports as incomplete — instead of running to the wall-clock cap.
"""
import json
import os
import pathlib
import sys
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import _run_turn_bg, _status_from_result, _turns  # noqa: E402


def _tool_use(i):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"cmd": "true"}}]}}


def _child_script(n_calls: int = 8, pause: float = 0.05, repeat: bool = False,
                  result: dict | None = None, hang: bool = False) -> str:
    """A CLI that streams a claude-shaped turn: init, n tool rounds, then a result (or, with `hang`,
    nothing more until it is killed). `repeat` reports every call twice, the way a normaliser may
    report a call's start and then its completion."""
    lines = ["import json,sys,time",
             "print(json.dumps({\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"s1\"}), flush=True)"]
    for i in range(n_calls):
        tu = json.dumps(_tool_use(i))
        tr = json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}})
        lines.append(f"print({json.dumps(tu)}, flush=True)")
        if repeat:
            lines.append(f"print({json.dumps(tu)}, flush=True)")
        lines.append(f"print({json.dumps(tr)}, flush=True)")
        if pause:
            lines.append(f"time.sleep({pause})")
    done = result or {"type": "result", "subtype": "success", "is_error": False,
                      "result": "done anyway"}
    lines.append("time.sleep(30)" if hang else f"print({json.dumps(json.dumps(done))}, flush=True)")
    return "\n".join(lines) + "\n"


def _run(tmp_path, script: str, backend: str = "qwen", max_turns: int = 2,
         count_steps: bool = True) -> dict:
    turn_id = "gen-budget-" + uuid.uuid4().hex
    path = tmp_path / "stream.py"
    path.write_text(script)
    _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                       "started": time.time(), "backend": backend, "model": "m"}
    try:
        _run_turn_bg(turn_id, [sys.executable, str(path)], os.environ.copy(), str(tmp_path),
                     rs._claude_passthrough, "m", timeout_seconds=30,
                     max_turns=max_turns, count_steps=count_steps)
        return _turns[turn_id]
    finally:
        _turns.pop(turn_id, None)


def _results(rec: dict) -> list[dict]:
    return [ev for ev in rec["events"] if ev.get("type") == "result"]


def test_the_generic_budget_ends_the_turn_as_max_turns(tmp_path):
    rec = _run(tmp_path, _child_script())
    results = _results(rec)
    assert results and results[-1]["subtype"] == "error_max_turns"
    assert results[-1]["is_error"] is False
    assert rec["status"] == "max_turns"          # the gateway reports this as incomplete
    # the budget stopped the turn: the CLI's own success result never made the record
    assert not any(ev.get("subtype") == "success" for ev in results)
    assert rec["done"]


def test_no_counting_for_a_base_with_its_own_limit(tmp_path):
    """The same stream with counting off (a base whose builder passes a native flag) runs whole."""
    rec = _run(tmp_path, _child_script(), backend="claude", count_steps=False)
    assert rec["status"] == "done" and rec["result"] == "done anyway"


def test_a_result_already_written_when_the_budget_stops_the_turn_is_not_a_success(tmp_path):
    """The CLI wrote its whole turn before the runner read a line: its success result is still
    in the pipe after the stop. It keeps its usage, and the turn is still incomplete at its budget."""
    usage = {"input_tokens": 1200, "output_tokens": 40}
    rec = _run(tmp_path, _child_script(pause=0, result={
        "type": "result", "subtype": "success", "is_error": False, "result": "all done",
        "usage": usage}))
    assert rec["status"] == "max_turns"
    final = _results(rec)[-1]
    assert final["subtype"] == "error_max_turns" and final["is_error"] is False
    assert final["usage"] == usage


def test_a_call_reported_twice_spends_the_budget_once(tmp_path):
    rec = _run(tmp_path, _child_script(n_calls=2, repeat=True), max_turns=2)
    assert rec["status"] == "done" and rec["result"] == "done anyway"


def test_a_stop_before_any_result_carries_what_the_relay_counted(tmp_path, monkeypatch):
    """codex never writes turn.completed once it is killed: the budget's result is the turn's, and
    its usage is the relay's count. Where nothing counted, it carries no usage, never a zero."""
    hang = _child_script(n_calls=4, hang=True)
    relay = {"input_tokens": 900, "output_tokens": 12}
    monkeypatch.setattr(rs, "_relay_usage", lambda env: dict(relay))
    rec = _run(tmp_path, hang)
    final = _results(rec)[-1]
    assert rec["status"] == "max_turns" and final["subtype"] == "error_max_turns"
    assert final["usage"] == relay
    monkeypatch.setattr(rs, "_relay_usage", lambda env: {})
    rec = _run(tmp_path, hang)
    assert rec["status"] == "max_turns" and "usage" not in _results(rec)[-1]


def test_a_remote_base_is_stopped_gracefully_and_its_charge_kept(tmp_path, monkeypatch):
    """qoder's process is a client of a runtime elsewhere: killing it outright leaves that runtime
    running and billing. The budget stops it the way a cancel does: SIGTERM first, so the driver
    cancels the remote turn and reports its charge, which stays on the turn's result."""
    monkeypatch.setitem(rs.BACKENDS, "remotebase", {"remote": True})
    cancelled = {"type": "result", "subtype": "error", "is_error": True,
                 "result": "cancel accepted", "charge": {"credits": 3}}
    script = "\n".join([
        "import json,signal,sys,time",
        "def term(*a):",
        f"    print({json.dumps(json.dumps(cancelled))}, flush=True)",
        "    sys.exit(0)",
        "signal.signal(signal.SIGTERM, term)",
    ] + [f"print({json.dumps(json.dumps(_tool_use(i)))}, flush=True)" for i in range(4)]
        + ["time.sleep(30)"]) + "\n"
    rec = _run(tmp_path, script, backend="remotebase")
    final = _results(rec)[-1]
    assert rec["status"] == "max_turns"
    assert final["subtype"] == "error_max_turns" and final["is_error"] is False
    assert final["charge"] == {"credits": 3} and final["result"] == "cancel accepted"


def test_the_budget_set_covers_exactly_the_unbounded_bases():
    assert rs._GENERIC_STEP_BUDGET == {"codex", "dsh", "pi", "omp", "gajae", "qwen", "gemini",
                                       "cline", "opencode", "mimo", "kilo", "qoder"}
    # and every entry is a backend the registry offers
    assert rs._GENERIC_STEP_BUDGET <= set(rs.BACKENDS)


def test_the_stop_result_reports_incomplete_at_the_gateway_layer():
    ev = {"type": "result", "subtype": "error_max_turns", "is_error": False, "result": ""}
    assert _status_from_result(ev, -9) == "max_turns"
