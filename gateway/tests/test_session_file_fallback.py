"""Reading a session file by PATH must survive the workspace being reaped.

The live workspace is garbage-collected after HR_WORKSPACE_TTL_HOURS (72h by default), but a file
the session PRODUCED was captured to a durable blob and stays in the listing. Before this, the
by-path route read only the live directory, so one session could LIST dashboard.json and 404 it in
the same breath — and the dashboard kit, which fetches by path, told the user "no dashboard has
been built for this conversation" about a dashboard that existed. Seen live on a 12-day-old
session on the public VM.

NOTE ON RUNNING THESE: gateway tests import app.py, which needs hashlib.scrypt. macOS system
python does not have it, so a local run here fails at COLLECTION with an AttributeError that has
nothing to do with the code under test. Run them in a container (docker exec <c> sh -lc 'cd
/app/gateway && python3 -m pytest') or let CI be the gate — CI pins the interpreter this tree
targets. A red local run is not evidence of a broken branch.
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


@pytest.mark.asyncio
async def test_the_newest_capture_of_a_filename_wins(monkeypatch):
    """Two captures can name the same file: the agent's, taken when a turn ended, and the app's,
    taken when somebody saved between turns. Serving the older one hands back work the person
    already replaced, and which one that was used to depend on blob-listing order."""
    import json as _json

    async def _list(_prefix, **_k):
        return {"items": [{"file_id": "containers/s/cfile_old.meta"},
                          {"file_id": "containers/s/cfile_new.meta"}]}

    async def _get(fid, **_k):
        stamps = {"containers/s/cfile_old.meta": 100.0, "containers/s/cfile_new.meta": 200.0}
        return _json.dumps({"filename": "sheet.json", "written_at": stamps[fid]}).encode()

    monkeypatch.setattr(A, "_blob_list", _list)
    monkeypatch.setattr(A, "_blob_get", _get)
    assert (await A._cfile_by_name("s"))["sheet.json"] == "cfile_new"

    # ...and the same regardless of the order the listing happened to return them in.
    async def _list_rev(_prefix, **_k):
        return {"items": [{"file_id": "containers/s/cfile_new.meta"},
                          {"file_id": "containers/s/cfile_old.meta"}]}

    monkeypatch.setattr(A, "_blob_list", _list_rev)
    assert (await A._cfile_by_name("s"))["sheet.json"] == "cfile_new"


@pytest.mark.asyncio
async def test_legacy_metas_with_no_stamp_resolve_as_they_always_did(monkeypatch):
    """Captures written before the stamp existed must not change meaning: last one still wins."""
    import json as _json

    async def _list(_prefix, **_k):
        return {"items": [{"file_id": "containers/s/cfile_a.meta"},
                          {"file_id": "containers/s/cfile_b.meta"}]}

    async def _get(_fid, **_k):
        return _json.dumps({"filename": "sheet.json"}).encode()

    monkeypatch.setattr(A, "_blob_list", _list)
    monkeypatch.setattr(A, "_blob_get", _get)
    assert (await A._cfile_by_name("s"))["sheet.json"] == "cfile_b"


def _captures(monkeypatch, entries):
    """entries: [(cfile_id, filename, written_at, source)]"""
    import json as _json

    async def _list(_prefix, **_k):
        return {"items": [{"file_id": f"containers/s/{cid}.meta"} for cid, *_ in entries]}

    async def _get(fid, **_k):
        cid = fid.rsplit("/", 1)[-1][: -len(".meta")]
        for c, name, ts, src in entries:
            if c == cid:
                m = {"filename": name, "written_at": ts}
                if src:
                    m["source"] = src
                return _json.dumps(m).encode()
        return None

    monkeypatch.setattr(A, "_blob_list", _list)
    monkeypatch.setattr(A, "_blob_get", _get)


@pytest.mark.asyncio
async def test_hydrate_puts_back_what_the_app_wrote_since_the_checkpoint(monkeypatch):
    """The checkpoint is only taken when a turn ENDS, so a sheet edited between turns is not in it.
    Without this the agent opens the older copy and writes the person's rows away."""
    _captures(monkeypatch, [("cfile_app", "sheet.json", 200.0, "app")])

    async def _bytes(_sid, cid):
        return (b'{"rows":["typed by the person"]}', "application/json", "sheet.json") if cid == "cfile_app" else None

    written = {}

    class _Ws:
        async def write(self, _sid, name, data):
            written[name] = data
            return True

    monkeypatch.setattr(A, "_container_file_bytes", _bytes)
    monkeypatch.setattr(A.BACKING, "workspace", _Ws(), raising=False)

    assert await A._reapply_app_writes("s") == 1
    assert written == {"sheet.json": b'{"rows":["typed by the person"]}'}


@pytest.mark.asyncio
async def test_it_never_overwrites_a_newer_agent_capture(monkeypatch):
    """The repair must not become the thing that destroys work. If the agent touched the file in
    its last turn, the checkpoint already holds that, and the older app copy is left alone."""
    _captures(monkeypatch, [("cfile_app", "sheet.json", 100.0, "app"),
                            ("cfile_agent", "sheet.json", 300.0, None)])

    written = {}

    class _Ws:
        async def write(self, _sid, name, data):
            written[name] = data
            return True

    async def _bytes(_sid, _cid):
        return (b"x", "application/json", "sheet.json")

    monkeypatch.setattr(A, "_container_file_bytes", _bytes)
    monkeypatch.setattr(A.BACKING, "workspace", _Ws(), raising=False)

    assert await A._reapply_app_writes("s") == 0
    assert written == {}


@pytest.mark.asyncio
async def test_a_broken_blob_store_does_not_stop_the_turn(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("blob store down")

    monkeypatch.setattr(A, "_blob_list", _boom)
    assert await A._reapply_app_writes("s") == 0
