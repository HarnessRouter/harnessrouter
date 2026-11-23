"""Run leases prevent stale task executors from committing late results."""

from datetime import datetime, timedelta, timezone

from app.db.models import Run, Task
from app.tasks.service import TaskExecutor, encoded
from app.db.models import CommandReceipt, NodeRun, RunEvent
import asyncio
import pytest


def _seed_active_run(app):
    with app.state.session_factory() as db:
        task = Task(user_id=1, title='leased run')
        db.add(task)
        db.flush()
        run = Run(task_id=task.id, workflow_revision=1, status='running',
                  snapshot_json=encoded({'workflow': {'nodes': []}, 'input': ''}))
        db.add(run)
        db.commit()
        return run.id


def test_second_executor_cannot_take_a_fresh_run_lease(app, client):
    run_id = _seed_active_run(app)
    first = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='executor-a')
    second = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='executor-b')

    with app.state.session_factory() as db:
        assert first.acquire_run_lease(db, run_id) == 1
        db.commit()
        assert second.acquire_run_lease(db, run_id) is None
        db.rollback()
        run = db.get(Run, run_id)
        assert run.lease_owner == 'executor-a'
        assert run.lease_fence == 1


def test_expired_lease_gets_a_new_fence_and_stale_owner_cannot_renew(app, client):
    run_id = _seed_active_run(app)
    first = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='executor-a')
    second = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='executor-b')

    with app.state.session_factory() as db:
        assert first.acquire_run_lease(db, run_id) == 1
        db.commit()
        run = db.get(Run, run_id)
        run.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        assert second.acquire_run_lease(db, run_id) == 2
        db.commit()
        assert first.renew_run_lease(db, run_id, 1) is False
        db.rollback()
        run = db.get(Run, run_id)
        assert run.lease_owner == 'executor-b'
        assert run.lease_fence == 2


def test_completed_run_releases_lease(app, client):
    run_id = _seed_active_run(app)
    executor = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='executor-a')
    with app.state.session_factory() as db:
        fence = executor.acquire_run_lease(db, run_id)
        db.commit()
        assert fence == 1
        assert executor.release_run_lease(db, run_id, fence) is True
        db.commit()
        run = db.get(Run, run_id)
        assert run.lease_owner is None
        assert run.lease_fence == 1


def test_startup_recovery_preserves_another_live_executor(app, client):
    run_id = _seed_active_run(app)
    owner = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='live-owner')
    with app.state.session_factory() as db:
        assert owner.acquire_run_lease(db, run_id) == 1
        row = NodeRun(run_id=run_id, node_id='work', status='running', response_id='known-live-response')
        db.add(row)
        db.flush()
        db.add(CommandReceipt(node_run_id=row.id, command_id='live-command', request_hash='a' * 64, side_effect_state='started'))
        db.commit()
        row_id = row.id
    TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='new-api').recover()
    with app.state.session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == 'running'
        assert (run.lease_owner, run.lease_fence) == ('live-owner', 1)
        assert db.get(NodeRun, row_id).status == 'running'
        assert db.query(CommandReceipt).filter_by(node_run_id=row_id).one().side_effect_state == 'started'
        assert db.query(RunEvent).filter_by(run_id=run_id).count() == 0


def test_expired_recovery_revokes_fence_and_appends_unknown_once(app, client):
    run_id = _seed_active_run(app)
    owner = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='expired-owner')
    with app.state.session_factory() as db:
        assert owner.acquire_run_lease(db, run_id) == 1
        db.get(Run, run_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        row = NodeRun(run_id=run_id, node_id='work', status='running', response_id='known-expired-response')
        db.add(row)
        db.flush()
        db.add(CommandReceipt(node_run_id=row.id, command_id='expired-command', request_hash='b' * 64, side_effect_state='started'))
        db.commit()
        row_id = row.id
    recovery = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='new-api')
    recovery.recover()
    recovery.recover()
    with app.state.session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == 'failed'
        assert run.lease_owner is None
        assert run.lease_fence == 2
        assert owner.renew_run_lease(db, run_id, 1) is False
        receipt = db.query(CommandReceipt).filter_by(node_run_id=row_id).one()
        assert (receipt.side_effect_state, receipt.reconciliation_required) == ('unknown', True)
        assert receipt.response_id == 'known-expired-response'
        assert db.query(RunEvent).filter_by(run_id=run_id, event_type='run.recovered_unknown').count() == 1


@pytest.mark.anyio
async def test_stale_owner_cannot_write_streamed_progress_or_results(app, client):
    run_id = _seed_active_run(app)
    owner = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='stale-owner')
    with app.state.session_factory() as db:
        assert owner.acquire_run_lease(db, run_id) == 1
        row = NodeRun(run_id=run_id, node_id='work', status='running')
        db.add(row)
        db.commit()
        row_id = row.id

    class Gateway:
        async def create_response(self, *args, on_progress, on_execution, **kwargs):
            with app.state.session_factory() as db:
                run = db.get(Run, run_id)
                run.lease_owner, run.lease_fence = 'new-owner', 2
                db.commit()
            await on_progress('stale-response', 'must not appear')
            await on_execution({'tools': [{'name': 'stale-tool'}]})
            return {'status': 'completed', 'text': 'stale result'}

    owner.gateway = Gateway()
    await owner.execute_node(run_id, row_id, {'agent_id': 'agent-1', 'model': 'gpt-6.1'}, {}, None, lease_fence=1)
    with app.state.session_factory() as db:
        row = db.get(NodeRun, row_id)
        assert row.partial_text == ''
        assert row.response_id is None
        assert row.execution_json is None
        assert row.output_json is None
        assert row.status == 'running'


def test_lease_recheck_refreshes_previously_loaded_run(app, client):
    run_id = _seed_active_run(app)
    owner = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='old-owner')
    with app.state.session_factory() as db:
        assert owner.acquire_run_lease(db, run_id) == 1
        db.commit()
    with app.state.session_factory() as stale:
        cached = stale.get(Run, run_id)
        with app.state.session_factory() as other:
            run = other.get(Run, run_id)
            run.lease_owner, run.lease_fence = 'new-owner', 2
            other.commit()
        assert owner.renew_run_lease(stale, run_id, 1) is False
        stale.rollback()
        assert cached.lease_owner == 'new-owner'


@pytest.mark.anyio
async def test_periodic_reaper_reconciles_only_expired_owned_runs(app, client):
    expired_id = _seed_active_run(app)
    live_id = _seed_active_run(app)
    owner = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='periodic-owner')
    with app.state.session_factory() as db:
        assert owner.acquire_run_lease(db, expired_id) == 1
        assert owner.acquire_run_lease(db, live_id) == 1
        db.get(Run, expired_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    owner.LEASE_REAPER_INTERVAL_SECONDS = 0.01
    owner.start_reaper()
    try:
        for _ in range(100):
            with app.state.session_factory() as db:
                expired = db.get(Run, expired_id)
                live = db.get(Run, live_id)
                if expired.status == 'failed':
                    break
            await asyncio.sleep(0.01)
        with app.state.session_factory() as db:
            assert db.get(Run, expired_id).status == 'failed'
            assert db.get(Run, live_id).status == 'running'
            assert db.query(RunEvent).filter_by(run_id=expired_id, event_type='run.recovered_unknown').count() == 1
            assert db.query(RunEvent).filter_by(run_id=live_id).count() == 0
    finally:
        await owner.close()
