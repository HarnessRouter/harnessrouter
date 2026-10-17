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


# ── what the review of #478 found ─────────────────────────────────────────────────────────────
def _nanobot(ws):
    (ws / ".harness").mkdir()
    (ws / ".harness" / "agent-subdir").write_text("workspace")
    (ws / ".git" / "info").mkdir(parents=True)
    (ws / ".git" / "info" / "exclude").write_text(
        "# runner\nworkspace/.nanobot/\nworkspace/skills/\nworkspace/memory/\nworkspace/AGENTS.md\n")
    (ws / "workspace" / "skills" / "s").mkdir(parents=True)
    (ws / "workspace" / "skills" / "s" / "SKILL.md").write_text("skill")
    (ws / "workspace" / "AGENTS.md").write_text("doc")
    (ws / "workspace" / "deck.json").write_text("{}")


def test_the_nesting_base_s_own_directory_is_not_a_user_path(ws, c):
    """DELETE workspace would have removed nanobot's whole working directory."""
    _nanobot(ws)
    assert c.delete("/file", params={"identifier": "s", "path": "workspace"}).status_code == 404
    assert c.post("/file/move", params={"identifier": "s", "path": "workspace", "to": "w2"}).status_code == 404
    assert (ws / "workspace" / "deck.json").exists() and (ws / "workspace" / "skills").is_dir()


@pytest.mark.parametrize("call", [
    ("delete", {"path": "skills"}), ("delete", {"path": "AGENTS.md"}),
    ("delete", {"path": "skills/s/SKILL.md"}), ("move", {"path": "skills", "to": "s2"}),
    ("move", {"path": "deck.json", "to": "skills/deck.json"}), ("mkdir", {"path": "memory/new"})])
def test_the_base_s_excluded_machinery_is_refused(ws, c, call):
    _nanobot(ws)
    op, params = call
    if op == "delete":
        r = c.delete("/file", params={"identifier": "s", **params})
    else:
        r = c.post(f"/file/{op}", params={"identifier": "s", **params})
    assert r.status_code == 400
    assert (ws / "workspace" / "skills" / "s" / "SKILL.md").exists() and (ws / "workspace" / "AGENTS.md").exists()


def test_a_flat_base_s_excluded_files_are_refused(ws, c):
    (ws / ".git" / "info").mkdir(parents=True)
    (ws / ".git" / "info" / "exclude").write_text("SOUL.md\nmemory/\n")
    (ws / "SOUL.md").write_text("s")
    (ws / "notes.md").write_text("n")
    assert c.delete("/file", params={"identifier": "s", "path": "SOUL.md"}).status_code == 400
    assert c.delete("/file", params={"identifier": "s", "path": "notes.md"}).status_code == 200
    assert (ws / "SOUL.md").exists()


def test_a_file_written_at_the_root_between_turns_is_still_reachable(ws, c):
    """An app's PUT lands at the session root until the next turn adopts it into the agent's directory."""
    _nanobot(ws)
    (ws / "sheet.json").write_text("rows")
    r = c.post("/file/move", params={"identifier": "s", "path": "sheet.json", "to": "kept.json"})
    assert r.status_code == 200 and (ws / "kept.json").read_text() == "rows"


def test_a_move_under_a_file_is_409(ws, c):
    (ws / "notes.txt").write_text("n")
    (ws / "a.md").write_text("a")
    r = c.post("/file/move", params={"identifier": "s", "path": "a.md", "to": "notes.txt/a.md"})
    assert r.status_code == 409 and (ws / "a.md").exists()


def test_a_new_folder_on_the_nesting_base_goes_in_the_agent_s_directory(ws, c):
    """Where the checkpoint's copy of the change puts it (backing.tar_change), so the two agree."""
    _nanobot(ws)
    r = c.post("/file/mkdir", params={"identifier": "s", "path": "slides/old"})
    assert r.status_code == 200 and r.json()["path"] == "workspace/slides/old"
    assert (ws / "workspace" / "slides" / "old").is_dir() and not (ws / "slides").exists()
    (ws / "workspace" / "notes").write_text("a file")
    assert c.post("/file/mkdir", params={"identifier": "s", "path": "notes/x"}).status_code == 409


def test_an_existing_root_folder_is_found_before_a_new_one_is_made(ws, c):
    """A folder an app's PUT made at the root between turns is the one mkdir answers for."""
    _nanobot(ws)
    (ws / "data").mkdir()
    r = c.post("/file/mkdir", params={"identifier": "s", "path": "data"})
    assert r.status_code == 200 and r.json()["created"] is False and not (ws / "workspace" / "data").exists()


@pytest.mark.parametrize("rel", ["skills", "skills/x", "workspace/skills", "workspace/skills/s/SKILL.md",
                                 "workspace", "workspace/deck.json", "SOUL.md", "SOUL.md.bak", "memory",
                                 "memory/a", "memo", "workspace/AGENTS.md", "workspace/AGENTS.mdx"])
def test_the_protection_rule_is_the_gateway_s(rel):
    """The runner and the gateway's checkpoint path each apply it; the two must agree."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))
    import backing  # noqa: E402
    pats = ("workspace/skills/", "workspace/AGENTS.md", "SOUL.md", "memory/")
    assert server._ws_protected(rel, pats) == backing.ws_protected(rel, pats)


def test_a_put_replaces_the_nesting_base_s_file_where_it_is(ws, c):
    """Written at the root it sat beside the agent's copy, which every read found first."""
    _nanobot(ws)
    r = c.put("/file", params={"identifier": "s", "path": "deck.json"}, content=b'{"v":2}')
    assert r.status_code == 200 and r.json()["path"] == "workspace/deck.json"
    assert (ws / "workspace" / "deck.json").read_bytes() == b'{"v":2}' and not (ws / "deck.json").exists()
    r = c.put("/file", params={"identifier": "s", "path": "new.json"}, content=b"n")
    assert r.json()["path"] == "new.json"                     # a new file: the root, adopted next turn


def test_a_delete_on_the_nesting_base_removes_every_copy(ws, c):
    _nanobot(ws)
    (ws / "notes.md").write_text("app")                       # an older PUT, beside the agent's copy
    (ws / "workspace" / "notes.md").write_text("agent")
    assert c.delete("/file", params={"identifier": "s", "path": "notes.md"}).status_code == 200
    assert not (ws / "notes.md").exists() and not (ws / "workspace" / "notes.md").exists()
