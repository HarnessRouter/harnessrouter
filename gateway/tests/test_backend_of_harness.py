"""Every base a user can pin a harness to must route to its backend.

The hand-written if-chain this guards against silently missed qwen: a user-created harness on
that base fell through to model-name guessing, and gpt-5.4 on a qwen harness ran on codex.
Derived-from-the-catalog is the fix; this test is the tripwire that makes the NEXT base unable
to reintroduce the class — it enumerates the catalog rather than naming bases, so it cannot go
stale the way the chain did.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402


def test_every_catalog_base_routes_a_user_harness():
    for base, entry in A._BASE_CATALOG.items():
        got = A._backend_of_harness({"base": base})
        assert got == entry["backend"], (
            f"a user-created harness pinned to base '{base}' resolves to {got!r}, not "
            f"'{entry['backend']}' — it would fall through to model-name guessing")


def test_the_stored_aliases_still_resolve():
    assert A._backend_of_harness({"base": "claude"}) == "claude"
    assert A._backend_of_harness({"base": "claude-code"}) == "claude"
    assert A._backend_of_harness({"base": "deepseek-harness"}) == "dsh"
    assert A._backend_of_harness({"base": "omp"}) == "omp"


def test_unknown_base_stays_empty_for_the_caller_to_infer():
    assert A._backend_of_harness({"base": "not-a-base"}) == ""
    assert A._backend_of_harness(None) == ""
