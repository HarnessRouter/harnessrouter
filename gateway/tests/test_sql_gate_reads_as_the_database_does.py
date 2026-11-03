"""The read-only gate reads a statement the way the database will, or refuses it.

A gate that reads differently from the database passes what the database then runs. Comments were removed before strings,
in separate passes, so a `--` or `/*` inside a string ate the rest of the statement before the keyword check saw it; MySQL's
executable comments were taken for comments; MySQL's `--` needs whitespace after it and `#` is a comment to it; and a backslash
before a quote ends a string for one database and not another.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sql_plane import SqlRefused, _strip, check_readonly, with_limit  # noqa: E402

OUTFILE = "INTO OUTFILE '/tmp/x'"
EVERY = ["mysql", "postgres", ""]


@pytest.mark.parametrize("sql", [
    f"SELECT 1 /*!50000 {OUTFILE} */",                      # MySQL's executable comment
    f"SELECT 1 /*! {OUTFILE} */",
    f"SELECT 1 /*M! {OUTFILE} */",                          # MariaDB's
    f"SELECT '--' {OUTFILE}",                               # a comment opener inside a string
    f"SELECT '/*' {OUTFILE} -- */'",
    f"SELECT '/*' {OUTFILE} /* */",
    f"SELECT '\\'' {OUTFILE} -- '",                         # a backslash that ends the string for one reader only
    f'SELECT "\\"" {OUTFILE} -- "',
    "SELECT 1; DROP TABLE t",
    "DROP TABLE t",
    f"SELECT $$ ' $$ {OUTFILE} -- '",                       # Postgres's other string quote
    f"SELECT 'a {OUTFILE}",                                 # an unbalanced quote
    f"SELECT 1 /* {OUTFILE}",                               # an unclosed comment
])
@pytest.mark.parametrize("engine", EVERY)
def test_what_could_hide_a_statement_is_refused(sql, engine):
    with pytest.raises(SqlRefused):
        check_readonly(sql, engine)


@pytest.mark.parametrize("sql", [
    f"SELECT 1--1 {OUTFILE}",                               # arithmetic to MySQL, which needs whitespace after --
    f"SELECT 1 # '\n{OUTFILE} #'",                          # a comment to MySQL: the quote after it would pair differently here
    "SELECT 1 # a comment",
])
def test_mysqls_own_comment_rules_are_read_as_mysql_reads_them(sql):
    with pytest.raises(SqlRefused):
        check_readonly(sql, "mysql")


@pytest.mark.parametrize("sql,engine", [
    ("SELECT id FROM users -- delete this later", "mysql"),
    ("SELECT id FROM users -- delete this later", "postgres"),
    ("SELECT id /* drop table users */ FROM users", "mysql"),
    ("SELECT /*+ MAX_EXECUTION_TIME(100) */ id FROM users", "mysql"),   # an optimizer hint is not an executable comment
    ("SELECT 'please delete me' AS note", "mysql"),
    ("SELECT '--not a comment' AS a, '/* nor this */' AS b, '#nor this' AS c", "mysql"),
    ("SELECT 'it''s' AS a", "mysql"),
    ("SELECT `update_time` FROM t", "mysql"),
    ("SELECT update_time FROM t", "postgres"),
    ("SELECT doc #>> '{a,b}' AS v FROM t", "postgres"),         # JSON path operators are not comments in Postgres
    ("SELECT doc #> '{a}' AS v FROM t", "postgres"),
    ("SELECT 1 --comment without a space", "postgres"),         # a comment in Postgres
    ("SELECT 'C:\\dir\\file' AS path", "mysql"),                # a backslash with no quote after it
    ("WITH a AS (SELECT 1 AS x) SELECT x FROM a", "postgres"),
])
def test_ordinary_statements_still_pass(sql, engine):
    assert check_readonly(sql, engine)


def test_the_comment_a_string_holds_stays_text_for_the_row_limit():
    out, added = with_limit("SELECT '--' AS a", 10)
    assert added and out.endswith("LIMIT 10") and "'--'" in out
    assert "--" not in _strip("SELECT '--' AS a")
