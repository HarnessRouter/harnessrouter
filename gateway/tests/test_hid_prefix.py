"""The per-harness URL must accept every base the catalog declares.

The alternation was hardcoded and drifted twice: /dsh/v1/* and /opencode/v1/* answered a bare 404
because nobody added the new ids (found live on the hosted side). It is now derived from
_BASE_CATALOG, and this test is the tripwire: add a base, and its public URL routes with no
second edit — or this fails naming the base.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import _BASE_CATALOG, _HID_PREFIX_RE, _SUPPORTED_BASES  # noqa: E402


def test_every_catalog_base_routes_on_the_per_harness_url():
    for base in _BASE_CATALOG:
        m = _HID_PREFIX_RE.match(f"/{base}/v1/responses")
        assert m and m.group(1) == base, f"base '{base}' does not route on /{{hid}}/v1/*"


def test_the_stored_alias_and_chrn_ids_route_too():
    assert "claude" in _SUPPORTED_BASES
    assert _HID_PREFIX_RE.match("/claude/v1/responses")
    assert _HID_PREFIX_RE.match("/chrn_" + "a" * 32 + "/v1/responses")


def test_a_non_base_prefix_does_not_match():
    assert _HID_PREFIX_RE.match("/claudex/v1/responses") is None
    assert _HID_PREFIX_RE.match("/chrn_short/v1/responses") is None
