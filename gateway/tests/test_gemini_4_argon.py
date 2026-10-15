"""Gemini 4 Argon (announced 2026-10-14), read off each vendor's own list that day: Google AI Studio
`gemini-4-argon` (generateContent, 1,048,576 input tokens, thinking), OpenRouter and Vercel
`google/gemini-4-argon` ($2 / $10 per million), each answering as itself. TokenRouter and llmtr do
not list it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_each_vendor_that_serves_it_names_it_as_it_does():
    assert gw._VENDOR_MODELS["google"]["gemini-4-argon"] == "gemini-4-argon"
    assert gw._VENDOR_MODELS["openrouter"]["gemini-4-argon"] == "google/gemini-4-argon"
    assert gw._VENDOR_MODELS["vercel"]["gemini-4-argon"] == "google/gemini-4-argon"
    assert "gemini-4-argon" not in gw._VENDOR_MODELS["tokenrouter"] and "gemini-4-argon" in gw._TOKENROUTER_NO_CHANNEL
    assert "gemini-4-argon" not in gw._VENDOR_MODELS.get("llmtr", {})


def test_every_base_that_offers_the_previous_pro_model_offers_it_first_in_its_family():
    for b, c in gw._MODEL_CATALOG.items():
        if "gemini-3.1-pro-preview" in c["models"]:
            gem = [m for m in c["models"] if m.startswith("gemini")]
            assert gem[0] == "gemini-4-argon", (b, gem)
    assert gw._MODEL_ORDER.count("gemini-4-argon") == 1
