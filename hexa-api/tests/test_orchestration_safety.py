"""Execution boundaries shared by serial/parallel fanout and loop controls."""
import json

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db.models import create_session_factory
from app.tasks.service import TaskError, workflow_from_json
from tests.test_task_workflows import authenticated, node, wait_run


def test_existing_sqlite_node_history_upgrades_without_rewriting_output(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy-nodes.db'}"
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text('CREATE TABLE node_runs (id INTEGER PRIMARY KEY, output_json TEXT)'))
        db.execute(text("INSERT INTO node_runs VALUES (71, '{\"items\":[1]}')"))
    engine.dispose()
    for _ in range(2):
        factory = create_session_factory(url)
        columns = {column['name'] for column in inspect(factory.kw['bind']).get_columns('node_runs')}
        assert {'execution_kind', 'foreach_index'} <= columns
        with factory() as db:
            assert db.execute(text('SELECT output_json, execution_kind, foreach_index FROM node_runs WHERE id=71')).one() == ('{"items":[1]}', 'node', None)
        factory.kw['bind'].dispose()


@pytest.mark.parametrize('mode', ['serial', 'parallel'])
def test_collection_items_with_business_items_field_preserve_each_output(client, app, mode):
    authenticated(client)

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'values': [1, 2]}
        return {'status': 'completed', 'items': [context['foreach_item']]}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [
        node('source'), node('worker', deps=['source'], foreach={'source': 'source', 'path': 'values', 'max_items': 2, 'mode': mode}),
    ]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'business-items'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == 'completed'
    worker = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    assert worker['output'] == {'items': [
        {'status': 'completed', 'items': [1]}, {'status': 'completed', 'items': [2]},
    ]}
    attempts = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    children = [row for row in attempts if row['execution_kind'] == 'foreach_item']
    assert [row['foreach_index'] for row in children] == [0, 1]
    assert [row['attempt'] for row in children] == [1, 1]
    assert [row['output']['items'] for row in children] == [[1], [2]]
    assert worker['execution_kind'] == 'foreach_aggregate'


@pytest.mark.parametrize('mode', ['serial', 'parallel'])
def test_false_collection_condition_never_expands_or_executes_items(client, app, mode):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context['prompt'])
        return {'status': 'completed', 'route': 'no', 'values': [1, 2]}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [
        node('source'), node('worker', deps=['source'],
            condition={'source': 'source', 'path': 'route', 'op': 'eq', 'value': 'yes'},
            foreach={'source': 'source', 'path': 'values', 'max_items': 2, 'mode': mode}),
    ]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'skip-items'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == 'completed'
    worker = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    assert worker['status'] == 'skipped'
    assert worker['output'] is None
    assert calls == ['execute source']
    assert len(client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']) == 1


@pytest.mark.parametrize('value', [
    [{'id': 'x', 'prompt': 'a', 'agent_id': 'other'}],
    [{'id': 'x', 'prompt': 'a', 'mcp_servers': []}],
    [{'id': 'x', 'prompt': 'a'}, {'id': 'x', 'prompt': 'b'}],
    [{'id': '', 'prompt': 'a'}],
    [{'id': 'x', 'prompt': ''}],
    'not an array', None,
])
def test_invalid_dynamic_items_fail_without_worker_call(client, app, value):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        calls.append(json.loads(text)['prompt'])
        return {'status': 'completed', 'plan': value}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [
        node('planner'), node('worker', deps=['planner'], dynamic_plan={'source': 'planner', 'path': 'plan', 'max_items': 3}),
    ]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'invalid-plan'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == 'failed'
    worker = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    assert worker['error_code'] == 'dynamic_plan_invalid'
    assert calls == ['execute planner']


def test_loop_rejects_escaping_body_output_and_overlapping_scopes():
    definition = {'nodes': [
        node('work'), node('check', deps=['work'], loop={
            'body': ['work', 'check'], 'max_iterations': 2,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }), node('escape', deps=['work']),
    ]}
    with pytest.raises(TaskError) as failure:
        workflow_from_json(definition)
    assert failure.value.code == 'invalid_workflow'
