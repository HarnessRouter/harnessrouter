"""The console must never offer a MiniMax Code tool toggle the runner cannot enforce, nor a model the
base cannot drive.

The runner withholds a tool by leaving it out of the config's `agents.default.tools` allowlist (or,
for `task`, by switching the delegation feature off); a name outside runner/server.py's
_MINIMAX_TOOLS matches nothing, so a catalog id outside it would be a toggle reported as off that
changes nothing — the overstatement UHP section 4.3 forbids, and the reason this base may claim
`tool_enforcement: "hard"` at all.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import BACKENDS, _MINIMAX_TOOLS  # noqa: E402


def test_every_advertised_minimax_tool_can_actually_be_withheld():
    advertised = {tid for tid, _label in A._BASE_CATALOG["minimax"]["tools"]}
    assert advertised == set(_MINIMAX_TOOLS)


def test_minimax_account_services_are_not_offered():
    """web_search and website_deploy are MiniMax's hosted services, never enabled here."""
    ids = {tid for tid, _ in A._BASE_CATALOG["minimax"]["tools"]}
    assert not ids & {"web_search", "website_deploy"}


def test_minimax_is_registered_as_itself_and_claims_hard_enforcement():
    base = A._BASE_CATALOG["minimax"]
    assert (base["backend"], base["label"], base["tool_enforcement"]) == ("minimax", "MiniMax Code", "hard")


def test_minimax_is_chat_completions_only_and_offers_no_responses_only_id():
    assert "minimax" in A.CHAT_ONLY_BACKENDS
    assert not set(A._MODEL_CATALOG["minimax"]["models"]) & A.RESPONSES_ONLY_MODELS


def test_the_default_is_minimax_s_own_model_and_agrees_with_the_runner():
    cat = A._MODEL_CATALOG["minimax"]
    assert cat["default"] == "minimax-m3" == BACKENDS["minimax"]["default_model"]
    assert "minimax-m3" in cat["models"]


def test_minimax_is_wired_like_kimi_and_speaks_the_custom_openai_format():
    kimi = {k[0]: v for k, v in A._INTEGRATION_WIRING.items() if k[1] == "kimi"}
    mm = {k[0]: v for k, v in A._INTEGRATION_WIRING.items() if k[1] == "minimax"}
    assert mm == kimi
    assert "minimax" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "minimax" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    for runner_provider in mm.values():
        assert runner_provider in BACKENDS["minimax"]["providers"]
