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
        if "gemini-3.1-pro-preview" in c["models"] and "gemini-4-argon" not in gw._NOT_OFFERED.get(b, ()):
            gem = [m for m in c["models"] if m.startswith("gemini")]
            assert gem[0] == "gemini-4-argon", (b, gem)
    assert gw._MODEL_ORDER.count("gemini-4-argon") == 1


def test_two_pairs_are_off_after_deck_conversations_that_changed_models():
    """fast-agent + gemini-4-argon and docker-agent + grok-4.20 failed on the hosted service in deck conversations
    that changed models (2026-10-27; Richard: "Hide those two pairs"). Each base keeps the rest of the family."""
    assert "gemini-4-argon" not in gw._MODEL_CATALOG["fast-agent"]["models"]
    assert "grok-4.20" not in gw._MODEL_CATALOG["docker-agent"]["models"]
    assert "gemini-3.8-flash" in gw._MODEL_CATALOG["fast-agent"]["models"]
    assert "grok-4.6" in gw._MODEL_CATALOG["docker-agent"]["models"]
