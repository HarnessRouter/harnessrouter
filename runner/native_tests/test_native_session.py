"""Native session registration lifetime with real HITL and durable SQLite."""
import asyncio
from pathlib import Path
import sys
import time
import threading

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.memory import InMemorySaver

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_lease import RuntimeLeaseRegistry, LeaseLost
from langgraph_approval import NativeApprovalError
try:
    from native_session import LangGraphNativeSession
except ModuleNotFoundError:
    LangGraphNativeSession = None
from test_langgraph_approval import graph, CONFIG, TOOL, bound, gate_for, decide, SCOPE, ScriptedModel


def session(runtime, store, **changes):
    assert LangGraphNativeSession is not None, 'native session lifecycle missing'
    return LangGraphNativeSession(runtime, CONFIG, {'write_report': TOOL}, registry=store,
        runtime_id='runtime', session_id='native-session', instance_id='instance', **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['approve', 'deny'])
async def test_session_registers_resumes_and_invalidates_retained_adapter(tmp_path, choice):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    output = tmp_path / 'tool.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = graph(saver, output)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        async with session(runtime, store) as live:
            registration = store.inspect_registration('runtime')
            assert registration['runtime_name'] == 'langgraph' and registration['runtime_version']
            token = store.acquire('runtime', 'owner', registration_id=registration['registration_id'],
                                  ttl=30, now=time.time()).token
            native = live.adapter(token)
            pending = await native.pending()
            gate = gate_for(tmp_path / 'control.db')
            call = bound(pending)
            await decide(gate, call, choice)
            resume = gate.execute if choice == 'approve' else gate.resume_denial
            await resume(SCOPE, call.command_id, 'resume', call, native_allowed=True,
                         dispatch=lambda saved: native.resume(pending, choice))
            store.release(token, now=time.time())
        assert store.inspect_registration('runtime')['expires_at'] <= time.time()
        with pytest.raises(NativeApprovalError, match='native_session_unavailable'):
            await native.pending()
        assert output.exists() == (choice == 'approve')


@pytest.mark.asyncio
async def test_session_health_failure_stops_renewal_and_rejects_old_adapter(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = graph(saver, tmp_path / 'tool.txt')
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        async with session(runtime, store, ttl=0.6) as live:
            reg = store.inspect_registration('runtime')
            token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=30, now=time.time()).token
            native = live.adapter(token)
            await native.pending()
            await saver.conn.close()
            await asyncio.wait_for(live.wait_lost(), timeout=5)
            with pytest.raises(NativeApprovalError, match='native_session_unavailable'):
                await native.pending()
            assert store.inspect_registration('runtime')['expires_at'] <= time.time()
            assert not (tmp_path / 'tool.txt').exists()


@pytest.mark.asyncio
async def test_session_heartbeat_and_duplicate_manager(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = graph(saver, tmp_path / 'tool.txt')
        async with session(runtime, store, ttl=0.6) as live:
            first = store.inspect_registration('runtime')
            async with asyncio.timeout(5):
                while store.inspect_registration('runtime')['expires_at'] <= first['expires_at']:
                    await asyncio.sleep(0.02)
            with pytest.raises(NativeApprovalError):
                async with session(runtime, store):
                    pytest.fail('duplicate session entered')
            assert store.inspect_registration('runtime')['registration_id'] == first['registration_id']


@pytest.mark.asyncio
async def test_memory_checkpoint_never_registers(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    with pytest.raises(NativeApprovalError):
        async with session(graph(InMemorySaver(), tmp_path / 'tool.txt'), store):
            pytest.fail('non-durable runtime registered')
    assert store.inspect_registration('runtime') is None


@pytest.mark.asyncio
async def test_closing_session_preserves_unknown_execution_pin(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = graph(saver, tmp_path / 'tool.txt')
        async with session(runtime, store) as live:
            reg = store.inspect_registration('runtime')
            token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=30, now=time.time()).token
            store.begin_execution(token, 'in-flight', now=time.time())
        state = store.inspect('runtime')
        assert state.execution_state == 'unknown' and state.execution_id == 'in-flight'
        with pytest.raises(LeaseLost):
            store.assert_owner(token, now=time.time())
        with pytest.raises(NativeApprovalError):
            async with session(runtime, store):
                pytest.fail('unknown execution reopened')


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['closed', 'sqlite-memory'])
async def test_unavailable_sqlite_checkpointer_never_registers(tmp_path, failure):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    path = ':memory:' if failure == 'sqlite-memory' else str(tmp_path / 'checkpoint.db')
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        runtime = graph(saver, tmp_path / 'tool.txt')
        if failure == 'closed':
            await saver.conn.close()
        with pytest.raises(NativeApprovalError, match='native_session_unavailable'):
            async with session(runtime, store):
                pytest.fail('unavailable checkpoint registered')
        assert store.inspect_registration('runtime') is None


@pytest.mark.asyncio
async def test_session_adapter_rejects_token_for_another_runtime(tmp_path):
    from dataclasses import replace
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        async with session(graph(saver, tmp_path / 'tool.txt'), store) as live:
            reg = store.inspect_registration('runtime')
            token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'], ttl=30, now=time.time()).token
            for altered in (replace(token, runtime_id='another'), replace(token, registration_id='old')):
                with pytest.raises(NativeApprovalError, match='native_session_unavailable'):
                    live.adapter(altered)
            store.release(token, now=time.time())


@pytest.mark.asyncio
async def test_revoked_registration_heartbeat_does_not_recreate_it(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        async with session(graph(saver, tmp_path / 'tool.txt'), store, ttl=0.6) as live:
            reg = store.inspect_registration('runtime')
            store.revoke_registration('runtime', reg['registration_id'], now=time.time())
            await asyncio.wait_for(live.wait_lost(), timeout=5)
            assert store.inspect_registration('runtime')['registration_id'] == reg['registration_id']
            assert store.inspect_registration('runtime')['expires_at'] <= time.time()


@pytest.mark.asyncio
async def test_old_session_exit_cannot_revoke_new_session_after_expiry(tmp_path):
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    clock = [100.0]
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = graph(saver, tmp_path / 'tool.txt')
        old = session(runtime, store, clock=lambda: clock[0])
        await old.__aenter__()
        first = store.inspect_registration('runtime')
        try:
            clock[0] = 200.0
            async with session(runtime, store, clock=lambda: clock[0]) as live:
                current = store.inspect_registration('runtime')
                assert current['registration_id'] != first['registration_id']
                await old.__aexit__(None, None, None)
                assert store.inspect_registration('runtime') == current
                token = store.acquire('runtime', 'new-owner', registration_id=current['registration_id'],
                                      ttl=10, now=200).token
                live.adapter(token)
                store.release(token, now=201)
        finally:
            await old.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_cancel_session_during_native_tool_keeps_unknown_after_thread_exits(tmp_path):
    from langchain.agents import create_agent
    from langchain.agents.middleware import HumanInTheLoopMiddleware
    from langchain_core.tools import tool
    entered, released, exited = threading.Event(), threading.Event(), threading.Event()
    commands = []
    store = RuntimeLeaseRegistry(str(tmp_path / 'lease.db'))
    output = tmp_path / 'tool.txt'
    @tool
    def write_report(text: str) -> str:
        """Write report with a controlled in-flight side effect."""
        entered.set()
        try:
            if not released.wait(10):
                raise RuntimeError('controlled test deadline')
            output.write_text(text)
            return 'saved'
        finally:
            exited.set()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = create_agent(ScriptedModel(), tools=[write_report], checkpointer=saver,
            middleware=[HumanInTheLoopMiddleware(interrupt_on={
                'write_report': {'allowed_decisions': ['approve', 'reject']}})])
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        async def execute():
            async with session(runtime, store) as live:
                reg = store.inspect_registration('runtime')
                token = store.acquire('runtime', 'owner', registration_id=reg['registration_id'],
                                      ttl=30, now=time.time()).token
                native = live.adapter(token)
                pending = await native.pending()
                gate = gate_for(tmp_path / 'control.db')
                call = bound(pending)
                commands.append(call.command_id)
                await decide(gate, call)
                await gate.execute(SCOPE, call.command_id, 'resume', call, native_allowed=True,
                                   dispatch=lambda saved: native.resume(pending, 'approve'))
        task = asyncio.create_task(execute())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert store.inspect('runtime').execution_state == 'unknown'
            released.set()
            assert await asyncio.to_thread(exited.wait, 5)
            assert output.exists()  # Cancellation did not stop the native tool thread.
            assert store.inspect('runtime').execution_state == 'unknown'
            receipt = await gate_for(tmp_path / 'control.db').journal.read(SCOPE, commands[0])
            assert receipt['receipt']['side_effect_state'] == 'unknown'
            with pytest.raises(NativeApprovalError):
                async with session(runtime, store):
                    pytest.fail('uncertain native execution restarted')
        finally:
            released.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
