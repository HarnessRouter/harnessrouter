"""A transcript is never served SHORT because a chunk read failed.

`GET /v1/traces/{sid}/all` joins the session's event chunks. The join skipped any chunk that came
back empty, so a chunk the store could not read was dropped and the route answered 200 with a
transcript missing the middle of the run — while the CACHE beside it already refused to store
exactly that join ("a transient chunk-get failure must never become a permanently-truncated
authoritative transcript"). What these pin, on the self-hosted file store where a read can really
fail (a directory where the object's file belongs: EISDIR, as EIO or EMFILE would be):
  a chunk that cannot be read is said (503 server_error, the protocol's code), never a short 200;
  every chunk readable still reads back the WHOLE transcript, in chunk order, compact and full;
  a chunk that is simply NOT THERE is still not a failure — the join carries on, as before.
"""
from __future__ import annotations

import asyncio
import json
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
    monkeypatch.setattr(gw.BACKING, "graph", backing.SqliteGraphStore(str(tmp_path / "graph.db")))
    monkeypatch.setattr(gw.BACKING, "blob", backing.FileBlobStore(str(tmp_path / "blobs")))
    monkeypatch.setattr(gw, "VG_GATEWAY_URL", "")

    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    return tmp_path


def _event(i: int) -> bytes:
    return json.dumps({"type": "message", "seq": i}).encode() + b"\n"


def _trace(chunks: list[bytes], status: str = "done") -> tuple[str, str, list[str]]:
    """A session whose events/ holds `chunks`, written as a turn writes them. Returns
    (sid, base, chunk keys in order)."""
    _n[0] += 1
    sid = f"hsesstrall{_n[0]}{os.urandom(3).hex()}"
    base = f"{ORG}/0000_{sid}"
    keys = []
    for i, c in enumerate(chunks):
        key = f"{base}/events/{1792560576000 + i}-aaaa-{i}-{c.count(b'\n')}.jsonl"
        assert asyncio.run(gw._blob_put(key, c, kb=gw.TRACE_KB))
        keys.append(key)
    asyncio.run(gw._blob_put(gw._manifest_key(base), json.dumps({"status": status}).encode(),
                             kb=gw.TRACE_KB))
    asyncio.run(gw._vertex_upsert(sid, {"tenant": ORG, "status": status, "trace_blob": base,
                                        "member_id": "me@local"}))
    return sid, base, keys


def _unreadable(tmp_path: Path, key: str) -> None:
    """The chunk's object is there, is LISTED, and cannot be read (EACCES, as EIO or EMFILE would
    be): not the same thing as a chunk that is not there."""
    (tmp_path / "blobs" / gw.TRACE_KB / key).chmod(0o000)


def test_a_whole_transcript_reads_back_whole(stores):
    chunks = [_event(0) + _event(1), _event(2), _event(3)]
    sid, _, _ = _trace(chunks)
    api = TestClient(gw.app)
    r = api.get(f"/v1/traces/{sid}/all")
    assert r.status_code == 200, r.text
    assert r.content == b"".join(chunks)
    assert [json.loads(ln)["seq"] for ln in r.content.splitlines()] == [0, 1, 2, 3]
    assert len(api.get(f"/v1/traces/{sid}/all?compact=1").content.splitlines()) == 4


def test_a_chunk_that_cannot_be_read_is_said_never_a_short_transcript(stores):
    tmp = stores
    chunks = [_event(0), _event(1), _event(2)]
    sid, base, keys = _trace(chunks)
    _unreadable(tmp, keys[1])
    r = TestClient(gw.app).get(f"/v1/traces/{sid}/all")
    assert r.status_code == 503, f"{r.status_code} {r.content!r}"
    err = r.json()["error"]
    assert err["type"] == "server_error" and err["code"] == "server_error"
    assert err["message"] == "This transcript could not be loaded just now. Try again in a moment."
    # and nothing was cached from the failed join
    assert asyncio.run(gw._blob_get(f"{base}/all.jsonl", kb=gw.TRACE_KB)) is None
    assert TestClient(gw.app).get(f"/v1/traces/{sid}/all?compact=1").status_code == 503


def test_a_chunk_that_is_not_there_is_still_not_a_failure(stores):
    """The join falls back to a SYNTHESIZED key when the listing comes back empty, and that key
    names an object that is not there. That is an empty transcript, not a failure."""
    sid, _, _ = _trace([])
    r = TestClient(gw.app).get(f"/v1/traces/{sid}/all")
    assert r.status_code == 200, f"{r.status_code} {r.content!r}"
    assert r.content == b""


def test_an_empty_but_readable_chunk_is_not_a_failure(stores, monkeypatch):
    """A chunk read that SUCCEEDS with no bytes contributes nothing to the join and is not the
    failure above. The writer never emits one (_trace_flush writes only a non-empty chunk, always
    newline-terminated) and FileBlobStore.put refuses empty data, so this drives the store
    directly — the point is that the strict read leaves the empty case exactly as it was."""
    chunks = [_event(0), _event(1)]
    sid, _, keys = _trace(chunks)
    real = gw.BACKING.blob.get_or_raise

    async def get_or_raise(kb, file_id):
        return b"" if file_id == keys[0] else await real(kb, file_id)
    monkeypatch.setattr(gw.BACKING.blob, "get_or_raise", get_or_raise)
    r = TestClient(gw.app).get(f"/v1/traces/{sid}/all")
    assert r.status_code == 200, f"{r.status_code} {r.content!r}"
    assert r.content == chunks[1]
