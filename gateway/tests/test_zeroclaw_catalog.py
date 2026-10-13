"""The zeroclaw base as the gateway offers it, held to what the runner can actually do.

  * the tool ids are the runner's ALL_ZEROCLAW_TOOLS — the tools zeroclaw 0.8.5 offered a session
    under the runner's config, as the agent listed them — so no console toggle names a tool the
    risk profile's `excluded_tools` cannot withhold (UHP section 4.3)
  * the ids the runner never offers are not toggles at all
  * every provider wiring row maps to a provider the runner accepts for this backend, and a
    Responses-only model is not offered: zeroclaw's `custom` provider speaks chat/completions
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import ALL_ZEROCLAW_TOOLS, BACKENDS, ZEROCLAW_PROVIDERS, _ZEROCLAW_NEVER  # noqa: E402


def _offered() -> set:
    return {tid for tid, _label in A._BASE_CATALOG["zeroclaw"]["tools"]}


def test_zeroclaw_offers_exactly_the_tools_the_runner_can_withhold():
    offered = _offered()
    assert offered == set(ALL_ZEROCLAW_TOOLS), (
        f"only in catalog: {offered - set(ALL_ZEROCLAW_TOOLS)}, "
        f"only in the runner: {set(ALL_ZEROCLAW_TOOLS) - offered}")
    assert not offered & set(_ZEROCLAW_NEVER)
    assert A._BASE_CATALOG["zeroclaw"]["tool_enforcement"] == "hard"


def test_zeroclaw_is_a_base_the_runner_can_execute_and_connect():
    entry = A._BASE_CATALOG["zeroclaw"]
    assert entry["backend"] == "zeroclaw" and entry["backend"] in BACKENDS
    assert A._MODEL_CATALOG["zeroclaw"]["models"]
    rows = {p: rp for (p, b), rp in A._INTEGRATION_WIRING.items() if b == "zeroclaw"}
    assert rows and set(rows.values()) <= ZEROCLAW_PROVIDERS
    # wired row for row with nanobot, the other chat/completions base driven through the relay
    assert rows == {p: rp for (p, b), rp in A._INTEGRATION_WIRING.items() if b == "nanobot"}


def test_zeroclaw_is_chat_completions_only():
    assert "zeroclaw" in A.CHAT_ONLY_BACKENDS
    assert not set(A._MODEL_CATALOG["zeroclaw"]["models"]) & A.RESPONSES_ONLY_MODELS
    assert "zeroclaw" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "zeroclaw" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]


def test_a_model_the_matrix_failed_twice_is_not_offered():
    assert "llama-3.3-70b" not in A._MODEL_CATALOG["zeroclaw"]["models"]
    # withheld per base, not from the catalog: other bases still offer it
    assert any("llama-3.3-70b" in e["models"] for b, e in A._MODEL_CATALOG.items() if b != "zeroclaw")
