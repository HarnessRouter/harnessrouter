"""A deleted task is final (2026-09-07): a follow-up sent to a deleted Codex task was accepted, ran,
billed, and rewrote the task's card as "?", and the delete button then refused the tombstone with
404, so the ghost card stayed in the list for good. The turn resolver refuses a tombstone the way
it refuses another org's session, and a tombstoned session can be deleted again."""
import asyncio
import os
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": "local", "x-harness-member": "m"}


def _resolve(session_hint: str):
    return asyncio.run(gw._resp_resolve_session("org.a", "m", None, "codex", session_hint=session_hint))


def test_a_deleted_session_is_not_continued(monkeypatch):
    async def vertex(sid):
        return {"tenant": "org.a", "status": "deleted", "cli_session_id": "c1"}
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    with pytest.raises(Exception) as ei:
        _resolve("hsessdead")
    assert getattr(ei.value, "status_code", None) == 404


def test_another_orgs_session_is_not_continued(monkeypatch):
    async def vertex(sid):
        return {"tenant": "org.b", "status": "done", "cli_session_id": "c1"}
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    with pytest.raises(Exception) as ei:
        _resolve("hsessother")
    assert getattr(ei.value, "status_code", None) == 404


def test_an_unknown_session_id_is_refused_rather_than_replaced(monkeypatch):
    async def vertex(sid):
        return None
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    with pytest.raises(Exception) as ei:
        _resolve("hsessnone")
    assert getattr(ei.value, "status_code", None) == 404


def test_a_live_session_of_the_org_is_continued(monkeypatch):
    async def vertex(sid):
        return {"tenant": "org.a", "status": "done", "cli_session_id": "c1", "trace_blob": "org.a/1_" + sid}
    async def cursor(tr):
        return None
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    monkeypatch.setattr(gw, "_recover_trace_cursor", cursor)
    assert _resolve("hsesslive") == ("hsesslive", "c1")


def test_a_tombstoned_session_can_be_deleted_again():
    sid = "hsessdeletetwice"
    asyncio.run(gw._vertex_upsert(sid, {"tenant": "local", "status": "done", "created_at_inv": "98211493921626",
                                        "trace_blob": "local/98211493921626_" + sid}))
    c = TestClient(gw.app)
    first = c.delete(f"/v1/sessions/{sid}", headers=HEADERS)
    second = c.delete(f"/v1/sessions/{sid}", headers=HEADERS)
    assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
    assert (asyncio.run(gw._vertex_get(sid)) or {}).get("status") == "deleted"
    # ownership still gates it: another org cannot delete (or learn about) the tombstone
    other = c.delete(f"/v1/sessions/{sid}", headers={**HEADERS, "x-harness-org": "other"})
    assert other.status_code == 404
    # and a turn on the tombstone is refused before anything runs
    with pytest.raises(Exception) as ei:
        asyncio.run(gw._resp_resolve_session("local", "m", None, "codex", session_hint=sid))
    assert getattr(ei.value, "status_code", None) == 404
