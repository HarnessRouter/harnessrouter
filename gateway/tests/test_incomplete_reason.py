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


def test_the_empty_output_settle_never_claims_a_cause():
    """The reconciler's empty-output settle cannot tell a cut turn from one that ended cleanly
    with no text: a max_step=1 turn ends 'done' with empty output and nothing interrupted it —
    measured live on the SaaS port, which shipped "interrupted" there and caught it within the
    hour. Unknown must stay absent rather than be guessed."""
    src = open(pathlib.Path(__file__).resolve().parents[1] / "app.py").read()
    i = src.index('settled == "completed" and not (rec.get("output")')
    window = src[i:i + 1200]
    assert '"reason"' not in window.split("else:")[0], (
        "the empty-output settle claims a reason it cannot know")


def test_a_finishing_owner_is_not_settled_from_under(monkeypatch):
    """The session flips to done before its owner has written the checkpoint and the full
    response record; a poller's reconcile in that window used to settle the record 'incomplete'
    and a replica cached that for good. A fresh heartbeat means the owner is alive: leave it."""
    import asyncio, time
    calls = []
    async def _vertex_get(vid):
        return {"id": vid, "status": "done", "heartbeat": str(time.time() - 5)}
    async def _blob_put(*a, **k):
        calls.append("put"); return True
    monkeypatch.setattr(A, "_vertex_get", _vertex_get)
    monkeypatch.setattr(A, "_blob_put", _blob_put)
    rec = {"id": "resp_x", "status": "running", "_session_id": "hsess1", "output": []}
    out = asyncio.run(A._reconcile_response("resp_x", rec))
    assert out["status"] == "running" and calls == []
    # the same session with a dead owner is settled, as before
    async def _vertex_get_dead(vid):
        return {"id": vid, "status": "done", "heartbeat": str(time.time() - 10_000)}
    async def _blob_get(*a, **k):
        return None
    async def _vg_upsert(*a, **k):
        return None
    monkeypatch.setattr(A, "_vertex_get", _vertex_get_dead)
    monkeypatch.setattr(A, "_blob_get", _blob_get)
    monkeypatch.setattr(A, "_vg_upsert", _vg_upsert)
    out = asyncio.run(A._reconcile_response("resp_x", dict(rec)))
    assert out["status"] == "incomplete" and calls == ["put"]


def test_a_refused_turn_leaves_the_session_as_it_found_it():
    """The lease is checked before the session is stamped running/starting: a follow-up refused
    as 'already in progress' must not leave a finished session looking live, or the orphan sweep
    adopts it and every retry is refused in turn (omp follow-ups, 2026-09-15)."""
    import inspect
    src = inspect.getsource(A._resp_execute)
    admit = src.index("control_store.lease_admit(")
    stamp = src.index('"turn_status": "starting"')
    assert admit < stamp, "the session must be stamped only after admission"
    refused = src.index('"a turn is already in progress for this session"')
    assert refused < stamp, "a refused turn returns before the stamp"
