"""A direct provider's key needs no endpoint from the user: the broker knows the provider's own."""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def _doc(monkeypatch, integrations):
    async def doc(*_a, **_k):
        return integrations
    monkeypatch.setattr(gw, "_integrations_doc", doc)


def test_an_openai_key_resolves_to_openais_endpoint(monkeypatch):
    _doc(monkeypatch, [{"name": "default", "provider": "OpenAI", "config": {"api_key": "sk-proj-x"}}])
    conn = asyncio.run(gw._broker_resolve("integration:default", "org.a"))
    assert conn["base_url"] == "https://api.openai.com/v1" and conn["api_key"] == "sk-proj-x"


def test_an_anthropic_key_resolves_to_anthropics_endpoint(monkeypatch):
    _doc(monkeypatch, [{"name": "k", "provider": "anthropic", "config": {"api_key": "sk-ant-x"}}])
    conn = asyncio.run(gw._broker_resolve("integration:k", "org.a"))
    assert conn["base_url"] == "https://api.anthropic.com/v1"


def test_a_connection_with_its_own_endpoint_keeps_it(monkeypatch):
    _doc(monkeypatch, [{"name": "v", "provider": "vercel", "config": {"api_key": "vck_x", "base_url": "https://ai-gateway.vercel.sh/v1"}}])
    conn = asyncio.run(gw._broker_resolve("integration:v", "org.a"))
    assert conn["base_url"] == "https://ai-gateway.vercel.sh/v1"


def test_a_gateway_without_an_endpoint_stays_without_one(monkeypatch):
    _doc(monkeypatch, [{"name": "o", "provider": "openrouter", "config": {"api_key": "sk-or-x"}}])
    conn = asyncio.run(gw._broker_resolve("integration:o", "org.a"))
    assert not conn.get("base_url"), "only direct providers get a default endpoint"


def test_a_vault_connection_gets_the_default_too(monkeypatch):
    async def get(_org, _name):
        return {"provider": "openai", "api_key": "sk-x"}, "org.a"
    _doc(monkeypatch, [])
    monkeypatch.setattr(gw, "_get_connection", get)
    conn = asyncio.run(gw._broker_resolve("openai", "org.a"))
    assert conn["base_url"] == "https://api.openai.com/v1"
