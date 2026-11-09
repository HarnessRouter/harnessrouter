"""The prompt is handed over by file or stdin, not on the command line.

A process's command line is what `ps` lists (/proc/<pid>/cmdline). Each builder below writes
the turn's prompt to a file of the session's own (0600, in its tmp/) and the CLI reads it on stdin, or from the
file's path in its argv, or through prompt_launcher.py. These tests read what each builder returns: the prompt's
words appear nowhere in the argv, and the file holds them. test_root_writes_stay_in_the_session.py starts the
turns for real, as the session, and reads their command lines as another uid.
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

MARK = "the task's own words 7f3a91c2"
KEY = server.Auth(api_key="k-0123456789abcdef", base_url="https://up.example/v1")


def _build(backend: str, prompt: str = MARK, instructions: str | None = None, resume: str | None = None):
    """(argv, the turn's prompt record, cwd) for one turn of `backend`."""
    d = tempfile.mkdtemp()
    env: dict = {"HOME": os.path.join(d, ".harness", "home")}
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        if backend == "claude":
            cmd = server._build_claude("anthropic", server.Auth(api_key="k-0123456789abcdef"), "claude-sonnet-5.5",
                                       prompt, 5, d, env)
        elif backend == "codex":
            cmd, _ = server._build_codex("openai", KEY, "gpt-5.5", prompt, d, env)
        elif backend == "gemini":
            cmd = server._build_gemini("google", server.Auth(api_key="k-0123456789abcdef"), "gemini-3.8-flash", prompt, d, env)
        else:
            fn = getattr(server, f"_build_{backend.replace('-', '_')}")
            kw = {"instructions": instructions} if instructions is not None else {}
            if resume:
                kw["resume_session_id"] = resume
            cmd = fn("openai-api", KEY, server.BACKENDS[backend]["default_model"], prompt, d, env, **kw)
    finally:
        server._TURN_PROMPT.reset(tok)
    return [str(a) for a in cmd], held, d


def _file_named_in(cmd: list[str], d: str) -> pathlib.Path:
    prefix = os.path.join(d, "tmp", ".prompt-")
    files = [pathlib.Path(a.split("=", 1)[1] if a.startswith("--") else a) for a in cmd
             if a.startswith(prefix) or (a.startswith("--") and "=" + prefix in a)]
    assert len(files) == 1, cmd
    return files[0]


STDIN = ["claude", "codex", "pi", "omp", "qwen", "gemini", "cline", "opencode", "mimo", "kilo", "minimax"]
BY_PATH = ["grok", "goose", "vibe", "docker-agent", "opensquilla"]


@pytest.mark.parametrize("backend", STDIN)
def test_the_prompt_goes_on_stdin(backend):
    cmd, held, d = _build(backend)
    assert not any(MARK in a for a in cmd), cmd
    assert held.get("stdin") is True and held.get("fd") is not None
    p = pathlib.Path(held["path"])
    assert p.parent == pathlib.Path(d, "tmp") and p.read_text() == MARK
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert os.read(held["fd"], 1 << 16).decode() == MARK          # what the CLI reads, from the start
    server._prompt_discard(held)
    assert not p.exists()


@pytest.mark.parametrize("backend", BY_PATH)
def test_the_prompt_goes_by_file(backend):
    cmd, held, d = _build(backend)
    assert not any(MARK in a for a in cmd), cmd
    p = _file_named_in(cmd, d)
    assert p.read_text() == MARK and stat.S_IMODE(p.stat().st_mode) == 0o600
    assert held.get("stdin") is False and str(p) == held["path"]
    server._prompt_discard(held)
    assert not p.exists()


def test_the_flags_each_cli_reads_the_file_with():
    flags = {"grok": lambda c, p: f"--prompt-file={p}" in c,
             "goose": lambda c, p: c[c.index("-i") + 1] == p,
             "vibe": lambda c, p: c[c.index("--prompt-file") + 1] == p,
             "docker-agent": lambda c, p: c[c.index("--prompt-file") + 1] == p,
             "opensquilla": lambda c, p: c[1:5] == [server.PROMPT_LAUNCHER, p, "opensquilla.cli.main:app",
                                                    server.OPENSQUILLA_BIN] and server.PROMPT_ARG in c}
    for backend, ok in flags.items():
        cmd, held, d = _build(backend)
        assert ok(cmd, str(_file_named_in(cmd, d))), (backend, cmd)
        server._prompt_discard(held)


@pytest.mark.parametrize("backend", ["kimi", "grok", "mimo"])
def test_the_changed_instructions_travel_with_the_prompt(backend, monkeypatch):
    """Where an edit to the instructions is handed over with the message (_PINNED_INSTRUCTIONS), it goes the
    prompt's way. kimi still takes both on its command line: its CLI has no other way in (see below)."""
    probe = {"mimo": "_opencode_has_session"}.get(backend, f"_{backend}_has_session")
    monkeypatch.setattr(server, probe, lambda *a, **k: True)
    cmd, held, d = _build(backend, instructions="EDITED RULES 55e1", resume="hsess-continued")
    if backend == "kimi":
        assert any("EDITED RULES 55e1" in a for a in cmd)
        return
    assert not any("EDITED RULES 55e1" in a or MARK in a for a in cmd), cmd
    text = pathlib.Path(held["path"]).read_text()
    assert "EDITED RULES 55e1" in text and text.endswith(MARK), "the note leads the prompt, in the file"
    server._prompt_discard(held)


def test_only_kimi_and_jcode_still_take_the_prompt_on_the_command_line():
    """kimi (a Node single executable whose -p takes only an argument, and nothing reads stdin) and jcode (`run`
    takes only <MESSAGE>) have no other way in short of their ACP servers; the rest hand it over off argv."""
    still = {b for b in ("kimi", "jcode") if any(MARK in a for a in _build(b)[0])}
    assert still == {"kimi", "jcode"}


def test_the_prompt_file_is_made_fresh_and_never_through_a_planted_name(tmp_path):
    (tmp_path / "tmp").mkdir()
    tok = server._TURN_PROMPT.set(None)        # builders called on their own: each file stays
    try:
        a = server._prompt_handover(str(tmp_path), "one")
        b = server._prompt_handover(str(tmp_path), "two")
    finally:
        server._TURN_PROMPT.reset(tok)
    assert a != b and pathlib.Path(a).read_text() == "one" and pathlib.Path(b).read_text() == "two"


def test_a_turn_reads_its_prompt_on_stdin_and_the_file_goes_with_the_turn(tmp_path, monkeypatch):
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        path = server._prompt_handover(str(tmp_path), MARK, stdin=True)
    finally:
        server._TURN_PROMPT.reset(tok)
    seen = {}
    real = subprocess.Popen

    def popen(cmd, **kw):
        seen["stdin"] = os.read(kw["stdin"], 1 << 16).decode() if isinstance(kw.get("stdin"), int) else kw.get("stdin")
        return real(["true"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    monkeypatch.setattr(server.subprocess, "Popen", popen)
    server._turns["t-stdin"] = {"status": "running", "events": [], "result": "", "done": False, "backend": "claude",
                                "model": "m", "started": 0}
    server._run_turn_bg("t-stdin", ["claude", "-p"], dict(os.environ), str(tmp_path), server._claude_passthrough, "m",
                        prompt_io=held)
    assert seen["stdin"] == MARK
    assert not pathlib.Path(path).exists() and held.get("fd") is None


def test_a_turn_without_a_prompt_file_still_reads_nothing(tmp_path, monkeypatch):
    seen = {}
    real = subprocess.Popen

    def popen(cmd, **kw):
        seen["stdin"] = kw.get("stdin")
        return real(["true"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    monkeypatch.setattr(server.subprocess, "Popen", popen)
    server._turns["t-none"] = {"status": "running", "events": [], "result": "", "done": False, "backend": "kimi",
                               "model": "m", "started": 0}
    server._run_turn_bg("t-none", ["kimi"], dict(os.environ), str(tmp_path), server._claude_passthrough, "m")
    assert seen["stdin"] == subprocess.DEVNULL


def test_hermes_is_started_through_the_launcher_and_its_file_goes_with_the_turn(tmp_path, monkeypatch):
    seen = {}
    real = subprocess.Popen

    def popen(cmd, **kw):
        seen["cmd"] = list(cmd)
        seen["file"] = pathlib.Path(cmd[2]).read_text()
        return real(["true"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    monkeypatch.setattr(server.subprocess, "Popen", popen)
    server._turns["t-hermes"] = {"status": "running", "events": [], "result": "", "done": False,
                                 "backend": "hermes", "model": "m", "started": 0}
    server._run_hermes_bg("t-hermes", str(tmp_path), {**os.environ, "HERMES_HOME": str(tmp_path)}, "m", "openai-api",
                          MARK, None, 5)
    cmd = seen["cmd"]
    assert not any(MARK in a for a in cmd)
    assert cmd[:2] == [server.HERMES_PYTHON, server.PROMPT_LAUNCHER] and cmd[3:6] == ["hermes_cli.main:main",
                                                                                      "hermes", "-z"]
    assert cmd[6] == server.PROMPT_ARG and seen["file"] == MARK
    assert not pathlib.Path(cmd[2]).exists()


def test_the_launcher_runs_the_entry_point_with_the_prompt_in_its_own_argv(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "fakecli.py").write_text("import json, sys\n"
                                    "def main():\n"
                                    "    print(json.dumps(sys.argv))\n"
                                    "    return 3\n")
    prompt = tmp_path / "p.txt"
    prompt.write_text(MARK + "\nsecond line")
    out = subprocess.run([sys.executable, server.PROMPT_LAUNCHER, str(prompt), "fakecli:main", "fakecli",
                          "-z", server.PROMPT_ARG, "--model", "m"],
                         env={**os.environ, "PYTHONPATH": str(pkg)}, capture_output=True, text=True, timeout=60)
    assert out.returncode == 3, out.stderr
    assert json.loads(out.stdout) == ["fakecli", "-z", MARK + "\nsecond line", "--model", "m"]


def test_the_launcher_imports_nothing_from_the_folder_it_lives_in(tmp_path):
    """Its folder is the runner's: a module there named like one the CLI imports must not be the one it gets."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "fakecli.py").write_text("import sys\ndef main():\n    import server  # noqa\n    return 0\n")
    prompt = tmp_path / "p.txt"
    prompt.write_text("x")
    out = subprocess.run([sys.executable, server.PROMPT_LAUNCHER, str(prompt), "fakecli:main", "fakecli"],
                         env={**os.environ, "PYTHONPATH": str(pkg)}, capture_output=True, text=True, timeout=60)
    assert out.returncode != 0 and "No module named 'server'" in out.stderr
