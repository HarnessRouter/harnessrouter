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
from server import _collected_at_turn_start, _without_lo_profiles, _git, _git_ensure, _produced_ack, _produced_list  # noqa: E402


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


def test_each_produced_item_says_when_it_was_written():
    """A response carries at most HARNESS_RESP_MAX_FILES produced files, and the gateway puts the
    newest first by this field (a Mario run's 1,400 frames showed its first 24 without it,
    hosted 2026-09-25). A deletion is never a produced file, so the field is only ever a real time."""
    import os
    d = _ws()
    (pathlib.Path(d) / "old.txt").write_text("old")
    (pathlib.Path(d) / "new.txt").write_text("new")
    os.utime(pathlib.Path(d) / "old.txt", (1_700_000_000, 1_700_000_000))
    by = {f["path"]: f for f in _produced_list(d)}
    assert by["old.txt"]["mtime"] == 1_700_000_000.0
    assert by["new.txt"]["mtime"] > by["old.txt"]["mtime"]
    # the field survives a checkpoint: the file is still on disk, the time is still its own
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "checkpoint")
    assert {f["path"]: f["mtime"] for f in _produced_list(d)}["old.txt"] == 1_700_000_000.0


def test_a_first_turn_that_commits_its_own_work_still_hands_it_back():
    # 0.33.0-rc.7: jcode's gpt-6 models ended a first turn with `git add deck.pptx && git commit`.
    # The cursor was set at that turn's collection, to a HEAD that already held the commit, and
    # /produced listed nothing. Set at the turn's start, the agent's commit is past it.
    d = tempfile.mkdtemp()                       # a brand-new session: no repo, no commit
    _collected_at_turn_start(d)
    (pathlib.Path(d) / "deck.pptx").write_text("deck")
    _git(d, "add", "deck.pptx")
    _git(d, "commit", "-q", "-m", "Create deck")   # what the agent ran
    assert {f["path"] for f in _produced_list(d)} == {"deck.pptx"}


def test_the_turn_start_cursor_leaves_a_later_turns_cursor_where_collection_put_it():
    d = _ws()                                     # a session whose last turn was collected
    (pathlib.Path(d) / "old.txt").write_text("from an earlier turn")
    _produced_ack(d)
    _collected_at_turn_start(d)
    (pathlib.Path(d) / "new.txt").write_text("this turn")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "agent commit")
    assert {f["path"] for f in _produced_list(d)} == {"new.txt"}


def test_a_libreoffice_profile_in_the_workspace_is_not_a_deliverable():
    # gpt-6.1-sol checked its deck with -env:UserInstallation inside the workspace (opensquilla and
    # jcode, 2026-10-12); the profile's files, newer than the deck, filled the 25 a turn hands back.
    d = _ws()
    for rel in ("deck.pptx", "preview/deck.png", "preview/lo-profile/user/registrymodifications.xcu",
                "preview/lo-profile/user/pack/ExtensionInfo.pack", "notes/user/todo.md"):
        f = pathlib.Path(d) / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    assert {f["path"] for f in _produced_list(d)} == {"deck.pptx", "preview/deck.png", "notes/user/todo.md"}
    # a profile at the workspace root, and a folder named user/ that is not a profile, both read right
    assert _without_lo_profiles(["user/registrymodifications.xcu", "user/pack/a", "out.pdf"]) == ["out.pdf"]
    assert _without_lo_profiles(["user/readme.md", "out.pdf"]) == ["user/readme.md", "out.pdf"]


def test_each_produced_item_says_how_big_it_is():
    """The gateway reads a file over its cap from this field and never fetches it (a 49 MB image was
    read whole into the gateway only to be dropped, hosted 2026-10-19)."""
    d = _ws()
    (pathlib.Path(d) / "hero.png").write_bytes(b"x" * 4096)
    (pathlib.Path(d) / "out").mkdir()
    (pathlib.Path(d) / "out" / "a.txt").write_text("abc")
    by = {f["path"]: f for f in _produced_list(d)}
    assert by["hero.png"]["size"] == 4096 and by["out/a.txt"]["size"] == 3


def test_a_non_ascii_name_is_listed_as_the_agent_wrote_it():
    """git renders a non-ASCII path as \\NNN octal escapes in double quotes unless core.quotepath
    is off, and the listing's unquoting does not undo them. An escaped name is a name no file has:
    it cannot be stat'ed (mtime 0, size 0) and the gateway's GET /file 404s on it — whereupon
    _collect_produced `continue`s and acks anyway, stranding the artifact for good. Both readers
    (untracked via status, committed via diff) are checked, since they must never disagree.
    An ASCII name beside it pins that ordinary paths are unchanged."""
    d = _ws()
    accented = "résumé.pptx"
    (pathlib.Path(d) / accented).write_text("x" * 11)
    (pathlib.Path(d) / "plain.txt").write_text("y" * 7)
    # the premise: git really does quote this name under the default config
    raw = _git(d, "status", "--porcelain", "-uall").stdout
    assert '\\303\\251' in raw, f"fixture name is not quoted by this git; the test proves nothing: {raw!r}"

    by = {f["path"]: f for f in _produced_list(d)}          # untracked reader (status)
    assert set(by) == {accented, "plain.txt"}
    assert by[accented]["size"] == 11 and by[accented]["mtime"] > 0
    assert by["plain.txt"]["size"] == 7 and by["plain.txt"]["mtime"] > 0

    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "checkpoint")
    by = {f["path"]: f for f in _produced_list(d)}          # committed reader (diff vs the cursor)
    assert set(by) == {accented, "plain.txt"}
    assert by[accented]["size"] == 11 and by[accented]["mtime"] > 0


def test_a_name_git_would_escape_whatever_the_config_is_listed_as_written():
    """core.quotepath stops only the octal escapes of non-ASCII bytes: git still quotes and escapes a
    path holding a double quote, a backslash, a tab or a newline, so such a name was listed in an
    escaped spelling no file has (and stranded as above). The listings read git's NUL-separated
    output (-z), which is never quoted, for untracked and for committed files, renames included."""
    d = _ws()
    names = ['say "hi".txt', 'back\\slash.txt', 'tab\there.txt', 'two\nlines.txt', 'résumé.pptx']
    for i, n in enumerate(names):
        (pathlib.Path(d) / n).write_text("z" * (i + 1))
    by = {f["path"]: f for f in _produced_list(d)}          # untracked
    assert set(by) == set(names)
    assert all(by[n]["size"] == i + 1 for i, n in enumerate(names))
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "agent's own commit")
    _git(d, "mv", 'say "hi".txt', 'said "hi".txt')
    _git(d, "commit", "-q", "-m", "renamed")
    by = {f["path"]: f for f in _produced_list(d)}          # committed past the cursor (diff), a rename among them
    assert set(by) == (set(names) - {'say "hi".txt'}) | {'said "hi".txt'}
    assert by['said "hi".txt']["size"] == 1 and by['two\nlines.txt']["mtime"] > 0
