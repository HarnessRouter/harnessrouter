"""A turn queued behind the concurrency gates is alive, and says so.

On one container the gates admit as many turns as the box has cores. A turn accepted while they are
full waits as `starting`, with no runner turn yet; the orphan sweep read such a session as dead and
settled it, session and response, as failed, and the turn's own final write later said completed
(measured 2026-10-12: a background poller read `failed`, error null, four seconds into a 28-second
wait for a slot, and `completed` at 55 s)."""
import asyncio
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def _gates(monkeypatch, n=1):
    g, t = asyncio.Semaphore(n), asyncio.Semaphore(n)
    monkeypatch.setattr(gw, "_global_sem", lambda: g)
    monkeypatch.setattr(gw, "_tenant_sem", lambda org: t)
    return g


def test_a_turn_waiting_for_a_slot_keeps_its_heartbeat_fresh_and_stops_once_admitted(monkeypatch):
    beats: list = []

    async def _vup(sid, props):
        beats.append((sid, props))

    monkeypatch.setattr(gw, "_vertex_upsert", _vup)
    monkeypatch.setattr(gw, "_RECONCILE_STALE_S", 4)          # one beat a second

    async def main():
        g = _gates(monkeypatch)
        await g.acquire()                                      # the box is full
        admitted = asyncio.Event()

        async def turn():
            async with gw._turn_slot("org", "hsess1"):
                admitted.set()
                await asyncio.sleep(2.5)                       # running: no queue beats now

        task = asyncio.create_task(turn())
        await asyncio.sleep(2.5)
        queued = len(beats)
        g.release()                                            # a slot frees up
        await asyncio.wait_for(admitted.wait(), 2)
        await task
        return queued

    queued = asyncio.run(main())
    assert queued >= 2
    assert all(sid == "hsess1" and set(p) == {"heartbeat"} for sid, p in beats)
    assert len(beats) == queued                                # nothing written after admission
    assert time.time() - float(beats[-1][1]["heartbeat"]) < 10


def test_a_turn_that_gets_its_slot_at_once_writes_no_extra_beat(monkeypatch):
    beats: list = []

    async def _vup(sid, props):
        beats.append(props)

    monkeypatch.setattr(gw, "_vertex_upsert", _vup)
    monkeypatch.setattr(gw, "_RECONCILE_STALE_S", 4)

    async def main():
        _gates(monkeypatch)
        async with gw._turn_slot("org", "hsess1"):
            await asyncio.sleep(1.5)

    asyncio.run(main())
    assert beats == []


def test_the_sweep_leaves_a_queued_turn_alone(monkeypatch):
    # what the accept-time write leaves on the vertex: starting, no runner turn, a fresh heartbeat
    writes: list = []

    async def _vup(sid, props):
        writes.append(props)

    async def _tts(blob):
        return None

    monkeypatch.setattr(gw, "_vertex_upsert", _vup)
    monkeypatch.setattr(gw, "_trace_terminal_status", _tts)
    v = {"id": "hsess1", "status": "running", "turn_status": "starting", "runner_turn_id": "",
         "heartbeat": str(time.time())}
    assert asyncio.run(gw._reconcile_session(v)) is False and writes == []


def test_the_accept_time_write_stamps_the_heartbeat():
    src = pathlib.Path(gw.__file__).read_text()
    i = src.index('"running_response_id": resp_id, "runner_turn_id": "",')
    assert '"heartbeat": str(time.time())' in src[i:i + 200]
    assert src.count("async with _turn_slot(org, sid):") == 3
    assert src.count("async with _global_sem(), _tenant_sem(org):") == 1   # inside _turn_slot only
