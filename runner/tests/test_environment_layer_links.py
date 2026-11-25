"""A built layer is made read-only by changing only what the build itself made.

After a build, the runner makes the version root's and its group's to read: every name in it re-owned and its
mode set, as root, over a tree the build's own code wrote. Every name a build makes is its own identity's, so a
file another identity owns, reached through a second name in the layer, is not the build's: its name is taken
out of the layer and the file keeps its owner, its mode and its bytes. The build's own files under several names
are made read-only like the rest. Root's, on Linux, where the identities exist.
"""
import os
import pathlib
import stat
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import environments as E  # noqa: E402

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux") or os.geteuid() != 0, reason="root's, on Linux")
OTHER = 20998                       # an identity that is neither the build's nor root


def _foreign(owner: int, text: str) -> pathlib.Path:
    """A file of `owner`'s, mode 0600, in a folder of root's."""
    d = tempfile.mkdtemp(prefix="hrforeign-")
    f = pathlib.Path(d, "theirs")
    f.write_text(text)
    os.chown(f, owner, owner)
    os.chmod(f, 0o600)
    return f


def _unchanged(f: pathlib.Path, owner: int, text: str) -> None:
    st = os.stat(f)
    assert (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (owner, owner, 0o600), "the file of another owner changed"
    assert f.read_text() == text


def _layer(builder: int) -> pathlib.Path:
    v = pathlib.Path(tempfile.mkdtemp(prefix="hrlayer-"))
    (v / "bin").mkdir()
    (v / "bin" / "tool").write_bytes(b"#!/bin/sh\n")
    os.chmod(v / "bin" / "tool", 0o755)
    for alias in (v / "bin" / "tool-alias", v / "aaa-alias", v / "zzz-alias"):   # the build's own file, several names
        os.link(v / "bin" / "tool", alias)
    (v / "data.txt").write_text("d")
    for p in (v, v / "bin", v / "bin" / "tool", v / "data.txt"):
        os.lchown(p, builder, builder)
    return v


@pytest.mark.parametrize("owner", [OTHER, 0], ids=["another identity's", "root's"])
def test_a_second_name_for_a_file_the_build_does_not_own_leaves_that_file_alone(owner):
    gid = E.GID_BASE + 4321
    v = _layer(gid)
    theirs = _foreign(owner, "kept as it was")
    (v / "sub").mkdir()
    os.lchown(v / "sub", gid, gid)
    os.link(theirs, v / "sub" / "second")                      # made as root: the test plays every part
    E._read_only(v, gid)
    _unchanged(theirs, owner, "kept as it was")
    assert not os.path.lexists(v / "sub" / "second"), "the name stayed in the layer"
    # the build's own files, one name or two, are root's and the group's to read
    for p, m in ((v / "bin" / "tool", 0o750), (v / "bin" / "tool-alias", 0o750), (v / "aaa-alias", 0o750),
                 (v / "zzz-alias", 0o750), (v / "data.txt", 0o640), (v / "sub", 0o750)):
        st = os.lstat(p)
        assert (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (0, gid, m), p


def test_a_link_in_the_layer_is_re_owned_as_itself_and_never_followed():
    gid = E.GID_BASE + 4322
    v = _layer(gid)
    theirs = _foreign(OTHER, "behind a link")
    os.symlink(theirs, v / "points-out")
    os.symlink(theirs.parent, v / "dir-out")
    E._read_only(v, gid)
    _unchanged(theirs, OTHER, "behind a link")
    assert os.stat(theirs.parent).st_uid == 0 and stat.S_IMODE(os.stat(theirs.parent).st_mode) == 0o700
    assert os.lstat(v / "points-out").st_uid == 0 and os.lstat(v / "points-out").st_gid == gid


def test_a_version_from_before_environments_had_an_identity_keeps_roots_own_files(monkeypatch):
    """The start-up migration re-owns versions built as root; their files under two names are root's and stay."""
    store = tempfile.mkdtemp(prefix="hrenvstore-")
    monkeypatch.setattr(E, "ENV_ROOT", store)
    v = E.version_dir("henv_legacy", 1)
    v.mkdir(parents=True)
    (v / "tool").write_bytes(b"#!/bin/sh\n")
    os.chmod(v / "tool", 0o755)
    os.link(v / "tool", v / "tool-alias")
    theirs = _foreign(OTHER, "a legacy layer's second name")
    os.link(theirs, v / "second")
    assert E.secure_store() >= 1
    gid = E.env_gid("henv_legacy")
    assert gid is not None
    _unchanged(theirs, OTHER, "a legacy layer's second name")
    assert not os.path.lexists(v / "second")
    for p in (v / "tool", v / "tool-alias"):
        st = os.lstat(p)
        assert (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (0, gid, 0o750)


def test_a_build_ends_with_the_file_of_another_owner_untouched(monkeypatch):
    """Through the whole build: whatever stands in the layer when its code has finished, the file of another
    owner it names keeps its owner and mode, and the build still ends ready."""
    store = tempfile.mkdtemp(prefix="hrenvstore-")
    os.chmod(store, 0o755)
    monkeypatch.setattr(E, "ENV_ROOT", store)
    src = E.source_dir("henv_linked")
    src.mkdir(parents=True)
    (src / "setup.sh").write_text("echo built > built.txt\n")
    theirs = _foreign(OTHER, "outside the build")
    ended = E._end_build_processes

    def end_then_name(gid):                       # once the build's code is done, a second name stands in it
        ended(gid)
        os.link(theirs, E.version_dir("henv_linked", 1) / "second")
    monkeypatch.setattr(E, "_end_build_processes", end_then_name)
    E._build("henv_linked", 1, "henv-linked", True, {})
    rec = E.build_record("henv_linked", 1)
    assert rec and rec["status"] == "ready", rec
    _unchanged(theirs, OTHER, "outside the build")
    assert (E.version_dir("henv_linked", 1) / "built.txt").read_text().strip() == "built"
