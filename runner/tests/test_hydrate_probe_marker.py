"""The warm-resume probe vouches for a workspace that is actually there.

/hydrate?probe=<sha> asks "do you still hold this checkpoint?" so a follow-up turn on a warm
sandbox can skip the download and the wipe+untar. The answer came from the per-session marker
under /tmp/hr-ws alone — and the marker outlives the workspace: delete the folder from the
volume by hand and `docker stop`/`start` the runner, or call DELETE /workspace (which removed
the folder but, unlike the reaper, left the marker), and the next probe still said "held".
The gateway then skipped the restore and the turn ran on an empty workspace: the CLI found no
session to resume and the conversation started over (seen by richard-epsilla on #194).
"""
import hashlib
import io
import pathlib
import sys
import tarfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


@pytest.fixture
def runner(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setattr(server, "_WS_MARKER_DIR", str(tmp_path / "markers"))
    monkeypatch.setattr(server, "SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    (tmp_path / "ws").mkdir()
    return TestClient(server.app)


def _checkpoint() -> tuple[bytes, str]:
    """A checkpoint tarball as the gateway would stream it, and the sha it will probe with."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b'{"step": 1}'
        info = tarfile.TarInfo("./plan.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    body = buf.getvalue()
    return body, hashlib.sha256(body).hexdigest()


def test_a_warm_workspace_answers_the_probe(runner):
    body, sha = _checkpoint()
    assert runner.post("/hydrate?identifier=s1", content=body).json()["restored"] is True
    assert runner.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is True


def test_a_workspace_deleted_behind_the_marker_is_hydrated_again(runner, tmp_path):
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    import shutil
    shutil.rmtree(tmp_path / "ws" / "s1")                 # by hand on the volume, runner still up
    assert runner.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is False
    assert not server._ws_marker_path("s1").exists(), "the marker that lied is gone"
    # and the full hydrate the gateway then sends lands as usual
    r = runner.post("/hydrate?identifier=s1", content=body).json()
    assert r["restored"] is True and (tmp_path / "ws" / "s1" / "plan.json").read_text() == '{"step": 1}'


def test_delete_workspace_takes_the_marker_with_it(runner, tmp_path):
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    assert server._ws_marker_path("s1").exists()
    assert runner.delete("/workspace?identifier=s1").json()["removed"] is True
    assert not server._ws_marker_path("s1").exists()
    assert runner.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is False
