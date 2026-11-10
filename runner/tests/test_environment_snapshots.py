"""Environment recovery preserves layers and rejects archive path escapes."""
import io
import pathlib
import sys
import tarfile

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import environment_snapshots as S
import environments as E


def test_snapshot_restores_source_versions_and_active_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "ENV_ROOT", str(tmp_path / "first"))
    E.write_file("henv_a", "main.py", b"print(1)")
    version = E.version_dir("henv_a", 1)
    version.mkdir(parents=True)
    (version / "main.py").write_bytes(b"print(0)")
    E._write_record(version, {"version": 1, "status": "ready"})
    E._point_active("henv_a", 1)
    path = S.snapshot("henv_a")
    try:
        monkeypatch.setattr(E, "ENV_ROOT", str(tmp_path / "second"))
        assert S.restore("henv_a", path)["active"] == 1
        assert S.restore("henv_a", path)["active"] == 1
        assert E.read_file("henv_a", "main.py")[0] == b"print(1)"
        assert (E.version_dir("henv_a", 1) / "main.py").read_bytes() == b"print(0)"
        assert not E.version_dir("henv_a", 1).stat().st_mode & 0o022
    finally:
        pathlib.Path(path).unlink()


def test_snapshot_refuses_paths_outside_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "ENV_ROOT", str(tmp_path / "envs"))
    path = tmp_path / "bad.tgz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("environment/../../outside")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(HTTPException):
        S.restore("henv_a", str(path))
    assert not (tmp_path / "outside").exists()
    assert not E.env_dir("henv_a").exists()
