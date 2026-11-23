"""Two-level collection boundaries through task API and persisted manifests."""
import asyncio
import json
import time

import pytest

from app.db.models import NodeRun, Run
from app.tasks.fanout import advance_fanouts, node_record_usage
from app.tasks.service import encoded, latest_nodes, value_at_path, condition_matches
from tests.test_task_workflows import authenticated, node, wait_run


def workflow(outer='serial', inner='serial', hold=False):
    return {'max_concurrency': 4, 'nodes': [node('source'), node(
        'worker', deps=['source'], inputRefs=['source'], foreach={
            'source': 'source', 'path': 'groups', 'max_items': 3, 'mode': outer,
            'nested': {'path': 'items', 'max_items': 3, 'mode': inner},
        }, final_report=True,
    ), *([node('hold', node_type='human', deps=['source'])] if hold else [])]}


@pytest.mark.parametrize('outer,inner', [('serial', 'serial'), ('serial', 'parallel'),
                                         ('parallel', 'serial'), ('parallel', 'parallel')])
def test_nested_modes_obey_outer_boundary_and_global_limit(client, app, outer, inner):
    authenticated(client)
    active, completed, observed = set(), set(), []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'groups': [{'items': ['a', 'b']}, {'items': ['c', 'd']}]}
        value = context['foreach_item']
        observed.append((value, set(active), set(completed)))
        active.add(value)
        await asyncio.sleep(0.02)
        active.remove(value)
        completed.add(value)
        return {'status': 'completed', 'value': value}

    app.state.gateway.create_response = gateway
    definition = workflow(outer, inner)
    definition['max_concurrency'] = 2
    task = client.post('/api/hexa/tasks', json={'workflow': definition}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'modes'}).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result
    assert all(len(inflight) < 2 for _, inflight, _ in observed)
    if outer == 'serial':
        assert all({'a', 'b'} <= done for value, _, done in observed if value in ('c', 'd'))
    if inner == 'serial':
        assert all(not (inflight & ({'a', 'b'} if value in ('a', 'b') else {'c', 'd'}))
                   for value, inflight, _ in observed)
    target = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    history = client.get(f"/api/hexa/node-runs/{target['id']}").json()['attempts']
    leaves = [row for row in history if row['execution_kind'] == 'foreach_nested_item']
    assert all('outer_item_node_run_id' in row['input'] for row in leaves)


@pytest.mark.parametrize('terminal', [False, True])
@pytest.mark.parametrize('loop', [False, True])
def test_nested_retry_and_resume_reuse_successful_leaves(client, app, terminal, loop):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute source':
            calls.append('source')
            return {'status': 'completed', 'groups': [{'items': ['ok', 'bad', 'late']}, {'items': ['end']}]}
        if context['prompt'] == 'execute check':
            return {'status': 'completed', 'done': bool(context.get('loop_previous'))}
        value = context['foreach_item']
        calls.append(value)
        if value == 'bad' and calls.count('bad') == (2 if loop else 1):
            raise RuntimeError('outcome unknown; retry explicitly')
        return {'status': 'completed', 'value': value}

    app.state.gateway.create_response = gateway
    definition = workflow(hold=not terminal)
    if loop:
        definition['nodes'][1].pop('final_report')
        definition['nodes'].append(node('check', deps=['worker'], inputRefs=['worker'], final_report=True, loop={
            'body': ['worker', 'check'], 'max_iterations': 3,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }))
    task = client.post('/api/hexa/tasks', json={'workflow': definition}).json()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'first'}).json()
    result = wait_run(client, started['id'], {'failed' if terminal else 'waiting_human'})
    target = next(row for row in result['nodes'] if row['node_id'] == 'worker')
    before = client.get(f"/api/hexa/node-runs/{target['id']}").json()['attempts']
    failed = next(row for row in before if row['execution_kind'] == 'foreach_item' and row['status'] == 'failed')
    if terminal:
        response = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
            'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': result['id'],
            'item_node_run_id': failed['id'],
        }, headers={'Idempotency-Key': 'resume'})
        assert response.status_code == 202, response.json()
        run_id = response.json()['id']
    else:
        response = client.post(f"/api/hexa/runs/{result['id']}/nodes/worker/retry", json={
            'item_node_run_id': failed['id'],
        }, headers={'Idempotency-Key': 'retry'})
        assert response.status_code == 200, response.json()
        run_id = result['id']
    for _ in range(300):
        current = client.get(f'/api/hexa/runs/{run_id}').json()
        aggregate = next(row for row in current['nodes'] if row['node_id'] == 'worker')
        if aggregate['status'] == 'succeeded':
            break
        time.sleep(0.01)
    assert aggregate['status'] == 'succeeded', current
    assert calls == ['source', *(['ok', 'bad', 'late', 'end'] if loop else []), 'ok', 'bad', 'bad', 'late', 'end']
    history = client.get(f"/api/hexa/node-runs/{aggregate['id']}").json()['attempts']
    by_id = {row['id']: row for row in history}
    assert all(row['run_id'] == run_id for row in history)
    for row in history:
        state = row['input']
        for key in ('item_node_run_ids', 'nested_item_node_run_ids', 'retry_item_node_run_ids'):
            for identity in state.get(key, []):
                assert identity in by_id
        for key in ('outer_item_node_run_id', 'nested_aggregate_node_run_id', 'control_node_run_id'):
            if key in state:
                assert state[key] in by_id
    if terminal:
        assert client.get(f"/api/hexa/runs/{result['id']}").json() == result
        assert client.get(f"/api/hexa/node-runs/{target['id']}").json()['attempts'] == before
    else:
        assert all(by_id[row['id']] == row for row in before)


@pytest.mark.parametrize('groups', [[], [{'items': []}]])
def test_nested_empty_collections_succeed_without_leaf_calls(client, app, groups):
    authenticated(client)
    async def gateway(text, previous, key, **kwargs):
        assert json.loads(text)['prompt'] == 'execute source'
        return {'status': 'completed', 'groups': groups}
    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': workflow()}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'empty'}).json()
    result = wait_run(client, run['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result
    assert result['nodes'][1]['output'] == {'items': [{'items': []}] if groups else []}


def test_nested_pending_aggregate_reserves_capacity(client, app):
    from tests.test_task_concurrency import seed_run
    run_id = seed_run(app, workflow())
    with app.state.session_factory() as db:
        outer = NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_item',
                        status='running', input_json=encoded({'nested_item_node_run_ids': []}))
        db.add(outer)
        db.flush()
        assert node_record_usage(db, run_id) == db.query(NodeRun).filter_by(run_id=run_id).count() + 1


def test_nested_final_aggregate_output_limit(client, app):
    from tests.test_task_concurrency import seed_run
    run_id = seed_run(app, workflow())
    with app.state.session_factory() as db:
        run = db.get(Run, run_id)
        control = latest_nodes(db, run_id)['worker']
        outer = [NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_item',
                         foreach_index=i, status='succeeded', input_json='{"nested_item_node_run_ids":[]}',
                         output_json=encoded({'items': ['x' * 600000]})) for i in range(2)]
        db.add_all(outer)
        db.flush()
        control.status = 'running'
        control.input_json = encoded({'item_node_run_ids': [row.id for row in outer]})
        advance_fanouts(db, run, workflow(), latest_nodes(db, run_id), encoded=encoded,
                        value_at_path=value_at_path, condition_matches=condition_matches, decisions={})
        db.flush()
        assert latest_nodes(db, run_id)['worker'].status == 'failed'
        assert latest_nodes(db, run_id)['worker'].error_code == 'storage_limit_exceeded'


@pytest.mark.anyio
@pytest.mark.parametrize('action', ['pause', 'cancel', 'recover'])
async def test_nested_control_stops_new_leaf_dispatch_and_records_unknown(client, app, action):
    from app.tasks.service import TaskExecutor
    from tests.test_task_concurrency import seed_run
    run_id = seed_run(app, workflow())
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class Gateway:
        async def create_response(self, text, previous, key, **kwargs):
            context = json.loads(text)
            if context['prompt'] == 'execute source':
                return {'status': 'completed', 'groups': [{'items': ['first', 'later']}]}
            calls.append(context['foreach_item'])
            entered.set()
            await release.wait()
            return {'status': 'completed', 'value': context['foreach_item']}

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
            response = client.post(f'/api/hexa/runs/{run_id}/cancel', headers={'Idempotency-Key': 'cancel-nested'})
            assert response.status_code == 200
        release.set()
        await asyncio.wait_for(asyncio.gather(job, return_exceptions=True), 5)
        assert calls == ['first']
        with app.state.session_factory() as db:
            leaves = db.query(NodeRun).filter_by(run_id=run_id, execution_kind='foreach_nested_item').order_by(NodeRun.id).all()
            assert len(leaves) == 2
            if action == 'pause':
                assert [row.status for row in leaves] == ['succeeded', 'idle']
            else:
                assert leaves[0].status == ('canceled' if action == 'cancel' else 'failed')
                assert leaves[0].error_code == 'interrupted_unknown_outcome'
    finally:
        release.set()
        if not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)


@pytest.mark.parametrize('value,code', [(None, 'nested_foreach_input_invalid'),
                                        ([1, 2, 3, 4], 'nested_foreach_limit_exceeded')])
def test_nested_invalid_values_fail_before_gateway_leaf(client, app, value, code):
    authenticated(client)
    async def gateway(text, previous, key, **kwargs):
        assert json.loads(text)['prompt'] == 'execute source'
        return {'status': 'completed', 'groups': [{'items': value}]}
    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': workflow()}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'invalid'}).json()
    result = wait_run(client, run['id'], {'failed'})
    assert result['nodes'][1]['error_code'] == code
