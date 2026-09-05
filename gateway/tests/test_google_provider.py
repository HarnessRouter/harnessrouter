"""A Google AI Studio key is a provider: it serves the catalog's Gemini models on Gemini's
OpenAI-compatible surface for every backend that speaks that shape, and nothing else."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_google_serves_the_catalog_gemini_by_its_own_id():
    assert gw._vendor_models("google") == {"gemini-3.6-flash": "gemini-3.6-flash"}
    assert gw._integration_models({"provider": "google"}) == {"gemini-3.6-flash": "gemini-3.6-flash"}


def test_google_reaches_the_openai_shaped_backends_only():
    for backend in ("hermes", "pi", "dsh", "opencode", "qwen", "cline"):
        assert gw._INTEGRATION_WIRING[("google", backend)] == "openai-api", backend
    for backend in ("claude", "codex"):
        assert ("google", backend) not in gw._INTEGRATION_WIRING, backend


def test_google_is_listed_and_brokered_with_its_endpoint():
    assert "google" in {p for p, _ in gw._INTEGRATION_WIRING}
    assert "google" in gw._BROKERABLE_PROVIDERS
    conn = gw._with_provider_base({"provider": "google", "api_key": "k"})
    assert conn["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
