"""Linux Runner: real internal transport bridge, sealed gate and native HITL."""
import os
from pathlib import Path
import sys
import time

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if os.name != 'posix':
    pytest.skip('native bridge server integration requires Linux Runner', allow_module_level=True)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runner'))
sys.path.insert(0, str(ROOT / 'gateway'))
import server
from native_session import LangGraphNativeSession
from runtime_ownership import RuntimeOwnership
from tool_approvals import ApprovalError
from test_langgraph_approval import graph, CONFIG, TOOL, gate_for, SCOPE
try:
    from native_approval import NativeApprovalCoordinator
except ModuleNotFoundError:
    NativeApprovalCoordinator = None


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['approve', 'deny'])
async def test_capture_decide_resume_over_authenticated_native_http(monkeypatch, tmp_path, choice):
    assert NativeApprovalCoordinator is not None, 'Gateway native bridge coordinator missing'
    assert hasattr(server, '_native_sessions'), 'Runner native directory not wired'
    monkeypatch.setenv('HR_RUNTIME_LEASE_DB', str(tmp_path / 'lease.db'))
    monkeypatch.setattr(server, '_INTERNAL_KEY', 'controlled-key')
    monkeypatch.setattr(server, '_SESSION_UIDS', False)
    store = server._runtime_leases()
    output = tmp_path / 'tool.txt'
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'checkpoint.db')) as saver:
        runtime = graph(saver, output)
        await runtime.ainvoke({'messages': [('user', 'write')]}, CONFIG)
        async with LangGraphNativeSession(runtime, CONFIG, {'write_report': TOOL}, registry=store,
            runtime_id='runtime', session_id=SCOPE.session, instance_id=server._RUNTIME_INSTANCE_ID) as live:
            with server._native_sessions.publish(live, registry=store, instance_id=server._RUNTIME_INSTANCE_ID):
                reg = store.inspect_registration('runtime')
                expected = {k: reg[k] for k in ('runtime_name', 'runtime_version', 'thread_id', 'checkpoint_ns',
                                               'checkpoint_backend', 'capabilities')}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://runner',
                        headers={'x-harness-internal': 'controlled-key'}) as http:
                    paths = []
                    async def transport(path, sid, method='POST', body=None):
                        paths.append(path)
                        response = await http.request(method, path, params={'identifier': sid}, json=body)
                        if response.status_code >= 400:
                            raise ApprovalError(f'controlled_{response.status_code}_'
                                                f'{response.json().get("detail", {}).get("code")}', 503)
                        response.raise_for_status()
                        return response.json()
                    gate = gate_for(tmp_path / 'control.db')
                    bridge = NativeApprovalCoordinator(gate, RuntimeOwnership(transport), transport)
                    execution = {'workspace': 'workspace', 'policy_digest': 'a' * 64,
                        'capability_digest': 'b' * 64, 'credential_versions': {}, 'environment_versions': {}}
                    record = await bridge.capture(SCOPE, 'runtime', expected, execution,
                        expires_at=int(time.time()) + 600, preview='Write report')
                    assert not output.exists()
                    req = record['request']
                    assert 'private-report-marker' not in str(record)
                    await gate.journal.decide(SCOPE, req['command_id'], {
                        'type': 'tool_approval_response', 'approval_id': req['id'], 'command_id': req['command_id'],
                        'request_hash': req['request_hash'], 'decision': choice}, 'decision-key')
                    result = await bridge.resume(SCOPE, 'runtime', expected, execution, req['command_id'],
                                                  'continuation', native_allowed=True)
                    assert result['receipt']['decision'] == choice
                    assert output.exists() == (choice == 'approve')
                    assert paths.count('/internal/native-approvals/resume') == 1
                    assert await bridge.resume(SCOPE, 'runtime', expected, execution, req['command_id'],
                                               'continuation', native_allowed=True) == result
                    assert paths.count('/internal/native-approvals/resume') == 1
                    assert store.inspect('runtime').owner is None
                    unauthorized = await http.post('/internal/native-approvals/pending', headers={
                        'x-harness-internal': 'wrong-key'}, json={
                            'runtime_id': 'runtime', 'owner': 'owner', 'fence': 1,
                            'registration_id': 'registration'})
                    assert unauthorized.status_code == 401
