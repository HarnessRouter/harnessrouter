"""A symlink can't carry a file route to a dot name in the session (2026-11-03).

The gateway refuses a path on its spelling. Only the runner can see where a link goes: `link/x` looks ordinary and,
resolved, lands in `.harness/x`. The fuzz measured a PUT through such a link changing the file behind it."""
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "root"; root.mkdir()
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    d = root / "hsesslinks"; d.mkdir()
    (d / ".harness").mkdir(); (d / ".harness" / "mcp.json").write_text("secret")
    (d / "a" / ".b").mkdir(parents=True); (d / "a" / ".b" / "c").write_text("secret")
    (d / "sub").mkdir(); (d / "plain.txt").write_text("ordinary")
    (d / "link-dir").symlink_to(".harness")
    (d / "sub" / "link-file").symlink_to("../.harness/mcp.json")
    (d / "sub" / "link-b").symlink_to("../a/.b")
    (d / "link-ok").symlink_to("plain.txt")
    return d


Q = {"identifier": "hsesslinks"}
THROUGH = ["link-dir/mcp.json", "sub/link-file", "sub/link-b/c"]


@pytest.mark.parametrize("path", THROUGH)
def test_a_read_through_a_link_is_refused(ws, path):
    r = TestClient(server.app).get("/file", params={**Q, "path": path})
    assert r.status_code == 404 and b"secret" not in r.content


def test_an_ordinary_link_still_reads(ws):
    r = TestClient(server.app).get("/file", params={**Q, "path": "link-ok"})
    assert r.status_code == 200 and r.content == b"ordinary"


@pytest.mark.parametrize("path", THROUGH + ["link-dir/new.json", "sub/link-b/new"])
def test_a_write_through_a_link_is_refused(ws, path):
    r = TestClient(server.app).put("/file", params={**Q, "path": path}, content=b"changed")
    assert r.status_code == 400, r.text
    assert (ws / ".harness" / "mcp.json").read_text() == "secret" and (ws / "a" / ".b" / "c").read_text() == "secret"
    assert not (ws / ".harness" / "new.json").exists() and not (ws / "a" / ".b" / "new").exists()


@pytest.mark.parametrize("path", ["link-dir/mcp.json", "sub/link-b/c"])
def test_a_delete_through_a_link_is_refused(ws, path):
    r = TestClient(server.app).delete("/file", params={**Q, "path": path})
    assert r.status_code == 400, r.text
    assert (ws / ".harness" / "mcp.json").exists() and (ws / "a" / ".b" / "c").exists()


@pytest.mark.parametrize("path", ["link-dir/newdir", "sub/link-b/newdir"])
def test_a_mkdir_through_a_link_is_refused(ws, path):
    assert TestClient(server.app).post("/file/mkdir", params={**Q, "path": path}).status_code == 400
    assert not (ws / ".harness" / "newdir").exists() and not (ws / "a" / ".b" / "newdir").exists()


def test_a_move_through_a_link_is_refused_either_way(ws):
    c = TestClient(server.app)
    assert c.post("/file/move", params={**Q, "path": "link-dir/mcp.json", "to": "out.json"}).status_code == 400
    assert c.post("/file/move", params={**Q, "path": "plain.txt", "to": "link-dir/in.txt"}).status_code == 400
    assert (ws / ".harness" / "mcp.json").exists() and (ws / "plain.txt").exists() and not (ws / "out.json").exists()


def test_removing_a_link_itself_touches_nothing_behind_it(ws):
    assert TestClient(server.app).delete("/file", params={**Q, "path": "sub/link-file"}).status_code == 200
    assert (ws / ".harness" / "mcp.json").read_text() == "secret" and not (ws / "sub" / "link-file").is_symlink()
