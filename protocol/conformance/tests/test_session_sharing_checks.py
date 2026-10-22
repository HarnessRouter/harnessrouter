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
from uhp_conformance import context
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
    "bodyless_rejected": "R-08",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_series(defect: str, dialect: str = "plain",
                delete_paths: str = "sessions,traces") -> dict[str, Outcome]:
    """Every R- check against a stub carrying `defect`, in registration order."""
    port = _free_port()
    srv = subprocess.Popen([sys.executable, str(STUB)],
                           env={"DEFECT": defect, "DIALECT": dialect, "PORT": str(port),
                                "DELETE_PATHS": delete_paths, "PATH": "/usr/bin:/bin"},
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
    assert ids == [f"R-0{i}" for i in range(1, 9)]
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


def test_the_toggle_dialect_is_not_a_licence_to_refuse_a_bodyless_post():
    """The retry exists so a toggle server can be MEASURED, not so it can be excused.

    `enabled` is the dialect of a server that also accepts §5's bodyless POST — the reference
    implementation since #53 — so it must pass R-08 like everything else. `bodyless_rejected` is
    the server that only accepts the toggle, and it must fail R-08 and nothing else: every other
    check reaches it through the retry, which is exactly the hiding this check was written to
    undo.
    """
    assert _run_series("none", dialect="enabled")["R-08"] is Outcome.PASS

    out = _run_series("bodyless_rejected")
    assert out["R-08"] is Outcome.FAIL, out
    assert [i for i, o in out.items() if o is Outcome.FAIL] == ["R-08"], out


# ── §6's two delete paths ─────────────────────────────────────────────────────────────
# §6 names `DELETE /v1/sessions/{id}` and says `DELETE /v1/traces/{id}` is the older path for
# the same operation, which a server MAY keep. R-07 drove only the alias, so against a server
# serving only the named path it skipped — and `share_outlives_session` went unreported while
# every other R- check passed. The stub matched that drift (it too served only the alias), so
# the diagonal above was green by coincidence rather than by coverage.


@pytest.mark.parametrize("delete_paths", ["sessions", "traces", "sessions,traces"])
def test_a_published_link_outliving_its_session_is_caught_at_either_delete_path(delete_paths):
    out = _run_series("share_outlives_session", delete_paths=delete_paths)
    assert out["R-07"] is Outcome.FAIL, (
        f"a server serving delete at {delete_paths!r} let share_outlives_session through: {out}")
    assert [i for i, o in out.items() if o is Outcome.FAIL] == ["R-07"], out


@pytest.mark.parametrize("delete_paths", ["sessions", "traces", "sessions,traces"])
def test_a_conformant_server_passes_every_check_at_either_delete_path(delete_paths):
    """The fix must not turn a passing server into a failing one: whichever of §6's paths a
    conformant server serves, the series stays green rather than reporting the other missing."""
    out = _run_series("none", delete_paths=delete_paths)
    assert all(o is Outcome.PASS for o in out.values()), f"{delete_paths!r}: {out}"


# ── a broken installation of the suite ────────────────────────────────────────────────
# `ctx.validate` raises RuntimeError when the suite cannot validate anything: no jsonschema, or
# no schema file beside the installed package. #203 ruled that condition an ERROR rather than a
# SKIP, and the checks whose subject IS a schema still report it that way.
#
# The R-series' subject is what a shared view refuses, and `_share` validates the one share
# object it mints and caches on all eight checks' behalf. So the unavailable validator must not
# escape that mint: every check downstream of the cache would report a suite bug in place of a
# §5 measurement, and the whole series would say "broken install" six more times than the one
# cause deserves.


def _break_the_validator(monkeypatch, how: str) -> None:
    """Put `ctx.validate` in the state a broken installation puts it in.

    Both conditions are the two its own docstring names, and it raises RuntimeError — not Skip —
    for each. Asserted here, so a handler written for the wrong exception type cannot pass this
    file by catching something `ctx.validate` never raises.
    """
    if how == "no_jsonschema":
        monkeypatch.setattr(context, "jsonschema", None)
    elif how == "no_schema_file":
        monkeypatch.setattr(context, "SCHEMA_RESOURCE",
                            pathlib.Path("/nonexistent/uhp_conformance/uhp.schema.json"))
    else:
        raise AssertionError(f"unknown way to break the validator: {how!r}")
    with pytest.raises(context.ValidatorUnavailable):   # what _share catches, and nothing wider
        context.Context(client=Client("http://127.0.0.1:1", "unused")).validate({}, "SessionShare")


@pytest.mark.parametrize("how", ["no_jsonschema", "no_schema_file"])
def test_an_unavailable_validator_does_not_cascade_through_the_shared_mint(monkeypatch, how):
    """One unavailable validator, not six suite bugs: the series still measures §5."""
    _break_the_validator(monkeypatch, how)
    out = _run_series("none")
    errored = [i for i, o in out.items() if o is Outcome.ERROR]
    assert not errored, (
        f"{how}: {errored} report a suite bug because the mint they all share could not validate "
        f"its own share object: {out}")
    assert all(o is Outcome.PASS for o in out.values()), f"{how}: {out}"


@pytest.mark.parametrize("defect,expected", sorted(CAUGHT_BY.items()))
def test_a_real_defect_is_still_caught_when_the_validator_is_unavailable(monkeypatch, defect,
                                                                        expected):
    """Degrading the mint's own validation must cost no detection.

    A suite that cannot fail is worse than one that cannot run, so the whole defect matrix is
    driven again without a validator: each defect must still be caught by its own check.
    """
    _break_the_validator(monkeypatch, "no_jsonschema")
    out = _run_series(defect)
    assert out[expected] is Outcome.FAIL, (
        f"{defect!r} went uncaught by {expected} without a validator: {out}")
