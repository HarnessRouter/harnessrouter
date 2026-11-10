"""Nothing the runner starts as a session's uid holds the runner's secrets.

Git ran as the session uid with the runner's whole environment (HARNESS_INTERNAL_KEY included), inside a .git
the agent can write: a post-commit hook or a core.fsmonitor command the agent left there ran at the next
checkpoint with the internal key, and a process of the agent's still running could read /proc/<git>/environ
(2026-11-02). With the internal key, every session's files and every connection on the box are the agent's.
"""
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

SECRET = "hik-canary-internal-key-0123456789"


def _repo():
    d = tempfile.mkdtemp()
    server._git_ensure(d)
    (pathlib.Path(d) / "a.txt").write_text("a")
    return d


def test_git_starts_from_the_scrubbed_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_INTERNAL_KEY", SECRET)
    monkeypatch.setenv("HR_SECRET_KEY", SECRET + "-store")
    seen = []
    real = subprocess.run

    def run(cmd, *a, **kw):
        seen.append(kw.get("env"))
        return real(cmd, *a, **kw)
    monkeypatch.setattr(server.subprocess, "run", run)
    server._git(_repo(), "status", "--porcelain")
    assert seen and all(e is not None for e in seen), "git inherited the runner's environment"
    assert not any(SECRET in repr(e) for e in seen)


def test_a_hook_the_agent_planted_does_not_run(monkeypatch):
    monkeypatch.setenv("HARNESS_INTERNAL_KEY", SECRET)
    d = _repo()
    out = pathlib.Path(tempfile.mkdtemp()) / "hook-ran"
    hook = pathlib.Path(d) / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\nenv > {out}\n")
    hook.chmod(0o755)
    server._git(d, "add", "-A")
    server._git(d, "commit", "-q", "-m", "checkpoint")
    assert not out.exists(), "the agent's post-commit hook ran"


def test_an_fsmonitor_command_the_agent_set_does_not_run(monkeypatch):
    monkeypatch.setenv("HARNESS_INTERNAL_KEY", SECRET)
    d = _repo()
    out = pathlib.Path(tempfile.mkdtemp()) / "fsmonitor-ran"
    subprocess.run(["git", "-C", d, "config", "core.fsmonitor", f"sh -c 'env > {out}'"], check=True)
    server._git(d, "status", "--porcelain")
    assert not out.exists(), "the agent's fsmonitor command ran"


def test_the_hydrate_tar_starts_from_the_scrubbed_environment(monkeypatch):
    """The other spawns as the session (hydrate's tar, the qoder purge) take _child_env, never the
    runner's own: the source names it at each one."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "server.py").read_text()
    for marker in ('["tar", "xzf", "-", "-C", ws]', "_driver_cmd(QODER_PYTHON, QODER_DRIVER, job, penv)"):
        at = src.index(marker)
        window = src[max(0, at - 300): at + 300]
        assert "_child_env()" in window, marker
    assert "{**os.environ" not in src, "a spawn starts from the runner's whole environment"
