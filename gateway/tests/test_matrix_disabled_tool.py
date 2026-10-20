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


def test_this_batchs_bases_are_there():
    # batch 4, the same check as above for the bases added with it
    for b in ("vibe", "docker-agent", "fast-agent", "dcode"):
        assert b in _bases_in_dimension(), b
    # vtcode is NOT here: implemented and not offered (test_vtcode_not_offered.py)
    assert "vtcode" not in _bases_in_dimension()


def test_the_plugin_matrix_knows_this_batchs_bases_too():
    """The plugin dimension has its own base list, and a base missing from it is never measured
    there — the same silent gap the custom-harness list has. Found while running this batch's
    steps in order: the five bases were in the custom-harness dimension and not in this one."""
    src = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / "support-matrix"
           / "plugins" / "run-matrix.py").read_text()
    # the literal's own brackets, matched: a comment inside it mentions `[[mcp.servers]]`, so
    # cutting at the first "]" reads part of a comment as the whole list (it did, once)
    start = src.index("BASES = [") + len("BASES = ")
    depth, end = 0, start
    for i, ch in enumerate(src[start:], start):
        depth += (ch == "[") - (ch == "]")
        if depth == 0:
            end = i + 1
            break
    bases = src[start:end]
    for b in ("vibe", "docker-agent", "fast-agent", "dcode"):
        assert f'"{b}"' in bases, (b, bases[-200:])


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
        # vibe: measured off a real turn's own request, where these are the names it declares. Its
        # two DISPATCHERS matter here too — `run_typescript` runs a script with the tool registry
        # in scope and `search_tool_functions` looks a tool up by name, which is how this runtime
        # reaches an MCP server — so they are named as tools the fixture needs rather than left to
        # a regex that does not match them.
        "vibe": ("bash", "write_file", "run_typescript", "search_tool_functions"),
        # docker-agent: `shell` runs the skill's script and `write_file` is how it writes. Its
        # `think` and the four todo tools are the spares the dimension may withhold.
        "docker-agent": ("shell", "write_file", "read_file"),
        # fast-agent publishes exactly three and the fixture needs all three: bash runs the
        # skill's script, read_text_file reads, edit_file writes. So its row records the claim as
        # unmeasurable rather than withholding one of them — which is what pickDisabled returning
        # null means, and what the dimension already does for aider.
        "fast-agent": ("bash", "read_text_file", "edit_file"),
        # dcode: `execute` runs the skill's script and `write_file` is how it writes. Of its seven
        # the only one the fixture never needs is `delete`, which is why NEEDED_ID deliberately
        # does not match it — it is this base's one spare for pickDisabled.
        "dcode": ("execute", "write_file", "ls", "edit_file", "glob", "grep"),
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


def test_the_artifact_card_check_reads_the_session_not_only_the_turn():
    """The cards rule compares what the page renders against what the SESSION produced.

    It used to compare against the artifact TURN alone, which assumed no earlier turn ever writes
    a file. Measured on 2026-10-19: vtcode on gemini-3.1-pro-preview wrote `output.txt` carrying
    its answer on the FOLLOW-UP turn, and the artifact row then failed with "the cards do not
    match the record: cards [output.txt,hello-vtcode.txt] vs record [hello-vtcode.txt]" — both the
    page and the record were right. What the rule is FOR is still enforced: every file the turn
    stored has a card, no card is rendered twice (the 2026-09-07 defect), and no card names a file
    no turn produced.
    """
    src = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / "support-matrix"
           / "run.mjs").read_text()
    assert "noDuplicateCards" in src and "everyCardWasProduced" in src
    assert "everyWantHasACard" in src
    # the session's own turns are what it reads for that third condition
    assert "sessionFiles" in src and "turnsOf(rec.sid)" in src
