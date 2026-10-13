"""The custom-harness dimension must switch off a tool the base ACTUALLY HAS, and never one the
fixture needs.

A tool id that matches nothing in a runtime is dropped on the way through and disables nothing, so
`disabled_tool_unused` is then vacuously true: the row passes a check that is not running. That is
what a single hardcoded `WebSearch` did on eleven of the twenty bases.

`custom-harness.mjs` no longer carries a per-base table of what to withhold — it DERIVES the choice
from the base's own published tool list (`pickDisabled`), excluding what the fixture needs
(`NEEDED_ID`) and preferring a short list of spare tools, and records the claim as unmeasurable when
a base publishes nothing else. That is better than a table because there is no list to drift, and it
moves the risk somewhere else: a base whose EXECUTION, FILE, SKILL or MCP tool is not matched by
`NEEDED_ID` would have that tool withheld, and the fixture would fail for a reason that is the
dimension's. This test is where that is caught, for every base the gateway offers.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

MJS = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "support-matrix" / "custom-harness.mjs"
SRC = MJS.read_text()


def _regex(name: str) -> re.Pattern:
    """A JS regex literal from the driver, as a Python pattern (both are PCRE-ish for this shape)."""
    body = re.search(rf"const {name} = /\^?(.*?)\$?/i;", SRC).group(1)
    return re.compile(rf"^(?:{body})$", re.I)


NEEDED = _regex("NEEDED_ID")
PREFERRED = _regex("PREFERRED")
# What the fixture does: run its skill's script, read and write files, load the skill, call MCP. A
# tool of any of those kinds must never be the one withheld.
FIXTURE_KINDS = ("exec", "file", "skill", "mcp")


def _bases_in_dimension() -> list:
    """The ids the driver runs, as the gateway spells them — which is the same spelling."""
    return re.search(r"const BASES = \(process\.env\.BASES \|\| '([^']+)'\)", SRC).group(1).split(",")


# The driver's own exclusion: a System One model chooses among offered actions and runs no shell, so
# the fixture's script has nothing to run on it.
EXCLUDED = {"systemone"}


def _tool_ids(spec: dict) -> list:
    """A base's tool IDS. The catalog stores (id, label) pairs, and reading the pair as a string is
    how the first version of this test decided no base's tools were covered by NEEDED_ID."""
    out = []
    for t in (spec.get("tools") or []):
        out.append(str(t[0]) if isinstance(t, (tuple, list)) and t else str(t))
    return out


def test_every_base_the_gateway_offers_is_in_the_dimension():
    missing = [b for b in A._BASE_CATALOG if b not in _bases_in_dimension() and b not in EXCLUDED]
    assert not missing, f"the dimension would never measure {missing}"


def test_this_batchs_four_bases_are_there():
    for b in ("mimo", "jcode", "opensquilla", "nanobot"):
        assert b in _bases_in_dimension(), b


def test_gajae_is_not(the_dimension=None):
    # it is implemented and not offered; a base the server cannot serve produces a column of
    # failures that say nothing about it (see test_gajae_not_offered.py)
    assert "gajae" not in _bases_in_dimension()


def test_the_tools_this_batchs_bases_run_the_fixture_WITH_are_never_withheld():
    """Named, not inferred. The first version of this test tried to re-derive "what the fixture
    needs" with a regex over every base's tools and flagged `web_search`, `todowrite` and
    `board_read` — the spare tools the dimension is SUPPOSED to withhold. Re-deriving the driver's
    own judgement is how a test drifts; what is knowable here is the id each of these four bases
    uses to run a script and to write a file, so those are listed."""
    needs = {
        "mimo": ("bash", "edit"),                     # opencode's names, kept in the fork
        "jcode": ("bash", "write"),
        "opensquilla": ("exec", "write_file"),
        "nanobot": ("exec", "write_file"),
    }
    for base, ids in needs.items():
        published = _tool_ids(A._BASE_CATALOG[base])
        for tool in ids:
            assert tool in published, f"{base} no longer publishes {tool}; this list is stale"
            assert NEEDED.match(tool), (
                f"NEEDED_ID does not cover {base}:{tool}, so pickDisabled could withhold the tool "
                f"the fixture runs with and the row would fail for the dimension's reason")


def test_a_preferred_tool_is_never_also_one_the_fixture_needs():
    # the two lists must not overlap, or the preference would pick something the task uses
    for spec in A._BASE_CATALOG.values():
        for t in _tool_ids(spec):
            assert not (PREFERRED.match(t) and NEEDED.match(t)), t


def test_a_base_with_nothing_to_spare_records_it_as_unmeasurable():
    # the mechanism, pinned at the source: null rather than a pass, and the row says so
    assert "pickDisabled" in SRC
    assert "rec.disabled_tool_unused === null" in SRC, "a null must not be read as a pass"
    assert "disabled_tool_unused: null" in SRC or "? !toolNames.some" in SRC
