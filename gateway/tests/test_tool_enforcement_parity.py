"""The catalog's word on a disabled tool and what the runner does about it are one fact.

`tool_enforcement: "instruction"` in _BASE_CATALOG tells the console to say the agent can only be
asked; the runner's _TOOLS_OFF_BY_REQUEST is the set of bases it asks, in the agent doc. They drifted
once: Qwen Code and Cline were "instruction" in the catalog and in neither runner branch, so a
harness with every tool switched off ran on them with every tool offered and no request either. The
gateway cannot import the runner, so the runner's set is read from its source.
"""
import ast
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "runner" / "server.py"


def _runner_off_by_request() -> set[str]:
    tree = ast.parse(RUNNER.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_TOOLS_OFF_BY_REQUEST" for t in node.targets):
            call = node.value
            assert isinstance(call, ast.Call) and getattr(call.func, "id", None) == "frozenset", \
                "_TOOLS_OFF_BY_REQUEST must stay a literal frozenset so this test can read it"
            return set(ast.literal_eval(call.args[0]))
    raise AssertionError("runner/server.py has no _TOOLS_OFF_BY_REQUEST")


def _catalog(enforcement: str) -> set[str]:
    return {b["backend"] for b in A._BASE_CATALOG.values() if b["tool_enforcement"] == enforcement}


def test_every_instruction_base_is_asked_by_the_runner():
    missing = _catalog("instruction") - _runner_off_by_request()
    assert not missing, f"the console says these are asked, and the runner asks nothing: {sorted(missing)}"


def test_the_runner_asks_only_where_the_catalog_says_instruction():
    """A base the runner asks but the catalog calls hard would have the console promise a block the
    runner does not make."""
    extra = _runner_off_by_request() - _catalog("instruction")
    assert not extra, f"asked by the runner but called hard in the catalog: {sorted(extra)}"


def test_enforcement_is_one_of_the_two_words():
    assert {b["tool_enforcement"] for b in A._BASE_CATALOG.values()} <= {"hard", "instruction"}
