"""A conversation is never answered as empty because a read failed (hosted, 2026-10-21: a finished task
showed as a new, empty one for about two minutes; its turns read 200 with none). A session's turns come
from the store's index and each turn's record, and a read of either that failed was answered as no turn
at all: the graph's find swallowed its error into [], a blob read its error into None. What these pin,
on the self-hosted stores themselves (SQLite and files) where they can be:
  the index or a record unreadable: the conversation and a shared link say so (503 server_error, the
  protocol's code), never fewer turns; a record that is simply not there is still no turn;
  a follow-up's history read that fails goes on (no turns), counted and logged;
  the session's current turn shows even when the index does not hold it, taken from the session;
  the record and its index entry are tried twice, a refused write counts as a failed one, and a failure
  is counted and never fails the turn."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402
import backing  # noqa: E402

ORG = "local"
_n = [0]


def _rec(rid: str, sid: str, text: str) -> dict:
    return {"id": rid, "object": "response", "created_at": 1792560576, "status": "completed", "error": None,
            "_session_id": sid, "_org": ORG, "_input": [{"role": "user", "content": f"ask {text}"}],
            "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]}


@pytest.fixture
def stores(monkeypatch, tmp_path):
    graph = backing.SqliteGraphStore(str(tmp_path / "graph.db"))
    blob = backing.FileBlobStore(str(tmp_path / "blobs"))
    monkeypatch.setattr(gw.BACKING, "graph", graph)
    monkeypatch.setattr(gw.BACKING, "blob", blob)
    monkeypatch.setattr(gw, "_turns_reads", gw._OpsDrops("turns", 60, tuple(gw._turns_reads.counts)))
    monkeypatch.setattr(gw, "_prefix_from_vertex", lambda sid, v: None)
    monkeypatch.setattr(gw, "VG_GATEWAY_URL", "")

    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    gw._SHARE_TOKEN_CACHE.clear()
    return graph, blob, tmp_path


def _task(turns: int = 2) -> tuple[str, list[str]]:
    """A finished task of `turns` turns, written the way a turn writes it."""
    _n[0] += 1
    sid = f"hsessturns{_n[0]}{os.urandom(3).hex()}"
    rids = [f"resp_turns{_n[0]}x{i}" for i in range(turns)]
    for i, rid in enumerate(rids):
        asyncio.run(gw._resp_put(rid, _rec(rid, sid, f"answer {i}"), ORG, sid, rids[i - 1] if i else None,
                                 "completed", 1792560576.0 + i, True))
    asyncio.run(gw._vertex_upsert(sid, {"tenant": ORG, "status": "done", "turn_status": "done",
                                        "member_id": "me@local", "running_response_id": rids[-1]}))
    for rid in rids:
        gw._resp_cache_forget(rid)          # a fresh gateway: no record served from memory
    return sid, rids


def _unreadable(tmp_path: Path, rid: str) -> Path:
    """The record's file is there and cannot be read (a directory in its place: EISDIR, as EIO or
    EMFILE would be): not the same thing as a record that is not there."""
    p = tmp_path / "blobs" / gw.RESP_BLOB_KB / "responses" / f"{rid}.json"
    p.rename(p.with_suffix(".aside"))
    p.mkdir()
    return p


def test_a_finished_task_reads_back_whole(stores):
    sid, rids = _task()
    r = TestClient(gw.app).get(f"/v1/sessions/{sid}/turns")
    assert r.status_code == 200, r.text
    assert [t["id"] for t in r.json()["turns"]] == rids and r.json()["turns"][-1]["assistant"] == "answer 1"


def test_a_record_that_cannot_be_read_is_said_never_a_shorter_conversation(stores):
    _, _, tmp = stores
    sid, rids = _task()
    _unreadable(tmp, rids[-1])
    api = TestClient(gw.app)
    r = api.get(f"/v1/sessions/{sid}/turns")
    assert r.status_code == 503, r.text
    err = r.json()["error"]
    assert err["type"] == "server_error" and err["code"] == "server_error"
    assert err["message"] == "This conversation could not be loaded just now. Try again in a moment."
    assert gw._turns_reads.counts["record_failed"] == 1
    # the shared link reads the same conversation, and says the same
    token = api.post(f"/v1/sessions/{sid}/share").json()["token"]
    assert api.get(f"/share/{token}/turns").status_code == 503


def test_a_record_that_is_not_there_is_still_no_turn(stores):
    _, _, tmp = stores
    sid, rids = _task()
    (tmp / "blobs" / gw.RESP_BLOB_KB / "responses" / f"{rids[0]}.json").unlink()
    r = TestClient(gw.app).get(f"/v1/sessions/{sid}/turns")
    assert r.status_code == 200 and [t["id"] for t in r.json()["turns"]] == rids[1:]
    assert gw._turns_reads.counts["record_failed"] == 0


def test_an_unreadable_index_is_said_to_a_reader_and_a_follow_ups_history_goes_on(stores, monkeypatch):
    sid, _ = _task()

    async def find_strict(label, eq=None, neq=None):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(gw.BACKING.graph, "find_strict", find_strict)
    r = TestClient(gw.app).get(f"/v1/sessions/{sid}/turns")
    assert r.status_code == 503 and r.json()["error"]["type"] == "server_error"
    assert gw._turns_reads.counts["index_failed"] == 1
    # a follow-up's history (not strict): no turns, counted, the follow-up runs
    assert asyncio.run(gw._session_turns_data(sid))["turns"] == []
    assert gw._turns_reads.counts["index_failed"] == 2


def test_the_sqlite_index_raises_when_it_cannot_answer_and_find_still_answers_empty(tmp_path):
    g = backing.SqliteGraphStore(str(tmp_path / "graph.db"))
    asyncio.run(g.upsert("HarnessResponse", "resp_a", {"session_id": "s1"}))
    assert [r["id"] for r in asyncio.run(g.find_strict("HarnessResponse", {"session_id": "s1"}))] == ["resp_a"]
    assert asyncio.run(g.find_strict("HarnessResponse", {"session_id": "s2"})) == []
    g._path = str(tmp_path)                 # a directory: SQLite cannot open it
    with pytest.raises(Exception):
        asyncio.run(g.find_strict("HarnessResponse", {"session_id": "s1"}))
    assert asyncio.run(g.find("HarnessResponse", {"session_id": "s1"})) == []


def test_the_file_store_tells_a_missing_object_from_an_unreadable_one(tmp_path):
    b = backing.FileBlobStore(str(tmp_path))
    assert asyncio.run(b.put("kb", "a/x.json", b"{}"))
    assert asyncio.run(b.get_or_raise("kb", "a/x.json")) == b"{}"
    assert asyncio.run(b.get_or_raise("kb", "a/none.json")) is None
    assert asyncio.run(b.get_or_raise("kb", "x.json/under-a-file")) is None   # a file where a folder would be
    assert asyncio.run(b.get_or_raise("kb", "../escape")) is None
    (tmp_path / "kb" / "a" / "dir.json").mkdir()
    with pytest.raises(backing.BlobUnavailable):
        asyncio.run(b.get_or_raise("kb", "a/dir.json"))
    assert asyncio.run(b.get("kb", "a/dir.json")) is None                     # get keeps its old answer


def test_the_current_turn_shows_from_the_session_when_the_index_does_not_hold_it(stores):
    graph, _, _ = stores
    sid, rids = _task()
    assert asyncio.run(graph.delete(rids[-1], "HarnessResponse"))            # its index write failed
    r = TestClient(gw.app).get(f"/v1/sessions/{sid}/turns")
    assert r.status_code == 200 and [t["id"] for t in r.json()["turns"]] == rids
    assert r.json()["turns"][-1]["assistant"] == "answer 1"
    assert gw._turns_reads.counts["from_session"] == 1
    # a turn the index holds is not added twice
    sid2, rids2 = _task()
    assert [t["id"] for t in TestClient(gw.app).get(f"/v1/sessions/{sid2}/turns").json()["turns"]] == rids2
    assert gw._turns_reads.counts["from_session"] == 1


def test_a_queued_turn_with_no_record_yet_is_not_counted(stores):
    sid, rids = _task(1)
    asyncio.run(gw._vertex_upsert(sid, {"running_response_id": "resp_queued", "status": "running"}))
    r = TestClient(gw.app).get(f"/v1/sessions/{sid}/turns")
    assert r.status_code == 200 and [t["id"] for t in r.json()["turns"]] == rids
    assert gw._turns_reads.counts["from_session"] == 0


def test_a_follow_ups_history_never_takes_the_new_turn_from_the_session(stores):
    graph, _, _ = stores
    sid, rids = _task()
    asyncio.run(graph.delete(rids[-1], "HarnessResponse"))
    assert [t["id"] for t in asyncio.run(gw._session_turns_data(sid))["turns"]] == rids[:1]


def test_the_record_and_its_index_entry_are_tried_twice_and_a_failure_never_fails_the_turn(stores, monkeypatch):
    calls = {"blob": 0, "idx": 0}
    answers = [False, True]                                        # refused once, then written

    async def blob_put(key, data, kb=None):
        calls["blob"] += 1
        return answers.pop(0)

    async def vg_upsert(label, vid, props, *, raise_on_fail=False):
        if label == "HarnessResponse":
            calls["idx"] += 1
            assert raise_on_fail
            raise HTTPException(502, "graph write failed")         # both tries fail

    async def nosleep(_s):
        return None
    monkeypatch.setattr(gw, "_blob_put", blob_put)
    monkeypatch.setattr(gw, "_vg_upsert", vg_upsert)
    monkeypatch.setattr(gw.asyncio, "sleep", nosleep)
    asyncio.run(gw._resp_put("resp_w", _rec("resp_w", "hsessw", "x"), ORG, "hsessw", None, "running", 1792560576.0, True))
    assert calls == {"blob": 2, "idx": 2}
    assert gw._turns_reads.counts["record_write_failed"] == 0 and gw._turns_reads.counts["index_write_failed"] == 1


def test_a_record_the_store_refuses_twice_is_counted(stores, monkeypatch):
    async def blob_put(key, data, kb=None):
        return False                                               # the store refused: put answers False

    async def nosleep(_s):
        return None
    monkeypatch.setattr(gw, "_blob_put", blob_put)
    monkeypatch.setattr(gw.asyncio, "sleep", nosleep)
    asyncio.run(gw._resp_put("resp_r", _rec("resp_r", "hsessr", "x"), ORG, "hsessr", None, "running", 1792560576.0, True))
    assert gw._turns_reads.counts["record_write_failed"] == 1


def test_readyz_counts_the_conversation_reads(stores):
    body = json.dumps(TestClient(gw.app).get("/readyz").json())
    assert '"turns_reads"' in body and '"record_failed"' in body
