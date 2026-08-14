"""Running one SELECT against a customer database, safely.

Two callers, one engine, one place the credential is resolved:

  * the `sql` MCP tool, so an agent can explore a schema and test a query while it designs a
    dashboard;
  * `POST /v1/sql/query`, which a dashboard app calls to refresh its panels when someone opens it.

The second is why this is not simply an MCP server. Opening a dashboard must re-run its queries
without spending an agent turn — a turn per panel per page-load is both slow and billed. Both
paths land here, so the read-only gate and the row cap cannot be true of one and not the other.

WHAT NEVER LEAVES THIS PROCESS. The connection string is resolved from the secret store inside
the gateway. The runner never receives it (an agent gets a `datasource` name, never a DSN), and
neither does the browser. That is the same shape MCP bearer tokens already use: config stores
`vault:<ref>`, the live value is fetched at the moment of use.

THE READ-ONLY GATE IS NOT THE ONLY DEFENCE, and the documentation says so. It is a parser, and a
parser is a thing that can be wrong. Point the kit at a database account that only has SELECT and
the two defences are independent.
"""
from __future__ import annotations

import asyncio
import re

# A query that has not returned by now is not going to make a dashboard feel alive, and it is
# holding a connection while it fails to.
DEFAULT_TIMEOUT_S = 30.0
# Rows beyond this are of no use to a chart and considerable use to an out-of-memory error. The
# caller is TOLD when this truncates rather than silently receiving a partial answer.
DEFAULT_MAX_ROWS = 5000

ENGINES = ("postgres", "mysql")


class SqlError(Exception):
    """A failure with a sentence a person can act on. The database's own message is included when
    it is safe to: 'column "revenu" does not exist' is exactly what the agent needs to fix it."""


class SqlRefused(SqlError):
    """The statement was refused before it reached the database."""


# ── the read-only gate ────────────────────────────────────────────────────────────

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|`[^`]*`")

# Anywhere in the statement, not just at its start. Postgres allows a data-modifying CTE —
# `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` starts with WITH and deletes your rows —
# so checking only the leading keyword is not a check.
_FORBIDDEN = (
    "insert", "update", "delete", "merge", "upsert", "replace",
    "drop", "create", "alter", "truncate", "rename", "comment",
    "grant", "revoke", "vacuum", "analyze", "reindex", "cluster",
    "copy", "call", "do", "execute", "prepare", "deallocate",
    "set", "reset", "begin", "commit", "rollback", "savepoint",
    "lock", "listen", "notify", "load", "handler", "attach", "detach",
    "into",            # SELECT … INTO creates a table
)


def _strip(sql: str) -> str:
    """Comments and string/identifier literals removed, so keyword matching cannot be fooled by a
    column called `update_time` or a literal 'please delete me'."""
    s = _BLOCK_COMMENT.sub(" ", sql)
    s = _LINE_COMMENT.sub(" ", s)
    s = _STRING.sub(" '' ", s)
    return s


def check_readonly(sql: str) -> str:
    """The statement, or SqlRefused naming what was wrong. Returns the trimmed statement."""
    raw = (sql or "").strip().rstrip(";").strip()
    if not raw:
        raise SqlRefused("The query is empty.")

    bare = _strip(raw)

    # One statement. `SELECT 1; DROP TABLE users` is two, and the second is the interesting one.
    if ";" in bare.strip().rstrip(";"):
        raise SqlRefused("Send one statement at a time — this contains more than one.")

    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", bare.lower())
    if not words:
        raise SqlRefused("This does not look like a SQL statement.")
    if words[0] not in ("select", "with"):
        raise SqlRefused(
            f"Only SELECT is allowed here; this starts with {words[0].upper()}. "
            "This connection is for reading data to chart it.")

    hit = next((w for w in words if w in _FORBIDDEN), None)
    if hit:
        raise SqlRefused(
            f"Only SELECT is allowed here, and this contains {hit.upper()}. "
            "If that word is a column or table name, alias it — the check cannot tell them apart.")
    return raw


_LIMIT_TAIL = re.compile(r"\blimit\s+\d+\s*(?:offset\s+\d+\s*)?$", re.I)


def with_limit(sql: str, max_rows: int) -> tuple[str, bool]:
    """The statement with a row cap, and whether one was added.

    Wrapping in a subquery would be the robust way and it breaks ORDER BY semantics in enough
    engines to be worse. A trailing LIMIT is appended only when the statement does not already end
    in one; a query with its own smaller LIMIT keeps it.
    """
    bare = _strip(sql).strip().rstrip(";").strip()
    if _LIMIT_TAIL.search(bare):
        return sql, False
    return f"{sql}\nLIMIT {int(max_rows)}", True


# ── engines ───────────────────────────────────────────────────────────────────────

def _rows_out(columns: list[str], records: list, max_rows: int) -> dict:
    truncated = len(records) > max_rows
    rows = [[_jsonable(v) for v in rec] for rec in records[:max_rows]]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def _jsonable(v):
    """Whatever the driver handed back, as something JSON can carry. Decimals, dates, UUIDs and
    memoryviews all arrive from real schemas and none of them survive json.dumps."""
    import datetime
    import decimal
    import uuid
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, decimal.Decimal):
        # A float would quietly lose precision on money. A string keeps what the database said,
        # and ECharts parses it.
        return str(v)
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, datetime.timedelta):
        return v.total_seconds()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(v))} bytes>"
    return str(v)


async def _pg_query(dsn: str, sql: str, timeout: float, max_rows: int) -> dict:
    try:
        import asyncpg
    except ModuleNotFoundError as e:                                   # pragma: no cover
        raise SqlError("PostgreSQL support is not installed in this build.") from e
    conn = None
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=timeout)
        # A read-only transaction: the gate above is a parser, this is the database's own opinion.
        # Belt and braces, and this one cannot be fooled by clever text.
        async with conn.transaction(readonly=True):
            recs = await asyncio.wait_for(conn.fetch(sql), timeout=timeout)
        cols = list(recs[0].keys()) if recs else []
        return _rows_out(cols, [tuple(r.values()) for r in recs], max_rows)
    except asyncio.TimeoutError as e:
        raise SqlError(f"The query did not finish within {int(timeout)}s.") from e
    except SqlError:
        raise
    except Exception as e:
        raise SqlError(_clean_db_error(e)) from e
    finally:
        if conn is not None:
            await conn.close()


async def _mysql_query(dsn: str, sql: str, timeout: float, max_rows: int) -> dict:
    try:
        import aiomysql
    except ModuleNotFoundError as e:                                   # pragma: no cover
        raise SqlError("MySQL support is not installed in this build.") from e
    parsed = _parse_mysql_dsn(dsn)
    conn = None
    try:
        conn = await asyncio.wait_for(aiomysql.connect(**parsed), timeout=timeout)
        async with conn.cursor() as cur:
            # MySQL has no read-only transaction that survives a plain connection cleanly, so the
            # session is set read-only where the server supports it and the parser carries the
            # rest. Documented, not pretended.
            with_suppress = "SET SESSION TRANSACTION READ ONLY"
            try:
                await cur.execute(with_suppress)
            except Exception:
                pass
            await asyncio.wait_for(cur.execute(sql), timeout=timeout)
            recs = await cur.fetchall()
            cols = [d[0] for d in (cur.description or [])]
        return _rows_out(cols, list(recs), max_rows)
    except asyncio.TimeoutError as e:
        raise SqlError(f"The query did not finish within {int(timeout)}s.") from e
    except SqlError:
        raise
    except Exception as e:
        raise SqlError(_clean_db_error(e)) from e
    finally:
        if conn is not None:
            conn.close()


def _parse_mysql_dsn(dsn: str) -> dict:
    from urllib.parse import unquote, urlparse
    u = urlparse(dsn)
    if u.scheme not in ("mysql", "mariadb", "mysql+aiomysql"):
        raise SqlError("A MySQL connection string looks like mysql://user:password@host:3306/database")
    if not u.hostname:
        raise SqlError("That connection string has no host.")
    return {
        "host": u.hostname, "port": u.port or 3306,
        "user": unquote(u.username or ""), "password": unquote(u.password or ""),
        "db": (u.path or "/").lstrip("/") or None,
        "autocommit": True,
    }


_CRED = re.compile(r"://[^@/\s]*@")


def _clean_db_error(e: Exception) -> str:
    """The database's message, with any credential the driver echoed back removed.

    Drivers put the DSN in connection errors, and this message is shown to a person and handed to
    an agent — both places a password must not appear."""
    msg = str(e).strip() or e.__class__.__name__
    return _CRED.sub("://***@", msg)[:600]


async def run_query(engine: str, dsn: str, sql: str, *, timeout: float = DEFAULT_TIMEOUT_S,
                    max_rows: int = DEFAULT_MAX_ROWS) -> dict:
    """Check, cap, execute. The only way a statement reaches a customer database from here."""
    if engine not in ENGINES:
        raise SqlRefused(f"Unsupported database: {engine}. This build supports {', '.join(ENGINES)}.")
    checked = check_readonly(sql)
    capped, added = with_limit(checked, max_rows)
    out = await (_pg_query if engine == "postgres" else _mysql_query)(dsn, capped, timeout, max_rows)
    out["limit_applied"] = added and max_rows or None
    return out


# ── schema introspection ──────────────────────────────────────────────────────────

_PG_SCHEMA = """
SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND t.table_type IN ('BASE TABLE', 'VIEW')
ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""

_MYSQL_SCHEMA = """
SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
WHERE c.table_schema NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""


async def introspect(engine: str, dsn: str, *, sample_rows: int = 0,
                     max_tables: int = 200, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """The shape of the database, and optionally a few real rows per table.

    `sample_rows` is 0 unless the person turned sampling on when they launched the kit. Column
    names are one thing; the values in them are the customer's data, and sending them to a model
    provider is a decision only the person who owns them can make.
    """
    sql = _PG_SCHEMA if engine == "postgres" else _MYSQL_SCHEMA
    raw = await run_query(engine, dsn, sql, timeout=timeout, max_rows=20000)

    tables: dict[tuple[str, str], dict] = {}
    for schema, table, column, dtype, nullable in raw["rows"]:
        key = (schema, table)
        t = tables.setdefault(key, {"schema": schema, "name": table, "columns": []})
        t["columns"].append({"name": column, "type": dtype, "nullable": nullable == "YES"})

    out = list(tables.values())[:max_tables]
    truncated_tables = len(tables) > len(out)

    if sample_rows > 0:
        for t in out:
            ident = _quote_ident(engine, t["schema"], t["name"])
            try:
                s = await run_query(engine, dsn, f"SELECT * FROM {ident}",
                                    timeout=min(timeout, 10.0), max_rows=int(sample_rows))
                t["sample"] = {"columns": s["columns"], "rows": s["rows"]}
            except SqlError as e:
                # One unreadable table must not cost the whole schema — a view over a missing
                # foreign server is common and says nothing about the other 40 tables.
                t["sample_error"] = str(e)[:160]

    return {"engine": engine, "tables": out, "table_count": len(tables),
            "truncated": truncated_tables, "sampled": sample_rows > 0}


def _quote_ident(engine: str, schema: str, table: str) -> str:
    if engine == "postgres":
        return f'"{schema}"."{table}"'
    return f"`{schema}`.`{table}`"
