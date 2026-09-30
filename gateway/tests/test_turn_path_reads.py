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


def test_finalize_keeps_a_chosen_title_and_carries_the_flag(monkeypatch):
    """PATCH /v1/sessions names a session; the turn's finish used to rename it after the message
    it answered. The terminal card keeps the chosen title and the flag that marks it chosen."""
    gw._CARD_CACHE.clear()
    puts = []
    prior = {"session_id": "hsessT", "title": "Direct message · Ada", "title_custom": "1",
             "harness_id": "chrnabc", "member_id": "m@x", "workspace": "ws1", "credits": 1.0, "usage": {}}
    async def bget(file_id, kb=gw.BLOB_KB):
        return json.dumps(prior).encode()
    async def blist(prefix, kb=gw.BLOB_KB):
        return []
    async def bdel(file_id, kb=gw.BLOB_KB):
        return True
    async def vget(sid):
        return {"status": "done"}
    async def tput(key, data):
        puts.append((key, json.loads(data)))
        return True
    async def pricing():
        return None
    monkeypatch.setattr(gw, "_blob_get", bget)
    monkeypatch.setattr(gw, "_blob_list_all", blist)
    monkeypatch.setattr(gw, "_blob_delete", bdel)
    monkeypatch.setattr(gw, "_vertex_get", vget)
    monkeypatch.setattr(gw, "_trace_put", tput)
    monkeypatch.setattr(gw, "_refresh_pricing_table", pricing)
    monkeypatch.setitem(gw._session_trace, "hsessT", {"prefix": "org.x/00000000000009_hsessT", "org": "org.x",
                                                        "member": "m@x", "harness_id": "chrnabc", "workspace": "ws1"})
    asyncio.run(gw._trace_finalize("hsessT", {"user_text": "What was the haiku again?", "status": "completed",
                                                 "output": [], "usage": {}, "model": "gpt-5.5"}))
    assert puts, "the terminal card was written"
    for _, m in puts:
        assert m["title"] == "Direct message · Ada" and m["title_custom"] == "1" and m["status"] == "completed"


def test_finalize_names_an_unnamed_session_after_the_message(monkeypatch):
    gw._CARD_CACHE.clear()
    puts = []
    async def bget(file_id, kb=gw.BLOB_KB):
        return None
    async def blist(prefix, kb=gw.BLOB_KB):
        return []
    async def bdel(file_id, kb=gw.BLOB_KB):
        return True
    async def vget(sid):
        return {"status": "done"}
    async def tput(key, data):
        puts.append((key, json.loads(data)))
        return True
    async def pricing():
        return None
    monkeypatch.setattr(gw, "_blob_get", bget)
    monkeypatch.setattr(gw, "_blob_list_all", blist)
    monkeypatch.setattr(gw, "_blob_delete", bdel)
    monkeypatch.setattr(gw, "_vertex_get", vget)
    monkeypatch.setattr(gw, "_trace_put", tput)
    monkeypatch.setattr(gw, "_refresh_pricing_table", pricing)
    monkeypatch.setitem(gw._session_trace, "hsessU", {"prefix": "org.x/00000000000009_hsessU", "org": "org.x",
                                                        "member": "m@x", "harness_id": "chrnabc", "workspace": "ws1"})
    asyncio.run(gw._trace_finalize("hsessU", {"user_text": "Plan the launch\nin two lines", "status": "completed",
                                                 "output": [], "usage": {}, "model": "gpt-5.5"}))
    assert puts and all(m["title"] == "Plan the launch" and "title_custom" not in m for _, m in puts)
