"""Approval requirements must survive saving and must never become autonomous work."""
import copy

import pytest
from sqlalchemy import func, select

from app.db.models import CommandReceipt, NodeRun, Run, RunEvent
from app.tasks.service import TaskError, TaskExecutor, workflow_from_json
from tests.test_conversations import login
from tests.test_task_concurrency import seed_run
from tests.test_task_workflows import node, wait_run


POLICY = {'require': ['external_write', 'destructive']}
RISKS = ['read_only', 'workspace_read', 'workspace_write', 'local_process', 'network_read',
         'external_write', 'credential_access', 'destructive', 'permission_change']


def definition(scope, policy=POLICY):
    workflow = {'nodes': [node('source'), node('worker', deps=['source'])]}
    if scope == 'workflow':
        workflow['tool_approval_policy'] = copy.deepcopy(policy)
    elif scope == 'node':
        workflow['nodes'][1]['tool_approval_policy'] = copy.deepcopy(policy)
    else:
        child = node('leaf', tool_approval_policy=copy.deepcopy(policy))
        if scope == 'nested':
            child = node('inner', subgraph={'nodes': [child]})
        workflow['nodes'][1]['subgraph'] = {'nodes': [child]}
    return workflow


@pytest.mark.parametrize('scope', ['workflow', 'node', 'subgraph', 'nested'])
@pytest.mark.parametrize('policy', [
    None, {}, [], True, {'require': []}, {'require': 'external_write'},
    {'require': [None]}, {'require': [{}]}, {'require': ['unknown']},
    {'require': ['external_write', 'external_write']},
    {'require': ['external_write'], 'grants': ['always']},
])
def test_invalid_policy_is_rejected_at_every_static_scope(scope, policy):
    with pytest.raises(TaskError) as caught:
        workflow_from_json(definition(scope, policy))
    assert caught.value.code == 'invalid_workflow'
    assert caught.value.status == 422


@pytest.mark.parametrize('scope', ['workflow', 'node', 'subgraph', 'nested'])
def test_valid_policy_can_be_saved_at_every_static_scope(scope):
    workflow_from_json(definition(scope, {'require': RISKS}))


def test_explicit_human_node_cannot_claim_tool_approval_policy():
    with pytest.raises(TaskError) as caught:
        workflow_from_json({'nodes': [{'id': 'human', 'node_type': 'human',
                                      'tool_approval_policy': POLICY}]})
    assert caught.value.code == 'invalid_workflow'


@pytest.mark.parametrize('scope', ['workflow', 'node', 'subgraph', 'nested'])
def test_policy_survives_task_template_versions_and_import(client, scope):
    login(client)
    workflow = definition(scope)
    created = client.post('/api/hexa/tasks', json={'title': 'Approval policy', 'workflow': workflow})
    assert created.status_code == 201, created.text
    task = created.json()
    assert client.get(f'/api/hexa/tasks/{task["id"]}').json()['workflow'] == workflow
    exported = client.post(f'/api/hexa/tasks/{task["id"]}/save-as-template', json={})
    assert exported.status_code == 201, exported.text
    template = exported.json()
    assert template['latest_version']['workflow'] == workflow
    imported = client.post('/api/hexa/tasks', json={
        'title': 'Imported', 'template_version_id': template['latest_version']['id'],
    })
    assert imported.status_code == 201, imported.text
    assert imported.json()['workflow'] == workflow
    updated = copy.deepcopy(workflow)
    updated['max_concurrency'] = 2
    version = client.post(f'/api/hexa/templates/{template["id"]}/versions', json={
        'expected_revision': 1, 'workflow': updated,
    })
    assert version.status_code == 201, version.text
    assert version.json()['latest_version']['workflow'] == updated
    assert version.json()['versions'][0]['workflow'] == workflow
    assert client.get(f'/api/hexa/tasks/{task["id"]}').json()['workflow'] == workflow


@pytest.mark.parametrize('scope', ['workflow', 'node', 'subgraph', 'nested'])
@pytest.mark.parametrize('remote_claim', [None, False, True])
def test_start_refuses_policy_before_any_run_or_gateway_call(client, app, scope, remote_claim):
    login(client)
    async def discovery():
        return {'capabilities': {'tool_approvals': remote_claim}}
    app.state.gateway.get_uhp_discovery = discovery
    # Also prove no earlier read/model lookup could allocate remote resources.
    async def forbidden(*args, **kwargs):
        pytest.fail('approval-unavailable workflow reached the Gateway')
    app.state.gateway.list_agents = forbidden
    app.state.gateway.create_response = forbidden
    created = client.post('/api/hexa/tasks', json={'workflow': definition(scope)})
    assert created.status_code == 201, created.text
    task_id = created.json()['id']
    refused = client.post(f'/api/hexa/tasks/{task_id}/runs', headers={'Idempotency-Key': 'requires-approval'})
    assert refused.status_code == 422, refused.text
    assert refused.json()['detail']['code'] == 'configuration_unavailable'
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Run)) == 0
        assert db.scalar(select(func.count()).select_from(NodeRun)) == 0
        assert db.scalar(select(func.count()).select_from(RunEvent)) == 0
    assert client.get(f'/api/hexa/tasks/{task_id}').json()['status'] == 'draft'


@pytest.mark.anyio
@pytest.mark.parametrize('scope', ['workflow', 'node', 'subgraph', 'nested'])
async def test_persisted_pending_run_cannot_bypass_creation_gate(app, client, scope):
    run_id = seed_run(app, definition(scope))
    await TaskExecutor(app.state.session_factory, app.state.gateway).execute(run_id)
    assert app.state.gateway.calls == []
    with app.state.session_factory() as db:
        assert db.get(Run, run_id).status == 'failed'
        rows = db.scalars(select(NodeRun).where(NodeRun.run_id == run_id)).all()
        assert all(row.status == 'failed' and row.error_code == 'configuration_unavailable' for row in rows)
        assert db.scalar(select(func.count()).select_from(CommandReceipt)) == 0
        assert any(event.event_type == 'run.failed' and 'configuration_unavailable' in event.event_json
                   for event in db.scalars(select(RunEvent).where(RunEvent.run_id == run_id)).all())


@pytest.mark.anyio
@pytest.mark.parametrize('node_status', ['running', 'failed'])
@pytest.mark.parametrize('effect_state', ['started', 'unknown'])
async def test_existing_inflight_receipt_remains_unknown_when_policy_blocks_scheduling(app, client, node_status, effect_state):
    run_id = seed_run(app, definition('workflow'))
    with app.state.session_factory() as db:
        row = db.scalar(select(NodeRun).where(NodeRun.run_id == run_id, NodeRun.node_id == 'source'))
        row.status = node_status
        row.response_id = 'existing-response'
        db.add(CommandReceipt(node_run_id=row.id, command_id='already-started', request_hash='a' * 64,
                              side_effect_state=effect_state, response_id=row.response_id))
        db.commit()
    await TaskExecutor(app.state.session_factory, app.state.gateway).execute(run_id)
    assert app.state.gateway.calls == []
    with app.state.session_factory() as db:
        receipt = db.scalar(select(CommandReceipt))
        assert receipt.side_effect_state == 'unknown'
        assert receipt.reconciliation_required is True
        assert receipt.response_id == 'existing-response'
        row = db.get(NodeRun, receipt.node_run_id)
        assert row.error_code == 'interrupted_unknown_outcome'


def test_legacy_workflow_without_policy_still_executes(client, app):
    login(client)
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [node('work')]}}).json()
    started = client.post(f'/api/hexa/tasks/{task["id"]}/runs', headers={'Idempotency-Key': 'legacy'})
    assert started.status_code == 202, started.text
    assert wait_run(client, started.json()['id'], {'completed', 'failed'})['status'] == 'completed'
    assert len(app.state.gateway.calls) == 1
