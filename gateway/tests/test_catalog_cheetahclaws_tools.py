"""The console must never offer a CheetahClaws tool toggle the runner cannot enforce.

The driver withholds a disabled tool through the CLI's own `disabled_tools`, which matches registry
NAMES exactly: a catalog id outside the runner's CHEETAHCLAWS_TOOLS would be a toggle that is
reported as off and changes nothing, the overstatement UHP section 4.3 forbids and the reason this
backend may claim `tool_enforcement: "hard"`. CHEETAHCLAWS_TOOLS is the `tools` array of a live
3.5.88 request captured at a stub; this test holds the catalog to it.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import BACKENDS, CHEETAHCLAWS_TOOLS  # noqa: E402


def test_every_advertised_tool_can_actually_be_withheld():
    advertised = {tid for tid, _label in A._BASE_CATALOG["cheetahclaws"]["tools"]}
    assert advertised == set(CHEETAHCLAWS_TOOLS), (
        f"only in catalog: {advertised - set(CHEETAHCLAWS_TOOLS)}, "
        f"only in the runner: {set(CHEETAHCLAWS_TOOLS) - advertised}")


def test_a_tool_the_driver_always_withholds_is_not_offered():
    import cheetahclaws_driver as drv
    offered = {tid for tid, _ in A._BASE_CATALOG["cheetahclaws"]["tools"]}
    assert not offered & set(drv.ALWAYS_WITHHELD)
    assert not offered & set(drv.OPTIONAL_TOOLS)


def test_cheetahclaws_is_registered_as_a_chat_completions_base():
    base = A._BASE_CATALOG["cheetahclaws"]
    assert base["backend"] == "cheetahclaws" and base["tool_enforcement"] == "hard"
    assert "cheetahclaws" in A.CHAT_ONLY_BACKENDS
    assert "cheetahclaws" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "cheetahclaws" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert "cheetahclaws" not in A._CUSTOM_FORMAT_BACKENDS["responses"]
    assert "cheetahclaws" in BACKENDS


def test_it_is_wired_to_the_chat_completions_connections_only():
    wired = {prov: runner for (prov, backend), runner in A._INTEGRATION_WIRING.items()
             if backend == "cheetahclaws"}
    # the hosted HarnessRouter API is TokenRouter-shaped and is wired wherever TokenRouter is
    # (test_harnessrouter_provider.py)
    assert wired == {"openrouter": "openai-api", "tokenrouter": "tokenrouter",
                     "vercel": "tokenrouter", "custom": "openai-api", "harnessrouter": "tokenrouter"}
    assert set(wired.values()) <= set(BACKENDS["cheetahclaws"]["providers"])
