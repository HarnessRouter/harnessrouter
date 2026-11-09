"""A disabled tool on a base that cannot withhold it is asked off in the agent doc, by name.

Qwen Code and Cline had neither a block nor the request: a harness with every tool switched off ran
on them with every tool offered and nothing said about it (measured at a stand-in model, every tool
in the request, no "Disabled tools" block). UHP §4.3: where a runtime cannot block a tool, the
restriction MUST still reach the agent, and MUST NOT be silently dropped.
"""
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (BACKENDS, _TOOLS_OFF_BY_REQUEST, _agent_doc_path,  # noqa: E402
                    _disabled_tools_note, _write_agent_doc)

OFF = ["run_shell_command", "write_file (writes a file)", "editor"]


@pytest.mark.parametrize("backend", ["qwen", "gemini", "cline"])
def test_qwen_gemini_and_cline_withhold_rather_than_ask(backend):
    """Each has a real switch in a settings file (test_qwen_build.py, test_gemini_build.py,
    test_cline_backend.py)."""
    assert backend not in _TOOLS_OFF_BY_REQUEST and _disabled_tools_note(backend, OFF) == ""


@pytest.mark.parametrize("backend", sorted(_TOOLS_OFF_BY_REQUEST))
def test_every_request_only_base_is_asked_by_name(backend):
    note = _disabled_tools_note(backend, OFF)
    assert note.startswith("## Disabled tools\n\nDo NOT use these tools")
    for name in OFF:
        assert name in note, (backend, name)


@pytest.mark.parametrize("backend", sorted(set(BACKENDS) - _TOOLS_OFF_BY_REQUEST))
def test_a_base_with_a_real_switch_gets_no_request(backend):
    """Those withhold the tool in their builder; a request on top would say the switch is weaker
    than it is."""
    assert _disabled_tools_note(backend, OFF) == ""


@pytest.mark.parametrize("off", [None, [], [""], ["  "]])
def test_nothing_switched_off_says_nothing(off):
    assert _disabled_tools_note("codex", off) == ""


def test_every_request_only_base_is_a_backend():
    assert _TOOLS_OFF_BY_REQUEST <= set(BACKENDS)


@pytest.mark.parametrize("backend", sorted(_TOOLS_OFF_BY_REQUEST))
def test_the_request_lands_in_the_file_the_cli_reads(backend):
    """The doc is written where each CLI reads it (QWEN.md for qwen, GEMINI.md for gemini,
    AGENTS.md for cline and the rest); a request written anywhere else is never seen."""
    d = tempfile.mkdtemp()
    _write_agent_doc(d, backend, _disabled_tools_note(backend, OFF), [])
    text = _agent_doc_path(d, backend).read_text()
    assert "## Disabled tools" in text and "run_shell_command" in text
