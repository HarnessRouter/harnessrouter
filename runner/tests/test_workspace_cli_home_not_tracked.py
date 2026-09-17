"""The CLI home under .harness/home is carried by the checkpoint tar, never by the workspace repo.

The defect these pin (#193, 2026-09-16, opencode 1.18.31): `git add -A` before every checkpoint
committed .harness/home — opencode's snapshot repo and its SQLite session database — into
.git/objects, while opencode's snapshot repo (work tree = the workspace) snapshotted our .git
back. Twenty turns of one small file grew to a 1.4 GB tarball, ~140k files, for ~220 KB of
agent output, and the gateway's buffering local-backing relay took the host to OOM.

The repo has exactly one reader, /produced, and it already excludes `.harness/`, so ignoring
the CLI home changes nothing that reader reports. What must still hold: the checkpoint tar
keeps .harness/home — that is what --resume rides on.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from server import CHECKPOINT_EXCLUDE, _git, _git_ensure, _produced_ack, _produced_list  # noqa: E402


def _ws_with_cli_home():
    d = pathlib.Path(tempfile.mkdtemp())
    _git_ensure(str(d))
    # what a turn leaves behind: a deliverable, and a CLI home with a session db and transcripts
    (d / "plan.json").write_text("{}")
    oc = d / ".harness" / "home" / ".local" / "share" / "opencode"
    (oc / "snapshot" / "global" / "objects").mkdir(parents=True)     # what an old session still carries
    (oc / "snapshot" / "global" / "objects" / "ab").write_bytes(b"\x03" * 512)
    (oc / "opencode.db").write_bytes(b"\x00" * 1024)
    (d / ".harness" / "home" / ".claude" / "projects").mkdir(parents=True)
    (d / ".harness" / "home" / ".claude" / "projects" / "t.jsonl").write_text("{}\n")
    return d


def test_the_cli_home_never_enters_the_workspace_repo():
    d = _ws_with_cli_home()
    _git(str(d), "add", "-A")
    _git(str(d), "commit", "-q", "-m", "checkpoint")
    tracked = _git(str(d), "ls-files").stdout.split()
    assert "plan.json" in tracked
    assert not any(p.startswith(".harness/home/") for p in tracked), tracked
    # and git no longer has to walk it either: a status of the workspace is silent about it
    status = _git(str(d), "status", "--porcelain", "-uall").stdout
    assert ".harness/home" not in status


def test_a_workspace_that_already_tracks_the_cli_home_lets_go_of_it():
    # a session hydrated from before the rule: .harness/home is IN the index, and an ignore
    # rule alone would leave it there — every later `git add -A` would keep committing it
    d = _ws_with_cli_home()
    subprocess.run(["git", "-C", str(d), "add", "-f", "--", "plan.json",
                    ".harness/home/.local/share/opencode/opencode.db",
                    ".harness/home/.claude/projects/t.jsonl"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "old checkpoint"], check=True)
    assert any(p.startswith(".harness/home/") for p in _git(str(d), "ls-files").stdout.split())
    (d / ".harness" / "home" / ".local" / "share" / "opencode" / "opencode.db").write_bytes(b"\x02" * 4096)
    _git_ensure(str(d))                       # what every checkpoint/hydrate/produced call runs first
    _git(str(d), "add", "-A")
    _git(str(d), "commit", "-q", "-m", "checkpoint")
    tracked = _git(str(d), "ls-files").stdout.split()
    assert "plan.json" in tracked
    assert not any(p.startswith(".harness/home/") for p in tracked), tracked
    assert (d / ".harness" / "home" / ".local" / "share" / "opencode" / "opencode.db").exists(), "only the index lets go; the file stays"


def test_produced_reports_the_deliverable_and_not_the_cli_home():
    d = _ws_with_cli_home()
    assert {f["path"] for f in _produced_list(str(d))} == {"plan.json"}
    _produced_ack(str(d))
    # a later turn touches only the CLI home: nothing new is produced
    (d / ".harness" / "home" / ".local" / "share" / "opencode" / "opencode.db").write_bytes(b"\x01" * 2048)
    assert _produced_list(str(d)) == []


def test_the_checkpoint_tar_keeps_the_cli_home_but_drops_the_snapshot_store():
    # the tar is what --resume rides on: transcripts and the session db must still travel;
    # opencode's undo history must not (it is the 699 MB half of #193)
    d = _ws_with_cli_home()
    excl = [f"--exclude={p}" for p in CHECKPOINT_EXCLUDE]
    out = subprocess.run(["tar", "-cf", "-", *excl, "-C", str(d), "."], capture_output=True, check=True)
    names = subprocess.run(["tar", "-tf", "-"], input=out.stdout, capture_output=True, check=True).stdout.decode().split()
    assert "./.harness/home/.local/share/opencode/opencode.db" in names
    assert "./.harness/home/.claude/projects/t.jsonl" in names
    assert not any("/opencode/snapshot" in n for n in names), [n for n in names if "snapshot" in n]


def test_opencode_is_told_not_to_snapshot(tmp_path):
    server._opencode_config(server.Auth(provider="openai", base_url="https://api.openai.com/v1", api_key="k"),
                            "gpt-5.4", str(tmp_path), None, None, pr="openai")
    cfg = json.load(open(tmp_path / ".harness" / "opencode.json"))
    assert cfg["snapshot"] is False


def test_a_workspace_that_already_tracks_the_cli_home_sheds_the_copies_in_its_history():
    # untracking releases the index; it does not release .git/objects. Twenty pre-fix checkpoints
    # of a 136 MB session db are twenty reachable blobs, and the tarball carries them on every
    # later turn of that session (722 MB of the 1.4 GB in #193). The repo's one reader needs only
    # the cursor's tree and HEAD's tree, so the rest is rewritten away — and what /produced
    # answers must be the same before and after.
    d = _ws_with_cli_home()
    db = d / ".harness" / "home" / ".local" / "share" / "opencode" / "opencode.db"
    blobs = []
    for i in range(3):                                # three pre-fix checkpoints, each a new copy
        db.write_bytes(bytes([i + 1]) * 65536)
        blobs.append(_git(str(d), "hash-object", "--", str(db)).stdout.strip())
        subprocess.run(["git", "-C", str(d), "add", "-f", "-A", "--", "plan.json", ".harness/home"], check=True)
        subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", f"checkpoint {i}"], check=True)
    # the cursor exists and sits on that history (set by hand: _produced_ack runs _git_ensure,
    # the very call under test)
    _git(str(d), "update-ref", server._COLLECTED_REF, "HEAD")
    (d / "plan.json").write_text('{"step": 2}')       # produced since the last collection, not yet collected
    (d / "report.md").write_text("done")
    before = {"plan.json", "report.md"}
    for b in blobs:
        assert _git(str(d), "cat-file", "-e", b).returncode == 0

    _git_ensure(str(d))                               # the first call of the session's next turn

    assert {f["path"] for f in _produced_list(str(d))} == before, "the cursor→worktree answer is unchanged"
    assert not any(p.startswith(".harness/home/") for p in _git(str(d), "ls-files").stdout.split())
    assert db.exists() and db.read_bytes()[:1] == b"\x03", "the file itself is untouched"
    for b in blobs:
        assert _git(str(d), "cat-file", "-e", b).returncode != 0, f"blob {b} is still reachable"
    assert _git(str(d), "rev-list", "--count", "HEAD").stdout.strip() == "2"
    # and the session goes on: the next checkpoint commits on top of the rewritten tip
    _git(str(d), "add", "-A")
    _git(str(d), "commit", "-q", "-m", "checkpoint")
    assert _git(str(d), "rev-list", "--count", "HEAD").stdout.strip() == "3"
    assert _git(str(d), "fsck", "--no-progress").returncode == 0


def test_a_workspace_that_never_tracked_the_cli_home_is_not_rewritten():
    d = _ws_with_cli_home()
    _git(str(d), "add", "-A")
    _git(str(d), "commit", "-q", "-m", "checkpoint 0")
    (d / "plan.json").write_text("{1}")
    _git(str(d), "add", "-A")
    _git(str(d), "commit", "-q", "-m", "checkpoint 1")
    head = _git(str(d), "rev-parse", "HEAD").stdout.strip()
    _git_ensure(str(d))
    assert _git(str(d), "rev-parse", "HEAD").stdout.strip() == head
    assert _git(str(d), "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_a_workspace_whose_cli_home_was_untracked_by_an_earlier_turn_still_sheds_the_copies():
    # the index is the wrong signal: a session that untracked the home a turn ago has a clean
    # index and the same reachable copies (seen live on a session that took one turn on the
    # untrack-only build before this landed: 25 MB of .git and a 28 MB tarball, unchanged)
    d = _ws_with_cli_home()
    db = d / ".harness" / "home" / ".local" / "share" / "opencode" / "opencode.db"
    db.write_bytes(b"\x07" * 65536)
    blob = _git(str(d), "hash-object", "--", str(db)).stdout.strip()
    subprocess.run(["git", "-C", str(d), "add", "-f", "-A", "--", "plan.json", ".harness/home"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "pre-fix checkpoint"], check=True)
    subprocess.run(["git", "-C", str(d), "rm", "-r", "-q", "--cached", "--", ".harness/home"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", "checkpoint (untracked, history kept)"], check=True)
    assert not _git(str(d), "ls-files", "--", ".harness/home").stdout.strip()
    assert _git(str(d), "cat-file", "-e", blob).returncode == 0
    _git_ensure(str(d))
    assert _git(str(d), "cat-file", "-e", blob).returncode != 0
    assert _git(str(d), "rev-list", "--count", "HEAD").stdout.strip() == "1"   # no cursor yet: HEAD's tree alone
    head = _git(str(d), "rev-parse", "HEAD").stdout.strip()
    _git_ensure(str(d))                                                       # and it does not run twice
    assert _git(str(d), "rev-parse", "HEAD").stdout.strip() == head
