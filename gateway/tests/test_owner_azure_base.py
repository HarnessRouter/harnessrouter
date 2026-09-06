"""In owner trust the sandbox gets the provider base the broker would forward to: a bare Azure endpoint gains /openai/v1."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def test_a_bare_azure_endpoint_gains_its_path_in_owner_trust(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    out = gw._auth_from_conn({"provider": "azure-foundry", "api_key": "k", "base_url": "https://res.openai.azure.com/"}, "sid1")
    assert out["base_url"] == "https://res.openai.azure.com/openai/v1" and out["api_key"] == "k"


def test_a_full_azure_base_and_other_providers_are_left_alone(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    az = gw._auth_from_conn({"provider": "azure-foundry", "api_key": "k", "base_url": "https://res.cognitiveservices.azure.com/openai/v1"}, "sid1")
    assert az["base_url"] == "https://res.cognitiveservices.azure.com/openai/v1"
    tr = gw._auth_from_conn({"provider": "tokenrouter", "api_key": "k", "base_url": "https://api.tokenrouter.com/v1"}, "sid1")
    assert tr["base_url"] == "https://api.tokenrouter.com/v1"
