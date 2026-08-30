"""T-08/T-09/T-10 are shown to fail on servers that get §1.4 wrong.

The suite sent neither `tools` nor `include` before this, so both directions of the reserved-field
rule were unmeasured: a server that rejected them and a server that silently honoured them would
each have scored the same as a correct one. These tests pin all three ways it can go wrong —
rejecting, ignoring in silence, and reporting fields the request never sent.
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

STUB = pathlib.Path(__file__).parent / "reserved_field_stub.py"
IDS = ("T-08", "T-09", "T-10")

CAUGHT_BY = {
    "rejects_reserved": "T-08",
    "silent_ignore": "T-09",
    "partial_report": "T-09",
    "hardcoded_report": "T-10",
}


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
        return {c.id: c.run(ctx).outcome for c in REGISTRY if c.id in IDS}
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_the_checks_are_registered_at_core():
    got = [c for c in REGISTRY if c.id in IDS]
    assert [c.id for c in got] == list(IDS)
    assert {c.cls for c in got} == {"core"}


def test_a_conformant_server_passes_all_three():
    assert all(o is Outcome.PASS for o in _run("none").values())


@pytest.mark.parametrize("defect,expected", sorted(CAUGHT_BY.items()))
def test_each_defect_is_caught_by_its_own_check(defect, expected):
    out = _run(defect)
    assert out[expected] is Outcome.FAIL, f"{defect!r} was not caught by {expected}: {out}"


def test_rejecting_the_request_does_not_also_fail_the_reporting_check():
    """A server that refuses the request never produced a response to report anything in, so
    T-09 must skip rather than add a second red mark for one defect."""
    out = _run("rejects_reserved")
    assert out["T-08"] is Outcome.FAIL
    assert out["T-09"] is Outcome.SKIP, out


def test_no_check_errors_on_any_defect():
    for defect in ["none", *CAUGHT_BY]:
        assert Outcome.ERROR not in _run(defect).values(), defect
