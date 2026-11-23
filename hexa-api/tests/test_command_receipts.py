"""CommandReceipt records the durable boundary around one Agent side effect."""

import time

from app.gateway.client import GatewayError
from tests.test_task_workflows import authenticated, node, wait_run


def test_completed_node_exposes_a_stable_command_receipt(client, app):
    authenticated(client)
    task = client.post('/api/hexa/tasks', json={'workflow': {
        'nodes': [node('worker', final_report=True)],
    }}).json()
    started = client.post(
        f"/api/hexa/tasks/{task['id']}/runs",
        headers={'Idempotency-Key': 'receipt-success'},
    ).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'completed', result

    worker = result['nodes'][0]
    receipt = worker['command_receipt']
    assert receipt['command_id'] == f"hexa-task-{started['id']}-{worker['id']}"
    assert len(receipt['request_hash']) == 64
    assert receipt['side_effect_state'] == 'completed'
    assert receipt['reconciliation_required'] is False
    assert receipt['response_id'] == worker['response_id']
    assert 'input' not in receipt
    assert 'secret' not in receipt

    detail = client.get(f"/api/hexa/node-runs/{worker['id']}")
    assert detail.status_code == 200
    assert detail.json()['command_receipt'] == receipt


def test_uncertain_gateway_result_creates_unknown_receipt_without_replay(client, app):
    authenticated(client)

    async def uncertain_gateway(*args, **kwargs):
        raise GatewayError('connection interrupted', uncertain=True, response_id='resp-uncertain')

    app.state.gateway.create_response = uncertain_gateway
    task = client.post('/api/hexa/tasks', json={'workflow': {
        'nodes': [node('worker', final_report=True)],
    }}).json()
    started = client.post(
        f"/api/hexa/tasks/{task['id']}/runs",
        headers={'Idempotency-Key': 'receipt-unknown'},
    ).json()
    result = wait_run(client, started['id'], {'completed', 'failed'})
    assert result['status'] == 'failed', result
    worker = result['nodes'][0]
    receipt = worker['command_receipt']
    assert receipt['side_effect_state'] == 'unknown'
    assert receipt['reconciliation_required'] is True
    assert receipt['response_id'] == 'resp-uncertain'

    time.sleep(0.05)
    assert len(app.state.gateway.calls) == 0


def test_recovery_marks_started_receipt_unknown(client, app):
    from app.db.models import CommandReceipt, NodeRun, Run, Task
    from app.tasks.service import TaskExecutor, encoded

    with app.state.session_factory() as db:
        task = Task(user_id=1, title='recovery receipt')
        db.add(task)
        db.flush()
        run = Run(task_id=task.id, workflow_revision=1, status='running',
                  snapshot_json=encoded({'workflow': {'nodes': []}, 'input': ''}))
        db.add(run)
        db.flush()
        node_run = NodeRun(run_id=run.id, node_id='worker', status='running')
        db.add(node_run)
        db.flush()
        db.add(CommandReceipt(node_run_id=node_run.id, command_id=f'hexa-task-{run.id}-{node_run.id}',
                              request_hash='a' * 64, side_effect_state='started'))
        db.commit()
        run_id = run.id

    TaskExecutor(app.state.session_factory, app.state.gateway).recover()
    with app.state.session_factory() as db:
        receipt = db.query(CommandReceipt).filter_by(node_run_id=node_run.id).one()
        assert receipt.side_effect_state == 'unknown'
        assert receipt.reconciliation_required is True
