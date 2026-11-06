"""A turn answers only the session that started it: another session's turn id is "no such turn" on read and on cancel.
The gateway sends the session's identifier on every call (_sandbox adds it)."""
import asyncio
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def get_turn(*a, **kw) -> dict:
    return asyncio.run(server.get_turn(*a, **kw))


@pytest.fixture
def turn(monkeypatch):
    monkeypatch.setitem(server._turns, "t-bound", {"status": "running", "events": [], "result": "", "done": True,
                                                    "identifier": "sess-a", "backend": "", "model": "", "started": time.time()})
    return "t-bound"


def test_another_sessions_turn_reads_as_none(turn):
    with pytest.raises(HTTPException) as e:
        get_turn(turn, since=0, identifier="sess-b")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        get_turn(turn, since=0)
    assert e.value.status_code == 404


def test_another_session_cannot_cancel_it(turn):
    with pytest.raises(HTTPException) as e:
        server.cancel_turn(turn, identifier="sess-b")
    assert e.value.status_code == 404


def test_its_own_session_reads_and_cancels_it(turn):
    assert get_turn(turn, since=0, identifier="sess-a")["status"] == "running"
    assert server.cancel_turn(turn, identifier="sess-a")["cancelled"] is False      # done already: answered, not refused


def test_a_turn_recorded_without_a_session_is_as_before(monkeypatch):
    monkeypatch.setitem(server._turns, "t-plain", {"status": "running", "events": [], "result": "", "done": True,
                                                    "backend": "", "model": "", "started": time.time()})
    assert get_turn("t-plain", since=0)["status"] == "running"
    assert get_turn("t-plain", since=0, identifier="sess-b")["status"] == "running"


def test_an_idempotency_key_dedupes_only_within_its_session(monkeypatch):
    """A retried /turn with the same key returns the same turn, to the same session only: another session reusing the key
    never gets this turn's id, status or model, and goes on to start its own (here refused at the backend check, which
    comes right after the lookup, so no turn is built)."""
    monkeypatch.setitem(server._turns, "t-key", {"status": "running", "events": [], "result": "", "done": False,
                                                  "identifier": "sess-a", "backend": "claude", "model": "m", "started": time.time()})
    monkeypatch.setitem(server._turn_by_key, "sess-a\x00k-1", "t-key")
    req = server.TurnReq(backend="no-such-backend", prompt="hi", idempotency_key="k-1")
    again = server._start_turn(req, "sess-a")
    assert again["turn_id"] == "t-key" and again["deduplicated"] is True
    with pytest.raises(HTTPException) as e:
        server._start_turn(req, "sess-b")
    assert e.value.status_code == 400 and "unknown backend" in str(e.value.detail)
