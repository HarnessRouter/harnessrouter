"""A turn's processes carry the turn's id in their environment, so what the process-group kill
misses can still be found: openhands' terminal tool runs commands in tmux, whose server
daemonises with setsid, and a cancelled turn left it and the agent's `sleep 240` running
(hr-test, 2026-09-19)."""
import os
import pathlib
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


@pytest.mark.skipif(not os.path.isdir("/proc"), reason="reads /proc, Linux only")
def test_a_process_that_left_the_group_is_still_found_by_the_turns_marker(tmp_path):
    marker = "turn-sweep-" + str(os.getpid())
    tmux_dir = tmp_path / "ohsock"; tmux_dir.mkdir()
    # a child spawned in THIS group that then puts itself in a new session, as tmux's server does
    # (not start_new_session=True: a session leader's own setsid() is EPERM, and the child died
    # before the sweep looked, which is how the first version of this test failed in CI)
    child = subprocess.Popen([sys.executable, "-c", "import os,time; os.setsid(); time.sleep(60)"],
                             env={**os.environ, rs._TURN_MARK: marker, "TMUX_TMPDIR": str(tmux_dir)})
    time.sleep(0.5)
    assert child.poll() is None, "the child must be alive and in its own session when the sweep runs"
    assert os.getsid(child.pid) == child.pid
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             env={**os.environ, rs._TURN_MARK: "another-turn"}, start_new_session=True)
    try:
        killed = rs._sweep_turn_processes(marker)
        assert killed >= 1
        child.wait(timeout=5)
        assert child.returncode is not None
        assert other.poll() is None                       # a different turn's process is untouched
        assert rs._sweep_turn_processes("") == 0            # no marker, no sweep
    finally:
        other.kill()


def test_the_cli_env_carries_the_marker_and_the_kill_sites_pass_the_turn_id():
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    assert "env = {**env, _TURN_MARK: turn_id}" in src
    assert '_kill_proc_tree(proc, turn_id)' in src
    assert '_kill_proc_tree(proc, str(rec.get("turn_id") or ""))' in src
