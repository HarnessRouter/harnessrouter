"""Finished response records and finished session cards are immutable, so they are served from
memory; live ones are read every time; every writer forgets what it writes."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def _blob_reader(store: dict, reads: list):
    async def get(file_id, kb=gw.BLOB_KB):
        reads.append(file_id)
        return store.get(file_id)
    return get


def test_terminal_response_record_is_read_once(monkeypatch):
    gw._RESP_CACHE.clear()
    reads = []
    store = {"responses/r1.json": json.dumps({"status": "completed", "output": []}).encode(),
             "responses/r2.json": json.dumps({"status": "running", "output": []}).encode()}
    monkeypatch.setattr(gw, "_blob_get", _blob_reader(store, reads))
    for _ in range(3):
        assert asyncio.run(gw._resp_get("r1"))["status"] == "completed"
        assert asyncio.run(gw._resp_get("r2"))["status"] == "running"
    assert reads.count("responses/r1.json") == 1 and reads.count("responses/r2.json") == 3
    gw._resp_cache_forget("r1")
    asyncio.run(gw._resp_get("r1"))
    assert reads.count("responses/r1.json") == 2


def test_deleted_record_is_never_cached(monkeypatch):
    gw._RESP_CACHE.clear()
    reads = []
    store = {"responses/r3.json": json.dumps({"status": "completed", "_deleted": True}).encode()}
    monkeypatch.setattr(gw, "_blob_get", _blob_reader(store, reads))
    assert asyncio.run(gw._resp_get("r3")) is None and "r3" not in gw._RESP_CACHE


def test_finished_card_is_read_once_and_a_live_card_every_time(monkeypatch):
    gw._CARD_CACHE.clear(); gw._SETTLE_LIVE_AT.clear()
    reads = []
    done = {"session_id": "hsessA", "status": "done", "harness_id": "codex", "trace_blob": "org/00000000000001_hsessA"}
    live = {"session_id": "hsessB", "status": "running", "harness_id": "codex", "trace_blob": "org/00000000000002_hsessB"}
    store = {"org/idx/00000000000001_hsessA.json": json.dumps(done).encode(),
             "org/idx/00000000000002_hsessB.json": json.dumps(live).encode()}
    monkeypatch.setattr(gw, "_blob_get", _blob_reader(store, reads))
    async def blist(prefix, limit=20, cursor=None):
        return {"items": [{"file_id": k} for k in store], "cursor": ""}
    monkeypatch.setattr(gw, "_blob_list", blist)
    settles = []
    async def settle(sid, m):
        settles.append(sid)
        return None                       # genuinely live
    monkeypatch.setattr(gw, "_card_settle", settle)
    for _ in range(3):
        out = asyncio.run(gw._session_cards("org", 20, "", "", ""))
        assert {c["session_id"] for c in out["sessions"]} == {"hsessA", "hsessB"}
    assert reads.count("org/idx/00000000000001_hsessA.json") == 1
    assert reads.count("org/idx/00000000000002_hsessB.json") == 3
    assert settles == ["hsessB"]          # settled once, then trusted live for a while
    gw._SETTLE_LIVE_AT.clear()
    asyncio.run(gw._session_cards("org", 20, "", "", ""))
    assert settles == ["hsessB", "hsessB"]


def test_manifest_write_and_delete_forget_the_card(monkeypatch):
    gw._CARD_CACHE.clear()
    gw._CARD_CACHE["org/idx/x.json"] = {"status": "done"}
    class B:
        async def delete(self, kb, file_id):
            return True
    monkeypatch.setattr(gw.BACKING, "blob", B())
    asyncio.run(gw._blob_delete("org/idx/x.json", kb=gw.TRACE_KB))
    assert "org/idx/x.json" not in gw._CARD_CACHE
    gw._card_cache_forget("nothing")     # forgetting an absent key is fine
