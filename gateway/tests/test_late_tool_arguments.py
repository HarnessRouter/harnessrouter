"""A call announced without arguments and sent again with them fills its own row.

opensquilla's progress stream announces a call with no input; the arguments are in its transcript,
which the runner reads when the turn ends and sends again under the same id. Before, the row stayed
`{}` in the console and in the record. The fill is narrow so no other base changes: the same id and
name, the earlier row empty and without a result. Everything else appends, as it always did."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def _use(cid, name, inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": cid, "name": name, "input": inp}]}}


def _result(cid, out):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": cid, "content": out}]}}


def _run(events):
    t = gw._RespTranslator("resp_1", "m", None, True, time.time())
    evs = [e for ev in events for e in t.feed(ev)]
    calls = [o for o in t.output if o["type"] == "function_call"]
    return t, evs, calls


def test_the_arguments_land_on_the_row_the_call_started():
    t, evs, calls = _run([_use("call_a", "exec_command", {}),
                          _use("call_a", "exec_command", {"cmd": "echo one"}),
                          _result("call_a", "one")])
    assert len(calls) == 1 and json.loads(calls[0]["arguments"]) == {"cmd": "echo one"}
    # the stream says so on the SAME item, so a live console fills that row
    done = [e for e in evs if e["type"] == "response.function_call_arguments.done"]
    assert len(done) == 2 and done[0]["item_id"] == done[1]["item_id"] == calls[0]["id"]
    assert done[1]["output_index"] == done[0]["output_index"]
    outs = [o for o in t.output if o["type"] == "function_call_output"]
    assert len(outs) == 1 and outs[0]["call_id"] == "call_a"


def test_a_shared_fallback_id_with_a_result_is_two_calls_not_one():
    # some translators fall back to a fixed id ("tool") when a CLI gives none
    _, _, calls = _run([_use("tool", "bash", {}), _result("tool", "ok"), _use("tool", "bash", {"command": "ls"})])
    assert len(calls) == 2


def test_another_name_under_the_same_id_is_its_own_row():
    _, _, calls = _run([_use("x", "read", {}), _use("x", "write", {"path": "a"})])
    assert len(calls) == 2


def test_a_call_resent_with_the_arguments_it_had_goes_the_way_it_always_went():
    _, _, calls = _run([_use("c", "bash", {"command": "ls"}), _use("c", "bash", {"command": "ls"})])
    assert len(calls) == 2
    _, _, calls = _run([_use("d", "bash", {}), _use("d", "bash", {})])
    assert len(calls) == 2
