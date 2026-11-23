"""RunEvent is the append-only execution fact stream for task orchestration."""
import time

from sqlalchemy import inspect, select, text

from app.db.models import RunEvent, create_session_factory
from tests.test_task_workflows import authenticated, node, wait_run


def test_run_event_log_records_lifecycle_in_order(client, app):
    authenticated(client)
    task = client.post('/api/hexa/tasks', json={'workflow': {
        'nodes': [node('worker', final_report=True)],
    }}).json()
    started = client.post(
        f"/api/hexa/tasks/{task['id']}/runs",
        headers={'Idempotency-Key': 'run-event-lifecycle'},
    ).json()
    completed = wait_run(client, started['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed

    for _ in range(20):
        response = client.get(f"/api/hexa/runs/{started['id']}/event-log?offset=0&limit=50")
        if response.status_code == 200:
            break
        time.sleep(0.01)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['pagination'] == {'offset': 0, 'limit': 50, 'has_more': False}
    types = [event['event_type'] for event in body['events']]
    assert types[:4] == ['run.created', 'node.dispatched', 'node.succeeded', 'run.completed']
    assert all(event['run_id'] == started['id'] for event in body['events'])
    assert all(event['id'] < body['events'][index + 1]['id'] for index, event in enumerate(body['events'][:-1]))


def test_run_event_log_paginates_without_replacing_event_facts(client, app):
    authenticated(client)
    task = client.post('/api/hexa/tasks', json={'workflow': {
        'nodes': [node('worker', final_report=True)],
    }}).json()
    started = client.post(
        f"/api/hexa/tasks/{task['id']}/runs",
        headers={'Idempotency-Key': 'run-event-pagination'},
    ).json()
    wait_run(client, started['id'], {'completed', 'failed'})
    first = client.get(f"/api/hexa/runs/{started['id']}/event-log?offset=0&limit=2")
    second = client.get(f"/api/hexa/runs/{started['id']}/event-log?offset=2&limit=2")
    assert first.status_code == second.status_code == 200
    assert first.json()['pagination']['has_more'] is True
    assert [event['id'] for event in first.json()['events']] == [1, 2]
    assert [event['id'] for event in second.json()['events']] == [3, 4]
    assert first.json()['events'][0]['event_type'] == 'run.created'
    assert second.json()['events'][-1]['event_type'] == 'run.completed'


def test_idempotent_pause_replay_does_not_append_duplicate_fact(client, app):
    authenticated(client)

    async def slow_gateway(text, previous, key, **kwargs):
        await __import__('asyncio').sleep(0.15)
        return {'status': 'completed', 'text': 'done'}

    app.state.gateway.create_response = slow_gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {
        'nodes': [node('worker', final_report=True)],
    }}).json()
    started = client.post(
        f"/api/hexa/tasks/{task['id']}/runs",
        headers={'Idempotency-Key': 'run-event-pause'},
    ).json()
    time.sleep(0.02)

    first = client.post(
        f"/api/hexa/runs/{started['id']}/pause",
        headers={'Idempotency-Key': 'pause-once'},
    )
    replay = client.post(
        f"/api/hexa/runs/{started['id']}/pause",
        headers={'Idempotency-Key': 'pause-once'},
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()

    events = client.get(f"/api/hexa/runs/{started['id']}/event-log?offset=0&limit=50").json()['events']
    assert [event['event_type'] for event in events].count('run.paused') == 1


def test_existing_sqlite_database_gains_run_event_table_and_can_append(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy-without-run-events.db'}"
    engine = __import__('sqlalchemy').create_engine(url)
    with engine.begin() as db:
        db.execute(text('CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)'))
        db.execute(text("INSERT INTO tasks (id, title) VALUES (71, 'retained task')"))
    engine.dispose()

    factory = create_session_factory(url)
    try:
        assert 'run_events' in inspect(factory.kw['bind']).get_table_names()
        with factory() as db:
            db.execute(text("INSERT INTO task_runs (id, task_id, workflow_revision, status, kind, snapshot_json, request_hash, paused) VALUES (91, 71, 1, 'running', 'normal', '{}', '', 0)"))
            db.add(RunEvent(run_id=91, event_type='run.recovered_unknown', event_json='{"reason":"test"}'))
            db.commit()
            event = db.scalar(select(RunEvent).where(RunEvent.run_id == 91))
            assert event is not None
            assert event.event_type == 'run.recovered_unknown'
    finally:
        factory.kw['bind'].dispose()
