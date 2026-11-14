"""T-15 and T-16 are shown to fail on servers that get the refusals of a resume wrong (Tasks §3.3).

A black-box suite cannot restart a server, so these checks measure what it can: that a resume with
nothing to resume starts no task and is refused the way §3.3 says, and that a server without the
capability refuses the item rather than running it as an empty task. The stub gets each rule wrong,
one defect at a time.
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

STUB = pathlib.Path(__file__).parent / "resume_stub.py"
IDS = ("T-15", "T-16")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(defect: str) -> dict[str, Outcome]:
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
        ctx.state["discovery"] = ctx.client.get("/v1/uhp").json
        return {c.id: c.run(ctx).outcome for c in REGISTRY if c.id in IDS}
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_the_checks_are_registered_at_full():
    got = [c for c in REGISTRY if c.id in IDS]
    assert sorted(c.id for c in got) == list(IDS)
    assert {c.cls for c in got} == {"full"}


def test_a_conformant_server_passes_and_the_other_check_skips():
    assert _run("none") == {"T-15": Outcome.PASS, "T-16": Outcome.SKIP}


def test_a_server_without_the_capability_that_refuses_the_item_passes():
    assert _run("no_capability") == {"T-15": Outcome.SKIP, "T-16": Outcome.PASS}


def test_a_server_without_the_capability_that_runs_the_item_fails():
    """It read a resume as an ordinary task: a client that sent it unchecked started a turn on
    nothing."""
    assert _run("capability_runs_it")["T-16"] is Outcome.FAIL


@pytest.mark.parametrize("defect", ["runs_finished", "not_pending_is_404", "wrong_code",
                                    "no_previous_runs", "extra_item_runs", "double_resume_runs",
                                    "refusal_changes_it"])
def test_a_wrong_refusal_fails(defect):
    assert _run(defect)["T-15"] is Outcome.FAIL


def test_no_check_errors_on_any_defect():
    for defect in ["none", "no_capability", "capability_runs_it", "runs_finished", "not_pending_is_404",
                   "wrong_code", "no_previous_runs", "extra_item_runs", "double_resume_runs",
                   "refusal_changes_it"]:
        got = _run(defect)
        assert set(got) == set(IDS), f"a check is not registered, so the defect {defect!r} was never run"
        assert Outcome.ERROR not in got.values(), defect
