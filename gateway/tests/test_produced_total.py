"""A turn that produced more files than a response carries: the newest lead, the record says how
many there were in all, and the listing serves that number beside the captured count. Without it a
run that archived 2,700 frames showed its first 24 in path order (hosted, 2026-09-25) and the
console's "Showing 25 of N" could only ever read N = 25.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

ORG = "local"


class _Resp:
    def __init__(self, status: int, body: bytes, ctype: str = "application/json"):
        self.status_code, self.content, self.headers = status, body, {"content-type": ctype}

    def json(self):
        return json.loads(self.content)


def test_collection_keeps_the_newest_and_counts_them_all(monkeypatch):
    sid = "hsessprod" + os.urandom(4).hex()
    # 30 produced files, listed by the runner in path order, written at increasing times; two
    # internal names that never count and never show
    listed = [{"path": f"observations/{i:06d}.jpg", "status": "?", "mtime": 1_700_000_000 + i} for i in range(30)]
    listed += [{"path": ".harness/state.json", "status": "M", "mtime": 1_800_000_000},
               {"path": "AGENTS.md", "status": "M", "mtime": 1_800_000_001}]
    stored = {}

    async def _sandbox(path, s, method, body=None, params=None):
        if path == "/produced":
            return _Resp(200, json.dumps({"files": listed}).encode())
        if path == "/produced/ack":
            return _Resp(200, b"{}")
        return _Resp(200, b"bytes", "image/jpeg")           # GET /files/<path>

    async def _blob_put(key, data, kb=0):
        stored[key] = data
        return True
    monkeypatch.setattr(gw, "_sandbox", _sandbox)
    monkeypatch.setattr(gw, "_blob_put", _blob_put)
    monkeypatch.setattr(gw, "RESP_MAX_FILES", 25)
    out = asyncio.run(gw._collect_produced(sid))
    names = [o["filename"] for o in out]
    assert len(out) == 25 and names[0] == "observations/000029.jpg" and names[-1] == "observations/000005.jpg"
    assert not any(n.startswith(".harness/") or n == "AGENTS.md" for n in names)
    assert gw._produced_total[sid] == 30      # what the turn produced, not what the response carries


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    return TestClient(gw.app)


def _session(sid: str) -> None:
    asyncio.run(gw._vertex_upsert(sid, {"tenant": ORG, "status": "done", "member_id": "me@local"}))


def test_the_changed_listing_serves_the_turns_total_beside_the_captured_count(api):
    sid = "hsessprod" + os.urandom(4).hex()
    _session(sid)
    files = [{"path": f"observations/{i:06d}.jpg", "file_id": f"cfile{i}", "bytes": 5} for i in range(2)]
    asyncio.run(gw._blob_put(f"sessions/{sid}/changed.json",
                             json.dumps({"at": 1.0, "produced": 30, "files": files}).encode(), kb=gw.RESP_BLOB_KB))
    d = api.get(f"/v1/sessions/{sid}/files?changed=true").json()
    assert d["count"] == 2 and d["produced"] == 30 and len(d["files"]) == 2
    # a record written before the field existed: the total is at least what was captured
    asyncio.run(gw._blob_put(f"sessions/{sid}/changed.json",
                             json.dumps({"at": 1.0, "files": files}).encode(), kb=gw.RESP_BLOB_KB))
    d = api.get(f"/v1/sessions/{sid}/files?changed=true").json()
    assert d["count"] == 2 and d["produced"] == 2
