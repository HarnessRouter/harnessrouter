"""The self-hosting guide's "Connection `provider`" table must name every base the wiring allows.

Nothing breaks when a base is missing from that table, which is exactly why it drifted: an operator
reads it to decide which key to buy, and a base absent from a row reads as "this provider cannot
drive it". Found on 2026-11-19 while adding the nineteenth registration point in
docs/harness-verification.md: JiuwenSwarm was in none of the nine rows its wiring allows, Roder in
none of its seven, and the `google` row was missing Docker Agent and fast-agent.

`_INTEGRATION_WIRING` is the source of truth (registration point 10) and the table is derived from
it, so this test compares the two and names what is missing. A provider row the table does not carry
at all is left alone: the table is operator-facing and need not list a provider nobody can buy.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

GUIDE = pathlib.Path(__file__).resolve().parents[2] / "docs" / "self-hosting-guide.md"
# The CATALOG's id and the WIRING's backend name are not always the same word: the console offers
# `claude-code` and `gemini-cli` while the wiring (and the runner) say `claude` and `gemini`, which
# is the same pair of names scripts/support-matrix/render.py keeps in its HARNESS_BACKEND map.
BACKEND = {"claude-code": "claude", "gemini-cli": "gemini"}


def _label(backend: str) -> str:
    """The operator's name for a backend, as the table writes it."""
    for cid, entry in A._BASE_CATALOG.items():
        if BACKEND.get(cid, cid) == backend:
            return str((entry or {}).get("label") or cid)
    return backend


def _rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in GUIDE.read_text().splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0].startswith("`") and cells[0].endswith("`"):
            rows[cells[0].strip("`")] = cells[1]
    return rows


def test_the_table_has_a_row_for_the_providers_a_base_can_be_wired_to():
    rows = _rows()
    assert {"openai", "anthropic", "custom", "tokenrouter"} <= set(rows), sorted(rows)


def test_every_wired_pairing_is_named_in_its_providers_row():
    rows = _rows()
    missing = []
    for provider, base in sorted(A._INTEGRATION_WIRING):
        if provider not in rows:
            continue
        label = _label(base)
        if label not in rows[provider]:
            missing.append(f"{provider} -> {label}")
    assert not missing, "docs/self-hosting-guide.md's provider table is missing: " + ", ".join(missing)


def test_a_base_that_is_named_is_one_the_wiring_allows():
    # The other direction, which is the more dangerous one: a row that promises a pairing the
    # router refuses sends an operator to buy a key that cannot drive their base.
    rows = _rows()
    labels = {_label(BACKEND.get(cid, cid)): BACKEND.get(cid, cid) for cid in A._BASE_CATALOG}
    for provider, cell in rows.items():
        for label, base in labels.items():
            if label not in cell:
                continue
            # a longer label that contains a shorter one (goose / goose-cloud) is not a match
            assert A._INTEGRATION_WIRING.get((provider, base)) or any(
                lbl != label and label in lbl and lbl in cell for lbl in labels), (
                f"the guide says {provider} drives {label}, and the wiring has no such row")
