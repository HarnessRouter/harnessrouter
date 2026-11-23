"""Run explicitly with HEXA_TEST_POSTGRES_URL pointing at a disposable test database."""
import os
from pathlib import Path
import subprocess
import sys

import psycopg
import pytest

from tests.postgres import isolated_database


pytestmark = pytest.mark.skipif(not os.getenv('HEXA_TEST_POSTGRES_URL'), reason='opt-in real PostgreSQL lane')
ROOT = Path(__file__).resolve().parents[1]


def migrate(url, *args):
    result = subprocess.run([sys.executable, str(ROOT / 'migrate.py'), *args],
                            env={**os.environ, 'HEXA_DATABASE_URL': url},
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, 'migration CLI failed (inspect isolated database; do not print credentials)'
    return result.stdout


def connect(url):
    return psycopg.connect(url.replace('postgresql+psycopg://', 'postgresql://', 1))


def test_cli_fresh_repeat_and_read_only_check():
    with isolated_database(os.environ['HEXA_TEST_POSTGRES_URL'], migrate=False) as url:
        migrate(url, '--check')
        with connect(url) as db:
            assert db.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = current_schema()").fetchone() == (0,)
        assert 'applied 009_node_iterations.sql' in migrate(url)
        with connect(url) as db:
            db.execute("INSERT INTO tasks (user_id, title) VALUES (1, 'preserved')")
        migrate(url)
        migrate(url, '--check')
        with connect(url) as db:
            assert db.execute('SELECT title FROM tasks').fetchall() == [('preserved',)]
            columns = {row[0] for row in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'node_runs'")}
            assert {'partial_text', 'execution_json', 'execution_kind', 'iteration', 'foreach_index'} <= columns
            decision_columns = {row[0] for row in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'run_decisions'")}
            assert 'iteration' in decision_columns


def test_upgrade_backfills_version_identity_and_retains_history():
    with isolated_database(os.environ['HEXA_TEST_POSTGRES_URL'], migrate=False) as url:
        with connect(url) as db:
            # Model the shipped pre-version-ID schema, independent of current migration DDL.
            db.execute("CREATE TABLE tasks (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, title TEXT, current_revision INTEGER)")
            db.execute("CREATE TABLE workflow_revisions (id BIGSERIAL PRIMARY KEY, task_id BIGINT, revision INTEGER, definition_json TEXT)")
            db.execute("CREATE TABLE task_runs (id BIGSERIAL PRIMARY KEY, task_id BIGINT, workflow_revision INTEGER, status TEXT, idempotency_key TEXT, snapshot_json TEXT)")
            db.execute("CREATE TABLE node_runs (id BIGSERIAL PRIMARY KEY, run_id BIGINT, node_id TEXT, output_json TEXT)")
            db.execute("INSERT INTO tasks (id, user_id, title, current_revision) VALUES (71, 1, 'legacy', 2)")
            db.execute("INSERT INTO workflow_revisions VALUES (81, 71, 2, '{\"nodes\":[]}')")
            db.execute("INSERT INTO task_runs (id, task_id, workflow_revision, status, snapshot_json) VALUES (91, 71, 2, 'completed', '{\"historical\":true}')")
            db.execute("INSERT INTO node_runs (id, run_id, node_id, output_json) VALUES (101, 91, 'report', '{\"text\":\"retained\"}')")
        migrate(url)
        migrate(url)
        with connect(url) as db:
            assert db.execute('SELECT title, current_revision_id, source_template_version_id FROM tasks').fetchone() == ('legacy', 81, None)
            assert db.execute('SELECT workflow_revision_id, snapshot_json FROM task_runs').fetchone() == (81, '{"historical":true}')
            assert db.execute('SELECT output_json, partial_text, execution_json FROM node_runs').fetchone() == ('{"text":"retained"}', '', None)
