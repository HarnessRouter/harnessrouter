"""No process at a session's identity carries the runner's own environment.

The runner starts session processes through setpriv (_in_session), which root execs with the child's own
environment, and it starts with no secret in its own environment (docker/entrypoint.sh, HR_INTERNAL_KEY_FILE).
These sample, as root, every process at a session uid while spawns run. The first test is the sampler's own
control: a session process GIVEN the secret must be caught, or a pass below would prove nothing. Root on Linux
only (CI's runner job runs this file with HR_REQUIRE_ROOT_TESTS=1); elsewhere there is nothing to test.
"""
import glob
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import threading
import uuid

import pytest

RUNNER = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER))
import server  # noqa: E402

_ROOT_ON_LINUX = sys.platform.startswith("linux") and os.geteuid() == 0
if os.environ.get("HR_REQUIRE_ROOT_TESTS") == "1" and not _ROOT_ON_LINUX:
    raise RuntimeError("HR_REQUIRE_ROOT_TESTS=1, and these tests are not running as root on Linux")
pytestmark = pytest.mark.skipif(not _ROOT_ON_LINUX, reason="session uids are root's, on Linux")
UID = server._SESSION_UID_BASE + 4242


class Sampler:
    """Reads, as root, the environment of every process at UID until stopped: how many it saw, and how
    many held the secret."""

    def __init__(self, secret: bytes):
        self.secret = secret
        self.seen: set[str] = set()
        self.hits: set[str] = set()
        self.stop = threading.Event()
        self.t = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        while not self.stop.is_set():
            for d in glob.glob("/proc/[0-9]*"):
                try:
                    if os.stat(d).st_uid != UID:
                        continue
                    with open(f"{d}/environ", "rb") as fh:
                        env = fh.read()
                    with open(f"{d}/stat", "rb") as fh:
                        start = fh.read().rsplit(b")", 1)[1].split()[19].decode()
                except (OSError, IndexError):
                    continue
                key = f"{d}:{start}"
                self.seen.add(key)
                if self.secret in env:
                    self.hits.add(key)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.t.join(5)


def _workspace() -> str:
    ws = tempfile.mkdtemp(prefix="hrspawn-")
    os.chown(ws, UID, UID)
    os.chmod(ws, 0o700)
    return ws


def _run_helper(code: str, secret: str, ws: str) -> subprocess.CompletedProcess:
    """`code` in a fresh interpreter whose own environment holds the secret, as the runner's holds its key."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(RUNNER), "HOME": "/tmp",
           "HARNESS_INTERNAL_KEY": secret, "HR_WS": ws, "HR_UID": str(UID)}
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], env=env, capture_output=True,
                          text=True, timeout=120)


def test_the_sampler_sees_a_session_process_that_holds_the_secret():
    """Control: a session process whose own environment is given the secret, through the same path."""
    secret = f"canary-internal-{uuid.uuid4().hex}"
    ws = _workspace()
    with Sampler(secret.encode()) as s:
        p = _run_helper("""
            import os, subprocess
            import server
            server._SESSION_UIDS = True
            ws = os.environ["HR_WS"]
            env = {"PATH": os.environ["PATH"], "GIVEN": os.environ["HARNESS_INTERNAL_KEY"]}
            for _ in range(5):
                subprocess.run(server._in_session(["sleep", "0.3"], ws, env), env=env, check=True)
        """, secret, ws)
    assert p.returncode == 0, p.stderr
    assert s.hits, f"the sampler saw {len(s.seen)} process(es) at the session uid and missed the secret it was given"


def test_session_processes_never_show_the_runner_environment():
    secret = f"canary-internal-{uuid.uuid4().hex}"
    ws = _workspace()
    with Sampler(secret.encode()) as s:
        p = _run_helper("""
            import os, subprocess
            import server
            server._SESSION_UIDS = True
            ws = os.environ["HR_WS"]
            env = {**server._child_env(), "PATH": os.environ["PATH"]}
            assert "HARNESS_INTERNAL_KEY" not in env
            for _ in range(150):
                argv = server._in_session(["sleep", "0.02"], ws, env)
                assert argv[0] == server._SETPRIV and argv[-2:] == ["sleep", "0.02"], argv
                subprocess.run(argv, env=env, check=True)
            out = subprocess.run(server._in_session(["id", "-u"], ws, env), env=env, capture_output=True, text=True)
            print("uid", out.stdout.strip())
        """, secret, ws)
    assert p.returncode == 0, p.stderr
    assert f"uid {UID}" in p.stdout                      # the process ran as the session, not as root
    assert len(s.seen) >= 20, f"the sampler saw only {len(s.seen)} session process(es): it was not looking"
    assert not s.hits, f"{len(s.hits)} process(es) at the session uid held the runner's environment"

