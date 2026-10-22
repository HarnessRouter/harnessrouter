"""Environments (runner/environments.py): the source a person edits, an archive import that keeps
the tree and drops what must not land, a build that snapshots the source and installs what the
manifests declare, versions with an atomic active pointer, the mount link sessions are told, and
the variables and instructions a turn gets."""
import io
import json
import os
import pathlib
import stat
import sys
import tarfile
import threading
import time
import zipfile

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import environments as E  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "ENV_ROOT", str(tmp_path / "environments"))
    monkeypatch.setattr(E, "ENV_MOUNT", str(tmp_path / "env"))
    return tmp_path


def test_source_files_round_trip_and_the_tree_counts_them(store):
    E.write_file("henv_a", "scripts/render.py", b"print('hi')\n")
    E.write_file("henv_a", "config.yaml", b"a: 1\n")
    E.make_dir("henv_a", "assets/brand")
    data, ctype = E.read_file("henv_a", "scripts/render.py")
    assert data == b"print('hi')\n" and ctype.startswith("text/")
    t = E.tree("henv_a")
    assert {e["path"] for e in t if e["dir"]} == {"assets", "assets/brand", "scripts"}
    assert {e["path"] for e in t if not e["dir"]} == {"scripts/render.py", "config.yaml"}
    assert E.source_stat("henv_a") == {"count": 2, "bytes": 17}
    E.delete_path("henv_a", "scripts")
    assert {e["path"] for e in E.tree("henv_a")} == {"assets", "assets/brand", "config.yaml"}


def test_a_path_out_of_the_source_is_refused(store):
    E.write_file("henv_a", "ok.txt", b"x")
    for bad in ("../x", "/etc/passwd", "a/../../x", ".", ""):
        with pytest.raises(HTTPException) as e:
            E.write_file("henv_a", bad, b"x")
        assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        E.read_file("henv_a", "../ok.txt")
    with pytest.raises(HTTPException):
        E._check_id("../henv")


def test_import_strips_one_wrapping_directory_and_drops_escapes_and_links(store, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("proj-main/run.py", "print(1)\n")
        zf.writestr("proj-main/scripts/lib/util.py", "x = 1\n")
        zf.writestr("proj-main/../evil.txt", "no")
        info = zipfile.ZipInfo("proj-main/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    p = tmp_path / "up.zip"
    p.write_bytes(buf.getvalue())
    out = E.import_archive("henv_z", str(p))
    assert out["written"] == 2 and out["skipped"] == 2
    assert {e["path"] for e in E.tree("henv_z") if not e["dir"]} == {"run.py", "scripts/lib/util.py"}
    assert not (E.source_dir("henv_z") / "link").exists()
    # a tarball with no wrapper keeps its top level; replace= wipes what was there
    t = tmp_path / "up.tgz"
    with tarfile.open(t, "w:gz") as tf:
        for name, text in (("a.txt", "A"), ("d/b.txt", "B")):
            ti = tarfile.TarInfo(name); data = text.encode(); ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        ti = tarfile.TarInfo("d/ln"); ti.type = tarfile.SYMTYPE; ti.linkname = "../../x"
        tf.addfile(ti)
    out = E.import_archive("henv_z", str(t), replace=True)
    assert out["written"] == 2 and out["skipped"] == 1
    assert {e["path"] for e in E.tree("henv_z") if not e["dir"]} == {"a.txt", "d/b.txt"}


@pytest.mark.parametrize("archive_format", ["zip", "tar"])
@pytest.mark.parametrize("wrapper, directory_entry", [("", False), ("project/", False), ("project/", True)])
def test_import_keeps_a_single_file_with_or_without_a_wrapping_directory(
    store, tmp_path, archive_format, wrapper, directory_entry,
):
    data = b"a single file\n"
    p = tmp_path / ("single." + archive_format)
    if archive_format == "zip":
        with zipfile.ZipFile(p, "w") as zf:
            if directory_entry:
                zf.writestr(wrapper, b"")
            zf.writestr(wrapper + "new.txt", data)
    else:
        with tarfile.open(p, "w") as tf:
            if directory_entry:
                directory = tarfile.TarInfo(wrapper)
                directory.type = tarfile.DIRTYPE
                tf.addfile(directory)
            member = tarfile.TarInfo(wrapper + "new.txt")
            member.size = len(data)
            tf.addfile(member, io.BytesIO(data))

    out = E.import_archive("henv_single", str(p))
    assert out["written"] == 1 and out["skipped"] == 0
    assert E.source_stat("henv_single") == {"count": 1, "bytes": len(data)}
    assert E.read_file("henv_single", "new.txt")[0] == data
    assert {e["path"] for e in E.tree("henv_single")} == {"new.txt"}


def _wait(env_id, n, timeout=240):
    for _ in range(timeout * 4):
        rec = E.build_record(env_id, n)
        if rec and rec["status"] in ("ready", "failed"):
            return rec
        time.sleep(0.25)
    raise AssertionError("build did not finish")


def test_a_build_snapshots_the_source_installs_and_becomes_the_active_read_only_layer(store):
    E.write_file("henv_b", "scripts/render.py", b"import sys\nprint(sys.prefix)\n")
    E.write_file("henv_b", "requirements.txt", b"")               # a venv with nothing in it: no network needed
    E.write_file("henv_b", "node_modules/left/over.js", b"//")     # never copied: the build installs its own
    E.write_file("henv_b", "run.sh", b"#!/bin/sh\necho run\n")
    os.chmod(E.source_dir("henv_b") / "run.sh", 0o755)
    E.start_build("henv_b", 1, "content-studio")
    rec = _wait("henv_b", 1)
    assert rec["status"] == "ready", rec["log"]
    v1 = E.version_dir("henv_b", 1)
    assert (v1 / "scripts" / "render.py").is_file() and not (v1 / "node_modules").exists()
    assert (v1 / ".venv" / "bin" / "python3").exists() or (v1 / ".venv" / "bin" / "python").exists()
    assert any(p["manager"] == "pip" and p["name"] == "pip" for p in rec["packages"])
    assert rec["files"] > 3 and rec["bytes"] > 0
    # the layer is its group's to read and nobody else's; the source is the runner's alone
    assert oct(os.stat(v1 / "scripts" / "render.py").st_mode & 0o777) == "0o640"
    assert oct(os.stat(v1 / "run.sh").st_mode & 0o777) == "0o750"
    assert oct(os.stat(v1).st_mode & 0o777) == "0o750"
    assert oct(os.stat(E.source_dir("henv_b")).st_mode & 0o777) == "0o700"
    assert E.active_version("henv_b") == 1
    link = E.mount_path("content-studio")
    assert os.path.islink(link) and pathlib.Path(link).resolve() == v1.resolve()
    assert E.versions("henv_b")[0]["version"] == 1 and E.versions("henv_b")[0]["status"] == "ready"
    # the source changes; sessions keep seeing the build until the next one
    E.write_file("henv_b", "scripts/render.py", b"print('v2')\n")
    assert (v1 / "scripts" / "render.py").read_bytes() == b"import sys\nprint(sys.prefix)\n"
    E.start_build("henv_b", 2, "content-studio")
    assert _wait("henv_b", 2)["status"] == "ready"
    assert E.active_version("henv_b") == 2 and pathlib.Path(link).resolve() == E.version_dir("henv_b", 2).resolve()
    # rollback is the pointer, nothing is rebuilt
    E.activate_version("henv_b", 1, "content-studio")
    assert E.active_version("henv_b") == 1 and pathlib.Path(link).resolve() == v1.resolve()
    with pytest.raises(HTTPException):
        E.activate_version("henv_b", 9, "content-studio")
    E.delete_environment("henv_b", "content-studio")
    assert not E.env_dir("henv_b").exists() and not os.path.lexists(link)


def test_a_failed_build_records_why_and_never_becomes_active(store):
    E.write_file("henv_f", "setup.sh", b"#!/bin/sh\necho preparing\nexit 3\n")
    E.start_build("henv_f", 1, "broken")
    rec = _wait("henv_f", 1)
    assert rec["status"] == "failed" and "exited 3" in rec["error"] and "preparing" in rec["log"]
    assert E.active_version("henv_f") is None
    with pytest.raises(HTTPException) as e:
        E.resolve({"id": "henv_f", "slug": "broken"})
    assert e.value.status_code == 409


def test_when_the_record_says_ready_the_version_is_already_the_active_one(store, monkeypatch):
    """The record is what a reader waits on. It was written before the version became active, and a
    turn started the moment it read "ready" was refused with "the environment has no built version"
    (issue #401). Asked here at the instant the ready record is written, not after it."""
    seen = []
    real = E._write_record

    def spy(dst, rec):
        if rec.get("status") == "ready":
            seen.append((E.active_version("henv_o"), E.resolve({"id": "henv_o", "slug": "ordered"})["version"]))
        real(dst, rec)
    monkeypatch.setattr(E, "_write_record", spy)
    E.write_file("henv_o", "setup.sh", b"#!/bin/sh\necho preparing\n")
    E.start_build("henv_o", 1, "ordered")
    assert _wait("henv_o", 1)["status"] == "ready"
    assert seen == [(1, 1)]


def test_a_source_write_during_a_build_snapshot_waits_for_the_snapshot(store, monkeypatch):
    """#425: `_build` copied the source in its own thread while `write_file` could still land, so a
    version could hold `a/` from before a write and `z/` from after it — a state the source was
    never in. The snapshot takes the environment's source lock, and this asks the question at the
    moment the copy is standing between two directories."""
    E.write_file("henv_k", "a/one.py", b"old a\n")
    E.write_file("henv_k", "z/two.py", b"old z\n")
    inside_copy, release = threading.Event(), threading.Event()
    real_copytree = E.shutil.copytree

    def slow_copytree(src, dst, **kw):
        real_copytree(pathlib.Path(src) / "a", pathlib.Path(dst) / "a", dirs_exist_ok=True)
        inside_copy.set()                 # the build is mid-copy, past a/, before z/
        release.wait(30)
        real_copytree(pathlib.Path(src) / "z", pathlib.Path(dst) / "z", dirs_exist_ok=True)
    monkeypatch.setattr(E.shutil, "copytree", slow_copytree)

    # the count in the build log is read with the same hold the copy takes, so it describes the
    # tree this build copied rather than whatever the source looked like a moment later
    reads = []
    real_count = E.source_stat

    def spy_count(env):
        out = real_count(env)
        lock = getattr(E, "_source_lock", None)      # absent before the fix: the read is not held
        reads.append((out["count"], bool(lock is not None and lock(env).locked())))
        return out
    monkeypatch.setattr(E, "source_stat", spy_count)

    landed = threading.Event()

    def writer():
        E.write_file("henv_k", "z/three.py", b"new z\n")
        landed.set()
    thread = threading.Thread(target=writer)
    E.start_build("henv_k", 1, "mixed")
    assert inside_copy.wait(30), "the build never reached the copy"
    thread.start()
    assert not landed.wait(0.5), "the write landed while the build was inside the snapshot"
    release.set()
    thread.join(30)
    assert landed.is_set()

    rec = _wait("henv_k", 1)
    assert rec["status"] == "ready", rec["log"]
    v1 = E.version_dir("henv_k", 1)
    assert (v1 / "a" / "one.py").read_bytes() == b"old a\n"
    assert (v1 / "z" / "two.py").read_bytes() == b"old z\n"
    assert not (v1 / "z" / "three.py").exists()               # one whole state, not a mix of two
    assert (2, True) in reads, reads                          # a/one.py + z/two.py, counted under the hold
    # the write is not lost, only ordered: the next build holds it
    E.start_build("henv_k", 2, "mixed")
    assert _wait("henv_k", 2)["status"] == "ready"
    assert (E.version_dir("henv_k", 2) / "z" / "three.py").read_bytes() == b"new z\n"


@pytest.mark.parametrize("change,env_id", [("make_dir", "henv_md"), ("delete_path", "henv_dp"),
                                           ("import_archive", "henv_ia"), ("import_git", "henv_ig")])
def test_the_snapshot_holds_every_change_to_the_source_not_only_a_write(store, monkeypatch, change, env_id):
    """#425 asks for the interleaving to be tested rather than for a lock to exist. `make_dir`,
    `delete_path` and the two imports change the source just as `write_file` does, so each is
    another way a version can hold a state the source was never in."""
    E.write_file(env_id, "a/one.py", b"old a\n")
    E.write_file(env_id, "z/two.py", b"old z\n")
    archive = store / "one.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("from_archive.txt", "in archive\n")
    archive.write_bytes(buf.getvalue())
    if change == "import_git":
        # the clone is the part that must stay OUTSIDE the hold, so it is not what is being asked
        # here: git is answered without a network and the swap-in is what the test watches
        def no_clone(cmd, **kw):
            class R:
                returncode, stdout, stderr = 0, "", ""
            return R()
        monkeypatch.setattr(E.subprocess, "run", no_clone)

    inside_copy, release, landed = threading.Event(), threading.Event(), threading.Event()
    real_copytree = E.shutil.copytree

    def slow_copytree(src, dst, **kw):
        real_copytree(pathlib.Path(src) / "a", pathlib.Path(dst) / "a", dirs_exist_ok=True)
        inside_copy.set()
        release.wait(30)
        real_copytree(pathlib.Path(src) / "z", pathlib.Path(dst) / "z", dirs_exist_ok=True)
    monkeypatch.setattr(E.shutil, "copytree", slow_copytree)

    def worker():
        if change == "make_dir":
            E.make_dir(env_id, "z/deep")
        elif change == "delete_path":
            E.delete_path(env_id, "z/two.py")
        elif change == "import_git":
            E.import_git(env_id, "https://example.invalid/repository.git")
        else:
            E.import_archive(env_id, str(archive), replace=False)
        landed.set()
    thread = threading.Thread(target=worker)
    E.start_build(env_id, 1, "held")
    assert inside_copy.wait(30), "the build never reached the copy"
    thread.start()
    assert not landed.wait(0.5), f"{change} landed while the build was inside the snapshot"
    release.set()
    thread.join(30)
    assert landed.is_set(), f"{change} never finished after the snapshot released"

    paths = {e["path"] for e in E.tree(env_id)}
    if change == "make_dir":
        assert "z/deep" in paths
    elif change == "delete_path":
        assert "z/two.py" not in paths
    elif change == "import_git":
        assert {"a/one.py", "z/two.py"} <= paths        # swapped in, and the source is still there
    else:
        assert "from_archive.txt" in paths
    assert _wait(env_id, 1)["status"] == "ready"


def test_a_build_whose_last_write_fails_leaves_the_active_version_as_it_was(store, monkeypatch):
    E.write_file("henv_l", "setup.sh", b"#!/bin/sh\necho preparing\n")
    E.start_build("henv_l", 1, "last")
    assert _wait("henv_l", 1)["status"] == "ready" and E.active_version("henv_l") == 1
    real = E._write_record
    failed_once = []

    def refuse_ready(dst, rec):
        if rec.get("status") == "ready" and rec.get("version") == 2 and not failed_once:
            failed_once.append(1)
            raise OSError("no space left on device")
        real(dst, rec)
    monkeypatch.setattr(E, "_write_record", refuse_ready)
    E.start_build("henv_l", 2, "last")
    rec = _wait("henv_l", 2)
    assert rec["status"] == "failed" and "no space" in rec["error"]
    assert E.active_version("henv_l") == 1                      # version 1 still serves
    assert E.resolve({"id": "henv_l", "slug": "last"})["version"] == 1
    # and a first build that fails the same way leaves the environment with no version at all
    failed_once.clear()
    monkeypatch.setattr(E, "_write_record", lambda dst, rec: (_ for _ in ()).throw(OSError("no space left on device"))
                        if rec.get("status") == "ready" else real(dst, rec))
    E.write_file("henv_n", "setup.sh", b"#!/bin/sh\necho preparing\n")
    E.start_build("henv_n", 1, "none")
    assert _wait("henv_n", 1)["status"] == "failed" and E.active_version("henv_n") is None


def test_a_build_that_stopped_without_recording_its_end_reads_as_failed(store, monkeypatch):
    """The record is the build's only report. When its last write fails (_build swallows that one)
    or the runner restarts under a build, the record says building with no thread behind it, and
    every read said building for good. The build's own read and the versions, which the gateway
    takes the environment's status from, answer it as failed; a build still running is building."""
    E.write_file("henv_s", "setup.sh", b"#!/bin/sh\necho preparing\nexit 3\n")
    real = E._write_record
    monkeypatch.setattr(E, "_write_record", lambda dst, rec: (_ for _ in ()).throw(OSError("no space left on device"))
                        if rec.get("status") == "failed" else real(dst, rec))
    E.start_build("henv_s", 1, "stopped")
    for _ in range(960):
        with E._builds_lock:
            if "henv_s:1" not in E._builds:
                break
        time.sleep(0.25)
    assert E.build_record("henv_s", 1)["status"] == "building"        # what the disk still says
    rec = E.r_build_status("henv_s", 1)
    assert rec["status"] == "failed" and rec["error"] == "the build stopped before it recorded its end"
    assert rec["stage"] == "" and rec["finished_at"] >= rec["started_at"]
    assert [(v["version"], v["status"]) for v in E.versions("henv_s")] == [(1, "failed")]

    class Alive:
        def is_alive(self):
            return True
    monkeypatch.setitem(E._builds, "henv_s:1", Alive())             # the same record while a build runs
    assert E.r_build_status("henv_s", 1)["status"] == "building"
    assert E.versions("henv_s")[0]["status"] == "building"


def test_the_turn_gets_the_path_the_variables_and_the_instructions(store):
    E.write_file("henv_t", "requirements.txt", b"")
    E.write_file("henv_t", "package.json", json.dumps({"name": "p", "version": "1.0.0", "private": True}).encode())
    E.start_build("henv_t", 1, "studio")
    rec = _wait("henv_t", 1)
    assert rec["status"] == "ready", rec["log"]
    applied = E.resolve({"id": "henv_t", "slug": "studio", "entry": "python3 run.py"})
    link = E.mount_path("studio")
    assert applied == {"id": "henv_t", "slug": "studio", "path": link, "version": 1, "entry": "python3 run.py"}
    env = {"PATH": "/usr/bin", "NODE_PATH": "/tools/node_modules"}
    E.apply_env(env, applied)
    assert env["PROJECT_ROOT"] == link and env["PYTHONPATH"] == link
    assert env["PATH"].startswith(link + "/.venv/bin:") and env["PATH"].endswith(":/usr/bin")
    assert env["VIRTUAL_ENV"] == link + "/.venv"
    if (pathlib.Path(link) / "node_modules").is_dir():   # npm made one even with no dependencies
        assert env["NODE_PATH"].startswith(link + "/node_modules:")
    doc = "\n".join(E.doc_section(applied))
    assert "## Project environment" in doc and link in doc and "READ-ONLY" in doc and "python3 run.py" in doc
    assert E.doc_section(None) == []
    # the mount link survives a restart: remade from the store when it is gone
    os.unlink(link)
    assert E.resolve({"id": "henv_t", "slug": "studio"})["path"] == link and os.path.islink(link)


def test_each_environment_gets_its_own_group_and_its_builds_run_as_it(store, monkeypatch):
    """The group model needs root; what a test process can pin is the allocation, the identity a
    build step gets, the group a turn joins, and that none of it applies off root."""
    E.write_file("henv_g1", "a.txt", b"a")
    assert E.env_gid("henv_g1") is None and E._build_as("henv_g1") == {} and E.secure_store() == 0   # not root: modes only
    owned, made = {}, []
    monkeypatch.setattr(E.os, "geteuid", lambda: 0)
    monkeypatch.setattr(E.os, "chown", lambda p, u, g: owned.__setitem__(str(p), (u, g)))
    monkeypatch.setattr(E.os, "lchown", lambda p, u, g: owned.__setitem__(str(p), (u, g)))
    monkeypatch.setattr(E, "_account", lambda n: made.append(n))
    real_stat = os.stat

    def fake_stat(p, *a, **k):        # the directory's group is the record: replay what chown set
        st = real_stat(p, *a, **k)
        if str(p) in owned:
            class St:
                st_uid, st_gid, st_mode = owned[str(p)][0], owned[str(p)][1], st.st_mode
            return St()
        return st
    monkeypatch.setattr(E.os, "stat", fake_stat)
    E._claim("henv_g1"); E._claim("henv_g2")
    g1, g2 = E.env_gid("henv_g1"), E.env_gid("henv_g2")
    assert g1 and g2 and g1 != g2 and E.GID_BASE <= g1 < E.GID_BASE + E.GID_SPAN and made == [g1, g2]
    assert owned[str(E.env_dir("henv_g1"))] == (0, g1) and oct(real_stat(E.env_dir("henv_g1")).st_mode & 0o777) == "0o750"
    assert E._claim("henv_g1") == E.env_dir("henv_g1") and E.env_gid("henv_g1") == g1      # stable: read back, not reallocated
    assert E._build_as("henv_g1") == {"user": g1, "group": g1, "extra_groups": []}
    # a layer made read-only for the group is chowned root:group, links included
    v = E.version_dir("henv_g1", 1); (v / "bin").mkdir(parents=True); (v / "bin" / "tool").write_bytes(b"#!/bin/sh\n")
    os.chmod(v / "bin" / "tool", 0o755); os.symlink("tool", v / "bin" / "alias")
    E._read_only(v, g1)
    assert owned[str(v)] == (0, g1) and owned[str(v / "bin" / "tool")] == (0, g1) and owned[str(v / "bin" / "alias")] == (0, g1)
    assert oct(real_stat(v / "bin" / "tool").st_mode & 0o777) == "0o750"
    # the turn joins the group of the environment at its mount, and no group for a path outside the range
    assert E.reader_gid(str(v)) == g1 and E.reader_gid(str(store)) is None and E.reader_gid("") is None


def test_the_slug_is_a_path_segment(store):
    assert E.slug_ok("content-studio") and E.slug_ok("a.b_c") and not E.slug_ok("../x") and not E.slug_ok("a/b") and not E.slug_ok("")


def test_declared_specs_are_checked_and_the_runtimes_are_what_the_box_has(store):
    assert E.clean_specs(["pyyaml==6.0.2", "sharp@0.33.5", "@scope/pkg@1.0.0", "ffmpeg", "bad spec!", "", "pyyaml==6.0.2", "../x"]) == \
        ["pyyaml==6.0.2", "sharp@0.33.5", "@scope/pkg@1.0.0", "ffmpeg"]
    rt = E.runtimes()
    assert isinstance(rt["python"], list) and all(v.startswith("3.") for v in rt["python"]) and isinstance(rt["apt"], bool)
    # a declared pip package with no network still records what was asked; the manifests path is unchanged
    E.write_file("henv_d", "run.py", b"print(1)\n")
    E.start_build("henv_d", 1, "declared", spec={"pip": [], "npm": [], "apt": [], "python": rt["python"][-1] if rt["python"] else ""})
    rec = _wait("henv_d", 1)
    assert rec["status"] == "ready" and rec["declared"] == {"pip": [], "npm": [], "apt": []}


def test_a_build_writes_its_record_as_each_step_ends_with_the_stage(store, monkeypatch):
    """The record on disk is what the owner reads while a build runs: written as steps end, with
    the step's name, not only when the build is over."""
    writes: list[tuple[str, int]] = []
    real = E._write_record

    def spy(dst, rec):
        writes.append((str(rec.get("stage")), len(rec.get("log") or [])))
        real(dst, rec)
    monkeypatch.setattr(E, "_write_record", spy)
    E.write_file("henv_s", "requirements.txt", b"")
    E.write_file("henv_s", "setup.sh", b"#!/bin/sh\necho preparing\n")
    E.start_build("henv_s", 1, "staged")
    rec = _wait("henv_s", 1)
    assert rec["status"] == "ready" and rec["stage"] == ""
    stages = [w[0] for w in writes]
    assert stages[0] == "starting" and "copying files" in stages and "python packages" in stages and "setup.sh" in stages and "finishing" in stages
    assert len(writes) >= 8, writes     # the start, each stage, and after each command's line and output
    logs = [w[1] for w in writes]
    assert logs == sorted(logs) and logs[-1] > logs[0]   # the log only grows between writes


def test_a_package_check_asks_the_registry_and_refuses_what_is_not_there(monkeypatch):
    answers = {
        "https://pypi.org/pypi/numpy/json": (200, {"info": {"name": "numpy", "version": "2.5.3"}, "releases": {"2.5.3": [], "2.5.2": []}}),
        "https://pypi.org/pypi/numpyy/json": (404, {}),
        "https://registry.npmjs.org/@types%2Fnode": (200, {"dist-tags": {"latest": "24.1.0"}, "versions": {"24.1.0": {}, "22.0.0": {}}}),
        "https://registry.npmjs.org/no-such-pkg-xyz": (404, {}),
    }
    monkeypatch.setattr(E, "_http_json", lambda url: answers.get(url, (503, {})))
    ok = E.check_package("pip", "numpy")
    assert ok["exists"] is True and ok["latest"] == "2.5.3" and ok["version"] == "" and not ok["error"]
    pinned = E.check_package("pip", "numpy==2.5.2")
    assert pinned["exists"] is True and pinned["version"] == "2.5.2"
    missing_pin = E.check_package("pip", "numpy==9.9")
    assert missing_pin["exists"] is True and missing_pin["version"] == "" and "9.9 is not published" in missing_pin["error"] and "2.5.3" in missing_pin["error"]
    gone = E.check_package("pip", "numpyy")
    assert gone["exists"] is False and "not on PyPI" in gone["error"]
    scoped = E.check_package("npm", "@types/node@24.1.0")
    assert scoped["exists"] is True and scoped["name"] == "@types/node" and scoped["version"] == "24.1.0"
    assert E.check_package("npm", "no-such-pkg-xyz")["exists"] is False
    down = E.check_package("pip", "requests")
    assert down["exists"] is None and "could not be asked" in down["error"]
    with pytest.raises(HTTPException):
        E.check_package("cargo", "serde")
    with pytest.raises(HTTPException):
        E.check_package("pip", "not a spec !!")
    # apt: the box's own lists
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[:2])
        class R:
            stdout = ""
            returncode = 0
        out = R()
        if cmd[:2] == ["apt-cache", "policy"]:
            out.stdout = "jq:\n  Installed: (none)\n  Candidate: 1.7.1-3\n" if cmd[2] == "jq" else "N: Unable to locate package nope\n"
        if cmd[:2] == ["apt-cache", "madison"]:
            out.stdout = " jq | 1.7.1-3 | http://deb.debian.org bookworm/main amd64 Packages\n"
        return out
    monkeypatch.setattr(E.subprocess, "run", fake_run)
    monkeypatch.setattr(E, "_apt_lists", lambda: None)
    apt = E.check_package("apt", "jq=1.7.1-3")
    assert apt["exists"] is True and apt["latest"] == "1.7.1-3" and apt["version"] == "1.7.1-3"
    assert E.check_package("apt", "nope")["exists"] is False


def _apt_install_argv(monkeypatch, tmp_path, names):
    """The `apt-get install` command line `_apt_into_layer` hands the box for these declared specs,
    with `_run` stubbed: no apt, no network, no image, and the same argv a build would get."""
    calls = []

    def fake_run(log, cmd, cwd, env, deadline, run_as=None, flush=None):
        calls.append(cmd)
        if cmd[:3] == ["apt-get", "install", "-y"]:
            archives = tmp_path / "apt-archives"
            archives.mkdir(parents=True, exist_ok=True)
            (archives / "jq_1.7.1-3_amd64.deb").write_bytes(b"!")   # what apt would have downloaded
    monkeypatch.setattr(E, "_run", fake_run)
    layer = tmp_path / "layer"
    layer.mkdir(exist_ok=True)
    E._apt_into_layer([], layer, names, {}, str(tmp_path), time.time() + 60)
    return next(c for c in calls if c[:3] == ["apt-get", "install", "-y"])


def test_an_apt_spec_reaches_apt_as_the_version_the_declaration_names(monkeypatch, tmp_path):
    """#427: the pin was cut off before `apt-get` ran, so the layer held a different version than
    the record declared and nothing said so. A pin apt cannot satisfy must fail the build instead."""
    exact = _apt_install_argv(monkeypatch, tmp_path, ["jq=1.7.1-3"])
    assert "jq=1.7.1-3" in exact and "jq" not in exact
    # pip's `==` is not apt's grammar: it arrives as the single `=` apt parses
    doubled = _apt_install_argv(monkeypatch, tmp_path, ["jq==1.7.1-3"])
    assert "jq==1.7.1-3" not in doubled and "jq=1.7.1-3" in doubled
    # a range: apt has no syntax for one, and installing the newest whatever the range says would be
    # #427's silent substitution again, so the build fails naming it before apt runs at all
    for specs in (["jq>=1.6"], ["jq=1.7.1-3", "libyaml>=0.2", "curl"]):
        with pytest.raises(RuntimeError, match=r"cannot hold to (jq>=1\.6|libyaml>=0\.2)"):
            _apt_install_argv(monkeypatch, tmp_path, specs)
    # a bare name keeps its shape: only a pin gets the `=` joined back on
    bare = _apt_install_argv(monkeypatch, tmp_path, ["jq"])
    assert "jq" in bare and not any("=" in str(a) and a.startswith("jq") for a in bare)
    # several declarations keep their own arms, and the package specs are still the last words
    mixed = _apt_install_argv(monkeypatch, tmp_path, ["jq=1.7.1-3", "libyaml==0.2.5-1", "curl"])
    assert mixed[-3:] == ["jq=1.7.1-3", "libyaml=0.2.5-1", "curl"]
    assert mixed[:2] == ["apt-get", "install"] and "Debug::NoLocking=1" in mixed
    # #427's remaining question: a pin older than a version the image already has is planned by apt
    # as a downgrade, and `-y` alone stops on "Packages were downgraded and -y was used without
    # --allow-downgrades". The download goes to the layer's own cache, so the plan is all it changes.
    assert all("--allow-downgrades" in argv for argv in (exact, doubled, bare, mixed))


def test_a_range_is_a_name_with_no_pin_for_every_manager(monkeypatch):
    """`spec_parts` documents that a range is a name with no pin, and both the build's apt line and
    the console's package check read through it. Looking for the pin operator first broke that
    promise for every range that ends in `=`: `jq>=1.6` came back as the name `jq>`."""
    for spec, want in (("jq", ("jq", "")),
                       ("jq=1.7.1-3", ("jq", "1.7.1-3")),
                       ("jq==1.7.1-3", ("jq", "1.7.1-3")),
                       ("jq>=1.6", ("jq", "")),
                       ("jq<=1.6", ("jq", "")),
                       ("jq~=1.6", ("jq", "")),
                       ("jq!=1.6", ("jq", "")),
                       ("jq>1.6", ("jq", "")),
                       ("jq<1.6", ("jq", ""))):
        assert E.spec_parts(spec, "apt") == want, spec
        assert E.spec_parts(spec, "pip") == want, spec
    assert E.spec_parts("@types/node@24.1.0", "npm") == ("@types/node", "24.1.0")

    # and the registry is asked about the package a range names, not about `jq>`: before, an apt
    # range was looked up as a package literally called `jq>`, which is never in the box's lists
    def fake_run(cmd, **kw):
        class R:
            stdout, returncode = "", 0
        out = R()
        if cmd[:2] == ["apt-cache", "policy"]:
            assert cmd[2] == "jq", cmd      # the name, with no operator left glued to it
            out.stdout = "jq:\n  Installed: (none)\n  Candidate: 1.7.1-3\n"
        if cmd[:2] == ["apt-cache", "madison"]:
            out.stdout = " jq | 1.7.1-3 | http://deb.debian.org bookworm/main amd64 Packages\n"
        return out
    monkeypatch.setattr(E.subprocess, "run", fake_run)
    monkeypatch.setattr(E, "_apt_lists", lambda: None)
    ranged = E.check_package("apt", "jq>=1.6")
    assert ranged["exists"] is True and ranged["latest"] == "1.7.1-3" and ranged["version"] == ""
    # and it is refused there, with the reason, so the console never adds a range apt cannot hold to
    assert "cannot hold to jq>=1.6" in ranged["error"] and "jq=1.7.1-3" in ranged["error"]


def test_a_git_import_lands_files_and_directories_and_never_follows_a_link(store, tmp_path, monkeypatch):
    """A link a repository commits is dropped and counted, like an archive's; following it as root
    wrote what it pointed at into the source (reported privately). The clone gets the build's
    environment, without the runner's secrets."""
    outside = tmp_path / "outside"
    (outside / "dir").mkdir(parents=True)
    (outside / "private.txt").write_text("not for the environment")
    (outside / "dir" / "inner.txt").write_text("nor this")
    monkeypatch.setenv("HR_SECRET_KEY", "runner-secret-value")
    monkeypatch.setenv("HARNESS_INTERNAL_KEY", "runner-internal-value")
    seen = {}

    def fake_clone(cmd, **kw):
        seen["env"] = kw.get("env") or {}
        repo = pathlib.Path(cmd[-1])
        (repo / ".git").mkdir(parents=True)
        (repo / "src").mkdir()
        (repo / "README.md").write_text("hello\n")
        (repo / "src" / "run.sh").write_text("echo hi\n")
        os.chmod(repo / "src" / "run.sh", 0o755)
        os.symlink(outside / "private.txt", repo / "leak.txt")
        os.symlink(outside / "dir", repo / "src" / "linked-dir")
        os.symlink("README.md", repo / "readme-alias")
        return None
    monkeypatch.setattr(E.subprocess, "run", fake_clone)
    out = E.import_git("henv_g", "https://example.com/repo.git")
    assert out["written"] == 2 and out["skipped"] == 3, out
    files = {e["path"] for e in E.tree("henv_g") if not e["dir"]}
    assert files == {"README.md", "src/run.sh"}
    src = E.source_dir("henv_g")
    assert not any(p.is_symlink() for p in src.rglob("*"))
    assert all("not for the environment" not in p.read_text() and "nor this" not in p.read_text()
               for p in src.rglob("*") if p.is_file())
    assert os.stat(src / "src" / "run.sh").st_mode & 0o111
    assert "HR_SECRET_KEY" not in seen["env"] and "HARNESS_INTERNAL_KEY" not in seen["env"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_a_deleted_environment_takes_down_only_its_own_path(store):
    """Deleting keeps the files for 30 days and frees the name at once; by the time the files go,
    another environment may be mounted under that name, and its path must stay."""
    def point(env_id, slug):
        E.env_dir(env_id).mkdir(parents=True, exist_ok=True)
        os.makedirs(E.ENV_MOUNT, exist_ok=True)
        link = E.mount_path(slug)
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(str(E.active_link(env_id)), link)

    a, b = "henv_" + "a" * 32, "henv_" + "b" * 32
    point(a, "data")
    E.drop_mount("data", a)                      # the delete: its path goes, its files stay
    assert not os.path.lexists(E.mount_path("data")) and E.env_dir(a).is_dir()
    point(b, "data")                             # the name is taken by another environment
    E.drop_mount("data", a)
    E.delete_environment(a)                      # the sweep, 30 days later: no name given
    assert os.readlink(E.mount_path("data")) == str(E.active_link(b))
    assert not E.env_dir(a).exists()


def test_taking_a_path_down_refuses_a_name_that_is_not_one_segment(store):
    for slug in ("../outside", "a/b", "", ".."):
        with pytest.raises(HTTPException):
            E.drop_mount(slug, "henv_" + "a" * 32)


def test_a_pinned_git_clone_connects_to_the_address_the_gateway_classified(store, monkeypatch):
    """On a shared deployment the gateway hands over host:port:address; git must not resolve the
    name again when it connects (a DNS rebind), nor follow a redirect to a name it would resolve."""
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        os.makedirs(cmd[-1], exist_ok=True)
        pathlib.Path(cmd[-1], "README.md").write_text("hi\n")
        return None
    monkeypatch.setattr(E.subprocess, "run", fake_run)
    E.import_git("henv_" + "c" * 32, "https://git.example/team/repo.git", pin="git.example:443:140.82.112.3")
    E.import_git("henv_" + "c" * 32, "git@git.example:team/repo.git", pin="git.example:22:140.82.112.3")
    E.import_git("henv_" + "c" * 32, "https://git.example/team/repo.git")
    https, ssh, unpinned = seen
    assert https[:5] == ["git", "-c", "http.curloptResolve=git.example:443:140.82.112.3",
                         "-c", "http.followRedirects=false"]
    assert ssh[:3] == ["git", "-c", "core.sshCommand=ssh -o HostName=140.82.112.3 -o HostKeyAlias=git.example"]
    assert unpinned[:2] == ["git", "clone"]
    # through the route, as the gateway sends it
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(E.router)
    r = TestClient(app).post(f"/environments/henv_{'c' * 32}/import",
                             params={"git_url": "https://git.example/team/repo.git", "git_pin": "git.example:443:140.82.112.3"})
    assert r.status_code == 200 and seen[-1][:3] == ["git", "-c", "http.curloptResolve=git.example:443:140.82.112.3"]
    for bad in ("git.example:443:not-an-address", "git.example::140.82.112.3", "a b:22:140.82.112.3"):
        with pytest.raises(HTTPException):
            E.import_git("henv_" + "c" * 32, "git@git.example:team/repo.git" if " " in bad else
                         "https://git.example/team/repo.git", pin=bad)


def test_a_write_waiting_on_a_snapshot_or_a_slow_import_leaves_the_runner_answering(store, monkeypatch):
    """The runner answers every turn from one event loop. A write waiting for the source lock, or a
    git clone, run on that loop froze every other request until it ended (on 0.32.8 a 4.6 s import
    kept the runner's /healthz waiting 4.3 s); both now run in a worker thread."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(E.router)

    @app.get("/ping")
    async def ping():
        return {}

    eid = "henv_" + "d" * 32
    E.write_file(eid, "a.txt", b"1")
    done: dict = {}

    def ping_seconds(c):
        """How long the loop took to answer, or None when it had not answered in 2 s."""
        out: dict = {}
        th = threading.Thread(target=lambda: (t0 := time.time(), c.get("/ping"), out.update(s=time.time() - t0)), daemon=True)
        th.start()
        th.join(2.0)
        return out.get("s")

    with TestClient(app) as c:              # one client, one event loop, as in the runner
        lock = E._source_lock(eid)
        lock.acquire()                      # a build is inside its snapshot
        try:
            w = threading.Thread(target=lambda: done.update(w=c.put(f"/environments/{eid}/source",
                                                                    params={"path": "a.txt"}, content=b"2")), daemon=True)
            w.start()
            time.sleep(0.3)
            waited = ping_seconds(c)
            still_waiting = "w" not in done     # the write is held until the snapshot ends
        finally:
            lock.release()
        w.join(10)
        assert waited is not None and waited < 1.0, f"the runner did not answer while a write waited ({waited})"
        assert still_waiting and done["w"].status_code == 200 and E.read_file(eid, "a.txt")[0] == b"2"

        monkeypatch.setattr(E, "import_git", lambda *a, **k: (time.sleep(1.5), {"imported": "git"})[1])
        g = threading.Thread(target=lambda: done.update(g=c.post(f"/environments/{eid}/import",
                                                                 params={"git_url": "https://git.example/x.git"})), daemon=True)
        g.start()
        time.sleep(0.3)
        waited = ping_seconds(c)
        g.join(10)
        assert waited is not None and waited < 1.0, f"the runner did not answer while a git import ran ({waited})"
        assert done["g"].status_code == 200


def test_an_npm_range_is_a_name_with_no_pin(monkeypatch):
    """npm's ranges went through as exact pins, so `lodash@^4.17.0` was checked against the
    registry's exact versions and refused as "not published" though npm installs it."""
    for spec in ("lodash@^4.17.0", "lodash@~4.17", "lodash@>=4", "lodash@4.x", "lodash@*", "lodash@1 || 2"):
        assert E.spec_parts(spec, "npm") == ("lodash", ""), spec
    for spec, want in (("lodash@4.17.21", ("lodash", "4.17.21")), ("@types/node@24.1.0", ("@types/node", "24.1.0")),
                       ("lodash@1.0.0-rc.1", ("lodash", "1.0.0-rc.1")), ("lodash", ("lodash", ""))):
        assert E.spec_parts(spec, "npm") == want, spec
    answers = {"https://registry.npmjs.org/lodash": (200, {"dist-tags": {"latest": "4.17.21"},
                                                          "versions": {"4.17.21": {}, "4.17.20": {}}})}
    monkeypatch.setattr(E, "_http_json", lambda url: answers.get(url, (503, {})))
    ranged = E.check_package("npm", "lodash@^4.17.0")
    assert ranged["exists"] is True and ranged["error"] == "" and ranged["version"] == ""
    assert "not published" in E.check_package("npm", "lodash@9.9.9")["error"]


def test_a_pip_wildcard_pin_is_a_name_with_no_pin(monkeypatch):
    """PEP 440's prefix match (`numpy==1.4.*`) is every release beginning `1.4.`, not one version,
    the way npm's `lodash@4.x` is not. It went through as an exact pin, so it was checked against
    PyPI's exact releases and refused as "not published" though pip installs it."""
    for spec in ("numpy==1.4.*", "numpy==1.*", "numpy == 1.4.* "):
        assert E.spec_parts(spec, "pip") == ("numpy", ""), spec
    for spec, want in (("numpy==1.4.0", ("numpy", "1.4.0")), ("numpy==1.4.0rc1", ("numpy", "1.4.0rc1")),
                       ("numpy", ("numpy", ""))):
        assert E.spec_parts(spec, "pip") == want, spec

    answers = {"https://pypi.org/pypi/numpy/json": (200, {"info": {"version": "2.3.1", "name": "numpy"},
                                                          "releases": {"1.4.0": {}, "1.4.1": {}, "2.3.1": {}}})}
    monkeypatch.setattr(E, "_http_json", lambda url: answers.get(url, (503, {})))
    ranged = E.check_package("pip", "numpy==1.4.*")
    assert ranged["exists"] is True and ranged["error"] == "" and ranged["version"] == ""
    assert "not published" in E.check_package("pip", "numpy==9.9.9")["error"]
    # and an apt declaration keeps its pin verbatim: apt has no wildcard, so `=1.4.*` is a pin
    # that is genuinely not in the sources, which is what the check should say.
    assert E.spec_parts("jq=1.4.*", "apt") == ("jq", "1.4.*")


def test_an_npm_dist_tag_resolves_to_its_version(monkeypatch):
    """#494: `lodash@latest` names a dist-tag, not a version — the check resolves the tag
    instead of reporting it "not published". An unknown tag keeps the error."""
    answers = {
        "https://registry.npmjs.org/lodash": (200, {
            "dist-tags": {"latest": "4.17.21", "next": "4.17.22-beta.0"},
            "versions": {"4.17.21": {}, "4.17.20": {}},
        }),
    }
    monkeypatch.setattr(E, "_http_json", lambda url: answers.get(url, (503, {})))
    tagged = E.check_package("npm", "lodash@latest")
    assert tagged["exists"] is True and tagged["version"] == "4.17.21" and not tagged["error"]
    other_tag = E.check_package("npm", "lodash@next")
    assert other_tag["version"] == "4.17.22-beta.0" and not other_tag["error"]
    unknown = E.check_package("npm", "lodash@no-such-tag")
    assert unknown["version"] == "" and "no-such-tag is not published" in unknown["error"]
    exact = E.check_package("npm", "lodash@9.9.9")
    assert exact["version"] == "" and "9.9.9 is not published" in exact["error"]
    pinned = E.check_package("npm", "lodash@4.17.20")
    assert pinned["version"] == "4.17.20" and not pinned["error"]


def test_an_apt_epoch_is_a_spec_the_check_recommends_and_both_the_check_and_the_build_accept(monkeypatch, tmp_path):
    """An apt version may carry an epoch (`7:4.4.2-0ubuntu0.22.04.1`), and `_SPEC_RE` left `:` out of
    its version class, so the spec `check_package` itself tells an owner to declare came back from
    `check_package` as HTTP 400 "that is not a package spec" and was dropped from a build's
    declaration by `clean_specs` with no error at all. The rest of the file already reads epochs:
    the `Candidate:` line is split once on `:`, and `_apt_packages` decodes `%3a` back to one."""
    candidate = "7:4.4.2-0ubuntu0.22.04.1"

    def fake_run(cmd, **kw):
        class R:
            stdout, stderr, returncode = "", "", 0
        out = R()
        if cmd[:2] == ["apt-cache", "policy"]:
            assert cmd[2] == "ffmpeg", cmd
            out.stdout = f"ffmpeg:\n  Installed: (none)\n  Candidate: {candidate}\n"
        if cmd[:2] == ["apt-cache", "madison"]:
            out.stdout = f" ffmpeg | {candidate} | http://archive.ubuntu.com jammy/main amd64 Packages\n"
        return out
    monkeypatch.setattr(E.subprocess, "run", fake_run)
    monkeypatch.setattr(E, "_apt_lists", lambda: None)

    # the round trip: the advice a range gets names a spec, and that spec is accepted
    advice = E.check_package("apt", "ffmpeg>=7")["error"]
    recommended = advice.split(", or ", 1)[1].split(" to pin", 1)[0]
    assert recommended == f"ffmpeg={candidate}", advice
    pinned = E.check_package("apt", recommended)
    assert pinned["error"] == "" and pinned["exists"] is True and pinned["version"] == candidate
    assert E.spec_parts(recommended, "apt") == ("ffmpeg", candidate)

    # and the build keeps it instead of silently dropping it: it reaches apt-get as declared
    assert E.clean_specs([recommended]) == [recommended]
    argv = _apt_install_argv(monkeypatch, tmp_path, [recommended])
    assert argv[-1] == f"ffmpeg={candidate}", argv

    # the gate is still a gate: the colon is admitted only as apt's epoch, so nothing else a colon
    # introduces becomes a spec, and a malformed version is refused as before
    for bad in ("foo@npm:other", "pkg@https://example.invalid/x", "ffmpeg=1:2:3", ":1.0",
                "ffmpeg=99999:1.0", "jq==1.0;rm -rf /", "jq=1.0 2.0"):
        assert E.clean_specs([bad]) == [], bad
        with pytest.raises(HTTPException) as e:
            E.check_package("apt", bad)
        assert e.value.status_code == 400 and e.value.detail == "that is not a package spec", bad

    # `_SPEC_RE` is shared with pip and npm, which have no epoch: their own spellings are unchanged
    for ok in ("requests==2.31.0", "numpy==1.4.*", "numpy>=1.4", "lodash@^4.17.0", "lodash@4.x",
               "@types/node@24.1.0", "lodash@latest", "jq"):
        assert E.clean_specs([ok]) == [ok], ok
