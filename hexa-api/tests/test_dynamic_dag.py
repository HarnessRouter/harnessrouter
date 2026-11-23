"""Runtime-local DAG plans retain static execution identity and immutable history."""
import asyncio
import json
import time

import pytest

from app.tasks.service import TaskError, workflow_from_json
from tests.test_task_workflows import authenticated, node, wait_run


def definition(mode='parallel', hold=False):
    return {'max_concurrency': 2, 'nodes': [node('planner'), node(
        'worker', deps=['planner'], inputRefs=['planner'], final_report=True,
        dynamic_plan={'source': 'planner', 'path': 'plan', 'max_items': 10, 'mode': mode, 'topology': 'dag'},
    ), *([node('hold', node_type='human', deps=['planner'])] if hold else [])]}


PLAN = [
    {'id': 'join', 'prompt': 'combine', 'deps': ['a', 'b'], 'inputRefs': ['b']},
    {'id': 'a', 'prompt': 'first'}, {'id': 'b', 'prompt': 'second'},
]


@pytest.mark.parametrize('topology', [None, 'graph', True, [], {}])
def test_invalid_dynamic_topology_rejected_before_revision(topology):
    workflow = definition()
    workflow['nodes'][1]['dynamic_plan']['topology'] = topology
    with pytest.raises(TaskError):
        workflow_from_json(workflow)


@pytest.mark.parametrize('mode', ['serial', 'parallel'])
@pytest.mark.parametrize('json_text', [False, True])
def test_dag_fork_join_obeys_dependencies_and_selected_inputs(client, app, mode, json_text):
    authenticated(client)
    calls, active, done = [], set(), set()
    peak = 0

    async def gateway(text, previous, key, **kwargs):
        nonlocal peak
        context = json.loads(text)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'plan': json.dumps(PLAN) if json_text else PLAN}
        identity = context['dynamic_item']['id']
        calls.append((identity, context, kwargs))
        if identity == 'join':
            assert done == {'a', 'b'}
        active.add(identity)
        peak = max(peak, len(active))
        await asyncio.sleep(0.02)
        active.remove(identity)
        done.add(identity)
        return {'status': 'completed', 'value': identity}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': definition(mode)}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'dag'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result
    assert [identity for identity, _, _ in calls] == ['a', 'b', 'join']
    assert peak == (2 if mode == 'parallel' else 1)
    joined = calls[-1][1]
    assert [ref['id'] for ref in joined['plan_refs']] == ['b']
    assert joined['plan_refs'][0]['output'] == {'status': 'completed', 'value': 'b'}
    assert [ref['node_id'] for ref in joined['refs']] == ['planner']
    assert all(kwargs['agent_id'] == 'agent-1' for _, _, kwargs in calls)
    target = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    assert target['output']['items'] == [
        {'id': identity, 'status': 'succeeded', 'output': {'status': 'completed', 'value': identity}}
        for identity in ('join', 'a', 'b')
    ]
    assert result['workflow'] == task['workflow']


@pytest.mark.parametrize('plan', [
    [{'id': 'a', 'prompt': 'x', 'deps': ['missing']}],
    [{'id': 'a', 'prompt': 'x', 'deps': ['a']}],
    [{'id': 'a', 'prompt': 'x', 'deps': ['b']}, {'id': 'b', 'prompt': 'y', 'deps': ['a']}],
    [{'id': 'a', 'prompt': 'x', 'agent_id': 'other'}],
    [{'id': 'a', 'prompt': 'x', 'deps': [], 'inputRefs': ['b']}, {'id': 'b', 'prompt': 'y'}],
    [{'id': 'a', 'prompt': 'x', 'deps': ['b', 'b']}, {'id': 'b', 'prompt': 'y'}],
    [{'id': 'a', 'prompt': 'x', 'condition': {'source': 'b', 'path': 'ok', 'op': 'eq', 'value': True}}],
    [{'id': 'a', 'prompt': 'x', 'allow_missing_inputs': 'true'}],
    '```json\n[]\n```', '[invalid]', 'null',
])
def test_invalid_dag_fails_before_any_child_is_created(client, app, plan):
    authenticated(client)
    async def gateway(text, previous, key, **kwargs):
        assert json.loads(text)['prompt'] == 'execute planner'
        return {'status': 'completed', 'plan': plan}
    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': definition()}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'invalid'}).json()
    result = wait_run(client, run['id'], {'failed'})
    worker = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    assert worker['error_code'] == 'dynamic_plan_invalid'
    assert client.get(f"/api/hexa/node-runs/{worker['id']}/items").json()['items'] == []


@pytest.mark.parametrize('allow_missing', [False, True])
def test_dag_condition_skips_and_explicit_join_controls_missing_input(client, app, allow_missing):
    authenticated(client)
    plan = [{'id': 'route', 'prompt': 'route'},
            {'id': 'skip', 'prompt': 'unused', 'deps': ['route'],
             'condition': {'source': 'route', 'path': 'value', 'op': 'eq', 'value': 'different'}},
            {'id': 'join', 'prompt': 'join', 'deps': ['route', 'skip'], 'inputRefs': ['route', 'skip'],
             'allow_missing_inputs': allow_missing}]
    calls = []
    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'plan': plan}
        identity = context['dynamic_item']['id']
        calls.append(context)
        return {'status': 'completed', 'value': identity}
    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': definition()}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'condition'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == ('completed' if allow_missing else 'failed')
    assert [call['dynamic_item']['id'] for call in calls] == (['route', 'join'] if allow_missing else ['route'])
    worker = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    if allow_missing:
        assert worker['output']['items'][1] == {'id': 'skip', 'status': 'skipped', 'output': None}
        assert [ref['id'] for ref in calls[-1]['plan_refs']] == ['route']
    else:
        assert worker['error_code'] == 'dynamic_dependency_unavailable'


@pytest.mark.parametrize('terminal', [False, True])
def test_dag_retry_or_resume_keeps_success_and_current_plan_refs(client, app, terminal):
    authenticated(client)
    calls = []
    plan = [{'id': 'a', 'prompt': 'a'}, {'id': 'b', 'prompt': 'b', 'deps': ['a'], 'inputRefs': ['a']},
            {'id': 'c', 'prompt': 'c', 'deps': ['b'], 'inputRefs': ['b']}]
    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute planner':
            calls.append('planner')
            return {'status': 'completed', 'plan': plan}
        identity = context['dynamic_item']['id']
        calls.append(identity)
        if identity == 'b' and calls.count('b') == 1:
            raise RuntimeError('unknown; explicit recovery only')
        return {'status': 'completed', 'value': identity}
    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': definition(hold=not terminal)}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'start'}).json()
    result = wait_run(client, started['id'], {'failed' if terminal else 'waiting_human'})
    target = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    items = client.get(f"/api/hexa/node-runs/{target['id']}/items").json()['items']
    failed = next(row for row in items if row['status'] == 'failed')
    if terminal:
        response = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
            'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': result['id'], 'item_node_run_id': failed['id'],
        }, headers={'Idempotency-Key': 'resume'})
        assert response.status_code == 202
        run_id = response.json()['id']
    else:
        assert client.post(f"/api/hexa/runs/{result['id']}/nodes/worker/retry", json={'item_node_run_id': failed['id']},
                           headers={'Idempotency-Key': 'retry'}).status_code == 200
        run_id = result['id']
    for _ in range(300):
        current = client.get(f'/api/hexa/runs/{run_id}').json()
        worker = next(row for row in current['nodes'] if row['node_id'] == 'worker')
        if worker['status'] == 'succeeded':
            break
        time.sleep(0.01)
    assert worker['status'] == 'succeeded', current
    assert calls == ['planner', 'a', 'b', 'b', 'c']
    history = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    by_id = {row['id']: row for row in history}
    for row in history:
        for ref in row['input'].get('plan_refs', []):
            assert by_id[ref['node_run_id']]['run_id'] == run_id
    if terminal:
        assert client.get(f"/api/hexa/runs/{result['id']}").json() == result


def test_graph_validation_unit_covers_shape_and_no_expression_execution():
    from app.tasks.dynamic_graph import graph_valid
    assert graph_valid(PLAN)
    assert graph_valid([])
    assert not graph_valid([{'id': 'a', 'prompt': 'p', 'condition': 'eval(1)'}])
    assert not graph_valid([{'id': 'a', 'prompt': 'p', 'deps': True}])
    assert not graph_valid([{'id': 'a', 'prompt': 'p', 'condition': {'source': 'a', 'path': 'x', 'op': []}}])


@pytest.mark.anyio
@pytest.mark.parametrize('action', ['pause', 'cancel', 'recover'])
async def test_dynamic_dag_control_prevents_dependent_dispatch(client, app, action):
    from app.db.models import Run, NodeRun
    from app.tasks.service import TaskExecutor
    from tests.test_task_concurrency import seed_run
    plan = [{'id': 'a', 'prompt': 'a'}, {'id': 'b', 'prompt': 'b', 'deps': ['a'], 'inputRefs': ['a']}]
    run_id = seed_run(app, definition())
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    class Gateway:
        async def create_response(self, text, previous, key, **kwargs):
            context = json.loads(text)
            if context['prompt'] == 'execute planner':
                return {'status': 'completed', 'plan': plan}
            calls.append(context['dynamic_item']['id'])
            entered.set()
            await release.wait()
            return {'status': 'completed'}
    executor = TaskExecutor(app.state.session_factory, Gateway())
    job = asyncio.create_task(executor.execute(run_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if action == 'recover':
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            executor.recover()
        elif action == 'pause':
            with app.state.session_factory() as db:
                db.get(Run, run_id).paused = True
                db.commit()
        else:
            authenticated(client)
            assert client.post(f'/api/hexa/runs/{run_id}/cancel', headers={'Idempotency-Key': 'cancel'}).status_code == 200
        release.set()
        await asyncio.wait_for(asyncio.gather(job, return_exceptions=True), 5)
        assert calls == ['a']
        with app.state.session_factory() as db:
            rows = db.query(NodeRun).filter_by(run_id=run_id, execution_kind='dynamic_item').order_by(NodeRun.id).all()
            if action == 'pause':
                assert [row.status for row in rows] == ['succeeded', 'idle']
            else:
                assert rows[0].error_code == 'interrupted_unknown_outcome'
    finally:
        release.set()
        if not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)


def test_dynamic_dag_in_loop_keeps_each_round_local_refs(client, app):
    authenticated(client)
    workflow = definition()
    workflow['nodes'][1].pop('final_report')
    workflow['nodes'].append(node('check', deps=['worker'], inputRefs=['worker'], final_report=True, loop={
        'body': ['worker', 'check'], 'max_iterations': 3,
        'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
    }))
    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'plan': PLAN}
        if context['prompt'] == 'execute check':
            return {'status': 'completed', 'done': bool(context.get('loop_previous'))}
        return {'status': 'completed', 'value': context['dynamic_item']['id']}
    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': workflow}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'loop'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == 'completed'
    worker = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    history = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    by_id = {row['id']: row for row in history}
    assert worker['iteration'] == 2
    for row in history:
        for ref in row['input'].get('plan_refs', []):
            assert by_id[ref['node_run_id']]['iteration'] == row['iteration']


@pytest.mark.parametrize('plan', [[], PLAN * 4])
def test_dag_empty_and_oversize_plans_do_not_dispatch_children(client, app, plan):
    authenticated(client)
    async def gateway(text, previous, key, **kwargs):
        assert json.loads(text)['prompt'] == 'execute planner'
        return {'status': 'completed', 'plan': plan}
    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': definition()}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'size'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == ('failed' if plan else 'completed')
    target = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    if not plan:
        assert target['output'] == {'items': []}


def test_dag_human_gate_precedes_plan_materialization(client, app):
    authenticated(client)
    calls = []
    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute planner':
            return {'status': 'completed', 'plan': PLAN}
        return {'status': 'completed', 'value': context['dynamic_item']['id']}
    app.state.gateway.create_response = gateway
    workflow = definition()
    workflow['nodes'][1]['requires_human'] = True
    task = client.post('/api/hexa/tasks', json={'workflow': workflow}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'gated'}).json()
    result = wait_run(client, run['id'], {'waiting_human'})
    target = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    assert client.get(f"/api/hexa/node-runs/{target['id']}/items").json()['items'] == []
    assert len(calls) == 1
    assert client.post(f"/api/hexa/runs/{run['id']}/continue", json={'node_id': 'worker', 'input_refs': ['planner']},
                       headers={'Idempotency-Key': 'approve'}).status_code == 200
    assert wait_run(client, run['id'], {'completed', 'failed'})['status'] == 'completed'


@pytest.mark.anyio
async def test_dag_reserves_all_items_and_aggregate_before_any_child_call(client, app):
    from app.db.models import NodeRun
    from app.tasks.service import TaskExecutor, latest_nodes
    from tests.test_task_concurrency import seed_run
    run_id = seed_run(app, definition())
    with app.state.session_factory() as db:
        source = latest_nodes(db, run_id)['planner']
        source.status, source.output_json = 'succeeded', json.dumps({'plan': PLAN})
        db.add_all(NodeRun(run_id=run_id, node_id='planner', iteration=0, status='succeeded') for _ in range(495))
        db.commit()
    class Gateway:
        async def create_response(self, *args, **kwargs):
            pytest.fail('quota rejected before dispatch')
    await TaskExecutor(app.state.session_factory, Gateway()).execute(run_id)
    with app.state.session_factory() as db:
        assert latest_nodes(db, run_id)['worker'].error_code == 'storage_limit_exceeded'
        assert db.query(NodeRun).filter_by(run_id=run_id).count() == 497


def test_http_dag_terminal_recovery_and_restart_keep_successful_local_references(client, app):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from app.gateway.client import GatewayClient
    from app.main import create_app
    calls = []
    plan = [{'id': 'a', 'prompt': 'a'}, {'id': 'b', 'prompt': 'b', 'deps': ['a'], 'inputRefs': ['a']},
            {'id': 'c', 'prompt': 'c', 'deps': ['b'], 'inputRefs': ['a', 'b']}]
    # c consumes only direct dependencies, so explicitly declare both.
    plan[-1]['deps'] = ['a', 'b']
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context = json.loads(body['input'][0]['content'])
            identity = context.get('dynamic_item', {}).get('id', 'planner')
            calls.append((identity, self.headers.get('Idempotency-Key')))
            failed = identity == 'b' and sum(name == 'b' for name, _ in calls) == 1
            output = json.dumps(plan) if identity == 'planner' else identity
            final = {'id': f'response-{len(calls)}', 'status': 'failed' if failed else 'completed',
                     'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}]}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(('data: ' + json.dumps({'type': 'response.failed' if failed else 'response.completed', 'response': final}) + '\n\n').encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        authenticated(client)
        app.state.task_executor.gateway = GatewayClient(f'http://127.0.0.1:{server.server_port}', 'fixture-key')
        workflow = definition()
        workflow['nodes'][1]['dynamic_plan']['path'] = 'text'
        task = client.post('/api/hexa/tasks', json={'workflow': workflow}).json()
        run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'http-first'}).json()
        failed = wait_run(client, run['id'], {'failed'})
        old_worker = next(row for row in failed['nodes'] if row['node_id'] == 'worker')
        prior = client.get(f"/api/hexa/node-runs/{old_worker['id']}/items").json()
        selected = next(row for row in prior['items'] if row['status'] == 'failed')
        response = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
            'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': run['id'], 'item_node_run_id': selected['id'],
        }, headers={'Idempotency-Key': 'http-resume'})
        assert response.status_code == 202, response.json()
        completed = wait_run(client, response.json()['id'], {'completed', 'failed'})
        assert completed['status'] == 'completed'
        assert [name for name, _ in calls] == ['planner', 'a', 'b', 'b', 'c']
        assert calls[2][1] != calls[3][1]
        worker = next(row for row in completed['nodes'] if row['node_id'] == 'worker')
        current = client.get(f"/api/hexa/node-runs/{worker['id']}/items").json()
        by_id = {row['id']: row for row in current['items']}
        for row in current['items']:
            assert row['run_id'] == completed['id']
            for ref in row['input'].get('plan_refs', []):
                assert by_id[ref['node_run_id']]['run_id'] == completed['id']
        with TestClient(create_app(app.state.settings, app.state.gateway)) as restarted:
            restarted.cookies.update(client.cookies)
            assert restarted.get(f"/api/hexa/node-runs/{worker['id']}/items").json() == current
            assert restarted.get(f"/api/hexa/node-runs/{old_worker['id']}/items").json() == prior
        assert len(calls) == 5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
