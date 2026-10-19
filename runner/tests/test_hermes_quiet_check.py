"""hermes checks its work once, before it answers, and keeps the check out of the reply.

What this pins (2026-10-19): hermes' own verify-on-stop ran a second turn after the final answer,
told the model to write a `hermes-verify-` script under the OS temp dir while the agent doc said
files belong in the workspace, and asked for the check to be summarised to the person. The
person read about test commands and /tmp, and on one card got two answers."""
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _hermes_cfg(tmp_path, **kw) -> dict:
    env = {"HOME": str(tmp_path)}
    server._hermes_prepare_env("bedrock", server.Auth(), str(tmp_path), env, model="m", **kw)
    return yaml.safe_load((tmp_path / ".hermes" / "config.yaml").read_text())


def test_no_verify_turn_after_the_final_answer(tmp_path):
    """verify-on-stop is the one thing that runs the model again after it has answered. It is off
    in the file hermes reads, explicitly: left out, hermes' schema default ("auto") turns it on."""
    assert _hermes_cfg(tmp_path)["agent"]["verify_on_stop"] is False


def test_max_turns_rides_beside_it(tmp_path):
    agent = _hermes_cfg(tmp_path, max_turns=7)["agent"]
    assert agent == {"verify_on_stop": False, "max_turns": 7}


def _doc(tmp_path, backend: str) -> str:
    server._write_agent_doc(str(tmp_path), backend, "", [])
    return server._agent_doc_path(str(tmp_path), backend).read_text()


def test_one_file_rule_scratch_goes_inside_the_workspace(tmp_path):
    """Scratch has one place, `tmp/` in the workspace, and nothing points anywhere else: no
    instruction to write under /tmp beside one that says files outside are lost."""
    doc = _doc(tmp_path, "hermes")
    assert "`tmp/` folder" in doc and "Keep every file you write inside the workspace" in doc
    # /tmp is named once, as a place outside the workspace, never as a place to write to
    assert doc.count("/tmp") == 1 and "(/tmp, /app" in doc
    assert "hermes-verify" not in doc and "tempfile" not in doc
    # the config carries no path rule of its own
    _hermes_cfg(tmp_path)
    assert "tmp" not in (tmp_path / ".hermes" / "config.yaml").read_text()


def test_the_scratch_folder_is_scratch_in_fact(tmp_path):
    """The instruction and the runtime agree: a file in `tmp/` is never a produced file and never
    travels in the checkpoint, while a deliverable beside it is collected."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "tmp").mkdir()
    (ws / "tmp" / "check.py").write_text("print('ok')\n")
    (ws / "report.md").write_text("# report\n")
    paths = [f["path"] for f in server._produced_list(str(ws))]
    assert paths == ["report.md"]
    assert "./tmp" in server.CHECKPOINT_EXCLUDE
    ignored = subprocess.run(["git", "-C", str(ws), "check-ignore", "-q", "tmp/check.py"])
    assert ignored.returncode == 0


def test_the_check_stays_out_of_the_reply(tmp_path):
    doc = _doc(tmp_path, "hermes")
    assert "## Checking your work" in doc
    assert "before your final reply" in doc and "never after" in doc
    assert "The check is for you, not the user" in doc
    for kept_out in ("tests", "linters", "validators", "check scripts and their paths",
                     "whether the workspace has a test command"):
        assert kept_out in doc
    # inside the managed block, so a harness's own doc cannot be overwritten by it or shadow it
    begin, end = doc.index(server._AGENTS_BEGIN), doc.index(server._AGENTS_END)
    assert begin < doc.index("## Checking your work") < end


def test_the_check_section_is_hermes_only(tmp_path):
    """It replaces hermes' own stop-time check; no other base had one."""
    for backend in ("codex", "claude", "pi"):
        d = tmp_path / backend
        d.mkdir()
        doc = _doc(d, backend)
        assert "## Checking your work" not in doc
        assert "`tmp/` folder" in doc            # the file rule itself is every base's
