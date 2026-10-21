"""fast-agent's catalog must offer only the tools it can really withhold.

This framework ships NO tools of its own — they come from MCP servers — and `-x` turns on a local
runtime that declares four: bash, process, read_text_file, edit_file (measured off a turn's own
request on 0.10.45; a turn WITHOUT -x declared zero and answered that it had no file-system tool).

Three of those four have a switch, which is why three are offered:
  bash            `--no-shell`, measured on a RESUMED session — omitting -x is not enough there,
                  because the session brings its runtime back
  read_text_file  `shell.enable_read_text_file: false` in the config this runner writes
  edit_file       `shell.write_text_file_mode: "off"` in the same file
`process` is the shell runtime's second tool and has no switch of its own: offering it would either
disable nothing or take bash away with it, and a toggle that does neither of the things it says is
the overstatement UHP section 4.3 forbids.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import ALL_FAST_AGENT_TOOLS, FAST_AGENT_PROVIDERS  # noqa: E402


def _offered(base: str) -> set:
    return {tid for tid, _label in A._BASE_CATALOG[base]["tools"]}


def test_the_catalog_offers_exactly_the_three_with_a_switch():
    offered = _offered("fast-agent")
    want = set(ALL_FAST_AGENT_TOOLS)
    assert offered == want, (
        f"only in catalog: {offered - want}, only in the runner: {want - offered}")
    assert "process" not in offered, "it has no switch of its own"


def test_the_claim_is_hard_and_the_base_is_chat_only():
    assert A._BASE_CATALOG["fast-agent"]["tool_enforcement"] == "hard"
    assert "fast-agent" in A.CHAT_ONLY_BACKENDS
    assert "fast-agent" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "fast-agent" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]


def test_its_hyphenated_id_routes():
    assert "fast-agent" in A._SUPPORTED_BASES
    assert A._HID_PREFIX_RE.match("/fast-agent/v1/responses")


def test_every_wired_provider_type_is_one_the_runner_accepts():
    for (_kind, base), ptype in A._INTEGRATION_WIRING.items():
        if base == "fast-agent":
            assert ptype in FAST_AGENT_PROVIDERS, (base, ptype)


def test_the_catalog_lists_models_and_a_default_it_also_lists():
    entry = A._MODEL_CATALOG["fast-agent"]
    assert entry["models"] and entry["default"] in entry["models"]
