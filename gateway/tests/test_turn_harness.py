"""A turn addressed to a harness runs on that harness or not at all."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_an_unknown_harness_id_is_refused_and_a_base_id_or_no_id_is_not():
    """A typo'd chrn_ id used to run on the default backend and bill the caller; now it is a 404 like
    a deleted harness. A base id is a harness without a vertex and still runs; no id at all is an
    ad-hoc turn and still runs."""
    gw._turn_harness_check("", None)
    base = next(iter(gw._BASE_CATALOG))
    gw._turn_harness_check(base, None)
    gw._turn_harness_check("chrn_0123456789abcdef", {"id": "chrn_0123456789abcdef", "org": "org.a", "deleted": "0"})
    with pytest.raises(Exception) as e:
        gw._turn_harness_check("chrn_doesnotexist0000", None)
    assert "harness_not_found" in str(getattr(e.value, "detail", e.value)) or "No harness" in str(e.value)
    with pytest.raises(Exception):
        gw._turn_harness_check("chrn_0123456789abcdef", {"id": "chrn_0123456789abcdef", "deleted": "1"})
