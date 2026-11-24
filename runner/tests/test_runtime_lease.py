"""Cross-process runtime ownership lease contract."""
import multiprocessing
import pathlib
import sys
import time
import sqlite3

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from runtime_lease import (LeaseConflict, LeaseLost, RuntimeLeaseRegistry,
                           RuntimeLeaseToken)


def test_acquire_is_idempotent_for_same_owner_and_fences_takeover(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / "leases.sqlite3"))
    first = registry.acquire("session/thread", "gateway-a", ttl=10, now=100.0)
    again = registry.acquire("session/thread", "gateway-a", ttl=10, now=101.0)
    assert again == first

    with pytest.raises(LeaseConflict):
        registry.acquire("session/thread", "gateway-b", ttl=10, now=102.0)

    takeover = registry.acquire("session/thread", "gateway-b", ttl=10, now=111.0)
    assert takeover.fence == first.fence + 1
    assert takeover.owner == "gateway-b"

    with pytest.raises(LeaseLost):
        registry.renew(RuntimeLeaseToken("session/thread", "gateway-a", first.fence),
                       ttl=10, now=112.0)
    with pytest.raises(LeaseLost):
        registry.release(RuntimeLeaseToken("session/thread", "gateway-a", first.fence), now=112.0)


def test_renew_release_and_reopen_preserve_fence(tmp_path):
    path = str(tmp_path / "leases.sqlite3")
    registry = RuntimeLeaseRegistry(path)
    lease = registry.acquire("runtime-1", "runner-1", ttl=5, now=10.0)
    renewed = registry.renew(RuntimeLeaseToken("runtime-1", "runner-1", lease.fence),
                             ttl=20, now=11.0)
    assert renewed.expires_at == 31.0
    registry.close()

    reopened = RuntimeLeaseRegistry(path)
    assert reopened.inspect("runtime-1") == renewed
    reopened.release(RuntimeLeaseToken("runtime-1", "runner-1", lease.fence), now=12.0)
    released = reopened.inspect("runtime-1")
    assert released is not None
    assert released.owner is None
    assert released.fence == lease.fence


def test_expired_lease_cannot_be_used_by_old_owner(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / "leases.sqlite3"))
    lease = registry.acquire("runtime-1", "owner-a", ttl=2, now=10.0)
    with pytest.raises(LeaseLost):
        registry.assert_owner(RuntimeLeaseToken("runtime-1", "owner-a", lease.fence), now=12.0)


def _contender(path, owner, start, result):
    registry = RuntimeLeaseRegistry(path)
    try:
        lease = registry.acquire("shared-runtime", owner, ttl=30, now=start)
        result.put((owner, "acquired", lease.fence))
    except LeaseConflict:
        result.put((owner, "conflict", None))


def test_two_processes_have_one_active_owner(tmp_path):
    path = str(tmp_path / "leases.sqlite3")
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Queue()
    processes = [ctx.Process(target=_contender, args=(path, owner, 100.0, result))
                 for owner in ("owner-a", "owner-b")]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(timeout=45)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    rows = [result.get(timeout=2) for _ in processes]
    assert sorted(row[1] for row in rows) == ["acquired", "conflict"]


def test_execution_pin_blocks_takeover_release_and_duplicate_dispatch(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    token = registry.acquire('runtime', 'owner', ttl=10, now=100).token
    assert hasattr(registry, 'begin_execution'), 'durable execution pin is missing'
    registry.begin_execution(token, 'operation', now=101)
    for now in (102, 111):
        with pytest.raises(LeaseConflict):
            registry.acquire('runtime', 'next-owner', ttl=30, now=now)
    with pytest.raises(LeaseConflict):
        registry.acquire('runtime', 'owner', ttl=30, now=102)
    with pytest.raises(LeaseConflict):
        registry.release(token, now=102)
    with pytest.raises(LeaseConflict):
        registry.begin_execution(token, 'another-operation', now=102)
    registry.end_execution(token, 'operation', now=103)
    assert registry.inspect('runtime').execution_id is None
    registry.release(token, now=104)


@pytest.mark.parametrize('outcome', ['unknown', 'late-end'])
def test_uncertain_execution_pin_survives_reopen_and_expiry(tmp_path, outcome):
    path = str(tmp_path / 'leases.db')
    registry = RuntimeLeaseRegistry(path)
    token = registry.acquire('runtime', 'owner', ttl=10, now=100).token
    assert hasattr(registry, 'begin_execution'), 'durable execution pin is missing'
    registry.begin_execution(token, 'operation', now=101)
    if outcome == 'unknown':
        registry.mark_execution_unknown(token, 'operation')
    else:
        with pytest.raises(LeaseLost):
            registry.end_execution(token, 'operation', now=111)
    reopened = RuntimeLeaseRegistry(path)
    state = reopened.inspect('runtime')
    assert state.execution_id == 'operation' and state.execution_state == 'unknown'
    with pytest.raises(LeaseConflict):
        reopened.acquire('runtime', 'next', ttl=10, now=200)
    with pytest.raises(LeaseLost):
        reopened.end_execution(token, 'operation', now=105)


def _leave_active_pin(path):
    registry = RuntimeLeaseRegistry(path)
    token = registry.acquire('runtime', 'process-owner', ttl=10, now=100).token
    registry.begin_execution(token, 'process-operation', now=101)


def test_process_exit_never_frees_active_execution(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    assert hasattr(registry, 'begin_execution'), 'durable execution pin is missing'
    ctx = multiprocessing.get_context('spawn')
    process = ctx.Process(target=_leave_active_pin, args=(registry.path,))
    process.start()
    try:
        process.join(timeout=45)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert registry.inspect('runtime').execution_id == 'process-operation'
    with pytest.raises(LeaseConflict):
        registry.acquire('runtime', 'next', ttl=10, now=200)


@pytest.mark.parametrize('field,value', [('ttl', float('nan')), ('ttl', float('inf')),
                                         ('now', float('nan')), ('now', float('inf'))])
def test_nonfinite_times_are_rejected_without_writing(tmp_path, field, value):
    from runtime_lease import LeaseError
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    times = {'ttl': 10, 'now': 100}
    times[field] = value
    with pytest.raises(LeaseError):
        registry.acquire('runtime', 'owner', **times)
    assert registry.inspect('runtime') is None


def test_existing_database_upgrades_without_losing_fence(tmp_path):
    path = str(tmp_path / 'legacy.db')
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE runtime_leases (runtime_id TEXT PRIMARY KEY, owner TEXT, '
                     'fence INTEGER NOT NULL, heartbeat_at REAL, expires_at REAL)')
        conn.execute('INSERT INTO runtime_leases VALUES (?, ?, ?, ?, ?)',
                     ('runtime', 'owner', 7, 100, 110))
    registry = RuntimeLeaseRegistry(path)
    state = registry.inspect('runtime')
    assert state.fence == 7 and state.owner == 'owner'
    assert hasattr(state, 'execution_id'), 'execution pin migration is missing'
    assert state.execution_id is None
