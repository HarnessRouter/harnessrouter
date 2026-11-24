"""Runner internal Runtime lease HTTP contract (Unix Runner image)."""
import os
import asyncio
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

if os.name != "posix":
    pytest.skip("Runner HTTP tests require the Unix Runner image", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def test_runtime_lease_http_preserves_fence_and_rejects_stale_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("HR_RUNTIME_LEASE_DB", str(tmp_path / "runtime-leases.sqlite3"))
    monkeypatch.setattr(server, "_INTERNAL_KEY", "runner-key")
    monkeypatch.setattr(server, "_runtime_lease_registry", None)
    monkeypatch.setattr(server, "_runtime_lease_registry_path", None)
    monkeypatch.setattr(server, "_SESSION_UIDS", False)
    client = TestClient(server.app)

    acquired = client.post("/internal/runtime-leases/acquire", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-a", "ttl_seconds": 30,
    })
    assert acquired.status_code == 200
    lease = acquired.json()
    assert lease["owner"] == "runner-a"
    assert lease["fence"] == 1

    conflict = client.post("/internal/runtime-leases/acquire", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-b", "ttl_seconds": 30,
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "runtime_lease_conflict"

    renewed = client.post("/internal/runtime-leases/renew", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-a", "fence": lease["fence"],
        "ttl_seconds": 30,
    })
    assert renewed.status_code == 200
    assert renewed.json()["fence"] == lease["fence"]

    stale = client.post("/internal/runtime-leases/release", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-b", "fence": lease["fence"],
    })
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "runtime_lease_lost"

    released = client.post("/internal/runtime-leases/release", headers={"x-harness-internal": "runner-key"}, json={
        "runtime_id": "session/thread", "owner": "runner-a", "fence": lease["fence"],
    })
    assert released.status_code == 200
    assert released.json()["owner"] is None


def test_runtime_lease_http_never_uses_unkeyed_internal_surface(monkeypatch, tmp_path):
    monkeypatch.setenv("HR_RUNTIME_LEASE_DB", str(tmp_path / "runtime-leases.sqlite3"))
    monkeypatch.setattr(server, "_INTERNAL_KEY", "runner-key")
    monkeypatch.setattr(server, "_runtime_lease_registry", None)
    monkeypatch.setattr(server, "_runtime_lease_registry_path", None)
    client = TestClient(server.app)
    response = client.post("/internal/runtime-leases/acquire", json={
        "runtime_id": "runtime", "owner": "owner", "ttl_seconds": 30,
    })
    assert response.status_code == 401


@pytest.mark.parametrize('changes', [{'fence': True}, {'ttl_seconds': True}, {'ttl_seconds': '30'},
                                    {'unknown': 'private-marker'}, {'fence': 1.5}, {'owner': ''}])
def test_runtime_lease_http_rejects_coercion_and_extra_fields(monkeypatch, tmp_path, changes):
    monkeypatch.setenv('HR_RUNTIME_LEASE_DB', str(tmp_path / 'leases.db'))
    monkeypatch.setattr(server, '_INTERNAL_KEY', 'runner-key')
    monkeypatch.setattr(server, '_SESSION_UIDS', False)
    body = {'runtime_id': 'runtime', 'owner': 'owner', 'ttl_seconds': 30, **changes}
    response = TestClient(server.app).post('/internal/runtime-leases/acquire',
        headers={'x-harness-internal': 'runner-key'}, json=body)
    assert response.status_code == 422
    assert 'private-marker' not in response.text


def test_runtime_lease_http_requires_configured_key_even_when_header_matches_empty(monkeypatch):
    monkeypatch.setattr(server, '_INTERNAL_KEY', '')
    monkeypatch.setattr(server, '_SESSION_UIDS', False)
    assert TestClient(server.app).post('/internal/runtime-leases/acquire', json={
        'runtime_id': 'runtime', 'owner': 'owner'}).status_code == 401


def test_runtime_lease_http_inspection_exposes_pin_state_without_payload(monkeypatch, tmp_path):
    monkeypatch.setenv('HR_RUNTIME_LEASE_DB', str(tmp_path / 'leases.db'))
    monkeypatch.setattr(server, '_INTERNAL_KEY', 'runner-key')
    monkeypatch.setattr(server, '_SESSION_UIDS', False)
    registry = server._runtime_leases()
    token = registry.acquire('runtime', 'owner', ttl=10, now=100).token
    registry.begin_execution(token, 'operation', now=101)
    registry.mark_execution_unknown(token, 'operation')
    response = TestClient(server.app).get('/internal/runtime-leases/runtime',
        headers={'x-harness-internal': 'runner-key'})
    assert response.status_code == 200
    assert response.json()['execution_state'] == 'unknown'
    assert response.json()['execution_id'] == 'operation'


@pytest.mark.parametrize('outcome', ['completed', 'canceled'])
def test_gateway_ownership_client_with_real_runner_http_store(monkeypatch, tmp_path, outcome):
    import httpx
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'gateway'))
    from runtime_ownership import RuntimeOwnership
    from runtime_lease import RuntimeLeaseToken

    monkeypatch.setenv('HR_RUNTIME_LEASE_DB', str(tmp_path / 'leases.db'))
    monkeypatch.setattr(server, '_INTERNAL_KEY', 'runner-key')
    monkeypatch.setattr(server, '_SESSION_UIDS', False)
    registry = server._runtime_leases()

    async def journey():
        renewed, entered = asyncio.Event(), asyncio.Event()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                base_url='http://runner', headers={'x-harness-internal': 'runner-key'}) as client:
            async def transport(path, sid, method='POST', body=None):
                response = await client.request(method, path, params={'identifier': sid}, json=body)
                response.raise_for_status()
                if path.endswith('/renew'):
                    renewed.set()
                return response.json()

            async def operation(token):
                native_token = RuntimeLeaseToken(**token)
                registry.begin_execution(native_token, 'controlled-operation', now=server.time.time())
                entered.set()
                try:
                    await asyncio.wait_for(renewed.wait(), timeout=5)
                    if outcome == 'canceled':
                        await asyncio.Event().wait()
                    registry.end_execution(native_token, 'controlled-operation', now=server.time.time())
                    return 'completed'
                except BaseException:
                    registry.mark_execution_unknown(native_token, 'controlled-operation')
                    raise

            coordinator = RuntimeOwnership(transport, ttl=3)
            task = asyncio.create_task(coordinator.run('session', 'runtime', operation))
            await asyncio.wait_for(entered.wait(), timeout=5)
            if outcome == 'canceled':
                await asyncio.wait_for(renewed.wait(), timeout=5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                state = registry.inspect('runtime')
                assert state.execution_state == 'unknown' and state.owner
                refused = await client.post('/internal/runtime-leases/acquire', json={
                    'runtime_id': 'runtime', 'owner': 'next', 'ttl_seconds': 30})
                assert refused.status_code == 409
            else:
                assert await task == 'completed'
                assert registry.inspect('runtime').owner is None
    asyncio.run(journey())
