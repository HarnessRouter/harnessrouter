"""Terminal fanout recovery is an explicit new run with immutable provenance."""
import json

import pytest

from tests.test_task_workflows import authenticated, node, wait_run


@pytest.fixture(params=[('foreach', 'serial'), ('foreach', 'parallel'), ('dynamic_plan', 'serial'), ('dynamic_plan', 'parallel')])
def terminal_collection(client, app, request):
    kind, mode = request.param
    prefix = 'foreach' if kind == 'foreach' else 'dynamic'
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        if context['prompt'] == 'execute source':
            calls.append('source')
            return {'status': 'completed', 'values': ['ok', 'bad', 'late'] if kind == 'foreach' else [
                {'id': value, 'prompt': value} for value in ('ok', 'bad', 'late')
            ]}
        if context['prompt'] == 'execute report':
            calls.append('report')
            return {'status': 'completed', 'items': context['refs'][0]['output']['items']}
        value = context[f'{prefix}_item']
        value = value if kind == 'foreach' else value['id']
        calls.append(value)
        if value == 'bad' and calls.count('bad') == 1:
            raise RuntimeError('unknown outcome')
        return {'status': 'completed', 'value': value}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'input': 'fixed input', 'workflow': {
        'max_concurrency': 1, 'nodes': [node('source'),
            node('worker', deps=['source'], inputRefs=['source'], **{kind: {
                'source': 'source', 'path': 'values', 'max_items': 3, 'mode': mode,
            }}), node('report', deps=['worker'], inputRefs=['worker'], final_report=True),
        ],
    }}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'first-failed'}).json()
    failed = wait_run(client, run['id'], {'failed'})
    worker = next(row for row in failed['nodes'] if row['node_id'] == 'worker')
    history = client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts']
    item = next(row for row in history if row['execution_kind'] in ('foreach_item', 'dynamic_item') and row['status'] == 'failed')
    return task, failed, history, item, calls


def test_terminal_item_resume_reuses_successes_in_a_new_run(client, terminal_collection):
    task, failed, history, item, calls = terminal_collection
    body = {'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': failed['id'],
            'item_node_run_id': item['id']}
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", json=body,
                          headers={'Idempotency-Key': 'resume-item'})
    assert started.status_code == 202
    resumed = wait_run(client, started.json()['id'], {'completed', 'failed'})
    assert resumed['status'] == 'completed'
    assert calls == ['source', 'ok', 'bad', 'bad', 'late', 'report']
    assert resumed['id'] != failed['id']
    assert resumed['execution_snapshot']['resume']['source_run_id'] == failed['id']
    assert resumed['workflow_revision_id'] == failed['workflow_revision_id']
    assert client.get(f"/api/hexa/runs/{failed['id']}").json() == failed
    worker = next(row for row in failed['nodes'] if row['node_id'] == 'worker')
    assert client.get(f"/api/hexa/node-runs/{worker['id']}").json()['attempts'] == history
    aggregate = next(row for row in resumed['nodes'] if row['node_id'] == 'worker')
    assert aggregate['output']['items'] == [{'status': 'completed', 'value': v} for v in ('ok', 'bad', 'late')]
    new_history = client.get(f"/api/hexa/node-runs/{aggregate['id']}").json()['attempts']
    assert all(row['run_id'] == resumed['id'] for row in new_history)
    assert any(row['input'].get('reused_from') == history[1]['id'] for row in new_history)
    replay = client.post(f"/api/hexa/tasks/{task['id']}/runs", json=body,
                         headers={'Idempotency-Key': 'resume-item'})
    assert replay.status_code == 200
    assert replay.json()['id'] == resumed['id']
    assert calls == ['source', 'ok', 'bad', 'bad', 'late', 'report']


@pytest.mark.parametrize('alteration', ['input', 'revision', 'other_task', 'success_item', 'reuse_refs', 'normal_kind', 'active_source', 'agent_config'])
def test_invalid_resume_does_not_create_run(client, app, terminal_collection, alteration):
    task, failed, history, item, calls = terminal_collection
    body = {'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': failed['id'],
            'item_node_run_id': item['id']}
    if alteration == 'input':
        result = client.put(f"/api/hexa/tasks/{task['id']}/input", json={'input': 'changed', 'expected_input': 'fixed input'})
        assert result.status_code == 200
    elif alteration == 'revision':
        assert client.put(f"/api/hexa/tasks/{task['id']}/workflow", json={
            'workflow': task['workflow'], 'expected_revision': 1,
        }).status_code == 200
    elif alteration == 'other_task':
        task = client.post('/api/hexa/tasks', json={'workflow': task['workflow']}).json()
    elif alteration == 'success_item':
        body['item_node_run_id'] = next(row['id'] for row in history if row['execution_kind'] in ('foreach_item', 'dynamic_item') and row['status'] == 'succeeded')
    elif alteration == 'reuse_refs':
        body['reuse_refs'] = [next(row['id'] for row in failed['nodes'] if row['node_id'] == 'source')]
    elif alteration == 'normal_kind':
        body['kind'] = 'normal'
    elif alteration == 'active_source':
        from app.db.models import Run
        with app.state.session_factory() as db:
            db.get(Run, failed['id']).status = 'waiting_human'
            db.commit()
    elif alteration == 'agent_config':
        from app.db.models import Run
        with app.state.session_factory() as db:
            prior = db.get(Run, failed['id'])
            snapshot = json.loads(prior.snapshot_json)
            snapshot['agents']['agent-1']['system_prompt'] = 'old configuration'
            prior.snapshot_json = json.dumps(snapshot)
            db.commit()
    before = client.get(f"/api/hexa/tasks/{task['id']}/runs").json()['runs']
    result = client.post(f"/api/hexa/tasks/{task['id']}/runs", json=body,
                         headers={'Idempotency-Key': 'invalid-resume'})
    assert result.status_code == (404 if alteration == 'other_task' else 409 if alteration in ('input', 'revision', 'active_source', 'agent_config') else 422), result.json()
    assert client.get(f"/api/hexa/tasks/{task['id']}/runs").json()['runs'] == before
    assert calls == ['source', 'ok', 'bad']


@pytest.mark.parametrize('gated', [False, True])
def test_loop_resume_keeps_round_and_requires_new_human_decision(client, app, gated):
    authenticated(client)
    calls = []

    async def gateway(text, previous, key, **kwargs):
        context = json.loads(text)
        calls.append(context)
        if context['prompt'] == 'execute source':
            return {'status': 'completed', 'values': [1]}
        if context['prompt'] == 'execute check':
            return {'status': 'completed', 'done': bool(context.get('loop_previous'))}
        if context.get('loop_previous') and sum(c['prompt'] == 'execute worker' for c in calls) == 2:
            raise RuntimeError('unknown in second round')
        return {'status': 'completed', 'value': context['foreach_item']}

    app.state.gateway.create_response = gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {'nodes': [node('source'),
        node('worker', deps=['source'], inputRefs=['source'], requires_human=gated, foreach={
            'source': 'source', 'path': 'values', 'max_items': 1,
        }), node('check', deps=['worker'], inputRefs=['worker'], loop={
            'body': ['worker', 'check'], 'max_iterations': 3,
            'until': {'source': 'check', 'path': 'done', 'op': 'eq', 'value': True},
        }, final_report=True),
    ]}}).json()
    first = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'loop-first'}).json()
    if gated:
        for iteration in (1, 2):
            assert wait_run(client, first['id'], {'waiting_human', 'failed'})['status'] == 'waiting_human'
            assert client.post(f"/api/hexa/runs/{first['id']}/continue", json={
                'node_id': 'worker', 'input_refs': ['source'],
            }, headers={'Idempotency-Key': f'confirm-{iteration}'}).status_code == 200
    failed = wait_run(client, first['id'], {'failed'})
    target = next(row for row in failed['nodes'] if row['node_id'] == 'worker')
    assert target['iteration'] == 2
    history = client.get(f"/api/hexa/node-runs/{target['id']}").json()['attempts']
    item = next(row for row in history if row['execution_kind'] == 'foreach_item' and row['iteration'] == 2)
    resumed = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
        'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': failed['id'],
        'item_node_run_id': item['id'],
    }, headers={'Idempotency-Key': 'loop-resume'})
    assert resumed.status_code == 202, resumed.json()
    if gated:
        count = len(calls)
        waiting = wait_run(client, resumed.json()['id'], {'waiting_human', 'completed', 'failed'})
        assert waiting['status'] == 'waiting_human'
        assert waiting['decisions'] == []
        assert len(calls) == count
        assert client.post(f"/api/hexa/runs/{waiting['id']}/continue", json={
            'node_id': 'worker', 'input_refs': ['source'],
        }, headers={'Idempotency-Key': 'confirm-new-run'}).status_code == 200
    completed = wait_run(client, resumed.json()['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed
    current = next(row for row in completed['nodes'] if row['node_id'] == 'worker')
    assert current['iteration'] == 2
    assert len([c for c in calls if c['prompt'] == 'execute source']) == 1
    assert len([c for c in calls if c['prompt'] == 'execute worker']) == 3
    assert calls[-2]['loop_previous']['iteration'] == 1
    assert client.get(f"/api/hexa/runs/{failed['id']}").json() == failed


def test_canceled_source_can_resume_all_failed_items(client, app, terminal_collection):
    from app.db.models import Run
    task, failed, history, item, calls = terminal_collection
    with app.state.session_factory() as db:
        db.get(Run, failed['id']).status = 'canceled'
        db.commit()
    result = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
        'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': failed['id'],
    }, headers={'Idempotency-Key': 'canceled-resume'})
    assert result.status_code == 202
    assert wait_run(client, result.json()['id'], {'completed', 'failed'})['status'] == 'completed'
    assert calls == ['source', 'ok', 'bad', 'bad', 'late', 'report']
    assert client.get(f"/api/hexa/runs/{failed['id']}").json()['status'] == 'canceled'


def test_fanout_manifest_copy_cannot_cross_record_budget(client, app):
    from app.db.models import NodeRun, Run
    from app.tasks.service import encoded
    from app.tasks.resume import seed_resume
    from app.tasks.service import TaskError, downstream_nodes
    from tests.test_task_concurrency import seed_run
    workflow = {'nodes': [node('worker', foreach={'source': 'source', 'path': 'values', 'max_items': 1}), node('source')]}
    source_id = seed_run(app, workflow)
    target_id = seed_run(app, workflow)
    with app.state.session_factory() as db:
        source, target = db.get(Run, source_id), db.get(Run, target_id)
        from app.tasks.service import latest_nodes
        rows = latest_nodes(db, source_id)
        rows['worker'].status = 'failed'
        rows['source'].status, rows['source'].output_json = 'succeeded', '{"values":[1]}'
        item = NodeRun(run_id=source_id, node_id='worker', execution_kind='foreach_item',
                       foreach_index=0, status='failed', input_json='{"foreach_item":1}')
        db.add(item)
        db.flush()
        rows['worker'].input_json = encoded({'item_node_run_ids': [item.id]})
        db.add_all(NodeRun(run_id=target_id, node_id='source', iteration=0, status='succeeded') for _ in range(496))
        db.flush()
        with pytest.raises(TaskError) as failure:
            seed_resume(db, target, (source, rows, workflow['nodes'][0], rows['worker'], [item]), {},
                        encoded=encoded, downstream_nodes=downstream_nodes, error=TaskError)
        assert failure.value.code == 'storage_limit_exceeded'
        db.rollback()


def test_resume_body_requires_typed_source_and_item_identity(client, terminal_collection):
    task, failed, _, item, calls = terminal_collection
    for invalid in ({'resume_from_run_id': True}, {'resume_from_run_id': str(failed['id'])},
                    {'item_node_run_id': '3'}, {'agent_id': 'injected'}):
        body = {'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': failed['id'],
                'item_node_run_id': item['id'], **invalid}
        response = client.post(f"/api/hexa/tasks/{task['id']}/runs", json=body,
                               headers={'Idempotency-Key': 'invalid-types'})
        assert response.status_code == 422
    assert len(client.get(f"/api/hexa/tasks/{task['id']}/runs").json()['runs']) == 1
    assert calls == ['source', 'ok', 'bad']


def test_unrelated_unknown_failure_is_not_replayed(client, app, terminal_collection):
    from app.db.models import NodeRun, Run
    task, failed, history, item, calls = terminal_collection
    # Add an independent failed node to the saved fixture's definition and
    # source snapshot, representing a previously persisted uncertain call.
    with app.state.session_factory() as db:
        from app.db.models import WorkflowRevision
        source = db.get(Run, failed['id'])
        snapshot = json.loads(source.snapshot_json)
        snapshot['workflow']['nodes'].append(node('unrelated'))
        source.snapshot_json = json.dumps(snapshot)
        revision = db.get(WorkflowRevision, source.workflow_revision_id)
        revision.definition_json = json.dumps(snapshot['workflow'])
        db.add(NodeRun(run_id=source.id, node_id='unrelated', status='failed',
                       error_code='interrupted_unknown_outcome', input_json='{}'))
        db.commit()
    started = client.post(f"/api/hexa/tasks/{task['id']}/runs", json={
        'kind': 'rerun', 'target_node': 'worker', 'resume_from_run_id': failed['id'],
    }, headers={'Idempotency-Key': 'unrelated-resume'})
    assert started.status_code == 202
    result = wait_run(client, started.json()['id'], {'completed', 'failed'})
    assert result['status'] == 'failed'
    assert next(row for row in result['nodes'] if row['node_id'] == 'unrelated')['error_code'] == 'interrupted_unknown_outcome'
    assert next(row for row in result['nodes'] if row['node_id'] == 'worker')['status'] == 'succeeded'
    assert calls == ['source', 'ok', 'bad', 'bad', 'late', 'report']


def test_restored_successful_aggregate_keeps_local_item_provenance(client, app):
    from app.db.models import NodeRun, Run, Task
    from app.tasks.service import encoded, latest_nodes, downstream_nodes, TaskError
    from app.tasks.resume import seed_resume
    workflow = {'nodes': [node('source'),
        node('first', deps=['source'], foreach={'source': 'source', 'path': 'values', 'max_items': 1}),
        node('second', deps=['first'], foreach={'source': 'first', 'path': 'items', 'max_items': 1})]}
    from tests.test_task_concurrency import seed_run
    source_id, target_id = seed_run(app, workflow), seed_run(app, workflow)
    with app.state.session_factory() as db:
        rows = latest_nodes(db, source_id)
        rows['source'].status, rows['source'].output_json = 'succeeded', '{"values":[1]}'
        first_item = NodeRun(run_id=source_id, node_id='first', execution_kind='foreach_item', foreach_index=0,
                             status='succeeded', input_json='{"foreach_item":1}', output_json='{"value":1}')
        db.add(first_item)
        db.flush()
        rows['first'].status = 'succeeded'
        rows['first'].input_json = encoded({'item_node_run_ids': [first_item.id]})
        aggregate = NodeRun(run_id=source_id, node_id='first', execution_kind='foreach_aggregate',
                            status='succeeded', input_json=encoded({'control_node_run_id': rows['first'].id,
                            'item_node_run_ids': [first_item.id]}), output_json='{"items":[{"value":1}]}')
        second_item = NodeRun(run_id=source_id, node_id='second', execution_kind='foreach_item', foreach_index=0,
                             status='failed', input_json='{"foreach_item":{"value":1}}')
        db.add_all([aggregate, second_item])
        db.flush()
        rows['first'] = aggregate
        rows['second'].status = 'failed'
        rows['second'].input_json = encoded({'item_node_run_ids': [second_item.id]})
        seed_resume(db, db.get(Run, target_id), (db.get(Run, source_id), rows, workflow['nodes'][2], rows['second'], [second_item]),
                    {}, encoded=encoded, downstream_nodes=downstream_nodes, error=TaskError)
        restored = latest_nodes(db, target_id)['first']
        assert restored.execution_kind == 'foreach_aggregate'
        state = json.loads(restored.input_json)
        assert 'item_node_run_ids' in state
        assert db.get(NodeRun, state['item_node_run_ids'][0]).run_id == target_id
        assert db.get(NodeRun, state['control_node_run_id']).run_id == target_id
