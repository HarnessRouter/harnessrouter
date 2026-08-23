"""Vision for hermes is a capability resolved across the instance's integrations, independent of
the writing model, so a supported model is supported whatever it is, with whatever keys exist."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app  # noqa: E402


def _with(monkeypatch, integrations):
    async def _doc():
        return integrations
    monkeypatch.setattr(app, "_integrations_doc", _doc)
    monkeypatch.setattr(app, "SANDBOX_TRUST", "owner")


def test_only_anthropic_key_audits_with_claude(monkeypatch):
    _with(monkeypatch, [{"name": "ant", "provider": "anthropic", "config": {"api_key": "ka"}}])
    v = asyncio.run(app._vision_auth("sess1", "hermes"))
    assert v and v["model"].startswith("claude-haiku") and v["api_key"] == "ka"


def test_only_openai_key_audits_with_gpt(monkeypatch):
    _with(monkeypatch, [{"name": "oai", "provider": "openai", "config": {"api_key": "ko"}}])
    v = asyncio.run(app._vision_auth("sess1", "hermes"))
    assert v and v["model"] == "gpt-5.4-mini" and v["api_key"] == "ko"


def test_resolution_is_deterministic_by_name_not_insertion_order(monkeypatch):
    integs = [{"name": "zeta", "provider": "openai", "config": {"api_key": "ko"}},
              {"name": "alpha", "provider": "anthropic", "config": {"api_key": "ka"}}]
    _with(monkeypatch, integs)
    a = asyncio.run(app._vision_auth("s", "hermes"))
    _with(monkeypatch, list(reversed(integs)))
    b = asyncio.run(app._vision_auth("s", "hermes"))
    assert a == b and a["api_key"] == "ka"


def test_no_vision_capable_integration_means_none(monkeypatch):
    # A vendor whose catalogue has no vision-capable model: nothing to route to, so hermes keeps
    # its default rather than being pointed at a model the endpoint cannot serve.
    monkeypatch.setattr(app, "_integration_models", lambda integ: {"llama-3": "llama-3"})
    _with(monkeypatch, [{"name": "local", "provider": "openai-api",
                         "config": {"api_key": "k", "base_url": "http://llm.local/v1"}}])
    assert asyncio.run(app._vision_auth("s", "hermes")) is None


def test_custom_endpoint_with_a_known_catalogue_is_routed(monkeypatch):
    # An OpenAI-compatible endpoint inherits the gpt catalogue, so it can answer image questions
    # with gpt-5.4-mini, through its own base_url.
    _with(monkeypatch, [{"name": "local", "provider": "openai-api",
                         "config": {"api_key": "k", "base_url": "http://llm.local/v1"}}])
    v = asyncio.run(app._vision_auth("s", "hermes"))
    assert v == {"provider": "openai-api", "model": "gpt-5.4-mini",
                 "base_url": "http://llm.local/v1", "api_key": "k"}


def test_no_session_means_none(monkeypatch):
    _with(monkeypatch, [{"name": "ant", "provider": "anthropic", "config": {"api_key": "ka"}}])
    assert asyncio.run(app._vision_auth("", "hermes")) is None
