"""A question for the person ends the turn (UHP Tasks §3.2, #476).

The base gets `ask_user` as an MCP tool (ask_user_mcp.py). The runner reads its call in the stream,
and at the call's RESULT — not the call, so the base's transcript holds the pair its resume
continues from — stops the process the way the step budget does. The turn's result is
`incomplete` with reason `input_required` and the question beside it; the gateway makes that the
response's `input_request` item. A call the tool refused (a choice with one option) goes back to
the model and ends nothing.
"""
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ask_user_mcp  # noqa: E402
import server as rs  # noqa: E402
from server import _run_turn_bg, _status_from_result, _turn_answer, _turns  # noqa: E402

ASK = "mcp__harnessrouter__ask_user"
QUESTION = {"kind": "choice", "prompt": "Which language?",
            "options": [{"id": "en", "label": "English"}, {"id": "zh", "label": "Chinese"}]}


def _ev_tool_use(i, name="Bash", inp=None):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp or {"cmd": "true"}}]}}


def _ev_tool_result(i, content="ok", is_error=False):
    block = {"type": "tool_result", "tool_use_id": f"t{i}", "content": content}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "message": {"content": [block]}}


def _script(events: list[dict], then: str = "hang") -> str:
    """A CLI that streams the given claude-shaped events, then hangs until killed (the usual
    killed-CLI case), or prints a success result and exits."""
    lines = ["import json,sys,time",
             "print(json.dumps({\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"s1\"}), flush=True)"]
    for ev in events:
        lines.append(f"print({json.dumps(json.dumps(ev))}, flush=True)")
        lines.append("time.sleep(0.05)")
    if then == "hang":
        lines.append("time.sleep(30)")
    else:
        done = {"type": "result", "subtype": "success", "is_error": False, "result": then}
        lines.append(f"print({json.dumps(json.dumps(done))}, flush=True)")
    return "\n".join(lines) + "\n"


def _run(tmp_path, script: str, asks: bool = True) -> dict:
    turn_id = "ask-" + uuid.uuid4().hex
    path = tmp_path / "stream.py"
    path.write_text(script)
    _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                       "started": time.time(), "backend": "claude", "model": "m", "asks": asks}
    try:
        _run_turn_bg(turn_id, [sys.executable, str(path)], os.environ.copy(), str(tmp_path),
                     rs._claude_passthrough, "m", timeout_seconds=30)
        return _turns[turn_id]
    finally:
        _turns.pop(turn_id, None)


def _results(rec: dict) -> list[dict]:
    return [ev for ev in rec["events"] if ev.get("type") == "result"]


def test_the_question_ends_the_turn_incomplete_with_the_question(tmp_path):
    t0 = time.time()
    rec = _run(tmp_path, _script([_ev_tool_use(1, ASK, QUESTION),
                                  _ev_tool_result(1, json.dumps({"status": "input_required"}))]))
    assert time.time() - t0 < 10, "the CLI was left to hang instead of being stopped at the question"
    assert rec["status"] == "incomplete" and rec["reason"] == "input_required"
    assert rec["input_request"] == QUESTION
    final = _results(rec)[-1]
    assert final["subtype"] == "incomplete" and final["is_error"] is False
    assert final["reason"] == "input_required" and final["input_request"] == QUESTION
    assert rec["done"] and not rec.get("error")
    assert _status_from_result(final, -9) == "incomplete"


def test_the_turn_ends_at_the_result_not_at_the_call(tmp_path):
    """The call alone ends nothing: the stop waits for the tool's answer, so the transcript the
    base resumes from holds the call and its result as a pair."""
    rec = _run(tmp_path, _script([_ev_tool_use(1, ASK, QUESTION)], then="finished"))
    assert rec["status"] == "done" and rec["result"] == "finished"
    assert rec["input_request"] is None


def test_a_call_the_tool_refused_ends_nothing(tmp_path):
    """ask_user_mcp refuses a choice with one option; the refusal goes back to the model as the
    tool's error, and the turn goes on."""
    one = {"kind": "choice", "prompt": "Which?", "options": [{"id": "a", "label": "A"}]}
    rec = _run(tmp_path, _script([_ev_tool_use(1, ASK, one),
                                  _ev_tool_result(1, "ask_user: a choice needs at least two options", is_error=True),
                                  _ev_tool_use(2, ASK, QUESTION),
                                  _ev_tool_result(2, json.dumps({"status": "input_required"}))]))
    assert rec["status"] == "incomplete" and rec["input_request"] == QUESTION


def test_another_tools_result_is_not_a_question(tmp_path):
    rec = _run(tmp_path, _script([_ev_tool_use(1), _ev_tool_result(1)], then="finished"))
    assert rec["status"] == "done" and rec["input_request"] is None


def test_a_result_the_cli_wrote_before_the_stop_is_still_the_questions(tmp_path):
    """A model that goes on after the call, or a CLI whose whole turn was in the pipe before the
    runner read a line: its success result is rewritten, as the step budget rewrites one."""
    rec = _run(tmp_path, _script([_ev_tool_use(1, ASK, QUESTION),
                                  _ev_tool_result(1, json.dumps({"status": "input_required"}))],
                                 then="I went on anyway"))
    assert rec["status"] == "incomplete" and rec["reason"] == "input_required"
    final = _results(rec)[-1]
    assert final["subtype"] == "incomplete" and final["input_request"] == QUESTION
    assert not any(ev.get("subtype") == "success" for ev in _results(rec))


def test_the_bare_tool_name_counts_too():
    assert rs._is_ask_tool("mcp__harnessrouter__ask_user")
    # a customer's tool with the same name is theirs: it must not end the turn
    assert not rs._is_ask_tool("ask_user") and not rs._is_ask_tool("mcp__helpdesk__ask_user")
    assert not rs._is_ask_tool("AskUserQuestion") and not rs._is_ask_tool("ask_user_question")


def test_a_turn_that_was_not_served_the_tool_is_not_ended_by_one(tmp_path):
    rec = _run(tmp_path, _script([_ev_tool_use(1, ASK, QUESTION),
                                  _ev_tool_result(1, json.dumps({"status": "input_required"}))], then="finished"),
               asks=False)
    assert rec["status"] == "done" and rec["result"] == "finished" and not rec.get("input_request")


def test_a_secret_answer_is_scrubbed_at_any_length_and_the_record_is_given_it():
    vals = rs._turn_secrets({"HR_INPUT_a": "123456", "OTHER": "short"}, ["HR_INPUT_a", "OTHER"])
    assert "123456" in vals and "short" not in vals
    # The record's list comes from the turn's whole environment: _caller_env drops HR_ names, which
    # left a secret answer unscrubbed in everything a client reads while the agent echoed it.
    src = pathlib.Path(rs.__file__).read_text()
    assert '"secrets": _turn_secrets(req.env or {}, req.env_secret)' in src


@pytest.mark.parametrize("ttl", [float("inf"), float("-inf"), float("nan")])
def test_an_expiry_that_is_not_a_number_is_refused(ttl):
    assert ask_user_mcp.validate_request({"kind": "free_text", "prompt": "x", "expires_in_seconds": ttl})[0] is None


def test_the_poll_body_carries_the_question_and_redacts_a_secret_in_it():
    rec = {"status": "incomplete", "done": True, "result": "", "backend": "claude", "model": "m",
           "events": [], "started": time.time(), "reason": "input_required",
           "input_request": {"kind": "free_text", "prompt": "The key is hunter22hunter22; confirm?"},
           "secrets": ["hunter22hunter22"]}
    out = _turn_answer("t", rec, 0, False)
    assert out["reason"] == "input_required"
    assert out["input_request"]["prompt"] == "The key is [redacted]; confirm?"
    assert rec["input_request"]["prompt"].startswith("The key is hunter22")   # a copy; the record is untouched


# ── the tool's own rules ──────────────────────────────────────────────────────────────────────────

def test_validate_a_choice():
    req, why = ask_user_mcp.validate_request(QUESTION)
    assert req == QUESTION and why == ""


def test_validate_takes_option_strings_as_id_and_label():
    req, _ = ask_user_mcp.validate_request({"kind": "choice", "prompt": "Which?", "options": ["a", "b"]})
    assert req["options"] == [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}]


def test_validate_a_confirm_gets_yes_and_no():
    req, _ = ask_user_mcp.validate_request({"kind": "confirm", "prompt": "Delete it?"})
    assert req["options"] == [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}]


def test_validate_refuses_what_cannot_be_asked():
    bad = [({"kind": "choice", "prompt": "x", "options": ["a"]}, "two options"),
           ({"kind": "choice", "prompt": "x", "options": ["a", "a"]}, "distinct"),
           ({"kind": "free_text", "prompt": "x", "options": ["a", "b"]}, "no options"),
           ({"kind": "poll", "prompt": "x"}, "kind must be"),
           ({"kind": "secret", "prompt": ""}, "prompt"),
           ({"kind": "secret", "prompt": "x", "expires_in_seconds": 0}, "expires_in_seconds"),
           ("not an object", "object")]
    for inp, word in bad:
        req, why = ask_user_mcp.validate_request(inp)
        assert req is None and word in why, (inp, why)


def test_validate_turns_a_ttl_into_expires_at():
    req, _ = ask_user_mcp.validate_request({"kind": "secret", "prompt": "Token?", "expires_in_seconds": 60}, now=1000)
    assert req == {"kind": "secret", "prompt": "Token?", "expires_at": 1060}


def test_the_server_speaks_mcp_over_stdio():
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "ask_user", "arguments": QUESTION}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "ask_user", "arguments": {"kind": "choice", "prompt": "x", "options": []}}},
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list"}]
    out = subprocess.run([sys.executable, str(pathlib.Path(rs.__file__).with_name("ask_user_mcp.py"))],
                         input="\n".join(json.dumps(m) for m in msgs) + "\n",
                         capture_output=True, text=True, timeout=20)
    replies = {r["id"]: r for r in (json.loads(ln) for ln in out.stdout.splitlines() if ln.strip())}
    assert replies[1]["result"]["serverInfo"]["name"] == "harnessrouter"
    assert [t["name"] for t in replies[2]["result"]["tools"]] == ["ask_user"]
    assert json.loads(replies[3]["result"]["content"][0]["text"]) == {"status": "input_required"}
    assert replies[3]["result"]["isError"] is False
    assert replies[4]["result"]["isError"] is True and "two options" in replies[4]["result"]["content"][0]["text"]
    assert replies[5]["error"]["code"] == -32601


def test_the_claude_turn_gets_the_tool_and_loses_the_clis_own_question():
    """What _start_turn hands the claude builder: the ask server beside the harness's own MCP
    servers, and AskUserQuestion in the deny list."""
    srv = rs._ask_user_server()
    assert srv["name"] == "harnessrouter" and srv["args"][0].endswith("ask_user_mcp.py")
    assert pathlib.Path(srv["args"][0]).is_file()
    src = pathlib.Path(rs.__file__).read_text()
    i = src.index("if req.input_requests:")
    window = src[i:i + 600]
    assert "_ask_user_server()" in window and '"AskUserQuestion"' in window
