"""The hosted service as a provider: one key, every model on its list, the endpoint fixed by the
gateway, the key handed over through a connect flow the browser never has to reach directly."""
import asyncio
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402


def test_it_is_wired_wherever_tokenrouter_is():
    tr = {b: v for (p, b), v in A._INTEGRATION_WIRING.items() if p == "tokenrouter"}
    hr = {b: v for (p, b), v in A._INTEGRATION_WIRING.items() if p == "harnessrouter"}
    assert hr == tr and "claude" in hr and "codex" in hr and "dsh" in hr


def test_the_catalog_entry_and_the_fixed_endpoint():
    meta = A._PROVIDER_CATALOG["harnessrouter"]
    assert meta["label"] == "HarnessRouter API" and meta["fields"] == [] and meta["secret"] == "api_key"
    assert meta["base_url"] == A.HR_HOSTED_PROVIDER_BASE and meta["key_hint"].startswith("sk-hr-")
    assert A._provider_base_url("harnessrouter", "") == A.HR_HOSTED_PROVIDER_BASE
    assert A._provider_base_url("harnessrouter", "https://example.com/anything") == A.HR_HOSTED_PROVIDER_BASE
    assert A._provider_base_url("harnessrouter", "https://api.harnessrouter.ai/v1/provider/") == "https://api.harnessrouter.ai/v1/provider"
    assert any(c["id"] == "harnessrouter" for c in A._provider_catalog_public())


def test_the_model_list_is_read_in_both_shapes_and_only_available_ids():
    ours = {"backends": {"codex": {"models": [{"id": "gpt-5.4", "available": True}, {"id": "gpt-6-astra", "available": False}]},
                         "claude": {"models": [{"id": "claude-opus-4.8", "available": True}]}}}
    assert A._hosted_models_parse(ours) == ["claude-opus-4.8", "gpt-5.4"]
    assert A._hosted_models_parse({"data": [{"id": "b"}, {"id": "a"}]}) == ["a", "b"]
    assert A._hosted_models_parse({}) == []


class _R:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.headers = {"content-type": "application/json"}
    def json(self):
        return self._body


def test_the_connect_flow_is_proxied_and_the_secret_stays_here(monkeypatch):
    calls = []
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            calls.append(("POST", url, json)); return _R(200, {"code": "c1", "secret": "s1", "url": "https://app.harnessrouter.ai/get-key?code=c1", "expires_in": 1800})
        async def get(self, url, headers=None):
            calls.append(("GET", url, headers))
            if url.endswith("/v1/connect/c1"):
                return _R(202, {"status": "pending"}) if len([c for c in calls if c[0] == "GET" and "connect" in c[1]]) == 1 else \
                       _R(200, {"status": "ready", "api_key": "sk-hr-" + "a" * 64, "endpoint": "https://api.harnessrouter.ai/v1/provider",
                                "models_url": "https://api.harnessrouter.ai/v1/models", "org": "org1"})
            return _R(200, {"backends": {"codex": {"models": [{"id": "gpt-5.4", "available": True}]}}})
    monkeypatch.setattr(A.httpx, "AsyncClient", _Client)
    async def admin(req): return None
    monkeypatch.setattr(A, "_require_integrations_admin", admin)
    class Req:
        headers = {"host": "console.local"}
    start = asyncio.run(A.admin_connect_start(A.ConnectBody(instance="console.local"), Req()))
    assert start == {"code": "c1", "url": "https://app.harnessrouter.ai/get-key?code=c1", "expires_in": 1800}
    assert "secret" not in start and A._CONNECTS["c1"]["secret"] == "s1"
    pending = asyncio.run(A.admin_connect_poll("c1", Req()))
    assert pending.status_code == 202
    ready = asyncio.run(A.admin_connect_poll("c1", Req()))
    assert ready["status"] == "ready" and ready["api_key"].startswith("sk-hr-") and ready["endpoint"].endswith("/v1/provider")
    assert ready["models"] == ["gpt-5.4"] and A._VENDOR_MODELS["harnessrouter"] == {"gpt-5.4": "gpt-5.4"}
    assert [c for c in calls if c[0] == "GET" and "connect" in c[1]][0][2] == {"X-Connect-Secret": "s1"}
    # The hosted side hands the key over once; this side answers every later poll with the same
    # body (no second hosted read), so a poll that overtook a slow one cannot lose the key.
    n_hosted = len([c for c in calls if c[0] == "GET" and "connect" in c[1]])
    again = asyncio.run(A.admin_connect_poll("c1", Req()))
    assert again == ready and len([c for c in calls if c[0] == "GET" and "connect" in c[1]]) == n_hosted
    # ...until the code's own lifetime is over.
    A._CONNECTS["c1"]["at"] -= A._CONNECT_TTL + 1
    with pytest.raises(A.HTTPException) as ei:
        asyncio.run(A.admin_connect_poll("c1", Req()))
    assert ei.value.status_code == 410 and "c1" not in A._CONNECTS
