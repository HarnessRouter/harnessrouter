"""DELETE /file, POST /file/mkdir and POST /file/move: an app changing a session's workspace, through
the runner, which is the one process that acts as the session (see PUT /file).

What each must hold: nothing outside the workspace is reachable, by `..` or by a symlink; a symlink
is removed or renamed as itself, never as the file it points to; the nesting base's user files
(nanobot keeps them one level down) are found where GET /file finds them; and the answer names the
path inside the session directory, because that is where the gateway changes the checkpoint too.
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "sess"
    root.mkdir()
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_ws", lambda identifier="": str(root))
    return root


@pytest.fixture
def c():
    return TestClient(server.app)


def test_delete_a_file(ws, c):
    (ws / "a.txt").write_text("x")
    r = c.delete("/file", params={"identifier": "s", "path": "a.txt"})
    assert r.status_code == 200 and r.json()["path"] == "a.txt"
    assert not (ws / "a.txt").exists()


def test_delete_a_directory_with_everything_in_it(ws, c):
    (ws / "d" / "e").mkdir(parents=True)
    (ws / "d" / "e" / "f.txt").write_text("x")
    assert c.delete("/file", params={"identifier": "s", "path": "d"}).status_code == 200
    assert not (ws / "d").exists()


def test_delete_nothing_is_404(ws, c):
    assert c.delete("/file", params={"identifier": "s", "path": "nope.txt"}).status_code == 404


@pytest.mark.parametrize("path", ["../x", "../../etc/passwd", "a/../../x"])
def test_escapes_are_refused(ws, c, path):
    (ws.parent / "x").write_text("outside")
    assert c.delete("/file", params={"identifier": "s", "path": path}).status_code == 400
    assert c.post("/file/mkdir", params={"identifier": "s", "path": path}).status_code == 400
    (ws / "a.txt").write_text("x")
    assert c.post("/file/move", params={"identifier": "s", "path": "a.txt", "to": path}).status_code == 400
    assert (ws.parent / "x").read_text() == "outside"


def test_the_workspace_itself_is_not_a_path(ws, c):
    for p in ("", "/", "."):
        assert c.delete("/file", params={"identifier": "s", "path": p}).status_code in (400, 404)
    assert ws.is_dir()


def test_a_symlink_is_removed_not_its_target(ws, c):
    (ws / "real.txt").write_text("keep me")
    os.symlink(ws / "real.txt", ws / "link.txt")
    assert c.delete("/file", params={"identifier": "s", "path": "link.txt"}).status_code == 200
    assert not (ws / "link.txt").is_symlink() and (ws / "real.txt").read_text() == "keep me"


def test_a_symlink_out_of_the_workspace_is_removed_as_a_link(ws, c):
    outside = ws.parent / "secret.txt"
    outside.write_text("theirs")
    os.symlink(outside, ws / "escape")
    assert c.delete("/file", params={"identifier": "s", "path": "escape"}).status_code == 200
    assert outside.read_text() == "theirs"


def test_mkdir_makes_parents_and_is_idempotent(ws, c):
    r = c.post("/file/mkdir", params={"identifier": "s", "path": "a/b/c"})
    assert r.status_code == 200 and r.json()["created"] is True and (ws / "a" / "b" / "c").is_dir()
    r = c.post("/file/mkdir", params={"identifier": "s", "path": "a/b/c"})
    assert r.status_code == 200 and r.json()["created"] is False


def test_mkdir_over_a_file_is_409(ws, c):
    (ws / "a").write_text("x")
    assert c.post("/file/mkdir", params={"identifier": "s", "path": "a"}).status_code == 409
    assert c.post("/file/mkdir", params={"identifier": "s", "path": "a/b"}).status_code == 409


def test_move_a_file_into_a_new_directory(ws, c):
    (ws / "a.txt").write_text("x")
    r = c.post("/file/move", params={"identifier": "s", "path": "a.txt", "to": "notes/b.txt"})
    assert r.status_code == 200 and r.json() == {"ok": True, "path": "a.txt", "to": "notes/b.txt"}
    assert (ws / "notes" / "b.txt").read_text() == "x" and not (ws / "a.txt").exists()


def test_move_a_directory(ws, c):
    (ws / "d").mkdir()
    (ws / "d" / "f.txt").write_text("x")
    assert c.post("/file/move", params={"identifier": "s", "path": "d", "to": "e"}).status_code == 200
    assert (ws / "e" / "f.txt").read_text() == "x" and not (ws / "d").exists()


def test_move_never_overwrites(ws, c):
    (ws / "a.txt").write_text("a")
    (ws / "b.txt").write_text("b")
    assert c.post("/file/move", params={"identifier": "s", "path": "a.txt", "to": "b.txt"}).status_code == 409
    assert (ws / "b.txt").read_text() == "b" and (ws / "a.txt").read_text() == "a"


def test_move_into_itself_is_refused(ws, c):
    (ws / "d").mkdir()
    assert c.post("/file/move", params={"identifier": "s", "path": "d", "to": "d/inner"}).status_code == 400
    assert (ws / "d").is_dir()


def test_move_of_nothing_is_404(ws, c):
    assert c.post("/file/move", params={"identifier": "s", "path": "nope", "to": "x"}).status_code == 404


def test_the_nesting_base_finds_user_files_one_level_down(ws, c):
    """nanobot's user files live in the agent's directory; the answer names them inside the
    session directory, which is where they are in the checkpoint."""
    (ws / ".harness").mkdir()
    (ws / ".harness" / "agent-subdir").write_text("workspace")
    (ws / "workspace").mkdir()
    (ws / "workspace" / "deck.json").write_text("{}")
    r = c.post("/file/move", params={"identifier": "s", "path": "deck.json", "to": "old/deck.json"})
    assert r.status_code == 200
    assert r.json()["path"] == "workspace/deck.json" and r.json()["to"] == "workspace/old/deck.json"
    assert (ws / "workspace" / "old" / "deck.json").exists()
    r = c.delete("/file", params={"identifier": "s", "path": "old"})
    assert r.status_code == 200 and r.json()["path"] == "workspace/old"
