"""Explicit fanout retries preserve successful calls and immutable attempts."""
import json
import time

import pytest

from app.db.models import NodeRun
from app.tasks.service import TaskError, encoded, latest_nodes
from app.tasks.fanout import retry_fanout, fanout_items
from tests.test_task_workflows import authenticated, node, wait_run


@pytest.mark.parametrize('kind,mode', [('foreach', 'serial'), ('foreach', 'parallel'),
                                       ('dynamic_plan', 'serial'), ('dynamic_plan', 'parallel')])
def test_retry_preserves_successful_items_and_appends_only_failed_calls(client, app, kind, mode):
    authenticated(client)
    calls = []
    prefix = 'foreach' if kind == 'foreach' else 'dynamic'

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'values': ['ok', 'bad', 'late'] if kind == 'foreach' else [
                {'id': value, 'prompt': value} for value in ('ok', 'bad', 'late')
            ]}
        value = context[f'{prefix}_item']
        identity = value if kind == 'foreach' else value['id']
        calls.append(identity)
        if identity == 'bad' and calls.count('bad') == 1:
            raise RuntimeError('outcome unknown: retry must be explicit')
        return {'status': 'completed', 'value': identity}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'max_concurrency': 1, 'nodes': [
        node('source'),
        node('worker', deps=['source'], inputRefs=['source'], **{kind: {
            'source': 'source', 'path': 'values', 'max_items': 3, 'mode': mode,
        }}),
        node('hold', node_type='human', deps=['source']),
    ]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'start-retry'}).json()
    waiting = wait_run(client, run['id'], {'waiting_human', 'failed'})
    assert waiting['status'] == 'waiting_human'
    worker = next(row for row in waiting['nodes'] if row['node_id'] == 'worker')
    assert worker['status'] == 'failed'
    before = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    failed = next(row for row in before if row['execution_kind'] == f'{prefix}_item' and row['status'] == 'failed')
    result = client.post(f"/api/hexa/runs/{run['id']}/nodes/worker/retry", json={
        'item_node_run_id': failed['id'],
    }, headers={'Idempotency-Key': 'retry-item'})
    assert result.status_code == 200
    assert client.post(f"/api/hexa/runs/{run['id']}/nodes/worker/retry", json={
        'item_node_run_id': failed['id'],
    }, headers={'Idempotency-Key': 'retry-item'}).json() == result.json()
    for _ in range(200):
        current = client.get(f"/api/hexa/runs/{run['id']}").json()
        aggregate = next(row for row in current['nodes'] if row['node_id'] == 'worker')
        if aggregate['status'] == 'succeeded':
            break
        time.sleep(0.01)
    assert aggregate['status'] == 'succeeded', current
    assert calls == ['ok', 'bad', 'bad', 'late']
    assert aggregate['attempt'] == 2
    assert aggregate['output']['items'] == [
        {'status': 'completed', 'value': value} for value in ('ok', 'bad', 'late')
    ]
    history = client.get(f"/api/hexa/node-runs/{aggregate['id']}").json()['attempts']
    by_id = {row['id']: row for row in history}
    assert all(by_id[row['id']] == row for row in before)
    selected = [by_id[identity] for identity in aggregate['input']['item_node_run_ids']]
    assert [row['attempt'] for row in selected] == [1, 2, 2]
    assert [row['foreach_index'] for row in selected] == [0, 1, 2]
    assert aggregate['input']['refs'][0]['node_id'] == 'source'
    conflict = client.post(f"/api/hexa/runs/{run['id']}/nodes/worker/retry", json={},
                          headers={'Idempotency-Key': 'retry-item'})
    assert conflict.status_code == 409
    assert conflict.json()['detail']['code'] == 'idempotency_conflict'
    confirmed = client.post(f"/api/hexa/runs/{run['id']}/continue", json={
        'node_id': 'hold', 'input_refs': ['source'],
    }, headers={'Idempotency-Key': 'finish-hold'})
    assert confirmed.status_code == 200
    assert wait_run(client, run['id'], {'completed', 'failed'})['status'] == 'completed'


@pytest.fixture()
def failed_collection(client, app):
    from tests.test_task_concurrency import seed_run
    from app.db.models import Run
    workflow = {'nodes': [node('source'), node('worker', deps=['source'], foreach={
        'source': 'source', 'path': 'values', 'max_items': 3,
    })]}
    run_id = seed_run(app, workflow)
    with app.state.session_factory() as db:
        run = db.get(Run, run_id)
        run.status = 'waiting_human'
        source = latest_nodes(db, run_id)['source']
        source.status, source.output_json = 'succeeded', '{"values":[1,2,3]}'
        control = latest_nodes(db, run_id)['worker']
        children = [NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_item',
                            foreach_index=index, status=status, error_code='agent_failed' if status == 'failed' else None,
                            input_json=encoded({'foreach_item': index, 'foreach_index': index}),
                            output_json='{"result":0}' if status == 'succeeded' else None)
                    for index, status in enumerate(['succeeded', 'failed', 'failed'])]
        db.add_all(children)
        db.flush()
        control.status = 'failed'
        control.input_json = encoded({'item_node_run_ids': [row.id for row in children]})
        identities = (run_id, control.id, [row.id for row in children])
        db.commit()
    return identities, workflow


def test_manifest_ignores_unselected_historical_item_attempts(app, failed_collection):
    (run_id, control_id, children), _ = failed_collection
    with app.state.session_factory() as db:
        db.add(NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_item',
                       foreach_index=1, attempt=99, status='succeeded', output_json='{"wrong":true}'))
        db.flush()
        selected = fanout_items(db, db.get(NodeRun, control_id), 'foreach')
        assert [row.id for row in selected] == children


@pytest.mark.parametrize('invalid', ['source', 'success', 'other_round', 'unknown'])
def test_invalid_retry_reference_writes_nothing(client, app, failed_collection, invalid):
    authenticated(client)
    (run_id, control_id, children), _ = failed_collection
    with app.state.session_factory() as db:
        other = NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_item',
                        iteration=2, foreach_index=1, status='failed')
        db.add(other)
        db.commit()
        identity = {'source': latest_nodes(db, run_id)['source'].id, 'success': children[0],
                    'other_round': other.id, 'unknown': 99999}[invalid]
        before = db.query(NodeRun).filter_by(run_id=run_id).count()
    response = client.post(f'/api/hexa/runs/{run_id}/nodes/worker/retry',
                           json={'item_node_run_id': identity}, headers={'Idempotency-Key': 'invalid-retry'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_retry_item'
    with app.state.session_factory() as db:
        assert db.query(NodeRun).filter_by(run_id=run_id).count() == before


def test_retry_budget_rejection_is_atomic(client, app, failed_collection):
    authenticated(client)
    (run_id, _, children), _ = failed_collection
    with app.state.session_factory() as db:
        count = db.query(NodeRun).filter_by(run_id=run_id).count()
        db.add_all(NodeRun(run_id=run_id, node_id='source', iteration=0, status='succeeded')
                   for _ in range(498 - count))
        db.commit()
    response = client.post(f'/api/hexa/runs/{run_id}/nodes/worker/retry',
                           json={'item_node_run_id': children[1]}, headers={'Idempotency-Key': 'full-retry'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'storage_limit_exceeded'
    with app.state.session_factory() as db:
        assert db.query(NodeRun).filter_by(run_id=run_id).count() == 498


def test_terminal_collection_retry_requires_new_run(client, app, failed_collection):
    from app.db.models import Run
    authenticated(client)
    (run_id, _, children), _ = failed_collection
    with app.state.session_factory() as db:
        db.get(Run, run_id).status = 'failed'
        db.commit()
        count = db.query(NodeRun).filter_by(run_id=run_id).count()
    response = client.post(f'/api/hexa/runs/{run_id}/nodes/worker/retry',
                           json={'item_node_run_id': children[1]}, headers={'Idempotency-Key': 'terminal-retry'})
    assert response.status_code == 409
    with app.state.session_factory() as db:
        assert db.query(NodeRun).filter_by(run_id=run_id).count() == count


@pytest.mark.parametrize('payload', [
    {'item_node_run_id': True}, {'item_node_run_id': '3'}, {'item_node_run_id': 0},
    {'item_node_run_id': 3, 'agent_id': 'injected'},
])
def test_retry_rejects_untyped_or_execution_configuration_payload(client, failed_collection, payload):
    authenticated(client)
    (run_id, _, _), _ = failed_collection
    assert client.post(f'/api/hexa/runs/{run_id}/nodes/worker/retry', json=payload,
                       headers={'Idempotency-Key': 'typed-retry'}).status_code == 422


@pytest.mark.anyio
async def test_selected_retry_runs_even_when_another_item_remains_failed(app, failed_collection):
    from app.db.models import Run
    from app.tasks.service import TaskExecutor
    (run_id, control_id, children), workflow = failed_collection
    calls = []

    class Gateway:
        async def create_response(self, text, previous, key, **kwargs):
            value = json.loads(text)['foreach_item']
            calls.append(value)
            return {'status': 'completed', 'value': value}

    with app.state.session_factory() as db:
        run = db.get(Run, run_id)
        retry_fanout(db, run, workflow['nodes'][1], db.get(NodeRun, control_id), children[1],
                     encoded=encoded, error=TaskError)
        run.status = 'running'
        db.commit()
    await TaskExecutor(app.state.session_factory, Gateway()).execute(run_id)
    assert calls == [1]
    with app.state.session_factory() as db:
        selected = fanout_items(db, latest_nodes(db, run_id)['worker'], 'foreach')
        assert [row.status for row in selected] == ['succeeded', 'succeeded', 'failed']
        assert db.get(NodeRun, children[1]).status == 'failed'


@pytest.mark.parametrize('terminal', [False, True])
@pytest.mark.parametrize('nested', [False, True])
def test_http_retry_uses_fresh_request_and_survives_read_only_restart(client, app, terminal, nested):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from app.gateway.client import GatewayClient
    from app.main import create_app
    from fastapi.testclient import TestClient

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context = json.loads(body['input'][0]['content'])
            calls.append((context, self.headers.get('Idempotency-Key')))
            rid = f'retry-{len(calls)}'
            failed = context['prompt'] == 'execute worker' and sum(c[0]['prompt'] == 'execute worker' for c in calls) == 1
            annotations = [{'type': 'container_file_citation', 'file_id': 'input',
                            'container_id': 'fixture', 'filename': 'input.txt'}]
            final = {'id': rid, 'status': 'failed' if failed else 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': 'finished',
                  'annotations': annotations if context['prompt'] in ('execute source', 'execute prep') else []}]}]}
            events = [{'type': 'response.created', 'response': {'id': rid}},
                      {'type': 'response.output_text.delta', 'delta': 'finished'},
                      {'type': 'response.failed' if failed else 'response.completed', 'response': final}]
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for event in events:
                self.wfile.write(f'data: {json.dumps(event)}\n\n'.encode())
                self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        authenticated(client)
        app.state.task_executor.gateway = GatewayClient(f'http://127.0.0.1:{server.server_port}', 'fixture-key')
        task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [node('source'),
            *([node('prep', deps=['source'], inputRefs=['source'], foreach={
                'source': 'source', 'path': 'artifacts', 'max_items': 1,
            })] if nested else []),
            node('worker', deps=['prep' if nested else 'source'], inputRefs=['prep' if nested else 'source'], foreach={
                'source': 'prep' if nested else 'source', 'path': 'items' if nested else 'artifacts', 'max_items': 1,
                **({'nested': {'path': 'artifacts', 'max_items': 1}} if nested else {}),
            }), *([] if terminal else [node('hold', deps=['source'], node_type='human')]),
        ]}}).json()
        run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'http-start'}).json()
        waiting = wait_run(client, run['id'], {'failed' if terminal else 'waiting_human'})
        control = next(row for row in waiting['nodes'] if row['node_id'] == 'worker')
        before = client.get(f"/api/hexa/node-runs/{control['id']}").json()['attempts']
        failed = next(row for row in before if row['execution_kind'] == 'foreach_item')
        assert failed['status'] == 'failed'
        if terminal:
            resumed = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
                'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': run['id'],
                'item_node_run_id': failed['id'],
            }, headers={'Idempotency-Key': 'http-resume'})
            assert resumed.status_code == 202
            original_run_id = run['id']
            run = resumed.json()
            assert run['id'] != original_run_id
        else:
            assert client.post(f"/api/hexa/runs/{run['id']}/nodes/worker/retry", json={
                'item_node_run_id': failed['id'],
            }, headers={'Idempotency-Key': 'http-retry'}).status_code == 200
        for _ in range(200):
            result = client.get(f"/api/hexa/runs/{run['id']}").json()
            aggregate = next(row for row in result['nodes'] if row['node_id'] == 'worker')
            if aggregate['status'] == 'succeeded' and result['status'] == ('completed' if terminal else 'waiting_human'):
                break
            time.sleep(0.01)
        assert aggregate['status'] == 'succeeded'
        assert len(calls) == (4 if nested else 3)
        assert calls[-2][0]['foreach_item'] == calls[-1][0]['foreach_item']
        assert calls[-2][1] != calls[-1][1]
        history = client.get(f"/api/hexa/node-runs/{aggregate['id']}").json()['attempts']
        with TestClient(create_app(app.state.settings, app.state.gateway)) as restarted:
            restarted.cookies.update(client.cookies)
            assert restarted.get(f"/api/hexa/node-runs/{aggregate['id']}").json()['attempts'] == history
            assert restarted.get(f"/api/hexa/runs/{run['id']}").json() == result
        assert len(calls) == (4 if nested else 3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
