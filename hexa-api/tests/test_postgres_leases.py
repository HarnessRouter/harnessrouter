"""Real independent PostgreSQL processes; a fresh isolated schema per test."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.db.models import CommandReceipt, NodeRun, Run, RunEvent
from app.tasks.service import TaskExecutor
from tests.test_run_leases import _seed_active_run

pytestmark = pytest.mark.skipif(not os.getenv('HEXA_TEST_POSTGRES_URL'), reason='opt-in real PostgreSQL lane')


def contenders(app, run_id, action):
    url = app.state.session_factory.kw['bind'].url.render_as_string(hide_password=False)
    processes = []
    try:
        for index in range(2):
            process = subprocess.Popen(
                [sys.executable, '-m', 'tests.lease_worker'],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, 'HEXA_LEASE_TEST_URL': url},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8',
            )
            processes.append(process)
            process.stdin.write(json.dumps({'owner': f'process-{index}', 'run_id': run_id, 'action': action}) + '\n')
            process.stdin.flush()
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            ready = [pool.submit(process.stdout.readline) for process in processes]
            assert [future.result(timeout=15).strip() for future in ready] == ['ready', 'ready']
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            process.stdin.write('go\n')
            process.stdin.flush()
        results = []
        for process in processes:
            stdout, _ = process.communicate(timeout=20)
            assert process.returncode == 0, 'lease worker failed (credentials withheld)'
            results.append(json.loads(stdout)['result'])
        return results
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


def test_independent_processes_cannot_both_acquire(app, client):
    run_id = _seed_active_run(app)
    results = contenders(app, run_id, 'acquire')
    assert results.count(1) == 1
    assert results.count(None) == 1
    with app.state.session_factory() as db:
        assert db.get(Run, run_id).lease_fence == 1


@pytest.mark.parametrize('expired', [False, True])
def test_independent_recovery_preserves_live_owner_or_revokes_expired_owner_once(app, client, expired):
    run_id = _seed_active_run(app)
    owner = TaskExecutor(app.state.session_factory, app.state.gateway, lease_owner='original-owner')
    with app.state.session_factory() as db:
        assert owner.acquire_run_lease(db, run_id) == 1
        if expired:
            db.get(Run, run_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        row = NodeRun(run_id=run_id, node_id='work', status='running', response_id='known-process-response')
        db.add(row)
        db.flush()
        db.add(CommandReceipt(node_run_id=row.id, command_id='process-command', request_hash='c' * 64, side_effect_state='started'))
        db.commit()
        row_id = row.id
    assert contenders(app, run_id, 'recover') == ['recovered', 'recovered']
    with app.state.session_factory() as db:
        run = db.get(Run, run_id)
        assert run.status == ('failed' if expired else 'running')
        assert run.lease_fence == (2 if expired else 1)
        assert run.lease_owner == (None if expired else 'original-owner')
        assert db.get(NodeRun, row_id).status == ('failed' if expired else 'running')
        receipt = db.query(CommandReceipt).filter_by(node_run_id=row_id).one()
        assert receipt.side_effect_state == ('unknown' if expired else 'started')
        assert receipt.reconciliation_required == expired
        if expired:
            assert receipt.response_id == 'known-process-response'
        events = db.query(RunEvent).filter_by(run_id=run_id).all()
        assert [event.event_type for event in events] == (['run.recovered_unknown', 'node.unknown', 'run.failed'] if expired else [])
        if expired:
            assert not owner.renew_run_lease(db, run_id, 1)
    assert app.state.gateway.calls == []
