"""docker-agent's catalog must offer exactly the tools its toolsets bring, and nothing it cannot
withhold.

Both lists are MEASURED off a real turn's own request on v1.150.0 (2026-10-16): the four toolsets
this runner declares — filesystem, shell, todo, think — put fifteen tools in front of the model.

The withholding is by TOOLSET: a toolset's `tools` key is an include list and there is no per-tool
deny, so the runner narrows the list (and drops a toolset whose every tool was withheld). Measured
through the product's own path: with write_file, edit_file and shell disabled, the model reported
that none of its remaining tools could create or edit a file, and nothing was written.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import ALL_DOCKER_AGENT_TOOLS, DOCKER_AGENT_PROVIDERS  # noqa: E402


def _offered(base: str) -> set:
    return {tid for tid, _label in A._BASE_CATALOG[base]["tools"]}


def test_the_catalog_offers_exactly_what_the_toolsets_bring():
    offered = _offered("docker-agent")
    want = set(ALL_DOCKER_AGENT_TOOLS)
    assert offered == want, (
        f"only in catalog: {offered - want}, only in the runner: {want - offered}")


def test_the_claim_is_hard_and_the_base_is_chat_only():
    assert A._BASE_CATALOG["docker-agent"]["tool_enforcement"] == "hard"
    assert "docker-agent" in A.CHAT_ONLY_BACKENDS
    assert "docker-agent" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "docker-agent" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]


def test_its_hyphenated_id_still_routes():
    # the only base id besides claude-code with a hyphen in it; the per-harness URL pattern is
    # derived from the catalog with re.escape, so this is a real check rather than a formality
    assert "docker-agent" in A._SUPPORTED_BASES
    assert A._HID_PREFIX_RE.match("/docker-agent/v1/responses")


def test_every_wired_provider_type_is_one_the_runner_accepts():
    for (_kind, base), ptype in A._INTEGRATION_WIRING.items():
        if base == "docker-agent":
            assert ptype in DOCKER_AGENT_PROVIDERS, (base, ptype)


def test_the_catalog_lists_models_and_a_default_it_also_lists():
    entry = A._MODEL_CATALOG["docker-agent"]
    assert entry["models"]
    assert entry["default"] in entry["models"]
