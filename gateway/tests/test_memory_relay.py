"""A memory vendor's server on the model relay: it calls /v1/llm with a memory service credential, not a provider key,
and each call goes through this instance's own key for the model, named as that key names it (memory_relay)."""
from __future__ import annotations

import json
import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_relay  # noqa: E402

INTERNAL = {"x-harness-internal": "k-test"}
OPENAI = {"name": "OpenAI", "provider": "openai", "config": {"api_key": "sk-openai-SENTINEL"}}
VERCEL = {"name": "Vercel AI Gateway", "provider": "vercel", "config": {"api_key": "vck-SENTINEL", "base_url": "https://ai-gateway.vercel.sh/v1"}}
AZURE = {"name": "Azure OpenAI E2", "provider": "azure-foundry", "config": {"api_key": "az-SENTINEL", "base_url": "https://e2.openai.azure.com"}}
LISTED = {"OpenAI": {"gpt-5.4-mini": "gpt-5.4-mini-2026"}, "Azure OpenAI E2": {"gpt-4o-mini": "gpt-4o-mini-e2"}}


@pytest.fixture
def relay(monkeypatch):
    vault: dict = {}
    sent: list[httpx.Request] = []
    keys = {"list": [VERCEL, OPENAI]}

    async def vget(tenant, name):
        return vault.get((tenant, name))

    async def vput(tenant, name, value):
        vault[(tenant, name)] = value

    async def integrations():
        return keys["list"]

    async def catalog():
        return {"gpt-5.4-mini": "OpenAI"}

    def upstream(req: httpx.Request) -> httpx.Response:
        sent.append(req)
        # a stream, as a provider's answer is: the relay passes it through as it comes
        data = json.dumps({"ok": True, "model": json.loads(req.content)["model"]}).encode()
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(data))
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test")
    monkeypatch.setattr(gw, "_vault_get", vget)
    monkeypatch.setattr(gw, "_vault_put", vput)
    monkeypatch.setattr(gw, "_integrations_doc", integrations)
    monkeypatch.setattr(gw, "_effective_model_map", catalog)
    monkeypatch.setattr(gw, "_integration_models", lambda i: LISTED.get(i["name"], {}))
    monkeypatch.setattr(gw, "HR_MEMORY_RELAY_KEYS", [])
    monkeypatch.setattr(gw, "_relay_http", httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    c = TestClient(gw.app)

    def service(**kw):
        body = {"vendor": "hindsight", "llm_model": "gpt-4o-mini", "embedding_model": "text-embedding-3-small", **kw}
        r = c.post("/v1/memory-services", headers=INTERNAL, json=body)
        assert r.status_code == 200, r.text
        return r.json()
    return c, service, sent, keys


def test_a_service_is_set_up_by_the_operator_only_and_its_credential_is_said_once(relay):
    c, service, _sent, _keys = relay
    s = service()
    assert s["credential"].startswith("hrm_" + s["id"] + ".") and s["vendor"] == "hindsight" and s["revoked"] is False
    listed = c.get("/v1/memory-services", headers=INTERNAL).json()["data"]
    assert [x["id"] for x in listed] == [s["id"]] and "credential" not in listed[0]
    assert c.post("/v1/memory-services", headers={**INTERNAL, "authorization": "Bearer junk"}, json={}).status_code == 401
    assert c.post("/v1/memory-services", json={"vendor": "mem0", "llm_model": "gpt-4o-mini", "embedding_model": "text-embedding-3-small"}).status_code == 401


@pytest.mark.parametrize("body,why", [
    ({"vendor": "nope", "llm_model": "gpt-4o-mini", "embedding_model": "text-embedding-3-small"}, "vendor"),
    ({"vendor": "mem0", "llm_model": "text-embedding-3-small", "embedding_model": "text-embedding-3-small"}, "llm_model"),
    ({"vendor": "mem0", "llm_model": "gpt-4o-mini", "embedding_model": "gpt-4o-mini"}, "embedding_model"),
    ({"vendor": "mem0", "llm_model": "some-model-nobody-serves", "embedding_model": "text-embedding-3-small"}, "llm_model"),
])
def test_a_service_names_models_this_instance_can_serve_of_the_right_kind(relay, body, why):
    c, *_ = relay
    r = c.post("/v1/memory-services", headers=INTERNAL, json=body)
    assert r.status_code == 400 and why in r.text


def test_an_embedding_goes_through_the_makers_own_key_named_as_it_names_it(relay):
    c, service, sent, _keys = relay
    tok = service()["credential"]
    r = c.post("/v1/llm/v1/embeddings", headers={"authorization": f"Bearer {tok}"}, json={"model": "text-embedding-3-small", "input": ["hi"]})
    assert r.status_code == 200 and r.json()["model"] == "text-embedding-3-small"
    up = sent[-1]
    assert str(up.url) == "https://api.openai.com/v1/embeddings", "OpenAI's own key before a gateway that also lists it"
    assert up.headers["authorization"] == "Bearer sk-openai-SENTINEL"
    assert tok not in str(up.headers) and tok not in up.content.decode(), "the service's credential never leaves"


def test_a_model_only_a_gateway_serves_is_named_as_the_gateway_names_it(relay):
    c, service, sent, keys = relay
    tok = service()["credential"]
    keys["list"] = [VERCEL]
    r = c.post("/v1/llm/v1/chat/completions", headers={"authorization": f"Bearer {tok}"}, json={"model": "gpt-4o-mini", "messages": []})
    assert r.status_code == 200
    assert str(sent[-1].url) == "https://ai-gateway.vercel.sh/v1/chat/completions" and json.loads(sent[-1].content)["model"] == "openai/gpt-4o-mini"


def test_a_model_from_the_agents_catalog_goes_where_the_catalog_sends_it(relay):
    c, service, sent, _keys = relay
    tok = service(llm_model="gpt-5.4-mini")["credential"]
    r = c.post("/v1/llm/v1/responses", headers={"authorization": f"Bearer {tok}"}, json={"model": "gpt-5.4-mini", "input": "x"})
    assert r.status_code == 200 and json.loads(sent[-1].content)["model"] == "gpt-5.4-mini-2026"
    assert str(sent[-1].url) == "https://api.openai.com/v1/responses"


@pytest.mark.parametrize("method,path,model", [
    ("POST", "embeddings", "text-embedding-3-large"),     # not this service's
    ("POST", "embeddings", "gpt-4o-mini"),                # its model, on the wrong path
    ("POST", "chat/completions", "text-embedding-3-small"),
    ("POST", "messages/batches", "gpt-4o-mini"),          # not an inference path it has
    ("GET", "models", ""),
])
def test_a_service_uses_its_own_models_on_the_inference_paths_and_nothing_else(relay, method, path, model):
    c, service, sent, _keys = relay
    tok = service()["credential"]
    r = c.request(method, f"/v1/llm/v1/{path}", headers={"authorization": f"Bearer {tok}"}, json={"model": model} if method == "POST" else None)
    assert r.status_code == 403 and not sent


def test_a_withdrawn_or_forged_credential_is_refused(relay):
    c, service, sent, _keys = relay
    s = service()
    forged = s["credential"][:-4] + "0000"
    assert c.post("/v1/llm/v1/embeddings", headers={"authorization": f"Bearer {forged}"}, json={"model": "text-embedding-3-small"}).status_code == 401
    assert c.post(f"/v1/memory-services/{s['id']}/revoke", headers=INTERNAL).json()["revoked"] is True
    assert c.post("/v1/llm/v1/embeddings", headers={"authorization": f"Bearer {s['credential']}"}, json={"model": "text-embedding-3-small"}).status_code == 401
    assert not sent


def test_a_credential_is_bound_to_this_gateways_key():
    tok = memory_relay.mint(b"one-key", "msvc_0123456789abcdef")
    assert memory_relay.verify(b"one-key", tok) == "msvc_0123456789abcdef"
    assert memory_relay.verify(b"another-key", tok) is None
    assert memory_relay.verify(b"one-key", "hrm_msvc_nothex.deadbeef") is None


def test_an_instance_can_keep_memory_services_on_its_gateway_keys(relay, monkeypatch):
    """The test instance spends gateway credit, never a provider's own key: Vercel first, then Azure."""
    c, service, sent, keys = relay
    monkeypatch.setattr(gw, "HR_MEMORY_RELAY_KEYS", ["vercel", "azure-foundry"])
    keys["list"] = [OPENAI, AZURE, VERCEL]
    tok = service()["credential"]
    c.post("/v1/llm/v1/embeddings", headers={"authorization": f"Bearer {tok}"}, json={"model": "text-embedding-3-small", "input": ["hi"]})
    assert str(sent[-1].url) == "https://ai-gateway.vercel.sh/v1/embeddings" and json.loads(sent[-1].content)["model"] == "openai/text-embedding-3-small"
    # a model only a provider's own key lists isn't served here at all
    r = c.post("/v1/memory-services", headers=INTERNAL, json={"vendor": "mem0", "llm_model": "gpt-5.4-mini", "embedding_model": "text-embedding-3-small"})
    assert r.status_code == 400 and "no key here serves gpt-5.4-mini" in r.text


def test_an_azure_key_serves_what_it_has_deployed_named_as_deployed(relay, monkeypatch):
    c, service, sent, keys = relay
    monkeypatch.setattr(gw, "HR_MEMORY_RELAY_KEYS", ["azure-foundry", "vercel"])
    keys["list"] = [VERCEL, AZURE]
    tok = service()["credential"]
    c.post("/v1/llm/v1/chat/completions", headers={"authorization": f"Bearer {tok}"}, json={"model": "gpt-4o-mini", "messages": []})
    assert str(sent[-1].url).startswith("https://e2.openai.azure.com/openai/v1/chat/completions") and json.loads(sent[-1].content)["model"] == "gpt-4o-mini-e2"
    assert sent[-1].headers["api-key"] == "az-SENTINEL" and "authorization" not in sent[-1].headers
    # not deployed there: the next key on the list
    c.post("/v1/llm/v1/embeddings", headers={"authorization": f"Bearer {tok}"}, json={"model": "text-embedding-3-small", "input": ["x"]})
    assert str(sent[-1].url) == "https://ai-gateway.vercel.sh/v1/embeddings"


def test_the_operators_own_tools_take_a_credential_on_the_same_terms(relay):
    c, service, sent, _keys = relay
    tok = service(vendor="operator", embedding_model="text-embedding-3-small")["credential"]
    assert c.post("/v1/llm/v1/chat/completions", headers={"authorization": f"Bearer {tok}"}, json={"model": "gpt-4o-mini", "messages": []}).status_code == 200
    assert c.post("/v1/llm/v1/chat/completions", headers={"authorization": f"Bearer {tok}"}, json={"model": "gpt-4.1-mini", "messages": []}).status_code == 403
