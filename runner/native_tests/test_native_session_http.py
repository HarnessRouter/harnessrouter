"""Linux Runner image: lifecycle -> authenticated HTTP -> ownership -> HITL.

Imports the POSIX Runner and requires its delivery image plus native test deps.
Run explicitly on Linux; this is not a Windows test module.
"""
import sys
import os
from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if os.name != 'posix':
    pytest.skip('Runner HTTP requires the Unix delivery image; run explicitly in Linux', allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from native_session import LangGraphNativeSession
from runtime_ownership import RuntimeOwnership, OwnershipError
from runtime_lease import RuntimeLeaseToken
from test_langgraph_approval import graph, CONFIG, TOOL, bound, gate_for, decide, SCOPE


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['approve', 'deny'])
async def test_registered_session_through_runner_http_and_gateway_gate(monkeypatch, tmp_path, choice):
    monkeypatch.setenv('HR_RUNTIME_LEASE_DB', str(tmp_path / 'lease.db'))
    monkeypatch.setattr(server, '_INTERNAL_KEY', 'controlled-key')
    monkeypatch.setattr(server, '_SESSION_UIDS', False)
    store = server._runtime_leases()
    output = tmp_path / 'tool.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = graph(saver, output)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://runner',
                                     headers={'x-harness-internal': 'controlled-key'}) as http:
            async def transport(path, sid, method='POST', body=None):
                response = await http.request(method, path, params={'identifier': sid}, json=body)
                response.raise_for_status()
                return response.json()
            async with LangGraphNativeSession(runtime, CONFIG, {'write_report': TOOL}, registry=store,
                    runtime_id='runtime', session_id='native-session', instance_id=server._RUNTIME_INSTANCE_ID) as live:
                reg = store.inspect_registration('runtime')
                expected = {k: reg[k] for k in ('runtime_name', 'runtime_version', 'thread_id', 'checkpoint_ns',
                                               'checkpoint_backend', 'capabilities')}
                async def operation(token):
                    native = live.adapter(RuntimeLeaseToken(**token))
                    pending = await native.pending()
                    call = bound(pending)
                    gate = gate_for(tmp_path / 'control.db')
                    await decide(gate, call, choice)
                    resume = gate.execute if choice == 'approve' else gate.resume_denial
                    return await resume(SCOPE, call.command_id, 'resume', call, native_allowed=True,
                                        dispatch=lambda saved: native.resume(pending, choice))
                await RuntimeOwnership(transport).run_registered('native-session', 'runtime', expected, operation)
                assert store.inspect('runtime').owner is None
                assert output.exists() == (choice == 'approve')
            async def forbidden(token):
                pytest.fail('closed session dispatched')
            with pytest.raises(OwnershipError, match='runtime_registration_unavailable'):
                await RuntimeOwnership(transport).run_registered('native-session', 'runtime', expected, forbidden)
