"""Real Runner HTTP read/acquire boundary; registration writes are adapter-only."""
import os
from pathlib import Path
import sys
import time

import pytest
from fastapi.testclient import TestClient

if os.name != 'posix':
    pytest.skip('Runner HTTP requires the Unix delivery image', allow_module_level=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from test_runtime_registration import descriptor


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setenv('HR_RUNTIME_LEASE_DB', str(tmp_path / 'leases.db'))
    monkeypatch.setattr(server, '_INTERNAL_KEY', 'runner-key')
    monkeypatch.setattr(server, '_SESSION_UIDS', False)
    monkeypatch.setattr(server, '_RUNTIME_INSTANCE_ID', 'controlled-instance', raising=False)
    reg = server._runtime_leases().register('runtime', descriptor(instance_id=server._RUNTIME_INSTANCE_ID),
                                           ttl=300, now=time.time())
    return TestClient(server.app), reg


def test_registration_read_is_authenticated_scoped_and_has_no_write_endpoint(runtime):
    client, reg = runtime
    path = '/internal/runtime-registrations/runtime'
    assert client.get(path, params={'identifier': 'session'}).status_code == 401
    headers = {'x-harness-internal': 'runner-key'}
    assert client.get(path, headers=headers, params={'identifier': 'other'}).status_code == 404
    result = client.get(path, headers=headers, params={'identifier': 'session'})
    assert result.status_code == 200 and result.json() == reg
    assert result.headers['cache-control'] == 'no-store'
    assert client.post(path, headers=headers, json=reg).status_code == 405
    assert client.get('/internal/runtime-registrations/missing', headers=headers,
                      params={'identifier': 'session'}).status_code == 404


def test_registration_id_bound_to_lease_and_restart_cannot_use_old_instance(runtime, monkeypatch):
    client, reg = runtime
    headers = {'x-harness-internal': 'runner-key'}
    body = {'runtime_id': 'runtime', 'owner': 'owner', 'registration_id': reg['registration_id'],
            'ttl_seconds': 30}
    path = '/internal/runtime-leases/'
    assert client.post(path + 'acquire', headers=headers, params={'identifier': 'other'}, json=body).status_code == 409
    result = client.post(path + 'acquire', headers=headers, params={'identifier': 'session'}, json=body)
    assert result.status_code == 200 and result.json()['registration_id'] == reg['registration_id']
    token = {**body, 'fence': result.json()['fence']}
    assert client.post(path + 'renew', headers=headers, params={'identifier': 'session'}, json=token).status_code == 200
    monkeypatch.setattr(server, '_RUNTIME_INSTANCE_ID', 'restarted-instance')
    assert client.get('/internal/runtime-registrations/runtime', headers=headers,
                      params={'identifier': 'session'}).status_code == 409
    for action in ('renew', 'release', 'acquire'):
        failed = client.post(path + action, headers=headers, params={'identifier': 'session'}, json=token)
        assert failed.status_code == 409
        assert failed.json()['detail']['code'] == 'runtime_lease_lost'


def test_unregistered_acquire_cannot_bypass_existing_registration(runtime):
    client, reg = runtime
    result = client.post('/internal/runtime-leases/acquire', headers={'x-harness-internal': 'runner-key'},
                         params={'identifier': 'session'}, json={'runtime_id': 'runtime', 'owner': 'owner'})
    assert result.status_code == 409 and result.json()['detail']['code'] == 'runtime_lease_lost'


@pytest.mark.parametrize('outcome', ['complete', 'registration-lost'])
def test_gateway_registered_ownership_with_real_runner_http(runtime, outcome):
    import asyncio
    import sqlite3
    import httpx
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'gateway'))
    from runtime_ownership import RuntimeOwnership, OwnershipError
    from runtime_lease import RuntimeLeaseToken
    client, reg = runtime
    store = server._runtime_leases()
    expected = {k: reg[k] for k in ('runtime_name', 'runtime_version', 'thread_id', 'checkpoint_ns',
                                   'checkpoint_backend', 'capabilities')}
    async def journey():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://runner',
                                     headers={'x-harness-internal': 'runner-key'}) as http:
            async def transport(path, sid, method='POST', body=None):
                response = await http.request(method, path, params={'identifier': sid}, json=body)
                response.raise_for_status()
                return response.json()
            async def operation(token):
                native_token = RuntimeLeaseToken(**token)
                store.begin_execution(native_token, 'operation', now=time.time())
                try:
                    if outcome == 'registration-lost':
                        with sqlite3.connect(store.path) as conn:
                            conn.execute('DELETE FROM runtime_registrations WHERE runtime_id=?', ('runtime',))
                        await asyncio.Event().wait()
                    store.end_execution(native_token, 'operation', now=time.time())
                    return 'completed'
                except BaseException:
                    store.mark_execution_unknown(native_token, 'operation')
                    raise
            owned = RuntimeOwnership(transport, ttl=0.3)
            if outcome == 'complete':
                assert await owned.run_registered('session', 'runtime', expected, operation) == 'completed'
                assert store.inspect('runtime').owner is None
            else:
                with pytest.raises(OwnershipError, match='runtime_lease_lost'):
                    await asyncio.wait_for(owned.run_registered('session', 'runtime', expected, operation), timeout=5)
                assert store.inspect('runtime').execution_state == 'unknown'
                assert store.inspect('runtime').owner is not None
    asyncio.run(journey())
