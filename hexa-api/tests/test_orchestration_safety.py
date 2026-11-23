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
        db.execute(text('CREATE TABLE run_decisions (id INTEGER PRIMARY KEY, run_id INTEGER, node_id TEXT, input_refs_json TEXT)'))
        db.execute(text("INSERT INTO run_decisions VALUES (81, 1, 'review', '[\"source\"]')"))
    engine.dispose()
    for _ in range(2):
        factory = create_session_factory(url)
        columns = {column['name'] for column in inspect(factory.kw['bind']).get_columns('node_runs')}
        assert {'execution_kind', 'iteration', 'foreach_index'} <= columns
        with factory() as db:
            assert db.execute(text('SELECT output_json, execution_kind, iteration, foreach_index FROM node_runs WHERE id=71')).one() == ('{"items":[1]}', 'node', 1, None)
            assert db.execute(text('SELECT node_id, input_refs_json, iteration FROM run_decisions WHERE id=81')).one() == ('review', '["source"]', 1)
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


@pytest.mark.anyio
@pytest.mark.parametrize('kind,remaining', [('repeat', 0), ('loop', 0), ('loop', 1)])
async def test_automatic_iterations_respect_record_budget_atomically(app, kind, remaining):
    from fastapi.testclient import TestClient
    from app.db.models import NodeRun, Run
    from app.tasks.service import TaskExecutor, latest_nodes
    from tests.test_task_concurrency import seed_run

    class Gateway:
        def __init__(self):
            self.calls = []

        async def create_response(self, text, previous, key, **kwargs):
            self.calls.append(json.loads(text)['prompt'])
            return {'status': 'completed', 'done': False}

    if kind == 'repeat':
        workflow = {'nodes': [node('work', repeat={
            'max_iterations': 2, 'until': {'path': 'done', 'op': 'eq', 'value': True},
        })]}
    else:
        workflow = {'nodes': [node('work'), node('check', deps=['work'], loop={
            'body': ['work', 'check'], 'max_iterations': 2,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        })]}
    with TestClient(app):
        run_id = seed_run(app, workflow)
        with app.state.session_factory() as db:
            db.add_all(NodeRun(run_id=run_id, node_id='work', iteration=0, status='succeeded')
                       for _ in range(500 - remaining - len(workflow['nodes'])))
            db.commit()
        gateway = Gateway()
        await TaskExecutor(app.state.session_factory, gateway).execute(run_id)
        with app.state.session_factory() as db:
            assert db.query(NodeRun).filter_by(run_id=run_id).count() == 500 - remaining
            assert db.get(Run, run_id).status == 'failed'
            failed = latest_nodes(db, run_id)['work' if kind == 'repeat' else 'check']
            assert failed.error_code == 'storage_limit_exceeded'
        assert gateway.calls == (['execute work'] if kind == 'repeat' else ['execute work', 'execute check'])


def test_skipped_dependency_does_not_silently_complete_pending_fanout(client, app):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        calls.append(json.loads(text)['prompt'])
        return {'status': 'completed', 'route': 'no', 'values': [1]}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [
        node('source'),
        node('branch', deps=['source'], condition={
            'source': 'source', 'path': 'route', 'op': 'eq', 'value': 'yes',
        }),
        node('worker', deps=['branch'], foreach={'source': 'branch', 'path': 'values', 'max_items': 2}),
    ]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'blocked-fanout'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == 'failed'
    assert calls == ['execute source']


def test_latest_node_uses_round_before_aggregate_priority(tmp_path):
    from app.db.models import NodeRun, Run, Task
    from app.tasks.service import latest_nodes

    factory = create_session_factory(f"sqlite:///{tmp_path / 'priority.db'}")
    try:
        with factory() as db:
            task = Task(user_id=1, title='Round priority')
            db.add(task)
            db.flush()
            run = Run(task_id=task.id, workflow_revision=1, snapshot_json='{}')
            db.add(run)
            db.flush()
            old = NodeRun(run_id=run.id, node_id='worker', iteration=1, attempt=10,
                          execution_kind='foreach_aggregate', status='succeeded', output_json='{"items":[1]}')
            current = NodeRun(run_id=run.id, node_id='worker', iteration=2, attempt=1)
            db.add_all([old, current])
            db.flush()
            assert latest_nodes(db, run.id)['worker'].id == current.id
            assert old.output_json == '{"items":[1]}'
    finally:
        factory.kw['bind'].dispose()


@pytest.mark.parametrize('node_type', ['human', 'human_gate'])
@pytest.mark.parametrize('kind,config', [
    ('repeat', {'max_iterations': 2, 'until': {'path': 'done', 'op': 'exists'}}),
    ('foreach', {'source': 'source', 'path': 'values', 'max_items': 2}),
    ('dynamic_plan', {'source': 'source', 'path': 'values', 'max_items': 2}),
    ('loop', {'body': ['review'], 'max_iterations': 2,
              'until': {'source': 'review', 'path': 'done', 'op': 'exists'}}),
])
def test_explicit_human_nodes_reject_execution_modes(node_type, kind, config):
    with pytest.raises(TaskError) as failure:
        workflow_from_json({'nodes': [node('source'), node('review', node_type=node_type,
            deps=['source'], **{kind: config})]})
    assert failure.value.code == 'invalid_workflow'


@pytest.mark.parametrize('kind', ['foreach', 'dynamic_plan'])
def test_gated_fanout_requires_human_before_expansion(client, app, kind):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        return {'status': 'completed', 'values': [1] if kind == 'foreach' else [{'id': 'one', 'prompt': 'do one'}]}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [node('source'),
        node('work', deps=['source'], requires_human=True, **{kind: {
            'source': 'source', 'path': 'values', 'max_items': 2,
        }}),
    ]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'gated-expansion'}).json()
    waiting = wait_run(client, run['id'], {'waiting_human', 'completed', 'failed'})
    assert waiting['status'] == 'waiting_human'
    assert len(calls) == 1
    control = next(row for row in waiting['nodes'] if row['node_id'] == 'work')
    assert len(client.get(f"/api/hexa/node-runs/{control['id']}").json()['attempts']) == 1
    confirmed = client.post(f"/api/hexa/runs/{run['id']}/continue", json={
        'node_id': 'work', 'input_refs': ['source'],
    }, headers={'Idempotency-Key': 'confirm-expansion'})
    assert confirmed.status_code == 200
    assert wait_run(client, run['id'], {'completed', 'failed'})['status'] == 'completed'
    assert len(calls) == 2


def test_loop_human_confirmation_is_scoped_to_each_round(client, app):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        return {'status': 'completed', 'done': bool(context.get('loop_previous'))}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [
        node('source'), node('work', deps=['source'], inputRefs=['source'], requires_human=True),
        node('check', deps=['work'], inputRefs=['work'], loop={
            'body': ['work', 'check'], 'max_iterations': 2,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }),
    ]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'loop-human'}).json()
    for iteration in (1, 2):
        waiting = wait_run(client, run['id'], {'waiting_human', 'completed', 'failed'})
        assert waiting['status'] == 'waiting_human'
        assert next(row for row in waiting['nodes'] if row['node_id'] == 'work')['iteration'] == iteration
        assert len(calls) == (1 if iteration == 1 else 3)
        result = client.post(f"/api/hexa/runs/{run['id']}/continue", json={
            'node_id': 'work', 'input_refs': ['source'],
        }, headers={'Idempotency-Key': f'confirm-round-{iteration}'})
        assert result.status_code == 200
    assert wait_run(client, run['id'], {'completed', 'failed'})['status'] == 'completed'
    assert len(calls) == 5
    history = client.get(f"/api/hexa/runs/{run['id']}").json()['decision_history']
    assert history == [
        {'node_id': 'work', 'iteration': 1, 'input_refs': ['source']},
        {'node_id': 'work', 'iteration': 2, 'input_refs': ['source']},
    ]


@pytest.mark.anyio
async def test_concurrent_fanouts_reserve_each_pending_aggregate(app):
    from fastapi.testclient import TestClient
    from app.db.models import NodeRun
    from app.tasks.service import TaskExecutor, latest_nodes
    from tests.test_task_concurrency import seed_run

    class Gateway:
        async def create_response(self, *args, **kwargs):
            return {'status': 'completed', 'text': 'item'}

    workflow = {'nodes': [node('source'), *[
        node(name, deps=['source'], foreach={'source': 'source', 'path': 'values', 'max_items': 1})
        for name in ('first', 'second')
    ]]}
    with TestClient(app):
        run_id = seed_run(app, workflow)
        with app.state.session_factory() as db:
            source = latest_nodes(db, run_id)['source']
            source.status, source.output_json = 'succeeded', '{"values":[1]}'
            db.add_all(NodeRun(run_id=run_id, node_id='source', iteration=0, status='succeeded')
                       for _ in range(494))
            db.commit()
        await TaskExecutor(app.state.session_factory, Gateway()).execute(run_id)
        with app.state.session_factory() as db:
            assert db.query(NodeRun).filter_by(run_id=run_id).count() <= 500
            assert latest_nodes(db, run_id)['second'].error_code == 'storage_limit_exceeded'
