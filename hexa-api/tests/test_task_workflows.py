import time

from app.db.models import NodeRun, Run, WorkflowRevision
from app.tasks.service import is_human_node


def test_human_node_predicate_covers_explicit_and_legacy_gate_configs():
    assert is_human_node({'node_type': 'human'})
    assert is_human_node({'node_type': 'human', 'requires_human': False})
    assert is_human_node({'node_type': 'human_gate'})
    assert is_human_node({'node_type': 'human_gate', 'requires_human': False})
    assert is_human_node({'requires_human': True})
    assert is_human_node({'node_type': 'agent', 'requires_human': True})
    assert not is_human_node({'node_type': 'agent', 'requires_human': False})
    assert not is_human_node({})


def authenticated(client):
    assert client.post('/api/hexa/auth/login', json={'username': 'admin', 'password': 'correct-password'}).status_code == 200


def node(node_id, **kwargs):
    return {'id': node_id, 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'prompt': f'execute {node_id}', **kwargs}


def wait_run(client, run_id, statuses):
    for attempt in range(100):
        result = client.get(f'/api/hexa/runs/{run_id}')
        assert result.status_code == 200
        if result.json()['status'] in statuses:
            return result.json()
        time.sleep(0.01)
    raise AssertionError(result.json())


def test_blank_task_and_invalid_config_are_safe(client):
    authenticated(client)
    blank = client.post('/api/hexa/tasks', json={'title': 'Blank', 'workflow': {'nodes': []}})
    assert blank.status_code == 201
    assert client.post(f"/api/hexa/tasks/{blank.json()['id']}/runs", headers={'Idempotency-Key': 'blank'}).status_code == 422
    task = client.post('/api/hexa/tasks', json={'title': 'Unavailable', 'workflow': {'nodes': [node('a', agent_id='missing')]}}).json()
    response = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'unavailable'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'configuration_unavailable'


def test_complete_five_agents_selection_two_validators_report(client, app):
    authenticated(client)
    collectors = [f'collect-{index}' for index in range(5)]
    nodes = [node(name) for name in collectors] + [
        node('summary', deps=collectors, requires_human=True),
        node('validate-a', deps=['summary'], inputRefs=['summary']),
        node('validate-b', deps=['summary'], inputRefs=['summary']),
        node('report', deps=['summary', 'validate-a', 'validate-b'], inputRefs=['summary', 'validate-a', 'validate-b'], final_report=True),
    ]
    task = client.post('/api/hexa/tasks', json={'title': 'Full flow', 'input': 'Investigate incident', 'workflow': {'nodes': nodes}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'full'})
    assert started.status_code == 202
    run_id = started.json()['id']
    waiting = wait_run(client, run_id, {'waiting_human'})
    assert len([row for row in waiting['nodes'] if row['status'] == 'succeeded']) == 5
    assert client.get(f"/api/hexa/tasks/{task['id']}").json()['status'] == 'waiting'
    invalid = client.post(f'/api/hexa/runs/{run_id}/continue', headers={'Idempotency-Key': 'bad-choice'}, json={'node_id': 'summary', 'input_refs': ['report']})
    assert invalid.status_code == 422
    continued = client.post(f'/api/hexa/runs/{run_id}/continue', headers={'Idempotency-Key': 'choice'}, json={'node_id': 'summary', 'input_refs': collectors[1:3]})
    assert continued.status_code == 200
    completed = wait_run(client, run_id, {'completed'})
    assert len(app.state.gateway.calls) == 9
    assert all(call[3]['agent_id'] == 'agent-1' and call[3]['model'] == 'gpt-6.1' for call in app.state.gateway.calls)
    summary = next(row for row in completed['nodes'] if row['node_id'] == 'summary')
    assert [ref['node_id'] for ref in summary['input']['refs']] == collectors[1:3]
    assert client.get(f"/api/hexa/tasks/{task['id']}").json()['status'] == 'completed'
    assert client.get(f"/api/hexa/tasks/{task['id']}").json()['current_result']['report'] == next(row for row in completed['nodes'] if row['node_id'] == 'report')['id']
    assert client.get(f"/api/hexa/node-runs/{summary['id']}").status_code == 200
    replay = client.post(f'/api/hexa/runs/{run_id}/continue', headers={'Idempotency-Key': 'choice'}, json={'node_id': 'summary', 'input_refs': collectors[1:3]})
    assert replay.status_code == 200
    assert len(app.state.gateway.calls) == 9


def test_template_versions_copy_definitions_and_history_is_immutable(client, app):
    authenticated(client)
    definition = {'nodes': [node('a')]}
    template = client.post('/api/hexa/templates', json={'title': 'Reusable', 'workflow': definition})
    assert template.status_code == 201
    template_id = template.json()['id']
    version_id = template.json()['versions'][0]['id']
    task_response = client.post('/api/hexa/tasks', json={'title': 'Copied', 'template_version_id': version_id})
    assert task_response.status_code == 201
    task = task_response.json()
    assert task['workflow'] == definition
    run_id = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'template-run'}).json()['id']
    wait_run(client, run_id, {'completed'})
    saved = client.put(f"/api/hexa/tasks/{task['id']}/workflow", json={'expected_revision': 1, 'workflow': {'nodes': [node('b')]}})
    assert saved.status_code == 200
    with app.state.session_factory() as db:
        assert db.query(WorkflowRevision).filter_by(task_id=task['id']).count() == 2
        assert db.get(Run, run_id).workflow_revision == 1
    assert client.get(f'/api/hexa/templates/{template_id}').json()['versions'][0]['workflow'] == definition


def test_cancel_fences_late_results_and_locks_active_workflow(client, app):
    import asyncio

    original = app.state.gateway.create_response

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.2)
        return await original(*args, **kwargs)

    app.state.gateway.create_response = slow
    authenticated(client)
    task = client.post('/api/hexa/tasks', json={'title': 'Cancel', 'workflow': {'nodes': [node('a')]}}).json()
    run_id = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'cancel-run'}).json()['id']
    locked = client.put(f"/api/hexa/tasks/{task['id']}/workflow", json={'expected_revision': 1, 'workflow': {'nodes': [node('b')]}})
    assert locked.status_code == 409
    canceled = client.post(f'/api/hexa/runs/{run_id}/cancel', headers={'Idempotency-Key': 'cancel'})
    assert canceled.status_code == 200
    time.sleep(0.3)
    result = client.get(f'/api/hexa/runs/{run_id}').json()
    assert result['status'] == 'canceled'
    assert all(row['status'] == 'canceled' and row['output'] is None for row in result['nodes'])


def test_rerun_adoption_stales_only_actual_consumers(client):
    authenticated(client)
    task = client.post('/api/hexa/tasks', json={'title': 'Rerun', 'workflow': {'nodes': [node('a'), node('b', deps=['a'], inputRefs=['a'])]}}).json()
    first = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'first'}).json()['id']
    completed = wait_run(client, first, {'completed'})
    for row in completed['nodes']:
        assert client.post(f"/api/hexa/tasks/{task['id']}/nodes/{row['node_id']}/adopt", headers={'Idempotency-Key': f"adopt-{row['id']}"}, json={'node_run_id': row['id']}).status_code == 200
    second = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'second'}, json={'kind': 'rerun', 'target_node': 'a'}).json()['id']
    rerun = wait_run(client, second, {'completed'})
    replacement = next(row for row in rerun['nodes'] if row['node_id'] == 'a')
    assert client.post(f"/api/hexa/tasks/{task['id']}/nodes/a/adopt", headers={'Idempotency-Key': 'replace-a'}, json={'node_run_id': replacement['id']}).status_code == 200
    assert client.get(f"/api/hexa/tasks/{task['id']}").json()['stale_nodes'] == ['b']
    assert client.get(f'/api/hexa/runs/{first}').json()['nodes'] == completed['nodes']


def test_terminal_rerun_reexecutes_target_and_downstream_only(client, app):
    authenticated(client)
    task = client.post('/api/hexa/tasks', json={'title': 'Target rerun', 'workflow': {'nodes': [node('a'), node('b'), node('report', deps=['a'], inputRefs=['a'], final_report=True)]}}).json()
    first = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'rerun-first'}).json()['id']
    completed = wait_run(client, first, {'completed'})
    for row in completed['nodes']:
        assert client.post(f"/api/hexa/tasks/{task['id']}/nodes/{row['node_id']}/adopt", headers={'Idempotency-Key': f"rerun-adopt-{row['id']}"}, json={'node_run_id': row['id']}).status_code == 200
    before = len(app.state.gateway.calls)
    second = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'rerun-second'}, json={'kind': 'rerun', 'target_node': 'a'}).json()['id']
    rerun = wait_run(client, second, {'completed'})
    assert len(app.state.gateway.calls) == before + 2
    reused = next(row for row in rerun['nodes'] if row['node_id'] == 'b')
    assert reused['status'] == 'succeeded'
    assert reused['input']['reused_from'] == next(row for row in completed['nodes'] if row['node_id'] == 'b')['id']
