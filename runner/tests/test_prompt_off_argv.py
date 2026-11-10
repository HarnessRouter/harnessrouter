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
import shutil
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
node = pytest.mark.skipif(not shutil.which("node"), reason="no node here")


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


STDIN = ["claude", "codex", "pi", "omp", "gemini", "opencode", "mimo", "kilo", "minimax", "docker-agent"]
PIPE = ["cline"]
BY_PATH = ["grok", "goose", "vibe", "opensquilla", "qwen"]


def _cli_reads(path, hold: float = 0.6) -> str:
    """The CLI's read: a process handed the file's path on its command line opens it, reads it, and holds it a
    moment, as a CLI does while it starts (the watcher knows the CLI's open by that: server._cli_holds)."""
    out = subprocess.run([sys.executable, "-c", "import sys, time\nf = open(sys.argv[1])\nd = f.read()\n"
                          f"time.sleep({hold})\nf.close()\nsys.stdout.write(d)", str(path)],
                         capture_output=True, text=True, timeout=30)
    return out.stdout


def _foreign_read(path, hold: float = 0.6) -> str:
    """A read by something the file was never handed to (a scan of the session's files, a checkpoint): the path
    comes on stdin, so it is in neither its command line nor its environment."""
    out = subprocess.run([sys.executable, "-c", "import sys, time\np = sys.stdin.read().strip()\nf = open(p)\n"
                          f"d = f.read()\ntime.sleep({hold})\nf.close()\nsys.stdout.write(d)"],
                         input=str(path), capture_output=True, text=True, timeout=30)
    return out.stdout


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
    assert not pathlib.Path(d, "tmp", server.PROMPT_DIR).exists(), "the folder made for it goes with it"
    assert MARK in os.read(held["fd"], 1 << 16).decode()          # what the CLI reads, from the start
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
    assert _cli_reads(p) == MARK                                      # the CLI's read
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
                                                    server.OPENSQUILLA_BIN] and server.PROMPT_ARG in c,
             "qwen": lambda c, p: c[:3] == ["node", server.PROMPT_LAUNCHER_JS, p]
                                  and c[c.index("-p") + 1] == server.PROMPT_ARG}
    for backend, ok in flags.items():
        cmd, held, d = _build(backend)
        assert ok(cmd, str(_file_named_in(cmd, d))), (backend, cmd)
        server._prompt_discard(held)


@pytest.mark.parametrize("backend", ["kimi", "grok", "mimo"])
def test_the_changed_instructions_travel_with_the_prompt(backend, monkeypatch):
    """Where an edit to the instructions is handed over with the message (_PINNED_INSTRUCTIONS), it goes the
    prompt's way."""
    probe = {"mimo": "_opencode_has_session"}.get(backend, f"_{backend}_has_session")
    monkeypatch.setattr(server, probe, lambda *a, **k: True)
    cmd, held, d = _build(backend, instructions="EDITED RULES 55e1", resume="hsess-continued")
    assert not any("EDITED RULES 55e1" in a or MARK in a for a in cmd), cmd
    text = handed.text(held)
    assert "EDITED RULES 55e1" in text and text.rstrip('"').endswith(MARK), "the note leads the prompt, off the command line"
    server._prompt_discard(held)


# ── kimi and jcode: one executable, the prompt only as an argument ─────────────────────────────────────
# Kimi Code is a Node single executable whose -p takes only an argument and which reads nothing on stdin; jcode's
# `run` takes only <MESSAGE>. Neither has an entry point a launcher could run in-process, so the argument is set
# inside the CLI's own process before its code reads it: by a Node preload for kimi (prompt_preload.cjs), by a
# library the dynamic loader runs first for jcode (prompt_argv.so). The command line holds only the placeholder.
def _env_of(backend: str, prompt: str = MARK):
    d = tempfile.mkdtemp()
    env: dict = {"HOME": os.path.join(d, ".harness", "home"), "PATH": os.environ.get("PATH", "")}
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        fn = getattr(server, f"_build_{backend}")
        cmd = fn("openai-api", KEY, server.BACKENDS[backend]["default_model"], prompt, d, env)
    finally:
        server._TURN_PROMPT.reset(tok)
    return [str(a) for a in cmd], env, held, d


def test_no_cli_takes_the_prompt_on_its_command_line_any_more():
    for backend in ("kimi", "jcode"):
        cmd, env, held, d = _env_of(backend)
        assert not any(MARK in a for a in cmd) and server.PROMPT_ARG in cmd, (backend, cmd)
        assert env["HR_PROMPT_FILE"] == held["path"]
        assert pathlib.Path(held["path"]).parent == pathlib.Path(d, "tmp", server.PROMPT_DIR)
        # looked at before it's read: reading it is what lets the runner take the file, and then its empty folder, away
        _folder_is_private(d)
        assert handed.text(held) == MARK, backend
        server._prompt_discard(held)
        assert not os.path.exists(env["HR_PROMPT_FILE"]), "the file goes with the turn"


def test_kimi_is_handed_its_prompt_by_the_node_preload():
    cmd, env, held, _ = _env_of("kimi")
    assert cmd[:3] == ["kimi", "-p", server.PROMPT_ARG]
    assert env["NODE_OPTIONS"] == f"--require {server.PROMPT_PRELOAD_CJS}"
    server._prompt_discard(held)


def test_jcode_is_handed_its_prompt_by_the_loader_library_in_jcode_itself(tmp_path, monkeypatch):
    """The Linux release is a launcher and `<launcher>.bin` (docker/entrypoint.sh, install_jcode): the binary is
    started directly, with its folder on LD_LIBRARY_PATH as the launcher would put it, so no shell in between holds
    the arguments; the library acts only in the binary HR_PROMPT_EXE names."""
    rel = tmp_path / "jcode"
    rel.mkdir()
    launcher, binary = rel / "jcode-linux-x86_64", rel / "jcode-linux-x86_64.bin"
    launcher.write_text("#!/bin/sh\nexec \"$0.bin\" \"$@\"\n")
    binary.write_text("")
    os.chmod(launcher, 0o755)
    os.chmod(binary, 0o755)
    on_path = tmp_path / "bin"
    on_path.mkdir()
    (on_path / "jcode").symlink_to(launcher)
    monkeypatch.setenv("PATH", f"{on_path}{os.pathsep}{os.environ.get('PATH', '')}")
    cmd, env, held, _ = _env_of("jcode", prompt="-a message that starts with a dash")
    assert cmd[0] == os.path.realpath(binary) and cmd[-4:] == ["run", "--ndjson", "--", server.PROMPT_ARG]
    assert env["LD_LIBRARY_PATH"].split(os.pathsep)[0] == os.path.dirname(os.path.realpath(binary))
    assert env["LD_PRELOAD"] == server.PROMPT_ARGV_SO and env["HR_PROMPT_EXE"] == os.path.realpath(binary)
    assert handed.text(held) == "-a message that starts with a dash"     # after `--`: still the message
    server._prompt_discard(held)


def test_jcode_is_refused_in_words_where_the_runner_has_no_library_to_hand_it_over(monkeypatch):
    """Never started with the placeholder as its message, and never with the prompt on its command line."""
    monkeypatch.setattr(server, "PROMPT_ARGV_SO", "/nonexistent/prompt_argv.so")
    with pytest.raises(server.HTTPException) as e:
        _env_of("jcode")
    assert "prompt_argv.so" in str(e.value.detail) and "process list" in str(e.value.detail)


@node
def test_the_preload_sets_the_argument_in_process_and_leaves_nothing_for_what_the_cli_starts(tmp_path):
    entry = tmp_path / "fakecli.js"
    entry.write_text("const { execFileSync } = require('node:child_process');\n"
                     "const child = execFileSync(process.execPath, ['-e', "
                     "'process.stdout.write(JSON.stringify([process.env.NODE_OPTIONS || null, process.env.HR_PROMPT_FILE || null]))']);\n"
                     "let cmdline = null;\n"
                     "try { cmdline = require('node:fs').readFileSync('/proc/self/cmdline', 'utf8'); } catch {}\n"
                     "process.stdout.write(JSON.stringify({argv: process.argv.slice(2), child: JSON.parse(child), cmdline}));\n")
    prompt = _private(tmp_path / "p.txt", MARK + "\nsecond line")
    env = {**os.environ, "NODE_OPTIONS": f"--require {server.PROMPT_PRELOAD_CJS}", "HR_PROMPT_FILE": str(prompt)}
    out = subprocess.run(["node", str(entry), "-p", server.PROMPT_ARG, "--output-format", "stream-json"],
                         env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["argv"] == ["-p", MARK + "\nsecond line", "--output-format", "stream-json"]
    assert got["child"] == [None, None], "what the CLI starts loads no preload and finds no prompt file"
    assert not prompt.exists(), "the preload removes the file once it has read it"
    if got["cmdline"] is not None:
        assert MARK not in got["cmdline"] and server.PROMPT_ARG in got["cmdline"]


@node
@pytest.mark.parametrize("case", ["no file", "no placeholder"])
def test_the_preload_stops_the_cli_rather_than_run_it_without_its_prompt(tmp_path, case):
    entry = tmp_path / "fakecli.js"
    entry.write_text("process.stdout.write('ran');\n")
    prompt = tmp_path / "p.txt"
    if case == "no placeholder":
        _private(prompt, MARK)
    env = {**os.environ, "NODE_OPTIONS": f"--require {server.PROMPT_PRELOAD_CJS}", "HR_PROMPT_FILE": str(prompt)}
    args = ["-p", server.PROMPT_ARG] if case == "no file" else ["-p", "something else"]
    out = subprocess.run(["node", str(entry), *args], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 2 and out.stdout == "", (out.stdout, out.stderr)


def _private(path: pathlib.Path, text: str) -> pathlib.Path:
    """A prompt file as _prompt_handover makes it: this process's own, 0600."""
    path.write_text(text)
    os.chmod(path, 0o600)
    return path


def _library(tmp_path) -> str:
    cc = shutil.which("cc") or shutil.which("gcc")
    if not sys.platform.startswith("linux") or not cc:
        pytest.skip("the library is a Linux one, built where a C compiler is (the image builds it)")
    so = tmp_path / "prompt_argv.so"
    built = subprocess.run([cc, "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(so),
                            str(pathlib.Path(server.__file__).with_name("prompt_argv.c"))], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return str(so)


_SHOW = ("import json, os, sys\n"
         "print(json.dumps({'argv': sys.argv[1:], 'cmdline': open('/proc/self/cmdline', 'rb').read().decode(errors='replace'),"
         " 'env': [os.environ.get(k) for k in ('LD_PRELOAD', 'HR_PROMPT_FILE', 'HR_PROMPT_EXE')]}))\n")


def test_the_library_sets_the_argument_in_the_named_binary_alone(tmp_path):
    so = _library(tmp_path)
    prompt = _private(tmp_path / "p.txt", MARK + "\nsecond line")
    py = os.path.realpath(sys.executable)
    env = {**os.environ, "LD_PRELOAD": so, "HR_PROMPT_FILE": str(prompt), "HR_PROMPT_EXE": py}
    out = subprocess.run([py, "-c", _SHOW, "run", "--", server.PROMPT_ARG], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["argv"] == ["run", "--", MARK + "\nsecond line"]
    assert MARK not in got["cmdline"] and server.PROMPT_ARG in got["cmdline"]
    assert got["env"] == [None, None, None], "nothing the binary starts loads the library or finds the file"
    assert not prompt.exists()
    # any other program (a launcher in between) passes the placeholder on as it is, and keeps the file
    _private(prompt, MARK)
    out = subprocess.run([py, "-c", _SHOW, "--", server.PROMPT_ARG], env={**env, "HR_PROMPT_EXE": "/usr/bin/elsewhere"},
                         capture_output=True, text=True, timeout=60)
    assert json.loads(out.stdout)["argv"] == ["--", server.PROMPT_ARG] and prompt.exists()


@pytest.mark.parametrize("case", ["no file", "no placeholder"])
def test_the_library_stops_the_binary_rather_than_run_it_without_its_prompt(tmp_path, case):
    so = _library(tmp_path)
    prompt = tmp_path / "p.txt"
    if case == "no placeholder":
        _private(prompt, MARK)
    py = os.path.realpath(sys.executable)
    env = {**os.environ, "LD_PRELOAD": so, "HR_PROMPT_FILE": str(prompt), "HR_PROMPT_EXE": py}
    args = ["--", server.PROMPT_ARG] if case == "no file" else ["--", "something else"]
    out = subprocess.run([py, "-c", "print('ran')", *args], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 2 and out.stdout == "" and "the prompt could not be handed over" in out.stderr


@node
def test_the_preload_refuses_a_prompt_file_others_could_read(tmp_path):
    """The session's own and private (0600, as _prompt_handover makes it): a 0644 file stops the CLI before it runs."""
    entry = tmp_path / "fakecli.js"
    entry.write_text("process.stdout.write('ran');\n")
    prompt = _private(tmp_path / "p.txt", MARK)
    os.chmod(prompt, 0o644)
    env = {**os.environ, "NODE_OPTIONS": f"--require {server.PROMPT_PRELOAD_CJS}", "HR_PROMPT_FILE": str(prompt)}
    out = subprocess.run(["node", str(entry), "-p", server.PROMPT_ARG], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 2 and out.stdout == "" and "own private file" in out.stderr, (out.stdout, out.stderr)
    assert prompt.exists(), "a file that is not the CLI's own private one is left where it is"


def test_the_library_refuses_a_prompt_file_others_could_read(tmp_path):
    so = _library(tmp_path)
    prompt = _private(tmp_path / "p.txt", MARK)
    os.chmod(prompt, 0o644)
    py = os.path.realpath(sys.executable)
    env = {**os.environ, "LD_PRELOAD": so, "HR_PROMPT_FILE": str(prompt), "HR_PROMPT_EXE": py}
    out = subprocess.run([py, "-c", "print('ran')", "--", server.PROMPT_ARG], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 2 and out.stdout == "" and "own private file" in out.stderr, (out.stdout, out.stderr)
    assert prompt.exists()


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
    assert _cli_reads(path) == MARK                  # read by the CLI and closed: gone
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


def test_a_tmp_folder_the_handover_made_goes_with_it_so_no_cli_lists_it(tmp_path):
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        server._prompt_handover(str(tmp_path), MARK, stdin=True)
    finally:
        server._TURN_PROMPT.reset(tok)
    assert os.listdir(tmp_path) == []
    server._prompt_discard(held)


def test_a_tmp_folder_the_session_had_stays_and_only_the_prompt_folder_goes(tmp_path):
    (tmp_path / "tmp" / "kept").mkdir(parents=True)
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        server._prompt_handover(str(tmp_path), MARK, stdin=True)
    finally:
        server._TURN_PROMPT.reset(tok)
    assert sorted(os.listdir(tmp_path / "tmp")) == ["kept"]
    server._prompt_discard(held)
    assert sorted(os.listdir(tmp_path / "tmp")) == ["kept"]


def test_what_each_cli_is_handed_is_the_message_it_stored_from_its_arguments():
    """Measured on recorded requests, 0.40.2 against this: opencode and mimo store the message from their
    arguments wrapped in quotes and stdin's as it is, so stdin gets the quoted form; Qwen Code stores plain
    stdin with a blank line after it, and its stream-json input changes its system prompt, so it is given
    -p in-process through prompt_launcher.mjs."""
    for backend in ("opencode", "mimo", "kilo"):
        cmd, held, _ = _build(backend, prompt='say "hi" twice')
        assert handed.text(held) == '"say \\"hi\\" twice"', backend
        server._prompt_discard(held)
        cmd, held, _ = _build(backend, prompt="one-word")
        assert handed.text(held) == "one-word", backend           # no space: as it is, as from arguments
        server._prompt_discard(held)
    cmd, held, _ = _build("kilo", prompt="-a dash first")
    assert handed.text(held) == "-a dash first"                    # after `--`, which kilo does not quote
    server._prompt_discard(held)
    cmd, held, _ = _build("opencode", prompt="-a dash first")
    assert handed.text(held) == '"-a dash first"'                  # opencode quotes after `--` too
    server._prompt_discard(held)
    env: dict = {}
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        cmd = server._build_qwen("openai-api", KEY, server.BACKENDS["qwen"]["default_model"], MARK, tempfile.mkdtemp(), env)
    finally:
        server._TURN_PROMPT.reset(tok)
    assert "--input-format" not in cmd and cmd[cmd.index("-p") + 1] == server.PROMPT_ARG
    assert handed.text(held) == MARK                                  # -p's text, exactly, in-process
    assert env["QWEN_CODE_NO_RELAUNCH"] == "1"                       # no child with that argv on its command line
    server._prompt_discard(held)




@node
def test_the_node_launcher_runs_the_entry_script_with_the_prompt_in_its_own_argv(tmp_path):
    entry = tmp_path / "fakecli.mjs"
    entry.write_text("process.stdout.write(JSON.stringify(process.argv.slice(1)));\n")
    prompt = tmp_path / "p.txt"
    prompt.write_text(MARK + "\nsecond line")
    out = subprocess.run(["node", server.PROMPT_LAUNCHER_JS, str(prompt), str(entry), "-p", server.PROMPT_ARG,
                          "-o", "stream-json"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [str(entry), "-p", MARK + "\nsecond line", "-o", "stream-json"]
    assert not prompt.exists(), "the launcher removes the file once it has read it"


@node
def test_the_node_launcher_names_the_file_and_never_its_text_on_its_command_line(tmp_path):
    entry = tmp_path / "fakecli.mjs"
    entry.write_text("import { readFileSync } from 'node:fs';\n"
                     "process.stdout.write(readFileSync('/proc/self/cmdline', 'utf8'));\n")
    prompt = tmp_path / "p.txt"
    prompt.write_text(MARK)
    if not os.path.exists("/proc/self/cmdline"):
        pytest.skip("no /proc here")
    out = subprocess.run(["node", server.PROMPT_LAUNCHER_JS, str(prompt), str(entry), "-p", server.PROMPT_ARG],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert MARK not in out.stdout and server.PROMPT_ARG in out.stdout


@pytest.mark.skipif(server._LIBC is None, reason="inotify is Linux's")
def test_a_read_by_anything_but_the_cli_leaves_the_file_for_the_cli(tmp_path):
    """On 0.41.9's release candidate a scan of the session volume read goose's prompt file before goose did, the
    file went at that read, and goose answered "Instruction file not found". A read by a process the file was
    never handed to (the runner's own, a scan, a checkpoint) leaves it; the CLI's own read still takes it."""
    import time
    held: dict = {}
    tok = server._TURN_PROMPT.set(held)
    try:
        path = server._prompt_handover(str(tmp_path), MARK)
    finally:
        server._TURN_PROMPT.reset(tok)
    assert _foreign_read(path) == MARK               # another process, handed nothing
    with open(path) as fh:
        assert fh.read() == MARK                     # this process, handed nothing either
    time.sleep(0.8)
    assert pathlib.Path(path).exists(), "taken away by a read that wasn't the CLI's"
    assert _cli_reads(path) == MARK                  # the CLI's own read
    for _ in range(40):
        if not pathlib.Path(path).exists():
            break
        time.sleep(0.05)
    assert not pathlib.Path(path).exists(), "the CLI read it, closed it, and it is still there"
    server._prompt_discard(held)
