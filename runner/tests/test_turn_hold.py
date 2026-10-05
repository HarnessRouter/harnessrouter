"""GET /turn/{id}?wait= holds its answer until the turn has something new.

The gateway asked for a turn's events every 1.2 s, which put up to that long before a turn's first
text and again before its end (measured on the hosted service, 2026-10-05). A held answer comes when
there is an event past `since`, when the turn is done, or when `wait` has passed, and says `held` so
a caller can tell this runner from one that ignores the parameter.
"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402
from server import _hermes_error_text  # noqa: E402


def get_turn(*a, **kw) -> dict:
    return asyncio.run(server.get_turn(*a, **kw))


def _turn(tid: str) -> dict:
    rec = {"status": "running", "events": [], "result": "", "done": False, "backend": "pi",
           "model": "m", "started": time.time()}
    server._turns[tid] = rec
    return rec


def _later(delay: float, fn) -> None:
    threading.Timer(delay, fn).start()


def test_without_wait_the_answer_is_immediate_and_does_not_claim_to_be_held():
    _turn("t-plain")
    t0 = time.monotonic()
    out = get_turn("t-plain", since=0)
    assert time.monotonic() - t0 < 0.2 and "held" not in out and out["events"] == []


def test_a_held_answer_comes_when_an_event_arrives_not_when_the_wait_ends():
    rec = _turn("t-event")
    _later(0.2, lambda: rec["events"].append({"type": "assistant", "n": 1}))
    t0 = time.monotonic()
    out = get_turn("t-event", since=0, wait=5)
    took = time.monotonic() - t0
    assert 0.2 <= took < 1.0, took
    assert out["held"] is True and out["n_total"] == 1 and out["events"] == [{"type": "assistant", "n": 1}]


def test_events_that_follow_within_a_moment_travel_in_the_same_answer():
    rec = _turn("t-burst")
    _later(0.10, lambda: rec["events"].append({"n": 1}))
    _later(0.15, lambda: rec["events"].append({"n": 2}))
    _later(0.20, lambda: rec["events"].append({"n": 3}))
    out = get_turn("t-burst", since=0, wait=5)
    assert [e["n"] for e in out["events"]] == [1, 2, 3]


def test_the_end_of_a_turn_is_answered_at_once_with_no_lingering():
    rec = _turn("t-done")

    def finish():
        rec["events"].append({"type": "result"})
        rec["status"], rec["done"] = "done", True
    _later(0.2, finish)
    t0 = time.monotonic()
    out = get_turn("t-done", since=0, wait=5)
    assert time.monotonic() - t0 < 0.3 + server._TURN_HOLD_LINGER_S
    assert out["done"] is True and out["status"] == "done" and out["n_total"] == 1


def test_nothing_new_is_answered_when_the_wait_has_passed_and_only_events_past_since_count():
    rec = _turn("t-quiet")
    rec["events"].extend([{"n": 1}, {"n": 2}])
    t0 = time.monotonic()
    out = get_turn("t-quiet", since=2, wait=0.3)
    assert 0.3 <= time.monotonic() - t0 < 0.7
    assert out["held"] is True and out["events"] == [] and out["n_total"] == 2


def test_the_hold_is_capped(monkeypatch):
    _turn("t-cap")
    monkeypatch.setattr(server, "_TURN_HOLD_MAX_S", 0.2)
    t0 = time.monotonic()
    get_turn("t-cap", since=0, wait=3600)
    assert time.monotonic() - t0 < 0.6


def test_many_held_turns_wait_together_without_a_thread_each():
    """One runner serves every session of a self-hosted instance. A hold that slept on a worker
    thread would take one per running turn, and the pool that starts turns has forty."""
    for i in range(120):
        _turn(f"t-many-{i}")

    async def all_at_once():
        t0 = time.monotonic()
        outs = await asyncio.gather(*(server.get_turn(f"t-many-{i}", since=0, wait=0.4) for i in range(120)))
        return time.monotonic() - t0, outs

    took, outs = asyncio.run(all_at_once())
    assert took < 1.5, took                      # together, not forty at a time
    assert all(o["held"] is True and o["events"] == [] for o in outs)


def test_a_hermes_failure_is_not_explained_by_the_clis_closing_session_line():
    only_sid = ["session_id: 20261005_135032_0fb4fd\n"]
    text = _hermes_error_text(only_sid, 0, 277.4)
    assert "session_id" not in text and "without a final answer" in text
    assert "exit code 0" in text and "277 s" in text
    said = ["Error: provider returned 400: context length exceeded", "session_id: 20261005_135032_0fb4fd"]
    assert _hermes_error_text(said, 1, 3.0) == "Error: provider returned 400: context length exceeded"


def test_what_a_cli_rebuilds_for_itself_is_not_saved_with_the_workspace(tmp_path):
    """Saved with the workspace, these were most of what a turn's end waited for: omp's two native
    binaries were a 183 MB archive and 10 s after every turn (the hosted service, 2026-10-05)."""
    for p in ("./.harness/home/.omp/natives", "./.harness/home/.codex/.tmp", "./.harness/home/.cache/pkg"):
        assert p in server.CHECKPOINT_EXCLUDE
    # with the image's own tar (GNU; bsdtar reads an exclude pattern differently) the folders are
    # left out while their neighbours, the conversation state a resume needs, are kept
    import shutil
    import subprocess
    tar = next((t for t in ("gtar", "tar") if shutil.which(t)
                and b"GNU tar" in subprocess.run([t, "--version"], capture_output=True).stdout), None)
    if not tar:
        return
    for rel in (".harness/home/.omp/natives/18.1.13/pi_natives.node", ".harness/home/.omp/agent/agent.db",
                ".harness/home/.codex/.tmp/plugins/README.md", ".harness/home/.codex/sessions/a.jsonl",
                ".harness/home/.cache/pkg/abc/lib.so", ".harness/home/.cache/opencode/models.json", "notes.md"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    excl = [f"--exclude={p}" for p in server.CHECKPOINT_EXCLUDE]
    made = subprocess.run([tar, "-cf", "-", *excl, "-C", str(tmp_path), "."], capture_output=True, check=True)
    listed = subprocess.run([tar, "-tf", "-"], input=made.stdout, capture_output=True, check=True).stdout.decode()
    for gone in ("natives", ".codex/.tmp", ".cache/pkg"):
        assert gone not in listed, gone
    for kept in (".omp/agent/agent.db", ".codex/sessions/a.jsonl", ".cache/opencode/models.json", "notes.md"):
        assert kept in listed, kept


def test_the_cli_home_is_out_of_the_workspaces_own_history_so_the_tar_is_the_only_place(tmp_path):
    """On the hosted service the same binaries had a second copy in .git/objects, which the tar also
    carries. Here the whole CLI home has been ignored by the workspace's repository since #193."""
    import subprocess
    ws = str(tmp_path)
    for rel in (".harness/home/.omp/natives/18.1.13/pi_natives.node", ".harness/home/.cache/pkg/abc/lib.so", "notes.md"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    server._git_ensure(ws)
    subprocess.run(["git", "-C", ws, "add", "-A"], check=True, env={**os.environ, **server._GIT_ENV})
    tracked = subprocess.run(["git", "-C", ws, "ls-files"], capture_output=True, check=True).stdout.decode()
    assert "notes.md" in tracked and ".harness/home" not in tracked
