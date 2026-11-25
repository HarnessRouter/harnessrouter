"""What reaches git and tar's command lines from a session: the session's path, always as -C's own value, and
object ids read back from the session's repo, used only when they are object ids. The repo is the agent's, so
nothing read from it may arrive in a position where it could be taken as an option (git's --upload-pack=,
tar's --to-command=)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

OID = "0123456789abcdef0123456789abcdef01234567"
HOSTILE = ["--upload-pack=touch /tmp/pwned", "-n", "--exec=x", f"{OID}\n--x", "", "HEAD"]


def _fake_git(monkeypatch, out_for):
    calls: list[tuple] = []

    def fake(ws, *args, check=False, env=None):
        calls.append(args)
        rc, out = out_for(args)
        return subprocess.CompletedProcess(["git", *args], rc, out, "")
    monkeypatch.setattr(server, "_git", fake)
    monkeypatch.setattr(server, "_git_ensure", lambda ws: None)
    return calls


@pytest.mark.parametrize("bad", HOSTILE)
def test_an_id_read_back_from_the_repo_is_used_only_when_it_is_one(monkeypatch, tmp_path, bad):
    def out_for(args):
        if args[:3] == ("rev-parse", "-q", "--verify") and args[3] == server._COLLECTED_REF:
            return 1, ""                                    # no cursor yet: _collected_init sets it
        if args[0] in ("rev-parse", "write-tree", "commit-tree"):
            return 0, bad + "\n"
        return 0, ""
    calls = _fake_git(monkeypatch, out_for)
    server._collected_init(str(tmp_path))
    assert server._produced_ack(str(tmp_path)) == ""
    used = [a for a in calls if a[0] in ("update-ref", "commit-tree")]
    assert used == [], f"a value read from the repo reached git as an argument: {used}"


def test_a_real_object_id_still_moves_the_cursor(monkeypatch, tmp_path):
    def out_for(args):
        if args[:3] == ("rev-parse", "-q", "--verify") and args[3] == server._COLLECTED_REF:
            return 1, ""
        if args[0] == "rev-parse":
            return 0, OID + "\n"
        return 0, ""
    calls = _fake_git(monkeypatch, out_for)
    server._collected_init(str(tmp_path))
    assert server._produced_ack(str(tmp_path)) == OID
    assert [a for a in calls if a[0] == "update-ref"] == [("update-ref", server._COLLECTED_REF, OID)] * 2


def test_the_history_shed_never_commits_or_moves_a_ref_on_a_hostile_id(monkeypatch, tmp_path):
    def out_for(args):
        if args[0] == "rev-parse":
            return 0, OID + "\n"                            # HEAD and the cursor exist
        if args[0] in ("write-tree", "commit-tree"):
            return 0, "--upload-pack=touch /tmp/pwned\n"
        return 0, ""
    calls = _fake_git(monkeypatch, out_for)
    monkeypatch.setattr(server, "_rm_tree_as_session", lambda *a, **k: None, raising=False)
    try:
        server._git_shed_cli_home_history(str(tmp_path))
    except Exception:
        pass                                                # the cleanup after it is not under test here
    assert not [a for a in calls if a[0] in ("commit-tree", "update-ref")]


@pytest.mark.parametrize("ident", ["-rf", "--to-command=sh", "-C", "..-x", "a b"])
def test_the_session_path_is_never_an_option(monkeypatch, tmp_path, ident):
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    ws = server._ws(ident)
    assert os.path.isabs(ws) and not ws.startswith("-")
    # and git and tar take it as -C's own value, the next element, whatever it reads like
    seen = {}

    def run(argv, *a, **k):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(server.subprocess, "run", run)
    monkeypatch.setattr(server, "_session_uid", lambda w: None)
    server._git(ws, "status")
    argv = seen["argv"]
    assert argv[0] == "git" and argv[argv.index("-C") + 1] == ws


def test_tars_excludes_are_a_fixed_list_of_option_values():
    """Each is passed as one --exclude=<pattern> word, so none can be an option of its own."""
    assert server.CHECKPOINT_EXCLUDE and all(isinstance(p, str) and p and not p.startswith("-")
                                             for p in server.CHECKPOINT_EXCLUDE)
