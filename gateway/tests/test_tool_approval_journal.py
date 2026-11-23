"""Internal journal guarantees, using the real local control-store boundary.

These tests do not claim native interception or shipped UHP approval support.
"""
import asyncio
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_sqlite
from tool_approvals import ApprovalError, ApprovalJournal, ApprovalScope


SCOPE = ApprovalScope('org', 'person', 'session', 'response')


def request(**changes):
    return {'id': 'approval_test', 'type': 'tool_approval_request', 'status': 'completed',
            'command_id': 'command-1', 'request_hash': 'a' * 64, 'canonicalization': 'RFC8785-v1',
            'policy_digest': 'b' * 64, 'capability_digest': 'c' * 64,
            'tool': {'name': 'write', 'origin': 'direct'}, 'preview': 'Write report',
            'expires_at': int(time.time()) + 300, **changes}


def decision(value=None, choice='approve'):
    value = value or request()
    return {'type': 'tool_approval_response', 'approval_id': value['id'],
            'command_id': value['command_id'], 'request_hash': value['request_hash'], 'decision': choice}


@pytest.fixture
def journal(tmp_path):
    return ApprovalJournal(control_sqlite.SqliteContainer(str(tmp_path / 'control.db')), control_sqlite)


async def approved(journal, choice='approve'):
    value = request()
    await journal.create(SCOPE, value)
    receipt = await journal.decide(SCOPE, value['command_id'], decision(value, choice), 'decision-key')
    return value, receipt


def failure(code, status=409):
    return pytest.raises(ApprovalError, match=code, check=lambda exc: exc.status_code == status)


@pytest.mark.asyncio
async def test_request_reopens_in_separate_process_without_losing_identity(journal):
    value = request()
    first = await journal.create(SCOPE, value)
    path = journal.container._path
    script = '''import asyncio,json,sys
from control_sqlite import SqliteContainer
import control_sqlite
from tool_approvals import ApprovalJournal,ApprovalScope
async def main():
    j=ApprovalJournal(SqliteContainer(sys.argv[1]),control_sqlite)
    print(json.dumps(await j.read(ApprovalScope('org','person','session','response'),'command-1')))
asyncio.run(main())
'''
    process = subprocess.run([sys.executable, '-c', script, path], cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(process.stdout) == first == {'request': value, 'state': 'pending'}
    assert await journal.create(SCOPE, {**value, 'id': 'approval_competitor'}) == first
    with failure('hexa_approval_conflict'):
        await journal.create(SCOPE, {**value, 'request_hash': 'd' * 64})


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['org', 'principal', 'session', 'response'])
async def test_scope_isolation_for_read_decide_and_start(journal, field):
    value, _ = await approved(journal)
    scope = ApprovalScope(**{**SCOPE.__dict__, field: 'stranger'})
    for operation in (lambda: journal.read(scope, value['command_id']),
                      lambda: journal.decide(scope, value['command_id'], decision(value), 'decision-key'),
                      lambda: journal.start(scope, value['command_id'], 'continuation', value['request_hash'], native_allowed=True)):
        with failure('hexa_approval_not_found', 404):
            await operation()


@pytest.mark.asyncio
async def test_decision_is_idempotent_but_cannot_be_replaced(journal):
    value, receipt = await approved(journal)
    assert receipt['side_effect_state'] == 'not_started'
    assert receipt['reconciliation_required'] is False
    assert await journal.decide(SCOPE, value['command_id'], decision(value), 'decision-key') == receipt
    for payload, key in ((decision(value, 'deny'), 'decision-key'), (decision(value), 'another-key'),
                         (decision({**value, 'request_hash': 'd' * 64}), 'decision-key')):
        with failure('hexa_approval_conflict'):
            await journal.decide(SCOPE, value['command_id'], payload, key)
    assert (await journal.read(SCOPE, value['command_id']))['state'] == 'approved'


@pytest.mark.asyncio
async def test_exact_continuation_and_single_start_with_monotonic_receipts(journal):
    value, receipt = await approved(journal)
    command, binding = value['command_id'], value['request_hash']
    with failure('hexa_approval_not_pending'):
        await journal.start(SCOPE, command, 'resume-1', binding, native_allowed=True)
    await journal.reserve(SCOPE, command, 'resume-1', binding)
    await journal.reserve(SCOPE, command, 'resume-1', binding)
    with failure('hexa_approval_conflict'):
        await journal.reserve(SCOPE, command, 'resume-2', binding)
    assert await journal.start(SCOPE, command, 'resume-1', binding, native_allowed=True) is True
    assert await journal.start(SCOPE, command, 'resume-1', binding, native_allowed=True) is False
    assert await journal.decide(SCOPE, command, decision(value), 'decision-key') == receipt
    await journal.finish(SCOPE, command, 'resume-1', 'completed')
    assert (await journal.read(SCOPE, command))['receipt']['side_effect_state'] == 'completed'
    assert await journal.start(SCOPE, command, 'resume-1', binding, native_allowed=True) is False
    with failure('hexa_approval_conflict'):
        await journal.finish(SCOPE, command, 'resume-1', 'failed')


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['deny', 'expire', 'void', 'changed', 'native_deny'])
async def test_unsafe_or_unapproved_calls_never_receive_start_permit(journal, reason):
    value, _ = await approved(journal, 'deny' if reason == 'deny' else 'approve')
    command, binding = value['command_id'], value['request_hash']
    await journal.reserve(SCOPE, command, 'resume', binding)
    if reason == 'expire':
        journal.clock = lambda: value['expires_at'] + 1
    if reason == 'void':
        await journal.void(SCOPE, command)
    with pytest.raises(ApprovalError):
        await journal.start(SCOPE, command, 'resume', 'd' * 64 if reason == 'changed' else binding,
                            native_allowed=reason != 'native_deny')
    result = await journal.read(SCOPE, command)
    assert result['receipt']['side_effect_state'] == 'not_started'
    assert result['state'] == {'deny': 'denied', 'expire': 'expired', 'void': 'voided',
                               'changed': 'voided', 'native_deny': 'voided'}[reason]


@pytest.mark.asyncio
@pytest.mark.parametrize('started', [False, True])
async def test_recovery_never_replays_reserved_or_started_calls(journal, started):
    value, _ = await approved(journal)
    command, binding = value['command_id'], value['request_hash']
    await journal.reserve(SCOPE, command, 'resume', binding)
    if started:
        await journal.start(SCOPE, command, 'resume', binding, native_allowed=True)
    recovered = await journal.recover(SCOPE, command)
    assert recovered['receipt']['side_effect_state'] == 'unknown'
    assert recovered['receipt']['reconciliation_required'] is True
    assert await journal.start(SCOPE, command, 'resume', binding, native_allowed=True) is False
    assert await journal.recover(SCOPE, command) == recovered


@pytest.mark.asyncio
async def test_pending_recovery_preserves_request_and_revoking_started_is_unknown(journal):
    value = request()
    before = await journal.create(SCOPE, value)
    assert await journal.recover(SCOPE, value['command_id']) == before
    await journal.decide(SCOPE, value['command_id'], decision(value), 'key')
    await journal.reserve(SCOPE, value['command_id'], 'resume', value['request_hash'])
    await journal.start(SCOPE, value['command_id'], 'resume', value['request_hash'], native_allowed=True)
    await journal.void(SCOPE, value['command_id'])
    result = await journal.read(SCOPE, value['command_id'])
    assert result['state'] == 'voided'
    assert result['receipt']['side_effect_state'] == 'unknown'
    assert result['receipt']['reconciliation_required'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('mutate', [
    lambda value: value.update(auth='private'),
    lambda value: value['tool'].update(headers={'Authorization': 'private'}),
    lambda value: value.update(expires_at=0),
    lambda value: value.update(expires_at=int(time.time()) + 100000),
    lambda value: value.update(request_hash='not-a-digest'),
    lambda value: value['tool'].update(origin='plugin'),
])
async def test_invalid_or_secret_bearing_requests_are_not_persisted(journal, mutate):
    value = request()
    mutate(value)
    with failure('hexa_approval_invalid', 422):
        await journal.create(SCOPE, value)
    with failure('hexa_approval_not_found', 404):
        await journal.read(SCOPE, value['command_id'])


@pytest.mark.asyncio
async def test_expiry_is_durable_and_command_cannot_be_recreated(journal):
    value = request()
    await journal.create(SCOPE, value)
    journal.clock = lambda: value['expires_at']
    with failure('hexa_approval_expired', 410):
        await journal.decide(SCOPE, value['command_id'], decision(value), 'key')
    assert (await journal.read(SCOPE, value['command_id']))['state'] == 'expired'
    journal.clock = time.time
    with failure('hexa_approval_conflict'):
        await journal.create(SCOPE, {**value, 'expires_at': value['expires_at'] + 100})


@pytest.mark.asyncio
async def test_store_failure_propagates_instead_of_issuing_permission(journal):
    value, _ = await approved(journal)
    await journal.reserve(SCOPE, value['command_id'], 'resume', value['request_hash'])
    async def unavailable(*args, **kwargs):
        raise OSError('store unavailable')
    journal.container.replace_item = unavailable
    with pytest.raises(OSError):
        await journal.start(SCOPE, value['command_id'], 'resume', value['request_hash'], native_allowed=True)


def test_independent_writers_only_receive_one_start_permit(tmp_path):
    path = str(tmp_path / 'race.db')
    def make_journal():
        return ApprovalJournal(control_sqlite.SqliteContainer(path), control_sqlite)
    journal = make_journal()
    value, _ = asyncio.run(approved(journal))
    asyncio.run(journal.reserve(SCOPE, value['command_id'], 'resume', value['request_hash']))
    def race(_):
        return asyncio.run(make_journal().start(SCOPE, value['command_id'], 'resume', value['request_hash'], native_allowed=True))
    with ThreadPoolExecutor(max_workers=8) as pool:
        permits = list(pool.map(race, range(16)))
    assert permits.count(True) == 1
    assert permits.count(False) == 15


def test_conflicting_decisions_race_without_overwriting_the_winner(tmp_path):
    path = str(tmp_path / 'decision-race.db')
    def make_journal():
        return ApprovalJournal(control_sqlite.SqliteContainer(path), control_sqlite)
    value = request()
    asyncio.run(make_journal().create(SCOPE, value))
    def race(index):
        try:
            return asyncio.run(make_journal().decide(SCOPE, value['command_id'],
                                                     decision(value, 'approve' if index % 2 else 'deny'), f'key-{index}'))
        except ApprovalError as exc:
            assert exc.code == 'hexa_approval_conflict'
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [result for result in pool.map(race, range(16)) if result]
    assert len(results) == 1
    stored = asyncio.run(make_journal().read(SCOPE, value['command_id']))
    assert stored['receipt'] == results[0]


@pytest.mark.asyncio
async def test_scope_encoding_does_not_alias_delimiter_characters(journal):
    value = request()
    first = ApprovalScope('org::person', 'x', 'session', 'response')
    second = ApprovalScope('org', 'person::x', 'session', 'response')
    await journal.create(first, value)
    with failure('hexa_approval_not_found', 404):
        await journal.read(second, value['command_id'])


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    lambda payload: payload.update(arguments={'path': 'another-file'}),
    lambda payload: payload.update(decision='always'),
    lambda payload: payload.update(approval_id='approval_forged'),
])
async def test_malformed_or_forged_decisions_do_not_change_pending(journal, mutation):
    value = request()
    await journal.create(SCOPE, value)
    payload = decision(value)
    mutation(payload)
    with pytest.raises(ApprovalError):
        await journal.decide(SCOPE, value['command_id'], payload, 'key')
    assert (await journal.read(SCOPE, value['command_id']))['state'] == 'pending'


@pytest.mark.asyncio
async def test_expiry_after_start_preserves_actual_terminal_evidence(journal):
    value, _ = await approved(journal)
    await journal.reserve(SCOPE, value['command_id'], 'resume', value['request_hash'])
    await journal.start(SCOPE, value['command_id'], 'resume', value['request_hash'], native_allowed=True)
    journal.clock = lambda: value['expires_at'] + 100
    await journal.finish(SCOPE, value['command_id'], 'resume', 'completed')
    stored = await journal.recover(SCOPE, value['command_id'])
    assert stored['state'] == 'approved'
    assert stored['receipt']['side_effect_state'] == 'completed'
    assert stored['receipt']['reconciliation_required'] is False


@pytest.mark.asyncio
async def test_decision_and_record_match_proposed_wire_shapes(journal):
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[2] /
                         'protocol/proposals/tool-approvals/schema.json').read_text(encoding='utf-8'))
    value, _ = await approved(journal)
    validator = Draft202012Validator({**schema, 'oneOf': [{'$ref': '#/$defs/Record'}]})
    validator.validate(await journal.read(SCOPE, value['command_id']))
    await journal.reserve(SCOPE, value['command_id'], 'resume', value['request_hash'])
    validator.validate(await journal.recover(SCOPE, value['command_id']))


@pytest.mark.asyncio
async def test_configured_factory_reuses_existing_local_store(monkeypatch, tmp_path):
    import control_store
    monkeypatch.setenv('HR_BACKING', 'local')
    monkeypatch.setenv('HR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(control_store, '_ENDPOINT', '')
    monkeypatch.setattr(control_store, '_cont', None)
    journal = await ApprovalJournal.configured_control_store()
    value = request()
    await journal.create(SCOPE, value)
    monkeypatch.setattr(control_store, '_cont', None)
    reopened = await ApprovalJournal.configured_control_store()
    assert (await reopened.read(SCOPE, value['command_id']))['request'] == value


def test_revocation_racing_start_never_leaves_reusable_permission(tmp_path):
    path = str(tmp_path / 'revoke-race.db')
    def make_journal():
        return ApprovalJournal(control_sqlite.SqliteContainer(path), control_sqlite)
    journal = make_journal()
    value, _ = asyncio.run(approved(journal))
    command, binding = value['command_id'], value['request_hash']
    asyncio.run(journal.reserve(SCOPE, command, 'resume', binding))
    def race(index):
        if index == 0:
            asyncio.run(make_journal().void(SCOPE, command))
            return False
        try:
            return asyncio.run(make_journal().start(SCOPE, command, 'resume', binding, native_allowed=True))
        except ApprovalError as exc:
            assert exc.code == 'hexa_approval_not_pending'
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(race, range(16)))
    stored = asyncio.run(journal.read(SCOPE, command))
    assert results.count(True) <= 1
    assert stored['state'] == 'voided'
    assert stored['receipt']['side_effect_state'] == ('unknown' if any(results) else 'not_started')
    with failure('hexa_approval_not_pending'):
        asyncio.run(journal.start(SCOPE, command, 'resume', binding, native_allowed=True))


@pytest.mark.asyncio
async def test_invalid_requests_and_decisions_do_not_leak_sensitive_error_details(journal):
    value = request()
    value['tool']['headers'] = {'Authorization': 'sensitive-test-marker'}
    with pytest.raises(ApprovalError) as caught:
        await journal.create(SCOPE, value)
    assert str(caught.value) == 'hexa_approval_invalid'
    assert 'sensitive-test-marker' not in repr(caught.value)


@pytest.mark.asyncio
async def test_no_receipt_can_be_completed_without_start_permission(journal):
    value, _ = await approved(journal)
    with failure('hexa_approval_not_pending'):
        await journal.finish(SCOPE, value['command_id'], 'unreserved', 'completed')
    await journal.reserve(SCOPE, value['command_id'], 'resume', value['request_hash'])
    with failure('hexa_approval_conflict'):
        await journal.finish(SCOPE, value['command_id'], 'resume', 'completed')
    assert (await journal.read(SCOPE, value['command_id']))['receipt']['side_effect_state'] == 'not_started'


@pytest.mark.asyncio
@pytest.mark.parametrize('invalidate', ['expire', 'void'])
async def test_decision_replay_after_invalidation_remains_receipt_only(journal, invalidate):
    value, receipt = await approved(journal)
    if invalidate == 'expire':
        journal.clock = lambda: value['expires_at'] + 1
    else:
        await journal.void(SCOPE, value['command_id'])
    assert await journal.decide(SCOPE, value['command_id'], decision(value), 'decision-key') == receipt
    with pytest.raises(ApprovalError):
        await journal.reserve(SCOPE, value['command_id'], 'resume', value['request_hash'])
    assert (await journal.read(SCOPE, value['command_id']))['state'] == ('expired' if invalidate == 'expire' else 'voided')
