"""A session that never saved a checkpoint is asked about its fresh start before a restore (#712).

Its first turn, cut by a restart before the end-of-turn checkpoint, left files and the CLI's
conversation in a workspace the restart kept: the cut turn's error says `workspace: kept`. The
follow-up asked the runner nothing (there was no checkpoint sha to ask about), restored "nothing"
and so wiped both. Now it asks `probe=fresh`, and a runner that still holds that workspace keeps it.
"""
import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.headers = {"content-type": "application/json"}
        self.text = ""

    def json(self):
        return self._body


@pytest.fixture()
def calls(monkeypatch):
    seen = {"probes": [], "restores": 0}

    async def sandbox(path, sid, method, content=None, params=None, **kw):
        seen["probes"].append((params or {}).get("probe"))
        return _Resp(200, {"ok": True, "skipped": seen["held"]})

    async def relay(sid, params, **kw):
        seen["restores"] += 1
        return _Resp(200, {"ok": True, "restored": False})

    async def reapply(sid, since):
        return 0

    monkeypatch.setattr(gw, "_sandbox", sandbox)
    monkeypatch.setattr(gw, "_hydrate_relay", relay)
    monkeypatch.setattr(gw, "_reapply_app_writes", reapply)
    return seen


def _vertex(monkeypatch, v):
    async def get(sid):
        return v
    monkeypatch.setattr(gw, "_vertex_get", get)


def test_no_checkpoint_and_the_runner_holds_the_fresh_start_keeps_the_workspace(monkeypatch, calls):
    _vertex(monkeypatch, {"status": "failed", "end_reason": "interrupted"})      # no ws_sha
    calls["held"] = True
    rec: dict = {}
    asyncio.run(gw._hydrate("s1", rec))
    assert calls["probes"] == ["fresh"] and calls["restores"] == 0
    assert rec["hydrated"] is True and rec["hydrate"]["skipped"] is True


def test_a_new_session_is_started_empty_as_before(monkeypatch, calls):
    _vertex(monkeypatch, {})
    calls["held"] = False
    rec: dict = {}
    asyncio.run(gw._hydrate("s1", rec))
    assert calls["probes"] == ["fresh"] and calls["restores"] == 1 and rec["hydrated"] is True


def test_a_checkpoint_is_still_asked_about_by_its_sha(monkeypatch, calls):
    _vertex(monkeypatch, {"ws_sha": "ab" * 32})
    calls["held"] = True
    asyncio.run(gw._hydrate("s1", {}))
    assert calls["probes"] == ["ab" * 32] and calls["restores"] == 0


def test_a_forced_restore_asks_nothing(monkeypatch, calls):
    _vertex(monkeypatch, {})
    calls["held"] = True
    asyncio.run(gw._hydrate("s1", {}, force=True))
    assert calls["probes"] == [] and calls["restores"] == 1
