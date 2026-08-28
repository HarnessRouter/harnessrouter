"""Reading a session file by PATH must survive the workspace being reaped.

The live workspace is garbage-collected after HR_WORKSPACE_TTL_HOURS (72h by default), but a file
the session PRODUCED was captured to a durable blob and stays in the listing. Before this, the
by-path route read only the live directory, so one session could LIST dashboard.json and 404 it in
the same breath — and the dashboard kit, which fetches by path, told the user "no dashboard has
been built for this conversation" about a dashboard that existed. Seen live on a 12-day-old
session on the public VM.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as A  # noqa: E402


@pytest.mark.asyncio
async def test_by_path_falls_back_to_the_captured_blob(monkeypatch):
    sid, body = "hsess_reaped", b'{"panels":[1,2,3]}'

    class _Gone:
        async def read(self, *_a, **_k):
            return None                      # workspace reaped

    monkeypatch.setattr(A.BACKING, "workspace", _Gone(), raising=False)
    monkeypatch.setattr(A, "_owned_session", _ok := (lambda *a, **k: _noop()), raising=False)

    async def _noop():
        return ("org", {})

    async def _byname(_sid):
        assert _sid == sid
        return {"dashboard.json": "cfile_abc"}

    async def _bytes(_sid, fid):
        return (body, "application/json", "dashboard.json") if fid == "cfile_abc" else None

    monkeypatch.setattr(A, "_cfile_by_name", _byname)
    monkeypatch.setattr(A, "_container_file_bytes", _bytes)

    r = await A.read_session_file(sid, "dashboard.json", request=None)
    assert r.status_code == 200 and r.body == body


@pytest.mark.asyncio
async def test_a_file_that_never_existed_still_404s(monkeypatch):
    """The fallback must not turn every miss into a success."""
    class _Gone:
        async def read(self, *_a, **_k):
            return None

    async def _noop():
        return ("org", {})

    monkeypatch.setattr(A.BACKING, "workspace", _Gone(), raising=False)
    monkeypatch.setattr(A, "_owned_session", lambda *a, **k: _noop(), raising=False)
    monkeypatch.setattr(A, "_cfile_by_name", lambda _s: _empty())

    async def _empty():
        return {}

    with pytest.raises(Exception):
        await A.read_session_file("hsess_x", "nope.json", request=None)
