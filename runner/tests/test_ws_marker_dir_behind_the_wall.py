"""Behind the write-wall the workspace markers live only where the entrypoint put them.

The runner writes and removes a marker per session as root. Behind the wall (one runner, many session uids)
it takes the folder from HR_WS_MARKER_DIR, and that must be a real directory of root's with mode 0700; without
one the runner refuses to start rather than keep the markers anywhere else. A per-session sandbox, and a runner
without the wall, keep what they had.
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
root_only = pytest.mark.skipif(not _ROOT_ON_LINUX, reason="a directory of root's needs root")


@pytest.fixture
def wall(monkeypatch):
    monkeypatch.setattr(server, "_SESSION_UIDS", True)
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    return monkeypatch


def test_the_wall_refuses_to_start_without_a_named_folder(wall, tmp_path):
    wall.delenv("HR_WS_MARKER_DIR", raising=False)
    wall.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "data" / "workspaces"))
    with pytest.raises(RuntimeError, match="HR_WS_MARKER_DIR"):
        server._ws_marker_dir()


def test_the_wall_refuses_a_folder_that_is_not_there(wall, tmp_path):
    wall.setenv("HR_WS_MARKER_DIR", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="HR_WS_MARKER_DIR"):
        server._ws_marker_dir()


def _roots(mode: int = 0o700) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp(prefix="hrmarkers-"))
    os.chmod(d, mode)
    return d


@pytest.mark.parametrize("shape", ["another owner's", "mode 0755", "mode 0733", "a link to root's folder", "a file"])
def test_the_wall_refuses_a_folder_of_any_other_shape(wall, shape):
    if shape == "another owner's":
        d = _roots()
        if os.geteuid() == 0:
            os.chown(d, 20781, 20781)
        named = d                                 # not root's: a non-root test process makes its own
    elif shape.startswith("mode"):
        if os.geteuid() != 0:
            pytest.skip("a directory of root's needs root")
        named = _roots(int(shape.split()[1], 8))
    elif shape.startswith("a link"):
        target = _roots()
        named = pathlib.Path(tempfile.mkdtemp(prefix="hrmarkerlink-")) / "markers"
        named.symlink_to(target)
    else:
        named = pathlib.Path(tempfile.mkdtemp(prefix="hrmarkerfile-")) / "markers"
        named.write_text("")
    wall.setenv("HR_WS_MARKER_DIR", str(named))
    with pytest.raises(RuntimeError, match="HR_WS_MARKER_DIR"):
        server._ws_marker_dir()


@root_only
def test_the_wall_takes_a_folder_of_roots_own(wall):
    d = _roots()
    wall.setenv("HR_WS_MARKER_DIR", str(d))
    assert server._ws_marker_dir() == str(d)


def test_a_per_session_sandbox_and_a_runner_without_the_wall_keep_what_they_had(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.delenv("HR_WS_MARKER_DIR", raising=False)
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", True)
    assert server._ws_marker_dir() == "/tmp/hr-ws"
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "data" / "workspaces"))
    assert server._ws_marker_dir() == str(tmp_path / "data" / "ws-markers")
    monkeypatch.setenv("HR_WS_MARKER_DIR", str(tmp_path / "named"))
    assert server._ws_marker_dir() == str(tmp_path / "named")


@root_only
@pytest.mark.parametrize("named", [None, "shared"], ids=["unset", "a shared scratch folder"])
def test_the_runner_does_not_start_behind_the_wall_without_one(tmp_path, named):
    runner = str(pathlib.Path(__file__).resolve().parents[1])
    env = {k: v for k, v in os.environ.items() if k != "HR_WS_MARKER_DIR"}
    env.update(HR_SESSION_UIDS="1", HARNESS_WORKSPACE=str(tmp_path / "workspaces"))
    if named:
        env["HR_WS_MARKER_DIR"] = "/tmp"
    out = subprocess.run([sys.executable, "-c", "import server"], env=env, cwd=runner,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode != 0 and "HR_WS_MARKER_DIR" in out.stderr, (out.returncode, out.stderr[-600:])
