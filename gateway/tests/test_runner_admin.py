import asyncio
import pathlib
import sys

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gateway


def test_runner_management_requires_internal_operator_key(monkeypatch):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(gateway.app), base_url="http://gateway") as client:
            assert (await client.get("/internal/runners")).status_code == 401
            assert (await client.get("/internal/runners", headers={"x-harness-internal": gateway.INTERNAL_KEY,
                                                                       "authorization": "Bearer wrong"})).status_code == 401
    asyncio.run(go())


def test_runner_management_forwards_only_supported_actions(monkeypatch):
    calls = []

    class Client:
        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return httpx.Response(200, json={"runners": []} if method == "GET" else {"ok": True})

    monkeypatch.setattr(gateway, "POOL_ENDPOINT", "http://router:8090")
    monkeypatch.setattr(gateway, "_client", lambda: Client())

    async def go():
        headers = {"x-harness-internal": gateway.INTERNAL_KEY}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(gateway.app), base_url="http://gateway", headers=headers) as client:
            assert (await client.get("/internal/runners")).json() == {"runners": []}
            for action in ("register", "drain", "deregister"):
                assert (await client.post(f"/internal/runners/{action}", json={"name": "test"})).status_code == 200
            assert (await client.post("/internal/runners/heartbeat", json={})).status_code == 404
    asyncio.run(go())
    assert len(calls) == 4
    assert calls[1][1] == "http://router:8090/register"
    assert calls[0][2]["headers"] == {"X-Harness-Internal": gateway.INTERNAL_KEY}
