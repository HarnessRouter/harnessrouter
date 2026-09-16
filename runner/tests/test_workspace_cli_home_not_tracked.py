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
