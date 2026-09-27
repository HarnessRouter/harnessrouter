"""The console must never offer a Grok Build tool toggle the runner cannot enforce.

grok's --disallowed-tools matches the CLI's INTERNAL tool id, which equals the name the model sees
for every offered tool but the shell (`run_terminal_command` on the wire, `run_terminal_cmd` on the
policy side; the wire name matches nothing — measured on 1.0.41). The runner's _GROK_TOOL_POLICY_IDS
carries that mapping, and a catalog id outside it would be a toggle reported as off that changes
nothing, the overstatement UHP section 4.3 forbids."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import _GROK_ALWAYS_WITHHELD, _GROK_TOOL_POLICY_IDS  # noqa: E402


def test_every_advertised_grok_tool_can_actually_be_withheld():
    advertised = {tid for tid, _label in A._BASE_CATALOG["grok"]["tools"]}
    assert advertised == set(_GROK_TOOL_POLICY_IDS)


def test_a_tool_the_runner_always_withholds_is_not_offered():
    advertised = {tid for tid, _label in A._BASE_CATALOG["grok"]["tools"]}
    assert not advertised & set(_GROK_ALWAYS_WITHHELD)
    assert "read_file" not in advertised   # cannot be withheld alone


def test_grok_registration():
    base = A._BASE_CATALOG["grok"]
    assert base["backend"] == "grok" and base["label"] == "Grok Build" and base["tool_enforcement"] == "hard"
    assert "grok" in A.CHAT_ONLY_BACKENDS
    assert "grok" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "grok" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    for prov in ("vercel", "google", "custom", "openrouter", "tokenrouter", "harnessrouter"):
        assert (prov, "grok") in A._INTEGRATION_WIRING
    cat = A._MODEL_CATALOG["grok"]
    assert cat["default"] in cat["models"] and cat["default"].startswith("grok-")
    assert not set(cat["models"]) & set(A.RESPONSES_ONLY_MODELS)
