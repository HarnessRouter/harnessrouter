"""The reconcile sweep ages a session from its heartbeat, its birth and its turn's start, never from
1970. A heartbeat of 0 read as "never" made every running session without one older than the hard
cap, and with no result in its trace the sweep settled it failed at once (hosted, 2026-10-19: a
newborn settled while its sandbox was being placed, then completed 34 s later). The response-level
twin of this trap was fixed in _reconcile_response (test_reconcile_newborn.py)."""
import asyncio
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def _running(**props) -> dict:
    return {"id": "hsess1", "tenant": "org.p", "status": "running", "running_response_id": "",
            "runner_turn_id": "", "backend": "codex", **props}


def _sweep(monkeypatch, v: dict) -> tuple[bool, list]:
    writes: list = []

    async def vertex_upsert(sid, props):
        writes.append((sid, dict(props)))
        return True

    async def trace_status(base, since_ms=0):
        return None                                   # no result in the trace

    async def sandbox(*a, **k):
        raise AssertionError("the runner is not asked about a session the sweep leaves alone")
    monkeypatch.setattr(gw, "_vertex_upsert", vertex_upsert)
    monkeypatch.setattr(gw, "_trace_terminal_status", trace_status)
    monkeypatch.setattr(gw, "_sandbox", sandbox)
    return asyncio.run(gw._reconcile_session(v)), writes


def test_a_newborn_session_with_no_heartbeat_yet_is_not_settled(monkeypatch):
    settled, writes = _sweep(monkeypatch, _running(created_at=str(time.time() - 5)))
    assert settled is False and writes == []


def test_a_follow_up_waiting_for_its_turn_is_aged_from_the_turns_start(monkeypatch):
    """An old task's next turn: its last heartbeat is the previous turn's, hours ago, past the cap;
    the turn was accepted half a minute ago and has not reached its first heartbeat."""
    v = _running(created_at=str(time.time() - 2 * 86400), heartbeat=str(time.time() - 8 * 3600),
                 turn_at=str(time.time() - 30))
    settled, writes = _sweep(monkeypatch, v)
    assert settled is False and writes == []


def test_a_session_dead_past_the_cap_by_a_known_time_still_settles(monkeypatch):
    v = _running(created_at=str(time.time() - 2 * 86400), heartbeat=str(time.time() - 7 * 3600),
                 turn_at=str(time.time() - 7 * 3600))
    settled, writes = _sweep(monkeypatch, v)
    assert settled is True and writes == [("hsess1", {"status": "failed", "turn_status": "failed", "end_reason": "timeout"})]


def test_a_session_with_no_time_on_record_is_left_alone(monkeypatch):
    settled, writes = _sweep(monkeypatch, _running())
    assert settled is False and writes == []


def test_the_trace_prefix_dates_a_session_whose_record_has_no_created_at(monkeypatch):
    inv = gw._inv_ts(time.time() - 10)                # born ten seconds ago, by its prefix
    settled, writes = _sweep(monkeypatch, _running(trace_blob=f"org.p/{inv}_hsess1"))
    assert settled is False and writes == []


def test_the_age_floor_reads_each_clock():
    now = time.time()
    assert gw._sweep_seen({}) == 0
    assert gw._sweep_seen({"heartbeat": "x", "created_at": None}) == 0
    assert gw._sweep_seen({"heartbeat": str(now - 100), "turn_at": str(now - 5)}) == now - 5
    assert abs(gw._sweep_seen({"trace_blob": f"org/{gw._inv_ts(now - 60)}_hsess1"}) - (now - 60)) < 0.01
    assert gw._created_from_prefix("not-a-prefix") is None
