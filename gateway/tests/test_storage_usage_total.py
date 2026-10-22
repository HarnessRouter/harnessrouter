"""The storage total the daily billing sweep reads is never zero because a read failed.

/internal/storage-usage sums each non-deleted session's checkpoint_bytes per org, and its own
docstring names its consumer: "the daily storage.gb_day billing sweep". It resolved the session
index with `find`, which swallows a read failure into [] (backing.py: "the normal read paths
swallow errors and return empty"). A store that could not answer therefore produced
200 {"by_org": {}} — a zero storage total for every org, indistinguishable from an org that stores
nothing. `find_strict` (added with BlobStore.get_or_raise) is the read for a caller that must not
take a failure for nothing there. An index that is legitimately empty still answers {}: that is a
true total, and the distinction is the point.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402
import backing  # noqa: E402

KEY = "internal-storage-key"
HDR = {"x-harness-internal": KEY}


@pytest.fixture
def api(monkeypatch, tmp_path):
    graph = backing.SqliteGraphStore(str(tmp_path / "graph.db"))
    monkeypatch.setattr(gw.BACKING, "graph", graph)
    monkeypatch.setattr(gw, "INTERNAL_KEY", KEY)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)
    return TestClient(gw.app), graph


def _session(graph, sid: str, org: str, nbytes: int, status: str = "done") -> None:
    asyncio.run(graph.upsert("HarnessSession", sid, {
        "tenant": org, "status": status, "checkpoint_bytes": str(nbytes)}))


def test_a_populated_index_reports_its_real_totals(api):
    c, graph = api
    _session(graph, "hsessa", "org.acme", 1024)
    _session(graph, "hsessb", "org.acme", 2048)
    _session(graph, "hsessc", "org.other", 4096)
    _session(graph, "hsessd", "org.acme", 8192, status="deleted")   # not counted
    r = c.get("/internal/storage-usage", headers=HDR)
    assert r.status_code == 200, r.text
    assert r.json() == {"by_org": {"org.acme": 3072, "org.other": 4096}}


def test_an_empty_index_still_answers_an_empty_total(api):
    c, _ = api
    r = c.get("/internal/storage-usage", headers=HDR)
    assert r.status_code == 200, r.text
    assert r.json() == {"by_org": {}}          # nothing stored is a true zero, not a failure


def test_an_index_read_that_failed_is_never_answered_as_a_zero_total(api):
    """The regression: the sweep must not read {} — a day it cannot measure is not a free day."""
    c, graph = api
    _session(graph, "hsesse", "org.acme", 1024)
    graph._path = str(Path(graph._path).parent)        # a directory: SQLite cannot open it
    r = c.get("/internal/storage-usage", headers=HDR)
    assert r.status_code >= 500, r.text
    assert "by_org" not in r.text


def test_an_index_read_that_raised_is_answered_503_retry(api, monkeypatch):
    c, graph = api

    async def find_strict(label, eq=None, neq=None):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(graph, "find_strict", find_strict)
    r = c.get("/internal/storage-usage", headers=HDR)
    assert r.status_code == 503, r.text
    assert "retry" in r.text and "by_org" not in r.text
