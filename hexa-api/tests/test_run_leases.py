"""Run leases prevent stale task executors from committing late results."""

from datetime import datetime, timedelta, timezone

from app.db.models import Run, Task
from app.tasks.service import TaskExecutor, encoded


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
