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
