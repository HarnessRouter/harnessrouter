"""A model a channel cannot run as itself is off that channel's table, so the effective map routes it to
one that can: Vercel garbles nemotron-3.5-lightning's tool arguments, Google answers gemini-3.7-flash
with gemini-3.8-flash (both measured 2026-10-08). Each stays served elsewhere."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_vercel_does_not_offer_nemotron_lightning_and_openrouter_does():
    assert "nemotron-3.5-lightning" not in gw._integration_models({"provider": "vercel"})
    assert gw._integration_models({"provider": "openrouter"})["nemotron-3.5-lightning"] == "nvidia/nemotron-3.5-lightning"
    # the rest of the Nemotron family stays on Vercel
    assert "nemotron-3-super" in gw._integration_models({"provider": "vercel"})


def test_google_does_not_offer_gemini_3_7_flash_and_the_aggregators_do():
    assert "gemini-3.7-flash" not in gw._integration_models({"provider": "google"})
    for p in ("vercel", "openrouter", "tokenrouter"):
        assert "gemini-3.7-flash" in gw._integration_models({"provider": p}), p


def test_the_map_routes_each_to_a_channel_that_serves_it(monkeypatch):
    docs = [{"name": "Vercel", "provider": "vercel", "config": {"api_key": "k"}},
            {"name": "Google", "provider": "google", "config": {"api_key": "k"}},
            {"name": "OpenRouter", "provider": "openrouter", "config": {"api_key": "k"}}]

    async def integrations():
        return docs

    async def stored():
        return {}

    monkeypatch.setattr(gw, "_integrations_doc", integrations)
    monkeypatch.setattr(gw, "_model_map_doc", stored)
    import asyncio
    mm = asyncio.run(gw._effective_model_map())
    assert mm["nemotron-3.5-lightning"] == "OpenRouter"
    assert mm["gemini-3.7-flash"] == "Vercel"
    assert mm["nemotron-3-super"] == "Vercel"
