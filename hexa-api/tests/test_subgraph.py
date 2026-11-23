"""Bounded static subgraphs execute in a parent NodeRun scope."""
import asyncio
import json

import pytest

from app.tasks.service import TaskError, workflow_from_json
from app.db.models import NodeRun
from tests.test_task_workflows import authenticated, node, wait_run


def subgraph_node(node_id='group', **kwargs):
    return node(node_id, **kwargs, subgraph={
        'max_concurrency': 2,
        'nodes': [
            node('first'),
            node('second'),
        ],
    })


def dynamic_subgraph_node(node_id='group', **kwargs):
    return node(node_id, **kwargs, subgraph={
        'max_concurrency': 2,
        'dynamic': {
            'source': 'planner',
            'path': 'nodes',
            'max_nodes': 10,
            'mode': 'parallel',
        },
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
    {'max_concurrency': 2, 'nodes': [node('a', subgraph={'nodes': [node('inner', subgraph={'nodes': [node('mid', subgraph={'nodes': [node('leaf')]})]})]})]},
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


@pytest.mark.parametrize('dynamic', [
    {'source': 'missing', 'path': 'nodes', 'max_nodes': 2},
    {'source': 'source', 'path': '../nodes', 'max_nodes': 2},
    {'source': 'source', 'path': 'nodes', 'max_nodes': 11},
    {'source': 'source', 'path': 'nodes', 'max_nodes': 2, 'extra': True},
])
def test_dynamic_subgraph_validation_rejects_unsafe_shapes(dynamic):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [node('source'), node('group', deps=['source'], subgraph={
            'max_concurrency': 1, 'dynamic': dynamic,
        })]})
    assert failure.value.code == 'invalid_workflow'


def test_dynamic_subgraph_requires_exactly_one_static_or_dynamic_definition():
    for subgraph in [
        {'max_concurrency': 1},
        {'max_concurrency': 1, 'nodes': [node('child')], 'dynamic': {'source': 'source', 'path': 'nodes', 'max_nodes': 2}},
    ]:
        with pytest.raises(TaskError):
            workflow_from_json({'nodes': [node('source'), node('group', deps=['source'], subgraph=subgraph)]})


def test_dynamic_subgraph_runs_frozen_local_dag_and_inherits_parent_execution(client, app):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'nodes': [
                {'id': 'first', 'prompt': 'draft'},
                {'id': 'second', 'prompt': 'review', 'deps': ['first'], 'inputRefs': ['first']},
            ]}
        if context.get('_orchestration_role') == 'subgraph_node':
            assert context['subgraph_node_id'] in {'first', 'second'}
            assert context['prompt'].endswith('\ndraft') or context['prompt'].endswith('\nreview')
            if context['subgraph_node_id'] == 'second':
                assert context['inputRefs'] == ['first']
                assert any(ref['id'] == 'first' and ref['output']['child'] == 'first' for ref in context['refs'])
            return {'status': 'completed', 'child': context['subgraph_node_id']}
        if context['prompt'] == 'execute report':
            assert context['refs'][0]['output']['status'] == 'completed'
            return {'status': 'completed', 'report': 'ok'}
        pytest.fail(f'unexpected prompt: {context}')

    app.state.gateway.create_response = gateway
    definition = {'max_concurrency': 2, 'nodes': [
        node('planner'),
        dynamic_subgraph_node('group', deps=['planner'], inputRefs=['planner']),
        node('report', deps=['group'], inputRefs=['group'], final_report=True),
    ]}
    created = client.post('/api/hexa/tasks', json={'workflow': definition})
    assert created.status_code == 201, created.text
    task = created.json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'dynamic-subgraph'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result
    child_calls = [call for call in calls if call.get('_orchestration_role') == 'subgraph_node']
    assert [call['subgraph_node_id'] for call in child_calls] == ['first', 'second']
    group = next(row for row in result['nodes'] if row['node_id'] == 'group')
    assert group['output']['status'] == 'completed'


def test_dynamic_subgraph_invalid_output_fails_before_child_dispatch(client, app):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'nodes': [{'id': 'bad', 'prompt': 'x', 'model': 'do-not-accept'}]}
        pytest.fail('dynamic child was dispatched before full validation')

    app.state.gateway.create_response = gateway
    definition = {'nodes': [
        node('planner'),
        dynamic_subgraph_node('group', deps=['planner'], inputRefs=['planner']),
    ]}
    created = client.post('/api/hexa/tasks', json={'workflow': definition})
    assert created.status_code == 201, created.text
    task = created.json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'dynamic-subgraph-invalid'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'failed', result
    group = next(row for row in result['nodes'] if row['node_id'] == 'group')
    assert group['error_code'] == 'subgraph_dynamic_invalid'
    assert not any(call.get('_orchestration_role') == 'subgraph_node' for call in calls)


def test_dynamic_subgraph_terminal_resume_reuses_success_and_retries_failed_child(client, app):
    authenticated(client)
    calls = []
    attempts = {'second': 0}

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'nodes': [
                {'id': 'first', 'prompt': 'draft'},
                {'id': 'second', 'prompt': 'review', 'deps': ['first'], 'inputRefs': ['first']},
            ]}
        if context.get('_orchestration_role') == 'subgraph_node':
            if context['subgraph_node_id'] == 'second':
                attempts['second'] += 1
                if attempts['second'] == 1:
                    return {'status': 'failed'}
            return {'status': 'completed', 'child': context['subgraph_node_id']}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'report': 'ok'}
        pytest.fail(f'unexpected prompt: {context}')

    app.state.gateway.create_response = gateway
    definition = {'nodes': [
        node('planner'),
        dynamic_subgraph_node('group', deps=['planner'], inputRefs=['planner']),
        node('report', deps=['group'], inputRefs=['group'], final_report=True),
    ]}
    created = client.post('/api/hexa/tasks', json={'workflow': definition})
    assert created.status_code == 201, created.text
    task = created.json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'dynamic-resume-first'}).json()
    failed = wait_run(client, started['id'], {'failed'})
    group = next(row for row in failed['nodes'] if row['node_id'] == 'group')
    failed_child = next(row for row in client.get(f"/api/hexa/node-runs/{group['id']}/items").json()['items'] if row['status'] == 'failed')
    resumed = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
        'kind': 'rerun', 'target_node': 'group', 'resume_from_run_id': failed['id'],
        'item_node_run_id': failed_child['id'],
    }, headers={'Idempotency-Key': 'dynamic-resume-second'})
    assert resumed.status_code == 202, resumed.text
    completed = wait_run(client, resumed.json()['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed
    assert [context['subgraph_node_id'] for context in calls if context.get('_orchestration_role') == 'subgraph_node'] == ['first', 'second', 'second']
    assert client.get(f"/api/hexa/runs/{failed['id']}").json() == failed


def test_dynamic_subgraph_empty_plan_aggregates_successfully(client, app):
    authenticated(client)

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'nodes': []}
        if context['prompt'] == 'execute report':
            assert context['refs'][0]['output']['nodes'] == []
            return {'status': 'completed', 'report': 'empty'}
        pytest.fail(f'unexpected prompt: {context}')

    app.state.gateway.create_response = gateway
    definition = {'nodes': [
        node('planner'),
        dynamic_subgraph_node('group', deps=['planner'], inputRefs=['planner']),
        node('report', deps=['group'], inputRefs=['group'], final_report=True),
    ]}
    created = client.post('/api/hexa/tasks', json={'workflow': definition})
    assert created.status_code == 201, created.text
    task = created.json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'dynamic-empty'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result


def test_nested_static_subgraph_runs_in_one_parent_run_and_releases_downstream(client, app):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'value': 'source'}
        if context.get('_orchestration_role') == 'subgraph_node':
            assert context['subgraph_node_id'] == 'leaf'
            assert context['prompt'].endswith('\nleaf work')
            return {'status': 'completed', 'child': 'leaf'}
        if context['prompt'] == 'execute report':
            assert context['refs'][0]['output']['status'] == 'completed'
            return {'status': 'completed', 'report': 'nested'}
        pytest.fail(f'unexpected prompt: {context}')

    app.state.gateway.create_response = gateway
    nested = {
        'max_concurrency': 1,
        'nodes': [{
            'id': 'outer', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'prompt': 'outer control',
            'subgraph': {'max_concurrency': 1, 'nodes': [
                {'id': 'leaf', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'prompt': 'leaf work'},
            ]},
        }],
    }
    definition = {'nodes': [
        node('source'),
        node('group', deps=['source'], inputRefs=['source'], subgraph=nested),
        node('report', deps=['group'], inputRefs=['group'], final_report=True),
    ]}
    created = client.post('/api/hexa/tasks', json={'workflow': definition})
    assert created.status_code == 201, created.text
    task = created.json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'nested-subgraph'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result
    assert [call['subgraph_node_id'] for call in calls if call.get('_orchestration_role') == 'subgraph_node'] == ['leaf']
    group = next(row for row in result['nodes'] if row['node_id'] == 'group')
    items = client.get(f"/api/hexa/node-runs/{group['id']}/items").json()['items']
    assert {item['input'].get('subgraph_node_id') for item in items if item['execution_kind'] == 'subgraph_node'} == {'outer', 'leaf'}
    assert next(item for item in items if item['input'].get('subgraph_node_id') == 'leaf')['input']['subgraph_parent_node_run_id'] == next(item for item in items if item['input'].get('subgraph_node_id') == 'outer')['id']


def test_nested_static_subgraph_resume_reuses_outer_and_retries_failed_leaf(client, app):
    authenticated(client)
    calls = []
    attempts = {'leaf': 0}

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'value': 'source'}
        if context.get('_orchestration_role') == 'subgraph_node':
            attempts['leaf'] += 1
            if attempts['leaf'] == 1:
                return {'status': 'failed'}
            return {'status': 'completed', 'child': 'leaf'}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'report': 'nested-resumed'}
        pytest.fail(f'unexpected prompt: {context}')

    app.state.gateway.create_response = gateway
    definition = {'nodes': [
        node('source'),
        node('group', deps=['source'], inputRefs=['source'], subgraph={
            'max_concurrency': 1,
            'nodes': [{
                'id': 'outer', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'prompt': 'outer control',
                'subgraph': {'max_concurrency': 1, 'nodes': [
                    {'id': 'leaf', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'prompt': 'leaf work'},
                ]},
            }],
        }),
        node('report', deps=['group'], inputRefs=['group'], final_report=True),
    ]}
    task = client.post('/api/hexa/tasks', json={'workflow': definition}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'nested-resume-first'}).json()
    failed = wait_run(client, started['id'], {'failed'})
    group = next(row for row in failed['nodes'] if row['node_id'] == 'group')
    items = client.get(f"/api/hexa/node-runs/{group['id']}/items").json()['items']
    leaf = next(item for item in items if item['input'].get('subgraph_node_id') == 'leaf')
    resumed = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
        'kind': 'rerun', 'target_node': 'group', 'resume_from_run_id': failed['id'],
        'item_node_run_id': leaf['id'],
    }, headers={'Idempotency-Key': 'nested-resume-second'})
    assert resumed.status_code == 202, resumed.text
    completed = wait_run(client, resumed.json()['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed
    assert attempts['leaf'] == 2
    assert client.get(f"/api/hexa/runs/{failed['id']}").json() == failed
    new_group = next(row for row in completed['nodes'] if row['node_id'] == 'group')
    items_response = client.get(f"/api/hexa/node-runs/{new_group['id']}/items")
    assert items_response.status_code == 200, items_response.text
    new_items = items_response.json()['items']
    assert {item['input'].get('subgraph_node_id') for item in new_items if item['execution_kind'] == 'subgraph_node'} == {'outer', 'leaf'}
    assert all(item['run_id'] == completed['id'] for item in new_items)


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


def test_active_subgraph_retry_appends_failed_child_attempt_and_preserves_success(client, app):
    authenticated(client)
    calls = []
    attempts = {'second': 0}

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'items': []}
        if context.get('_orchestration_role') == 'subgraph_node':
            if context['subgraph_node_id'] == 'second':
                attempts['second'] += 1
                if attempts['second'] == 1:
                    return {'status': 'failed'}
            return {'status': 'completed', 'child': context['subgraph_node_id']}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'report': 'ok'}
        pytest.fail(f'unexpected prompt: {context}')

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': workflow()}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'subgraph-active-retry'}).json()
    failed = wait_run(client, started['id'], {'failed'})
    group = next(row for row in failed['nodes'] if row['node_id'] == 'group')
    items = client.get(f"/api/hexa/node-runs/{group['id']}/items").json()['items']
    failed_child = next(row for row in items if row['status'] == 'failed')
    from app.db.models import Run
    with app.state.session_factory() as db:
        db.get(Run, started['id']).status = 'running'
        db.commit()
    retried = client.post(
        f"/api/hexa/runs/{started['id']}/nodes/group/retry",
        json={'item_node_run_id': failed_child['id']},
        headers={'Idempotency-Key': 'subgraph-active-retry-action'},
    )
    assert retried.status_code == 200, retried.text
    completed = wait_run(client, started['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed
    assert [call.get('subgraph_node_id') for call in calls if call.get('_orchestration_role') == 'subgraph_node'] == ['first', 'second', 'second']
    with app.state.session_factory() as db:
        rows = db.query(NodeRun).filter_by(run_id=started['id'], node_id='group', execution_kind='subgraph_node').order_by(NodeRun.id).all()
        assert [row.status for row in rows] == ['succeeded', 'failed', 'succeeded']
