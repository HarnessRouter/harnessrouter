"""Bounded static subgraphs execute in a parent NodeRun scope."""
import asyncio
import json

import pytest

from app.tasks.service import TaskError, workflow_from_json
from tests.test_task_workflows import authenticated, node, wait_run


def subgraph_node(node_id='group', **kwargs):
    return node(node_id, **kwargs, subgraph={
        'max_concurrency': 2,
        'nodes': [
            node('first'),
            node('second'),
        ],
    })


def workflow():
    return {'max_concurrency': 2, 'nodes': [
        node('source'),
        subgraph_node('group', deps=['source'], inputRefs=['source']),
        node('report', deps=['group'], inputRefs=['group'], final_report=True),
    ]}


@pytest.mark.parametrize('subgraph', [
    {'max_concurrency': 2, 'nodes': []},
    {'max_concurrency': 2, 'nodes': [node('a'), node('a')]},
    {'max_concurrency': 2, 'nodes': [node('a', deps=['missing'])]},
    {'max_concurrency': 2, 'nodes': [node('a', deps=['b']), node('b', deps=['a'])]},
    {'max_concurrency': 2, 'nodes': [node('a', subgraph={'nodes': [node('inner')]})]},
    {'max_concurrency': 11, 'nodes': [node('a')]},
])
def test_subgraph_validation_rejects_unbounded_or_recursive_shapes(subgraph):
    value = {'nodes': [node('group', subgraph=subgraph)]}
    with pytest.raises(TaskError) as failure:
        workflow_from_json(value)
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


def test_subgraph_requires_parent_dependency_and_rejects_other_control_modes():
    value = {'nodes': [node('source'), node('group', subgraph={
        'nodes': [node('child')], 'max_concurrency': 1,
    }, repeat={'max_iterations': 1, 'until': {'op': 'exists', 'path': 'done'}})]}
    with pytest.raises(TaskError):
        workflow_from_json(value)


@pytest.mark.parametrize('mode', ['serial', 'parallel'])
def test_subgraph_runs_children_in_scope_and_aggregates_before_downstream(client, app, mode):
    authenticated(client)
    definition = workflow()
    definition['nodes'][1]['subgraph']['max_concurrency'] = 2 if mode == 'parallel' else 1
    calls, active, peak = [], set(), 0

    async def gateway(text, previous, key, **kwargs):
        nonlocal peak
        context = json.loads(text)
        prompt = context['prompt']
        calls.append(context)
        if prompt == 'execute source':
            return {'status': 'completed', 'items': [{'value': 1}]}
        if prompt == 'execute report':
            assert context['refs'][0]['node_id'] == 'group'
            assert context['refs'][0]['output']['status'] == 'completed'
            return {'status': 'completed', 'report': 'ok'}
        active.add(context['subgraph_node_id'])
        peak = max(peak, len(active))
        await asyncio.sleep(0.02)
        active.remove(context['subgraph_node_id'])
        return {'status': 'completed', 'child': context['subgraph_node_id']}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': definition}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': f'subgraph-{mode}'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result
    child_calls = [call for call in calls if call.get('_orchestration_role') == 'subgraph_node']
    assert sorted(call['subgraph_node_id'] for call in child_calls) == ['first', 'second']
    assert peak == (1 if mode == 'serial' else 2)
    group = next(row for row in result['nodes'] if row['node_id'] == 'group')
    assert group['output']['status'] == 'completed'
    assert [item['id'] for item in group['output']['nodes']] == ['first', 'second']
    assert calls[-1]['prompt'] == 'execute report'


def test_subgraph_failure_blocks_downstream_and_keeps_child_history(client, app):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'items': []}
        if context.get('_orchestration_role') == 'subgraph_node' and context['subgraph_node_id'] == 'first':
            return {'status': 'failed'}
        pytest.fail('downstream or sibling child was dispatched after failure')

    app.state.gateway.create_response = gateway
    definition = workflow()
    definition['nodes'][1]['subgraph']['max_concurrency'] = 1
    task = client.post('/api/hexa/tasks', json={'workflow': definition}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'subgraph-fail'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'failed', result
    group = next(row for row in result['nodes'] if row['node_id'] == 'group')
    assert group['error_code'] == 'subgraph_child_failed'
    assert client.get(f"/api/hexa/node-runs/{group['id']}/items").status_code == 200
    assert next(row for row in result['nodes'] if row['node_id'] == 'report')['status'] == 'idle'
    assert [call.get('subgraph_node_id') for call in calls if call.get('_orchestration_role') == 'subgraph_node'] == ['first']


def test_terminal_subgraph_resume_reuses_success_and_retries_failed_child(client, app):
    authenticated(client)
    calls = []
    second_attempt = {'value': 0}

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'items': []}
        if context.get('_orchestration_role') == 'subgraph_node':
            if context['subgraph_node_id'] == 'first':
                return {'status': 'completed', 'child': 'first'}
            second_attempt['value'] += 1
            if second_attempt['value'] == 1:
                return {'status': 'failed'}
            return {'status': 'completed', 'child': 'second'}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'report': 'ok'}
        pytest.fail('unexpected subgraph call')

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': workflow()}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'subgraph-resume-first'}).json()
    failed = wait_run(client, started['id'], {'failed'})
    group = next(row for row in failed['nodes'] if row['node_id'] == 'group')
    children = client.get(f"/api/hexa/node-runs/{group['id']}/items").json()['items']
    failed_child = next(row for row in children if row['status'] == 'failed')
    resumed = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
        'kind': 'rerun', 'target_node': 'group', 'resume_from_run_id': failed['id'],
        'item_node_run_id': failed_child['id'],
    }, headers={'Idempotency-Key': 'subgraph-resume-second'})
    assert resumed.status_code == 202, resumed.json()
    completed = wait_run(client, resumed.json()['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed
    assert [context.get('subgraph_node_id') for context in calls
            if context.get('_orchestration_role') == 'subgraph_node'] == ['first', 'second', 'second']
    resumed_child = next(row for row in completed['nodes'] if row['node_id'] == 'group')
    resumed_items = client.get(f"/api/hexa/node-runs/{resumed_child['id']}/items").json()['items']
    assert all(ref['run_id'] == completed['id'] for item in resumed_items for ref in item['input'].get('parent_refs', []))
    assert client.get(f"/api/hexa/runs/{failed['id']}").json() == failed


def test_subgraph_pause_does_not_dispatch_next_child_until_continue(client, app):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'items': []}
        if context.get('_orchestration_role') == 'subgraph_node':
            await asyncio.sleep(0.08)
            return {'status': 'completed', 'child': context['subgraph_node_id']}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'report': 'ok'}
        pytest.fail('unexpected subgraph call')

    app.state.gateway.create_response = gateway
    definition = workflow()
    definition['nodes'][1]['subgraph']['max_concurrency'] = 1
    task = client.post('/api/hexa/tasks', json={'workflow': definition}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'subgraph-pause'}).json()
    for _ in range(50):
        if any(call.get('_orchestration_role') == 'subgraph_node' for call in calls):
            break
        import time
        time.sleep(0.01)
    paused = client.post(f"/api/hexa/runs/{started['id']}/pause", headers={'Idempotency-Key': 'subgraph-pause-action'})
    assert paused.status_code == 200
    import time
    time.sleep(0.12)
    assert [call.get('subgraph_node_id') for call in calls if call.get('_orchestration_role') == 'subgraph_node'] == ['first']
    continued = client.post(f"/api/hexa/runs/{started['id']}/continue", headers={'Idempotency-Key': 'subgraph-continue'})
    assert continued.status_code == 200
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result
    assert [call.get('subgraph_node_id') for call in calls if call.get('_orchestration_role') == 'subgraph_node'] == ['first', 'second']
