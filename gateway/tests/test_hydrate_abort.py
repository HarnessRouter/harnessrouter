"""A checkpoint that cannot be restored is tried once more, and a turn never runs on the wiped
workspace: under a burst of cold sessions one restore in ten to twenty failed and the conversation
started over without a word (2026-09-06); the checkpoint itself was intact every time."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


class _R:
    def __init__(self, status):
        self.status_code = status
        self.headers = {"content-type": "application/json"}
        self.text = "boom" if status >= 400 else ""
    def json(self):
        return {"ok": self.status_code < 400}


def _wire(monkeypatch, statuses):
    calls = []
    async def relay(sid, params):
        calls.append(sid)
        return _R(statuses[min(len(calls) - 1, len(statuses) - 1)])
    async def vertex(sid):
        return {"ws_sha": "abc123"}
    monkeypatch.setattr(gw, "_hydrate_relay", relay)
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    monkeypatch.setattr(gw, "COLLAB_URL", "")
    return calls


def test_a_failed_restore_is_tried_once_more(monkeypatch):
    calls = _wire(monkeypatch, [500, 200])
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 2 and rec["hydrated"] is True and not rec.get("hydrate_failed_with_checkpoint")


def test_two_failed_restores_flag_the_turn(monkeypatch):
    calls = _wire(monkeypatch, [500, 503])
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 2 and rec["hydrated"] is False
    assert rec["hydrate_failed_with_checkpoint"] is True and "503" in rec["hydrate_error"]


def test_no_checkpoint_means_no_retry(monkeypatch):
    calls = _wire(monkeypatch, [500])
    async def vertex(sid):
        return {}
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 1 and not rec.get("hydrate_failed_with_checkpoint")


def test_recycle_refuses_when_the_restore_failed(monkeypatch):
    async def vertex(sid):
        return {"id": sid, "status": "done", "turn_status": "done", "ws_sha": "abc"}
    async def hydrate(sid, rec, force=False):
        rec["hydrated"] = False
        rec["hydrate_error"] = "HTTP 500 boom"
        rec["hydrate_failed_with_checkpoint"] = True
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    monkeypatch.setattr(gw, "_hydrate", hydrate)
    with pytest.raises(gw.HTTPException) as e:
        asyncio.run(gw.recycle_session_sandbox("hsessx"))
    assert e.value.status_code == 502 and "restore failed" in str(e.value.detail)
