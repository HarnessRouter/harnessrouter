"""The report is the published evidence for a conformance claim, so its verdict fields are the
contract under test here: a skip must never disappear into a green `conformant`, and the file
must date itself and name the suite revision that produced it (issue #7)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from uhp_conformance import __version__
from uhp_conformance.registry import CheckResult, Outcome
from uhp_conformance.report import highest_class, render, to_json


def _r(id, outcome, cls="core", detail=""):
    return CheckResult(id, f"title {id}", cls, "spec §x", outcome, detail)


CLEAN = [_r("B-01", Outcome.PASS), _r("B-02", Outcome.PASS)]
SKIPPY = [_r("B-01", Outcome.PASS), _r("B-02", Outcome.SKIP, detail="no session api"),
          _r("B-03", Outcome.SKIP, detail="no files api")]
FAILING = [_r("B-01", Outcome.PASS), _r("B-02", Outcome.FAIL, detail="wrong status")]


def test_clean_run_is_conformant():
    d = json.loads(to_json(CLEAN, "http://t", "core"))
    assert d["conformant"] is True
    assert d["conformant_with_skips"] is True
    assert d["skipped_not_verified"] == []


def test_a_skip_is_never_a_pass_in_the_json_verdict():
    d = json.loads(to_json(SKIPPY, "http://t", "core"))
    assert d["conformant"] is False
    assert d["conformant_with_skips"] is True
    assert d["skipped_not_verified"] == ["B-02", "B-03"]


def test_failures_fail_both_verdicts():
    d = json.loads(to_json(FAILING, "http://t", "core"))
    assert d["conformant"] is False
    assert d["conformant_with_skips"] is False


def test_report_dates_itself_and_names_the_suite():
    d = json.loads(to_json(CLEAN, "http://t", "core"))
    assert d["suite_version"] == __version__
    stamped = datetime.strptime(d["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert abs((datetime.now(timezone.utc).replace(tzinfo=None) - stamped).total_seconds()) < 60


def test_human_summary_speaks_the_same_vocabulary():
    out = render(SKIPPY, "http://t", "core", plain=True)
    assert "CONFORMANT WITH SKIPS" in out
    assert "A skip is not a pass." in out
    clean = render(CLEAN, "http://t", "core", plain=True)
    assert "CONFORMANT WITH SKIPS" not in clean
    assert "CONFORMANT" in clean


def test_highest_class_is_strict():
    # "Fully passed" means every check at and below the class ran and passed: fails, errors,
    # skips, and classes with no results at all each break the ladder.
    assert highest_class(CLEAN) == "core"          # only core ran — full is not creditable
    assert highest_class(SKIPPY) == ""             # a skipped check was not verified
    assert highest_class(FAILING) == ""
    full = [_r(f"{c}-01", Outcome.PASS, cls=c) for c in ("core", "extended", "full")]
    assert highest_class(full) == "full"
