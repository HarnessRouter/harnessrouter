"""Runner must never silently turn an approval policy into autonomous execution."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from approval_policy import approval_policy_error  # noqa: E402


def test_approval_policy_is_refused_before_runtime_selection():
    assert approval_policy_error({"require": ["external_write"]}, field_present=True) == \
        "hexa_approval_unavailable"


def test_explicit_null_policy_is_also_refused():
    assert approval_policy_error(None, field_present=True) == "hexa_approval_unavailable"


def test_absent_policy_keeps_legacy_unconfigured_path():
    assert approval_policy_error(None, field_present=False) is None
