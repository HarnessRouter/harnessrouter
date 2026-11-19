"""Explicit opt-in PostgreSQL test isolation; never touch the configured public schema."""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


@contextmanager
def isolated_database(database_url, *, migrate=True):
    url = make_url(database_url)
    if url.drivername not in ('postgresql', 'postgresql+psycopg'):
        raise ValueError('HEXA_TEST_POSTGRES_URL must use PostgreSQL with psycopg')
    schema = 'hexa_test_' + uuid4().hex
    admin_url = url.set(drivername='postgresql').render_as_string(hide_password=False)
    scoped = url.set(drivername='postgresql+psycopg').update_query_dict({'options': f'-csearch_path={schema}'})
    scoped_url = scoped.render_as_string(hide_password=False)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            if migrate:
                from migrate import MIGRATIONS
                with psycopg.connect(scoped_url.replace('postgresql+psycopg://', 'postgresql://', 1)) as connection:
                    for name in MIGRATIONS:
                        connection.execute((Path(__file__).resolve().parents[1] / 'migrations' / name).read_text(encoding='utf-8'))
            yield scoped_url
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
