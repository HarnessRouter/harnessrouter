"""A build's root steps go nowhere its own code points them.

Pip's hooks, npm's scripts and setup.sh run the project's code as the environment's identity, inside a tree the runner then
touches as root. A link planted there redirected root's write of the build record and of package.json, a link at apt/ would
have had root unpack packages anywhere, and root read the record back through a link and returned what it found. These run as
root on Linux, where the identity exists; elsewhere there is nothing to test.
"""
import json
import os
import pathlib
import sys
import tempfile
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import environments as e  # noqa: E402

root_only = pytest.mark.skipif(not sys.platform.startswith("linux") or os.geteuid() != 0, reason="root's, on Linux")


def _victim():
    d = tempfile.mkdtemp(prefix="hrvictim-")
    f = pathlib.Path(d) / "victim"
    f.write_text("root's own")
    os.chmod(f, 0o600)
    return f


def test_the_record_is_not_written_through_a_planted_link(tmp_path):
    victim = _victim()
    (tmp_path / ".hr-build.json").symlink_to(victim)
    (tmp_path / ".hr-build.json.tmp").symlink_to(victim)
    e._write_record(tmp_path, {"status": "building", "log": []})
    assert victim.read_text() == "root's own"
    assert not (tmp_path / ".hr-build.json").is_symlink()
    assert json.loads((tmp_path / ".hr-build.json").read_text())["status"] == "building"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp") and not p.is_symlink()] == []


def test_a_new_file_is_never_written_through_a_link_even_a_dangling_one(tmp_path):
    gone = tmp_path.parent / f"never-made-{os.getpid()}"
    link = tmp_path / "package.json"
    link.symlink_to(gone)
    assert not link.is_file(), "it reads as absent: why the caller's check can't catch it"
    with pytest.raises(OSError):
        e._new_in_layer(link, "{}")
    assert not gone.exists()


def test_the_record_is_not_read_through_a_link(tmp_path, monkeypatch):
    secret = tmp_path / "other.json"
    secret.write_text(json.dumps({"password_hash": "not-yours"}))
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / ".hr-build.json").symlink_to(secret)
    monkeypatch.setattr(e, "version_dir", lambda env_id, n: tmp_path / "v")
    assert e.build_record("env", 1) is None


def test_a_fifo_as_the_record_does_not_hang_the_reader(tmp_path, monkeypatch):
    (tmp_path / "v").mkdir()
    os.mkfifo(tmp_path / "v" / ".hr-build.json")
    monkeypatch.setattr(e, "version_dir", lambda env_id, n: tmp_path / "v")
    assert e.build_record("env", 1) is None


def _marker() -> pathlib.Path:
    """Where the build's own script can write a pid: pytest's tmp_path is under a directory only root can enter."""
    d = tempfile.mkdtemp(prefix="hrmarker-")
    os.chmod(d, 0o777)
    m = pathlib.Path(d) / "pid"
    m.write_text("")
    os.chmod(m, 0o666)
    return m


def _source(monkeypatch, tmp_path, files: dict, mode=0o755):
    monkeypatch.setattr(e, "ENV_ROOT", str(tmp_path / "envs"), raising=False)
    src = e.source_dir("envtest")
    src.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (src / name).write_text(text)
    return src


@root_only
def test_apt_runs_before_the_project_can_touch_the_tree(monkeypatch, tmp_path):
    os.chmod(tmp_path, 0o755)
    _source(monkeypatch, tmp_path, {"setup.sh": "echo ran-setup > ran-setup\n"})
    seen = {}

    def apt(log, dst, names, env, scratch, deadline, flush):
        seen.update(owner=dst.stat().st_uid, setup_ran=(dst / "ran-setup").exists())
    monkeypatch.setattr(e, "_apt_into_layer", apt)
    e._build("envtest", 1, "envtest", True, {"apt": ["zlib1g"]})
    rec = e.build_record("envtest", 1)
    assert rec["status"] == "ready", rec
    assert seen == {"owner": 0, "setup_ran": False}, "apt ran after the project's code, or in a tree it owned"
    assert (e.version_dir("envtest", 1) / "ran-setup").exists()


@root_only
def test_a_build_that_plants_links_and_leaves_a_process_gets_neither(monkeypatch, tmp_path):
    os.chmod(tmp_path, 0o755)
    victim = _victim()
    os.chmod(victim.parent, 0o755); os.chmod(victim, 0o644)
    marker = _marker()
    _source(monkeypatch, tmp_path, {"setup.sh": f"""
ln -sf {victim} .hr-build.json
ln -sf {victim} .hr-build.json.tmp
sleep 600 >/dev/null 2>&1 &
echo $! > {marker}
"""})
    e._build("envtest", 1, "envtest", True, {})
    rec = e.build_record("envtest", 1)
    assert rec is not None and rec["status"] == "ready", rec
    assert victim.read_text() == "root's own"
    assert victim.stat().st_uid == 0 and victim.stat().st_mode & 0o777 == 0o644, "root walked through the link"
    pid = int(marker.read_text().strip())
    time.sleep(0.2)
    alive = pathlib.Path(f"/proc/{pid}").exists() and pathlib.Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    assert not alive, "a process of the build outlived it"


@root_only
def test_a_failed_build_leaves_no_process_either(monkeypatch, tmp_path):
    os.chmod(tmp_path, 0o755)
    marker = _marker()
    _source(monkeypatch, tmp_path, {"setup.sh": f"sleep 600 >/dev/null 2>&1 &\necho $! > {marker}\nexit 3\n"})
    e._build("envtest", 1, "envtest", True, {})
    assert e.build_record("envtest", 1)["status"] == "failed"
    pid = int(marker.read_text().strip())
    time.sleep(0.2)
    assert not (pathlib.Path(f"/proc/{pid}").exists() and pathlib.Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z")


@root_only
def test_ending_a_builds_processes_touches_only_that_identity():
    import subprocess
    other = subprocess.Popen(["sleep", "30"], user=20901, group=20901, extra_groups=[])
    mine = subprocess.Popen(["sleep", "30"], user=20902, group=20902, extra_groups=[])
    root_child = subprocess.Popen(["sleep", "30"])
    try:
        e._end_build_processes(20902)
        time.sleep(0.2)
        assert mine.poll() is not None, "the identity's own process survived"
        assert other.poll() is None and root_child.poll() is None, "it reached past its own identity"
    finally:
        for p in (other, mine, root_child):
            p.kill(); p.wait()
