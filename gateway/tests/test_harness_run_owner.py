"""A harness runs only for the organization and workspace that own it (Richard, 2026-10-06).

Until then the harness id was the run capability: a caller that knew it ran the harness with the
owner's connected plugs, on the owner's connections. Made on the hosted service first; the same
rule and the same tests here.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402
from fastapi import HTTPException  # noqa: E402

HV = {"org": "org.owner", "workspace": "space.team"}


def _refused(principal, hv=HV):
    with pytest.raises(HTTPException) as e:
        gw._turn_harness_owned(principal, hv)
    return e.value.status_code


def test_another_organization_is_told_there_is_no_such_harness():
    assert _refused({"org": "org.other"}) == 404
    assert _refused({"org": ""}) == 404


def test_the_owner_runs_it_from_its_own_workspace_or_with_an_organization_wide_key():
    gw._turn_harness_owned({"org": "org.owner", "workspace": "space.team"}, HV)
    gw._turn_harness_owned({"org": "org.owner", "workspace": ""}, HV)          # a key for the whole organization


def test_a_key_of_another_workspace_of_the_same_organization_does_not_run_it():
    assert _refused({"org": "org.owner", "workspace": "space.elsewhere"}) == 404


def test_a_harness_from_before_workspaces_belongs_to_the_default_workspace():
    legacy = {"org": "org.owner", "workspace": ""}
    gw._turn_harness_owned({"org": "org.owner", "workspace": "org.owner__hr_default"}, legacy)
    gw._turn_harness_owned({"org": "org.owner", "workspace": "space.x", "workspace_default": True}, legacy)
    assert _refused({"org": "org.owner", "workspace": "space.team"}, legacy) == 404


def test_a_base_with_no_record_has_no_owner():
    gw._turn_harness_owned({"org": "org.anyone"}, None)


def test_a_credential_that_drives_one_harness_runs_it_in_its_own_organization():
    # the scoped credential of a calibrating run names an organization and no workspace
    gw._turn_harness_owned({"org": "org.owner", "member": "calibrator:s1", "calibration": {"inner": "chrn_1"}}, HV)
    assert _refused({"org": "org.other", "member": "calibrator:s1", "calibration": {"inner": "chrn_1"}}) == 404


def test_the_refusal_is_the_one_a_missing_harness_gets():
    with pytest.raises(HTTPException) as e:
        gw._turn_harness_owned({"org": "org.other"}, HV)
    assert e.value.status_code == 404 and "No harness with that id." in str(e.value.detail)


def test_every_new_turn_is_checked_right_after_the_harness_is_read():
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    i = src.index("    _turn_harness_check(harness_id, hv)\n    _turn_harness_owned(principal, hv)\n")
    assert src.rfind("async def create_response(", 0, i) > src.rfind("\nasync def ", 0, i) - 1
