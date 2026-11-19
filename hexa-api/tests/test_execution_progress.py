import asyncio
import json

import pytest
from sqlalchemy import select

from app.db.models import Conversation, IdempotencyRequest, NodeRun, Run, Task
from app.tasks.service import TaskExecutor


def test_running_conversation_restores_current_progress(client, app):
    assert client.post('/api/hexa/auth/login', json={'username': 'admin', 'password': 'correct-password'}).status_code == 200
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    with app.state.session_factory() as db:
        db.get(Conversation, cid).response_status = 'running'
        db.add(IdempotencyRequest(user_id=1, conversation_id=cid, key='live', request_hash='x', status='pending',
                                  partial_text='已收到的文本', response_id='resp-live',
                                  execution_json=json.dumps({'reasoning': '公开摘要', 'steps': []})))
        db.commit()
    live = client.get(f'/api/hexa/conversations/{cid}').json()['progress']
    assert live['text'] == '已收到的文本'
    assert live['response_id'] == 'resp-live'
    assert live['execution']['reasoning'] == '公开摘要'


@pytest.mark.anyio
async def test_parallel_node_progress_survives_failure_and_rejects_late_callbacks(app, client):
    secret = 'canary-progress-secret-123456'
    ready = asyncio.Event()
    release = asyncio.Event()
    callbacks = []
    class Gateway:
        async def create_response(self, text, previous, key, **kwargs):
            assert previous is None
            callbacks.append(kwargs)
            await kwargs['on_progress'](key, f'部分回答 {key} {secret}')
            await kwargs['on_execution']({'reasoning': f'公开摘要 {secret}', 'steps': [{'id': 'call', 'name': 'search', 'status': 'in_progress'}]})
            if len(callbacks) == 2:
                ready.set()
            await release.wait()
            raise RuntimeError('connection lost')
    with app.state.session_factory() as db:
        task = Task(user_id=1, title='progress')
        db.add(task); db.flush()
        run = Run(task_id=task.id, workflow_revision=1, status='running')
        db.add(run); db.flush()
        rows = [NodeRun(run_id=run.id, node_id=name, status='running') for name in ('a', 'b')]
        db.add_all(rows); db.commit()
        run_id, ids = run.id, [row.id for row in rows]
    executor = TaskExecutor(app.state.session_factory, Gateway(), (secret,))
    item = {'agent_id': 'agent-1', 'model': 'gpt-6.1'}
    jobs = [asyncio.create_task(executor.execute_node(run_id, id, item, {}, '')) for id in ids]
    try:
        await asyncio.wait_for(ready.wait(), 3)
        with app.state.session_factory() as db:
            from app.tasks.service import node_json
            snapshots = [node_json(db.get(NodeRun, id)) for id in ids]
        assert all(row['progress']['text'].startswith('部分回答') for row in snapshots)
        assert snapshots[0]['response_id'] != snapshots[1]['response_id']
        assert secret not in json.dumps(snapshots)
        assert all(row['output'] is None for row in snapshots)
    finally:
        release.set()
        await asyncio.gather(*jobs)
    with app.state.session_factory() as db:
        before = [node_json(db.get(NodeRun, id)) for id in ids]
    for callback in callbacks:
        await callback['on_progress']('late', 'late')
        await callback['on_execution']({'reasoning': 'late', 'steps': []})
    with app.state.session_factory() as db:
        after = [node_json(db.get(NodeRun, id)) for id in ids]
    assert before == after
    assert all(row['status'] == 'failed' and row['progress']['text'] for row in after)
