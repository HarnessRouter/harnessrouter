"""Unknown Agent outcomes can be reconciled by reading an existing response only."""

import asyncio

from app.gateway.client import GatewayError
from tests.test_task_workflows import authenticated, node, wait_run


def _unknown_run(client, app, key='reconcile-start'):
    async def interrupted(*args, **kwargs):
        raise GatewayError('connection interrupted', uncertain=True, response_id='resp-reconcile')

    app.state.gateway.create_response = interrupted
    task = client.post('/api/hexa/tasks', json={'workflow': {
        'nodes': [node('worker', final_report=True)],
    }}).json()
    started = client.post(
        f"/api/hexa/tasks/{task['id']}/runs",
        headers={'Idempotency-Key': key},
    ).json()
    result = wait_run(client, started['id'], {'failed', 'completed'})
    worker = result['nodes'][0]
    assert result['status'] == 'failed'
    assert worker['command_receipt']['side_effect_state'] == 'unknown'
    return started['id'], worker['id']


def test_reconcile_running_response_keeps_unknown_without_replay(client, app):
    authenticated(client)
    run_id, node_run_id = _unknown_run(client, app, 'reconcile-running')
    calls = []

    async def read_response(response_id):
        calls.append(response_id)
        return {'id': response_id, 'status': 'running'}

    app.state.gateway.get_response = read_response
    response = client.post(
        f'/api/hexa/runs/{run_id}/nodes/{node_run_id}/reconcile',
        headers={'Idempotency-Key': 'reconcile-running-once'},
    )
    assert response.status_code == 202
    assert response.json()['side_effect_state'] == 'unknown'
    assert calls == ['resp-reconcile']


def test_reconcile_completed_response_projects_result_without_create_call(client, app):
    authenticated(client)
    run_id, node_run_id = _unknown_run(client, app, 'reconcile-completed')
    reads = []

    async def read_response(response_id):
        reads.append(response_id)
        return {
            'id': response_id,
            'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'recovered output'}]}],
        }

    app.state.gateway.get_response = read_response
    response = client.post(
        f'/api/hexa/runs/{run_id}/nodes/{node_run_id}/reconcile',
        headers={'Idempotency-Key': 'reconcile-completed-once'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body['side_effect_state'] == 'completed'
    assert body['reconciliation_required'] is False

    run = client.get(f'/api/hexa/runs/{run_id}').json()
    worker = next(row for row in run['nodes'] if row['id'] == node_run_id)
    assert worker['status'] == 'succeeded'
    assert worker['output']['text'] == 'recovered output'
    assert reads == ['resp-reconcile']

    replay = client.post(
        f'/api/hexa/runs/{run_id}/nodes/{node_run_id}/reconcile',
        headers={'Idempotency-Key': 'reconcile-completed-once'},
    )
    assert replay.status_code == 200
    assert replay.json() == body
    assert reads == ['resp-reconcile']


def test_reconcile_gateway_read_failure_keeps_unknown(client, app):
    authenticated(client)
    run_id, node_run_id = _unknown_run(client, app, 'reconcile-failure')

    async def unavailable(response_id):
        raise GatewayError('read unavailable', uncertain=True, response_id=response_id)

    app.state.gateway.get_response = unavailable
    response = client.post(
        f'/api/hexa/runs/{run_id}/nodes/{node_run_id}/reconcile',
        headers={'Idempotency-Key': 'reconcile-failure-once'},
    )
    assert response.status_code == 202
    assert response.json()['side_effect_state'] == 'unknown'
