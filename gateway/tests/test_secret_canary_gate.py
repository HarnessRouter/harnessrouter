"""The release gate's own eyes. A scan that can't see a value passes for the wrong reason, so these
plant one in each form it claims to read, and it must find every one."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import io
import pathlib
import subprocess
import tarfile
import urllib.parse
import zlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("secret_canary_gate", ROOT / "scripts" / "secret-canary-gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

VALUE = "canary-value-0123456789abcdef"


def _found(data: bytes) -> bool:
    t = gate.Table()
    t.add("x", VALUE)
    t.scan(data, "here")
    return bool(t.where("x"))


def _tar(name: str, body: bytes) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tf:
        info = tarfile.TarInfo(name)
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    return out.getvalue()


@pytest.mark.parametrize("data", [
    VALUE.encode(),
    b"before " + VALUE.encode() + b" after",
    base64.b64encode(VALUE.encode()),
    base64.urlsafe_b64encode(VALUE.encode()),
    urllib.parse.quote("x=" + VALUE, safe="").encode(),
    gzip.compress(VALUE.encode()),
    zlib.compress(VALUE.encode()),
    _tar("a/b.txt", VALUE.encode()),
    gzip.compress(_tar("a/b.txt", VALUE.encode())),
    gzip.compress(_tar("a/b.gz", gzip.compress(VALUE.encode()))),
], ids=["raw", "inside", "base64", "urlsafe", "urlencoded", "gzip", "zlib", "tar", "tar.gz", "gz-in-tar.gz"])
def test_each_form_is_found(data):
    assert _found(data)


def test_a_clean_blob_finds_nothing():
    assert not _found(b"nothing to see" * 100)
    assert not _found(gzip.compress(b"nothing to see"))


def test_a_value_too_short_to_be_a_credential_is_not_looked_for():
    t = gate.Table()
    t.add("short", "ci-smoke")
    assert "short" not in t.by_label


def test_a_tree_is_walked_into_dot_folders_and_git_objects_are_read(tmp_path):
    (tmp_path / ".harness" / "home").mkdir(parents=True)
    (tmp_path / ".harness" / "home" / "config.toml").write_text(f"token = '{VALUE}'")
    t = gate.Table()
    t.add("x", VALUE)
    gate.scan_tree(str(tmp_path), t, "session")
    assert t.where("x") == {"session:.harness/home/config.toml"}

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    (repo / "f").write_text(VALUE)
    subprocess.run(["git", "add", "f"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=repo, check=True, env=env)
    (repo / "f").unlink()
    subprocess.run(["git", "commit", "-qam", "gone"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "gc", "-q"], cwd=repo, check=True, env=env)       # packed, and no longer in any file
    t = gate.Table()
    t.add("x", VALUE)
    gate.scan_tree(str(repo), t, "session")
    assert any("git objects" in w for w in t.where("x"))


def test_a_link_is_not_followed_and_a_skipped_tree_is_skipped(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text(VALUE)
    root = tmp_path / "root"
    (root / "tools").mkdir(parents=True)
    (root / "lnk").symlink_to(outside)
    (root / "tools" / "f").write_text(VALUE)
    t = gate.Table()
    t.add("x", VALUE)
    gate.scan_tree(str(root), t, "v", skip=(str(root / "tools"),))
    assert not t.where("x")


@pytest.mark.parametrize("kind,where,ok", [
    ("path", "volume:graph.db", True),
    ("query", "volume:graph.db-wal", True),
    ("pkg-bearer", "volume:blobs/harness-sessions/plugins/local/p.json", True),
    ("pkg-bearer", "volume:graph.db", True),
    ("pkg-bearer", "volume:blobs/other.json", False),
    ("bearer", "volume:graph.db", False),
    ("header", "volume:graph.db-wal", False),
    ("conn", "volume:secrets/global/x", False),
    ("path", "session folder:.harness/home/config.toml", False),
    ("pkg-bearer", "session folder:.harness/plugins/p/mcp.json", False),
    ("query", "process node environ", False),
    ("path", "client read responses/resp_1", False),
])
def test_only_what_is_stored_as_written_may_sit_at_rest(kind, where, ok):
    assert gate.at_rest_allowed(kind, where) is ok


def test_the_stand_in_answers_each_way_a_base_asks():
    for path, body in (("/x/v1/chat/completions", {"stream": True}), ("/x/v1/messages", {"stream": True}),
                       ("/x/v1/responses", {"stream": True}), ("/x/v1beta/models/m:streamGenerateContent", {})):
        ctype, data = gate._model_body(path, body)
        assert ctype == "text/event-stream" and b"OK" in data
    assert gate._model_body("/x/v1/chat/completions", {})[0] == "application/json"
