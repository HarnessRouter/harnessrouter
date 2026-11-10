"""A checkpoint holds what the session can read in its own tree, and nothing else.

/checkpoint archives a session's directory, and the archive is later restored into that same session. It is
read as the session, as /hydrate's untar writes as it, and the tar process starts from the environment agent
processes get, never the runner's own. A path the session cannot read is left out and named in the log (never
its contents); any other tar failure still fails the checkpoint. The archive itself is read as the session only
behind the wall, which is root's, on Linux.
"""
import io
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_ROOT_ON_LINUX = sys.platform.startswith("linux") and os.geteuid() == 0
root_only = pytest.mark.skipif(not _ROOT_ON_LINUX, reason="the write-wall is root's, on Linux")
UID = 20779
IDENT = "hsessckpt"


def _members(tar_bytes: bytes) -> dict[str, bytes | None]:
    out = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for m in tf.getmembers():
            f = tf.extractfile(m) if m.isfile() else None
            out[m.name.removeprefix("./")] = f.read() if f else None
    return out


@pytest.fixture
def wall(monkeypatch):
    """A runner behind the wall, and one session directory of uid UID inside a passable workspace root."""
    root = tempfile.mkdtemp(prefix="hrckroot-")
    os.chmod(root, 0o751)
    spool = tempfile.mkdtemp(prefix="hrckspool-")
    monkeypatch.setattr(server, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(server, "_WS_MARKER_DIR", tempfile.mkdtemp(prefix="hrckmarkers-"))
    monkeypatch.setattr(server, "SPOOL_DIR", spool)
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    ws = pathlib.Path(root, IDENT)
    ws.mkdir()
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    return TestClient(server.app), ws


def _session_file(ws: pathlib.Path, name: str, text: str, mode: int = 0o644) -> pathlib.Path:
    p = ws / name
    p.write_text(text)
    os.chown(p, UID, UID)
    os.chmod(p, mode)
    return p


@root_only
def test_a_file_of_another_owner_under_a_second_name_is_not_carried(wall):
    client, ws = wall
    _session_file(ws, "mine.txt", "the session's own")
    d = tempfile.mkdtemp(prefix="hrckother-")                 # root's, 0700
    theirs = pathlib.Path(d, "theirs")
    theirs.write_text("not the session's: 5c1d")
    os.chmod(theirs, 0o600)
    os.link(theirs, ws / "second-name")                       # made as root: the test plays every part
    r = client.get("/checkpoint", params={"identifier": IDENT})
    assert r.status_code == 200, r.text[:300]
    got = _members(r.content)
    assert got.get("mine.txt") == b"the session's own"
    assert "second-name" not in got
    assert not any(v and b"5c1d" in v for v in got.values()), "a file the session can't read reached its checkpoint"
    assert theirs.read_text() == "not the session's: 5c1d" and theirs.stat().st_uid == 0


@root_only
def test_a_file_the_session_made_unreadable_is_left_out_and_named(wall, capsys):
    client, ws = wall
    _session_file(ws, "mine.txt", "kept")
    _session_file(ws, "closed.txt", "closed bytes 9e4b", mode=0o000)
    r = client.get("/checkpoint", params={"identifier": IDENT})
    assert r.status_code == 200, r.text[:300]
    got = _members(r.content)
    assert got.get("mine.txt") == b"kept" and "closed.txt" not in got
    out = capsys.readouterr().out
    line = next((ln for ln in out.splitlines() if ln.startswith("[checkpoint] WARNING")), "")
    assert IDENT in line and "closed.txt" in line, out[-600:]
    assert "9e4b" not in out, "the log carried a file's contents"


@root_only
def test_what_the_runner_wrote_for_the_session_is_still_carried(wall):
    client, ws = wall
    _session_file(ws, "mine.txt", "x")
    server._isolate_session(str(ws))
    r = client.get("/checkpoint", params={"identifier": IDENT})
    assert r.status_code == 200
    got = _members(r.content)
    assert "never persist secrets" in (got.get(".gitignore") or b"").decode()   # written by the runner, as the session
    assert any(n.startswith(".git/") for n in got)


def _fake_runs(monkeypatch, tar_result):
    """Every subprocess /checkpoint starts, answered here: git as a success, tar as `tar_result`."""
    seen = []

    def run(cmd, *a, **kw):
        if cmd and cmd[0] == "tar":
            seen.append(kw)
            return subprocess.CompletedProcess(cmd, tar_result[0], b"", tar_result[1])
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(server.subprocess, "run", run)
    monkeypatch.setattr(server, "_git_ensure", lambda ws: None)
    monkeypatch.setattr(server, "_session_uid", lambda ws: UID)
    return seen


@pytest.fixture
def runner_anywhere(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setattr(server, "_WS_MARKER_DIR", str(tmp_path / "markers"))
    monkeypatch.setattr(server, "SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    (tmp_path / "ws" / IDENT).mkdir(parents=True)
    return TestClient(server.app)


def test_tar_runs_as_the_session_from_the_agents_environment(runner_anywhere, monkeypatch):
    monkeypatch.setenv("HARNESS_INTERNAL_KEY", "internal-key-never-in-a-child")
    seen = _fake_runs(monkeypatch, (0, b""))
    assert runner_anywhere.get("/checkpoint", params={"identifier": IDENT}).status_code == 200
    kw = seen[0]
    assert kw.get("user") == UID and kw.get("group") == UID
    assert "HARNESS_INTERNAL_KEY" not in (kw.get("env") or {}) and kw.get("env") is not None


def test_skipped_paths_are_logged_by_name_and_the_checkpoint_succeeds(runner_anywhere, monkeypatch, capsys):
    err = (b"tar: ./closed.txt: Warning: Cannot open: Permission denied\n"
           b"tar: ./shut: Warning: Cannot open: Permission denied\n")
    _fake_runs(monkeypatch, (0, err))
    assert runner_anywhere.get("/checkpoint", params={"identifier": IDENT}).status_code == 200
    out = capsys.readouterr().out
    assert "[checkpoint] WARNING" in out and "./closed.txt" in out and "./shut" in out and "2 path(s)" in out


@pytest.mark.parametrize("code", [1, 2])
def test_any_other_tar_failure_still_fails_the_checkpoint(runner_anywhere, monkeypatch, code):
    _fake_runs(monkeypatch, (code, b"tar: ./x: file changed as we read it\n"))
    r = runner_anywhere.get("/checkpoint", params={"identifier": IDENT})
    assert r.status_code == 500 and "tar failed" in r.text


def test_only_tars_skip_lines_are_read_as_names():
    err = ("tar: ./a b: Warning: Cannot open: Permission denied\n"
           "tar: ./d: Warning: Cannot savedir: Permission denied\n"
           "tar: ./x: file changed as we read it\n"
           "something else entirely\n")
    assert server._tar_skipped(err.encode()) == ["./a b", "./d"]
    assert server._tar_skipped(b"") == [] and server._tar_skipped(None) == []
