"""Every route on a session's files refuses a path with a segment that starts with a dot (2026-11-03).

Default deny: those hold per-turn config that can carry a server's credential, the marker naming the agent's directory,
git's hooks, a credential file an older runner left behind, and whatever the next CLI adds. No list of names to keep up."""
import asyncio
import json

import pytest
from test_plugs_local import client, _req  # noqa: F401
import app as gw

STATE = [".harness/agent-subdir", ".harness/mcp.json", ".harness/home/.codex/config.toml", ".git/config", ".git/hooks/pre-commit",
         ".claude/settings.json", ".codex/config.toml", ".codex/auth.json", ".mcp.json", ".claude.json", ".credentials.json",
         ".gcp-sa.json", "workspace/.harness/mcp.json", "dir/.git/config", "dir/.mcp.json", "dir/.credentials.json", "dir/.gcp-sa.json",
         ".foo", ".foo/bar", "a/.b/c", ".env", ".env.example", ".gitignore"]
ORDINARY = ["deck.json", "src/app/page.tsx", "harness/notes.md", "my.codex/a.txt", "git/config", "a.b/c.d", "my file.txt", "x..y"]


@pytest.fixture
def box(monkeypatch):
    calls = []

    async def read(sid, path):
        calls.append(("read", path))
        return b"from the workspace"

    async def write(sid, path, data):
        calls.append(("write", path))
        return True

    async def owned(request, sid):
        return "org.x", {}

    monkeypatch.setattr(gw.BACKING.workspace, "read", read)
    monkeypatch.setattr(gw.BACKING.workspace, "write", write)
    monkeypatch.setattr(gw, "_owned_session", owned)
    return calls


@pytest.mark.parametrize("path", ["./.harness/x", "a/../.git/config", "//.claude/x", ".harness", ".git", "a/.codex", "b/../.mcp.json", "c/./.gcp-sa.json",
                                  ".", "..", "../x", "a/..", "a/.", "a//b", "a/", " .git/config", ".git /config", "\u00a0.git/config", "a/ .b/c",
                                  "\t.git/config", ".git\n/config", "a\\b", ".git\\config", "a\x00b", ""])
def test_no_spelling_gets_past_it(path):
    assert not gw._ws_path_allowed(path), repr(path)


def test_the_backing_cannot_turn_an_allowed_path_into_a_refused_one():
    """It strips what it is given: whatever passes here must be the same path to it, or the check reads one path and the backing another."""
    import backing
    for path in ORDINARY + [" .git/config", "\u2003.git/config", "/ .git/config", "/report.md"]:
        if gw._ws_path_allowed(path):
            assert backing._safe_member(path) == path.lstrip("/"), repr(path)


@pytest.mark.parametrize("path", STATE)
def test_a_read_by_path_never_reaches_the_workspace(client, box, path):  # noqa: F811
    r = _req(client, "GET", f"/v1/sessions/s1/files/{path}")
    assert r.status_code == 404 and b"from the workspace" not in r.content and box == [], r.text


@pytest.mark.parametrize("path", STATE)
def test_a_write_by_path_never_reaches_the_workspace(client, box, path):  # noqa: F811
    r = _req(client, "PUT", f"/v1/sessions/s1/files/{path}", {"content": "x"})
    assert r.status_code == 400 and box == [], r.text


@pytest.mark.parametrize("path", ORDINARY)
def test_a_persons_own_files_go_as_ever(client, box, path):  # noqa: F811
    assert _req(client, "GET", f"/v1/sessions/s1/files/{path}").content == b"from the workspace"
    assert _req(client, "PUT", f"/v1/sessions/s1/files/{path}", {"content": "x"}).status_code == 200
    assert box == [("read", path), ("write", path)]


@pytest.mark.parametrize("path", STATE)
def test_a_crafted_file_id_opens_nothing(monkeypatch, path):
    async def never(*_a, **_k):
        raise AssertionError("a state path reached the checkpoint")
    monkeypatch.setattr(gw, "_ws_files", never)
    monkeypatch.setattr(gw, "_workspace_tar", never)
    assert not gw._ws_visible(path)
    assert asyncio.run(gw._container_file_bytes("s1", gw._wf_id(path))) is None


@pytest.mark.parametrize("name,served", [("dir/.mcp.json", False), (".credentials.json", False), ("report.md", True)])
def test_a_capture_is_served_by_its_id_only_when_its_name_is_a_persons(monkeypatch, name, served):
    async def blob(key, **_k):
        return json.dumps({"filename": name}).encode() if key.endswith(".meta") else b"bytes"
    monkeypatch.setattr(gw, "_blob_get", blob)
    got = asyncio.run(gw._container_file_bytes("s1", "cfile_x"))
    assert (got is not None) == served and (not got or got[0] == b"bytes")


@pytest.mark.parametrize("path", STATE)
def test_move_mkdir_and_delete_refuse_it(box, path):
    for call in (lambda: gw.delete_session_file("s1", path, request=None),
                 lambda: gw.mkdir_session_file("s1", path, request=None),
                 lambda: gw.move_session_file("s1", path, gw.WorkspaceMove(to="ok"), request=None),
                 lambda: gw.move_session_file("s1", "ok", gw.WorkspaceMove(to=path), request=None)):
        with pytest.raises(Exception) as e:
            asyncio.run(call())
        assert e.value.status_code == 400 and e.value.detail["code"] == "invalid_input", path
    assert box == []


def test_an_apps_earlier_write_of_it_is_not_put_back(monkeypatch, box):
    """An app's write taken before this rule would otherwise come back at the start of the next turn."""
    async def caps(sid):
        return {".git/hooks/pre-commit": ("cfile_a", True), "dir/.mcp.json": ("cfile_b", True), "deck.json": ("cfile_c", True)}

    async def blob(key, **_k):
        return b"bytes"
    monkeypatch.setattr(gw, "_newest_captures", caps)
    monkeypatch.setattr(gw, "_blob_get", blob)
    assert asyncio.run(gw._reapply_app_writes("s1")) == 1
    assert box == [("write", "deck.json")]


def test_a_stored_read_does_not_follow_a_link_in_the_archive():
    """`sub/link -> ../.harness/mcp.json` passes the check on its spelling, and extractfile would follow it."""
    import io
    import tarfile
    import backing

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in ((".harness/mcp.json", b"secret"), ("plain.txt", b"ordinary")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("sub/link")
        link.type, link.linkname = tarfile.SYMTYPE, "../.harness/mcp.json"
        tf.addfile(link)

    class Blob:
        async def get(self, kb, key):
            return buf.getvalue()
    ws = backing.CheckpointWorkspaceFiles(Blob(), "kb", lambda sid: f"sessions/{sid}/checkpoint")
    assert asyncio.run(ws.read("s1", "plain.txt")) == b"ordinary"
    assert gw._ws_path_allowed("sub/link") and asyncio.run(ws.read("s1", "sub/link")) is None


def test_a_stored_write_does_not_go_through_a_link_in_the_archive():
    """Nothing resolves at write time here: `link/x` would sit beside `link -> .harness`, and the next unpack puts it in `.harness/`."""
    import io
    import tarfile
    import backing

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        link = tarfile.TarInfo("link")
        link.type, link.linkname = tarfile.SYMTYPE, ".harness"
        tf.addfile(link)
        info = tarfile.TarInfo("plain.txt")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    store = {"k": buf.getvalue()}

    class Blob:
        async def get(self, kb, key):
            return store["k"]

        async def put(self, kb, key, data):
            store["k"] = data
            return True
    ws = backing.CheckpointWorkspaceFiles(Blob(), "kb", lambda sid: "k")
    before = store["k"]
    assert asyncio.run(ws.write("s1", "link/x", b"y")) is False and store["k"] == before
    assert asyncio.run(ws.write("s1", "plain.txt/x", b"y")) is False and store["k"] == before
    assert asyncio.run(ws.write("s1", "folder/x", b"y")) is True


def test_a_turn_does_not_keep_what_no_route_would_serve():
    for name in (".env", ".foo/x", "a/.b/c", "sub/.npmrc", ".harness/x"):
        assert gw._is_internal_output(name), name
    for name in ("report.md", "src/app/page.tsx"):
        assert not gw._is_internal_output(name), name


def test_an_old_turns_archive_leaves_a_dot_name_out_and_still_downloads(client, monkeypatch):  # noqa: F811
    import io
    import zipfile

    async def owned(request, sid):
        return "org.x", {}

    async def blob(key, **_k):
        if key.endswith("changed.json"):
            return json.dumps({"files": [{"file_id": "cfile_a", "path": ".env"}, {"file_id": "cfile_b", "path": "report.md"}]}).encode()
        if key.endswith("cfile_b.meta"):
            return json.dumps({"filename": "report.md"}).encode()
        if key.endswith(".meta"):
            return json.dumps({"filename": ".env"}).encode()
        return b"bytes"
    monkeypatch.setattr(gw, "_owned_session", owned)
    monkeypatch.setattr(gw, "_blob_get", blob)
    r = _req(client, "GET", "/v1/sessions/s1/files/archive?changed=true")
    assert r.status_code == 200, r.text
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["report.md"]
