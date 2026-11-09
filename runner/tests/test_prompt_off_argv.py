"""The prompt is handed over by file or stdin, not on the command line.

A process's command line is what `ps` lists (/proc/<pid>/cmdline). Each builder below writes
the turn's prompt to a file of the session's own (0600, in a 0700 folder in its tmp/) and the CLI reads it on
stdin, or from the file's path in its argv, or through prompt_launcher.py. These tests read what each builder
returns: the prompt's words appear nowhere in the argv, and the CLI is handed them. test_root_writes_stay_in_the_session.py starts the
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
import handed  # noqa: E402

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
    prefix = os.path.join(d, "tmp", server.PROMPT_DIR, "prompt-")
    files = [pathlib.Path(a.split("=", 1)[1] if a.startswith("--") else a) for a in cmd
             if a.startswith(prefix) or (a.startswith("--") and "=" + prefix in a)]
    assert len(files) == 1, cmd
    return files[0]


STDIN = ["claude", "codex", "pi", "omp", "qwen", "gemini", "opencode", "mimo", "kilo", "minimax", "docker-agent"]
PIPE = ["cline"]
BY_PATH = ["grok", "goose", "vibe", "opensquilla"]


def _folder_is_private(d: str) -> None:
    folder = pathlib.Path(d, "tmp", server.PROMPT_DIR)
    assert folder.is_dir() and not folder.is_symlink() and stat.S_IMODE(folder.stat().st_mode) == 0o700


@pytest.mark.parametrize("backend", STDIN)
def test_the_prompt_goes_on_stdin_and_nothing_of_it_stays_on_disk(backend):
    cmd, held, d = _build(backend)
    assert not any(MARK in a for a in cmd), cmd
    assert held.get("stdin") is True and held.get("fd") is not None
    p = pathlib.Path(held["path"])
    assert p.parent == pathlib.Path(d, "tmp", server.PROMPT_DIR)
    assert not p.exists(), "removed before the CLI starts: the CLI reads the open descriptor"
    assert stat.S_IMODE(os.fstat(held["fd"]).st_mode) == 0o600
    _folder_is_private(d)
    assert os.read(held["fd"], 1 << 16).decode() == MARK          # what the CLI reads, from the start
    server._prompt_discard(held)
    assert held.get("fd") is None and held.get("dfd") is None


@pytest.mark.parametrize("backend", PIPE)
def test_the_prompt_goes_through_a_pipe_and_no_file_is_made(backend):
    cmd, held, d = _build(backend)
    assert not any(MARK in a for a in cmd), cmd
    assert held.get("stdin") is True and held.get("path") == ""
    assert stat.S_ISFIFO(os.fstat(held["fd"]).st_mode)
    assert handed.text(held) == MARK                                 # all of it, then the end
    assert not pathlib.Path(d, "tmp", server.PROMPT_DIR).exists() or not list(pathlib.Path(d, "tmp", server.PROMPT_DIR).iterdir())
    server._prompt_discard(held)
    assert held.get("fd") is None


def test_a_prompt_longer_than_a_pipe_holds_goes_whole():
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    big = "x" * (1 << 20) + MARK
    try:
        server._prompt_handover(tempfile.mkdtemp(), big, stdin="pipe")
    finally:
        server._TURN_PROMPT.reset(tok)
    assert handed.text(held) == big
    server._prompt_discard(held)


def test_a_pipe_nobody_reads_lets_its_writer_go(tmp_path):
    import threading
    import time
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        server._prompt_handover(str(tmp_path), "y" * (1 << 20), stdin="pipe")
    finally:
        server._TURN_PROMPT.reset(tok)
    server._prompt_discard(held)                                      # the turn never started
    for _ in range(40):
        if not [t for t in threading.enumerate() if t.name == "prompt-pipe"]:
            break
        time.sleep(0.05)
    assert not [t for t in threading.enumerate() if t.name == "prompt-pipe"]


@pytest.mark.parametrize("backend", BY_PATH)
def test_the_prompt_goes_by_file(backend):
    """The file waits for the CLI: nothing the build did counts as its read. The test's own read below is the
    one the CLI would make, so on Linux the file is gone right after it (_prompt_watch); everything else about
    the file is looked at first, without reading it."""
    import time
    cmd, held, d = _build(backend)
    assert not any(MARK in a for a in cmd), cmd
    p = _file_named_in(cmd, d)
    time.sleep(0.6)
    assert p.exists(), "removed before anything read it"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    _folder_is_private(d)
    assert held.get("stdin") is False and str(p) == held["path"] and held.get("fd") is None
    assert p.read_text() == MARK                                      # the CLI's read
    if server._LIBC is not None:
        for _ in range(40):
            if not p.exists():
                break
            time.sleep(0.05)
        assert not p.exists(), "read, closed, and still there"
    server._prompt_discard(held)
    assert not p.exists()


def test_the_flags_each_cli_reads_the_file_with():
    flags = {"grok": lambda c, p: f"--prompt-file={p}" in c,
             "goose": lambda c, p: c[c.index("-i") + 1] == p,
             "vibe": lambda c, p: c[c.index("--prompt-file") + 1] == p,
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
    text = handed.text(held)
    assert "EDITED RULES 55e1" in text and text.endswith(MARK), "the note leads the prompt, off the command line"
    server._prompt_discard(held)


def test_only_kimi_and_jcode_still_take_the_prompt_on_the_command_line():
    """kimi (a Node single executable whose -p takes only an argument, and nothing reads stdin) and jcode (`run`
    takes only <MESSAGE>) have no other way in short of their ACP servers; the rest hand it over off argv."""
    still = {b for b in ("kimi", "jcode") if any(MARK in a for a in _build(b)[0])}
    assert still == {"kimi", "jcode"}


def test_the_prompt_file_is_made_fresh_each_time(tmp_path):
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
    assert not pathlib.Path(path).exists() and held.get("fd") is None and held.get("dfd") is None


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
    assert not prompt.exists(), "the launcher removes the file once it has read it"


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


def test_the_folder_is_made_0700_and_one_left_wider_is_narrowed(tmp_path):
    (tmp_path / "tmp" / server.PROMPT_DIR).mkdir(parents=True, mode=0o755)
    os.chmod(tmp_path / "tmp" / server.PROMPT_DIR, 0o755)
    server._prompt_handover(str(tmp_path), "x")
    _folder_is_private(str(tmp_path))


def test_a_link_at_the_folders_name_is_refused_in_the_sessions_own_terms(tmp_path):
    """Named by its place in the session's tree, so the turn is refused in words (_session_tree_refused)."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    ws = tmp_path / "ws"
    (ws / "tmp").mkdir(parents=True)
    (ws / "tmp" / server.PROMPT_DIR).symlink_to(elsewhere)
    with pytest.raises(OSError) as e:
        server._prompt_handover(str(ws), MARK)
    assert server._session_tree_refused(e.value, str(ws)), e.value
    assert list(elsewhere.iterdir()) == []


def test_a_file_whose_turn_never_started_is_removed(tmp_path):
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        path = server._prompt_handover(str(tmp_path), MARK)
    finally:
        server._TURN_PROMPT.reset(tok)
    assert pathlib.Path(path).exists()
    server._prompt_discard(held)
    assert not pathlib.Path(path).exists()


@pytest.mark.skipif(server._LIBC is None, reason="inotify is Linux's")
def test_a_file_read_by_its_path_goes_once_the_cli_has_read_it(tmp_path):
    import time
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        path = server._prompt_handover(str(tmp_path), MARK)
    finally:
        server._TURN_PROMPT.reset(tok)
    os.stat(path)                                    # a look without a read leaves it
    with open(path, "rb"):
        pass                                         # an open and close without a read leaves it
    time.sleep(0.6)
    assert pathlib.Path(path).exists()
    with open(path) as fh:
        assert fh.read() == MARK                     # read and closed: gone
    for _ in range(40):
        if not pathlib.Path(path).exists():
            break
        time.sleep(0.05)
    assert not pathlib.Path(path).exists()
    server._prompt_discard(held)


def test_the_stdin_flags_each_cli_needs():
    """minimax's exec reads stdin only under `--input -`; cline's --json wants an argument before it reads
    stdin, so it gets one space, which carries nothing of the task; docker-agent's message comes from stdin
    when it has no message argument, and --prompt-file (an instruction file, not a message) is not used."""
    cmd, held, _ = _build("minimax")
    assert cmd[-2:] == ["--input", "-"]
    server._prompt_discard(held)
    cmd, held, _ = _build("cline")
    assert cmd[1] == server.CLINE_STDIN_ARG == " " and not cmd[1].strip()
    server._prompt_discard(held)
    cmd, held, _ = _build("docker-agent")
    assert "--prompt-file" not in cmd and cmd[-1].endswith("/agent.yaml")    # the agent file, then no message
    server._prompt_discard(held)
