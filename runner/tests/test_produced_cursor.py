"""The collection cursor: 'checkpointed' must never imply 'collected'.

The defect these pin (seen live, twice, same deck, 2026-08-25): /produced was
uncommitted-vs-HEAD while /checkpoint moved HEAD unconditionally, so any terminal path
that skipped collection (crash, cancel, OOM, sweep-settle) followed by any checkpoint
buried the turn's files — on disk, invisible to collection, forever.
"""
import pathlib
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import _git, _git_ensure, _produced_ack, _produced_list  # noqa: E402


def _ws():
    d = tempfile.mkdtemp()
    _git_ensure(d)
    (pathlib.Path(d) / "base.txt").write_text("base")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "hydrated")
    _produced_ack(d)          # cursor at the hydrated state: nothing produced yet
    return d


def test_untracked_and_committed_changes_are_both_produced():
    d = _ws()
    (pathlib.Path(d) / "deck.pptx").write_text("v1")
    assert {f["path"] for f in _produced_list(d)} == {"deck.pptx"}
    # a checkpoint commits it — the old design lost it here
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", f"checkpoint {int(time.time())}")
    assert {f["path"] for f in _produced_list(d)} == {"deck.pptx"}


def test_files_survive_any_number_of_checkpoints_until_acked():
    d = _ws()
    (pathlib.Path(d) / "deck.pptx").write_text("v1")
    for i in range(3):
        _git(d, "add", "-A")
        _git(d, "commit", "-q", "--allow-empty", "-m", f"checkpoint {i}")
    (pathlib.Path(d) / "deck.pptx").write_text("v2 restyled")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "another checkpoint")
    assert {f["path"] for f in _produced_list(d)} == {"deck.pptx"}


def test_ack_is_what_consumes_the_list():
    d = _ws()
    (pathlib.Path(d) / "deck.pptx").write_text("v1")
    _produced_ack(d)
    assert _produced_list(d) == []
    (pathlib.Path(d) / "notes.md").write_text("later work")
    assert {f["path"] for f in _produced_list(d)} == {"notes.md"}


def test_a_deleted_file_is_not_offered():
    d = _ws()
    (pathlib.Path(d) / "gone.txt").write_text("x")
    _produced_ack(d)
    (pathlib.Path(d) / "gone.txt").unlink()
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "checkpoint")
    assert _produced_list(d) == []
