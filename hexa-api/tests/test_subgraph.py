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
