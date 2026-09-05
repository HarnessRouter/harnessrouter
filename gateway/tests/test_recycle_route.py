"""The recycle route restores the durable checkpoint into the sandbox and never checkpoints first:
a checkpoint taken from a sandbox that no longer holds the session would overwrite the good blob
with an empty workspace."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_recycle_hydrates_without_probe_and_without_checkpoint(monkeypatch):
    calls = []
    async def vertex_get(sid):
        return {"ws_sha": "abc123", "turn_status": "completed"}
    async def sandbox(path, sid, method, **kw):
        calls.append(("probe", kw.get("params")))
        raise AssertionError("the probe must not run on a forced hydrate")
    class R:
        status_code = 200
        headers = {"content-type": "application/json"}
        def json(self):
            return {"ok": True, "restored": True, "skipped": False}
    async def relay(sid, params):
        calls.append(("relay", sid))
        return R()
    async def checkpoint(sid, rec):
        calls.append(("checkpoint", sid))
    monkeypatch.setattr(app, "_vertex_get", vertex_get)
    monkeypatch.setattr(app, "_sandbox", sandbox)
    monkeypatch.setattr(app, "_hydrate_relay", relay)
    monkeypatch.setattr(app, "_checkpoint", checkpoint)
    monkeypatch.setattr(app, "COLLAB_URL", "")
    out = _run(app.recycle_session_sandbox("hsess1"))
    assert calls == [("relay", "hsess1")]
    assert out["hydrated"] is True and out["hydrate"]["restored"] is True
    assert out["checkpoint_sha"] == "abc123"


def test_recycle_refused_while_a_turn_runs(monkeypatch):
    async def vertex_get(sid):
        return {"ws_sha": "abc123", "turn_status": "running"}
    monkeypatch.setattr(app, "_vertex_get", vertex_get)
    with pytest.raises(HTTPException) as e:
        _run(app.recycle_session_sandbox("hsess1"))
    assert e.value.status_code == 409


def test_hydrate_probe_still_used_for_ordinary_turns(monkeypatch):
    """Without force the warm-sandbox probe runs first and a match skips the restore."""
    calls = []
    async def vertex_get(sid):
        return {"ws_sha": "abc123"}
    class P:
        status_code = 200
        headers = {"content-type": "application/json"}
        def json(self):
            return {"ok": True, "skipped": True, "restored": False}
    async def sandbox(path, sid, method, **kw):
        calls.append(("probe", (kw.get("params") or {}).get("probe")))
        return P()
    async def relay(sid, params):
        calls.append(("relay", sid))
        raise AssertionError("a matching probe must skip the relay")
    monkeypatch.setattr(app, "_vertex_get", vertex_get)
    monkeypatch.setattr(app, "_sandbox", sandbox)
    monkeypatch.setattr(app, "_hydrate_relay", relay)
    monkeypatch.setattr(app, "COLLAB_URL", "")
    rec = {}
    _run(app._hydrate("hsess1", rec))
    assert calls == [("probe", "abc123")] and rec["hydrated"] is True and rec["hydrate"]["skipped"] is True
