"""The archive of a turn's cited files keeps the workspace's folders, keeps two files that share a
basename, and is refused with the names when a cited file is no longer there: "all" means all."""
import io
import zipfile

from fastapi.testclient import TestClient

import app as gw


async def _async_value(v):
    return v


def _wire(monkeypatch, tmp_path, files: dict[str, bytes | None]):
    monkeypatch.setattr(gw, "_owned_session", lambda request, sid: _async_value(None))
    monkeypatch.setattr(gw, "_reap_spool_dir", lambda: None)
    monkeypatch.setattr(gw, "_WS_TAR_DIR", str(tmp_path))

    async def bytes_of(sid, fid):
        path = gw._wf_path(fid)
        data = files.get(path)
        return None if data is None else (data, "text/plain", path)
    monkeypatch.setattr(gw, "_container_file_bytes", bytes_of)


def test_the_archive_keeps_folders_and_same_named_files(monkeypatch, tmp_path):
    files = {"travel/__init__.py": b"a", "output/__init__.py": b"b", "README.md": b"c"}
    _wire(monkeypatch, tmp_path, files)
    ids = ",".join(gw._wf_id(p) for p in files)
    r = TestClient(gw.app).get(f"/v1/sessions/s1/files/archive?files={ids}")
    assert r.status_code == 200
    names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert names == ["README.md", "output/__init__.py", "travel/__init__.py"]


def test_a_missing_cited_file_refuses_the_archive_by_name(monkeypatch, tmp_path):
    files = {"README.md": b"c", "output/gone.json": None}
    _wire(monkeypatch, tmp_path, files)
    ids = ",".join(gw._wf_id(p) for p in files)
    r = TestClient(gw.app).get(f"/v1/sessions/s1/files/archive?files={ids}")
    assert r.status_code == 404
    assert "1 of 2 files" in r.text and "output/gone.json" in r.text


def test_the_single_download_names_the_file_without_its_folder(monkeypatch):
    async def bytes_of(cid, fid):
        return (b"x", "text/plain", "deep/folder/notes.txt")
    monkeypatch.setattr(gw, "_container_file_bytes", bytes_of)
    monkeypatch.setattr(gw, "_owned_session", lambda request, sid: _async_value(None))
    r = TestClient(gw.app).get("/v1/containers/s1/files/wf_x/content")
    assert r.status_code == 200 and r.headers["content-disposition"] == 'attachment; filename="notes.txt"'
