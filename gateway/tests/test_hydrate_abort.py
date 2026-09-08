"""A checkpoint that cannot be restored is asked again for a minute and a half, and a turn never runs
on the wiped workspace: under a burst of cold sessions one restore in ten to twenty failed and the
conversation started over without a word (2026-09-06); the checkpoint itself was intact every time.
The last answer is always recorded, so a refusal names its cause, never "unknown"."""
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


def test_every_failed_restore_is_tried_over_a_minute_and_a_half_then_flags_the_turn(monkeypatch):
    calls = _wire(monkeypatch, [500])
    pauses = []
    async def sleep(s):
        pauses.append(s)
    monkeypatch.setattr(gw.asyncio, "sleep", sleep)
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 7 and rec["hydrated"] is False and rec.get("hydrate_failed_with_checkpoint")
    assert pauses == [1.0, 3.0, 6.0, 12.0, 24.0, 48.0]           # a sandbox under a burst comes in tens of seconds
    assert rec["hydrate_error"].startswith("HTTP 500")            # the refusal names its cause, never "unknown"


def test_a_refused_allocation_is_asked_again_even_without_a_checkpoint(monkeypatch):
    calls = _wire(monkeypatch, [429, 429, 200])
    async def vertex(sid):
        return {}
    async def sleep(s):
        pass
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    monkeypatch.setattr(gw.asyncio, "sleep", sleep)
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 3 and rec["hydrated"] is True and not rec.get("hydrate_failed_with_checkpoint")


def test_a_failure_without_a_checkpoint_is_not_retried_but_still_recorded(monkeypatch):
    calls = _wire(monkeypatch, [502])
    async def vertex(sid):
        return {}
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 1 and rec["hydrated"] is False and not rec.get("hydrate_failed_with_checkpoint")
    assert rec["hydrate_error"].startswith("HTTP 502")


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


def test_a_relay_that_raises_is_tried_again_on_the_same_ladder_and_names_its_cause(monkeypatch):
    """Twelve restores in two minutes raised while the pool refused allocations (hosted, 2026-09-08
    08:10Z): each was recorded as "unknown" and none was asked again. The restore is idempotent."""
    import httpx
    calls = []
    async def relay(sid, params):
        calls.append(sid)
        if len(calls) < 3:
            raise httpx.ReadError("")
        return _R(200)
    async def vertex(sid):
        return {"ws_sha": "abc123"}
    async def sleep(s):
        pass
    monkeypatch.setattr(gw, "_hydrate_relay", relay)
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    monkeypatch.setattr(gw, "COLLAB_URL", "")
    monkeypatch.setattr(gw.asyncio, "sleep", sleep)
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 3 and rec["hydrated"] is True and not rec.get("hydrate_failed_with_checkpoint")

    calls.clear()
    async def always(sid, params):
        calls.append(sid)
        raise httpx.ReadError("")
    monkeypatch.setattr(gw, "_hydrate_relay", always)
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 7 and rec["hydrated"] is False and rec.get("hydrate_failed_with_checkpoint")
    assert rec["hydrate_error"] == "ReadError"                    # the class, never "unknown"
    assert gw._hydrate_reason(rec) == "ReadError"


def test_a_raise_without_a_checkpoint_is_not_retried_and_a_pool_refusal_reads_as_busy(monkeypatch):
    calls = []
    async def relay(sid, params):
        calls.append(sid)
        raise RuntimeError("hydrate blob GET failed: HTTP 503")
    async def vertex(sid):
        return {}
    async def sleep(s):
        pass
    monkeypatch.setattr(gw, "_hydrate_relay", relay)
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    monkeypatch.setattr(gw, "COLLAB_URL", "")
    monkeypatch.setattr(gw.asyncio, "sleep", sleep)
    rec = {}
    asyncio.run(gw._hydrate("hsessx", rec, force=True))
    assert len(calls) == 1 and rec["hydrated"] is False and not rec.get("hydrate_failed_with_checkpoint")
    assert rec["hydrate_error"] == "RuntimeError: hydrate blob GET failed: HTTP 503"
    assert gw._hydrate_reason({"hydrate_error": "HTTP 429 Error happened when allocating pod for identifier x in pool y"}) \
        == "the sandbox could not be started right now (busy); try again in a minute"
