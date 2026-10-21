"""T-12 is shown to fail on servers that get the step-budget rule wrong.

Nothing in the suite sent `max_step` before this, so the rule was unmeasured: a server that
ignored the budget and reported `completed` scored as well as one that stopped at the budget and
reported `incomplete`. These tests pin the ways it can go wrong — a silent `completed`, a chain cut
short and reported done, an `incomplete` with no reason, a reason that names another budget — and
the answers the check has to accept: a server that names `max_step` in `metadata.ignored_fields`,
and a task whose chain never began, which measured nothing.
"""
from __future__ import annotations

import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from uhp_conformance import checks  # noqa: F401 — importing populates the registry
from uhp_conformance.client import Client
from uhp_conformance.context import Context
from uhp_conformance.registry import REGISTRY, Outcome

STUB = pathlib.Path(__file__).parent / "step_budget_stub.py"
# The stub answers as the fixture does, so it needs the package the check reads the fixture from.
PKG_PATH = str(pathlib.Path(checks.__file__).resolve().parent.parent)
ID = "T-12"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(defect: str) -> dict[str, Outcome]:
    port = _free_port()
    srv = subprocess.Popen([sys.executable, str(STUB)],
                           env={"DEFECT": defect, "PORT": str(port), "PATH": "/usr/bin:/bin",
                                "PYTHONPATH": PKG_PATH},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/uhp", timeout=1).read()
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)
        else:
            pytest.fail(f"the stub did not start for defect {defect!r}")
        ctx = Context(client=Client(f"http://127.0.0.1:{port}", "stub-key"), task_timeout=30.0)
        return {c.id: c.run(ctx).outcome for c in REGISTRY if c.id == ID}
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_the_check_is_registered_at_full():
    got = [c for c in REGISTRY if c.id == ID]
    assert [c.id for c in got] == [ID]
    assert {c.cls for c in got} == {"full"}


def test_a_conformant_server_passes():
    assert _run("none")[ID] is Outcome.PASS


def test_a_server_that_ignores_the_budget_fails():
    """The task ended `completed` after the fixture's chain ran past the budget: the work was
    truncated and reported as done, which §1.1 forbids."""
    assert _run("ignores_budget")[ID] is Outcome.FAIL


def test_a_server_that_runs_the_chain_past_the_budget_fails():
    """Two rounds against a budget of one is already past it: the server let the work outgrow the
    budget and then reported the task done."""
    assert _run("ignores_budget_two_calls")[ID] is Outcome.FAIL


def test_a_task_that_failed_past_the_budget_fails():
    """A server that stopped the task at the budget must report `incomplete`; a task that ran
    past the budget and ended `failed` is not that."""
    assert _run("failed_status")[ID] is Outcome.FAIL


def test_a_chain_that_stayed_inside_the_budget_skips():
    """One round is inside a budget of one, so the server truncated nothing and the model ended
    the turn. §1.1 forbids reporting `completed` for work the SERVER truncated; this is not
    that, so the check skips rather than failing a correct server."""
    assert _run("model_ended_the_turn")[ID] is Outcome.SKIP


def test_incomplete_without_a_reason_passes_with_a_note():
    """§1.1 requires `incomplete` for work stopped at the budget and says nothing of the reason, so
    a missing reason is reported in the result, never failed: a check holds a server to the protocol."""
    assert _run("no_reason")[ID] is Outcome.PASS


def test_a_reason_that_names_another_budget_passes_with_a_note():
    """A reason that names the time budget is a poor diagnosis, but §1.1 requires the status, not
    the reason, so it is reported and not failed."""
    assert _run("wrong_reason")[ID] is Outcome.PASS


def test_a_reason_that_names_the_budget_in_the_specs_other_words_passes():
    """§1.1 calls `max_step` an upper bound on "agent steps (tool-call rounds)", so a server that
    says "rounds" names the same budget as one that says "steps"."""
    assert _run("rounds_reason")[ID] is Outcome.PASS


def test_a_server_that_names_max_step_as_ignored_passes():
    """A server that cannot bound a base has to say so (§1.1: ignoring must be observable). That is
    §1.1's other answer, so it passes: a skip would leave the server short of a clean verdict for good."""
    assert _run("reports_ignored")[ID] is Outcome.PASS


def test_a_tool_named_with_the_servers_mcp_prefix_is_counted():
    """Claude-family bases name an MCP tool mcp__<server>__<tool>; those rounds are the fixture's
    tool all the same, or the reference server would skip this check forever."""
    assert _run("prefixed_tool")[ID] is Outcome.PASS


def test_a_task_that_never_called_the_tool_skips():
    """The agent never called the tool, so there was no work to truncate: the check measured
    nothing, and a model that ignores the prompt must not fail the suite."""
    assert _run("no_tool_call")[ID] is Outcome.SKIP


def test_a_task_that_never_started_skips():
    """A server that reports `incomplete` without the work ever having started measured nothing
    either: no tool call, no chain, no truncation. The check skips rather than pass, because a
    pass would be a claim about a budget that was never spent."""
    assert _run("incomplete_never_started")[ID] is Outcome.SKIP


def test_no_check_errors_on_any_defect():
    for defect in ["none", "ignores_budget", "ignores_budget_two_calls", "model_ended_the_turn",
                   "no_reason", "wrong_reason", "rounds_reason", "reports_ignored",
                   "no_tool_call", "incomplete_never_started", "failed_status", "prefixed_tool"]:
        got = _run(defect)
        assert ID in got, f"the check {ID} is not registered, so the defect {defect!r} was never run"
        assert Outcome.ERROR not in got.values(), defect
