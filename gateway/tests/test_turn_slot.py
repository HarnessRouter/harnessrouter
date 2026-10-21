"""A turn queued behind the concurrency gates is alive, and says so.

On one container the gates admit as many turns as the box has cores. A turn accepted while they are
full waits as `starting`, with no runner turn yet; the orphan sweep read such a session as dead and
settled it, session and response, as failed, and the turn's own final write later said completed
(measured 2026-10-12: a background poller read `failed`, error null, four seconds into a 28-second
wait for a slot, and `completed` at 55 s)."""
import asyncio
import json
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
                gw._runner_turn_recorded("hsess1")            # its runner turn is on record: the poll loop beats
                await asyncio.sleep(2.5)                       # running: no slot beats now

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
            gw._runner_turn_recorded("hsess1")
            await asyncio.sleep(1.5)

    asyncio.run(main())
    assert beats == []


def test_a_turn_still_restoring_its_workspace_keeps_beating_and_is_never_settled(monkeypatch):
    """Past the gates but before its runner turn is on record (the workspace restore, plugins, the
    runner's /turn start), a turn has no runner turn for the sweep to ask and no poll loop to beat.
    The slot keeps its heartbeat fresh through all of it, so a restore longer than the stale window
    is never read as gone (CAT, 2026-10-21: restores past 120 s measured on the hosted service).
    Time is compressed: a stale window of 4 s, a restore of 6 s."""
    beats: list = []
    vertex = {"id": "hsess1", "tenant": "org", "status": "running", "turn_status": "starting",
              "runner_turn_id": "", "heartbeat": str(time.time())}

    async def _vup(sid, props):
        beats.append(props)
        vertex.update(props)

    monkeypatch.setattr(gw, "_vertex_upsert", _vup)
    monkeypatch.setattr(gw, "_RECONCILE_STALE_S", 4)

    async def sandbox(*a, **k):
        raise AssertionError("a session with a fresh heartbeat is not probed")
    monkeypatch.setattr(gw, "_sandbox", sandbox)

    async def main():
        _gates(monkeypatch)
        async with gw._turn_slot("org", "hsess1"):
            await asyncio.sleep(6)                          # the restore, longer than the stale window
            settled = await gw._reconcile_session(dict(vertex))
            before = len(beats)
            gw._runner_turn_recorded("hsess1")
            await asyncio.sleep(1.5)
            return settled, before

    settled, before = asyncio.run(main())
    assert settled is False
    assert before >= 4 and len(beats) == before                 # it beat until the runner turn was on record
    assert gw._RUNNER_TURN_ON.get("hsess1") is None             # and the slot cleaned up after itself


def test_the_sweep_leaves_a_queued_turn_alone(monkeypatch):
    # what the accept-time write leaves on the vertex: starting, no runner turn, a fresh heartbeat
    writes: list = []

    async def _vup(sid, props):
        writes.append(props)

    async def _tts(blob, since_ms=0):
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


def test_a_restore_that_hangs_past_the_cap_settles_at_the_cap_though_the_slot_still_beats(monkeypatch):
    """The slot's beat keeps a restoring turn alive, but not forever: the hard cap runs from the
    turn's start (turn_at), so a turn still without a runner turn past the cap is settled failed with
    reason timeout even while its heartbeat is fresh (CAT, 2026-10-21). Scaled: a 3 s cap, a 4 s stale
    window, a restore that hangs for 4.5 s."""
    started = time.time()
    vertex = {"id": "hsess1", "tenant": "org", "status": "running", "turn_status": "starting",
              "runner_turn_id": "", "running_response_id": "", "turn_at": str(started), "heartbeat": str(started)}
    writes: list = []

    async def _vup(sid, props):
        writes.append(dict(props))
        vertex.update(props)

    async def _tts(base, since_ms=0):
        return None

    async def sandbox(*a, **k):
        raise AssertionError("past the cap, nothing needs asking")
    monkeypatch.setattr(gw, "_vertex_upsert", _vup)
    monkeypatch.setattr(gw, "_trace_terminal_status", _tts)
    monkeypatch.setattr(gw, "_sandbox", sandbox)
    monkeypatch.setattr(gw, "_RECONCILE_STALE_S", 4)
    monkeypatch.setattr(gw, "_GW_MAX_TURN_S", 2)
    monkeypatch.setattr(gw, "_RUNNER_MAX_TURN_S", 2)
    monkeypatch.setattr(gw, "_CAP_MARGIN_S", 1)               # the cap: max(2, 2) + 1 = 3 s

    async def main():
        _gates(monkeypatch)
        async with gw._turn_slot("org", "hsess1"):
            await asyncio.sleep(4.5)                     # the restore hangs past the cap
            fresh = time.time() - float(vertex["heartbeat"]) < 4
            return fresh, await gw._reconcile_session(dict(vertex))

    fresh, settled = asyncio.run(main())
    assert fresh, "the slot was still beating"
    assert settled is True
    assert {"status": "failed", "turn_status": "failed", "end_reason": "timeout"} in writes


def _cap_sweep(monkeypatch, turn_age: float, probe: int = 200):
    """The sweep on a turn whose runner turn is on record and whose heartbeat went stale (its poll loop
    is gone), `turn_age` seconds after its start; the runner answers `probe` for the turn. Scaled: the
    gateway's and the runner's limit 100 s, the placement and restore margin 30 s."""
    monkeypatch.setattr(gw, "_GW_MAX_TURN_S", 100)
    monkeypatch.setattr(gw, "_RUNNER_MAX_TURN_S", 100)
    monkeypatch.setattr(gw, "_CAP_MARGIN_S", 30)
    monkeypatch.setattr(gw, "_adopting", {"hsess1"})          # an adoption is already running: spawn none
    now = time.time()
    v = {"id": "hsess1", "tenant": "org", "status": "running", "turn_status": "running", "runner_turn_id": "rt_1",
         "running_response_id": "", "turn_at": str(now - turn_age), "heartbeat": str(now - 300)}
    writes, calls = [], []

    async def _vup(sid, props):
        writes.append(dict(props))

    async def _tts(base, since_ms=0):
        return None

    class _R:
        def __init__(self, code):
            self.status_code = code

    async def sandbox(path, sid, method="POST", **k):
        calls.append((method, path))
        return _R(probe)
    monkeypatch.setattr(gw, "_vertex_upsert", _vup)
    monkeypatch.setattr(gw, "_trace_terminal_status", _tts)
    monkeypatch.setattr(gw, "_sandbox", sandbox)
    return asyncio.run(gw._reconcile_session(v)), writes, calls


def test_the_sweep_cap_is_the_runners_limit_plus_the_placement_margin(monkeypatch):
    monkeypatch.setattr(gw, "_GW_MAX_TURN_S", 100)
    monkeypatch.setattr(gw, "_RUNNER_MAX_TURN_S", 120)
    monkeypatch.setattr(gw, "_CAP_MARGIN_S", 30)
    assert gw._sweep_cap_s() == 150


def test_a_turn_still_inside_the_runners_limit_plus_margin_is_not_settled_as_timed_out(monkeypatch):
    """The gateway's clock starts at accept, before placement and restore; past the runner's limit
    but inside the margin, the runner may still be working on it, so nothing is settled as timed out."""
    settled, writes, calls = _cap_sweep(monkeypatch, turn_age=120)
    assert settled is False and not any(w.get("end_reason") == "timeout" for w in writes)
    assert ("POST", "/turn/rt_1/cancel") not in calls


def test_past_the_limit_plus_margin_it_settles_timed_out_and_the_runners_turn_is_cancelled(monkeypatch):
    settled, writes, calls = _cap_sweep(monkeypatch, turn_age=140)
    assert settled is True
    assert writes[0] == {"status": "failed", "turn_status": "failed", "end_reason": "timeout"}
    assert ("POST", "/turn/rt_1/cancel") in calls


def _record_sweep(monkeypatch, vertex: dict, rec: dict):
    """The sweep on `vertex` with its running response record `rec`; returns whether it settled and
    the record as it was persisted. Scaled: the cap is max(2, 2) + 1 = 3 s."""
    monkeypatch.setattr(gw, "_GW_MAX_TURN_S", 2)
    monkeypatch.setattr(gw, "_RUNNER_MAX_TURN_S", 2)
    monkeypatch.setattr(gw, "_CAP_MARGIN_S", 1)
    monkeypatch.setattr(gw, "_RECONCILE_STALE_S", 4)
    stored: dict = {}

    async def _vup(sid, props):
        vertex.update(props)

    async def _vget(sid):
        return dict(vertex)

    async def _tts(base, since_ms=0):
        return None

    async def _resp_get(rid):
        return dict(rec)

    async def _blob_get(*a, **k):
        return None

    async def _blob_put(key, data, **k):
        stored.update(json.loads(data))
        return True

    async def _nothing(*a, **k):
        return None

    async def sandbox(*a, **k):
        raise AssertionError("no runner turn on record: nothing to ask or cancel")
    for name, fn in (("_vertex_upsert", _vup), ("_vertex_get", _vget), ("_trace_terminal_status", _tts),
                     ("_resp_get", _resp_get), ("_blob_get", _blob_get), ("_blob_put", _blob_put),
                     ("_vg_upsert", _nothing), ("_sandbox", sandbox)):
        monkeypatch.setattr(gw, name, fn)
    return asyncio.run(gw._reconcile_session(dict(vertex))), stored


def test_a_capped_turn_whose_slot_still_beats_settles_its_response_record_too(monkeypatch):
    """Past the cap with no runner turn on record, the sweep settles the session while the slot still
    beats (a restore that hangs), and the response record must settle in the same pass. The record's
    guard for an owner that is finalizing reads a terminal session with a fresh heartbeat as one about
    to write its own record, so the record stayed `running` for as long as the slot beat, and a
    background poller never saw the turn end (found by the hosted port, 2026-10-21)."""
    now = time.time()
    vertex = {"id": "hsess1", "tenant": "org", "status": "running", "turn_status": "starting",
              "runner_turn_id": "", "running_response_id": "resp_1", "turn_at": str(now - 10),
              "heartbeat": str(now)}
    rec = {"id": "resp_1", "status": "running", "_session_id": "hsess1", "output": [], "created_at": now - 10}
    settled, stored = _record_sweep(monkeypatch, vertex, rec)
    assert settled is True and vertex["end_reason"] == "timeout"
    assert stored.get("status") == "failed", "the response record stayed running"
    assert stored["error"] == gw._cap_error()


def test_a_session_an_owner_is_finalizing_still_leaves_its_record_to_the_owner(monkeypatch):
    """The guard stands for what it is for: a terminal session whose owner beat moments ago, with no
    reason the sweep proved, is an owner writing its own record, and the record is left alone."""
    now = time.time()
    v = {"id": "hsess1", "status": "done", "heartbeat": str(now), "running_response_id": "resp_1"}
    rec = {"id": "resp_1", "status": "running", "_session_id": "hsess1", "output": []}

    async def _vget(sid):
        return dict(v)

    async def _blob_put(*a, **k):
        raise AssertionError("the owner writes this record, not the reconciler")
    monkeypatch.setattr(gw, "_vertex_get", _vget)
    monkeypatch.setattr(gw, "_blob_put", _blob_put)
    assert asyncio.run(gw._reconcile_response("resp_1", dict(rec)))["status"] == "running"
    # a reason on the session that belongs to another response does not open the guard either
    v.update(status="failed", end_reason="timeout", running_response_id="resp_2")
    assert asyncio.run(gw._reconcile_response("resp_1", dict(rec)))["status"] == "running"


def _drive_a_late_turn(monkeypatch, age_s: float, hydrate=None):
    """Run `_resp_execute` for a turn accepted `age_s` seconds ago (a restore or a wait that hung),
    with the world's edges stubbed; returns (status, rec, vertex writes, runner calls). Scaled: the
    cap is max(2, 2) + 1 = 3 s."""
    monkeypatch.setattr(gw, "_GW_MAX_TURN_S", 2)
    monkeypatch.setattr(gw, "_RUNNER_MAX_TURN_S", 2)
    monkeypatch.setattr(gw, "_CAP_MARGIN_S", 1)
    calls, writes = [], []

    async def _sandbox_json(path, sid, method="POST", body=None, **kw):
        calls.append(path)
        if path == "/turn":
            return {"turn_id": "t1", "status": "running"}
        if path.startswith("/turn/"):
            return {"done": True, "status": "done", "events": [], "n_total": 0}
        return {}

    async def _nothing(*a, **kw):
        return None

    async def _vup(sid, props):
        writes.append(dict(props))

    async def _get_connection(org, name):
        return ({"provider": "anthropic", "base_url": "https://proxy.example/v1"}, "tenant-1")

    async def _harness_plugins(*a, **kw):
        return ([], [], [], [], [])

    async def _harness_env(*a, **kw):
        return ({}, [])

    async def _false(*a, **kw):
        return False

    async def _collect_produced(*a, **kw):
        return []
    for name, fn in (("_sandbox_json", _sandbox_json), ("_vertex_get", _nothing), ("_vertex_upsert", _vup),
                     ("_hydrate", hydrate or _nothing), ("_harness_plugins", _harness_plugins), ("_harness_env", _harness_env),
                     ("_image_auth", _nothing), ("_get_connection", _get_connection),
                     ("_auth_from_conn", lambda *a, **k: {"token": "t", "base_url": "https://proxy.example/v1"}),
                     ("_turn_cancelled", _false), ("_collect_produced", _collect_produced), ("_blob_put", _nothing),
                     ("_checkpoint", _nothing), ("_trace_finalize", _nothing), ("_browser_close", _nothing),
                     ("_recover_trace_cursor", _nothing)):
        monkeypatch.setattr(gw, name, fn)
    monkeypatch.setattr(gw, "RESP_POLL_S", 0)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)
    translator = gw._RespTranslator("resp_late", "m", None, True, time.time() - age_s)
    status, _produced, rec = asyncio.run(gw._resp_execute(
        translator, org="org", member="me@local", sid="sess_late", backend="claude",
        chain=["anthropic"], prompt="hi", files_in=[], resume=None, emit=lambda ev: asyncio.sleep(0)))
    return status, rec, writes, calls, translator


def test_a_turn_that_waited_past_the_cap_for_its_slot_never_runs(monkeypatch):
    """The sweep settled it as timed out while it waited; when the slot comes, the turn must not be
    stamped running again, restore, or start the agent and finish over that answer (terminal is
    final). It ends as the sweep said: failed, reason timeout, and nothing runs."""
    status, rec, writes, calls, tr = _drive_a_late_turn(monkeypatch, age_s=10)
    assert "/turn" not in calls, "a turn past the cap started the agent"
    assert status == "failed" and rec["error"] == gw._cap_error()
    assert writes == [{"status": "failed", "turn_status": "failed", "end_reason": "timeout"}], (
        f"a settled turn was written over: {writes}")
    evs = gw._fail_events(tr, rec)
    assert evs[-2]["code"] == "harness_error"
    assert evs[-1]["response"]["error"] == gw._cap_error()


def test_a_turn_inside_the_cap_starts_as_before(monkeypatch):
    status, rec, writes, calls, _tr = _drive_a_late_turn(monkeypatch, age_s=1)
    assert "/turn" in calls and status == "completed" and "error" not in rec


def test_a_restore_that_hung_past_the_cap_ends_the_turn_before_the_agent_starts(monkeypatch):
    """The turn began inside the cap and its restore hung past it: it stops before the agent starts."""
    async def _slow_hydrate(sid, rec):
        await asyncio.sleep(2.5)
    status, rec, writes, calls, _tr = _drive_a_late_turn(monkeypatch, age_s=1, hydrate=_slow_hydrate)
    assert "/turn" not in calls and status == "failed" and rec["error"] == gw._cap_error()
    assert writes[-1] == {"status": "failed", "turn_status": "failed", "end_reason": "timeout"}
