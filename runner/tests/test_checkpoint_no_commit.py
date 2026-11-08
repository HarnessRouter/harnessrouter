"""A checkpoint taken while the turn runs does not commit (#505).

/checkpoint stages and commits the workspace before it tars it. At the end of a turn that is the
turn's record. Taken mid-turn (the gateway's per-step checkpoint) it would commit the agent's work
under its feet: its own `git status` and `git diff` go quiet halfway through what it is doing, and
`git add` can meet the agent's own git on .git/index.lock. `commit=0` takes the tarball only, and
the uncommitted state is restored as it was.
"""
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
    client = TestClient(server.app)
    assert client.post("/hydrate?identifier=s1", content=b"").json()["ok"]   # a fresh repo
    return client


def _head(ws: str) -> str:
    return server._git(ws, "rev-parse", "HEAD").stdout.strip()


def _names(tar_bytes: bytes) -> set[str]:
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        return {m.name.removeprefix("./") for m in tf.getmembers()}


def test_a_mid_turn_checkpoint_leaves_the_agents_git_alone(runner):
    ws = server._ws("s1")
    pathlib.Path(ws, "step1.txt").write_text("one")
    head = _head(ws)
    r = runner.get("/checkpoint?identifier=s1&commit=0")
    assert r.status_code == 200
    assert _head(ws) == head                                          # nothing committed
    assert "?? step1.txt" in server._git(ws, "status", "--porcelain").stdout   # still the agent's change
    assert "step1.txt" in _names(r.content)                          # and it is in the checkpoint
    assert r.headers["X-Git-Head"] == head[:len(r.headers["X-Git-Head"])]


def test_the_end_of_turn_checkpoint_still_commits(runner):
    ws = server._ws("s1")
    pathlib.Path(ws, "done.txt").write_text("done")
    head = _head(ws)
    r = runner.get("/checkpoint?identifier=s1")
    assert r.status_code == 200
    assert _head(ws) != head
    assert server._git(ws, "status", "--porcelain").stdout.strip() == ""
    assert "done.txt" in _names(r.content)
