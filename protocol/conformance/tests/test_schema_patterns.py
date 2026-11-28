"""Schema regex compatibility checks (#767): no lookaround and behavioral equivalence."""
from __future__ import annotations

from importlib import resources
import itertools
import json
import re

import jsonschema

from uhp_conformance import UHP_VERSION

SCHEMA_NAME = f"uhp-{UHP_VERSION}.schema.json"
LEGACY_LOOKAHEAD_PATTERN = r"^(?!.*(--|\.\.))[a-z0-9]([a-z0-9.-]*[a-z0-9])?$"
RE2_PLUGIN_NAME_PATTERN = r"^[a-z0-9]+(?:(?:\.(?:-\.)*-?|-(?:\.-)*\.?)[a-z0-9]+)*$"


def _iter_patterns(node, path=""):
    if isinstance(node, dict):
        if "pattern" in node and isinstance(node["pattern"], str):
            yield path or "<root>", node["pattern"]
        for k, v in node.items():
            yield from _iter_patterns(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _iter_patterns(v, f"{path}[{i}]")


def _has_unescaped_lookaround(pattern: str) -> bool:
    """Detect lookahead/lookbehind constructs unsupported by RE2."""
    i = 0
    in_class = False
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
            i += 1
            continue
        if ch == "[":
            in_class = True
            if i + 1 < n and pattern[i + 1] == "^":
                i += 1
            if i + 1 < n and pattern[i + 1] == "]":
                i += 1
            i += 1
            continue
        if ch == "(" and pattern[i + 1 : i + 2] == "?":
            if pattern[i + 2 : i + 3] in ("=", "!") or pattern[i + 2 : i + 4] in ("<=", "<!"):
                return True
        i += 1
    return False


def test_schema_patterns_contain_no_lookaround():
    schema = json.loads(resources.files("uhp_conformance").joinpath(SCHEMA_NAME).read_text())
    patterns = list(_iter_patterns(schema))
    assert patterns, "expected at least one pattern in the schema"
    for path, pat in patterns:
        assert not _has_unescaped_lookaround(pat), f"{path} uses lookaround unsupported by RE2: {pat!r}"
        re.compile(pat)


def test_plugin_name_pattern_is_re2_and_equivalent_to_legacy_lookahead():
    schema = json.loads(resources.files("uhp_conformance").joinpath(SCHEMA_NAME).read_text())
    defs = schema["$defs"]
    plugin_pat = defs["Plugin"]["properties"]["name"]["pattern"]
    manifest_pat = defs["PluginManifest"]["properties"]["name"]["pattern"]
    assert plugin_pat == RE2_PLUGIN_NAME_PATTERN
    assert manifest_pat == RE2_PLUGIN_NAME_PATTERN

    legacy_re = re.compile(LEGACY_LOOKAHEAD_PATTERN)
    re2_re = re.compile(plugin_pat)

    # Every equivalence class of valid/invalid chars: lowercase alpha, digit, dot, hyphen, uppercase, other.
    alphabet = ("a", "0", ".", "-", "A", "_")
    for length in range(7):
        for chars in itertools.product(alphabet, repeat=length):
            candidate = "".join(chars)
            assert bool(re2_re.fullmatch(candidate)) is bool(legacy_re.fullmatch(candidate)), (
                f"mismatch on {candidate!r}"
            )

    edge_cases = [
        "a",
        "0",
        "a-b.c",
        "a.b-c",
        "a.-b.-.c",
        "a-.b-.-c",
        "contract-review",
        "uhp-conformance-plugin",
        "a--b",
        "a..b",
        ".a",
        "a.",
        "-a",
        "a-",
        "",
        "a" * 64,
    ]
    for candidate in edge_cases:
        assert bool(re2_re.fullmatch(candidate)) is bool(legacy_re.fullmatch(candidate)), (
            f"mismatch on edge case {candidate!r}"
        )

    plugin_v = jsonschema.Draft202012Validator({"$defs": defs, **defs["Plugin"]})
    manifest_v = jsonschema.Draft202012Validator({"$defs": defs, **defs["PluginManifest"]})
    for good in ("a", "a.-b", "contract-review", "a.b-c.d"):
        assert not list(plugin_v.iter_errors({"name": good}))
        assert not list(manifest_v.iter_errors({"$schema": "https://example.com/s.json", "name": good}))
    for bad in ("", "a--b", "a..b", ".a", "a.", "-a", "a-", "Bad", "a_b"):
        assert list(plugin_v.iter_errors({"name": bad}))
        assert list(manifest_v.iter_errors({"$schema": "https://example.com/s.json", "name": bad}))
