"""jiuwenswarm's catalog must offer exactly the tools a turn declares, and nothing it cannot withhold.

A tool id in the catalog that matches nothing in the runtime is dropped on the way through and
disables nothing while the console reports it as off — the overstatement UHP section 4.3 forbids,
and the whole of what `tool_enforcement: "hard"` claims here.

The list on both sides is MEASURED: read off the requests a real turn on workswarm 0.2.8 sent to the
provider through a recording proxy (2026-11-18), with nothing switched off and then with a
nine-name policy, which declared exactly those nine. It is NOT the host permission registry's list
(`permission.get` reports 52 names, a different set, including tools this surface never declares),
and it is not the model's narration of its own tools.

Two of the offered ids are DISPATCHERS: with progressive tool exposure on — the shipped config's
default, which the runner keeps by starting from the package's own template — an MCP server's tools
are not declared at all, and the model reaches them through `tool_search` and then `tool_call`. A
judge reading tool NAMES alone will therefore not see an MCP call here, and withholding either would
take the MCP path with it.

Two ids the runtime declares are deliberately NOT offered:

  * `ask_user` — a one-shot machine run has nobody attached to answer it, so it is denied on every
    turn rather than offered and then ending one.
  * the `subagent_*` family — a custom agent definition, which is how this runner drives the base,
    does not declare those six at all (measured on the wire: 13 declared for a 19-name policy, and
    the six missing were exactly those).
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import ALL_JIUWENSWARM_TOOLS, JIUWENSWARM_PROVIDERS  # noqa: E402


def _offered(base: str) -> set:
    return {tid for tid, _label in A._BASE_CATALOG[base]["tools"]}


def test_the_catalog_offers_exactly_the_runners_measured_list():
    offered = _offered("jiuwenswarm")
    want = set(ALL_JIUWENSWARM_TOOLS)
    assert offered == want, (
        f"only in catalog: {offered - want}, only in the runner: {want - offered}")


def test_every_offered_tool_has_a_label_a_person_can_read():
    for tid, label in A._BASE_CATALOG["jiuwenswarm"]["tools"]:
        assert label and label != tid, tid


def test_the_claim_is_hard_because_the_policy_really_withholds():
    # Measured: with write_file denied the model's call was refused at execution
    # (`[PERMISSION_DENIED] run policy`) and the file was not created.
    assert A._BASE_CATALOG["jiuwenswarm"]["tool_enforcement"] == "hard"


def test_the_two_tools_nobody_could_answer_or_withhold_are_not_offered():
    offered = _offered("jiuwenswarm")
    assert "ask_user" not in offered
    assert not [t for t in offered if t.startswith("subagent_")]


def test_the_mcp_path_is_offered_whole():
    # Its MCP tools arrive as mcp_<server>_<tool> and are reached through these two; an offer that
    # kept one and dropped the other would describe a path that cannot be walked.
    offered = _offered("jiuwenswarm")
    assert {"tool_search", "tool_call"} <= offered


def test_every_provider_the_runner_accepts_can_be_wired_to_this_base():
    wired = {runner for (_integration, base), runner in A._INTEGRATION_WIRING.items()
             if base == "jiuwenswarm"}
    assert wired, "no integration can drive this base"
    assert wired <= JIUWENSWARM_PROVIDERS, wired - JIUWENSWARM_PROVIDERS


def test_a_direct_anthropic_connection_is_not_claimed():
    # The runtime has an Anthropic dialect (`client_provider: Anthropic`, /v1/messages) and no turn
    # has run on it here, so the row is absent rather than nearly true. When one does, this test is
    # what has to change with it.
    assert ("anthropic", "jiuwenswarm") not in A._INTEGRATION_WIRING
    assert "anthropic" not in JIUWENSWARM_PROVIDERS


def test_the_base_is_a_chat_completions_client_so_a_responses_only_id_is_not_offered():
    assert "jiuwenswarm" in A.CHAT_ONLY_BACKENDS
    assert "jiuwenswarm" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "jiuwenswarm" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert "jiuwenswarm" not in A._CUSTOM_FORMAT_BACKENDS["responses"]
