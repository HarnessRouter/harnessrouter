"""A failed turn's error names the base that ran and the tool that failed (#504).

The message says the turn failed and why; the detail says WHICH harness and WHICH tool, so the
debugging does not stop at the router. The runner's account of the failure (the tool's name) comes
in with the turn's record; the base is the harness's own name for the family that ran it.
"""
import asyncio
import json
import os
import pathlib
import sys
import time

import jsonschema

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCHEMA = os.path.join(_ROOT, "protocol", "schema", "uhp-2026-08-11.schema.json")
ORG = "org_e"


def _rec(**kw) -> dict:
    rec = {"base": "claude-code", "backend": "claude",
           "tried": [{"connection": "c", "status": "failed", "error": "boom"}],
           "error_detail": {"base": "claude", "tool": "Bash",
                            "exception": "ValueError: the tool blew up"}}
    rec.update(kw)
    return rec


def _failed(rec: dict) -> dict:
    tr = gw._RespTranslator("resp_test", "some-model", None, False, 0.0)
    gw._fail_events(tr, rec)
    return tr.error


def test_the_error_names_the_base_and_the_tool():
    err = _failed(_rec())
    assert err["type"] == "harness_error" and err["code"] == "turn_failed"
    assert err["detail"] == {"base": "claude-code", "tool": "Bash"}
    assert "boom" in err["message"]


def test_the_error_still_validates_against_the_spec():
    s = json.load(open(_SCHEMA))
    err = _failed(_rec())
    jsonschema.validate(err, {"$defs": s["$defs"], **s["$defs"]["Error"]})


def test_a_turn_with_no_failing_tool_names_the_base_only():
    rec = _rec(error_detail={"base": "claude", "tool": "", "exception": "boom"})
    err = _failed(rec)
    assert err["detail"] == {"base": "claude-code"}


def test_the_harnesses_own_base_is_named_when_it_says_one():
    rec = _rec(base="", backend="codex")
    err = _failed(rec)
    assert err["detail"] == {"base": "codex", "tool": "Bash"}


def test_the_errors_own_detail_is_kept_where_the_turn_has_one():
    """A turn the server cut short (interrupted, capped) carries its own detail; the runner's
    account of a failure does not overwrite it."""
    rec = _rec(error=gw._cap_error())
    err = _failed(rec)
    assert err["detail"] == {"reason": "timeout"}


# ── the whole path, from the runner's answer to the response and the trace ─────────────────────

def _drive_a_failed_turn(monkeypatch):
    """Run _resp_execute against a runner that answers a failed turn the way the runner answers
    one now: its own account of the failure (the base, the tool, the exception) beside the one
    line of reason. Returns (status, the record, the translator, the events written to the trace).
    """
    detail = {"base": "claude", "tool": "Bash",
              "exception": "ValueError: the tool blew up\n  File \"/app/tools.py\", line 42, in run"}
    traced: list = []

    async def _sandbox_json(path, sid, method="POST", body=None, **kw):
        if path == "/turn":
            return {"turn_id": "t1", "status": "running"}
        if path.startswith("/turn/"):
            return {"done": True, "status": "failed", "error": "the CLI own sentence",
                    "error_detail": detail,
                    "events": [{"type": "result", "subtype": "error", "is_error": True,
                                "result": "the CLI own sentence", "error_detail": detail}],
                    "n_total": 1}
        return {}

    async def _nothing(*a, **kw):
        return None

    async def _get_connection(org, name):
        return ({"provider": "anthropic", "base_url": "https://proxy.example/v1"}, "tenant-1")

    async def _harness_plugins(*a, **kw):
        return ([], [], [], [], [])

    async def _harness_env(*a, **kw):
        return ({}, [])

    async def _image_auth(*a, **kw):
        return None

    def _auth_from_conn(*a, **kw):
        return {"token": "t", "base_url": "https://proxy.example/v1"}

    async def _turn_cancelled(*a, **kw):
        return False

    async def _collect_produced(*a, **kw):
        return []

    async def _trace_flush(tr, s):
        traced.extend(s.get("events") or [])
        return True

    for name, fn in (("_sandbox_json", _sandbox_json), ("_vertex_get", _nothing),
                     ("_vertex_upsert", _nothing), ("_hydrate", _nothing),
                     ("_harness_plugins", _harness_plugins), ("_harness_env", _harness_env),
                     ("_image_auth", _image_auth), ("_get_connection", _get_connection),
                     ("_auth_from_conn", _auth_from_conn), ("_turn_cancelled", _turn_cancelled),
                     ("_collect_produced", _collect_produced), ("_blob_put", _nothing),
                     ("_checkpoint", _nothing), ("_trace_finalize", _nothing),
                     ("_browser_close", _nothing), ("_recover_trace_cursor", _nothing),
                     ("_trace_flush", _trace_flush)):
        monkeypatch.setattr(gw, name, fn)
    monkeypatch.setattr(gw, "RESP_POLL_S", 0)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)

    tr = gw._RespTranslator("resp_fail", "m", None, True, time.time())
    status, _produced, rec = asyncio.run(gw._resp_execute(
        tr, org=ORG, member="me@local", sid="sess_fail", backend="claude", chain=["anthropic"],
        prompt="hi", files_in=[], resume=None, emit=lambda ev: asyncio.sleep(0)))
    gw._fail_events(tr, rec)      # what create_response does with a failed turn
    return status, rec, tr, traced


def test_the_whole_path_names_the_base_and_the_tool_and_keeps_the_exception(monkeypatch):
    status, rec, tr, traced = _drive_a_failed_turn(monkeypatch)
    assert status == "failed", rec.get("tried")
    err = tr.error
    assert err["type"] == "harness_error" and err["code"] == "turn_failed"
    assert err["detail"] == {"base": "claude", "tool": "Bash"}
    assert "the CLI own sentence" in err["message"]
    # the trace keeps the harness's own account of the failure, exception and stack frames whole
    result_ev = [ev for ev in traced if ev.get("type") == "result"]
    assert result_ev and "ValueError: the tool blew up" in result_ev[-1]["error_detail"]["exception"]
    assert 'line 42, in run' in result_ev[-1]["error_detail"]["exception"]


def test_a_result_with_the_failure_as_error_adds_no_answer():
    """The runner's own result for a CLI that died before it said anything carries the reason as
    `error` (runner/tests/test_failure_detail.py): fed to the translator it closes the turn and says
    nothing, where a reason in `result` was drawn as the agent's reply."""
    made = {"type": "result", "subtype": "error", "is_error": True, "result": "",
            "error": "ValueError: the tool blew up", "error_detail": {"base": "claude", "tool": ""}}
    tr = gw._RespTranslator("resp_made", "m", None, False, 0.0)
    tr.feed(made)
    assert not tr.any_text
    assert not [o for o in tr.output if o.get("type") == "message"]
    said = gw._RespTranslator("resp_said", "m", None, False, 0.0)
    said.feed({**made, "result": "ValueError: the tool blew up", "error": None})
    assert said.any_text      # what the reason in `result` did: an answer the agent never gave
