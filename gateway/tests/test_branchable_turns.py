"""A session's turns say which of them can be branched (`branchable`), by the branch route's own test.

The console offered Branch on every finished reply, and the route refused it (409 branch_unavailable)
for every reply with no branch point: each one from before branching, one whose checkpoint wasn't
kept, an imported one. Both now answer from one function, _branch_point_of, so for any turn the
route's decision is the field. A record written since records carry their point answers it from
itself; an older one reads its point once, in parallel with the others, and keeps the answer.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw

OUT = [{"id": "msg_0", "type": "message", "status": "completed", "role": "assistant",
        "content": [{"type": "output_text", "text": "answer", "annotations": []}]}]


@pytest.fixture
def env(monkeypatch):
    suffix = uuid.uuid4().hex
    org, hid = "org.branchable." + suffix, "chrn_" + suffix
    calls = []

    async def principal(_):
        return {"org": org, "member": "fixture@example.invalid"}

    async def chain(*_, **__):
        return ["fixture"]

    async def execute(tr, **kwargs):
        calls.append("execute")
        tr.output.append(OUT[0])
        return "completed", [], {"status": "done"}

    async def hydrate(target, params, *, source_sid=None):
        calls.append("restore")
        return httpx.Response(200, json={"ok": True, "restored": True, "branched": True})

    async def checkpoint(_, commit=True):
        return True, 100, "target-sha", "a" * 7, "a" * 40

    async def none(*_, **__):
        return None

    monkeypatch.setattr(gw, "_mapped_integration_conn", none)
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    monkeypatch.setattr(gw, "_resp_execute", execute)
    monkeypatch.setattr(gw, "_hydrate_relay", hydrate)
    monkeypatch.setattr(gw, "_checkpoint_relay", checkpoint)
    asyncio.run(gw.BACKING.graph.upsert("Harness", hid, {
        "org": org, "member": "fixture@example.invalid", "workspace": "", "name": hid,
        "base": "claude-code", "custom": "1", "deleted": "0"}))
    return {"client": TestClient(gw.app), "org": org, "hid": hid, "calls": calls, "n": 0}


def point_of(rid: str, sid: str, commit: str = "1" * 40) -> dict:
    return {"commit": commit, "ws_sha": "sha", "session_id": sid, "response_id": rid, "backend": ""}


def seed(env, *, status: str = "completed", mark=..., stored=None, imported: bool = False) -> tuple[str, str]:
    """A session of one reply. `mark`: what the record says of its point (`_branch_point`), left out
    for a record from before records said so. `stored`: the point kept in the store, if any."""
    env["n"] += 1
    sid, rid = f"hsess{uuid.uuid4().hex}", f"resp_{uuid.uuid4().hex}"

    async def go():
        await gw._vertex_upsert(sid, {"tenant": env["org"], "status": "done", "harness_id": env["hid"],
                                     "ws_sha": "sha", "workspace": "", "backend": "claude"})
        record = {"id": rid, "status": status, "_session_id": sid, "_org": env["org"],
                  "_input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
                  "output": OUT, "metadata": {"session_id": sid}, "model": "claude"}
        if mark is not ...:
            record["_branch_point"] = mark(rid, sid) if callable(mark) else mark
        if imported:
            record["_imported"] = True
        await gw._resp_put(rid, record, env["org"], sid, None, status, 1000.0, True)
        if stored is not None:
            await gw._blob_put(gw._branch_point_key(rid), json.dumps(stored(rid, sid)).encode(), kb=gw.RESP_BLOB_KB)
    asyncio.run(go())
    return sid, rid


def turn_of(env, sid: str, rid: str) -> dict:
    response = env["client"].get(f"/v1/sessions/{sid}/turns")
    assert response.status_code == 200, response.text
    return next(t for t in response.json()["turns"] if t["id"] == rid)


def branch(env, rid: str) -> httpx.Response:
    return env["client"].post("/v1/responses", json={"input": "another way", "branch": True,
                                                     "previous_response_id": rid,
                                                     "metadata": {"harness_id": env["hid"]}})


# (case, how the reply is kept, whether a branch can be made from it)
CASES = [
    ("from before branching: no point anywhere", {}, False),
    ("from before records carried their point, its point in the store", {"stored": point_of}, True),
    ("its record carries its point", {"mark": point_of}, True),
    ("its checkpoint kept no point, a stale one in the store", {"mark": None, "stored": point_of}, False),
    ("still running, with a point", {"status": "in_progress", "mark": point_of, "stored": point_of}, False),
    ("failed, with a point", {"status": "failed", "mark": point_of}, True),
    ("cancelled, with a point", {"status": "cancelled", "mark": point_of}, True),
    ("incomplete, with a point", {"status": "incomplete", "mark": point_of}, True),
    ("one the task was started with", {"imported": True, "stored": point_of}, False),
    ("its stored point is not a full commit", {"stored": lambda r, s: point_of(r, s, "invalid")}, False),
    ("its record names another session's point", {"mark": lambda r, s: point_of(r, "hsess_other")}, False),
]


@pytest.mark.parametrize("case,kept,can", CASES, ids=[c[0] for c in CASES])
def test_the_route_decides_as_the_turn_says(env, case, kept, can):
    sid, rid = seed(env, **kept)
    said = turn_of(env, sid, rid)["branchable"]
    assert said is can, case
    response = branch(env, rid)
    if can:
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["branched_from"] == rid
    else:
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "branch_unavailable"
        assert not env["calls"], "a refused branch did work first"
    # and the route's decision is the field, whatever the case
    assert (response.status_code == 200) is said


def test_a_reply_from_before_checkpoints_is_false(env):
    sid, rid = seed(env)
    assert turn_of(env, sid, rid)["branchable"] is False


def test_a_completed_reply_with_a_checkpoint_is_true(env):
    sid, rid = seed(env, mark=point_of)
    assert turn_of(env, sid, rid)["branchable"] is True


def test_a_running_reply_is_false(env):
    sid, rid = seed(env, status="in_progress", mark=point_of, stored=point_of)
    assert turn_of(env, sid, rid)["branchable"] is False


def test_a_record_that_carries_its_point_is_answered_with_no_read(env, monkeypatch):
    sid, rid = seed(env, mark=point_of)
    real = gw._blob_get_or_raise

    async def watched(key, kb=gw.BLOB_KB):
        assert not key.startswith("branch-points/"), "read a point the record already carries"
        return await real(key, kb=kb)

    monkeypatch.setattr(gw, "_blob_get_or_raise", watched)
    assert turn_of(env, sid, rid)["branchable"] is True
    assert branch(env, rid).status_code == 200


def test_an_older_records_point_is_read_once_then_kept(env, monkeypatch):
    sid, rid = seed(env, stored=point_of)
    reads = []
    real = gw._blob_get_or_raise

    async def counted(key, kb=gw.BLOB_KB):
        if key.startswith("branch-points/"):
            reads.append(key)
        return await real(key, kb=kb)

    monkeypatch.setattr(gw, "_blob_get_or_raise", counted)
    assert [turn_of(env, sid, rid)["branchable"] for _ in range(3)] == [True, True, True]
    assert reads == [gw._branch_point_key(rid)]


def test_a_point_that_could_not_be_read_is_not_offered_and_not_kept(env, monkeypatch):
    sid, rid = seed(env, stored=point_of)
    real = gw._blob_get_or_raise
    down = {"on": True}

    async def flaky(key, kb=gw.BLOB_KB):
        if key.startswith("branch-points/") and down["on"]:
            raise RuntimeError("store unavailable")
        return await real(key, kb=kb)

    monkeypatch.setattr(gw, "_blob_get_or_raise", flaky)
    assert turn_of(env, sid, rid)["branchable"] is False   # the conversation still reads
    down["on"] = False
    assert turn_of(env, sid, rid)["branchable"] is True


def test_a_turns_end_keeps_its_point_on_its_record(env, monkeypatch):
    """The turn's end-of-turn checkpoint answers the point it kept; the record written as the turn
    ends carries it, so its turns are answered from the record."""
    async def execute(tr, *, sid, **_):
        rec = {"backend": "claude"}
        # what _resp_execute does as the turn ends
        tr.ended_checkpoint(await gw._checkpoint(sid, rec, response_id=tr.resp_id))
        tr.output.append(OUT[0])
        return "completed", [], {"status": "done"}

    monkeypatch.setattr(gw, "_resp_execute", execute)
    response = env["client"].post("/v1/responses", json={"input": "hi", "metadata": {"harness_id": env["hid"]}})
    assert response.status_code == 200, response.text
    rid, sid = response.json()["id"], response.json()["metadata"]["session_id"]
    record = asyncio.run(gw._resp_get(rid))
    assert record["_branch_point"] == {"commit": "a" * 40, "ws_sha": "target-sha", "session_id": sid,
                                       "response_id": rid, "backend": "claude"}
    assert turn_of(env, sid, rid)["branchable"] is True


def test_a_translator_says_nothing_of_a_point_before_its_checkpoint_ran():
    tr = gw._RespTranslator("resp_t", "m", None, True, 0.0)
    assert tr.branch_mark() == {}
    tr.ended_checkpoint(None)
    assert tr.branch_mark() == {"_branch_point": None}


def test_a_deleted_reply_restored_is_not_branchable(env, monkeypatch):
    """A delete removes the point; a restore within the 30 days brings back the record, not the point."""
    sid, rid = seed(env, mark=point_of, stored=point_of)
    assert env["client"].delete(f"/v1/responses/{rid}").status_code in (200, 204)
    asyncio.run(gw.retention_restore(gw.RetentionRestoreBody(kind="responses", id=rid)))
    assert turn_of(env, sid, rid)["branchable"] is False
    assert branch(env, rid).status_code == 409


def test_a_share_link_says_nothing_of_branching(env, monkeypatch):
    sid, rid = seed(env, mark=point_of)

    async def shared(_token):
        return sid

    monkeypatch.setattr(gw, "_share_sid", shared)
    turns = env["client"].get("/share/tok/turns").json()["turns"]
    assert turns and all("branchable" not in t for t in turns)
