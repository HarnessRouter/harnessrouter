"""A change to a memory reaches whoever has it open: every writer, one place to tell it from, what a reconnecting
reader gets, and that a reader without the privilege gets nothing."""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import memory_fixture  # noqa: E402
import memory_live  # noqa: E402
import memory_plane  # noqa: E402

KEY = os.environ.get("HARNESS_INTERNAL_KEY", "")


def _h(member):
    return {"x-harness-internal": KEY, "x-harness-org": "acme", "x-harness-member": member}


@pytest.fixture(scope="module")
def c():
    memory_plane.PROVIDERS["fixture"] = memory_fixture.FixtureProvider()
    with TestClient(app.app) as client:
        yield client
    memory_plane.PROVIDERS.pop("fixture", None)


@pytest.fixture()
def mid(c):
    r = c.post("/v1/memories", json={"provider": "fixture", "name": "live"}, headers=_h("ada"))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def told(mid):
    ch = memory_live._channels.get(mid)
    return [e for e in (ch.kept if ch else [])]


def test_a_person_s_writes_are_told_and_say_who_not_what(c, mid):
    made = c.post(f"/v1/memories/{mid}/records", json={"type": "fact", "title": "Acme renews in March"}, headers=_h("ada")).json()
    c.patch(f"/v1/memories/{mid}/records/{made['id']}", json={"title": "Acme renews in April"}, headers=_h("ada"))
    c.delete(f"/v1/memories/{mid}/records/{made['id']}", headers=_h("ada"))
    kinds = [e["type"] for e in told(mid)]
    assert kinds == ["record.created", "record.revised", "record.forgotten"]
    for e in told(mid):
        assert e["record_id"] == made["id"] and e["written_by"]["id"] == "ada"
        assert "April" not in str(e) and "March" not in str(e), "an event names what changed, never what it says"


def test_a_revision_says_its_version_and_what_it_touched(c, mid):
    made = c.post(f"/v1/memories/{mid}/records", json={"type": "fact", "title": "one"}, headers=_h("ada")).json()
    out = c.patch(f"/v1/memories/{mid}/records/{made['id']}", json={"title": "two"}, headers=_h("ada")).json()
    ev = told(mid)[-1]
    assert ev["version"] == out["version"] and ev["fields"] == ["title"]


def test_a_failed_write_tells_nobody(c, mid):
    c.patch(f"/v1/memories/{mid}/records/hrec_nothing", json={"title": "x"}, headers=_h("ada"))
    assert told(mid) == []


def test_a_schema_change_is_told_where_a_provider_takes_one(c, mid):
    assert all(e["type"] != "schema.changed" for e in told(mid))


def test_every_provider_a_caller_gets_is_announced(c, mid):
    async def go():
        m = await memory_plane._load("acme", mid)
        return await memory_plane.provider_of(m)
    assert isinstance(asyncio.run(go()), memory_live.Announced)


def test_an_agent_s_tool_is_told_the_same_way(c, mid):
    # the tool's seam writes through the same provider_of, and marks the writer an agent
    async def go():
        m = await memory_plane._load("acme", mid)
        prov = await memory_plane.provider_of(m)
        return await memory_plane.remember(prov, mid, memory_plane._record_in({"type": "fact", "title": "from a tool"}),
                                            memory_plane.writer_of("agent:h1", agent=True))
    made = asyncio.run(go())
    ev = told(mid)[-1]
    assert ev["type"] == "record.created" and ev["record_id"] == made["id"]
    assert ev["written_by"]["type"] == "agent"


def _collect(mid, after, n, then=None):
    async def go():
        got = []
        it = memory_live.stream(mid, after, tick=0.05)
        try:
            async for ev in it:
                if ev is None:
                    if then is not None:
                        then()
                    if len(got) >= n:
                        return got
                    continue
                got.append(ev)
                if len(got) >= n:
                    return got
        finally:
            await it.aclose()
    return asyncio.run(asyncio.wait_for(go(), 5))


def test_a_reader_gets_what_happens_after_it_opens():
    mid = "hmem_a"
    fired = []

    def fire():
        if not fired:
            fired.append(1)
            memory_live.publish(mid, "record.revised", record_id="r1", version=2)
    got = _collect(mid, None, 1, then=fire)
    assert got[0]["record_id"] == "r1"


def test_a_reader_that_reconnects_gets_what_it_missed_and_nothing_twice():
    mid = "hmem_b"
    for i in range(5):
        memory_live.publish(mid, "record.revised", record_id=f"r{i}")
    got = _collect(mid, 3, 2)
    assert [e["record_id"] for e in got] == ["r3", "r4"]


def test_a_reader_from_before_a_restart_is_told_to_read_everything():
    mid = "hmem_c"
    memory_live.publish(mid, "record.revised", record_id="r0")
    got = _collect(mid, 900, 1)
    assert got[0]["type"] == "reset"


def test_a_reader_away_too_long_is_told_to_read_everything():
    mid = "hmem_d"
    for i in range(memory_live._KEPT + 10):
        memory_live.publish(mid, "record.revised", record_id=f"r{i}")
    got = _collect(mid, 2, 1)
    assert got[0]["type"] == "reset"


def test_a_reader_too_far_behind_is_told_to_read_everything_and_keeps_reading():
    mid = "hmem_e"

    async def go():
        it = memory_live.stream(mid, None, tick=0.05)
        first = asyncio.ensure_future(it.__anext__())
        await asyncio.sleep(0)
        for i in range(memory_live._BEHIND + 5):
            memory_live.publish(mid, "record.revised", record_id=f"r{i}")
        kinds = []
        ev = await first
        kinds.append(ev["type"] if ev else None)
        while "reset" not in kinds:
            ev = await it.__anext__()
            kinds.append(ev["type"] if ev else None)
        memory_live.publish(mid, "record.revised", record_id="after")
        # what came after the reset is still heard, up to the one published last
        ev = await it.__anext__()
        while ev is None or ev["record_id"] != "after":
            ev = await it.__anext__()
        await it.aclose()
        return kinds, ev
    kinds, ev = asyncio.run(asyncio.wait_for(go(), 5))
    assert "reset" in kinds and ev["record_id"] == "after"


def test_a_job_nobody_is_waiting_for_costs_the_provider_nothing(monkeypatch):
    asked = []

    class P:
        async def job(self, mid, job):
            asked.append(job)
            return {"status": "completed", "records": [{"id": "r1"}]}

    real = asyncio.sleep

    async def fast(_):
        await real(0)
    monkeypatch.setattr(memory_live.asyncio, "sleep", fast)
    monkeypatch.setattr(memory_live, "_JOB_MAX_S", 0.05)

    async def go():
        await memory_live._watch_job(P(), "hmem_f", "j1")
    asyncio.run(go())
    assert asked == []


def test_a_job_that_settles_tells_what_it_wrote(monkeypatch):
    mid = "hmem_g"

    class P:
        async def job(self, m, job):
            return {"status": "completed", "records": [{"id": "r1"}, {"id": "r2"}]}

    real = asyncio.sleep

    async def fast(_):
        await real(0)
    monkeypatch.setattr(memory_live.asyncio, "sleep", fast)

    async def go():
        ch = memory_live._channel(mid)
        ch.readers.add(asyncio.Queue())
        await memory_live._watch_job(P(), mid, "j2")
        return ch.kept[-1]
    ev = asyncio.run(go())
    assert ev["type"] == "records.changed" and ev["record_ids"] == ["r1", "r2"] and ev["status"] == "completed"


def test_a_reader_who_can_t_read_the_memory_gets_no_stream(c, mid):
    r = c.get(f"/v1/memories/{mid}/events", headers=_h("eve"))
    assert r.status_code in (403, 404)
    assert "text/event-stream" not in r.headers.get("content-type", "")


def test_a_memory_that_isn_t_there_gets_no_stream(c):
    r = c.get("/v1/memories/hmem_nothing/events", headers=_h("ada"))
    assert r.status_code == 404


def test_a_writer_who_read_an_old_version_is_refused_and_nothing_changes(c, mid):
    made = c.post(f"/v1/memories/{mid}/records", json={"type": "fact", "title": "one"}, headers=_h("ada")).json()
    moved = c.patch(f"/v1/memories/{mid}/records/{made['id']}", json={"title": "two"}, headers=_h("ada")).json()
    r = c.patch(f"/v1/memories/{mid}/records/{made['id']}", json={"title": "three"}, headers={**_h("ada"), "if-match": str(made["version"])})
    assert r.status_code == 412, r.text
    assert r.json()["error"]["code"] == "memory_version_moved"
    assert c.get(f"/v1/memories/{mid}/records/{made['id']}", headers=_h("ada")).json()["title"] == "two"
    ok = c.patch(f"/v1/memories/{mid}/records/{made['id']}", json={"title": "three"}, headers={**_h("ada"), "if-match": f'"{moved["version"]}"'})
    assert ok.status_code == 200 and ok.json()["title"] == "three"


def test_a_writer_who_names_no_version_still_writes(c, mid):
    made = c.post(f"/v1/memories/{mid}/records", json={"type": "fact", "title": "one"}, headers=_h("ada")).json()
    assert c.patch(f"/v1/memories/{mid}/records/{made['id']}", json={"title": "two"}, headers=_h("ada")).status_code == 200


def test_writers_on_one_record_go_one_at_a_time_and_the_second_sees_the_first():
    """A provider that takes its time: the second writer, who read the same version, must not land after the first
    and erase it."""
    order = []

    class Slow:
        version = 1

        async def get(self, mid, rid):
            return {"id": rid, "version": self.version}

        async def revise(self, mid, rid, patch, writer):
            order.append(("start", patch["title"]))
            await asyncio.sleep(0.05)
            self.version += 1
            order.append(("end", patch["title"]))
            return {"id": rid, "version": self.version}

    async def go():
        p = memory_live.Announced(Slow())
        first = asyncio.ensure_future(p.revise("hmem_x", "r", {"title": "a"}, {"id": "agent"}, expected=1))
        await asyncio.sleep(0)
        second = asyncio.ensure_future(p.revise("hmem_x", "r", {"title": "b"}, {"id": "person"}, expected=1))
        return await asyncio.gather(first, second, return_exceptions=True)
    a, b = asyncio.run(go())
    assert a["version"] == 2
    assert isinstance(b, memory_live.VersionMoved) and b.version == 2
    assert order == [("start", "a"), ("end", "a")]
    assert memory_live._locks == {}, "a lock outlives its writers"


def test_writers_on_different_records_don_t_wait_for_each_other():
    running = []

    class Slow:
        async def get(self, mid, rid):
            return None

        async def revise(self, mid, rid, patch, writer):
            running.append(rid)
            await asyncio.sleep(0.02)
            return {"id": rid, "version": 1, "seen": list(running)}

    async def go():
        p = memory_live.Announced(Slow())
        return await asyncio.gather(p.revise("m", "r1", {"t": 1}, {}), p.revise("m", "r2", {"t": 1}, {}))
    a, b = asyncio.run(go())
    assert set(b["seen"]) == {"r1", "r2"} or set(a["seen"]) == {"r1", "r2"}
