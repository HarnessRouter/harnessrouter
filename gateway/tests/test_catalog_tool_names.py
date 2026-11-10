"""A tool switch the catalog offers names a tool the pinned CLI has, by the name the runner uses.

Found stale on 2026-11-09: codex offered read_file, write_file and git, which codex 0.154 does not
have, and no switch for web_search, which it has and the runner can turn off; OpenSquilla offered
`exec` and `grep`, which 0.5.6 calls exec_command and grep_search. A switch for a name the CLI does
not have disables nothing while the console says it is off.

The runner pins each CLI's tool names beside the code that uses them (CLAUDE_TOOLS, CODEX_TOOLS,
OPENSQUILLA_TOOLS), with the catalog ids it maps to a current name (_CLAUDE_TOOL_RENAMES,
_CODEX_SHELL_NAMES). The gateway cannot import the runner, so they are read from its source, as
test_tool_enforcement_parity.py reads _TOOLS_OFF_BY_REQUEST.
"""
import ast
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "runner" / "server.py"


def _runner_literal(name: str):
    """A top-level literal assignment in runner/server.py: a tuple, a dict, or frozenset({...})."""
    for node in ast.parse(RUNNER.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            value = node.value
            if isinstance(value, ast.Call) and getattr(value.func, "id", None) == "frozenset":
                return frozenset(ast.literal_eval(value.args[0]))
            return ast.literal_eval(value)
    raise AssertionError(f"runner/server.py has no top-level literal {name}")


def _offered(base: str) -> set[str]:
    return {n for n, _ in A._BASE_CATALOG[base]["tools"]}


def test_claude_code_offers_only_tools_the_cli_has():
    tools = set(_runner_literal("CLAUDE_TOOLS"))
    renames = _runner_literal("_CLAUDE_TOOL_RENAMES")
    stale = _offered("claude-code") - tools - set(renames)
    assert not stale, f"not a Claude Code 2.1.280 tool, and the runner maps no such id: {sorted(stale)}"
    # an id kept for stored harnesses must land on a tool the CLI has now
    assert set(renames.values()) <= tools, sorted(set(renames.values()) - tools)
    # what the runner adds itself (the question tool, #476) is a tool the CLI has too
    assert "AskUserQuestion" in tools


def test_claude_code_offers_every_file_writing_tool():
    """With Edit and Write switched off, NotebookEdit still writes a file. The CLI groups the three
    as its edit tools, so a switch for two of them is not a switch for writing."""
    assert {"Edit", "Write", "NotebookEdit"} <= _offered("claude-code")


def test_codex_offers_only_tools_the_cli_has():
    tools = set(_runner_literal("CODEX_TOOLS"))
    shell = _runner_literal("_CODEX_SHELL_NAMES")
    stale = _offered("codex") - tools - shell
    assert not stale, f"not a codex 0.154 tool, and the runner maps no such id: {sorted(stale)}"
    assert shell - {"shell"} <= tools, "the runner's shell names must include the one codex sends"


def test_codex_offers_the_switches_the_runner_has():
    """The runner turns web_search and the shell off for real; a catalog without those ids leaves
    the console with no way to ask for either."""
    offered = _offered("codex")
    assert "web_search" in offered
    assert offered & _runner_literal("_CODEX_SHELL_NAMES")


def test_opensquilla_offers_only_tools_the_cli_has():
    tools = set(_runner_literal("OPENSQUILLA_TOOLS"))
    stale = _offered("opensquilla") - tools
    assert not stale, f"not an OpenSquilla 0.5.6 tool: {sorted(stale)}"
