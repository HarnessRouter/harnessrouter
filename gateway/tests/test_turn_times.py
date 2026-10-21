"""The turns feed says when each turn began and ended (UHP 2026-10-19, Sessions §3).

GET /v1/sessions/{id}/turns carried no time on its rows, so a reader had to fetch each turn's
response for it. Every row now carries `created_at`, and `completed_at` (null while the turn runs,
or when nobody knows when it ended), both in Unix seconds like every other time in the protocol,
read from the turn's own record: no read per row. The share view reads the same rows.
"""
import asyncio
import json
import os
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

BORN = 1792384812.25            # 2026-10-19T04:40:12.25Z
SECS = 1792384812
_n = [0]


class Store:
    """The response records and their index rows, in memory."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.rows: dict[str, dict] = {}

    async def blob_put(self, key, data, kb=None):
        self.blobs[key] = data
        return True

    async def blob_get(self, key, kb=None):
        return self.blobs.get(key)

    async def vg_upsert(self, label, vid, props, raise_on_fail=False):
        self.rows.setdefault(vid, {"id": vid}).update(props)

    async def find(self, label, props):
        return [dict(r) for r in self.rows.values() if r.get("session_id") == props.get("session_id")]

    find_strict = find

    def record(self, rid: str) -> dict:
        return json.loads(self.blobs[f"responses/{rid}.json"])


@pytest.fixture
def store(monkeypatch):
    s = Store()
    monkeypatch.setattr(A, "_blob_put", s.blob_put)
    monkeypatch.setattr(A, "_blob_get", s.blob_get)
    monkeypatch.setattr(A, "_blob_get_or_raise", s.blob_get)
    monkeypatch.setattr(A, "_vg_upsert", s.vg_upsert)
    monkeypatch.setattr(A.BACKING, "graph", s, raising=False)

    async def vertex_get(sid):
        return {"status": "running"}
    monkeypatch.setattr(A, "_vertex_get", vertex_get)
    monkeypatch.setattr(A, "_prefix_from_vertex", lambda sid, v: None)
    return s


def _ids() -> tuple[str, str]:
    _n[0] += 1
    return f"hsess_times{_n[0]}", f"resp_times{_n[0]}"


def _record(rid: str, sid: str, status: str, created_at: float = BORN) -> dict:
    return {"id": rid, "object": "response", "created_at": int(created_at), "status": status, "error": None,
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}]
            if status == "completed" else [],
            "_session_id": sid, "_org": "org.times", "_input": [{"role": "user", "content": "hello"}]}


def _put(rid, sid, status, created_at=BORN):
    return A._resp_put(rid, _record(rid, sid, status, created_at), "org.times", sid, None, status, created_at, True)


def _feed(sid):
    return asyncio.run(A._session_turns_data(sid))["turns"]


def test_a_row_carries_created_at_and_completed_at_once_the_turn_is_done(store):
    sid, rid = _ids()
    asyncio.run(_put(rid, sid, "running"))
    before = time.time()
    asyncio.run(_put(rid, sid, "completed"))
    after = time.time()
    (row,) = _feed(sid)
    assert row["status"] == "completed"
    assert row["created_at"] == SECS and type(row["created_at"]) is int
    stamp = store.record(rid)["_completed_at"]
    assert before <= stamp <= after
    assert type(row["completed_at"]) is int and row["completed_at"] == int(stamp)
    assert row["completed_at"] >= row["created_at"]
    # the stamp stays internal: the response object never shows it
    assert "_completed_at" not in A._strip_internal(store.record(rid))


def test_a_running_turn_has_completed_at_null(store):
    sid, rid = _ids()
    asyncio.run(_put(rid, sid, "running"))
    (row,) = _feed(sid)
    assert row["status"] == "running"
    assert row["created_at"] == SECS and row["completed_at"] is None
    assert "_completed_at" not in store.record(rid)


def test_a_cancel_that_latches_the_record_says_when_the_turn_ended(store, monkeypatch):
    """A cancel that cannot prove it owns the live turn latches the record itself: that is its end."""
    sid, rid = _ids()
    asyncio.run(_put(rid, sid, "running"))

    async def principal(request):
        return {"org": "org.times"}

    async def in_reach(principal, rec):
        return True

    async def vertex_get(sid):
        return {"status": "done"}          # the sandbox is not on this turn: no fast path
    monkeypatch.setattr(A, "_principal", principal)
    monkeypatch.setattr(A, "_response_in_reach", in_reach)
    monkeypatch.setattr(A, "_vertex_get", vertex_get)
    monkeypatch.setattr(A.control_store, "enabled", lambda: False)
    before = time.time()
    out = asyncio.run(A.cancel_response(rid, None))
    assert out["status"] == "cancelled" and "_completed_at" not in out
    stamp = store.record(rid)["_completed_at"]
    assert before <= stamp <= time.time()
    (row,) = _feed(sid)
    assert row["status"] == "cancelled" and row["completed_at"] == int(stamp)


def test_a_record_that_never_said_when_it_ended_reads_null_and_its_birth_falls_back_to_the_index(store):
    sid, rid = _ids()
    old = {k: v for k, v in _record(rid, sid, "completed").items() if k != "created_at"}   # before either field
    store.blobs[f"responses/{rid}.json"] = json.dumps(old).encode()
    store.rows[rid] = {"id": rid, "session_id": sid, "status": "completed", "created_at": str(BORN)}
    (row,) = _feed(sid)
    assert row["created_at"] == SECS and row["completed_at"] is None


def test_the_share_view_carries_the_same_fields(store, monkeypatch):
    sid, rid = _ids()
    asyncio.run(_put(rid, sid, "completed"))

    async def share_sid(token):
        return sid if token == "tok" else None
    monkeypatch.setattr(A, "_share_sid", share_sid)
    (row,) = asyncio.run(A.share_turns("tok"))["turns"]
    assert row["created_at"] == SECS and type(row["completed_at"]) is int
    assert row == _feed(sid)[0]


def test_the_time_form():
    assert A._unix_s(BORN) == SECS and A._unix_s(str(BORN)) == SECS and A._unix_s(SECS) == SECS
    assert A._unix_s(None) is None and A._unix_s(0) is None and A._unix_s("x") is None
    assert A._unix_s(float("inf")) is None and A._unix_s(float("nan")) is None


def test_the_rows_match_the_protocols_turn_item(store):
    """What the conformance suite checks (Sessions §3): the rows, running and done, against TurnItem."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((pathlib.Path(__file__).resolve().parents[2] / "protocol" / "conformance"
                         / "uhp_conformance" / "uhp-2026-10-19.schema.json").read_text())
    props = schema["$defs"]["TurnItem"]["properties"]
    assert props["created_at"]["type"] == "integer" and props["completed_at"]["type"] == ["integer", "null"]
    sid, done = _ids()
    _, live = _ids()
    asyncio.run(_put(done, sid, "completed"))
    asyncio.run(_put(live, sid, "running", created_at=BORN + 5))
    rows = _feed(sid)
    assert [r["completed_at"] is None for r in rows] == [False, True]
    v = jsonschema.Draft202012Validator({**schema, "$ref": "#/$defs/TurnItem"})
    for r in rows:
        assert not list(v.iter_errors(r)), r
