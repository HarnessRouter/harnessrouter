"""A background response is readable the moment its POST returns; the turn's task writes the
session vertex and its first heartbeat a beat later. The reconciler that settles orphans must not
call that newborn a corpse: no vertex yet, or a vertex without a heartbeat yet, is a turn that has
not started, not one that died (measured 2026-09-21: every inner run a calibrator started read
`failed`, error null, for its whole life, because the reconciler persisted `failed` on the first
read and the owner's final write was the only thing that ever corrected it)."""
import asyncio
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def _run(rec, vertex, monkeypatch, trace_status=None):
    puts: list = []

    async def _vget(sid):
        return vertex

    async def _bput(key, data, kb=0):
        puts.append(key)
        return True

    async def _bget(key, kb=0):
        return None

    async def _vgup(label, vid, props, **kw):
        return None

    async def _tts(blob):
        return trace_status

    monkeypatch.setattr(gw, "_vertex_get", _vget)
    monkeypatch.setattr(gw, "_blob_put", _bput)
    monkeypatch.setattr(gw, "_blob_get", _bget)
    monkeypatch.setattr(gw, "_vg_upsert", _vgup)
    monkeypatch.setattr(gw, "_trace_terminal_status", _tts)
    monkeypatch.setattr(gw, "_resp_cache_forget", lambda rid: None)
    out = asyncio.run(gw._reconcile_response("resp_1", dict(rec)))
    return out, puts


def test_a_record_whose_session_vertex_does_not_exist_yet_is_left_running(monkeypatch):
    rec = {"status": "running", "_session_id": "hsess1", "created_at": int(time.time())}
    out, puts = _run(rec, None, monkeypatch)
    assert out["status"] == "running" and puts == []


def test_a_vertex_the_turn_has_not_stamped_yet_is_a_newborn_not_an_orphan(monkeypatch):
    now = time.time()
    rec = {"status": "running", "_session_id": "hsess1", "created_at": int(now)}
    vertex = {"status": "running", "created_at": str(now)}          # no heartbeat yet
    out, puts = _run(rec, vertex, monkeypatch)
    assert out["status"] == "running" and puts == []


def test_a_turn_that_stopped_heartbeating_past_the_cap_is_still_settled(monkeypatch):
    old = time.time() - gw._GW_MAX_TURN_S - 600
    rec = {"status": "running", "_session_id": "hsess1", "created_at": int(old)}
    vertex = {"status": "running", "created_at": str(old), "heartbeat": str(old)}
    out, puts = _run(rec, vertex, monkeypatch)
    assert out["status"] == "failed" and puts == ["responses/resp_1.json"]


def test_a_stale_turn_with_a_terminal_trace_settles_from_the_trace(monkeypatch):
    old = time.time() - gw._RECONCILE_STALE_S - 60
    rec = {"status": "running", "_session_id": "hsess1", "created_at": int(old)}
    vertex = {"status": "running", "created_at": str(old), "heartbeat": str(old), "trace_blob": "x"}
    out, puts = _run(rec, vertex, monkeypatch, trace_status="done")
    assert out["status"] == "completed" and puts == ["responses/resp_1.json"]
