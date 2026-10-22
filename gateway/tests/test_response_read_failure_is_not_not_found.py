"""A turn's record that could not be read is never answered response_not_found.

`GET /v1/responses/{id}` is, in `_reconcile_response`'s own words, "the ONLY completion signal a
background poller has". It read the record through `_resp_get` without `strict`, and the normal read
paths swallow errors and return empty (`backing.py`: "the normal read paths swallow errors and return
empty"), so a store that could not answer looked exactly like a turn that does not exist and the route
answered 404 response_not_found — a permanent answer to a transient failure.

What these pin, on the self-hosted file blob store itself:
  a record whose read FAILS answers 503 server_error, never 404 response_not_found;
  a record that is genuinely NOT THERE still answers 404 response_not_found.
The second is the point: the fix must not turn the legitimate not-found path into a failure.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402
import backing  # noqa: E402

ORG = "local"
_n = [0]


@pytest.fixture
def stores(monkeypatch, tmp_path):
    graph = backing.SqliteGraphStore(str(tmp_path / "graph.db"))
    blob = backing.FileBlobStore(str(tmp_path / "blobs"))
    monkeypatch.setattr(gw.BACKING, "graph", graph)
    monkeypatch.setattr(gw.BACKING, "blob", blob)
    monkeypatch.setattr(gw, "_prefix_from_vertex", lambda sid, v: None)
    monkeypatch.setattr(gw, "VG_GATEWAY_URL", "")

    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    return graph, blob, tmp_path


def _turn() -> tuple[str, str]:
    """One finished turn, written the way a turn writes it, with nothing cached in memory."""
    _n[0] += 1
    sid = f"hsessrespread{_n[0]}{os.urandom(3).hex()}"
    rid = f"resp_respread{_n[0]}{os.urandom(3).hex()}"
    rec = {"id": rid, "object": "response", "created_at": 1792560576, "status": "completed",
           "error": None, "_session_id": sid, "_org": ORG,
           "_input": [{"role": "user", "content": "ask"}],
           "output": [{"type": "message", "role": "assistant",
                       "content": [{"type": "output_text", "text": "answer"}]}]}
    asyncio.run(gw._resp_put(rid, rec, ORG, sid, None, "completed", 1792560576.0, True))
    asyncio.run(gw._vertex_upsert(sid, {"tenant": ORG, "status": "done", "turn_status": "done",
                                        "member_id": "me@local", "running_response_id": rid}))
    gw._resp_cache_forget(rid)
    return sid, rid


def _unreadable(tmp_path: Path, rid: str) -> None:
    """The record's file is there and cannot be read (a directory in its place: EISDIR, as EIO or
    EMFILE would be) — not the same thing as a record that is not there."""
    p = tmp_path / "blobs" / gw.RESP_BLOB_KB / "responses" / f"{rid}.json"
    p.rename(p.with_suffix(".aside"))
    p.mkdir()


def test_a_turn_reads_back(stores):
    _, rid = _turn()
    r = TestClient(gw.app).get(f"/v1/responses/{rid}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == rid and r.json()["status"] == "completed"


def test_a_record_that_cannot_be_read_is_not_answered_not_found(stores):
    _, _, tmp = stores
    _, rid = _turn()
    _unreadable(tmp, rid)
    r = TestClient(gw.app).get(f"/v1/responses/{rid}")
    assert r.status_code == 503, r.text
    err = r.json()["error"]
    assert err["type"] == "server_error" and err["code"] == "server_error"
    assert err["code"] != "response_not_found"
    assert err["message"] == "This response could not be read just now. Try again in a moment."


def test_a_response_that_is_not_there_is_still_not_found(stores):
    _turn()                                     # a real turn exists; this id is not it
    r = TestClient(gw.app).get("/v1/responses/resp_nosuchrecordatall")
    assert r.status_code == 404, r.text
    err = r.json()["error"]
    assert err["code"] == "response_not_found" and err["param"] == "response_id"
