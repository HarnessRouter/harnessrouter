"""vtcode's catalog must offer exactly the tools its own runtime reports, and nothing it cannot
withhold.

Both lists are MEASURED on 0.177.0: `vtcode schema tools` reports five built-in tools, and the
request a real turn sent to the provider declared those same five. Everything else this runtime can
do (code_search, web_search, web_fetch, cron, an MCP server's tools) is DEFERRED behind
`search_tools` — the model calls it to have those definitions sent — which is why the list is short
and why it must stay short: a toggle for a tool the runtime never declares disables nothing while
the console reports it as off, the overstatement UHP section 4.3 forbids.

The withholding was measured at the strongest door this product has seen: with exec_command left
out of `[automation.full_auto].allowed_tools`, the model reported that the only tools it had were
the other four, and a call it made anyway came back `outcome: "hook_denied"` with nothing run.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import ALL_VTCODE_TOOLS, VTCODE_PROVIDERS  # noqa: E402


def _offered(base: str) -> set:
    return {tid for tid, _label in A._BASE_CATALOG[base]["tools"]}


def test_the_catalog_offers_exactly_the_five_the_runtime_reports():
    offered = _offered("vtcode")
    want = set(ALL_VTCODE_TOOLS)
    assert offered == want, (
        f"only in catalog: {offered - want}, only in the runner: {want - offered}")


def test_the_claim_is_hard_because_the_allow_list_is_a_hard_boundary():
    assert A._BASE_CATALOG["vtcode"]["tool_enforcement"] == "hard"


def test_it_is_chat_only_and_an_openai_custom_format():
    assert "vtcode" in A.CHAT_ONLY_BACKENDS
    assert "vtcode" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "vtcode" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert "vtcode" not in A._CUSTOM_FORMAT_BACKENDS["responses"]


def test_every_wired_provider_type_is_one_the_runner_accepts():
    for (_kind, base), ptype in A._INTEGRATION_WIRING.items():
        if base == "vtcode":
            assert ptype in VTCODE_PROVIDERS, (base, ptype)


def test_the_catalog_lists_models_and_a_default_it_also_lists():
    entry = A._MODEL_CATALOG["vtcode"]
    assert entry["models"]
    assert entry["default"] in entry["models"]
