import asyncio
import json
import pathlib
import sys

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gateway


@pytest.fixture
def runtime(monkeypatch):
    vault, calls = {}, []
    principal = {"org": "uhp-owner", "workspace": "", "member": "operator"}
    client_type = httpx.AsyncClient

    async def read(tenant, key):
        return vault.get((tenant, key))

    async def write(tenant, key, value, param=None):
        vault[tenant, key] = value

    async def identity(request):
        return principal

    async def allowed(url):
        return None

    def handler(request):
        calls.append(request)
        if request.url.path == "/v1/uhp":
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"version": "test"})
        assert request.headers["authorization"] == "Bearer test-runtime-secret"
        if request.url.path == "/v1/harnesses":
            return httpx.Response(200, json={"data": [{"id": "browser/page-1", "name": "Browser"}]})
        if request.url.path.endswith("/cancel"):
            assert request.method == "POST"
            return httpx.Response(200, json={"id": "remote-response", "status": "cancelled"})
        if request.method == "GET":
            return httpx.Response(200, json={"id": "remote-response", "status": "completed"})
        return httpx.Response(200, json={"id": "remote-response", "status": "completed"})

    monkeypatch.setattr(gateway, "_vault_get", read)
    monkeypatch.setattr(gateway, "_vault_put_credential", write)
    monkeypatch.setattr(gateway, "_principal", identity)
    monkeypatch.setattr(gateway, "_require_integrations_admin", identity)
    monkeypatch.setattr(gateway, "_ssrf_check", allowed)
    monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))

    async def setup():
        client = client_type(transport=httpx.ASGITransport(gateway.app), base_url="http://gateway")
        response = await client.put("/v1/admin/uhp-connections/browser", json={
            "name": "browser", "base_url": "http://runtime:8421/v1/uhp", "api_key": "test-runtime-secret"})
        assert response.status_code == 200, response.text
        row = response.json()["connection"]
        assert row["config"]["api_key"] == gateway._SECRET_SENTINEL
        await client.aclose()
        return client_type(transport=httpx.ASGITransport(gateway.app), base_url="http://gateway"), row

    return setup, principal, calls, vault, client_type


def test_save_update_and_delete_preserves_alias_and_redacts_secret(runtime):
    async def go():
        setup, _, calls, _, _ = runtime
        client, row = await setup()
        async with client:
            updated = await client.put("/v1/admin/uhp-connections/browser", json={
                "name": "browser", "base_url": "http://runtime:8421", "api_key": gateway._SECRET_SENTINEL})
            assert updated.status_code == 200, updated.text
            assert updated.json()["connection"]["harnesses"] == row["harnesses"]
            listed = await client.get("/v1/admin/uhp-connections")
            assert "test-runtime-secret" not in listed.text
            assert len(listed.json()["connections"]) == 1
            assert (await client.delete("/v1/admin/uhp-connections/browser")).status_code == 200
            assert (await client.get("/v1/admin/uhp-connections")).json()["connections"] == []
    asyncio.run(go())


def test_sync_background_get_cancel_and_continuation(runtime):
    async def go():
        setup, _, calls, _, _ = runtime
        client, row = await setup()
        async with client:
            hid = row["harnesses"][0]["id"]
            response = await client.post("/v1/responses", json={"input": "hello", "background": True,
                                                               "metadata": {"harness_id": hid}})
            assert response.status_code == 200, response.text
            rid = response.json()["id"]
            assert rid.startswith("resp_uhp_")
            payload = json.loads(calls[-1].content)
            assert payload["metadata"]["harness_id"] == "browser/page-1"
            assert payload["background"] is True
            assert (await client.get(f"/v1/responses/{rid}")).json()["id"] == rid
            cancelled = await client.post(f"/v1/responses/{rid}/cancel")
            assert cancelled.json() == {"id": rid, "status": "cancelled"}
            continued = await client.post("/v1/responses", json={"input": "again", "previous_response_id": rid})
            assert continued.status_code == 200, continued.text
            assert json.loads(calls[-1].content)["previous_response_id"] == "remote-response"
    asyncio.run(go())


def test_connection_and_responses_are_org_scoped(runtime):
    async def go():
        setup, principal, calls, _, _ = runtime
        client, row = await setup()
        async with client:
            hid = row["harnesses"][0]["id"]
            response = await client.post("/v1/responses", json={"input": "hello", "metadata": {"harness_id": hid}})
            rid = response.json()["id"]
            principal["org"] = "other-org"
            before = len(calls)
            assert (await client.get("/v1/admin/uhp-connections")).json()["connections"] == []
            assert await gateway._uhp_target(hid, principal) is None
            assert (await client.get(f"/v1/responses/{rid}")).status_code == 404
            assert (await client.post(f"/v1/responses/{rid}/cancel")).status_code == 404
            assert (await client.post("/v1/responses", json={"input": "again", "previous_response_id": rid,
                "metadata": {"harness_id": hid}})).status_code == 404
            assert (await client.delete("/v1/admin/uhp-connections/browser")).status_code == 404
            assert len(calls) == before
    asyncio.run(go())


def test_harness_discovery_exposes_gateway_alias(runtime, monkeypatch):
    async def empty(*args):
        return []
    async def grants(*args):
        return {}
    monkeypatch.setattr(gateway, "_vg_list_by_org", empty)
    monkeypatch.setattr(gateway.memory_plane, "grant_counts", grants)

    async def go():
        setup, principal, _, _, _ = runtime
        client, row = await setup()
        async with client:
            response = await client.get("/v1/harnesses")
            assert response.status_code == 200, response.text
            assert response.json()["harnesses"][0]["id"] == row["harnesses"][0]["id"]
            principal["workspace"] = "other-workspace"
            assert (await client.get("/v1/harnesses")).json()["harnesses"] == []
    asyncio.run(go())


def test_sse_first_event_arrives_before_terminal_and_closes(runtime, monkeypatch):
    async def go():
        setup, principal, _, _, client_type = runtime
        client, row = await setup()
        await client.aclose()
        release = asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                first = ('data: {"type":"response.created","response":{"id":"remote-stream","text":"中文"}}\r\n\r\n').encode()
                split = first.index("中".encode()) + 1
                yield first[:split]
                yield first[split:]
                await release.wait()
                yield b'data: {"type":"response.completed","response":{"id":"remote-stream"}}\n\n'

            async def aclose(self):
                self.closed = True

        stream = Stream()
        monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda **kw: client_type(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)), **kw))
        conn = (await gateway._uhp_connections_doc())[0]
        response = await gateway._uhp_request_response(gateway.CreateResponseBody(input="hi", stream=True),
            Request({"type": "http", "headers": []}), conn, row["harnesses"][0], principal)
        iterator = response.body_iterator
        first = await asyncio.wait_for(anext(iterator), 1)
        event = json.loads(first.decode()[6:])
        rid = event["response"]["id"]
        assert event["response"]["text"] == "中文"
        assert rid.startswith("resp_uhp_")
        assert (await gateway._uhp_response_get(rid))["remote_id"] == "remote-stream"
        assert not release.is_set()  # first event did not wait for the upstream terminal
        release.set()
        rest = b"".join([chunk async for chunk in iterator])
        assert rid.encode() in rest
        assert b"remote-stream" not in rest
        assert stream.closed
    asyncio.run(go())


def test_unavailable_runtime_returns_503(runtime, monkeypatch):
    async def go():
        setup, principal, _, _, client_type = runtime
        client, row = await setup()
        await client.aclose()
        conn = (await gateway._uhp_connections_doc())[0]

        def fail(request):
            raise httpx.ConnectError("offline", request=request)

        monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(fail), **kw))
        for stream in (False, True):
            with pytest.raises(HTTPException) as error:
                await gateway._uhp_request_response(gateway.CreateResponseBody(input="hi", stream=stream),
                    Request({"type": "http", "headers": []}), conn, row["harnesses"][0], principal)
            assert error.value.status_code == 503
    asyncio.run(go())
