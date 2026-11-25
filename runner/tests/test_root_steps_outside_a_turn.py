"""What the runner does as root outside a turn's own scope is done as the session, or in root's own places.

The turn's builders write as the session (_fs_as). A few steps run elsewhere: the cleanup that follows a
workspace's history rewrite, reached from /hydrate, /checkpoint and /produced; two probes that start a CLI as
root to ask it about its models; and the log line a session delete writes about a remote backend's record.
Each one keeps to the same rule: a session's tree is changed as the session, root's own processes start from
root's own folders, and a file in a session's tree reaches the log by name and size, never by content.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

_ROOT_ON_LINUX = sys.platform.startswith("linux") and os.geteuid() == 0
root_only = pytest.mark.skipif(not _ROOT_ON_LINUX, reason="the write-wall is root's, on Linux")
UID = 20780


def _fs_uid() -> int:
    """This thread's filesystem uid, the fourth figure of its Uid line."""
    for line in pathlib.Path("/proc/thread-self/status").read_text().splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[4])
    raise AssertionError("no Uid line")


@root_only
def test_the_history_rewrite_removes_its_scratch_index_as_the_session(monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    ws = tempfile.mkdtemp(prefix="hrshed-")
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    monkeypatch.setattr(server, "_git", lambda ws, *a, **k: subprocess.CompletedProcess(a, 0, "0" * 40, ""))
    seen = []
    real_unlink = os.unlink

    def unlink(p, *a, **k):
        if str(p).endswith("hr-shed-index"):
            seen.append(_fs_uid())
        return real_unlink(p, *a, **k)
    monkeypatch.setattr(server.os, "unlink", unlink)
    server._git_shed_cli_home_history(ws)
    assert seen == [UID], f"removed as {seen}"


@root_only
def test_the_jcode_model_probe_gets_a_home_of_roots_own(monkeypatch):
    """The probe starts as root from inside a session's scope; the folder it is given as its home is root's."""
    bindir = pathlib.Path(tempfile.mkdtemp(prefix="hrjcodebin-"))
    os.chmod(bindir, 0o755)
    stub = bindir / "jcode"
    stub.write_text('#!/bin/sh\necho "claude-home-$(stat -c %u-%a "$HOME")"\n')
    os.chmod(stub, 0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '/usr/bin:/bin')}")
    monkeypatch.setattr(server, "_JCODE_ANTHROPIC_LISTED", None)
    with server._fs_as(UID):
        listed = server._jcode_anthropic_listed()
    assert listed == ["claude-home-0-700"], listed


def test_the_fast_agent_model_probe_starts_in_a_folder_no_session_can_write(monkeypatch):
    seen = []

    def run(cmd, *a, **kw):
        seen.append(kw)
        return subprocess.CompletedProcess(cmd, 0, '{"tokenizes": ["text/plain"]}\n', "")
    monkeypatch.setattr(server.subprocess, "run", run)
    monkeypatch.setattr(server, "_FA_KNOWN", {})
    assert server._fast_agent_known("probe-model-cwd") == {"tokenizes": ["text/plain"]}
    assert seen and seen[0].get("cwd") == "/"


def test_a_session_delete_logs_the_remote_record_by_name_and_size_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    ws = tmp_path / "hsessdel"
    state = ws / server.QODER_STATE_REL
    state.parent.mkdir(parents=True)
    body = '{"agents": ["remote-id-4b7e"]}'
    state.write_text(body)
    out = server._remote_purge(str(ws), None)
    assert out and out["purged"] is False and out["reason"] == "no credential"
    logged = capsys.readouterr().out
    assert server.QODER_STATE_REL in logged and f"({len(body)} bytes)" in logged
    assert "remote-id-4b7e" not in logged, "the log carried the file's contents"
