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
    assert d["incomplete_details"] == {"reason": "max_steps", "handoff": None}   # a capped run hands nothing off


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


class _Resp:
    def __init__(self, code):
        self.status_code = code


def _sweep(monkeypatch, v, probe_code=404, rec=None, tts=None):
    """Run the orphan sweep on a session vertex, the runner answering the turn probe with
    probe_code; returns the vertex writes and the response record as it was persisted."""
    import asyncio
    vertex = dict(v)
    writes: list = []
    stored: dict = {}
    async def _vup(sid, props):
        writes.append(props)
        vertex.update(props)
    async def _vget(sid):
        return dict(vertex)
    async def _tts(blob, since_ms=0):
        return None
    async def _sandbox(path, sid, method, **k):
        return _Resp(probe_code)
    async def _resp_get(rid):
        return dict(rec) if rec else None
    async def _blob_get(*a, **k):
        return None
    async def _blob_put(key, data, **k):
        import json
        stored.update(json.loads(data))
        return True
    async def _vg_upsert(*a, **k):
        return None
    for name, fn in (("_vertex_upsert", _vup), ("_vertex_get", _vget), ("_trace_terminal_status", tts or _tts),
                     ("_sandbox", _sandbox), ("_resp_get", _resp_get), ("_blob_get", _blob_get),
                     ("_blob_put", _blob_put), ("_vg_upsert", _vg_upsert)):
        monkeypatch.setattr(A, name, fn)
    settled = asyncio.run(A._reconcile_session(v))
    return settled, writes, stored


def test_a_turn_the_runner_lost_to_a_restart_is_interrupted_not_failed(monkeypatch):
    """#505: the runner restarted under the turn, so it answers 404 for it. The task did not fail;
    the turn was cut, and a follow-up continues it. The session and the response both say so."""
    import time
    v = {"id": "hsess1", "status": "running", "turn_status": "running", "runner_turn_id": "rt_1",
         "running_response_id": "resp_1", "heartbeat": str(time.time() - 600)}
    rec = {"id": "resp_1", "status": "running", "_session_id": "hsess1", "output": []}
    settled, writes, stored = _sweep(monkeypatch, v, 404, rec)
    assert settled is True
    assert writes[0] == {"status": "incomplete", "turn_status": "incomplete",
                         "incomplete_reason": "interrupted"}
    assert stored["status"] == "incomplete"
    assert stored["incomplete_details"] == {"reason": "interrupted", "handoff": None}


def test_a_turn_with_no_runner_turn_recorded_is_still_failed(monkeypatch):
    """Nothing proves a restart when no runner turn was ever recorded: no reason is claimed."""
    import time
    v = {"id": "hsess1", "status": "running", "turn_status": "starting", "runner_turn_id": "",
         "heartbeat": str(time.time() - 600)}
    settled, writes, _ = _sweep(monkeypatch, v, 404)
    assert settled is True and writes[0] == {"status": "failed", "turn_status": "failed"}


def test_a_runner_that_still_holds_the_turn_is_not_settled(monkeypatch):
    import time
    monkeypatch.setattr(A, "_adopting", {"hsess1"})        # adoption already running: spawn nothing
    v = {"id": "hsess1", "status": "running", "turn_status": "running", "runner_turn_id": "rt_1",
         "heartbeat": str(time.time() - 600)}
    settled, writes, _ = _sweep(monkeypatch, v, 200)
    assert settled is False and writes == []


def test_a_new_turn_drops_the_last_turns_reason():
    """The reason lives on the session, so the next turn's start clears it: a later orphan must
    not inherit 'interrupted' from an earlier one."""
    import inspect
    src = inspect.getsource(A)
    i = src.index('"heartbeat": str(time.time()), "runner_turn_id": "", "incomplete_reason": ""')
    assert '"turn_status": "starting"' in src[i - 200:i]
    j = src.index('"running_response_id": resp_id, "runner_turn_id": "",')
    assert '"incomplete_reason": ""' in src[j:j + 250]


def test_a_turn_the_gateway_drains_under_is_interrupted(monkeypatch):
    import asyncio
    tr = _tr()
    emitted, persisted = [], []
    async def _emit(ev):
        emitted.append(ev)
    async def _persist(status):
        persisted.append((status, tr._response_obj(status)))
    asyncio.run(A._settle_drained(_persist, tr, _emit))
    assert emitted[-1]["type"] == "response.incomplete"
    assert persisted[0][0] == "incomplete"
    assert persisted[0][1]["incomplete_details"]["reason"] == "interrupted"
    assert persisted[0][1]["error"] is None


def test_a_dead_follow_up_is_not_settled_by_the_turn_before_it(monkeypatch):
    """The trace is one stream for the whole session. Turn 1 ended with a result; turn 2 died
    under a restart with none. Read unscoped, turn 1's result settled turn 2 'completed' with
    no output (#505, live). Scoped to turn 2's start it finds nothing, and the probe decides."""
    import asyncio, json
    chunks = {"t/events/1000-a-0-1.jsonl": json.dumps({"type": "result", "is_error": False}).encode(),
              "t/events/5000-b-0-1.jsonl": json.dumps({"type": "tool_use", "name": "Bash"}).encode()}
    async def _list(prefix, **k):
        return [{"file_id": c} for c in chunks]
    async def _get(cid, **k):
        return chunks.get(cid)
    monkeypatch.setattr(A, "_blob_list_all", _list)
    monkeypatch.setattr(A, "_blob_get", _get)
    assert asyncio.run(A._trace_terminal_status("t")) == "done"            # unscoped: turn 1's
    assert asyncio.run(A._trace_terminal_status("t", 4000)) is None         # turn 2's own: none
    assert A._turn_since_ms(None) == 0 and A._turn_since_ms({"created_at": 4.5}) == 4500


def test_the_previous_turns_result_in_the_same_second_is_not_this_turns():
    """created_at is whole seconds. Measured: turn 1's result chunk at 1792417802072, turn 2
    created later in second 1792417802. The cutoff is the next second, so that chunk is not read."""
    since = A._turn_since_ms({"created_at": 1792417802})
    assert since > 1792417802072 and since == 1792417803000


def test_the_sweep_reads_the_trace_from_the_running_turns_start(monkeypatch):
    import time
    seen = []
    v = {"id": "hsess1", "status": "running", "turn_status": "running", "runner_turn_id": "rt_1",
         "running_response_id": "resp_2", "trace_blob": "org/inv_hsess1", "heartbeat": str(time.time() - 600)}
    rec = {"id": "resp_2", "status": "running", "_session_id": "hsess1", "output": [], "created_at": 4}
    async def _tts(blob, since_ms=0):
        seen.append(since_ms)
        return None
    settled, writes, _ = _sweep(monkeypatch, v, 404, rec, tts=_tts)
    assert seen[0] == 5000 and writes[0]["incomplete_reason"] == "interrupted"
