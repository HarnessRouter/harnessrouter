import asyncio
import json

import httpx
import pytest

from test_uhp_connections import gateway, runtime


def test_external_detail_matches_directory_and_scope(runtime, monkeypatch):
    async def empty(*args):
        return []

    async def grants(*args):
        return {}

    async def identity(request):
        return runtime[1]

    monkeypatch.setattr(gateway, "_vg_list_by_org", empty)
    monkeypatch.setattr(gateway.memory_plane, "grant_counts", grants)
    monkeypatch.setattr(gateway, "_pub_principal", identity)

    async def go():
        setup, principal, _, _, _ = runtime
        client, saved = await setup()
        async with client:
            harness_id = saved["harnesses"][0]["id"]
            detail = await client.get("/v1/harnesses/" + harness_id)
            assert detail.status_code == 200, detail.text
            listing = await client.get("/v1/harnesses")
            assert detail.json() == listing.json()["harnesses"][0]
            assert detail.json()["available"] is True
            assert "test-runtime-secret" not in detail.text
            principal["workspace"] = "another-workspace"
            assert (await client.get("/v1/harnesses/" + harness_id)).status_code == 404
            principal["workspace"] = ""
            principal["calibration"] = {"inner": "another-agent"}
            assert (await client.get("/v1/harnesses/" + harness_id)).status_code == 404
            principal["calibration"] = {"inner": harness_id}
            assert (await client.get("/v1/harnesses/" + harness_id)).status_code == 200
            principal.pop("calibration")
            principal["org"] = "another-org"
            assert (await client.get("/v1/harnesses/" + harness_id)).status_code == 404
    asyncio.run(go())


def test_saved_health_and_probe_does_not_mutate(runtime):
    async def go():
        setup, _, _, vault, _ = runtime
        client, row = await setup()
        async with client:
            assert row["health"]["status"] == "healthy"
            assert row["health"]["fresh_until"] - row["health"]["last_checked_at"] == 90
            assert row["health"]["last_success_at"] > 0
            before = dict(vault)
            probe = await client.post("/v1/admin/uhp-connections/probe", json={
                "name": "browser", "base_url": row["base_url"], "api_key": gateway._SECRET_SENTINEL})
            assert probe.status_code == 200
            assert vault == before
    asyncio.run(go())


@pytest.mark.parametrize("failure,status", [
    ("offline", "unreachable"), ("timeout", "unreachable"), ("auth", "unauthorized"),
    ("json", "invalid"), ("protocol", "invalid"), ("list", "invalid"), ("missing", "harness_missing"),
])
def test_dispatch_blocks_bad_runtime_and_recovers(runtime, monkeypatch, failure, status):
    async def go():
        setup, _, _, _, client_type = runtime
        client, row = await setup()
        mode = failure
        posts = []

        def remote(request):
            if request.method == "POST":
                posts.append(request)
                return httpx.Response(200, json={"id": "remote-ok", "status": "completed"})
            if mode == "offline":
                raise httpx.ConnectError("test-runtime-secret", request=request)
            if mode == "timeout":
                raise httpx.ReadTimeout("test-runtime-secret", request=request)
            if request.url.path == "/v1/uhp":
                if mode == "json":
                    return httpx.Response(200, text="test-runtime-secret")
                return httpx.Response(200, json={} if mode == "protocol" else {"version": "test"})
            if mode == "auth":
                return httpx.Response(401, text="test-runtime-secret")
            return httpx.Response(200, json={"data": {} if mode == "list" else
                ([] if mode == "missing" else [{"id": "browser/page-1", "name": "Browser"}])})

        monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda **kwargs: client_type(
            transport=httpx.MockTransport(remote), **kwargs))
        async with client:
            body = {"input": "hello", "metadata": {"harness_id": row["harnesses"][0]["id"]}}
            blocked = await client.post("/v1/responses", json=body)
            assert blocked.status_code == 503, blocked.text
            assert not posts
            assert status in blocked.text
            assert "test-runtime-secret" not in blocked.text
            listing = await client.get("/v1/admin/uhp-connections")
            saved = listing.json()["connections"][0]
            assert saved["health"]["status"] == status
            assert saved["harnesses"][0]["id"] == row["harnesses"][0]["id"]
            assert "test-runtime-secret" not in listing.text
            mode = "healthy"
            recovered = await client.post("/v1/responses", json=body)
            assert recovered.status_code == 200, recovered.text
            assert len(posts) == 1
            assert (await client.get("/v1/admin/uhp-connections")).json()["connections"][0]["health"]["status"] == "healthy"
    asyncio.run(go())


def test_manual_check_scope_and_health_time(runtime):
    async def go():
        setup, principal, _, _, _ = runtime
        client, row = await setup()
        async with client:
            checked = await client.post("/v1/admin/uhp-connections/browser/check")
            assert checked.status_code == 200, checked.text
            assert checked.json()["connection"]["health"]["latency_ms"] >= 0
            principal["org"] = "other"
            assert (await client.post("/v1/admin/uhp-connections/browser/check")).status_code == 404
    asyncio.run(go())


def test_failed_save_persists_connection_for_repair(runtime, monkeypatch):
    async def go():
        setup, _, _, _, _ = runtime
        client, row = await setup()

        async def fail_probe(*args, **kwargs):
            raise gateway._UhpProbeError("unauthorized", "UHP 密钥无效或权限不足。")

        monkeypatch.setattr(gateway, "_uhp_probe", fail_probe)
        async with client:
            saved = await client.put("/v1/admin/uhp-connections/browser", json={
                "name": "browser", "base_url": "http://runtime-new:8421", "api_key": "new-secret"})
            assert saved.status_code == 200, saved.text
            assert saved.json()["ok"] is False
            assert saved.json()["connection"]["health"]["status"] == "unauthorized"
            assert saved.json()["connection"]["config"]["api_key"] == gateway._SECRET_SENTINEL
            listed = await client.get("/v1/admin/uhp-connections")
            assert listed.json()["connections"][0]["health"]["status"] == "unauthorized"
            assert "new-secret" not in listed.text
            assert listed.json()["connections"][0]["id"] == row["id"]
    asyncio.run(go())


def test_concurrent_checks_share_probe_and_expired_health_is_not_available(runtime, monkeypatch):
    async def go():
        setup, principal, calls, _, client_type = runtime
        client, _ = await setup()
        await client.aclose()
        row = (await gateway._uhp_connections_doc())[0]
        count = 0

        async def remote(request):
            nonlocal count
            count += 1
            await asyncio.sleep(0.02)
            return httpx.Response(200, json={"version": "test"} if request.url.path == "/v1/uhp" else
                                  {"data": [{"id": "browser/page-1", "name": "Browser"}]})

        monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda **kwargs: client_type(
            transport=httpx.MockTransport(remote), **kwargs))
        await asyncio.gather(*(gateway._uhp_check(row) for _ in range(5)))
        assert count == 2
        observed = (await gateway._uhp_connections_doc())[0]
        now = observed["health"]["fresh_until"] + 1
        monkeypatch.setattr(gateway.time, "time", lambda: now)
        assert (await gateway._uhp_connections_doc())[0]["health"]["stale"]
        assert not (await gateway._uhp_harnesses(principal))[0]["available"]
    asyncio.run(go())


def test_control_store_failure_preserves_observation_and_blocks_dispatch(runtime, monkeypatch):
    async def go():
        setup, _, calls, vault, _ = runtime
        client, row = await setup()
        before = dict(vault)
        async def unavailable(*args, **kwargs):
            return {"fence": 0, "rejected": False}
        monkeypatch.setattr(gateway.control_store, "enabled", lambda: True)
        monkeypatch.setattr(gateway.control_store, "lease_admit", unavailable)
        async with client:
            result = await client.post("/v1/responses", json={"input": "hi", "metadata": {
                "harness_id": row["harnesses"][0]["id"]}})
            assert result.status_code == 503
            assert vault == before
            assert len(calls) == 2
    asyncio.run(go())


def test_configuration_change_invalidates_old_observation(runtime):
    async def go():
        setup, _, _, vault, _ = runtime
        client, _ = await setup()
        await client.aclose()
        rows = json.loads(vault[gateway.GLOBAL_TENANT, gateway._UHP_CONNECTIONS_KEY])
        rows[0]["base_url"] = "http://other-runtime:8421"
        vault[gateway.GLOBAL_TENANT, gateway._UHP_CONNECTIONS_KEY] = json.dumps(rows)
        assert (await gateway._uhp_connections_doc())[0]["health"]["status"] == "unknown"
    asyncio.run(go())


def test_healthy_other_harness_remains_usable_and_business_failure_does_not_poison(runtime, monkeypatch):
    async def go():
        setup, _, _, _, client_type = runtime
        client, _ = await setup()
        def remote(request):
            if request.url.path == "/v1/uhp":
                return httpx.Response(200, json={"version": "test"})
            if request.url.path == "/v1/harnesses":
                return httpx.Response(200, json={"data": [{"id": "other", "name": "Other"}]})
            return httpx.Response(409, json={"error": {"code": "session_busy", "message": "busy"}})
        monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda **kwargs: client_type(
            transport=httpx.MockTransport(remote), **kwargs))
        async with client:
            checked = await client.post("/v1/admin/uhp-connections/browser/check")
            row = checked.json()["connection"]
            assert row["health"]["status"] == "harness_missing"
            target = next(item for item in row["harnesses"] if item["remote_id"] == "other")
            result = await client.post("/v1/responses", json={"input": "hi", "metadata": {"harness_id": target["id"]}})
            assert result.status_code == 409
            assert (await gateway._uhp_connections_doc())[0]["health"]["status"] == "harness_missing"
    asyncio.run(go())


def test_workflow_retries_health_failure_without_posting_to_runtime(runtime, monkeypatch):
    async def go():
        setup, _, calls, _, client_type = runtime
        client, row = await setup()
        check_calls = []
        def remote(request):
            check_calls.append(request.method)
            raise httpx.ConnectError("offline", request=request)
        monkeypatch.setattr(gateway.httpx, "AsyncClient", lambda **kwargs: client_type(
            transport=httpx.MockTransport(remote), **kwargs))
        async with client:
            created = await client.post("/v1/workflow-tasks", json={"title": "health", "input": "hi",
                "snapshot": {"title": "health", "nodes": [{"id": "one", "name": "one",
                    "agent_id": row["harnesses"][0]["id"], "retry_limit": 2, "deps": []}]}})
            assert created.status_code == 200, created.text
            task_id = created.json()["id"]
            await gateway._workflow_execute(task_id, {})
            result = (await client.get("/v1/workflow-tasks/" + task_id)).json()
            node = result["snapshot"]["nodes"][0]
            assert result["status"] == "failed"
            assert node["attempts"] == 3
            assert "unreachable" in node["output"]
            assert check_calls == ["GET", "GET", "GET"]
    asyncio.run(go())
