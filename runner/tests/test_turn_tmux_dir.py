"""A turn's tmux socket directory is removed only when it is exactly what the openhands driver makes.

The runner's turn sweep reads TMUX_TMPDIR from the turn's processes and removes that directory. Those
are the session's processes, so the value is input like any other: the raw value must match the
driver's mkdtemp shape, be a real directory owned by the uid of the process that named it, and be
removed as that uid."""
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402

ROOT = os.geteuid() == 0
ME = os.geteuid()


def _fresh() -> str:
    """A directory exactly as the driver makes it, owned by whoever runs the test."""
    return tempfile.mkdtemp(prefix="oh", dir="/tmp")


def test_the_drivers_own_directory_is_removed():
    d = _fresh()
    (pathlib.Path(d) / "tmux-1").mkdir()
    assert rs._remove_turn_tmux_dir(d, ME) is True
    assert not os.path.exists(d)


@pytest.mark.parametrize("value", [
    "/tmp/oh/../../{victim}",          # .. after the prefix, judged before any normalising
    "/tmp/oh{n}/../../{victim}",
    "/tmp/oh{n}/",                     # anything after the name
    "/tmp/oh{n}/sub",
    "/tmp/ohX{n}",                     # not mkdtemp's letters
    "/tmp/oh",                         # the prefix alone
    "/tmp/../tmp/oh{n}",
    "/var/tmp/oh{n}",
    "",
])
def test_a_value_of_any_other_shape_is_refused(value, tmp_path):
    victim = tmp_path / "victim"; victim.mkdir(); (victim / "f").write_text("x")
    n = uuid.uuid4().hex[:8]
    real = f"/tmp/oh{n}"
    os.mkdir(real)
    (pathlib.Path(real) / "sub").mkdir()
    try:
        v = value.format(n=n, victim=str(victim).lstrip("/"))
        assert rs._remove_turn_tmux_dir(v, ME) is False
        assert (victim / "f").exists() and os.path.isdir(real)
    finally:
        subprocess.run(["rm", "-rf", real])


def test_a_link_is_refused_and_what_it_points_at_survives(tmp_path):
    target = tmp_path / "kept"; target.mkdir(); (target / "f").write_text("x")
    link = f"/tmp/oh{uuid.uuid4().hex[:8]}"
    os.symlink(target, link)
    try:
        assert rs._remove_turn_tmux_dir(link, ME) is False
        assert (target / "f").exists()
    finally:
        os.unlink(link)


@pytest.mark.skipif(not ROOT, reason="needs root to make a directory another uid owns")
@pytest.mark.parametrize("owner", [0, 20002], ids=["root's", "another session's"])
def test_a_directory_the_naming_process_does_not_own_is_refused(owner):
    d = _fresh()
    os.chown(d, owner, owner)
    try:
        assert rs._remove_turn_tmux_dir(d, 20001) is False     # named by a process of session uid 20001
        assert os.path.isdir(d)
    finally:
        subprocess.run(["rm", "-rf", d])


@pytest.mark.skipif(not ROOT, reason="needs root and a second uid")
def test_the_removal_runs_as_the_naming_uid(tmp_path):
    # its own directory, holding a file of root's: removed as the session, root's file stays
    d = _fresh()
    os.chown(d, 20001, 20001)
    (pathlib.Path(d) / "roots").mkdir(mode=0o755)          # root's, inside: the session can't empty it
    (pathlib.Path(d) / "roots" / "f").write_text("x")
    try:
        rs._remove_turn_tmux_dir(d, 20001)
        assert (pathlib.Path(d) / "roots" / "f").exists()
    finally:
        subprocess.run(["rm", "-rf", d])


@pytest.mark.skipif(not ROOT, reason="needs root to read another uid's environ")
def test_the_sweep_removes_only_what_the_rule_allows(tmp_path):
    victim = pathlib.Path(tempfile.mkdtemp(dir="/var/tmp")); (victim / "f").write_text("x")
    os.chmod(victim, 0o700)
    os.makedirs("/tmp/oh", exist_ok=True)
    marker = "turn-tmux-" + uuid.uuid4().hex[:8]
    env = {"PATH": os.environ["PATH"], rs._TURN_MARK: marker, "TMUX_TMPDIR": f"/tmp/oh/../..{victim}"}
    p = subprocess.Popen(["setpriv", "--reuid=20001", "--regid=20001", "--clear-groups", "sleep", "60"], env=env)
    try:
        time.sleep(0.5)
        rs._sweep_turn_processes(marker)
        assert (victim / "f").exists()
    finally:
        p.kill()
        subprocess.run(["rm", "-rf", str(victim)])
