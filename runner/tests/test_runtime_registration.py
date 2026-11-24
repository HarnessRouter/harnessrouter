"""Trusted native registration is distinct from ownership and tool permission."""
import pathlib
import multiprocessing
import sqlite3
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from runtime_lease import LeaseError, LeaseLost, LeaseConflict, RuntimeLeaseRegistry


def descriptor(**changes):
    return {'session_id': 'session', 'instance_id': 'runner-instance',
            'runtime_name': 'langgraph', 'runtime_version': '1.1.8', 'thread_id': 'thread',
            'checkpoint_ns': '', 'checkpoint_backend': 'sqlite',
            'capabilities': ['checkpoint_before_tool', 'durable_checkpoint', 'exact_resume',
                             'deny_continuation'], **changes}


def register(registry, **kwargs):
    assert hasattr(registry, 'register'), 'trusted Runtime registration is missing'
    return registry.register('runtime', kwargs.pop('descriptor', descriptor()),
                             ttl=kwargs.pop('ttl', 30), now=kwargs.pop('now', 100), **kwargs)


def test_registration_is_durable_idempotent_and_lease_is_bound(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    first = register(store)
    again = register(store, now=101)
    assert first['registration_id'] == again['registration_id']
    assert again['expires_at'] == 131
    reopened = RuntimeLeaseRegistry(store.path)
    assert reopened.inspect_registration('runtime') == again
    lease = reopened.acquire('runtime', 'owner', registration_id=first['registration_id'], ttl=10, now=102)
    assert lease.registration_id == first['registration_id']
    assert lease.token.registration_id == first['registration_id']
    assert reopened.renew(lease.token, ttl=10, now=103).registration_id == first['registration_id']
    assert reopened.release(lease.token, now=104).registration_id == first['registration_id']


@pytest.mark.parametrize('changes', [
    {'capabilities': []}, {'capabilities': ['exact_resume']},
    {'capabilities': descriptor()['capabilities'] + ['untrusted']},
    {'capabilities': descriptor()['capabilities'] + ['exact_resume']},
    {'checkpoint_backend': 'memory'}, {'session_id': ''}, {'instance_id': ''},
    {'runtime_version': ''}, {'thread_id': ''}, {'checkpoint_ns': 'subgraph'},
    {'headers': {'Authorization': 'private-marker'}},
])
def test_invalid_descriptor_never_creates_registration(tmp_path, changes):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    with pytest.raises(LeaseError):
        register(store, descriptor=descriptor(**changes))
    assert store.inspect_registration('runtime') is None


def test_registered_runtime_cannot_downgrade_to_unregistered_lease(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    register(store)
    with pytest.raises(LeaseLost):
        store.acquire('runtime', 'owner', ttl=10, now=101)
    assert store.inspect('runtime') is None


@pytest.mark.parametrize('failure', ['expired', 'lost', 'replaced'])
def test_registration_loss_blocks_every_native_boundary(tmp_path, failure):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    reg = register(store, ttl=5)
    token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=30, now=101).token
    store.begin_execution(token, 'operation', now=102)
    now = 106 if failure == 'expired' else 103
    if failure != 'expired':
        with sqlite3.connect(store.path) as conn:
            if failure == 'lost':
                conn.execute('DELETE FROM runtime_registrations WHERE runtime_id=?', ('runtime',))
            else:
                conn.execute('UPDATE runtime_registrations SET registration_id=? WHERE runtime_id=?',
                             ('different-registration', 'runtime'))
    for action in [lambda: store.assert_owner(token, now=now),
                   lambda: store.renew(token, ttl=30, now=now),
                   lambda: store.assert_execution(token, 'operation', now=now),
                   lambda: store.end_execution(token, 'operation', now=now)]:
        with pytest.raises(LeaseLost):
            action()
    state = store.inspect('runtime')
    assert state.execution_state == 'unknown'
    with pytest.raises(LeaseConflict):
        register(store, descriptor=descriptor(instance_id='new-runner'), now=200)


def test_replacement_requires_idle_owner_and_new_id_fences_old_token(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    reg = register(store)
    token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=5, now=101).token
    with pytest.raises(LeaseConflict):
        register(store, descriptor=descriptor(instance_id='new-runner'), now=102)
    replaced = register(store, descriptor=descriptor(instance_id='new-runner'), now=107)
    assert replaced['registration_id'] != reg['registration_id']
    with pytest.raises(LeaseLost):
        store.acquire('runtime', 'old', registration_id=reg['registration_id'], ttl=10, now=108)
    new = store.acquire('runtime', 'new', registration_id=replaced['registration_id'], ttl=10, now=108)
    assert new.fence == token.fence + 1


def test_live_lease_cannot_outlive_expired_registration_by_reregistering(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    reg = register(store, ttl=5)
    store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=30, now=101)
    with pytest.raises(LeaseConflict):
        register(store, now=106)


def test_register_does_not_retroactively_attach_an_unregistered_live_lease(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    store.acquire('runtime', 'owner', ttl=10, now=100)
    with pytest.raises(LeaseConflict):
        register(store, now=101)


def test_registration_scope_is_validated_in_same_transaction_as_ownership(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    reg = register(store)
    with pytest.raises(LeaseLost):
        store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=10, now=101,
                      registration_scope={'session_id': 'other', 'instance_id': 'runner-instance'})
    assert store.inspect('runtime') is None
    token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=10, now=101,
                          registration_scope={'session_id': 'session', 'instance_id': 'runner-instance'}).token
    for action in (store.renew, store.release):
        with pytest.raises(LeaseLost):
            action(token, now=102, registration_scope={'session_id': 'session', 'instance_id': 'restarted'},
                   **({'ttl': 10} if action == store.renew else {}))


def test_lost_registration_cannot_downgrade_previously_registered_runtime(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    reg = register(store)
    token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=5, now=101).token
    with sqlite3.connect(store.path) as conn:
        conn.execute('DELETE FROM runtime_registrations WHERE runtime_id=?', ('runtime',))
    with pytest.raises(LeaseLost):
        store.acquire('runtime', 'new-owner', ttl=10, now=110)
    assert store.inspect('runtime').fence == token.fence


def _registered_contender(path, owner, result):
    store = RuntimeLeaseRegistry(path)
    registration = register(store)
    try:
        lease = store.acquire('runtime', owner, registration_id=registration['registration_id'], ttl=30, now=101)
        result.put(('acquired', registration['registration_id'], lease.fence))
    except LeaseConflict:
        result.put(('conflict', registration['registration_id'], None))


def test_independent_processes_share_registration_but_only_one_owner(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    ctx = multiprocessing.get_context('spawn')
    result = ctx.Queue()
    processes = [ctx.Process(target=_registered_contender, args=(store.path, owner, result))
                 for owner in ('replica-a', 'replica-b')]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(timeout=45)
            assert process.exitcode == 0
        rows = [result.get(timeout=2) for _ in processes]
        assert sorted(row[0] for row in rows) == ['acquired', 'conflict']
        assert len({row[1] for row in rows}) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result.close()


def test_registration_lifecycle_cas_renew_close_and_stale_close(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    first = register(store)
    assert hasattr(store, 'renew_registration'), 'registration lifecycle renewal missing'
    renewed = store.renew_registration('runtime', first['registration_id'], descriptor(), ttl=30, now=101)
    assert renewed['registration_id'] == first['registration_id'] and renewed['expires_at'] == 131
    store.revoke_registration('runtime', first['registration_id'], now=102)
    with pytest.raises(LeaseLost):
        store.renew_registration('runtime', first['registration_id'], descriptor(), ttl=30, now=103)
    second = register(store, now=104)
    assert second['registration_id'] != first['registration_id']
    store.revoke_registration('runtime', first['registration_id'], now=105)
    assert store.inspect_registration('runtime') == second


def test_registration_expired_or_changed_never_renews(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    first = register(store, ttl=5)
    assert hasattr(store, 'renew_registration'), 'registration lifecycle renewal missing'
    for value, now in [(descriptor(instance_id='other'), 101), (descriptor(), 106)]:
        with pytest.raises(LeaseLost):
            store.renew_registration('runtime', first['registration_id'], value, ttl=30, now=now)
    assert store.inspect_registration('runtime') == first


def test_registration_revocation_keeps_execution_unknown_and_forbids_reopen(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    reg = register(store)
    token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=30, now=101).token
    store.begin_execution(token, 'operation', now=102)
    assert hasattr(store, 'revoke_registration'), 'registration lifecycle revocation missing'
    store.revoke_registration('runtime', reg['registration_id'], now=103)
    state = store.inspect('runtime')
    assert state.execution_id == 'operation' and state.execution_state == 'unknown' and state.owner == 'owner'
    with pytest.raises(LeaseConflict):
        register(store, now=200)


def test_exclusive_session_registration_does_not_share_same_descriptor(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    first = register(store)
    with pytest.raises(LeaseConflict):
        register(store, exclusive=True, now=101)
    assert store.inspect_registration('runtime') == first
