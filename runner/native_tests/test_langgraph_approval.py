"""Real HITL graph + SQLite; deterministic model/tool, no Provider or UHP proof."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runner'))
sys.path.insert(0, str(ROOT / 'gateway'))
from approval_execution import BoundApprovalGate, Invocation
from tool_approvals import ApprovalError, ApprovalJournal, ApprovalScope
from runtime_lease import RuntimeLeaseRegistry, LeaseConflict
from runtime_ownership import RuntimeOwnership
import control_sqlite
try:
    from langgraph_approval import NativeApprovalError, LangGraphApprovalAdapter
except ModuleNotFoundError:
    NativeApprovalError = LangGraphApprovalAdapter = None

SCOPE = ApprovalScope('native-org', 'owner', 'native-session', 'native-response')
TOOL = {'name': 'write_report', 'origin': 'runtime'}
CONFIG = {'configurable': {'thread_id': 'native-session'}}


class ScriptedModel(BaseChatModel):
    """The only fake boundary: deterministically propose one real tool call."""
    calls: int = 0
    count: int = 1

    @property
    def _llm_type(self):
        return 'controlled-native-approval-test'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if any(isinstance(message, ToolMessage) for message in messages):
            answer = AIMessage(content='Report saved')
        else:
            answer = AIMessage(content='', tool_calls=[
                {'name': 'write_report', 'args': {'text': 'private-report-marker'},
                 'id': f'call-{index}', 'type': 'tool_call'} for index in range(self.count)])
        return ChatResult(generations=[ChatGeneration(message=answer)])


def graph(saver, path, model=None, crash=False):
    @tool
    def write_report(text: str) -> str:
        """Append a report to the controlled temporary workspace."""
        with path.open('a', encoding='utf-8') as stream:
            stream.write(text + '\n')
        if crash:
            raise RuntimeError('private-tool-crash-marker')
        return 'saved'

    return create_agent(model or ScriptedModel(), tools=[write_report], checkpointer=saver,
                        middleware=[HumanInTheLoopMiddleware(interrupt_on={
                            'write_report': {'allowed_decisions': ['approve', 'reject']}})])


def adapter(runtime, catalog=None):
    assert LangGraphApprovalAdapter is not None, 'native checkpoint adapter is not implemented'
    return LangGraphApprovalAdapter(runtime, CONFIG, catalog or {'write_report': TOOL})


def gate_for(path):
    return BoundApprovalGate(ApprovalJournal(control_sqlite.SqliteContainer(str(path)), control_sqlite), b'k' * 32)


def bound(pending, **changes):
    call = Invocation(command_id=pending.command_id, tool=pending.tool,
                      arguments=pending.arguments, checkpoint=pending.checkpoint,
                      workspace='controlled-workspace', runtime={'name': 'langgraph-test', 'version': '1.1.8'},
                      policy_digest='a' * 64, capability_digest='b' * 64,
                      credential_versions={}, environment_versions={})
    return replace(call, **changes)


async def decide(gate, call, choice='approve', record=None):
    if record is None:
        record = await gate.capture(SCOPE, call, expires_at=int(time.time()) + 600, preview='Write report')
    req = record['request']
    decision = {'type': 'tool_approval_response', 'approval_id': req['id'], 'command_id': call.command_id,
                'request_hash': req['request_hash'], 'decision': choice}
    first = await gate.journal.decide(SCOPE, call.command_id, decision, 'decision-key')
    assert await gate.journal.decide(SCOPE, call.command_id, decision, 'decision-key') == first
    return record


@pytest.mark.asyncio
async def test_checkpoint_reopen_and_concurrent_approval_resumes_original_tool_once(tmp_path):
    path, state, control = tmp_path / 'report.txt', tmp_path / 'runtime.db', tmp_path / 'control.db'
    model = ScriptedModel()
    async with AsyncSqliteSaver.from_conn_string(str(state)) as saver:
        runtime = graph(saver, path, model)
        await runtime.ainvoke({'messages': [('user', 'write report')]}, CONFIG)
        assert not path.exists() and model.calls == 1
        pending = await adapter(runtime).pending()
        call = bound(pending)
        record = await gate_for(control).capture(SCOPE, call, expires_at=int(time.time()) + 600, preview='Write report')
        assert 'private-report-marker' not in json.dumps(record)
        assert json.loads(pending.arguments) == {'text': 'private-report-marker'}

    # Close/reopen both stores and reconstruct the graph. No replacement prompt/model request.
    model = ScriptedModel()
    async with AsyncSqliteSaver.from_conn_string(str(state)) as saver:
        runtime = graph(saver, path, model)
        native = adapter(runtime)
        assert await native.pending() == pending
        gate = gate_for(control)
        await decide(gate, call, record=record)
        current = bound(await native.pending())

        async def dispatch(saved):
            assert saved.arguments == call.arguments and saved.checkpoint == call.checkpoint
            return await native.resume(pending, 'approve')

        results = await asyncio.gather(*(gate.execute(SCOPE, call.command_id, 'resume-1', current,
                                                     native_allowed=True, dispatch=dispatch) for _ in range(6)))
        assert sum(result is not None for result in results) == 1
        assert path.read_text().splitlines() == ['private-report-marker']
        assert model.calls == 1  # only the answer AFTER the tool; no regenerated invocation
        assert (await gate.journal.read(SCOPE, call.command_id))['receipt']['side_effect_state'] == 'completed'
        assert not (await runtime.aget_state(CONFIG)).interrupts


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['deny', 'expired', 'voided', 'native-deny', 'policy', 'capability', 'plugin'])
async def test_gateway_denial_and_stale_consent_never_resume_native_tool(tmp_path, reason):
    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = adapter(runtime)
        pending = await native.pending()
        call = bound(pending)
        gate = gate_for(tmp_path / 'control.db')
        record = await decide(gate, call, 'deny' if reason == 'deny' else 'approve')
        if reason == 'expired':
            gate.journal.clock = lambda: record['request']['expires_at'] + 1
        elif reason == 'voided':
            await gate.journal.void(SCOPE, call.command_id)
        current = call
        if reason == 'policy':
            current = replace(call, policy_digest='c' * 64)
        elif reason == 'capability':
            current = replace(call, capability_digest='d' * 64)
        elif reason == 'plugin':
            current = replace(call, tool={'name': 'write_report', 'origin': 'plugin', 'plugin_name': 'report',
                                         'plugin_version': '2', 'plugin_digest': 'e' * 64})
        with pytest.raises(ApprovalError):
            await gate.execute(SCOPE, call.command_id, 'resume', current, native_allowed=reason != 'native-deny',
                               dispatch=lambda saved: native.resume(pending, 'approve'))
        assert not path.exists()
        assert (await runtime.aget_state(CONFIG)).interrupts


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['checkpoint', 'arguments'])
async def test_native_checkpoint_change_blocks_resume_even_with_saved_approval(tmp_path, change):
    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = adapter(runtime)
        pending = await native.pending()
        snapshot = await runtime.aget_state(CONFIG)
        if change == 'arguments':
            message = snapshot.values['messages'][-1].model_copy(deep=True)
            message.tool_calls[0]['args'] = {'text': 'replaced'}
            await runtime.aupdate_state(CONFIG, {'messages': [message]})
        else:
            await runtime.aupdate_state(CONFIG, {'messages': []})
        with pytest.raises(NativeApprovalError, match='native_approval_changed'):
            await native.resume(pending, 'approve')
        assert not path.exists()


@pytest.mark.asyncio
async def test_native_reject_continues_without_running_the_tool(tmp_path):
    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = adapter(runtime)
        await native.resume(await native.pending(), 'deny')
        assert not path.exists()
        assert not (await runtime.aget_state(CONFIG)).interrupts


@pytest.mark.asyncio
async def test_durable_denial_does_not_authorize_a_followup_tool_request(tmp_path):
    class ReaskModel(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
                'name': 'write_report', 'args': {'text': 'private-report-marker'},
                'id': f'new-call-{self.calls}', 'type': 'tool_call'}]))])

    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path, ReaskModel())
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = adapter(runtime)
        pending = await native.pending()
        call = bound(pending)
        gate = gate_for(tmp_path / 'control.db')
        await decide(gate, call, 'deny')
        await gate.resume_denial(SCOPE, call.command_id, 'deny-resume', call, native_allowed=True,
                                 dispatch=lambda saved: native.resume(pending, 'deny'))
        again = await native.pending()
        assert again.command_id != pending.command_id
        assert again.checkpoint != pending.checkpoint
        assert not path.exists()
        assert (await gate.journal.read(SCOPE, call.command_id))['continuation_receipt']['state'] == 'completed'
        with pytest.raises(ApprovalError, match='hexa_approval_not_found'):
            await gate.execute(SCOPE, again.command_id, 'forged-resume', bound(again), native_allowed=True,
                               dispatch=lambda saved: native.resume(again, 'approve'))
        assert not path.exists()


@pytest.mark.asyncio
async def test_native_error_after_effect_is_unknown_and_gateway_never_replays(tmp_path):
    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path, crash=True)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = adapter(runtime)
        pending = await native.pending()
        call = bound(pending)
        gate = gate_for(tmp_path / 'control.db')
        await decide(gate, call)
        with pytest.raises(RuntimeError):
            await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True,
                               dispatch=lambda saved: native.resume(pending, 'approve'))
        receipt = (await gate.journal.read(SCOPE, call.command_id))['receipt']
        assert receipt['side_effect_state'] == 'unknown' and receipt['reconciliation_required'] is True
        assert await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True,
                                  dispatch=lambda saved: native.resume(pending, 'approve')) is None
        assert path.read_text().splitlines() == ['private-report-marker']


@pytest.mark.asyncio
@pytest.mark.parametrize('unsupported', ['memory', 'batch', 'unknown-tool'])
async def test_unsupported_checkpoint_or_tool_coverage_is_refused(tmp_path, unsupported):
    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        selected = InMemorySaver() if unsupported == 'memory' else saver
        runtime = graph(selected, path, ScriptedModel(count=2 if unsupported == 'batch' else 1))
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        assert LangGraphApprovalAdapter is not None, 'native checkpoint adapter is not implemented'
        with pytest.raises(NativeApprovalError, match='native_approval_unavailable'):
            await adapter(runtime, {'other': {'name': 'other', 'origin': 'runtime'}} if unsupported == 'unknown-tool' else None).pending()
        assert not path.exists()


@pytest.mark.asyncio
async def test_in_memory_sqlite_is_not_a_durable_checkpoint(tmp_path):
    async with AsyncSqliteSaver.from_conn_string(':memory:') as saver:
        runtime = graph(saver, tmp_path / 'report.txt')
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        with pytest.raises(NativeApprovalError, match='^native_approval_unavailable$'):
            await adapter(runtime).pending()


@pytest.mark.asyncio
async def test_concurrent_native_adapter_resume_revalidates_after_first_completion(tmp_path):
    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = adapter(runtime)
        pending = await native.pending()
        results = await asyncio.gather(*(native.resume(pending, 'approve') for _ in range(4)), return_exceptions=True)
        assert sum(isinstance(result, dict) for result in results) == 1
        assert sum(isinstance(result, NativeApprovalError) for result in results) == 3
        assert path.read_text().splitlines() == ['private-report-marker']


@pytest.mark.parametrize('choice', ['approve', 'deny'])
def test_separate_process_restarts_resume_saved_native_checkpoint(tmp_path, choice):
    def process(phase):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), phase, str(tmp_path), choice],
                                capture_output=True, text=True, timeout=45,
                                env={**os.environ, 'LANGSMITH_TRACING': 'false', 'LANGCHAIN_TRACING_V2': 'false'})
        assert result.returncode == 0, result.stderr
        assert 'private-report-marker' not in result.stdout
        return json.loads(result.stdout)
    first = process('capture')
    assert first['state'] == 'pending' and not (tmp_path / 'report.txt').exists()
    second = process('resume')
    assert second['request_hash'] == first['request_hash'] and second['state'] == 'completed'
    assert second['side_effect_state'] == ('completed' if choice == 'approve' else 'not_started')
    assert second['pending_interrupts'] == 0
    third = process('replay')
    assert third['request_hash'] == first['request_hash'] and third['state'] == 'completed'
    if choice == 'approve':
        assert (tmp_path / 'report.txt').read_text().splitlines() == ['private-report-marker']
    else:
        assert not (tmp_path / 'report.txt').exists()


async def _process_journey(phase, folder, choice):
    """Separate OS processes share only two SQLite stores; no serialized fake state."""
    async with AsyncSqliteSaver.from_conn_string(str(folder / 'runtime.db')) as saver:
        runtime = graph(saver, folder / 'report.txt')
        native = adapter(runtime)
        gate = gate_for(folder / 'control.db')
        if phase == 'capture':
            await runtime.ainvoke({'messages': [('user', 'write report')]}, CONFIG)
            call = bound(await native.pending())
            record = await gate.capture(SCOPE, call, expires_at=int(time.time()) + 600, preview='Write report')
            (folder / 'command.txt').write_text(call.command_id)
        else:
            command = (folder / 'command.txt').read_text()
            call = await gate.load(SCOPE, command)
            record = await gate.journal.read(SCOPE, command)
            if phase == 'resume':
                await decide(gate, call, choice, record=record)
                pending = await native.pending()
                resume = gate.execute if choice == 'approve' else gate.resume_denial
                await resume(SCOPE, command, 'process-resume', bound(pending), native_allowed=True,
                             dispatch=lambda saved: native.resume(pending, choice))
            else:
                async def forbidden(saved):
                    raise AssertionError('completed command was replayed')
                resume = gate.execute if choice == 'approve' else gate.resume_denial
                assert await resume(SCOPE, command, 'process-resume', call, native_allowed=True,
                                    dispatch=forbidden) is None
            record = await gate.journal.read(SCOPE, command)
        effect = record.get('receipt', {}).get('side_effect_state', record['state'])
        print(json.dumps({'request_hash': record['request']['request_hash'],
                          'state': record.get('continuation_receipt', {}).get('state', effect),
                          'side_effect_state': effect,
                          'pending_interrupts': len((await runtime.aget_state(CONFIG)).interrupts)}))


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['approve', 'deny'])
async def test_bound_adapter_checks_expiry_after_checkpoint_read(tmp_path, choice, monkeypatch):
    path = tmp_path / 'report.txt'
    clock = [100.0]
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    token = registry.acquire('native-session', 'owner', ttl=10, now=clock[0]).token
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = LangGraphApprovalAdapter(runtime, CONFIG, {'write_report': TOOL},
            lease_registry=registry, lease_token=token, clock=lambda: clock[0])
        pending = await native.pending()
        read = runtime.aget_state

        async def expire_during_read(*args, **kwargs):
            result = await read(*args, **kwargs)
            clock[0] = 111.0
            return result

        monkeypatch.setattr(runtime, 'aget_state', expire_during_read)
        with pytest.raises(NativeApprovalError, match='runtime_lease_lost'):
            await native.resume(pending, choice)
        assert not path.exists()
        with pytest.raises(LeaseConflict):
            registry.acquire('native-session', 'next', ttl=10, now=200)


@pytest.mark.asyncio
async def test_bound_adapter_pins_execution_until_native_returns(tmp_path, monkeypatch):
    path = tmp_path / 'report.txt'
    clock = [100.0]
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    token = registry.acquire('native-session', 'owner', ttl=10, now=clock[0]).token
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = LangGraphApprovalAdapter(runtime, CONFIG, {'write_report': TOOL},
            lease_registry=registry, lease_token=token, clock=lambda: clock[0])
        pending = await native.pending()
        invoke = runtime.ainvoke

        async def expire_after_invocation(*args, **kwargs):
            result = await invoke(*args, **kwargs)
            clock[0] = 111.0
            with pytest.raises(LeaseConflict):
                registry.acquire('native-session', 'next', ttl=30, now=111)
            return result

        monkeypatch.setattr(runtime, 'ainvoke', expire_after_invocation)
        with pytest.raises(NativeApprovalError, match='runtime_lease_lost'):
            await native.resume(pending, 'approve')
        assert path.read_text().splitlines() == ['private-report-marker']
        state = registry.inspect('native-session')
        assert state.execution_id and state.execution_state == 'unknown'


@pytest.mark.asyncio
async def test_bound_adapter_success_clears_pin(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    token = registry.acquire('native-session', 'owner', ttl=10, now=100).token
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        path = tmp_path / 'report.txt'
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = LangGraphApprovalAdapter(runtime, CONFIG, {'write_report': TOOL},
            lease_registry=registry, lease_token=token, clock=lambda: 101)
        await native.resume(await native.pending(), 'approve')
        assert registry.inspect('native-session').execution_id is None
        registry.release(token, now=102)
        assert path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['cancel', 'error'])
async def test_bound_adapter_uncertain_dispatch_remains_pinned(tmp_path, monkeypatch, failure):
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    token = registry.acquire('native-session', 'owner', ttl=10, now=100).token
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, tmp_path / 'report.txt')
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        native = LangGraphApprovalAdapter(runtime, CONFIG, {'write_report': TOOL},
            lease_registry=registry, lease_token=token, clock=lambda: 101)
        pending = await native.pending()
        entered, blocked = asyncio.Event(), asyncio.Event()

        async def interrupted(*args, **kwargs):
            entered.set()
            if failure == 'error':
                raise RuntimeError('controlled failure')
            await blocked.wait()

        monkeypatch.setattr(runtime, 'ainvoke', interrupted)
        task = asyncio.create_task(native.resume(pending, 'approve'))
        await asyncio.wait_for(entered.wait(), timeout=5)
        if failure == 'cancel':
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == 'cancel' else RuntimeError):
            await task
        state = registry.inspect('native-session')
        assert state.execution_id and state.execution_state == 'unknown'
        with pytest.raises(LeaseConflict):
            registry.acquire('native-session', 'next', ttl=10, now=200)


@pytest.mark.asyncio
async def test_two_adapter_objects_share_one_durable_execution_pin(tmp_path, monkeypatch):
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    token = registry.acquire('native-session', 'owner', ttl=10, now=100).token
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        path = tmp_path / 'report.txt'
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        adapters = [LangGraphApprovalAdapter(runtime, CONFIG, {'write_report': TOOL},
            lease_registry=RuntimeLeaseRegistry(registry.path), lease_token=token, clock=lambda: 101)
            for _ in range(2)]
        pending = await adapters[0].pending()
        entered, release = asyncio.Event(), asyncio.Event()
        invoke = runtime.ainvoke

        async def held(*args, **kwargs):
            entered.set()
            await release.wait()
            return await invoke(*args, **kwargs)

        monkeypatch.setattr(runtime, 'ainvoke', held)
        task = asyncio.create_task(adapters[0].resume(pending, 'approve'))
        await asyncio.wait_for(entered.wait(), timeout=5)
        try:
            with pytest.raises(NativeApprovalError, match='runtime_lease_lost'):
                await adapters[1].resume(pending, 'approve')
        finally:
            release.set()
            await task
        assert path.read_text().splitlines() == ['private-report-marker']


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['approve', 'deny'])
async def test_ownership_coordinator_gate_native_journey(tmp_path, choice):
    """Real native checkpoint + gate + ownership registry; no Provider/Response proof."""
    from dataclasses import asdict
    from runtime_lease import RuntimeLeaseToken

    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.db'))
    async def transport(path, sid, method='POST', body=None):
        assert sid == 'native-session'
        if path.endswith('/acquire'):
            state = registry.acquire(body['runtime_id'], body['owner'],
                                     ttl=body['ttl_seconds'], now=time.time())
        elif path.endswith('/renew'):
            state = registry.renew(RuntimeLeaseToken(body['runtime_id'], body['owner'], body['fence']),
                                   ttl=body['ttl_seconds'], now=time.time())
        else:
            assert path.endswith('/release')
            state = registry.release(RuntimeLeaseToken(body['runtime_id'], body['owner'], body['fence']), now=time.time())
        return asdict(state)

    path = tmp_path / 'report.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'runtime.db')) as saver:
        runtime = graph(saver, path)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        pending = await adapter(runtime).pending()
        call = bound(pending)
        gate = gate_for(tmp_path / 'control.db')
        await decide(gate, call, choice)

        async def operation(token):
            native = LangGraphApprovalAdapter(runtime, CONFIG, {'write_report': TOOL},
                lease_registry=registry, lease_token=RuntimeLeaseToken(**token))
            current = await native.pending()
            resume = gate.execute if choice == 'approve' else gate.resume_denial
            return await resume(SCOPE, call.command_id, 'owned-resume', bound(current), native_allowed=True,
                                dispatch=lambda saved: native.resume(current, choice))

        await RuntimeOwnership(transport).run('native-session', 'native-session', operation)
        assert registry.inspect('native-session').owner is None
        assert not (await runtime.aget_state(CONFIG)).interrupts
        if choice == 'approve':
            assert path.read_text().splitlines() == ['private-report-marker']
        else:
            assert not path.exists()


if __name__ == '__main__':
    asyncio.run(_process_journey(sys.argv[1], Path(sys.argv[2]), sys.argv[3]))
