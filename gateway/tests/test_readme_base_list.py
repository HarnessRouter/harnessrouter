"""The README's "N harness bases today" line names every base the catalog offers, and counts them.

Nothing breaks when a base is missing from that sentence, which is how it drifted: the base
installs, the console offers it, and the first page anyone reads says the product does not have it.
Found on 2026-11-19 while opening the batch's pull request — JiuwenSwarm was in `_BASE_CATALOG`,
in the install order, in the console and in the self-hosting guide, and in none of the README's
thirty-one names. The precedent is Roder (#588), an opt-in base that WAS added to this line in the
pull request that added it, so "opt-in" is not the reason a base may be left out.

`_BASE_CATALOG` is the source of truth (registration point 9) and the sentence is derived from it.
The comparison is on the whole list, parsed, not on substrings: "Pi" is inside "Oh My Pi", so a
substring check passes on a line that has lost Pi itself.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

README = pathlib.Path(__file__).resolve().parents[2] / "README.md"
SENTENCE = re.compile(r"\*\*(\d+) harness bases today:\*\*\s*(.+?)\.\s")


def _sentence() -> tuple[int, list[str]]:
    m = SENTENCE.search(README.read_text())
    assert m, "README.md no longer carries a '**N harness bases today:**' sentence"
    count, listed = int(m.group(1)), m.group(2)
    names = [n.strip() for part in listed.split(" and ") for n in part.split(",")]
    return count, [n for n in names if n]


def _labels() -> set[str]:
    return {str((entry or {}).get("label") or cid) for cid, entry in A._BASE_CATALOG.items()}


def test_every_base_the_catalog_offers_is_named():
    _, names = _sentence()
    missing = sorted(_labels() - set(names))
    assert not missing, "README.md's harness list is missing: " + ", ".join(missing)


def test_no_base_is_named_that_the_catalog_does_not_offer():
    # The other direction: a name here is a promise the console can be asked for.
    _, names = _sentence()
    extra = sorted(set(names) - _labels())
    assert not extra, "README.md names bases the catalog does not offer: " + ", ".join(extra)


def test_the_count_is_the_number_of_names():
    count, names = _sentence()
    assert count == len(names) == len(_labels()), (count, len(names), len(_labels()))
