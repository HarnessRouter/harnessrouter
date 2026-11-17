"""T-15 is shown to fail on servers that get the refusals of a resume wrong (Tasks §3.3).

A black-box suite cannot restart a server, so this check measures what it can: that a resume with
nothing to resume starts no task and is refused the way §3.3 says. A server without the capability
is not judged, whatever it does with the item: §3.3 asks it to refuse (SHOULD), and requiring that
within the version would fail servers that conformed before it. The stub gets each rule wrong, one
defect at a time.
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
IDS = ("T-15",)


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


def test_a_conformant_server_passes():
    assert _run("none") == {"T-15": Outcome.PASS}


@pytest.mark.parametrize("defect", ["no_capability", "capability_runs_it"])
def test_a_server_without_the_capability_is_not_judged_whatever_it_does_with_the_item(defect):
    """Refusing the item or reading it as an ordinary task, a server that does not report `resume`
    keeps the verdict it had before §3.3: no check of the suite fails it (VERSIONING)."""
    assert _run(defect) == {"T-15": Outcome.SKIP}


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
