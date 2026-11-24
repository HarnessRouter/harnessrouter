"""Durable delivery of a denial must not imply that its tool executed."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_sqlite
from approval_execution import BoundApprovalGate, Invocation
from tool_approvals import ApprovalError, ApprovalJournal, ApprovalScope

SCOPE = ApprovalScope('org', 'owner', 'session', 'response')


def reopen(path):
    return BoundApprovalGate(ApprovalJournal(control_sqlite.SqliteContainer(str(path)), control_sqlite), b'k' * 32)


@pytest.fixture
def gate(tmp_path):
    return reopen(tmp_path / 'control.db')


def invocation():
    return Invocation('command-deny', {'name': 'write', 'origin': 'runtime'}, b'{ "text": "private-marker" }',
                      b'exact-checkpoint', 'workspace', {'name': 'native', 'version': '1'}, 'a' * 64, 'b' * 64, {}, {})


async def prepare(gate, choice='deny'):
    call = invocation()
    record = await gate.capture(SCOPE, call, expires_at=int(time.time()) + 600, preview='write')
    decision = {'type': 'tool_approval_response', 'approval_id': record['request']['id'], 'command_id': call.command_id,
                'request_hash': record['request']['request_hash'], 'decision': choice}
    receipt = await gate.journal.decide(SCOPE, call.command_id, decision, 'decision-key')
    return call, record['request'], decision, receipt


def method(gate):
    assert callable(getattr(gate, 'resume_denial', None)), 'durable denial continuation is not implemented'
    return gate.resume_denial


@pytest.mark.asyncio
async def test_multiple_reopened_gates_deliver_one_exact_denial_without_tool_effects(gate):
    call, req, decision, receipt = await prepare(gate)
    seen = []
    async def deliver(saved):
        seen.append(saved)
        await asyncio.sleep(.01)
        return 'native-denied'
    gates = [reopen(gate.journal.container._path) for _ in range(8)]
    results = await asyncio.gather(*(method(item)(SCOPE, call.command_id, 'resume-denial', call,
                                                native_allowed=True, dispatch=deliver) for item in gates))
    assert seen == [call] and results.count('native-denied') == 1
    assert results.count(None) == 7
    stored = await gate.journal.read(SCOPE, call.command_id)
    assert stored['state'] == 'denied'
    assert stored['receipt'] == receipt
    assert receipt['side_effect_state'] == 'not_started' and receipt['reconciliation_required'] is False
    assert stored['continuation_receipt'] == {'decision': 'deny', 'state': 'completed', 'reconciliation_required': False}
    assert await gate.journal.decide(SCOPE, call.command_id, decision, 'decision-key') == receipt


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['approve', 'expire', 'void', 'native', 'arguments', 'checkpoint', 'capability', 'scope', 'other-continuation'])
async def test_denial_delivery_requires_current_exact_scoped_and_active_consent(gate, reason):
    call, req, _, _ = await prepare(gate, 'approve' if reason == 'approve' else 'deny')
    if reason == 'expire':
        gate.journal.clock = lambda: req['expires_at'] + 1
    elif reason == 'void':
        await gate.journal.void(SCOPE, call.command_id)
    elif reason == 'other-continuation':
        await gate.journal.reserve(SCOPE, call.command_id, 'already-reserved', req['request_hash'])
    current = call
    if reason == 'arguments':
        current = replace(call, arguments=b'{"text":"replacement"}')
    elif reason == 'checkpoint':
        current = replace(call, checkpoint=b'other-checkpoint')
    elif reason == 'capability':
        current = replace(call, capability_digest='c' * 64)
    async def forbidden(saved):
        pytest.fail('ineligible denial dispatched')
    with pytest.raises(ApprovalError):
        await method(gate)(replace(SCOPE, principal='stranger') if reason == 'scope' else SCOPE,
                           call.command_id, 'resume-denial', current, native_allowed=reason != 'native', dispatch=forbidden)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['exception', 'cancel', 'recover', 'void'])
async def test_interrupted_denial_is_unknown_and_never_delivered_twice(gate, failure):
    call, _, _, receipt = await prepare(gate)
    seen = []
    async def deliver(saved):
        seen.append(saved)
        if failure == 'recover':
            await gate.journal.recover(SCOPE, call.command_id)
            raise TimeoutError()
        if failure == 'void':
            await gate.journal.void(SCOPE, call.command_id)
            raise TimeoutError()
        if failure == 'cancel':
            raise asyncio.CancelledError()
        raise TimeoutError()
    with pytest.raises((TimeoutError, asyncio.CancelledError)):
        await method(gate)(SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=deliver)
    stored = await gate.journal.read(SCOPE, call.command_id)
    assert stored['receipt'] == receipt
    assert stored['continuation_receipt'] == {'decision': 'deny', 'state': 'unknown', 'reconciliation_required': True}
    if failure == 'void':
        with pytest.raises(ApprovalError):
            await method(gate)(SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=deliver)
    else:
        assert await method(reopen(gate.journal.container._path))(
            SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=deliver) is None
    assert seen == [call]


@pytest.mark.asyncio
async def test_failed_start_write_cannot_deliver_a_denial(gate, monkeypatch):
    call, req, _, _ = await prepare(gate)
    await gate.journal.reserve(SCOPE, call.command_id, 'resume-denial', req['request_hash'])
    async def unavailable(*args, **kwargs):
        raise OSError('store unavailable')
    monkeypatch.setattr(gate.journal.container, 'replace_item', unavailable)
    async def forbidden(saved):
        pytest.fail('start write failed but dispatched')
    with pytest.raises(OSError):
        await method(gate)(SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=forbidden)


@pytest.mark.asyncio
async def test_completed_denial_is_monotonic_across_recovery_and_expiry(gate):
    call, req, _, receipt = await prepare(gate)
    async def deliver(saved):
        return 'denied'
    await method(gate)(SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=deliver)
    gate.journal.clock = lambda: req['expires_at'] + 1
    stored = await gate.journal.recover(SCOPE, call.command_id)
    assert stored['state'] == 'denied' and stored['receipt'] == receipt
    assert stored['continuation_receipt']['state'] == 'completed'
    assert await method(gate)(SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=deliver) is None


@pytest.mark.asyncio
async def test_owner_crash_after_denial_start_is_unknown_when_reopened(gate):
    call, req, _, receipt = await prepare(gate)
    await gate.journal.reserve(SCOPE, call.command_id, 'resume-denial', req['request_hash'])
    assert await gate.journal.start_denial(SCOPE, call.command_id, 'resume-denial', req['request_hash'], native_allowed=True)
    # No callback/finish; the owner died after the durable start permit.
    fresh = reopen(gate.journal.container._path)
    stored = await fresh.journal.recover(SCOPE, call.command_id)
    assert stored['continuation_receipt']['state'] == 'unknown'
    assert stored['receipt'] == receipt
    with pytest.raises(ApprovalError, match='hexa_approval_conflict'):
        await fresh.journal.finish_denial(SCOPE, call.command_id, 'resume-denial')
    async def forbidden(saved):
        pytest.fail('unknown delivery replayed')
    assert await method(fresh)(SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=forbidden) is None


@pytest.mark.asyncio
async def test_no_denial_finish_without_a_denial_start_and_no_approve_start_for_deny(gate):
    call, req, _, _ = await prepare(gate)
    await gate.journal.reserve(SCOPE, call.command_id, 'resume-denial', req['request_hash'])
    with pytest.raises(ApprovalError, match='hexa_approval_conflict'):
        await gate.journal.finish_denial(SCOPE, call.command_id, 'resume-denial')
    with pytest.raises(ApprovalError, match='hexa_approval_not_pending'):
        await gate.journal.start(SCOPE, call.command_id, 'resume-denial', req['request_hash'], native_allowed=True)


def test_multithread_denial_start_racing_revocation_never_reopens_permission(tmp_path):
    path = tmp_path / 'race.db'
    gate = reopen(path)
    call, req, _, receipt = asyncio.run(prepare(gate))
    asyncio.run(gate.journal.reserve(SCOPE, call.command_id, 'resume-denial', req['request_hash']))
    def race(index):
        journal = reopen(path).journal
        if index == 0:
            asyncio.run(journal.void(SCOPE, call.command_id))
            return False
        try:
            return asyncio.run(journal.start_denial(SCOPE, call.command_id, 'resume-denial',
                                                   req['request_hash'], native_allowed=True))
        except ApprovalError as exc:
            assert exc.code == 'hexa_approval_not_pending'
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(race, range(16)))
    stored = asyncio.run(reopen(path).journal.read(SCOPE, call.command_id))
    assert results.count(True) <= 1 and stored['state'] == 'voided'
    assert stored['receipt'] == receipt
    if any(results):
        assert stored['continuation_receipt']['state'] == 'unknown'
    else:
        assert 'continuation_receipt' not in stored
    with pytest.raises(ApprovalError):
        asyncio.run(gate.journal.start_denial(SCOPE, call.command_id, 'resume-denial', req['request_hash'], native_allowed=True))


@pytest.mark.asyncio
async def test_lost_finish_persistence_marks_denial_unknown_without_replaying(gate, monkeypatch):
    call, _, _, receipt = await prepare(gate)
    seen = []
    async def unavailable(*args, **kwargs):
        raise OSError('finish write failed')
    monkeypatch.setattr(gate.journal, 'finish_denial', unavailable)
    async def deliver(saved):
        seen.append(saved)
        return 'native denied'
    with pytest.raises(OSError):
        await method(gate)(SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=deliver)
    stored = await gate.journal.read(SCOPE, call.command_id)
    assert stored['receipt'] == receipt and stored['continuation_receipt']['state'] == 'unknown'
    assert await method(reopen(gate.journal.container._path))(
        SCOPE, call.command_id, 'resume-denial', call, native_allowed=True, dispatch=deliver) is None
    assert seen == [call]
