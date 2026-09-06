"""The turn-start card costs one manifest read and no vertex read: the caller just wrote the vertex
and passes the prior card it read."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_running_card_reads_the_manifest_once_and_never_the_vertex(monkeypatch):
    gw._CARD_CACHE.clear()
    reads, vreads, puts = [], [], []
    prior = {"session_id": "hsessA", "title": "Deck", "title_custom": "1", "usage": {"credits": 3.5},
             "harness_id": "chrnabc", "member_id": "m@x", "workspace": "ws1"}
    async def bget(file_id, kb=gw.BLOB_KB):
        reads.append(file_id)
        return json.dumps(prior).encode()
    async def vget(sid):
        vreads.append(sid)
        return {"status": "running"}
    async def tput(key, data):
        puts.append((key, json.loads(data)))
        return True
    monkeypatch.setattr(gw, "_blob_get", bget)
    monkeypatch.setattr(gw, "_vertex_get", vget)
    monkeypatch.setattr(gw, "_trace_put", tput)
    tr = {"prefix": "org.x/00000000000009_hsessA", "member": "m@x", "harness_id": "chrnabc", "workspace": "ws1"}
    asyncio.run(gw._write_running_card(tr, sid="hsessA", org="org.x", member="m@x", harness_id="chrnabc",
                                       backend="codex", model="gpt-5.5", user_text="Change the color"))
    assert len(reads) == 1 and vreads == []
    assert puts and all(m["title"] == "Deck" and m["status"] == "running" for _, m in puts)


def test_index_manifest_still_guards_a_delete_when_not_known_live(monkeypatch):
    vreads, puts = [], []
    async def vget(sid):
        vreads.append(sid)
        return {"status": "deleted"}
    async def tput(key, data):
        puts.append(key)
        return True
    monkeypatch.setattr(gw, "_vertex_get", vget)
    monkeypatch.setattr(gw, "_trace_put", tput)
    asyncio.run(gw._index_manifest("org.x/1_hsessB", {"session_id": "hsessB", "status": "done"}, prior={}))
    assert vreads == ["hsessB"] and puts == []
