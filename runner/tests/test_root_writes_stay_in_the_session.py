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

_ROOT_ON_LINUX = sys.platform.startswith("linux") and os.geteuid() == 0
if os.environ.get("HR_REQUIRE_ROOT_TESTS") == "1" and not _ROOT_ON_LINUX:
    # The CI step that exists to run this file as root sets this, so the file can never quietly go back to
    # skipping there: anything other than root on Linux fails the step instead.
    raise RuntimeError("HR_REQUIRE_ROOT_TESTS=1, and these tests are not running as root on Linux")
pytestmark = pytest.mark.skipif(not _ROOT_ON_LINUX, reason="the write-wall is root's, on Linux")
UID = 20777


def _session(monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    ws = tempfile.mkdtemp(prefix="hrws-")
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    return ws


def _victim(text="root's own", dir_mode=0o700):
    d = tempfile.mkdtemp(prefix="hrvictim-")
    os.chmod(d, dir_mode)                      # root's, as /data/secrets or another session's directory is
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


class _StubProc:
    """Stands in for a CLI that exits at once with nothing to say: only the runner's own writes happen."""

    def __init__(self, cmd, **kw):
        self.args, self.pid, self.returncode = cmd, 999999, 0
        self.stdout = __import__("io").StringIO("")
        self.stderr = __import__("io").StringIO("")
        self.stdin = __import__("io").StringIO()
    poll = wait = lambda self, *a, **k: 0
    kill = terminate = send_signal = lambda self, *a, **k: None
    communicate = lambda self, *a, **k: ("", "")
    __enter__ = lambda self: self
    __exit__ = lambda self, *exc: False


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
    monkeypatch.setattr(server.subprocess, "Popen", lambda cmd, *a, **kw: spawned.append(cmd) or _StubProc(cmd, **kw))
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


# ── every per-turn configuration write, through the real /turn path ───────────────────────────
# Each family below is a file the runner writes into the session's tree on every turn (or on a continued one).
# Before the turn its real path is a link to a file of root's, mode 0600, in a directory a session can pass
# through: the name resolves, so the write is genuinely attempted. The turn either runs (200) or is refused in
# words (a 4xx with a detail), and the file of root's keeps its bytes, its owner and its mode, with nothing
# written beside it.

def _workspaces(monkeypatch):
    root = tempfile.mkdtemp(prefix="hrroot-")
    os.chmod(root, 0o751)                     # as the image makes /data/workspaces: passable, not listable
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    monkeypatch.setattr(server, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(server, "_ws", lambda identifier="": os.path.join(root, identifier or "s1"))
    monkeypatch.setattr(server.subprocess, "Popen", lambda cmd, *a, **kw: _StubProc(cmd, **kw))
    return root


def _own(ws: pathlib.Path, rel: str) -> pathlib.Path:
    """`rel`'s parent folders inside the session, each the session's, as a turn of its own would leave them."""
    p = ws
    for part in pathlib.Path(rel).parts[:-1]:
        p = p / part
        p.mkdir(exist_ok=True)
        os.lchown(p, UID, UID)
    return ws / rel


def _settle(client, ident: str, r) -> dict:
    """The finished turn's record, or {} when the turn was refused before it started."""
    if r.status_code != 200:
        return {}
    tid = r.json()["turn_id"]
    for _ in range(300):
        got = client.get(f"/turn/{tid}", params={"identifier": ident}).json()
        if got.get("done"):
            return got
        __import__("time").sleep(0.05)
    raise AssertionError("the turn did not finish")


def _assert_clean(r, before: tuple) -> None:
    """A turn that ran, or one refused in words: never an unhandled error."""
    if r.status_code != 200:
        assert 400 <= r.status_code < 500, (r.status_code, r.text[:300])
        assert "detail" in r.json() and "Traceback" not in r.text, r.text[:300]
    d, victim, st = before
    assert victim.read_text() == "root's own", "the file of root's was written through the link"
    now = os.stat(victim)
    assert (now.st_uid, now.st_gid, now.st_mode & 0o7777) == (st.st_uid, st.st_gid, st.st_mode & 0o7777)
    assert sorted(os.listdir(d)) == ["victim"], f"written beside it: {sorted(os.listdir(d))}"


_KEYED = {"api_key": "k-0123456789abcdef", "base_url": "https://up.example/v1"}
_WRITE_FAMILIES = {
    # family: (backend, provider, auth, the planted path, extra turn fields)
    "claude-settings": ("claude", "anthropic", {"api_key": "k-0123456789abcdef"},
                        ".harness/home/.claude/settings.json", {"tools_disabled": ["Bash"]}),
    "claude-instructions": ("claude", "anthropic", {"api_key": "k-0123456789abcdef"}, "CLAUDE.md", {}),
    "gemini-settings": ("gemini", "google", {"api_key": "k-0123456789abcdef"},
                        ".harness/home/.gemini/settings.json", {"tools_disabled": ["run_shell_command"]}),
    "qwen-settings": ("qwen", "openai-api", _KEYED, ".harness/home/.qwen/settings.json",
                      {"tools_disabled": ["run_shell_command"]}),
    "cline-global-settings": ("cline", "openai-api", _KEYED,
                              ".harness/home/.cline/data/settings/global-settings.json",
                              {"tools_disabled": ["run_commands"]}),
    "cline-mcp-settings": ("cline", "openai-api", _KEYED,
                           ".harness/home/.cline/data/settings/cline_mcp_settings.json", {}),
    "cline-providers": ("cline", "openai-api", _KEYED, ".harness/home/.cline/data/settings/providers.json", {}),
    "codex-config": ("codex", "openai", _KEYED, ".harness/home/.codex/config.toml", {"tools_disabled": ["shell"]}),
    "codex-instructions": ("codex", "openai", _KEYED, "AGENTS.md", {}),
    "codex-rollout": ("codex", "openai", _KEYED,
                      ".harness/home/.codex/sessions/2026/11/09/rollout-2026-11-09T00-00-00-hsessrollout.jsonl",
                      {"codex_appserver": True}),
    "hermes-config": ("hermes", "openai-api", _KEYED, ".harness/home/.hermes/config.yaml",
                      {"tools_disabled": ["terminal"]}),
    "hermes-state": ("hermes", "openai-api", _KEYED, ".harness/home/.hermes/state.db", {}),
    "fast-agent-session": ("fast-agent", "openai-api", _KEYED,
                           ".harness/fast-agent/sessions/hsessresumed/session.json", {}),
}


@pytest.mark.parametrize("continued", [False, True], ids=["first-turn", "continued-turn"])
@pytest.mark.parametrize("family", sorted(_WRITE_FAMILIES))
def test_a_per_turn_write_through_a_planted_link_leaves_roots_file_alone(family, continued, monkeypatch):
    from fastapi.testclient import TestClient
    backend, provider, auth, rel, extra = _WRITE_FAMILIES[family]
    root = _workspaces(monkeypatch)
    ident = f"hsessw{family.replace('-', '')}{int(continued)}"
    ws = pathlib.Path(root, ident)
    ws.mkdir()
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    d, victim = _victim(dir_mode=0o755)        # reachable by name, so the write is attempted, not skipped
    link = _own(ws, rel)
    link.symlink_to(victim)
    os.lchown(link, UID, UID)
    body = {"backend": backend, "provider": provider, "model": server.BACKENDS[backend]["default_model"],
            "prompt": "hi", "auth": auth, "agent_doc": "first instructions", **extra}
    if continued:
        # A continued task whose instructions were edited since its last turn, so the paths that run only
        # then (a stored prompt let go, the note that the instructions changed) run too.
        doc = server._agent_doc_path(str(ws), backend)
        if not doc.is_symlink():
            _own(ws, str(doc.relative_to(ws)))
            doc.write_text("the instructions before the edit\n")
            os.lchown(doc, UID, UID)
        body.update(resume_session_id="hsessresumed", agent_doc="edited instructions")
    before = (d, victim, os.stat(victim))
    client = TestClient(server.app, raise_server_exceptions=False)
    r = client.post("/turn", params={"identifier": ident}, json=body)
    _settle(client, ident, r)
    _assert_clean(r, before)

