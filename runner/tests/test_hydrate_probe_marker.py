"""The warm-resume probe vouches for a workspace that is actually there.

/hydrate?probe=<sha> asks "do you still hold this checkpoint?" so a follow-up turn on a warm
sandbox can skip the download and the wipe+untar. The answer came from the per-session marker
under /tmp/hr-ws alone — and the marker outlives the workspace: delete the folder from the
volume by hand and `docker stop`/`start` the runner, or call DELETE /workspace (which removed
the folder but, unlike the reaper, left the marker), and the next probe still said "held".
The gateway then skipped the restore and the turn ran on an empty workspace: the CLI found no
session to resume and the conversation started over (#194).
"""
import hashlib
import io
import pathlib
import sys
import tarfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


@pytest.fixture
def runner(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setattr(server, "_WS_MARKER_DIR", str(tmp_path / "markers"))
    monkeypatch.setattr(server, "SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", False)
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_INTERNAL_KEY", "")
    (tmp_path / "ws").mkdir()
    return TestClient(server.app)


def _checkpoint() -> tuple[bytes, str]:
    """A checkpoint tarball as the gateway would stream it, and the sha it will probe with."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b'{"step": 1}'
        info = tarfile.TarInfo("./plan.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    body = buf.getvalue()
    return body, hashlib.sha256(body).hexdigest()


def test_a_warm_workspace_answers_the_probe(runner):
    body, sha = _checkpoint()
    assert runner.post("/hydrate?identifier=s1", content=body).json()["restored"] is True
    assert runner.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is True


def test_a_workspace_deleted_behind_the_marker_is_hydrated_again(runner, tmp_path):
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    import shutil
    shutil.rmtree(tmp_path / "ws" / "s1")                 # by hand on the volume, runner still up
    assert runner.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is False
    assert not server._ws_marker_path("s1").exists(), "the marker that lied is gone"
    # and the full hydrate the gateway then sends lands as usual
    r = runner.post("/hydrate?identifier=s1", content=body).json()
    assert r["restored"] is True and (tmp_path / "ws" / "s1" / "plan.json").read_text() == '{"step": 1}'


def test_delete_workspace_takes_the_marker_with_it(runner, tmp_path):
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    assert server._ws_marker_path("s1").exists()
    assert runner.delete("/workspace?identifier=s1").json()["removed"] is True
    assert not server._ws_marker_path("s1").exists()
    assert runner.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is False


def test_delete_workspace_clears_the_marker_even_when_the_folder_is_already_gone(runner, tmp_path):
    # the folder removed by hand, the marker left standing: DELETE answers "no folder", and must
    # still take the marker with it — this is the very state in which a marker lies to the probe
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    import shutil
    shutil.rmtree(tmp_path / "ws" / "s1")
    assert server._ws_marker_path("s1").exists()
    r = runner.delete("/workspace?identifier=s1").json()
    assert r["removed"] is False and r["reason"] == "no folder"
    assert not server._ws_marker_path("s1").exists()
    assert runner.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is False


def test_the_markers_live_as_long_as_the_workspaces(monkeypatch, tmp_path):
    """Self-hosted keeps workspaces on the /data volume, and the markers go there too: in /tmp a
    restart forgot them, the probe missed, and the last checkpoint was restored over a workspace
    that had survived the restart (#505). The entrypoint names the place; without it a runner that
    holds several sessions puts them beside its workspace root; a per-session sandbox keeps /tmp."""
    entry = (pathlib.Path(server.__file__).resolve().parents[1] / "docker" / "entrypoint.sh").read_text()
    assert 'HR_WS_MARKER_DIR="${HR_WS_MARKER_DIR:-$DATA_DIR/ws-markers}"' in entry
    monkeypatch.setenv("HR_WS_MARKER_DIR", str(tmp_path / "named"))
    assert server._ws_marker_dir() == str(tmp_path / "named")
    monkeypatch.delenv("HR_WS_MARKER_DIR")
    monkeypatch.setattr(server, "WORKSPACE_ROOT", str(tmp_path / "data" / "workspaces"))
    assert server._ws_marker_dir() == str(tmp_path / "data" / "ws-markers")
    monkeypatch.setattr(server, "_SANDBOX_PER_SESSION", True)
    assert server._ws_marker_dir() == "/tmp/hr-ws"


def test_the_reaper_drops_a_marker_whose_folder_is_gone(runner, tmp_path):
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    runner.post("/hydrate?identifier=s2", content=body)
    import shutil
    shutil.rmtree(tmp_path / "ws" / "s1")                 # gone some other way than the reaper
    server._reap_workspaces(keep="s3")
    assert not server._ws_marker_path("s1").exists()
    assert server._ws_marker_path("s2").exists()          # its folder is there: kept


def test_a_workspace_that_outlived_a_restart_is_kept_as_the_interrupted_turn_left_it(runner, tmp_path):
    """The restart case (#505): the turn after the checkpoint wrote files, then the process died.
    The workspace and its marker are both on the volume, so the next turn's probe is answered
    'held' and the work the interrupted turn did is still there for the follow-up to continue."""
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    (tmp_path / "ws" / "s1" / "step2.txt").write_text("written before the restart")
    fresh = TestClient(server.app)                          # a new process, same volume
    assert fresh.post(f"/hydrate?identifier=s1&probe={sha}", content=b"").json()["skipped"] is True
    assert (tmp_path / "ws" / "s1" / "step2.txt").read_text() == "written before the restart"


def test_a_restore_cut_short_leaves_no_marker_vouching_for_it(runner, tmp_path, monkeypatch):
    """The marker now outlives a restart, so a hydrate that dies between the wipe and the untar
    must not leave the previous marker saying the half-restored folder holds the checkpoint."""
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s1", content=body)
    real_run = server.subprocess.run
    def _dies(cmd, *a, **k):
        if cmd[:2] == ["tar", "xzf"]:
            raise RuntimeError("killed mid-untar")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(server.subprocess, "run", _dies)
    with pytest.raises(RuntimeError):
        runner.post("/hydrate?identifier=s1", content=body)
    assert not server._ws_marker_path("s1").exists()


# ── a session that never saved a checkpoint (#712) ──────────────────────────────────────────────

def test_a_first_turn_cut_before_any_checkpoint_is_kept_for_the_follow_up(runner, tmp_path):
    """The first turn started from an empty restore, wrote a file and its CLI's conversation, and a
    restart cut it before the end-of-turn checkpoint. The follow-up asked about nothing, restored
    nothing over the folder and wiped both: the agent answered "this is the start of our
    conversation" and the file was gone (#712). Asked about the fresh start, the runner keeps it."""
    assert runner.post("/hydrate?identifier=s1", content=b"").json()["restored"] is False   # a new session
    ws = tmp_path / "ws" / "s1"
    (ws / "step0.txt").write_text("written by the cut turn")
    conv = ws / ".harness" / "home" / ".claude" / "projects" / "p" / "a2207f59.jsonl"
    conv.parent.mkdir(parents=True)
    conv.write_text('{"type": "user"}\n')
    fresh = TestClient(server.app)                          # a new process, same volume
    assert fresh.post("/hydrate?identifier=s1&probe=fresh", content=b"").json()["skipped"] is True
    assert (ws / "step0.txt").read_text() == "written by the cut turn"
    assert conv.is_file()


def test_the_fresh_probe_claims_nothing_without_a_fresh_marker(runner, tmp_path):
    # never started here: no marker file, so no claim
    assert runner.post("/hydrate?identifier=s9&probe=fresh", content=b"").json()["skipped"] is False
    # restored from a checkpoint: the marker names it, so the fresh start is not what the folder holds
    body, sha = _checkpoint()
    runner.post("/hydrate?identifier=s2", content=body)
    assert runner.post("/hydrate?identifier=s2&probe=fresh", content=b"").json()["skipped"] is False
    assert runner.post(f"/hydrate?identifier=s2&probe={sha}", content=b"").json()["skipped"] is True


def test_a_fresh_marker_over_an_emptied_folder_claims_nothing(runner, tmp_path):
    runner.post("/hydrate?identifier=s1", content=b"")
    import shutil
    shutil.rmtree(tmp_path / "ws" / "s1" / ".git")          # the folder holds nothing a start made
    assert runner.post("/hydrate?identifier=s1&probe=fresh", content=b"").json()["skipped"] is False
    assert not server._ws_marker_path("s1").exists()


@pytest.mark.parametrize("asked", ["", "_default", "s 1", "s/1", "s:1", " s_1", "s_1 ", "x" * 121])
def test_the_fresh_probe_is_never_answered_for_an_identifier_that_is_not_one_folder(runner, tmp_path, asked):
    """`fresh` claims a folder on the marker's name alone. An identifier that is empty, the fallback
    `_default`, or one that sanitising would fold onto another session's name, could hand one session
    another's workspace, so it is never answered held, even when the folder it maps to started fresh."""
    target = server._SID_SAFE.sub("_", asked.strip())[:120] or "_default"
    runner.post(f"/hydrate?identifier={target}", content=b"")         # that folder started fresh
    (tmp_path / "ws" / target / "theirs.txt").write_text("another session's file")
    r = runner.post("/hydrate", params={"identifier": asked, "probe": "fresh"}, content=b"")
    assert r.json()["skipped"] is False
    assert (tmp_path / "ws" / target / "theirs.txt").is_file()        # the probe itself touched nothing


def test_an_identifier_that_is_its_own_folder_is_answered(runner, tmp_path):
    runner.post("/hydrate?identifier=hsess0123abcd", content=b"")
    assert runner.post("/hydrate?identifier=hsess0123abcd&probe=fresh", content=b"").json()["skipped"] is True
