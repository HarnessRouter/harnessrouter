"""vibe's catalog must offer exactly the tools a turn declares, and nothing it cannot withhold.

A tool id in the catalog that matches nothing in the runtime is dropped on the way through and
disables nothing while the console reports it as off — the overstatement UHP section 4.3 forbids,
and the whole of what `tool_enforcement: "hard"` claims here.

The list on both sides is MEASURED: the nine tools in the request a real turn on mistral-vibe 2.26.1
sent to the provider, read off a recording proxy (2026-10-15) — the same nine with nothing disabled
and with two disabled.

The withholding was measured at the same door and is not what it first looked like: a disabled tool
is still declared, and its CALL is refused (`decision: "skip"`, `error.code: "tool_denied"`, nothing
written). The first reading of this — "web_search vanished from the declared list" — was a check with
no input, because web_search is not among the nine and was never declared.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import ALL_VIBE_TOOLS, VIBE_PROVIDERS  # noqa: E402


def _offered(base: str) -> set:
    return {tid for tid, _label in A._BASE_CATALOG[base]["tools"]}


def test_the_catalog_offers_exactly_the_runners_measured_list():
    offered = _offered("vibe")
    want = set(ALL_VIBE_TOOLS)
    assert offered == want, (
        f"only in catalog: {offered - want}, only in the runner: {want - offered}")


def test_the_claim_is_hard_because_the_flag_really_withholds():
    assert A._BASE_CATALOG["vibe"]["tool_enforcement"] == "hard"


def test_the_two_dispatchers_are_published_as_tools():
    # `run_typescript` runs a script with the tool registry in scope and `search_tool_functions`
    # looks a tool up by name: they are how this runtime reaches an MCP server's tools, so a person
    # switching tools off has to be able to see them (and the custom-harness dimension must never
    # withhold them — gateway/tests/test_matrix_disabled_tool.py holds that).
    offered = _offered("vibe")
    assert {"run_typescript", "search_tool_functions"} <= offered


def test_it_is_offered_chat_only_and_as_an_openai_custom_format():
    # its provider backend posts to /chat/completions and it has no Messages client at all
    assert "vibe" in A.CHAT_ONLY_BACKENDS
    assert "vibe" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "vibe" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert "vibe" not in A._CUSTOM_FORMAT_BACKENDS["responses"]


def test_every_wired_provider_type_is_one_the_runner_accepts():
    # a wiring row naming a provider type the builder refuses is a 400 at the point of no return
    for (_kind, base), ptype in A._INTEGRATION_WIRING.items():
        if base == "vibe":
            assert ptype in VIBE_PROVIDERS, (base, ptype)


def test_the_catalog_lists_models_and_a_default_it_also_lists():
    entry = A._MODEL_CATALOG["vibe"]
    assert entry["models"], "no models offered"
    assert entry["default"] in entry["models"]
