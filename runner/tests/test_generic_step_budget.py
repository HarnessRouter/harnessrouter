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


def _child_script(n_calls: int = 8) -> str:
    """A CLI that streams a claude-shaped turn: init, n tool rounds, then a success result."""
    lines = ["import json,sys,time",
             "print(json.dumps({\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"s1\"}), flush=True)"]
    for i in range(n_calls):
        tu = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"cmd": "true"}}]}})
        tr = json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}]}})
        lines.append(f"print({json.dumps(tu)}, flush=True)")
        lines.append(f"print({json.dumps(tr)}, flush=True)")
        lines.append("time.sleep(0.05)")
    done = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "result": "done anyway"})
    lines.append(f"print({json.dumps(done)}, flush=True)")
    return "\n".join(lines) + "\n"


def test_the_generic_budget_ends_the_turn_as_max_turns(tmp_path):
    turn_id = "gen-budget-" + uuid.uuid4().hex
    script = tmp_path / "stream.py"
    script.write_text(_child_script())
    _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                       "started": time.time(), "backend": "qwen", "model": "m"}
    try:
        _run_turn_bg(turn_id, [sys.executable, str(script)], os.environ.copy(), str(tmp_path),
                     rs._claude_passthrough, "m", timeout_seconds=30,
                     max_turns=2, count_steps=True)
        rec = _turns[turn_id]
        results = [ev for ev in rec["events"] if ev.get("type") == "result"]
        assert results and results[-1]["subtype"] == "error_max_turns"
        assert results[-1]["is_error"] is False
        assert rec["status"] == "max_turns"          # the gateway reports this as incomplete
        # the budget stopped the turn: the CLI's own success result never made the record
        assert not any(ev.get("subtype") == "success" for ev in results)
        assert rec["done"]
    finally:
        _turns.pop(turn_id, None)


def test_no_counting_for_a_base_with_its_own_limit(tmp_path):
    """The same stream with counting off (a base whose builder passes a native flag) runs whole."""
    turn_id = "gen-nocount-" + uuid.uuid4().hex
    script = tmp_path / "stream.py"
    script.write_text(_child_script())
    _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                       "started": time.time(), "backend": "claude", "model": "m"}
    try:
        _run_turn_bg(turn_id, [sys.executable, str(script)], os.environ.copy(), str(tmp_path),
                     rs._claude_passthrough, "m", timeout_seconds=30,
                     max_turns=2, count_steps=False)
        rec = _turns[turn_id]
        assert rec["status"] == "done" and rec["result"] == "done anyway"
    finally:
        _turns.pop(turn_id, None)


def test_the_budget_set_covers_exactly_the_unbounded_bases():
    assert rs._GENERIC_STEP_BUDGET == {"codex", "dsh", "pi", "omp", "gajae", "qwen", "gemini",
                                       "cline", "opencode", "mimo", "kilo", "qoder"}
    # and every entry is a backend the registry offers
    assert rs._GENERIC_STEP_BUDGET <= set(rs.BACKENDS)


def test_the_stop_result_reports_incomplete_at_the_gateway_layer():
    ev = {"type": "result", "subtype": "error_max_turns", "is_error": False, "result": ""}
    assert _status_from_result(ev, -9) == "max_turns"
