"""A backend wired to one provider runs through the integration that can drive it, even when the org's
model map names one that cannot (2026-09-06: the gemini backend on a default map)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

VERCEL = {"name": "Vercel AI Gateway", "provider": "vercel", "config": {"api_key": "v", "base_url": "https://ai-gateway.vercel.sh/v1"}}
GOOGLE = {"name": "Google AI Studio", "provider": "google", "config": {"api_key": "g", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"}}


def test_the_mapped_integration_is_kept_when_it_drives_the_backend():
    assert gw._integration_driving([GOOGLE, VERCEL], "pi", "gemini-3.5-flash", "Vercel AI Gateway") is VERCEL


def test_a_backend_the_mapping_cannot_drive_falls_through_to_one_that_can():
    assert gw._integration_driving([VERCEL, GOOGLE], "gemini", "gemini-3.5-flash", "Vercel AI Gateway") is GOOGLE
    assert gw._integration_driving([VERCEL], "gemini", "gemini-3.5-flash", "Vercel AI Gateway") is None
    # an integration that can drive the backend but does not serve the id is not it
    assert gw._integration_driving([VERCEL, GOOGLE], "gemini", "gpt-5.4", "Vercel AI Gateway") is None


def test_the_turn_and_the_picker_agree(monkeypatch):
    async def mm(): return {"gemini-3.5-flash": "Vercel AI Gateway", "gpt-5.4": "Vercel AI Gateway"}
    async def docs(): return [VERCEL, GOOGLE]
    async def chain(org, backend, _): return []
    monkeypatch.setattr(gw, "_effective_model_map", mm)
    monkeypatch.setattr(gw, "_integrations_doc", docs)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    conn = asyncio.run(gw._mapped_integration_conn("gemini", "gemini-3.5-flash"))
    assert conn and conn["name"] == "integration:Google AI Studio" and conn["provider"] == "google"
    assert conn.get("model") == "gemini-3.5-flash"
    assert asyncio.run(gw._mapped_integration_conn("gemini", "gpt-5.4")) is None
    servable = asyncio.run(gw._servable_models("org1", "gemini"))
    assert "gemini-3.5-flash" in servable and "gpt-5.4" not in servable
    pi = asyncio.run(gw._mapped_integration_conn("pi", "gemini-3.5-flash"))
    assert pi and pi["name"] == "integration:Vercel AI Gateway"
