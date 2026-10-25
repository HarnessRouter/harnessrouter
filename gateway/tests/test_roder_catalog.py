"""Only Responses connections may be offered to the Roder native app-server adapter."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A


def test_roder_registration_is_responses_only():
    assert A._BASE_CATALOG["roder"]["backend"] == "roder"
    assert A._BASE_CATALOG["roder"]["tool_enforcement"] == "hard"
    assert "roder" in A._CUSTOM_FORMAT_BACKENDS["responses"]
    assert "roder" not in A._CUSTOM_FORMAT_BACKENDS["openai"]
    assert "roder" not in A._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert A._INTEGRATION_WIRING[("openai", "roder")] == "openai"
    assert A._INTEGRATION_WIRING[("azure-foundry", "roder")] == "azure"
    assert ("anthropic", "roder") not in A._INTEGRATION_WIRING
    assert A._backend_of_builtin("roder") == "roder"


def test_roder_offers_current_model_families_and_default():
    models = A._MODEL_CATALOG["roder"]["models"]
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
    import roder_backend
    assert A._MODEL_CATALOG["roder"]["default"] == roder_backend.DEFAULT_MODEL == "gpt-6.1-sol"
    assert {"gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna",
            "claude-fable-5-1", "claude-opus-5.5", "gemini-4-argon",
            "grok-4.6", "deepseek-v4.1-flash", "kimi-k3", "qwen3.8-max"} <= set(models)
    for provider in ("openrouter", "vercel", "llmtr", "tokenrouter", "harnessrouter"):
        assert A._INTEGRATION_WIRING[(provider, "roder")] == "tokenrouter"
