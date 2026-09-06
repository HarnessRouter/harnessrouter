"""A Google AI Studio key is a provider the integrations document accepts, not only one the broker knows."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def test_every_wired_provider_is_in_the_catalog_the_document_is_validated_against():
    wired = {p for (p, _backend) in gw._INTEGRATION_WIRING}
    missing = wired - set(gw._PROVIDER_CATALOG)
    assert not missing, f"wired but refused on write: {missing}"


def test_google_carries_its_key_field_and_endpoint():
    g = gw._PROVIDER_CATALOG["google"]
    assert g["secret"] == "api_key" and g["base_url"].startswith("https://generativelanguage.googleapis.com")
    assert "gemini-3.6-flash" in gw._VENDOR_MODELS["google"]
