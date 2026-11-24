"""Trusted Runner ownership coordinator, without granting approval coverage."""
import asyncio
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
try:
    from runtime_ownership import RuntimeOwnership, OwnershipError
except ModuleNotFoundError:
    RuntimeOwnership = OwnershipError = None


def coordinator(call, **kwargs):
    assert RuntimeOwnership is not None, 'Gateway Runtime ownership client missing'
    return RuntimeOwnership(call, **kwargs)


def runner_transport(changes=None, fail=None):
    calls = []

    async def call(path, sid, method='POST', body=None):
        calls.append((path, sid, body.copy()))
        if path.endswith('/' + str(fail)):
            raise RuntimeError('private transport diagnostic')
        result = {'runtime_id': body['runtime_id'], 'owner': body['owner'], 'fence': 7,
                  'heartbeat_at': time.time(), 'expires_at': time.time() + 30,
                  'execution_id': None, 'execution_state': None}
        if path.endswith('/release'):
            result.update(owner=None, heartbeat_at=None, expires_at=None)
        if changes and path.endswith('/acquire'):
            result.update(changes)
        return result
    return call, calls


@pytest.mark.asyncio
async def test_scoped_operation_uses_runner_lease_and_releases_same_fence():
    transport, calls = runner_transport()
    owner = coordinator(transport)

    async def operation(token):
        assert token['runtime_id'] == 'runtime' and token['fence'] == 7
        assert token['owner']
        return 'result'

    assert await owner.run('session', 'runtime', operation) == 'result'
    assert [c[0] for c in calls] == ['/internal/runtime-leases/acquire',
                                    '/internal/runtime-leases/renew', '/internal/runtime-leases/release']
    assert all(c[1] == 'session' for c in calls)
    assert len({c[2]['owner'] for c in calls}) == 1
    assert calls[-1][2]['fence'] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [{'runtime_id': 'other'}, {'owner': 'other'}, {'fence': True},
    {'fence': 0}, {'expires_at': float('nan')}, {'expires_at': 0},
    {'execution_id': 'still-running'}, {'execution_state': 'unknown'}])
async def test_invalid_or_pinned_acquire_never_dispatches(change):
    transport, calls = runner_transport(change)
    owner = coordinator(transport)
    async def forbidden(token):
        pytest.fail('invalid lease dispatched operation')
    with pytest.raises(OwnershipError, match='runtime_lease_unavailable'):
        await owner.run('session', 'runtime', forbidden)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_acquire_failure_does_not_run_or_expose_transport_diagnostic():
    transport, calls = runner_transport(fail='acquire')
    owner = coordinator(transport)
    async def forbidden(token):
        pytest.fail('failed acquire dispatched operation')
    with pytest.raises(OwnershipError, match='^runtime_lease_unavailable$'):
        await owner.run('session', 'runtime', forbidden)


@pytest.mark.asyncio
async def test_heartbeat_failure_cancels_operation_and_propagates_unknown_boundary():
    entered, canceled = asyncio.Event(), asyncio.Event()
    transport, calls = runner_transport(fail='renew')
    owner = coordinator(transport, ttl=0.06)
    async def operation(token):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()
    with pytest.raises(OwnershipError, match='^runtime_lease_lost$'):
        await asyncio.wait_for(owner.run('session', 'runtime', operation), timeout=5)
    assert entered.is_set() and canceled.is_set()
    assert not any(path.endswith('/release') for path, _, _ in calls)


@pytest.mark.asyncio
async def test_cancellation_stops_heartbeat_without_releasing_uncertain_native_owner():
    entered, canceled = asyncio.Event(), asyncio.Event()
    transport, calls = runner_transport()
    owner = coordinator(transport)
    async def operation(token):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()
    task = asyncio.create_task(owner.run('session', 'runtime', operation))
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert canceled.is_set()
    assert not any(path.endswith('/release') for path, _, _ in calls)


@pytest.mark.asyncio
async def test_gateway_native_continuation_uses_configured_authenticated_runner(monkeypatch):
    import httpx
    import app as gateway
    assert hasattr(gateway, '_run_owned_native_continuation'), 'Gateway Runner transport missing'
    calls = []

    def response(request):
        import json
        body = json.loads(request.content)
        calls.append(request)
        assert request.url.host == 'runner' and request.url.params['identifier'] == 'session'
        assert request.headers['x-harness-internal'] == 'controlled-internal-key'
        value = {**body, 'fence': 3, 'heartbeat_at': time.time(), 'expires_at': time.time() + 30,
                 'execution_id': None, 'execution_state': None}
        if request.url.path.endswith('/release'):
            value.update(owner=None, heartbeat_at=None, expires_at=None)
        return httpx.Response(200, json=value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        monkeypatch.setattr(gateway, 'POOL_ENDPOINT', 'http://runner')
        monkeypatch.setattr(gateway, 'INTERNAL_KEY', 'controlled-internal-key')
        monkeypatch.setattr(gateway, '_client', lambda: client)
        async def operation(token):
            assert token['fence'] == 3
            return 'done'
        assert await gateway._run_owned_native_continuation('session', 'runtime', operation) == 'done'
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['renew-fence', 'renew-timeout', 'release-failure', 'operation-error'])
async def test_lost_fence_timeout_and_failures_never_report_success(failure):
    transport, calls = runner_transport(fail='release' if failure == 'release-failure' else None)
    canceled = asyncio.Event()
    async def call(path, sid, method='POST', body=None):
        if path.endswith('/renew') and failure == 'renew-timeout':
            await asyncio.Event().wait()
        value = await transport(path, sid, method, body)
        if path.endswith('/renew') and failure == 'renew-fence':
            value['fence'] += 1
        return value
    owner = coordinator(call, ttl=0.3)
    async def operation(token):
        if failure == 'operation-error':
            raise ValueError('controlled operation failure')
        if failure == 'release-failure':
            return 'finished'
        try:
            await asyncio.Event().wait()
        finally:
            canceled.set()
    with pytest.raises(ValueError if failure == 'operation-error' else OwnershipError):
        await asyncio.wait_for(owner.run('session', 'runtime', operation), timeout=5)
    if failure.startswith('renew-'):
        assert canceled.is_set()
    if failure != 'release-failure':
        assert not any(path.endswith('/release') for path, _, _ in calls)
