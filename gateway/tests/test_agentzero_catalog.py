"""The agentzero base (Agent Zero v2.13) in the gateway's catalogs.

The tool ids must be the ones runner/agentzero_driver.py maps to Agent Zero's _tool_access ids: an id
outside that table would be a console toggle that disables nothing while reporting it off, the
overstatement UHP 4.3 forbids and the reason the base may claim `tool_enforcement: "hard"`.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
import agentzero_driver as drv  # noqa: E402


def test_every_offered_tool_can_be_withheld():
    offered = {tid for tid, _label in A._BASE_CATALOG["agentzero"]["tools"]}
    assert offered == set(drv.TOOLS)
    assert A._BASE_CATALOG["agentzero"]["tool_enforcement"] == "hard"
    assert A._BASE_CATALOG["agentzero"]["backend"] == "agentzero"


def test_the_tools_that_cannot_run_here_are_not_offered():
    offered = {tid for tid, _label in A._BASE_CATALOG["agentzero"]["tools"]}
    for name in ("search_engine", "document_query", "scheduler", "notify_user", "a2a_chat",
                 "browser", "memory_load", "input"):
        assert name not in offered


def test_it_is_driven_through_the_relay_on_the_openai_shape():
    for provider in ("anthropic", "openai", "openrouter", "tokenrouter", "vercel", "google",
                     "custom", "harnessrouter"):
        assert A._INTEGRATION_WIRING.get((provider, "agentzero")), provider
    assert "agentzero" in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "agentzero" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert "agentzero" in A.CHAT_ONLY_BACKENDS


def test_the_catalog_offers_no_responses_only_id():
    models = set(A._MODEL_CATALOG["agentzero"]["models"])
    assert models and not (models & A.RESPONSES_ONLY_MODELS)
    assert A._MODEL_CATALOG["agentzero"]["default"] in models
