"""T-12 is shown to fail on a server that does not hold `max_step`.

The suite checked the field's schema and never its effect, so a server that dropped the budget in
silence and ran the task to the end scored the same as one that stopped it. The stub's agent always
makes three tool calls, so whether a turn outruns `max_step: 1` is not left to a model.
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
ID = "T-12"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(defect: str):
    port = _free_port()
    srv = subprocess.Popen([sys.executable, str(STUB)],
                           env={"DEFECT": defect, "PORT": str(port), "PATH": "/usr/bin:/bin"},
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
        return next(c for c in REGISTRY if c.id == ID).run(ctx)
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_the_check_is_registered_at_core():
    got = [c for c in REGISTRY if c.id == ID]
    assert len(got) == 1 and got[0].cls == "core"


@pytest.mark.parametrize("defect", ["none", "reports_ignored"])
def test_a_server_that_stops_or_says_it_cannot_passes(defect):
    res = _run(defect)
    assert res.outcome is Outcome.PASS, res.detail


@pytest.mark.parametrize("defect", ["silent_ignore", "rejects_max_step", "unnamed_reason"])
def test_each_defect_fails(defect):
    res = _run(defect)
    assert res.outcome is Outcome.FAIL, f"{defect!r}: {res.outcome} {res.detail}"


def test_a_silent_completed_is_named_in_the_failure():
    res = _run("silent_ignore")
    assert "completed" in res.detail and "ignored_fields" in res.detail, res.detail
