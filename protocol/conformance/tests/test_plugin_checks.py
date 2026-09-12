"""The P-series is tested the way it asks servers to be tested: by being shown to fail.

The Plugins chapter is a set of derivations, refusals and omissions, and a check that only ever
passes cannot tell a server that refuses from one that does not. So every P- check runs against
a deliberately wrong server (plugin_stub.py) carrying one defect at a time. Each defect must be
caught by the check that claims to cover it, by no other, and a clean server must pass all ten.
No task is ever run, so this needs no credentials, no network and no agent tokens.
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

STUB = pathlib.Path(__file__).parent / "plugin_stub.py"

# Each defect, and the check whose message names exactly that mistake.
CAUGHT_BY = {
    "no_plugin_schemas": "P-01",
    "copies_into_direct": "P-02",
    "files_endpoint_partial": "P-02",
    "expands_placeholders": "P-02",
    "accepts_no_manifest": "P-03",
    "accepts_collision": "P-04",
    "loses_files_on_rename": "P-05",
    "export_leaks_credentials": "P-06",
    "export_unrecorded": "P-06",
    "drops_invalid_silently": "P-07",
    "enabled_not_preserved": "P-08",
    "accepts_unknown_schema": "P-09",
    "accepts_duplicate_name": "P-10",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_series(defect: str) -> dict[str, Outcome]:
    """Every P- check against a stub carrying `defect`, in registration order."""
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
        return {c.id: c.run(ctx).outcome for c in REGISTRY if c.id.startswith("P-")}
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_the_series_is_registered_at_full():
    ids = [c.id for c in REGISTRY if c.id.startswith("P-")]
    assert ids == [f"P-{i:02d}" for i in range(1, 11)]
    assert {c.cls for c in REGISTRY if c.id.startswith("P-")} == {"full"}


def test_a_conformant_server_passes_every_check():
    out = _run_series("none")
    assert all(o is Outcome.PASS for o in out.values()), out


@pytest.mark.parametrize("defect,expected", sorted(CAUGHT_BY.items()))
def test_each_defect_is_caught_by_its_own_check(defect, expected):
    out = _run_series(defect)
    assert out[expected] is Outcome.FAIL, f"{defect!r} was not caught by {expected}: {out}"


@pytest.mark.parametrize("defect,expected", sorted(CAUGHT_BY.items()))
def test_no_other_check_reports_a_failure_for_that_defect(defect, expected):
    """One defect, one red check. A second failure elsewhere is a misleading diagnosis."""
    out = _run_series(defect)
    also_failed = [i for i, o in out.items() if o is Outcome.FAIL and i != expected]
    assert not also_failed, f"{defect!r} also failed {also_failed}, which diagnoses one bug twice"


def test_no_check_errors_on_any_defect():
    """An ERROR is a bug in the suite. It must never be how a defect gets reported."""
    for defect in ["none", *CAUGHT_BY]:
        out = _run_series(defect)
        assert Outcome.ERROR not in out.values(), f"{defect}: {out}"


def test_a_server_without_the_capability_skips_the_series():
    """Plugins are a MAY: a server that reports the capability false must skip, never fail."""
    from uhp_conformance.registry import Skip
    from uhp_conformance.checks import _plugins_supported

    class _Client:
        def get(self, path, auth=True):
            class R:
                json = {"capabilities": {"plugins": False}}
            return R()

    with pytest.raises(Skip):
        _plugins_supported(Context(client=_Client()))
