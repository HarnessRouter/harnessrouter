"""Hermes driver hang guards.

hermes-agent emits NO stdout event stream — the driver's only progress signal is what lands in
state.db. Three failure modes this pins:

1. A fresh turn whose subprocess blocks (e.g. an unbounded provider auth/model-init call) showed
   zero events, no error, indistinguishable from "still working," for up to the full per-turn cap
   (hours). _HERMES_STARTUP_TIMEOUT_S bounds just that startup window, independent of and much
   shorter than the overall turn timeout.
2. The guard must key on THE MODEL PRODUCING OUTPUT, not on a session row existing. hermes writes
   the session and echoes the user's prompt before it ever calls the provider, so a guard keyed on
   the session row disarms itself a fraction of a second in — which is how a hung glm-5.2 turn ran
   to the six-hour cap with the console showing "Working…" the whole time.
3. A resume whose target session isn't found in this sandbox silently fell back to a fresh start
   with only a server-log line — no signal in the turn's own event stream. A caller that believed
   this was a continuation had no way to detect the dropped context.
"""
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402


def _fake_popen_spawning(real_cmd: list[str]):
    """Replace rn.subprocess.Popen with one that ignores the requested argv and runs `real_cmd`
    instead, keeping only the kwargs _run_hermes_bg actually relies on (pipes, cwd, env, session)."""
    real_popen = subprocess.Popen
    keep = ("cwd", "env", "text", "bufsize", "stdout", "stderr", "start_new_session")

    def fake(cmd, **kw):
        return real_popen(real_cmd, **{k: v for k, v in kw.items() if k in keep})
    return fake


def _state_db(path: Path, started_at: float, rows: list[tuple[str, str]]) -> str:
    """A state.db shaped the way hermes writes one: a session plus its messages, in order."""
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL)")
    db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, "
               "role TEXT, content TEXT, tool_calls TEXT, tool_call_id TEXT)")
    db.execute("INSERT INTO sessions VALUES ('sess-1', ?)", (started_at,))
    for role, content in rows:
        db.execute("INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id) "
                   "VALUES ('sess-1', ?, ?, NULL, NULL)", (role, content))
    db.commit(); db.close()
    return str(path)


def _ro_opener(db_file: str):
    """Stand-in for _hermes_db_ro. row_factory matters: without it every row read raises inside
    the sweep's broad except and the guard sees no output at all — which would make these tests
    pass for the wrong reason."""
    def open_ro(_path):
        db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return db
    return open_ro


def test_startup_timeout_kills_a_hung_fresh_turn(monkeypatch, tmp_path):
    # No session row ever appears (simulates the CLI blocked before its first DB write).
    monkeypatch.setattr(rn, "_hermes_db_ro", lambda db_path: None)
    monkeypatch.setattr(rn, "_HERMES_STARTUP_TIMEOUT_S", 0.2)
    monkeypatch.setattr(rn, "_HERMES_POLL_S", 0.05)
    monkeypatch.setattr(rn, "MAX_TURN_SECONDS", 999)   # must NOT be what stops this turn
    monkeypatch.setattr(rn.subprocess, "Popen", _fake_popen_spawning(["sleep", "100"]))

    turn_id = "startup-hang"
    rn._turns[turn_id] = {"events": [], "done": False}
    env = {**os.environ, "HERMES_HOME": str(tmp_path)}

    t0 = time.time()
    rn._run_hermes_bg(turn_id, str(tmp_path), env, "gpt-5.4", "azure", "hi", None, None)
    elapsed = time.time() - t0

    rec = rn._turns[turn_id]
    assert elapsed < 5, "startup guard did not fire — turn ran to the full per-turn cap"
    assert rec["status"] == "timeout"
    assert rec.get("capped") is True
    assert "produced no output" in (rec.get("error") or "")


def test_startup_guard_survives_the_session_row_and_the_prompt_echo(monkeypatch, tmp_path):
    # The regression that motivated the guard's current shape: hermes HAS written its session row
    # and echoed the user's prompt, but the provider call behind it never returns. A guard keyed on
    # the session row would have disarmed here and let the turn run to the six-hour cap.
    started = time.time()
    db_file = _state_db(tmp_path / "echo.db", started, [("user", "hi")])
    monkeypatch.setattr(rn, "_hermes_db_ro", _ro_opener(db_file))
    monkeypatch.setattr(rn, "_HERMES_STARTUP_TIMEOUT_S", 0.3)
    monkeypatch.setattr(rn, "_HERMES_POLL_S", 0.05)
    monkeypatch.setattr(rn, "MAX_TURN_SECONDS", 999)
    monkeypatch.setattr(rn.subprocess, "Popen", _fake_popen_spawning(["sleep", "100"]))

    rn._turns["echo-only"] = {"events": [], "done": False}
    rn._run_hermes_bg("echo-only", str(tmp_path), {**os.environ, "HERMES_HOME": str(tmp_path)},
                      "gpt-5.4", "azure", "hi", None, None)

    rec = rn._turns["echo-only"]
    assert rec.get("capped") is True, "the prompt echo disarmed the guard — it must not count as output"
    assert rec["status"] == "timeout"


def test_startup_guard_disarms_once_the_model_produces_output(monkeypatch, tmp_path):
    # The other side of the same rule: real output means the turn is alive, and a tool call that
    # runs for minutes must never be killed. hermes writes the assistant message BEFORE executing
    # the call, so output exists by then.
    started = time.time()
    db_file = _state_db(tmp_path / "live.db", started, [("user", "hi"), ("assistant", "working on it")])
    monkeypatch.setattr(rn, "_hermes_db_ro", _ro_opener(db_file))
    monkeypatch.setattr(rn, "_HERMES_STARTUP_TIMEOUT_S", 0.3)
    monkeypatch.setattr(rn, "_HERMES_POLL_S", 0.05)
    monkeypatch.setattr(rn, "MAX_TURN_SECONDS", 999)
    # Outlives the startup window several times over, the way a long tool call does.
    monkeypatch.setattr(rn.subprocess, "Popen", _fake_popen_spawning(["sleep", "1.5"]))

    rn._turns["live"] = {"events": [], "done": False}
    rn._run_hermes_bg("live", str(tmp_path), {**os.environ, "HERMES_HOME": str(tmp_path)},
                      "gpt-5.4", "azure", "hi", None, None)

    rec = rn._turns["live"]
    assert not rec.get("capped"), "a turn that produced output was killed by the startup guard"
    assert rec["status"] == "done"


def test_resume_lost_emits_visible_event_not_just_a_log_line(monkeypatch, tmp_path):
    # The requested resume target is never found (_hermes_session_row -> None) — the driver must
    # emit a resume_lost event into the turn's OWN stream, not just print() to server logs.
    monkeypatch.setattr(rn, "_hermes_session_row", lambda db_path, sid: None)
    monkeypatch.setattr(rn, "_hermes_db_ro", lambda db_path: None)   # no session ever seen mid-run either
    monkeypatch.setattr(rn, "_HERMES_STARTUP_TIMEOUT_S", 10.0)       # must not race the fast fake process
    monkeypatch.setattr(rn, "_HERMES_POLL_S", 0.02)
    monkeypatch.setattr(rn.subprocess, "Popen", _fake_popen_spawning(["sh", "-c", "exit 0"]))

    turn_id = "resume-lost"
    rn._turns[turn_id] = {"events": [], "done": False}
    env = {**os.environ, "HERMES_HOME": str(tmp_path)}

    rn._run_hermes_bg(turn_id, str(tmp_path), env, "gpt-5.4", "azure", "hi", "prior-not-here", None)

    events = rn._turns[turn_id]["events"]
    assert any(e.get("type") == "system" and e.get("subtype") == "resume_lost"
               and e.get("requested_session_id") == "prior-not-here" for e in events), (
        "resume-lost was not signaled in the turn's event stream")
