import time
import json

import pytest
from app.db.models import NodeRun, Run, WorkflowRevision
from app.tasks.service import TaskError, is_human_node, workflow_from_json


def test_human_node_predicate_covers_explicit_and_legacy_gate_configs():
    assert is_human_node({'node_type': 'human'})
    assert is_human_node({'node_type': 'human', 'requires_human': False})
    assert is_human_node({'node_type': 'human_gate'})
    assert is_human_node({'node_type': 'human_gate', 'requires_human': False})
    assert is_human_node({'requires_human': True})
    assert is_human_node({'node_type': 'agent', 'requires_human': True})
    assert not is_human_node({'node_type': 'agent', 'requires_human': False})
    assert not is_human_node({})


@pytest.mark.parametrize('condition', [
    {'source': 'missing', 'path': 'route', 'op': 'eq', 'value': 'fast'},
    {'source': 'gate', 'path': 'route', 'op': 'contains', 'value': 'fast'},
    {'source': 'gate', 'path': 'route', 'op': 'eq'},
    {'source': 'gate', 'path': '../route', 'op': 'eq', 'value': 'fast'},
    'gate.route == "fast"',
])
def test_workflow_rejects_invalid_declarative_condition(condition):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [
            {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
            {'id': 'fast', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'], 'condition': condition},
        ]})
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


def test_workflow_accepts_condition_only_when_source_is_a_dependency():
    workflow_from_json({'nodes': [
        {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
        {'id': 'fast', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'],
         'condition': {'source': 'gate', 'path': 'route', 'op': 'eq', 'value': 'fast'}},
    ]})


@pytest.mark.parametrize('repeat', [
    {'max_iterations': 0, 'until': {'path': 'done', 'op': 'eq', 'value': True}},
    {'max_iterations': 11, 'until': {'path': 'done', 'op': 'eq', 'value': True}},
    {'max_iterations': True, 'until': {'path': 'done', 'op': 'eq', 'value': True}},
    {'max_iterations': 2, 'until': {'path': '../done', 'op': 'eq', 'value': True}},
    {'max_iterations': 2, 'until': {'path': 'done', 'op': 'contains', 'value': True}},
    {'max_iterations': 2, 'until': {'path': 'done', 'op': 'eq'}},
])
def test_workflow_rejects_invalid_bounded_repeat(repeat):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [
            {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'repeat': repeat},
        ]})
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


def test_workflow_accepts_bounded_repeat():
    workflow_from_json({'nodes': [
        {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1',
         'repeat': {'max_iterations': 2, 'until': {'path': 'done', 'op': 'eq', 'value': True}}},
    ]})


@pytest.mark.parametrize('foreach', [
    {'source': 'missing', 'path': 'items', 'max_items': 2},
    {'source': 'gate', 'path': '../items', 'max_items': 2},
    {'source': 'gate', 'path': 'items', 'max_items': 0},
    {'source': 'gate', 'path': 'items', 'max_items': 11},
    {'source': 'gate', 'path': 'items', 'max_items': True},
    {'source': 'gate', 'path': 'items'},
    {'source': 'gate', 'path': 'items', 'max_items': 2, 'mode': 'unknown'},
])
def test_workflow_rejects_invalid_bounded_foreach(foreach):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [
            {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
            {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'], 'foreach': foreach},
        ]})
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


def test_workflow_accepts_bounded_foreach_only_from_a_dependency():
    workflow_from_json({'nodes': [
        {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
        {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'],
         'foreach': {'source': 'gate', 'path': 'items', 'max_items': 10}},
    ]})


@pytest.mark.parametrize('nested', [
    {'path': '../items', 'max_items': 2},
    {'path': 'items', 'max_items': 0},
    {'path': 'items', 'max_items': 11},
    {'path': 'items', 'max_items': True},
    {'path': 'items', 'max_items': 2, 'mode': 'unknown'},
    {'path': 'items', 'max_items': 2, 'nested': {'path': 'again', 'max_items': 1}},
])
def test_workflow_rejects_invalid_nested_foreach(nested):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [
            {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
            {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'],
             'foreach': {'source': 'gate', 'path': 'groups', 'max_items': 2, 'nested': nested}},
        ]})
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


def test_workflow_accepts_bounded_two_level_foreach():
    workflow_from_json({'nodes': [
        {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
        {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'],
         'foreach': {'source': 'gate', 'path': 'groups', 'max_items': 2,
                     'mode': 'parallel', 'nested': {'path': 'items', 'max_items': 3, 'mode': 'serial'}}},
    ]})


@pytest.mark.parametrize('plan', [
    {'source': 'missing', 'path': 'items', 'max_items': 2},
    {'source': 'gate', 'path': '../items', 'max_items': 2},
    {'source': 'gate', 'path': 'items', 'max_items': 0},
    {'source': 'gate', 'path': 'items', 'max_items': 11},
    {'source': 'gate', 'path': 'items', 'max_items': 2, 'mode': 'unknown'},
])
def test_workflow_rejects_invalid_dynamic_plan(plan):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [
            {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
            {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'], 'dynamic_plan': plan},
        ]})
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


def test_workflow_accepts_restricted_dynamic_plan():
    workflow_from_json({'nodes': [
        {'id': 'gate', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
        {'id': 'worker', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['gate'],
         'dynamic_plan': {'source': 'gate', 'path': 'items', 'max_items': 10, 'mode': 'parallel'}},
    ]})


@pytest.mark.parametrize('loop', [
    {'body': ['a'], 'max_iterations': 0, 'until': {'source': 'a', 'path': 'done', 'op': 'eq', 'value': True}},
    {'body': ['missing'], 'max_iterations': 2, 'until': {'source': 'a', 'path': 'done', 'op': 'eq', 'value': True}},
    {'body': ['a'], 'max_iterations': 2, 'until': {'source': 'missing', 'path': 'done', 'op': 'eq', 'value': True}},
    {'body': ['a'], 'max_iterations': 2, 'until': {'source': 'a', 'path': '../done', 'op': 'eq', 'value': True}},
])
def test_workflow_rejects_invalid_bounded_cross_node_loop(loop):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [
            {'id': 'a', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'loop': loop},
        ]})
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


def test_workflow_accepts_bounded_cross_node_loop():
    workflow_from_json({'nodes': [
        {'id': 'a', 'agent_id': 'agent-1', 'model': 'gpt-6.1'},
        {'id': 'check', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'deps': ['a'], 'loop': {
            'body': ['a', 'check'], 'max_iterations': 3,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }},
    ]})


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


def test_condition_skips_one_branch_and_join_waits_for_selected_branch(client, app):
    authenticated(client)

    original = app.state.gateway.create_response

    async def routed(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute gate':
            app.state.gateway.calls.append((text, previous, key, kwargs))
            return {'status': 'completed', 'text': 'gate', 'route': 'fast'}
        return await original(text, previous, key, **kwargs)

    app.state.gateway.create_response = routed
    definition = {
        'nodes': [
            node('gate'),
            node('fast', deps=['gate'], inputRefs=['gate'], condition={'source': 'gate', 'path': 'route', 'op': 'eq', 'value': 'fast'}),
            node('slow', deps=['gate'], inputRefs=['gate'], condition={'source': 'gate', 'path': 'route', 'op': 'eq', 'value': 'slow'}),
            node('report', deps=['fast', 'slow'], inputRefs=['fast', 'slow'], allow_missing_inputs=True, final_report=True),
        ],
    }
    task = client.post('/api/hexa/tasks', json={'title': 'Conditional route', 'workflow': definition}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'condition-run'})
    assert started.status_code == 202
    completed = wait_run(client, started.json()['id'], {'completed'})
    rows = {row['node_id']: row for row in completed['nodes']}
    assert rows['gate']['status'] == 'succeeded'
    assert rows['fast']['status'] == 'succeeded'
    assert rows['slow']['status'] == 'skipped'
    assert rows['slow']['error_code'] == 'condition_not_matched'
    assert rows['report']['status'] == 'succeeded'
    assert [ref['node_id'] for ref in rows['report']['input']['refs']] == ['fast']
    assert [json.loads(call[0])['prompt'] for call in app.state.gateway.calls] == ['execute gate', 'execute fast', 'execute report']


def test_bounded_repeat_appends_attempts_until_output_matches(client, app):
    authenticated(client)
    calls = 0

    async def repeated(text, previous, key, **kwargs):
        nonlocal calls
        calls += 1
        return {'status': 'completed', 'done': calls >= 2, 'iteration': calls}

    app.state.gateway.create_response = repeated
    task = client.post('/api/hexa/tasks', json={'title': 'Bounded repeat', 'workflow': {'nodes': [
        node('worker', repeat={'max_iterations': 3, 'until': {'path': 'done', 'op': 'eq', 'value': True}}, final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'repeat-run'})
    completed = wait_run(client, started.json()['id'], {'completed'})
    worker = next(row for row in completed['nodes'] if row['node_id'] == 'worker')
    assert worker['status'] == 'succeeded'
    assert worker['attempt'] == 2
    assert worker['output']['iteration'] == 2
    assert calls == 2
    attempts = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    assert [row['attempt'] for row in attempts] == [1, 2]


def test_bounded_cross_node_loop_reexecutes_the_static_body_until_check_matches(client, app):
    authenticated(client)
    calls = []

    async def looping_gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context['prompt'])
        if context['prompt'] == 'execute check':
            return {'status': 'completed', 'done': calls.count('execute check') >= 2}
        return {'status': 'completed', 'value': calls.count('execute work')}

    app.state.gateway.create_response = looping_gateway
    task = client.post('/api/hexa/tasks', json={'title': 'Cross node loop', 'workflow': {'nodes': [
        node('work'),
        node('check', deps=['work'], inputRefs=['work'], loop={
            'body': ['work', 'check'], 'max_iterations': 3,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }, final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'cross-loop'})
    completed = wait_run(client, started.json()['id'], {'completed'})
    assert calls == ['execute work', 'execute check', 'execute work', 'execute check']
    check = next(row for row in completed['nodes'] if row['node_id'] == 'check')
    assert check['status'] == 'succeeded'
    assert check['iteration'] == 2
    assert check['attempt'] == 1
    attempts = client.get(f"/api/hexa/node-runs/{check['id']}").json()['attempts']
    assert [row['iteration'] for row in attempts] == [1, 2]
    assert [row['attempt'] for row in attempts] == [1, 1]


def test_bounded_cross_node_loop_fails_at_limit_without_an_extra_body_dispatch(client, app):
    authenticated(client)
    calls = []

    async def never_done(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context['prompt'])
        return {'status': 'completed', 'done': False}

    app.state.gateway.create_response = never_done
    task = client.post('/api/hexa/tasks', json={'title': 'Loop limit', 'workflow': {'nodes': [
        node('work'),
        node('check', deps=['work'], inputRefs=['work'], loop={
            'body': ['work', 'check'], 'max_iterations': 2,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }, final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'cross-loop-limit'})
    failed = wait_run(client, started.json()['id'], {'failed'})
    check = next(row for row in failed['nodes'] if row['node_id'] == 'check')
    assert check['error_code'] == 'loop_limit_exceeded'
    assert calls == ['execute work', 'execute check', 'execute work', 'execute check']


@pytest.mark.parametrize('kind,mode', [('foreach', 'serial'), ('foreach', 'parallel'), ('dynamic_plan', 'serial'), ('dynamic_plan', 'parallel')])
def test_bounded_loop_reexpands_foreach_body_each_iteration(client, app, kind, mode):
    authenticated(client)
    calls = []

    async def loop_foreach_gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute gate':
            return {'status': 'completed', 'items': ['a', 'b'] if kind == 'foreach' else [
                {'id': 'a', 'prompt': 'first'}, {'id': 'b', 'prompt': 'second'},
            ]}
        if context['prompt'] == 'execute check':
            return {'status': 'completed', 'done': sum(item.get('prompt') == 'execute check' for item in calls) >= 2}
        return {'status': 'completed', 'item': context[f'{kind if kind == "foreach" else "dynamic"}_item']}

    app.state.gateway.create_response = loop_foreach_gateway
    task = client.post('/api/hexa/tasks', json={'title': 'Loop foreach body', 'workflow': {'nodes': [
        node('gate'),
        node('work', deps=['gate'], inputRefs=['gate'], **{kind: {
            'source': 'gate', 'path': 'items', 'max_items': 2, 'mode': mode,
        }}),
        node('check', deps=['work'], inputRefs=['work'], loop={
            'body': ['work', 'check'], 'max_iterations': 3,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }, final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'loop-foreach-body'})
    completed = wait_run(client, started.json()['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed['nodes']
    assert [call['prompt'].splitlines()[0] for call in calls] == [
        'execute gate', 'execute work', 'execute work', 'execute check',
        'execute work', 'execute work', 'execute check',
    ]
    work = next(row for row in completed['nodes'] if row['node_id'] == 'work')
    attempts = client.get(f"/api/hexa/node-runs/{work['id']}").json()['attempts']
    prefix = 'foreach' if kind == 'foreach' else 'dynamic'
    assert sorted({row['iteration'] for row in attempts if row['execution_kind'] == f'{prefix}_item'}) == [1, 2]
    assert len([row for row in attempts if row['execution_kind'] == f'{prefix}_aggregate']) == 2
    previous = calls[4]['loop_previous']
    assert previous['iteration'] == 1
    assert [(ref['node_id'], ref['output']) for ref in previous['refs']] == [
        ('work', next(row['output'] for row in attempts if row['execution_kind'] == f'{prefix}_aggregate' and row['iteration'] == 1)),
        ('check', {'status': 'completed', 'done': False}),
    ]


@pytest.mark.parametrize('mode', ['serial', 'parallel'])
def test_chained_foreach_waits_for_upstream_aggregate(client, app, mode):
    authenticated(client)
    calls = []

    async def chained_gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'values': ['a', 'b']}
        return {'status': 'completed', 'value': context['foreach_item']}

    app.state.gateway.create_response = chained_gateway
    created = client.post('/api/hexa/tasks', json={'title': 'Chained foreach', 'workflow': {'nodes': [
        node('source'),
        node('outer', deps=['source'], inputRefs=['source'], foreach={
            'source': 'source', 'path': 'values', 'max_items': 2, 'mode': mode,
        }),
        node('inner', deps=['outer'], inputRefs=['outer'], foreach={
            'source': 'outer', 'path': 'items', 'max_items': 2, 'mode': mode,
        }, final_report=True),
    ]}})
    assert created.status_code == 201
    task = created.json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'chained-foreach'})
    completed = wait_run(client, started.json()['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed['nodes']
    outer = next(row for row in completed['nodes'] if row['node_id'] == 'outer')
    inner = next(row for row in completed['nodes'] if row['node_id'] == 'inner')
    assert outer['output']['items'] == [
        {'status': 'completed', 'value': 'a'},
        {'status': 'completed', 'value': 'b'},
    ]
    assert [item['value'] for item in inner['output']['items']] == outer['output']['items']
    inner_calls = [call for call in calls if call['prompt'] == 'execute inner']
    assert len(inner_calls) == 2
    assert all(call['refs'][0]['node_run_id'] == outer['id'] for call in inner_calls)


def test_two_level_foreach_persists_outer_and_nested_manifests(client, app):
    authenticated(client)
    calls = []

    async def nested_gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'groups': [
                {'name': 'one', 'items': ['a', 'b']},
                {'name': 'two', 'items': ['c']},
            ]}
        return {'status': 'completed', 'value': context['foreach_item']}

    app.state.gateway.create_response = nested_gateway
    task = client.post('/api/hexa/tasks', json={'title': 'Nested foreach', 'workflow': {'nodes': [
        node('source'),
        node('worker', deps=['source'], inputRefs=['source'], foreach={
            'source': 'source', 'path': 'groups', 'max_items': 2, 'mode': 'parallel',
            'nested': {'path': 'items', 'max_items': 2, 'mode': 'parallel'},
        }, final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'nested-foreach'})
    completed = wait_run(client, started.json()['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed
    worker = next(row for row in completed['nodes'] if row['node_id'] == 'worker')
    assert worker['output']['items'] == [
        {'items': [{'status': 'completed', 'value': 'a'}, {'status': 'completed', 'value': 'b'}]},
        {'items': [{'status': 'completed', 'value': 'c'}]},
    ]
    history = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    assert len([row for row in history if row['execution_kind'] == 'foreach_item']) == 2
    assert len([row for row in history if row['execution_kind'] == 'foreach_nested_item']) == 3
    assert len([row for row in history if row['execution_kind'] == 'foreach_nested_aggregate']) == 2
    assert [call['foreach_item'] for call in calls if call['prompt'] == 'execute worker'] == ['a', 'b', 'c']


def test_parallel_foreach_failure_cancels_unstarted_siblings_and_preserves_completed_items(client, app):
    authenticated(client)
    import asyncio
    calls = []

    async def failing_parallel_gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute gate':
            return {'status': 'completed', 'items': ['ok', 'bad', 'late']}
        if context['foreach_item'] == 'bad':
            raise RuntimeError('unknown side effect')
        await asyncio.sleep(0.05)
        return {'status': 'completed', 'item': context['foreach_item']}

    app.state.gateway.create_response = failing_parallel_gateway
    task = client.post('/api/hexa/tasks', json={'title': 'Parallel failure', 'workflow': {
        'max_concurrency': 2,
        'nodes': [node('gate'), node('worker', deps=['gate'], inputRefs=['gate'], foreach={
            'source': 'gate', 'path': 'items', 'max_items': 3, 'mode': 'parallel',
        }, final_report=True)],
    }}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'parallel-failure'})
    failed = wait_run(client, started.json()['id'], {'failed'})
    worker = next(row for row in failed['nodes'] if row['node_id'] == 'worker')
    attempts = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    item_attempts = {row['input'].get('foreach_index'): row for row in attempts if row['input'].get('_orchestration_role') == 'foreach_item'}
    assert item_attempts[0]['status'] == 'succeeded'
    assert item_attempts[1]['error_code'] == 'interrupted_unknown_outcome'
    assert item_attempts[2]['status'] == 'canceled'
    assert worker['error_code'] == 'interrupted_unknown_outcome'


def test_restricted_dynamic_plan_expands_safe_items_with_fixed_agent_and_aggregates(client, app):
    authenticated(client)
    import asyncio
    active = 0
    peak = 0
    calls = []

    async def dynamic_gateway(text, previous, key, **kwargs):
        nonlocal active, peak
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'items': [
                {'prompt': 'first item', 'id': 'a'},
                {'prompt': 'second item', 'id': 'b'},
                {'prompt': 'third item', 'id': 'c'},
            ]}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'items_seen': context['refs'][0]['output']['items']}
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.02)
            return {'status': 'completed', 'handled': context['dynamic_item']['id']}
        finally:
            active -= 1

    app.state.gateway.create_response = dynamic_gateway
    task = client.post('/api/hexa/tasks', json={'title': 'Dynamic plan', 'workflow': {
        'max_concurrency': 2,
        'nodes': [
            node('planner'),
            node('worker', deps=['planner'], inputRefs=['planner'], dynamic_plan={'source': 'planner', 'path': 'items', 'max_items': 3, 'mode': 'parallel'}),
            node('report', deps=['worker'], inputRefs=['worker'], final_report=True),
        ],
    }}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'dynamic-plan'})
    completed = wait_run(client, started.json()['id'], {'completed'})
    worker = next(row for row in completed['nodes'] if row['node_id'] == 'worker')
    assert peak == 2
    assert worker['output']['items'] == [
        {'handled': 'a', 'status': 'completed'},
        {'handled': 'b', 'status': 'completed'},
        {'handled': 'c', 'status': 'completed'},
    ]
    attempts = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    assert [row['execution_kind'] for row in attempts] == ['node', 'dynamic_item', 'dynamic_item', 'dynamic_item', 'dynamic_aggregate']
    assert [call['dynamic_item']['id'] for call in calls if 'dynamic_item' in call] == ['a', 'b', 'c']


def test_bounded_repeat_fails_at_limit_without_dispatching_extra_attempt(client, app):
    authenticated(client)
    calls = 0

    async def never_done(text, previous, key, **kwargs):
        nonlocal calls
        calls += 1
        return {'status': 'completed', 'done': False, 'iteration': calls}

    app.state.gateway.create_response = never_done
    task = client.post('/api/hexa/tasks', json={'title': 'Repeat limit', 'workflow': {'nodes': [
        node('worker', repeat={'max_iterations': 2, 'until': {'path': 'done', 'op': 'eq', 'value': True}}, final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'repeat-limit'})
    failed = wait_run(client, started.json()['id'], {'failed'})
    worker = next(row for row in failed['nodes'] if row['node_id'] == 'worker')
    assert worker['status'] == 'failed'
    assert worker['error_code'] == 'repeat_limit_exceeded'
    assert worker['attempt'] == 2
    assert calls == 2


def test_bounded_foreach_runs_each_item_and_aggregates_outputs(client, app):
    authenticated(client)
    calls = []

    async def foreach_gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute gate':
            return {'status': 'completed', 'items': ['alpha', 'beta', 'gamma']}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'report': context['refs'][0]['output']}
        return {'status': 'completed', 'item': context['foreach_item'], 'index': context['foreach_index']}

    app.state.gateway.create_response = foreach_gateway
    task = client.post('/api/hexa/tasks', json={'title': 'Bounded foreach', 'workflow': {'nodes': [
        node('gate'),
        node('worker', deps=['gate'], inputRefs=['gate'], foreach={'source': 'gate', 'path': 'items', 'max_items': 3}),
        node('report', deps=['worker'], inputRefs=['worker'], final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'foreach-run'})
    completed = wait_run(client, started.json()['id'], {'completed'})
    worker = next(row for row in completed['nodes'] if row['node_id'] == 'worker')
    assert worker['status'] == 'succeeded'
    assert worker['attempt'] == 1
    assert worker['input']['item_count'] == 3
    assert worker['output']['items'] == [
        {'status': 'completed', 'item': 'alpha', 'index': 0},
        {'status': 'completed', 'item': 'beta', 'index': 1},
        {'status': 'completed', 'item': 'gamma', 'index': 2},
    ]
    attempts = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    item_attempts = [row for row in attempts if row['execution_kind'] == 'foreach_item']
    assert [row['attempt'] for row in item_attempts] == [1, 1, 1]
    assert [row['foreach_index'] for row in item_attempts] == [0, 1, 2]
    assert [row['execution_kind'] for row in attempts if row['execution_kind'].endswith('_aggregate')] == ['foreach_aggregate']
    assert [call.get('foreach_item') for call in calls] == [None, 'alpha', 'beta', 'gamma', None]


def test_parallel_foreach_respects_workflow_limit_and_keeps_item_outputs_immutable(client, app):
    authenticated(client)
    import asyncio

    active = 0
    peak = 0
    calls = []

    async def parallel_gateway(text, previous, key, **kwargs):
        nonlocal active, peak
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute gate':
            return {'status': 'completed', 'items': ['alpha', 'beta', 'gamma']}
        if context['prompt'] == 'execute report':
            return {'status': 'completed', 'report': context['refs'][0]['output']}
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.02)
            return {'status': 'completed', 'item': context['foreach_item'], 'index': context['foreach_index']}
        finally:
            active -= 1

    app.state.gateway.create_response = parallel_gateway
    task = client.post('/api/hexa/tasks', json={'title': 'Parallel foreach', 'workflow': {
        'max_concurrency': 2,
        'nodes': [
            node('gate'),
            node('worker', deps=['gate'], inputRefs=['gate'], foreach={'source': 'gate', 'path': 'items', 'max_items': 3, 'mode': 'parallel'}),
            node('report', deps=['worker'], inputRefs=['worker'], final_report=True),
        ],
    }}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'parallel-foreach'})
    completed = wait_run(client, started.json()['id'], {'completed'})
    worker = next(row for row in completed['nodes'] if row['node_id'] == 'worker')
    assert peak == 2
    assert worker['status'] == 'succeeded'
    assert worker['output']['items'] == [
        {'status': 'completed', 'item': 'alpha', 'index': 0},
        {'status': 'completed', 'item': 'beta', 'index': 1},
        {'status': 'completed', 'item': 'gamma', 'index': 2},
    ]
    attempts = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    assert [row['input'].get('foreach_index') for row in attempts if row['input'].get('_orchestration_role') == 'foreach_item'] == [0, 1, 2]
    assert all(row['output'] is not None for row in attempts if row['input'].get('_orchestration_role') == 'foreach_item')
    assert any(row['input'].get('_orchestration_role') == 'foreach_aggregate' for row in attempts)


def test_bounded_foreach_rejects_more_items_than_limit_without_worker_call(client, app):
    authenticated(client)
    calls = []

    async def too_many(text, previous, key, **kwargs):
        calls.append(json.loads(text))
        return {'status': 'completed', 'items': ['a', 'b', 'c']}

    app.state.gateway.create_response = too_many
    task = client.post('/api/hexa/tasks', json={'title': 'Foreach limit', 'workflow': {'nodes': [
        node('gate'),
        node('worker', deps=['gate'], foreach={'source': 'gate', 'path': 'items', 'max_items': 2}, final_report=True),
    ]}}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'foreach-limit'})
    failed = wait_run(client, started.json()['id'], {'failed'})
    worker = next(row for row in failed['nodes'] if row['node_id'] == 'worker')
    assert worker['error_code'] == 'foreach_limit_exceeded'
    assert len(calls) == 1


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
