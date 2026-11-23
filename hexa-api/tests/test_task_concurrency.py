import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.db.models import NodeRun, Run, Task
from app.tasks.service import TaskError, TaskExecutor, encoded, latest_nodes, workflow_from_json


def definition(limit=None):
    workflow = {'nodes': [
        {'id': name, 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'prompt': name}
        for name in ('a', 'b', 'c', 'd', 'e')
    ]}
    workflow['nodes'].append({'id': 'summary', 'agent_id': 'agent-1', 'model': 'gpt-6.1',
                              'prompt': 'summary', 'deps': ['a', 'b', 'c', 'd', 'e'],
                              'inputRefs': ['a', 'b', 'c', 'd', 'e'], 'final_report': True})
    if limit is not None:
        workflow['max_concurrency'] = limit
    return workflow


@pytest.mark.parametrize('value', [0, -1, 51, True, False, '2', 2.0, None, [], {}])
def test_workflow_rejects_invalid_concurrency(value):
    workflow = definition()
    workflow['max_concurrency'] = value
    with pytest.raises(TaskError) as failure:
        workflow_from_json(workflow)
    assert failure.value.code == 'invalid_workflow'
    assert failure.value.status == 422


@pytest.mark.parametrize('value', [1, 2, 50])
def test_workflow_accepts_concurrency(value):
    workflow_from_json(definition(value))


class ControlledGateway:
    def __init__(self):
        self.started = asyncio.Queue()
        self.releases = {name: asyncio.Event() for name in ('a', 'b', 'c', 'd', 'e', 'summary')}
        self.active = set()
        self.peak = 0
        self.calls = []
        self.fail = set()

    async def create_response(self, text, previous, key, **kwargs):
        context = json.loads(text)
        name = context['prompt']
        self.active.add(name)
        self.peak = max(self.peak, len(self.active))
        self.calls.append((name, context))
        self.started.put_nowait(name)
        try:
            await self.releases[name].wait()
            if name in self.fail:
                raise RuntimeError('outcome unknown')
            return {'status': 'completed', 'text': name}
        finally:
            self.active.remove(name)

    def release_all(self):
        for event in self.releases.values():
            event.set()


def seed_run(app, workflow):
    with app.state.session_factory() as db:
        task = Task(user_id=1, title='bounded DAG')
        db.add(task)
        db.flush()
        run = Run(task_id=task.id, workflow_revision=1,
                  snapshot_json=encoded({'workflow': workflow, 'input': ''}))
        db.add(run)
        db.flush()
        db.add_all(NodeRun(run_id=run.id, node_id=item['id']) for item in workflow['nodes'])
        db.commit()
        return run.id


@pytest.fixture()
def started_app(app):
    with TestClient(app):
        yield app


async def started_batch(gateway, count):
    return [await asyncio.wait_for(gateway.started.get(), 3) for _ in range(count)]


@pytest.mark.anyio
@pytest.mark.parametrize('limit', [1, 2, None])
async def test_bounded_batches_keep_unstarted_nodes_idle_and_join_inputs(started_app, limit):
    workflow = definition(limit)
    run_id = seed_run(started_app, workflow)
    gateway = ControlledGateway()
    executor = TaskExecutor(started_app.state.session_factory, gateway)
    job = asyncio.create_task(executor.execute(run_id))
    cap = limit or 50
    try:
        names = ['a', 'b', 'c', 'd', 'e']
        for offset in range(0, 5, cap):
            batch = names[offset:offset + cap]
            assert await started_batch(gateway, len(batch)) == batch
            with started_app.state.session_factory() as db:
                rows = latest_nodes(db, run_id)
                assert {name for name, row in rows.items() if row.status == 'running'} == set(batch)
                for name in names[offset + cap:] + ['summary']:
                    assert rows[name].status == 'idle'
                    assert rows[name].started_at is None
            assert gateway.active == set(batch)
            for name in batch:
                gateway.releases[name].set()
        assert await started_batch(gateway, 1) == ['summary']
        refs = gateway.calls[-1][1]['refs']
        assert [ref['node_id'] for ref in refs] == names
        assert all(ref['output']['text'] == ref['node_id'] for ref in refs)
        gateway.releases['summary'].set()
        await asyncio.wait_for(job, 3)
        assert gateway.peak == min(cap, 5)
        with started_app.state.session_factory() as db:
            assert db.get(Run, run_id).status == 'completed'
    finally:
        gateway.release_all()
        await asyncio.wait_for(job, 3)


@pytest.mark.anyio
async def test_cancel_does_not_dispatch_remaining_batch(started_app):
    run_id = seed_run(started_app, definition(2))
    gateway = ControlledGateway()
    job = asyncio.create_task(TaskExecutor(started_app.state.session_factory, gateway).execute(run_id))
    try:
        assert await started_batch(gateway, 2) == ['a', 'b']
        with started_app.state.session_factory() as db:
            run = db.get(Run, run_id)
            run.status = 'canceled'
            for row in latest_nodes(db, run_id).values():
                row.status = 'canceled'
            db.commit()
        gateway.release_all()
        await asyncio.wait_for(job, 3)
        assert [name for name, _ in gateway.calls] == ['a', 'b']
        with started_app.state.session_factory() as db:
            assert all(row.output_json is None for row in latest_nodes(db, run_id).values())
    finally:
        gateway.release_all()
        await asyncio.wait_for(job, 3)


@pytest.mark.anyio
async def test_failure_keeps_required_join_unstarted(started_app):
    run_id = seed_run(started_app, definition(2))
    gateway = ControlledGateway()
    gateway.fail.add('a')
    gateway.release_all()
    await TaskExecutor(started_app.state.session_factory, gateway).execute(run_id)
    assert gateway.peak <= 2
    assert [name for name, _ in gateway.calls] == ['a', 'b', 'c', 'd', 'e']
    with started_app.state.session_factory() as db:
        assert db.get(Run, run_id).status == 'failed'
        rows = latest_nodes(db, run_id)
        assert rows['a'].error_code == 'interrupted_unknown_outcome'
        assert rows['summary'].status == 'idle'
        assert rows['summary'].output_json is None


def login(client):
    assert client.post('/api/hexa/auth/login', json={
        'username': 'admin', 'password': 'correct-password',
    }).status_code == 200


@pytest.mark.parametrize('value', [0, 51, True, '2', 1.5, None])
def test_api_invalid_concurrency_does_not_save_revision(client, value):
    login(client)
    workflow = definition()
    workflow['max_concurrency'] = value
    assert client.post('/api/hexa/tasks', json={'workflow': workflow}).status_code == 422
    task = client.post('/api/hexa/tasks', json={'workflow': definition(2)}).json()
    response = client.put(f"/api/hexa/tasks/{task['id']}/workflow", json={
        'expected_revision': 1, 'workflow': workflow,
    })
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_workflow'
    fetched = client.get(f"/api/hexa/tasks/{task['id']}").json()
    assert fetched['current_revision'] == 1
    assert fetched['workflow']['max_concurrency'] == 2
