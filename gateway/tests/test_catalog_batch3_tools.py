"""The console must never offer a toggle the runner cannot enforce, on any of this batch's bases.

A tool id in the catalog that matches nothing in the runtime is dropped on the way through and
disables nothing while the console reports it as off — the overstatement UHP section 4.3 forbids,
and the whole of what `tool_enforcement: "hard"` claims. These tests hold each catalog to the
runner's own measured list, which is also where the measurement is recorded:

  jcode   ALL_JCODE_TOOLS   — the model's own account of its tools on v0.90.0, with
                              --disabled-tools write proving the switch is enforcement
  nanobot ALL_NANOBOT_TOOLS — the 22 its loop logs at start-up on 0.3.5

mimo and opensquilla are checked differently and for stated reasons, below.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import (ALL_JCODE_TOOLS, ALL_NANOBOT_TOOLS,  # noqa: E402
                    BACKENDS, _opencode_denies)


def _offered(base: str) -> set:
    return {tid for tid, _label in A._BASE_CATALOG[base]["tools"]}


def test_jcode_offers_only_tools_the_deny_list_can_withhold():
    offered = _offered("jcode")
    assert offered == ALL_JCODE_TOOLS, (
        f"only in catalog: {offered - ALL_JCODE_TOOLS}, only in the runner: {ALL_JCODE_TOOLS - offered}")


def test_nanobot_offers_exactly_the_tools_its_loop_registers():
    offered = _offered("nanobot")
    assert offered == set(ALL_NANOBOT_TOOLS), (
        f"only in catalog: {offered - set(ALL_NANOBOT_TOOLS)}, "
        f"only in the runner: {set(ALL_NANOBOT_TOOLS) - offered}")


def test_mimo_offers_only_permission_keys_the_config_actually_denies():
    # Its switch is opencode's `permission.<key>: "deny"`, and the runner drops a key outside the
    # set opencode understands rather than writing one that matches no tool. So the test is not a
    # list comparison but the real question: does every id the console shows produce a deny?
    for tid in sorted(_offered("mimo")):
        assert _opencode_denies([tid]) == {tid: "deny"}, tid


def test_opensquilla_does_not_claim_an_enforcement_it_has_not_got():
    # Its agent CLI has no per-tool deny list — `--permissions` picks a posture — so the disabled
    # set reaches the model as an instruction in AGENTS.md, and the catalog must say so. UHP 4.3
    # forbids understating this as much as overstating it.
    assert A._BASE_CATALOG["opensquilla"]["tool_enforcement"] == "instruction"


def test_the_four_with_a_real_switch_claim_hard():
    for base in ("mimo", "jcode", "nanobot"):
        assert A._BASE_CATALOG[base]["tool_enforcement"] == "hard", base


def test_every_base_in_the_catalog_is_one_the_runner_can_execute():
    for base in ("mimo", "jcode", "opensquilla", "nanobot"):
        assert base in A._BASE_CATALOG
        assert A._BASE_CATALOG[base]["backend"] in BACKENDS
        assert base in A._MODEL_CATALOG and A._MODEL_CATALOG[base]["models"]
        # Every id the picker offers has to be drivable by at least one wiring row, or the base is
        # a row in the console that cannot be connected to anything.
        assert any(b == base for _p, b in A._INTEGRATION_WIRING), base


# ── the notice surface ────────────────────────────────────────────────────────────────────────
# An unrecognised `system` subtype is dropped here in silence, so a runner that emits one is
# writing to a surface that does not exist. `notice` is the third subtype this translator knows,
# and it exists because opensquilla says things about a turn that are neither its answer nor a
# failure — "Provider context limit reached; compacting older context before retrying" — and a
# person reading a turn that took minutes and lost its earlier context has no other way to learn why.

def test_a_cli_notice_is_rendered_as_a_note_on_the_reply():
    out = A._blocks_from_canonical({"type": "system", "subtype": "notice",
                                    "text": "Provider context limit reached; compacting."})
    assert len(out) == 1
    kind, text = out[0]
    assert kind == "text"
    assert "Provider context limit reached; compacting." in text
    assert text.strip().startswith("_Note:")


def test_an_empty_notice_renders_nothing():
    assert A._blocks_from_canonical({"type": "system", "subtype": "notice", "text": ""}) == []
    assert A._blocks_from_canonical({"type": "system", "subtype": "notice", "text": "   "}) == []


def test_a_notice_is_bounded():
    out = A._blocks_from_canonical({"type": "system", "subtype": "notice", "text": "x" * 5000})
    assert len(out[0][1]) < 600


def test_a_subtype_nobody_renders_still_produces_nothing():
    # The reason the runner may not invent one: this is silent, not an error.
    assert A._blocks_from_canonical({"type": "system", "subtype": "made_up", "text": "hi"}) == []
