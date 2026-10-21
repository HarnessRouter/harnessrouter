"""The read-only gate, pinned.

This is the file that decides whether an agent can write to a customer's production database, so
the cases worth testing are the ones an attacker or a confused model would actually produce: a
second statement hidden behind a semicolon, a data-modifying CTE that starts with the word WITH,
a keyword buried in a comment, and a column legitimately called `update_time` that must NOT be
refused.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sql_plane import SqlRefused, check_readonly, with_limit  # noqa: E402


def refused(sql):
    with pytest.raises(SqlRefused) as e:
        check_readonly(sql)
    return str(e.value)


# ── what must be allowed ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select * from orders",
    "  SELECT count(*) FROM users;  ",
    "WITH recent AS (SELECT * FROM orders WHERE created_at > now() - interval '7 days')"
    " SELECT count(*) FROM recent",
    # A column whose NAME contains a forbidden word. Refusing this would make the kit useless on
    # half the schemas in the world.
    "SELECT id, updated_at, created_at FROM users",
    "SELECT deleted_flag FROM accounts WHERE deleted_flag = false",
    # The word only appears inside a string literal.
    "SELECT * FROM logs WHERE message = 'please delete this row'",
    "SELECT * FROM t WHERE note = 'drop table users'",
])
def test_allowed(sql):
    assert check_readonly(sql)


# ── what must be refused ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "DELETE FROM users",
    "UPDATE users SET admin = true",
    "INSERT INTO users VALUES (1)",
    "DROP TABLE users",
    "TRUNCATE users",
    "ALTER TABLE users ADD COLUMN x int",
    "GRANT ALL ON users TO public",
    "CREATE TABLE t (id int)",
])
def test_refuses_plain_writes(sql):
    assert "only select" in refused(sql).lower()


def test_refuses_a_second_statement():
    # The classic. The first statement is innocent and the second is the point.
    assert "one statement" in refused("SELECT 1; DROP TABLE users").lower()
    assert "one statement" in refused("SELECT 1;DELETE FROM users;").lower()


def test_refuses_data_modifying_cte():
    """Starts with WITH, deletes your rows. Checking only the leading keyword is not a check —
    Postgres runs this and it is the single most likely way a write would have slipped through."""
    sql = "WITH gone AS (DELETE FROM orders WHERE id < 100 RETURNING *) SELECT count(*) FROM gone"
    assert "delete" in refused(sql).lower()


def test_refuses_select_into():
    """SELECT … INTO creates a table in Postgres. It starts with SELECT and it is not a read."""
    assert "into" in refused("SELECT * INTO backup_users FROM users").lower()


def test_keyword_hidden_in_a_comment_does_not_sneak_through_or_falsely_trip():
    # Commented-out text is not executed, so it must not refuse the query…
    assert check_readonly("SELECT id FROM users -- delete this later")
    assert check_readonly("SELECT id /* drop table users */ FROM users")
    # …but a real statement after a comment is still a real statement.
    assert "one statement" in refused("SELECT 1 -- ok\n; DROP TABLE users").lower()


def test_refuses_empty_and_nonsense():
    assert "empty" in refused("   ").lower()
    assert "starts with" in refused("EXPLAIN ANALYZE SELECT 1").lower()


def test_trailing_semicolon_is_fine_but_stripped():
    assert check_readonly("SELECT 1;") == "SELECT 1"


# ── the row cap ──────────────────────────────────────────────────────────────────

def test_limit_is_added_when_absent():
    out, added = with_limit("SELECT * FROM t", 500)
    assert added and out.endswith("LIMIT 500")


def test_existing_limit_is_respected():
    """A query that asked for 10 rows means 10 — appending another LIMIT would be a syntax error
    in some engines and a surprise in the rest."""
    out, added = with_limit("SELECT * FROM t ORDER BY x LIMIT 10", 500)
    assert not added and out.count("LIMIT") == 1


def test_limit_with_offset_is_respected():
    out, added = with_limit("SELECT * FROM t LIMIT 10 OFFSET 20", 500)
    assert not added


def test_mysqls_limit_offset_count_is_respected():
    """MySQL spells an offset as `LIMIT 5, 10`. The tail check knew only `LIMIT n [OFFSET m]`, so it
    appended a second LIMIT after this one, a syntax error, and the query never ran."""
    for sql in ("SELECT * FROM t LIMIT 5, 10", "SELECT * FROM t ORDER BY x limit 5 ,10"):
        out, added = with_limit(sql, 500)
        assert not added and out == sql


def test_postgres_limit_all_is_respected():
    """Postgres spells "no limit" `LIMIT ALL` (`LIMIT { count | ALL }`). The tail check read only a
    digit, so it appended a second LIMIT after this one — `LIMIT ALL LIMIT 500`, two LIMIT clauses,
    which Postgres refuses, so the query never ran. The fetch is bounded by the cursor either way
    (_pg_query, _mysql_query), so leaving the statement alone still returns at most max_rows."""
    for sql in ("SELECT * FROM t LIMIT ALL", "SELECT * FROM t ORDER BY x limit all",
                "SELECT * FROM t LIMIT ALL OFFSET 20"):
        out, added = with_limit(sql, 500)
        assert not added and out == sql, sql


def test_all_as_a_name_is_not_read_as_a_limit():
    """`ALL` is only the statement's own limit directly after LIMIT at the end of it."""
    out, added = with_limit("SELECT all_rows FROM t", 500)
    assert added and out.rstrip().endswith("LIMIT 500")
    out, added = with_limit("SELECT * FROM (SELECT * FROM t LIMIT ALL) s", 500)
    assert added and out.rstrip().endswith("LIMIT 500")


def test_a_comma_inside_the_query_is_not_read_as_a_limit():
    out, added = with_limit("SELECT a, b FROM (SELECT a, b FROM t LIMIT 5, 10) s", 500)
    assert added and out.rstrip().endswith("LIMIT 500")


def test_limit_inside_a_subquery_does_not_count_as_the_outer_one():
    """The outer query is unbounded and must still be capped."""
    out, added = with_limit("SELECT * FROM (SELECT * FROM t LIMIT 10) s", 500)
    assert added and out.rstrip().endswith("LIMIT 500")


# ── credentials must never appear in an error ────────────────────────────────────

def test_connection_errors_do_not_echo_the_password():
    from sql_plane import _clean_db_error
    e = Exception('could not connect to postgresql://app:hunter2@db.internal:5432/analytics')
    cleaned = _clean_db_error(e)
    assert "hunter2" not in cleaned and "://***@" in cleaned


# ── a capped answer says it was capped ───────────────────────────────────────────

def _engine_over(monkeypatch, n_rows: int):
    """A stand-in for the database that honours a trailing LIMIT, as both real engines do."""
    import asyncio
    import re as _re
    import sql_plane

    async def fake(dsn, sql, timeout, max_rows):
        m = _re.search(r"LIMIT (\d+)\s*$", sql)
        recs = [(i,) for i in range(n_rows)][: int(m.group(1)) if m else None]
        return sql_plane._rows_out(["x"], recs, max_rows)

    monkeypatch.setattr(sql_plane, "_pg_query", fake)
    return lambda sql, max_rows: asyncio.run(sql_plane.run_query("postgres", "", sql, max_rows=max_rows))


def test_a_result_cut_by_the_row_cap_is_marked_truncated(monkeypatch):
    """The cap appended LIMIT max_rows, so the database never returned more than max_rows rows and
    `truncated` (len(records) > max_rows) could not be true: a caller was handed a partial answer
    as if it were the whole one."""
    run = _engine_over(monkeypatch, 100)
    out = run("SELECT x FROM big", 10)
    assert out["row_count"] == 10 and out["truncated"] is True and out["limit_applied"] == 10


def test_a_result_within_the_cap_is_not_marked_truncated(monkeypatch):
    run = _engine_over(monkeypatch, 10)
    out = run("SELECT x FROM small", 10)          # exactly the cap: nothing was left out
    assert out["row_count"] == 10 and out["truncated"] is False
    out = run("SELECT x FROM small", 50)
    assert out["row_count"] == 10 and out["truncated"] is False and out["limit_applied"] == 50


# ── the fetch itself is bounded, not just the SQL ──────────────────────────────
# #493: the row cap was enforced by appending LIMIT to the SQL and slicing after
# fetchall(). A statement carrying its own large LIMIT (or MySQL's all-rows idiom)
# was never rewritten, so the driver loaded every row into memory first. The fix
# bounds the fetch at the driver: the plane must return max_rows rows, mark
# truncated, and never ask the driver for more than max_rows + 1.

class _PgRecord(dict):
    pass   # asyncpg Records answer .keys()/.values()


class _PgCursor:
    # Mirrors asyncpg's real Cursor: fetch/fetchrow/forward only. There is deliberately
    # NO close() here — asyncpg has none, so production code calling cur.close() would
    # raise AttributeError and fail the test instead of passing silently.
    def __init__(self, rows):
        self._rows = rows
        self.fetched = None

    async def fetch(self, n):
        self.fetched = n
        return self._rows[:n]


class _PgConn:
    def __init__(self, cursor):
        self._cursor = cursor

    async def cursor(self, sql):
        # Mirrors asyncpg: Connection.cursor() returns an awaitable CursorFactory,
        # and awaiting it opens the real server-side cursor.
        return self._cursor

    def transaction(self, readonly=False):
        class _Tx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return False

        return _Tx()

    async def close(self):
        pass


def _stub_asyncpg(monkeypatch, conn):
    import sys
    import types

    mod = types.ModuleType("asyncpg")

    async def connect(dsn):
        return conn

    mod.connect = connect
    monkeypatch.setitem(sys.modules, "asyncpg", mod)


class _SSCursor:
    """Stands for aiomysql.SSCursor, the unbuffered cursor class."""


class _MysqlCursor:
    def __init__(self, rows):
        self._rows = rows
        self.fetched = None
        self.closed = False
        self.description = [("x",)]

    async def execute(self, sql):
        pass

    async def fetchmany(self, n):
        self.fetched = n
        return self._rows[:n]

    async def close(self):
        # An unbuffered cursor's close() reads the rest of the result off the wire.
        self.closed = True


class _MysqlConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.cursor_classes = None
        self.closed = False

    async def cursor(self, *classes):   # aiomysql's cursor() is awaitable
        self.cursor_classes = classes
        return self._cursor

    def close(self):
        self.closed = True


def _stub_aiomysql(monkeypatch, conn):
    import sys
    import types

    mod = types.ModuleType("aiomysql")

    async def connect(**kw):
        return conn

    mod.connect = connect
    mod.SSCursor = _SSCursor
    monkeypatch.setitem(sys.modules, "aiomysql", mod)


def test_the_postgres_fetch_never_asks_for_more_than_the_cap_plus_one(monkeypatch):
    """The stand-in engine ignores the appended LIMIT and returns the statement's own
    huge result; the plane still returns max_rows rows, says truncated, and the driver
    was asked for exactly max_rows + 1."""
    import asyncio
    import sql_plane

    rows = [_PgRecord({"x": i}) for i in range(10_000)]
    cur = _PgCursor(rows)
    _stub_asyncpg(monkeypatch, _PgConn(cur))
    out = asyncio.run(sql_plane._pg_query("postgres://u@h/db", "SELECT x FROM t LIMIT 1000000", 5.0, 100))
    assert out["row_count"] == 100 and out["truncated"] is True
    assert cur.fetched == 101, f"driver asked for {cur.fetched} rows, not 101"
    # No close() assertion: asyncpg's Cursor has no close() — the server-side portal
    # is bound to the read-only transaction and dies when the block exits.


def test_the_mysql_fetch_never_asks_for_more_than_the_cap_plus_one(monkeypatch):
    """MySQL's all-rows idiom `LIMIT 0, 18446744073709551615` is never rewritten; with a
    bounded fetchmany the driver still hands over at most max_rows + 1 rows."""
    import asyncio
    import sql_plane

    rows = [(i,) for i in range(10_000)]
    cur = _MysqlCursor(rows)
    conn = _MysqlConn(cur)
    _stub_aiomysql(monkeypatch, conn)
    out = asyncio.run(sql_plane._mysql_query(
        "mysql://u@h/db", "SELECT x FROM t LIMIT 0, 18446744073709551615", 5.0, 100))
    assert out["row_count"] == 100 and out["truncated"] is True
    assert cur.fetched == 101, f"driver asked for {cur.fetched} rows, not 101"
    # The default cursor buffers the whole result inside execute(): only an unbuffered one is bounded.
    assert conn.cursor_classes == (_SSCursor,)
    # Closing the unbuffered cursor would read the rest of the result; the connection is closed instead.
    assert not cur.closed and conn.closed


def test_the_postgres_cursor_calls_match_real_asyncpg():
    """Regression guard for the #497 review thread: asyncpg's Connection.cursor() returns
    an awaitable CursorFactory (NOT a Cursor), and Cursor exposes fetch/fetchrow/forward
    only — no close(), no async context manager. The stub above mirrors this; if a future
    asyncpg changes the interface, this fails loudly instead of shipping a broken call."""
    import inspect

    asyncpg = pytest.importorskip("asyncpg")
    from asyncpg.cursor import Cursor, CursorFactory

    assert not inspect.iscoroutinefunction(asyncpg.Connection.cursor)
    assert hasattr(CursorFactory, "__await__")
    assert not hasattr(CursorFactory, "fetch")
    assert hasattr(Cursor, "fetch")
    assert not hasattr(Cursor, "close")
    assert not hasattr(Cursor, "__aenter__")


def test_the_mysql_cursor_calls_match_real_aiomysql():
    """Guard for the MySQL stubs above: aiomysql's SSCursor is its unbuffered cursor, and its close()
    is its own (it reads the rest of the result off the wire), which is why the plane closes the
    connection instead of the cursor."""
    aiomysql = pytest.importorskip("aiomysql")
    assert issubclass(aiomysql.SSCursor, aiomysql.Cursor)
    assert aiomysql.SSCursor.close is not aiomysql.Cursor.close
