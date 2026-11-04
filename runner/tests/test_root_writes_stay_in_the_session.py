"""The runner's root writes into a session's tree go nowhere a link the agent planted there points (GHSA-m479).

A session's tree is the agent's: between turns it can replace any name in it with a link. The runner, root,
wrote the git ignore list, the skills, the plugins and every CLI's configuration there, cleaned up skills by
rmtree, and handed files back by chown, each following such a link out of the tree: a root-owned file
overwritten (Part B), another session's workspace deleted or written into (Part C), a root file handed to the
session (Part D). These run as root on Linux, where the wall exists; elsewhere there is nothing to test.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux") or os.geteuid() != 0,
                                reason="the write-wall is root's, on Linux")
UID = 20777


def _session(monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    ws = tempfile.mkdtemp(prefix="hrws-")
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    return ws


def _victim(text="root's own"):
    d = tempfile.mkdtemp(prefix="hrvictim-")
    os.chmod(d, 0o700)                         # root's, as /data/secrets or another session's directory is
    f = pathlib.Path(d) / "victim"
    f.write_text(text)
    os.chmod(f, 0o600)
    return d, f


def test_the_ignore_list_is_not_written_through_a_link(monkeypatch):
    ws = _session(monkeypatch)
    _, victim = _victim()
    (pathlib.Path(ws) / ".gitignore").symlink_to(victim)
    os.lchown(pathlib.Path(ws) / ".gitignore", UID, UID)
    server._git_ensure(ws)
    assert victim.read_text() == "root's own"                                 # Part B
    gi = pathlib.Path(ws) / ".gitignore"
    assert not gi.is_symlink() and "never persist secrets" in gi.read_text()


def test_a_skills_root_linked_elsewhere_is_neither_written_nor_cleaned(monkeypatch):
    ws = _session(monkeypatch)
    other, _ = _victim()
    (pathlib.Path(other) / "other-sid").mkdir()                               # another session's workspace
    home = pathlib.Path(ws) / ".harness" / "home" / ".claude"
    home.mkdir(parents=True)
    (home / "skills").symlink_to(other)
    ledger = pathlib.Path(ws) / ".harness" / "skills-written.json"
    ledger.write_text(json.dumps(["other-sid"]))
    for p in (pathlib.Path(ws) / ".harness", home.parent, home, home / "skills", ledger):
        os.lchown(p, UID, UID)
    with server._fs_as(UID):
        server._write_skills(ws, [{"name": "evil", "files": [{"path": "SKILL.md", "content": "planted"}]}], "claude")
    assert (pathlib.Path(other) / "other-sid").is_dir(), "another session's directory was deleted"   # Part C
    assert not (pathlib.Path(other) / "evil").exists(), "a skill was written outside the session"


def test_the_chown_walk_follows_no_link(monkeypatch):
    ws = _session(monkeypatch)
    _, victim = _victim()
    (pathlib.Path(ws) / "sub").mkdir()
    (pathlib.Path(ws) / "sub" / "out").symlink_to(victim.parent)              # a directory link out of the tree
    server._own_tree(ws, UID, {0})
    assert victim.stat().st_uid == 0 and victim.parent.stat().st_uid == 0   # Part D: nothing outside changed hands


def test_the_session_identity_is_this_threads_only(monkeypatch):
    _session(monkeypatch)
    _, victim = _victim()
    seen = {}
    inside = threading.Event()
    done = threading.Event()

    def other_thread():
        inside.wait(5)
        try:
            victim.write_text("root writes on another thread")             # root's identity, unchanged
            seen["other"] = "wrote"
        except PermissionError:
            seen["other"] = "refused"
        done.set()
    t = threading.Thread(target=other_thread)
    t.start()
    with server._fs_as(UID):
        with pytest.raises(PermissionError):
            victim.write_text("as the session")                           # this thread: the session's identity
        inside.set()
        done.wait(5)
    t.join()
    assert seen["other"] == "wrote"
    victim.write_text("root again")                                         # restored on leaving


@pytest.mark.parametrize("backend,provider,auth", [
    ("codex", "openai", {"api_key": "k-0123456789abcdef", "base_url": "https://up.example/v1"}),
    ("claude", "anthropic", {"api_key": "k-0123456789abcdef"}),
    ("pi", "openai-api", {"api_key": "k-0123456789abcdef", "base_url": "https://up.example/v1"}),
    ("hermes", "openai-api", {"api_key": "k-0123456789abcdef", "base_url": "https://up.example/v1"}),
    ("gemini", "google", {"api_key": "k-0123456789abcdef"}),
    ("opencode", "openai-api", {"api_key": "k-0123456789abcdef", "base_url": "https://up.example/v1"}),
])
def test_a_new_sessions_first_turn_builds_as_the_session(backend, provider, auth, monkeypatch):
    """Everything the runner writes before the CLI starts is written as the session (its HOME, its configs, its
    skills, its agent doc), on a session's very first turn, when the directory was only just made. A folder made
    as root in between left the builders, writing as the session, refused inside it."""
    from fastapi.testclient import TestClient
    root = tempfile.mkdtemp(prefix="hrroot-")
    os.chmod(root, 0o751)                     # as the image makes /data/workspaces: passable, not listable
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    monkeypatch.setattr(server, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(server, "_ws", lambda identifier="": os.path.join(root, identifier or "s1"))
    spawned = []

    class _P:
        def __init__(self, cmd, **kw):
            self.args, self.pid, self.returncode = cmd, 999999, 0
            self.stdout = self.stderr = __import__("io").StringIO("")
        poll = wait = lambda self, *a, **k: 0
        kill = terminate = send_signal = lambda self, *a, **k: None
        communicate = lambda self, *a, **k: ("", "")
        __enter__ = lambda self: self
        __exit__ = lambda self, *exc: False
    monkeypatch.setattr(server.subprocess, "Popen", lambda cmd, *a, **kw: spawned.append(cmd) or _P(cmd, **kw))
    r = TestClient(server.app).post("/turn", params={"identifier": f"hsess{backend}"},
                                    json={"backend": backend, "provider": provider, "model": server.BACKENDS[backend]["default_model"],
                                          "prompt": "hi", "auth": auth,
                                          "skills": [{"name": "s", "files": [{"path": "SKILL.md", "content": "x"}]}]})
    assert r.status_code == 200, (r.status_code, r.text[:400])
    ws = pathlib.Path(root, f"hsess{backend}")
    uid = ws.stat().st_uid
    assert server._SESSION_UID_BASE <= uid
    rooted = [str(p.relative_to(ws)) for p in ws.rglob("*") if p.lstat().st_uid == 0]
    assert rooted == [], f"left root-owned in the session: {rooted[:8]}"


def test_a_scope_inside_another_leaves_the_outer_one_in_force(monkeypatch):
    _session(monkeypatch)
    _, victim = _victim()
    with server._fs_as(UID):
        with server._fs_as(UID):
            pass
        with pytest.raises(PermissionError):
            victim.write_text("still the session")             # the inner scope's exit did not hand back root
    victim.write_text("root again")


GROUP_ZERO_PROBE = """
import os, pathlib, sys
os.setgroups([0])                        # root's list in a container, whatever this test process was given
sys.path.insert(0, sys.argv[2])
import server
print("groups", os.getgroups())
try:
    with server._fs_as(int(sys.argv[3])):
        pathlib.Path(sys.argv[1]).write_text("planted")
    print("written")
except PermissionError:
    print("refused")
"""


def test_the_wall_leaves_a_session_scope_no_group_zero(tmp_path):
    """_fs_as changes the filesystem uid and gid and leaves the supplementary groups, so with root's group 0 a link
    the session planted still reached what group 0 could write. The wall drops them when the runner starts."""
    d = tempfile.mkdtemp(prefix="hrgroup-")
    os.chmod(d, 0o755)
    victim = pathlib.Path(d) / "victim"
    victim.write_text("root's own")
    os.chown(victim, 0, 0)
    os.chmod(victim, 0o664)
    runner = str(pathlib.Path(__file__).resolve().parents[1])
    env = {**os.environ, "HR_SESSION_UIDS": "1", "HARNESS_WORKSPACE": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", GROUP_ZERO_PROBE, str(victim), runner, str(UID)],
                         env=env, cwd=runner, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    assert "groups []" in out.stdout and "refused" in out.stdout, out.stdout[-300:]
    assert victim.read_text() == "root's own"


def test_a_planted_link_refuses_the_turn_at_once(monkeypatch):
    """A verdict the gateway does not wait out, and nothing written through the link."""
    root = tempfile.mkdtemp(prefix="hrroot-")
    os.chmod(root, 0o755)
    monkeypatch.setattr(server, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    _, victim = _victim()
    ws = pathlib.Path(root) / "hsessplanted"
    (ws / ".harness").mkdir(parents=True)
    link = ws / ".harness" / "mcp.json"
    link.symlink_to(victim)
    for p in (ws, ws / ".harness", link):
        os.lchown(p, UID, UID)
    req = server.TurnReq(prompt="x", provider="anthropic", input_requests=True, auth=server.Auth(api_key="k"))
    with pytest.raises(HTTPException) as e:
        server.turn(req, "hsessplanted")
    assert e.value.status_code == 409 and root not in e.value.detail
    assert victim.read_text() == "root's own"
