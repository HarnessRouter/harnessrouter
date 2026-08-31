"""An incomplete turn says WHY, and only when it knows.

One banner for every incomplete — "hit its step or time limit" — misdiagnosed a turn that was
cut by a deploy restart, and sent the operator debugging a 400-step default that was never
reached. The record now carries incomplete_details.reason (max_steps | timeout | interrupted);
absent means unknown, and the console claims nothing specific.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402


def _tr(**kw):
    return A._RespTranslator("resp_t", "m", None, True, 0.0, **kw)


def test_a_capped_turn_names_its_cap():
    tr = _tr()
    tr.incomplete_reason = "max_steps"
    d = tr._response_obj("incomplete")
    assert d["incomplete_details"] == {"reason": "max_steps"}


def test_an_unknown_cause_stays_null_rather_than_guessing():
    d = _tr()._response_obj("incomplete")
    assert d["incomplete_details"] is None


def test_a_completed_turn_never_carries_one():
    tr = _tr()
    tr.incomplete_reason = "max_steps"          # stale attr must not leak onto a clean finish
    assert _tr()._response_obj("completed")["incomplete_details"] is None
    assert tr._response_obj("completed")["incomplete_details"] is None
