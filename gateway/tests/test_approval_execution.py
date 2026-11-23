"""Bound gate over actual SQLite; callbacks are adapters, not live Runtime proof."""
import asyncio
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_sqlite
from tool_approvals import ApprovalError, ApprovalJournal, ApprovalScope
try:
    from approval_execution import BoundApprovalGate, Invocation, canonical_descriptor
except ModuleNotFoundError:
    BoundApprovalGate = Invocation = canonical_descriptor = None

SCOPE = ApprovalScope('org', 'person', 'session', 'response')


@pytest.fixture
def gate(tmp_path):
    assert BoundApprovalGate is not None, 'bound approval gate is not implemented'
    journal = ApprovalJournal(control_sqlite.SqliteContainer(str(tmp_path / 'control.db')), control_sqlite)
    return BoundApprovalGate(journal, b'k' * 32)


def invocation(**changes):
    assert Invocation is not None, 'immutable invocation is not implemented'
    return Invocation(command_id='command-1', tool={'name': 'write', 'origin': 'runtime'},
                      arguments=b'{ "text": "private-parameter-marker", "count": 1 }',
                      checkpoint=b'opaque-native-checkpoint', workspace='workspace-1',
                      runtime={'name': 'adapter', 'version': '1'},
                      policy_digest='a' * 64, capability_digest='b' * 64,
                      credential_versions={'credential-ref': 'c' * 64}, environment_versions={'env-ref': 'd' * 64},
                      **changes)


async def approve(gate, call=None, choice='approve'):
    call = call or invocation()
    record = await gate.capture(SCOPE, call, expires_at=int(time.time()) + 300, preview='Write report')
    request = record['request']
    await gate.journal.decide(SCOPE, call.command_id, {
        'type': 'tool_approval_response', 'approval_id': request['id'], 'command_id': call.command_id,
        'request_hash': request['request_hash'], 'decision': choice}, 'decision-key')
    return request


def test_rfc8785_known_numeric_and_unicode_sorting_vectors():
    assert canonical_descriptor is not None, 'RFC8785 binding is not implemented'
    assert canonical_descriptor({'numbers': [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27]}) == (
        b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}')
    assert canonical_descriptor({'\ue000': 1, '\U0001f600': 2, 'a': 3}) == (
        '{"a":3,"😀":2,"\ue000":1}'.encode())


@pytest.mark.asyncio
async def test_capture_is_atomic_private_and_reopens_with_exact_bytes(gate):
    call = invocation()
    record = await gate.capture(SCOPE, call, expires_at=int(time.time()) + 300, preview='Write report')
    assert record['state'] == 'pending'
    text = json.dumps(record)
    assert 'private-parameter-marker' not in text and 'opaque-native-checkpoint' not in text
    identity, partition = gate.journal._identity(SCOPE, call.command_id)
    raw = await gate.journal.container.read_item(identity, partition_key=partition)
    assert 'private-parameter-marker' not in json.dumps(raw)
    assert '_sealed_invocation' in raw
    fresh_journal = ApprovalJournal(control_sqlite.SqliteContainer(gate.journal.container._path), control_sqlite)
    reopened = BoundApprovalGate(fresh_journal, b'k' * 32)
    saved = await reopened.load(SCOPE, call.command_id)
    assert saved == call
    assert saved.arguments == b'{ "text": "private-parameter-marker", "count": 1 }'


@pytest.mark.asyncio
async def test_capture_does_not_publish_request_when_store_create_fails(gate, monkeypatch):
    async def failed(*args, **kwargs):
        raise OSError('private-store-marker')
    monkeypatch.setattr(gate.journal.container, 'create_item', failed)
    with pytest.raises(OSError):
        await gate.capture(SCOPE, invocation(), expires_at=int(time.time()) + 300, preview='write')
    with pytest.raises(ApprovalError):
        await gate.journal.read(SCOPE, 'command-1')


@pytest.mark.asyncio
async def test_concurrent_resume_dispatches_saved_invocation_once(gate):
    call = invocation()
    request = await approve(gate, call)
    dispatched = []
    async def dispatch(saved):
        dispatched.append(saved)
        await asyncio.sleep(0.01)
        return {'native_receipt': 'ok'}
    results = await asyncio.gather(*(gate.execute(SCOPE, call.command_id, 'continuation-1', call,
                                                  native_allowed=True, dispatch=dispatch) for _ in range(8)))
    assert dispatched == [call]
    assert sum(result == {'native_receipt': 'ok'} for result in results) == 1
    assert (await gate.journal.read(SCOPE, call.command_id))['receipt']['side_effect_state'] == 'completed'
    assert request['request_hash'] == gate.binding(SCOPE, call)


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('arguments', b'{"text":"changed"}'), ('checkpoint', b'different-checkpoint'), ('workspace', 'other'),
    ('runtime', {'name': 'adapter', 'version': '2'}), ('policy_digest', 'e' * 64), ('capability_digest', 'f' * 64),
    ('credential_versions', {'credential-ref': 'e' * 64}), ('environment_versions', {'env-ref': 'e' * 64}),
    ('tool', {'name': 'write', 'origin': 'plugin', 'plugin_name': 'report', 'plugin_version': '2', 'plugin_digest': 'f' * 64}),
])
async def test_any_execution_relevant_change_invalidates_consent_without_dispatch(gate, field, value):
    call = invocation()
    await approve(gate, call)
    async def forbidden(saved):
        pytest.fail('changed invocation dispatched')
    with pytest.raises(ApprovalError, match='hexa_approval_changed'):
        await gate.execute(SCOPE, call.command_id, 'resume', replace(call, **{field: value}), native_allowed=True, dispatch=forbidden)
    assert (await gate.journal.read(SCOPE, call.command_id))['state'] == 'voided'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['denied', 'expired', 'voided', 'native_deny', 'recovered'])
async def test_non_permitted_invocation_never_reaches_adapter(gate, reason):
    call = invocation()
    req = await approve(gate, call, 'deny' if reason == 'denied' else 'approve')
    if reason == 'expired':
        gate.journal.clock = lambda: req['expires_at'] + 1
    elif reason == 'voided':
        await gate.journal.void(SCOPE, call.command_id)
    elif reason == 'recovered':
        await gate.journal.reserve(SCOPE, call.command_id, 'resume', req['request_hash'])
        await gate.journal.recover(SCOPE, call.command_id)
    async def forbidden(saved):
        pytest.fail('unapproved invocation dispatched')
    try:
        result = await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=reason != 'native_deny', dispatch=forbidden)
        assert result is None and reason == 'recovered'
    except ApprovalError:
        assert reason != 'recovered'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['exception', 'cancel'])
async def test_uncertain_dispatch_is_unknown_and_never_repeated(gate, failure):
    call = invocation()
    await approve(gate, call)
    dispatched = []
    async def interrupted(saved):
        dispatched.append(saved)
        if failure == 'cancel':
            raise asyncio.CancelledError()
        raise TimeoutError('private-exception-marker')
    with pytest.raises((TimeoutError, asyncio.CancelledError)):
        await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True, dispatch=interrupted)
    stored = await gate.journal.read(SCOPE, call.command_id)
    assert stored['receipt']['side_effect_state'] == 'unknown'
    assert stored['receipt']['reconciliation_required'] is True
    assert await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True, dispatch=interrupted) is None
    assert len(dispatched) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['ciphertext', 'key', 'request_hash'])
async def test_corrupt_or_wrong_key_checkpoint_fails_closed(gate, change):
    call = invocation()
    await approve(gate, call)
    identity, partition = gate.journal._identity(SCOPE, call.command_id)
    if change == 'key':
        gate = BoundApprovalGate(gate.journal, b'x' * 32)
    else:
        raw = await gate.journal.container.read_item(identity, partition_key=partition)
        if change == 'ciphertext':
            raw['_sealed_invocation'] = 'invalid-private-ciphertext'
        else:
            raw['request']['request_hash'] = 'e' * 64
        await gate.journal.container.replace_item(identity, raw, etag=raw['_etag'])
    async def forbidden(saved):
        pytest.fail('corrupt invocation dispatched')
    with pytest.raises(ApprovalError, match='hexa_approval_unavailable') as caught:
        await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True, dispatch=forbidden)
    assert 'private-' not in str(caught.value)


@pytest.mark.parametrize('arguments', [b'{"a":1,"a":2}', b'{"n":NaN}', b'{"n":Infinity}', b'[]', b'\xff', b'x' * (1024 * 1024 + 1)],
                         ids=['duplicate-key', 'nan', 'infinity', 'array', 'invalid-utf8', 'oversize'])
def test_invalid_argument_bytes_are_rejected(gate, arguments):
    with pytest.raises(ApprovalError, match='hexa_approval_invalid'):
        gate.binding(SCOPE, replace(invocation(), arguments=arguments))


def test_secret_commitments_are_keyed_and_exact_bytes_and_scope_are_bound(gate):
    import hashlib
    call = invocation()
    first = gate.binding(SCOPE, call)
    assert first != BoundApprovalGate(gate.journal, b'x' * 32).binding(SCOPE, call)
    assert first != gate.binding(SCOPE, replace(call, arguments=b'{"text":"private-parameter-marker","count":1}'))
    assert first != gate.binding(replace(SCOPE, principal='other'), call)
    assert first != hashlib.sha256(call.arguments).hexdigest()


def test_configured_gate_requires_existing_secret_key(gate, monkeypatch):
    monkeypatch.delenv('HR_SECRET_KEY', raising=False)
    with pytest.raises(ApprovalError, match='hexa_approval_unavailable'):
        BoundApprovalGate.from_environment(gate.journal)


@pytest.mark.asyncio
async def test_plain_legacy_approval_cannot_gain_bound_execution(gate):
    value = {'id': 'approval_plain', 'type': 'tool_approval_request', 'status': 'completed',
             'command_id': 'command-1', 'request_hash': 'a' * 64, 'canonicalization': 'RFC8785-v1',
             'policy_digest': 'b' * 64, 'capability_digest': 'c' * 64,
             'tool': {'name': 'write', 'origin': 'runtime'}, 'preview': 'write', 'expires_at': int(time.time()) + 300}
    await gate.journal.create(SCOPE, value)
    with pytest.raises(ApprovalError, match='hexa_approval_unavailable'):
        await gate.load(SCOPE, 'command-1')


@pytest.mark.asyncio
async def test_reopened_gate_dispatches_exact_saved_bytes_and_checkpoint(gate):
    call = invocation()
    await approve(gate, call)
    fresh = BoundApprovalGate(ApprovalJournal(control_sqlite.SqliteContainer(gate.journal.container._path), control_sqlite), b'k' * 32)
    async def native(saved):
        assert saved.arguments == call.arguments
        assert saved.checkpoint == call.checkpoint
        return 'native-result'
    assert await fresh.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True, dispatch=native) == 'native-result'


@pytest.mark.asyncio
async def test_failed_start_write_never_dispatches_and_requires_recovery(gate, monkeypatch):
    call = invocation()
    req = await approve(gate, call)
    await gate.journal.reserve(SCOPE, call.command_id, 'resume', req['request_hash'])
    async def unavailable(*args, **kwargs):
        raise OSError('write failed')
    monkeypatch.setattr(gate.journal.container, 'replace_item', unavailable)
    async def forbidden(saved):
        pytest.fail('unpersisted start must never dispatch')
    with pytest.raises(OSError):
        await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True, dispatch=forbidden)


@pytest.mark.asyncio
async def test_concurrent_captures_keep_one_bound_record_and_change_cannot_replace_it(gate):
    call = invocation()
    expiry = int(time.time()) + 300
    records = await asyncio.gather(*(gate.capture(SCOPE, call, expires_at=expiry, preview='write') for _ in range(6)))
    assert all(record == records[0] for record in records)
    with pytest.raises(ApprovalError, match='hexa_approval_conflict'):
        await gate.capture(SCOPE, replace(call, arguments=b'{"other":true}'), expires_at=expiry, preview='write')
    assert await gate.load(SCOPE, call.command_id) == call


@pytest.mark.asyncio
async def test_another_scope_cannot_open_or_swap_sealed_invocation(gate):
    call = invocation()
    first = await approve(gate, call)
    other_scope = replace(SCOPE, principal='another-person')
    await gate.capture(other_scope, call, expires_at=int(time.time()) + 300, preview='write')
    key1, pk1 = gate.journal._identity(SCOPE, call.command_id)
    key2, pk2 = gate.journal._identity(other_scope, call.command_id)
    raw1 = await gate.journal.container.read_item(key1, partition_key=pk1)
    raw2 = await gate.journal.container.read_item(key2, partition_key=pk2)
    raw2['_sealed_invocation'] = raw1['_sealed_invocation']
    await gate.journal.container.replace_item(key2, raw2, etag=raw2['_etag'])
    with pytest.raises(ApprovalError, match='hexa_approval_unavailable'):
        await gate.load(other_scope, call.command_id)
    assert (await gate.journal.read(SCOPE, call.command_id))['request']['request_hash'] == first['request_hash']


@pytest.mark.parametrize('changes', [
    {'checkpoint': b''}, {'checkpoint': b'x' * (1024 * 1024 + 1)}, {'arguments': b'{"n":1e400}'},
    {'arguments': b'{"n":"\\ud800"}'}, {'credential_versions': {'key': 'raw-secret-marker'}},
    {'runtime': {'name': 'adapter', 'version': '1', 'headers': 'raw-secret-marker'}},
], ids=['empty-checkpoint', 'large-checkpoint', 'number-overflow', 'surrogate', 'raw-credential', 'runtime-secret'])
def test_checkpoint_and_execution_configuration_require_valid_bounded_data(gate, changes):
    with pytest.raises(ApprovalError, match='hexa_approval_invalid'):
        gate.binding(SCOPE, replace(invocation(), **changes))


@pytest.mark.asyncio
async def test_mutating_adapter_input_after_capture_cannot_replace_saved_configuration(gate):
    call = invocation()
    await approve(gate, call)
    call.tool['name'] = 'different-tool'
    assert (await gate.load(SCOPE, call.command_id)).tool['name'] == 'write'
    async def forbidden(saved):
        pytest.fail('mutated tool must not dispatch')
    with pytest.raises(ApprovalError, match='hexa_approval_changed'):
        await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True, dispatch=forbidden)
