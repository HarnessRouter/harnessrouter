"""An edit to a harness's instructions reaches a task that is continued.

The gateway sends the harness's current instructions with every turn and the runner rewrites the
base's instruction file from them, but a base that resumes its own conversation may keep the copy it
read when the conversation began. Measured on the released image with a recording stand-in model
(scripts/continued-instructions-check.py): the continued turns of Hermes, Kimi Code, Grok Build, MiMo
Code, dcode, OpenHands and fast-agent sent the first turn's instructions and not the edited ones.
Claude Code, Codex and dsh add the edited file after the old one with a note that it replaces it;
pi, opencode and most others rebuild their prompt every turn. (Qoder, whose session keeps the system
prompt of the Agent version it was made with, is held to the same in test_qoder_backend.py.)

The runner now knows when the file changed since the last turn, and a base that pins its first copy
is told: Hermes and fast-agent through their own "build it again" (the stored prompt let go), the
others with the current file ahead of the message, said to replace the stale copy. The conversation
itself is untouched."""
import json
import pathlib
import sqlite3
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import openhands_driver  # noqa: E402
import server  # noqa: E402


# ── the runner knows when the instructions changed ───────────────────────────────────────────
def test_the_doc_writer_says_when_the_instructions_changed(tmp_path):
    ws = str(tmp_path)
    assert server._write_agent_doc(ws, "hermes", "Rule A.", []) is True, "a first write is a change"
    assert server._write_agent_doc(ws, "hermes", "Rule A.", []) is False, "the same doc again is not"
    assert server._write_agent_doc(ws, "hermes", "Rule B.", []) is True
    assert "Rule B." in server._read_agent_doc(ws, "hermes")
    # a base that reads no workspace has no file to change
    assert server._write_agent_doc(ws, "systemone", "Rule C.", []) is False


# ── Hermes: a NULL stored prompt is its own signal to build the prompt again ─────────────────
def _hermes_db(path: pathlib.Path, sid: str, prompt: str) -> None:
    """The two tables of Hermes's state.db this touches, in its own column names (hermes_state.py)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, model TEXT, system_prompt TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    db.execute("INSERT OR REPLACE INTO sessions (id, model, system_prompt) VALUES (?, ?, ?)", (sid, "m", prompt))
    db.execute("INSERT INTO messages (session_id, role, content) VALUES (?, 'user', 'first message')", (sid,))
    db.commit()
    db.close()


def _hermes_row(path: pathlib.Path, sid: str) -> tuple:
    db = sqlite3.connect(path)
    try:
        prompt = db.execute("SELECT system_prompt FROM sessions WHERE id=?", (sid,)).fetchone()[0]
        n = db.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,)).fetchone()[0]
        return prompt, n
    finally:
        db.close()


def test_hermes_forgets_only_the_stored_prompt(tmp_path):
    db = tmp_path / "state.db"
    _hermes_db(db, "s1", "built with Rule A.")
    _hermes_db(db, "s2", "another session's prompt")
    assert server._hermes_forget_system_prompt(str(db), "s1") is True
    assert _hermes_row(db, "s1") == (None, 1), "the prompt goes, the conversation stays"
    assert _hermes_row(db, "s2")[0] == "another session's prompt"
    assert server._hermes_forget_system_prompt(str(db), "s1") is False, "nothing left to clear"
    assert server._hermes_forget_system_prompt(str(tmp_path / "absent.db"), "s1") is False


@pytest.fixture
def turn(tmp_path, monkeypatch):
    """Start turns of a base in one session; nothing runs, and each built command is kept."""
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    monkeypatch.setattr(server, "_run_hermes_bg", lambda *a, **k: None)
    monkeypatch.setattr(server, "_run_turn_bg", lambda *a, **k: None)
    built: list = []

    def keep(name):
        real = getattr(server, name)

        def wrapped(*a, **k):
            cmd = real(*a, **k)
            built.append(cmd)
            return cmd
        monkeypatch.setattr(server, name, wrapped)
    for name in ("_build_kimi", "_build_grok", "_build_mimo", "_build_dcode", "_build_openhands", "_build_fast_agent"):
        keep(name)
    ws = tmp_path / "ws"

    def start(backend: str, doc: str, resume: str | None = None, prompt: str = "next message"):
        req = server.TurnReq(backend=backend, provider="openai-api", model="m", prompt=prompt, cwd=str(ws),
                             auth=server.Auth(api_key="k", base_url="https://api.example/v1"),
                             agent_doc=doc, resume_session_id=resume)
        built.clear()
        server._start_turn(req, "sess-1")
        return built[-1] if built else None
    start.ws = ws
    return start


def test_a_continued_hermes_turn_after_an_edit_builds_its_prompt_again(turn):
    turn("hermes", "Rule A.")
    db = turn.ws / ".harness" / "home" / ".hermes" / "state.db"
    _hermes_db(db, "hs1", "system prompt built with Rule A.")
    turn("hermes", "Rule A.", resume="hs1")
    assert _hermes_row(db, "hs1") == ("system prompt built with Rule A.", 1), \
        "unchanged instructions keep the stored prompt (and the provider's cache)"
    turn("hermes", "Rule B.", resume="hs1")
    assert _hermes_row(db, "hs1") == (None, 1), "edited instructions: Hermes builds the prompt again, from Rule B."


# ── Kimi Code: the session's bound prompt stays; the edit comes with the message ─────────────
def _kimi_session(ws: pathlib.Path, sid: str) -> None:
    (server._kimi_home(ws) / "sessions" / "wd_ws_0" / sid).mkdir(parents=True, exist_ok=True)


def test_a_continued_kimi_turn_after_an_edit_carries_the_edit_ahead_of_its_message(turn):
    turn("kimi", "Rule A.")
    _kimi_session(turn.ws, "ks1")
    cmd = turn("kimi", "Rule A.", resume="ks1")
    assert cmd[cmd.index("-p") + 1] == "next message", "unchanged instructions add nothing"
    cmd = turn("kimi", "Rule B.", resume="ks1")
    prompt = cmd[cmd.index("-p") + 1]
    assert cmd[cmd.index("-r") + 1] == "ks1", "still the same conversation"
    assert prompt.endswith("next message") and "Rule B." in prompt and "Rule A." not in prompt
    assert prompt.index("replace") < prompt.index("Rule B."), "said to replace the stale copy, before it"


def test_a_kimi_turn_that_starts_a_conversation_gets_no_note(turn):
    turn("kimi", "Rule A.")
    cmd = turn("kimi", "Rule B.", resume="not-in-the-store")
    assert "-r" not in cmd and cmd[cmd.index("-p") + 1] == "next message", \
        "a new conversation reads the current file itself"


def test_a_note_too_long_for_one_argument_names_the_file_instead():
    big = "x" * (server._NOTE_INLINE_MAX + 1)
    note = server._instructions_changed_note("AGENTS.md", big, "/w/AGENTS.md")
    assert big not in note and "/w/AGENTS.md" in note and "stale" in note


# ── the other bases that keep their first copy: the current file ahead of the message ────────
def test_a_continued_grok_turn_after_an_edit_carries_the_edit(turn):
    turn("grok", "Rule A.")
    sid = str(uuid.uuid4())
    d = server._grok_home(turn.ws) / "sessions" / "%2Fws" / sid
    d.mkdir(parents=True)
    (d / "summary.json").write_text("{}")
    cmd = turn("grok", "Rule A.", resume=sid)
    assert cmd[1] == "--single=next message"
    cmd = turn("grok", "Rule B.", resume=sid)
    assert cmd[cmd.index("-r") + 1] == sid
    single = cmd[1]
    assert single.startswith("--single=<system-reminder>") and single.endswith("next message")
    assert "Rule B." in single and "Rule A." not in single


def test_a_continued_mimo_turn_after_an_edit_carries_the_edit(turn, monkeypatch):
    monkeypatch.setattr(server, "_opencode_has_session", lambda env, sid, share="": sid == "ses_1")
    turn("mimo", "Rule A.")
    assert turn("mimo", "Rule A.", resume="ses_1")[-1] == "next message"
    cmd = turn("mimo", "Rule B.", resume="ses_1")
    assert cmd[cmd.index("-s") + 1] == "ses_1"
    assert cmd[-1].endswith("next message") and "Rule B." in cmd[-1] and "Rule A." not in cmd[-1]
    cmd = turn("mimo", "Rule C.", resume="ses_gone")
    assert cmd[-1] == "next message", "a session the store does not hold starts fresh and reads the file"


def test_a_continued_dcode_turn_after_an_edit_carries_the_edit(turn, monkeypatch):
    monkeypatch.setattr(server, "_dcode_session_present", lambda cwd, cmd, sid: sid == "t1")
    jobs: list = []
    real = server._driver_cmd
    monkeypatch.setattr(server, "_driver_cmd", lambda py, drv, job, env: jobs.append(job) or real(py, drv, job, env))
    turn("dcode", "Rule A.")
    turn("dcode", "Rule A.", resume="t1")
    assert jobs[-1]["prompt"] == "next message" and jobs[-1]["resume_known"] is True
    turn("dcode", "Rule B.", resume="t1")
    assert jobs[-1]["prompt"].endswith("next message") and "Rule B." in jobs[-1]["prompt"]
    assert "Rule A." not in jobs[-1]["prompt"]


def test_a_continued_openhands_turn_after_an_edit_carries_the_edit_when_the_server_resumes_it(turn, monkeypatch):
    jobs: list = []
    real = server._driver_cmd
    monkeypatch.setattr(server, "_driver_cmd", lambda py, drv, job, env: jobs.append(job) or real(py, drv, job, env))
    turn("openhands", "Rule A.")
    turn("openhands", "Rule A.", resume="harness")
    assert "instructions_changed" not in jobs[-1]
    turn("openhands", "Rule B.", resume="harness")
    note = jobs[-1]["instructions_changed"]
    assert "Rule B." in note and "replace" in note and "Rule A." not in note
    # only the driver knows whether the agent-server holds the conversation: the note goes with a
    # resumed one, and a new conversation loads the current file itself
    assert openhands_driver._turn_prompt(jobs[-1], resumed=True) == note + "next message"
    assert openhands_driver._turn_prompt(jobs[-1], resumed=False) == "next message"


# ── fast-agent: an absent stored prompt is its own "nothing to restore" ──────────────────────
def _fa_session(ws: pathlib.Path, sid: str, prompt: str) -> pathlib.Path:
    path = server._fast_agent_session_file(str(ws), sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"continuation": {"agents": {"AGENTS": {
        "history_file": "history.json", "resolved_prompt": prompt, "model": "m", "model_spec": "generic.m"}}}}))
    return path


def test_fast_agent_lets_go_of_only_the_stored_prompt(tmp_path):
    path = _fa_session(tmp_path, "s1", "Rule A.")
    assert server._fast_agent_forget_prompt(str(tmp_path), "s1") is True
    spec = json.loads(path.read_text())["continuation"]["agents"]["AGENTS"]
    assert spec == {"history_file": "history.json", "resolved_prompt": None, "model": "m", "model_spec": "generic.m"}
    assert server._fast_agent_forget_prompt(str(tmp_path), "s1") is False
    assert server._fast_agent_forget_prompt(str(tmp_path), "absent") is False


def test_a_continued_fast_agent_turn_after_an_edit_takes_the_current_file(turn, monkeypatch):
    monkeypatch.setattr(server, "_fast_agent_session_present", lambda cwd, cmd, sid: sid == "s1")
    turn("fast-agent", "Rule A.")
    path = _fa_session(turn.ws, "s1", "Rule A.")
    turn("fast-agent", "Rule A.", resume="s1")
    assert json.loads(path.read_text())["continuation"]["agents"]["AGENTS"]["resolved_prompt"] == "Rule A."
    turn("fast-agent", "Rule B.", resume="s1")
    assert json.loads(path.read_text())["continuation"]["agents"]["AGENTS"]["resolved_prompt"] is None


def test_the_bases_that_keep_their_first_copy_are_named():
    """Each one measured keeping it; a base that rebuilds its prompt every turn is not sent a note."""
    assert server._PINNED_INSTRUCTIONS == {"kimi", "grok", "mimo", "dcode", "openhands"}
