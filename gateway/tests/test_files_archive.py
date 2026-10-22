"""The archive of a turn's cited files keeps the workspace's folders, keeps two files that share a
basename, and is refused with the names when a cited file is no longer there: "all" means all."""
import io
import json
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
    assert r.json()["error"]["code"] == "file_not_found"     # the protocol's code (errors.md §3.1)


def test_the_single_download_names_the_file_without_its_folder(monkeypatch):
    async def bytes_of(cid, fid):
        return (b"x", "text/plain", "deep/folder/notes.txt")
    monkeypatch.setattr(gw, "_container_file_bytes", bytes_of)
    monkeypatch.setattr(gw, "_owned_session", lambda request, sid: _async_value(None))
    r = TestClient(gw.app).get("/v1/containers/s1/files/wf_x/content")
    # RFC 6266 since #187: the ASCII fallback plus filename*, the same for every name.
    assert r.status_code == 200
    assert r.headers["content-disposition"] == (
        'attachment; filename="notes.txt"; filename*=UTF-8\'\'notes.txt')


def _wire_changed(monkeypatch, tmp_path, files: dict[str, bytes | None]):
    _wire(monkeypatch, tmp_path, files)

    async def blob_get(key, kb=None):
        return json.dumps(
            {"files": [{"file_id": gw._wf_id(p), "path": p} for p in files]}).encode()
    monkeypatch.setattr(gw, "_blob_get", blob_get)


def test_an_unreadable_changed_file_refuses_the_archive_by_name(monkeypatch, tmp_path):
    _wire_changed(monkeypatch, tmp_path, {"report.pdf": b"ok", "output/gone.json": None})
    r = TestClient(gw.app).get("/v1/sessions/s1/files/archive?changed=true")
    assert r.status_code == 404
    assert "1 of 2 files" in r.text and "output/gone.json" in r.text
    assert r.json()["error"]["code"] == "file_not_found"


def test_an_archive_with_nothing_in_it_is_a_file_not_found(monkeypatch, tmp_path):
    _wire_changed(monkeypatch, tmp_path, {})
    r = TestClient(gw.app).get("/v1/sessions/s1/files/archive?changed=true")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "file_not_found"


def test_a_readable_changed_set_still_archives_every_file(monkeypatch, tmp_path):
    _wire_changed(monkeypatch, tmp_path, {"report.pdf": b"ok", "output/notes.txt": b"n"})
    r = TestClient(gw.app).get("/v1/sessions/s1/files/archive?changed=true")
    assert r.status_code == 200
    assert sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == [
        "output/notes.txt", "report.pdf"]
