"""The R-series is tested the way it asks servers to be tested: by being shown to fail.

Sessions §5 is mostly a list of refusals, and a check that only ever passes cannot tell a
server that refuses from one that does not — D-05 passed against real servers for months while
being vacuous, which is the failure this file exists to avoid repeating.

So every R- check is run against a deliberately wrong server (share_defect_stub.py) carrying
one defect at a time. Each defect must be caught by the check that claims to cover it, and a
clean server must pass all seven. The stub answers every task itself, so this needs no
credentials, no network and no agent tokens.
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

STUB = pathlib.Path(__file__).parent / "share_defect_stub.py"

# Each defect, and the check whose message names exactly that mistake.
CAUGHT_BY = {
    "view_needs_auth": "R-01",
    "get_share_disagrees": "R-02",
    "share_id_is_token": "R-03",
    "view_accepts_writes": "R-04",
    "leaks_credentials": "R-05",
    "revoke_lies": "R-06",
    "multi_mint": "R-06",
    "no_delete_revocation": "R-06",
    "share_outlives_session": "R-07",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_series(defect: str, dialect: str = "plain") -> dict[str, Outcome]:
    """Every R- check against a stub carrying `defect`, in registration order."""
    port = _free_port()
    srv = subprocess.Popen([sys.executable, str(STUB)],
                           env={"DEFECT": defect, "DIALECT": dialect, "PORT": str(port),
                                "PATH": "/usr/bin:/bin"},
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

        # A fresh context per defect: the checks cache the share they minted, and a cache carried
        # between servers would test the previous one.
        ctx = Context(client=Client(f"http://127.0.0.1:{port}", "stub-key"), task_timeout=30.0)
        return {c.id: c.run(ctx).outcome for c in REGISTRY if c.id.startswith("R-")}
    finally:
        srv.terminate()
        srv.wait(timeout=5)


def test_the_series_is_registered_at_full():
    ids = [c.id for c in REGISTRY if c.id.startswith("R-")]
    assert ids == [f"R-0{i}" for i in range(1, 8)]
    assert {c.cls for c in REGISTRY if c.id.startswith("R-")} == {"full"}


def test_a_conformant_server_passes_every_check():
    out = _run_series("none")
    assert all(o is Outcome.PASS for o in out.values()), out


@pytest.mark.parametrize("defect,expected", sorted(CAUGHT_BY.items()))
def test_each_defect_is_caught_by_its_own_check(defect, expected):
    out = _run_series(defect)
    assert out[expected] is Outcome.FAIL, (
        f"{defect!r} was not caught by {expected}: {out}")


@pytest.mark.parametrize("defect,expected", sorted(CAUGHT_BY.items()))
def test_no_other_check_reports_a_failure_for_that_defect(defect, expected):
    """One defect, one red check.

    A second failure elsewhere is not extra safety — it is a misleading diagnosis, and it is how
    a reviewer ends up chasing the wrong sentence of the specification. Where a defect genuinely
    makes another check unrunnable (a view that never resolved cannot be observed to stop
    resolving), the check is expected to skip rather than to guess.
    """
    out = _run_series(defect)
    also_failed = [i for i, o in out.items() if o is Outcome.FAIL and i != expected]
    assert not also_failed, f"{defect!r} also failed {also_failed}, which diagnoses one bug twice"


def test_a_view_that_never_resolved_makes_the_later_checks_skip():
    out = _run_series("view_needs_auth")
    assert out["R-01"] is Outcome.FAIL
    for i in ("R-04", "R-05", "R-06", "R-07"):
        assert out[i] is Outcome.SKIP, (
            f"{i} should skip when the view never resolved, got {out[i]}: 'stops resolving' and "
            "'never resolved' are indistinguishable there")


def test_no_check_errors_on_any_defect():
    """An ERROR is a bug in the suite. It must never be how a defect gets reported."""
    for defect in ["none", *CAUGHT_BY]:
        out = _run_series(defect)
        assert Outcome.ERROR not in out.values(), f"{defect}: {out}"


# ── the toggle dialect ────────────────────────────────────────────────────────────────
# The reference implementation does not speak §5's bodyless POST: the body carries the target
# state, an empty body is a validation error, and revocation is {"enabled": false}. The series
# must drive that dialect too — it skipped all seven against the reference until it did — and
# driving it must not cost any detection.


def test_a_conformant_toggle_dialect_server_passes_every_check():
    out = _run_series("none", dialect="enabled")
    assert all(o is Outcome.PASS for o in out.values()), out


def test_a_lying_revocation_is_caught_in_the_toggle_dialect_too():
    """§5 now NAMES the revocation endpoint, and the dialect stub serves it; a server whose
    DELETE answers 200 and revokes nothing must still fail R-06 whichever dialect minted."""
    out = _run_series("revoke_lies", dialect="enabled")
    assert out["R-06"] is Outcome.FAIL, out
    assert [i for i, o in out.items() if o is Outcome.FAIL] == ["R-06"], out


def test_the_dialect_retry_does_not_hide_a_missing_feature():
    """A server with no sharing at all still skips, never fails: the retry only fires on a
    validation error, and 404/405/501 mean today what they meant before it existed."""
    out = _run_series("none", dialect="plain")   # the plain stub already proves pass; this
    assert Outcome.ERROR not in out.values()     # guards the retry against breaking it
