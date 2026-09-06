"""A finished turn holds no process handle and no pipe; finished records are evicted after the cap."""
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def test_release_closes_every_pipe_and_drops_the_handle():
    proc = subprocess.Popen([sys.executable, "-c", "print('x')"], text=True, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.wait()
    rec = {"proc": proc}
    server._release_proc(rec, proc)
    assert "proc" not in rec
    assert proc.stdin.closed and proc.stdout.closed and proc.stderr.closed


def test_a_stream_json_turn_leaves_no_handle_behind(tmp_path, monkeypatch):
    rec = {"status": "running", "events": [], "result": "", "done": False, "started": time.time()}
    monkeypatch.setitem(server._turns, "t1", rec)
    monkeypatch.setattr(server, "_kill_capped", lambda proc, rec: None)
    def normalize(obj, state):
        return [{"type": "result", "result": obj.get("text", "")}]
    server._run_turn_bg("t1", [sys.executable, "-c", "print('{\"text\": \"ok\"}')"], {}, str(tmp_path), normalize, "m", 30)
    assert rec.get("done") is True
    assert "proc" not in rec, "the handle outlived the process"


def test_finished_records_are_evicted_after_the_cap_plus_grace(monkeypatch):
    now = time.time()
    monkeypatch.setitem(server._turns, "old", {"done": True, "started": now - server.MAX_TURN_SECONDS - server._TURN_RETENTION_S - 1})
    monkeypatch.setitem(server._turns, "fresh", {"done": True, "started": now - 10})
    monkeypatch.setitem(server._turns, "live", {"done": False, "started": now - server.MAX_TURN_SECONDS - server._TURN_RETENTION_S - 1})
    monkeypatch.setitem(server._turn_by_key, "k-old", "old")
    assert server._evict_turns(now) == 1
    assert "old" not in server._turns and "fresh" in server._turns and "live" in server._turns
    assert "k-old" not in server._turn_by_key
