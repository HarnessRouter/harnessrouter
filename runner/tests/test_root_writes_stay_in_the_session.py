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
import stat
import shutil
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
    rooted = []
    for top, dirs, files in os.walk(ws):          # the turn's own thread is still at work: what it removes
        for name in dirs + files:                 # meanwhile (its prompt file) is no longer there to read
            try:
                if os.lstat(os.path.join(top, name)).st_uid == 0:
                    rooted.append(os.path.relpath(os.path.join(top, name), ws))
            except FileNotFoundError:
                pass
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



# ── what the runner reads back from a session's tree, it reads as the session ─────────────────
# After a turn the runner reads files the CLI wrote into the session's tree (a database, a transcript, an
# export, a log) and turns them into the turn's events, its result and its usage. Each read below is made as
# the session, so a link the session planted at that name leads nowhere it could not read itself: here, to the
# same kind of file in a second session's tree (another uid, its folder 0700, the file 0600), none of whose
# words may reach this turn.
UID2 = 20778
OTHERS = "words from the other session"


def _second_sessions(rel: str, content: bytes | None = None) -> pathlib.Path:
    """A file at `rel` in a second session's tree, that session's own."""
    top = pathlib.Path(tempfile.mkdtemp(prefix="hrother-"))
    os.chown(top, UID2, UID2)
    os.chmod(top, 0o700)
    f = top / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content or b"")
    for p in [f, *f.parents]:
        if p == top.parent:
            break
        os.chown(p, UID2, UID2)
    os.chmod(f, 0o600)
    return f


def _plant(ws: pathlib.Path, rel: str, target: pathlib.Path) -> None:
    link = _own(ws, rel)
    link.symlink_to(target)
    os.lchown(link, UID, UID)


def _a_session(monkeypatch) -> pathlib.Path:
    ws = pathlib.Path(_session(monkeypatch))
    return ws


def test_hermes_reads_its_database_as_the_session(monkeypatch):
    """The turn's events and usage come from hermes's state.db, read after the CLI ran."""
    import sqlite3
    import time
    from fastapi.testclient import TestClient
    other = _second_sessions(".harness/home/.hermes/state.db")
    db = sqlite3.connect(other)
    db.execute("CREATE TABLE sessions (id TEXT, started_at REAL, input_tokens INT, output_tokens INT)")
    db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, "
               "tool_calls TEXT, tool_call_id TEXT)")
    db.execute("INSERT INTO sessions VALUES ('20261109_other', ?, 4321, 1234)", (time.time() + 60,))
    db.execute("INSERT INTO messages (session_id, role, content) VALUES ('20261109_other', 'assistant', ?)", (OTHERS,))
    db.commit()
    db.close()
    os.chown(other, UID2, UID2)
    os.chmod(other, 0o600)
    root = _workspaces(monkeypatch)
    ws = pathlib.Path(root, "hsesshermesread")
    ws.mkdir()
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    _plant(ws, ".harness/home/.hermes/state.db", other)
    client = TestClient(server.app, raise_server_exceptions=False)
    r = client.post("/turn", params={"identifier": "hsesshermesread"},
                    json={"backend": "hermes", "provider": "openai-api", "model": server.BACKENDS["hermes"]["default_model"],
                          "prompt": "hi", "auth": _KEYED})
    got = _settle(client, "hsesshermesread", r)
    assert r.status_code == 200, r.text[:300]
    seen = json.dumps(got)
    assert OTHERS not in seen and "20261109_other" not in seen
    assert '"input_tokens": 4321' not in seen


def test_opensquilla_reads_its_transcript_as_the_session(monkeypatch):
    """Everything an opensquilla turn shows comes from its transcript, read at the end of the turn."""
    line = {"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": OTHERS}]}}
    other = _second_sessions(".harness/opensquilla/transcript.jsonl", (json.dumps(line) + "\n").encode())
    ws = _a_session(monkeypatch)
    _plant(ws, ".harness/opensquilla/transcript.jsonl", other)
    evs = server._opensquilla_eof({"cwd": str(ws), "prompt": "hi"}, 0)
    assert OTHERS not in json.dumps(evs)


def test_vibe_reads_its_export_as_the_session(monkeypatch):
    """A vibe turn's outcome, its error and its usage come from the export it wrote."""
    exp = {"outcome": "error", "error": {"message": OTHERS, "code": "x"},
           "usage": {"prompt_tokens": 4321, "completion_tokens": 1234}}
    other = _second_sessions(".harness/vibe/out/export.json", json.dumps(exp).encode())
    ws = _a_session(monkeypatch)
    _plant(ws, ".harness/vibe/out/export.json", other)
    evs = server._vibe_eof({"cwd": str(ws)}, 1)
    seen = json.dumps(evs)
    assert OTHERS not in seen and "4321" not in seen


def test_kimi_reads_its_log_as_the_session(monkeypatch):
    """The MCP servers a kimi turn could not reach are read off its own log, into an event."""
    import datetime
    import time
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    log = f'{now} ERROR mcp server unavailable  server=others_server transport=http status=failed reason="{OTHERS}"\n'
    other = _second_sessions(".harness/home/.kimi-code/logs/kimi-code.log", log.encode())
    ws = _a_session(monkeypatch)
    _plant(ws, ".harness/home/.kimi-code/logs/kimi-code.log", other)
    down = server._kimi_mcp_unavailable({"cwd": str(ws), "started": time.time() - 30})
    seen = json.dumps(down)
    assert OTHERS not in seen and "others_server" not in seen


def test_whether_a_conversation_is_there_is_asked_as_the_session(monkeypatch):
    """A continued turn asks the CLI's own store whether the conversation is in it, and says so when it is not."""
    other = _second_sessions(".harness/opensquilla/sessions.sqlite", b"SQLite format 3\x00 hsessothertoken ")
    ws = _a_session(monkeypatch)
    _plant(ws, ".harness/opensquilla/sessions.sqlite", other)
    assert server._resume_lost("opensquilla", [], "hsessothertoken", str(ws)) == "hsessothertoken"


# ── the prompt is handed over by file or stdin, never on the command line ─────────────────────
# A process's command line is what `ps` lists. Each turn below is started for real, as the session, with a
# stand-in under the CLI's own name that records what it was handed and then waits. Meanwhile, as another uid:
# its command line holds none of the prompt's words, and the prompt file can't be opened (EACCES while it is
# there, ENOENT once it is gone). The stand-in has the words all the same.
PROMPT_MARK = "the task's own words 7f3a91c2"
_STAND_IN = r"""#!{python}
import json, os, sys, time
report = {{"argv": sys.argv, "stdin": "", "files": {{}}}}
try:
    if not os.isatty(0):
        report["stdin"] = sys.stdin.read()
except Exception as e:
    report["stdin_error"] = repr(e)
for a in sys.argv[1:]:
    for cand in (a, a.split("=", 1)[-1]):
        if "/.hr-prompt/prompt-" in cand and os.path.isfile(cand):
            report["files"][cand] = open(cand).read()
if report["stdin"] or report["files"]:
    # a helper of its own, as a CLI starts its tools and workers: every process of the session is read below
    import subprocess
    report["helper"] = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)", "stand-in-helper"],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL).pid
out = os.path.join(os.getcwd(), ".stand-in-%d.json" % os.getpid())
with open(out + ".part", "w") as fh:
    json.dump(report, fh)
os.rename(out + ".part", out)
if report["stdin"] or report["files"]:
    time.sleep(6)          # a turn: alive while its command lines are read
"""
# Every process the session's uid has, as another uid reads them: its pid and whether its command line holds any
# of the words given.
_SESSION_PROCESSES = r"""
import json, os, sys
uid, words = int(sys.argv[1]), sys.argv[2:]
out = []
for d in os.listdir("/proc"):
    if not d.isdigit():
        continue
    try:
        if os.stat("/proc/" + d).st_uid != uid:
            continue
        with open("/proc/%s/cmdline" % d, "rb") as fh:
            raw = fh.read()
    except OSError:
        continue
    out.append([int(d), raw.split(b"\0")[0].decode(errors="replace"), [w for w in words if w.encode() in raw]])
print(json.dumps(out))
"""
_ON_PATH = ["claude", "codex", "pi", "omp", "qwen", "gemini", "cline", "opencode", "mimo", "kilo", "mcode", "goose",
            "grok", "node"]
_PROMPT_BASES = {  # base: (provider, auth)
    "claude": ("anthropic", {"api_key": "k-0123456789abcdef"}),
    "codex": ("openai", _KEYED), "pi": ("openai-api", _KEYED), "omp": ("openai-api", _KEYED),
    "qwen": ("openai-api", _KEYED), "gemini": ("google", {"api_key": "k-0123456789abcdef"}),
    "cline": ("openai-api", _KEYED), "opencode": ("openai-api", _KEYED), "mimo": ("openai-api", _KEYED),
    "kilo": ("openai-api", _KEYED), "minimax": ("openai-api", _KEYED), "goose": ("openai-api", _KEYED),
    "grok": ("openai-api", _KEYED), "vibe": ("openai-api", _KEYED), "docker-agent": ("openai-api", _KEYED),
    "opensquilla": ("openai-api", _KEYED), "hermes": ("openai-api", _KEYED),
    # the prompt is set in the CLI's own process: kimi's stand-in is a Node script (the preload acts in node), and
    # jcode's a native binary the loader library acts in (both below)
    "kimi": ("openai-api", _KEYED), "jcode": ("openai-api", _KEYED),
}
# kimi: a Node program, as Kimi Code is, so NODE_OPTIONS loads prompt_preload.cjs into it. It records the argv it
# holds in-process (where the preload put the prompt), starts a helper and waits.
_NODE_STAND_IN = r"""#!{node}
const fs = require('node:fs');
const {{ spawn }} = require('node:child_process');
const helper = spawn('/bin/sleep', ['8'], {{ stdio: 'ignore' }});
const out = `${{process.cwd()}}/.stand-in-${{process.pid}}.json`;
fs.writeFileSync(out + '.part', JSON.stringify({{ argv: process.argv, stdin: '', files: {{}}, in_process: process.argv.slice(2),
                                                 helper: helper.pid }}));
fs.renameSync(out + '.part', out);
setTimeout(() => process.exit(0), 6000);
"""
# jcode: a native binary, as jcode's release is (the `.bin` beside its launcher), so the loader runs
# prompt_argv.so in it. The same record.
_NATIVE_STAND_IN = r"""
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
static void quoted(FILE *f, const char *s) {
    fputc('"', f);
    for (; *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') fprintf(f, "\\%c", c);
        else if (c < 0x20) fprintf(f, "\\u%04x", c);
        else fputc(c, f);
    }
    fputc('"', f);
}
int main(int argc, char **argv) {
    pid_t helper = fork();
    if (helper == 0) { execl("/bin/sleep", "sleep", "8", (char *)NULL); _exit(127); }
    char out[256], part[300];
    snprintf(out, sizeof out, ".stand-in-%d.json", (int)getpid());
    snprintf(part, sizeof part, "%s.part", out);
    FILE *f = fopen(part, "w");
    if (!f) return 1;
    fprintf(f, "{\"stdin\": \"\", \"files\": {}, \"helper\": %d, \"in_process\": [", (int)helper);
    for (int i = 1; i < argc; i++) { quoted(f, argv[i]); if (i + 1 < argc) fputc(',', f); }
    fputs("]}", f);
    fclose(f);
    rename(part, out);
    sleep(6);
    return 0;
}
"""


def _opened_as(uid: int, path: str) -> str:
    """What opening `path` for reading gives `uid`: "opened", or the errno's name."""
    out = subprocess.run([sys.executable, "-c", "import errno, sys\n"
                          "try:\n    open(sys.argv[1], 'rb').close()\n    print('opened')\n"
                          "except OSError as e:\n    print(errno.errorcode.get(e.errno, str(e.errno)))", path],
                         user=uid, group=uid, capture_output=True, text=True, timeout=30)
    return out.stdout.strip() or out.stderr.strip()[-200:]


def test_while_the_prompt_file_is_there_another_uid_cant_open_it(monkeypatch):
    """Even with every folder above it passable: the file is the session's, 0600, in a 0700 folder of its own."""
    root = tempfile.mkdtemp(prefix="hrroot-")
    os.chmod(root, 0o755)
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    ws = pathlib.Path(root, "hsesspromptfile")
    (ws / "tmp").mkdir(parents=True)
    for d in (ws, ws / "tmp"):
        os.chown(d, UID, UID)
        os.chmod(d, 0o755)
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        path = server._prompt_handover(str(ws), PROMPT_MARK)
    finally:
        server._TURN_PROMPT.reset(tok)
    try:
        st, folder = os.stat(path), os.stat(os.path.dirname(path))
        assert (st.st_uid, stat.S_IMODE(st.st_mode)) == (UID, 0o600)
        assert (folder.st_uid, stat.S_IMODE(folder.st_mode)) == (UID, 0o700)
        assert _opened_as(UID, path) == "opened"           # the session itself, as its CLI would
        assert _opened_as(UID2, path) == "EACCES"
    finally:
        server._prompt_discard(held)
    assert not os.path.exists(path)


def _stand_ins(monkeypatch) -> pathlib.Path:
    """A folder of stand-ins, one per CLI name, first on PATH; and the absolute ones pointed at it."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="hrstandin-"))
    os.chmod(d, 0o755)
    node, cc = shutil.which("node"), shutil.which("cc") or shutil.which("gcc")
    text = _STAND_IN.format(python=sys.executable)
    for name in _ON_PATH + ["vibe", "docker-agent", "python-opensquilla", "python-hermes"]:
        (d / name).write_text(text)
        os.chmod(d / name, 0o755)
    if node:
        (d / "kimi").write_text(_NODE_STAND_IN.format(node=node))
        os.chmod(d / "kimi", 0o755)
    if cc:
        # jcode's pair: a launcher, and the binary beside it that the runner starts directly (_jcode_exe); and the
        # library that hands the binary its prompt, built from the runner's own source as the image builds it
        src = d / "jcode-stand-in.c"
        src.write_text(_NATIVE_STAND_IN)
        subprocess.run([cc, "-O2", "-o", str(d / "jcode.bin"), str(src)], check=True, capture_output=True)
        (d / "jcode").write_text('#!/bin/sh\nexec "$0.bin" "$@"\n')
        so = d / "prompt_argv.so"
        subprocess.run([cc, "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(so),
                        str(pathlib.Path(server.__file__).with_name("prompt_argv.c"))], check=True, capture_output=True)
        for f in (d / "jcode", d / "jcode.bin", so):
            os.chmod(f, 0o755)
        monkeypatch.setattr(server, "PROMPT_ARGV_SO", str(so), raising=False)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(server, "VIBE_BIN", str(d / "vibe"))
    monkeypatch.setattr(server, "DOCKER_AGENT_BIN", str(d / "docker-agent"))
    monkeypatch.setattr(server, "OPENSQUILLA_PYTHON", str(d / "python-opensquilla"))
    monkeypatch.setattr(server, "HERMES_PYTHON", str(d / "python-hermes"))
    return d


@pytest.mark.parametrize("continued", [False, True], ids=["first-turn", "continued-turn"])
@pytest.mark.parametrize("base", sorted(_PROMPT_BASES))
def test_a_turns_command_line_holds_none_of_its_prompt(base, continued, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    root = tempfile.mkdtemp(prefix="hrroot-")
    os.chmod(root, 0o751)
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    monkeypatch.setattr(server, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(server, "_ws", lambda identifier="": os.path.join(root, identifier or "s1"))
    _stand_ins(monkeypatch)
    if base == "kimi" and not shutil.which("node"):
        pytest.fail("kimi's stand-in is a Node program, and there is no node here")
    if base == "jcode" and not (shutil.which("cc") or shutil.which("gcc")):
        pytest.fail("jcode's stand-in and its library are built with a C compiler, and there is none here")
    provider, auth = _PROMPT_BASES[base]
    ident = f"hsessprompt{base.replace('-', '')}{int(continued)}"
    ws = pathlib.Path(root, ident)
    ws.mkdir()
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    body = {"backend": base, "provider": provider, "model": server.BACKENDS[base]["default_model"],
            "prompt": PROMPT_MARK, "auth": auth, "agent_doc": "first instructions"}
    if continued:   # instructions edited since the last turn: where a note joins the prompt, it goes the same way
        body.update(resume_session_id="hsessresumed", agent_doc="edited instructions")
    made: list[str] = []
    real = server._prompt_handover
    monkeypatch.setattr(server, "_prompt_handover", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    client = TestClient(server.app, raise_server_exceptions=False)
    r = client.post("/turn", params={"identifier": ident}, json=body)
    assert r.status_code == 200, r.text[:300]
    tid = r.json()["turn_id"]
    report = None
    for _ in range(400):
        pid = server._turns[tid].get("pid")
        if pid and (ws / f".stand-in-{pid}.json").exists():
            report = ws / f".stand-in-{pid}.json"
            break
        time.sleep(0.05)
    assert report, f"the turn's CLI never started: {server._turns[tid].get('events', [])[-3:]}"
    seen = subprocess.run(["cat", f"/proc/{pid}/cmdline"], user=UID2, group=UID2, capture_output=True, timeout=30)
    cmdline = seen.stdout.replace(b"\0", b" ").decode(errors="replace")
    assert seen.returncode == 0 and cmdline.strip(), seen.stderr     # the read itself worked, as another uid
    assert PROMPT_MARK not in cmdline and "edited instructions" not in cmdline, cmdline
    # ...and every other process the session has while the turn runs: a CLI starts helpers, and one that
    # starts itself again would start with whatever argv it holds in-process.
    walk = subprocess.run([sys.executable, "-c", _SESSION_PROCESSES, str(UID), PROMPT_MARK, "edited instructions"],
                          user=UID2, group=UID2, capture_output=True, text=True, timeout=60)
    procs = json.loads(walk.stdout or "[]")
    helper = json.loads(report.read_text()).get("helper")
    assert pid in [p[0] for p in procs] and helper in [p[0] for p in procs], (pid, helper, procs, walk.stderr)
    assert not [p for p in procs if p[2]], procs
    files = [f for f in made if f]                                  # cline's goes through a pipe: no file
    assert made and all(_opened_as(UID2, f) in ("EACCES", "ENOENT") for f in files), \
        [(f, _opened_as(UID2, f)) for f in files]
    got = json.loads(report.read_text())
    # kimi and jcode hold it in-process, where the preload and the library set it: nowhere a command line shows
    handed = got["stdin"] + "".join(got["files"].values()) + "".join(got.get("in_process") or [])
    assert PROMPT_MARK in handed, got                                  # ...and the CLI still has its prompt
    _settle(client, ident, r)
    assert not list((ws / "tmp").glob(".prompt-*")), "the prompt file outlived the turn"
