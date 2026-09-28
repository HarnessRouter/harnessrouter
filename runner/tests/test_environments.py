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
    assert oct(os.stat(v1 / "scripts" / "render.py").st_mode & 0o777) == "0o644"
    assert oct(os.stat(v1 / "run.sh").st_mode & 0o777) == "0o755"
    assert oct(os.stat(v1).st_mode & 0o777) == "0o755"
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


def test_the_slug_is_a_path_segment(store):
    assert E.slug_ok("content-studio") and E.slug_ok("a.b_c") and not E.slug_ok("../x") and not E.slug_ok("a/b") and not E.slug_ok("")
