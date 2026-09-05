"""A task card that still says running repairs itself from the session vertex on the next list."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def _wire(monkeypatch, vertex, indexed):
    async def vget(sid): return vertex
    async def index(base, m): indexed.append((base, dict(m)))
    monkeypatch.setattr(gw, "_vertex_get", vget)
    monkeypatch.setattr(gw, "_index_manifest", index)
    monkeypatch.setattr(gw, "_prefix_from_vertex", lambda sid, v: "org/1_sid")


def test_a_terminal_vertex_settles_the_card(monkeypatch):
    indexed = []
    _wire(monkeypatch, {"status": "failed", "turn_status": "failed", "heartbeat": str(time.time())}, indexed)
    m = asyncio.run(gw._card_settle("sid", {"session_id": "sid", "status": "running"}))
    assert m["status"] == "failed"
    assert indexed and indexed[0][1]["status"] == "failed", "every mirror is rewritten"


def test_a_live_turn_is_left_alone(monkeypatch):
    indexed = []
    _wire(monkeypatch, {"status": "running", "turn_status": "running", "heartbeat": str(time.time())}, indexed)
    assert asyncio.run(gw._card_settle("sid", {"session_id": "sid", "status": "running"})) is None
    assert not indexed


def test_a_dead_heartbeat_past_the_cap_reads_failed(monkeypatch):
    indexed = []
    _wire(monkeypatch, {"status": "running", "turn_status": "running", "heartbeat": str(time.time() - gw._GW_MAX_TURN_S - 5)}, indexed)
    m = asyncio.run(gw._card_settle("sid", {"session_id": "sid", "status": "running"}))
    assert m["status"] == "failed" and indexed


def test_an_already_matching_card_is_not_rewritten(monkeypatch):
    indexed = []
    _wire(monkeypatch, {"status": "failed", "turn_status": "failed"}, indexed)
    assert asyncio.run(gw._card_settle("sid", {"session_id": "sid", "status": "failed"})) is None
    assert not indexed
