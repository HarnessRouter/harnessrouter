"""SQLite control-store container — the self-hosted sibling of the hosted document store.

WHY THIS EXISTS
The control store holds the coordination state that keeps concurrent turns honest:
idempotency reservations, per-session execution leases (with fencing), response
cursors/terminal state, and API-key cache entries. It was originally written against a
hosted document database, which meant a self-hosted deployment had no control plane at
all — and any request carrying an `Idempotency-Key` failed closed with a 503.

Rather than fork the ~20 control-store functions into a second implementation (two copies
of subtle concurrency logic is how they drift apart), this module supplies a *container*
with the same five operations and the same error semantics the hosted client exposes:

    read_item / create_item / replace_item / upsert_item / delete_item

`control_store` picks the container at runtime, so every function above it — the fencing
maths, the CAS retries, the TTL handling — is byte-for-byte the same code in both
deployments. That is the whole point: one codebase, two backings.

CONCURRENCY
Compare-and-swap is the load-bearing primitive: `replace_item(..., etag=...)` must fail if
another writer changed the document first, or two turns could both believe they hold a
session lease. Here `_etag` is a monotonically bumped counter and the CAS is performed
inside a single IMMEDIATE transaction, so a concurrent writer either loses the race
cleanly (raising the access-condition error the callers already catch) or serialises
behind it. SQLite is opened per-operation in WAL mode, which safely supports the multiple
readers + single writer this workload produces.

TTL
The hosted store expires documents by a `ttl` field. SQLite has no background expiry, so
reads treat an expired document as absent (the same observable behaviour) and writes
opportunistically sweep. Expiry is thus lazy but never *late* from a caller's point of
view, which is what the lease and idempotency logic actually depends on.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time


# ── error types ───────────────────────────────────────────────────────────────
# Named to match the hosted client's exceptions so `except cex.CosmosResourceNotFoundError`
# in control_store works against either backing without a single conditional at the call
# site. control_store resolves `cex` to this module when running self-hosted.
class CosmosResourceNotFoundError(Exception):
    status_code = 404


class CosmosResourceExistsError(Exception):
    status_code = 409


class CosmosAccessConditionFailedError(Exception):
    """Raised when a CAS `replace_item` loses the race (etag no longer current)."""
    status_code = 412


class CosmosHttpResponseError(Exception):
    status_code = 500


def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("CREATE TABLE IF NOT EXISTS control ("
                "id TEXT PRIMARY KEY, pk TEXT NOT NULL, body TEXT NOT NULL, "
                "etag INTEGER NOT NULL, expires REAL)")
    con.execute("CREATE INDEX IF NOT EXISTS control_pk ON control(pk)")
    return con


def _expires_at(body: dict) -> float | None:
    """Absolute expiry from the document's relative `ttl`, or None for no expiry.

    `ts` is the write time the callers already stamp; falling back to now() keeps a
    document with a ttl but no ts from living forever."""
    try:
        ttl = int(body.get("ttl") or 0)
    except (TypeError, ValueError):
        return None
    if ttl <= 0:
        return None
    try:
        base = float(body.get("ts") or time.time())
    except (TypeError, ValueError):
        base = time.time()
    return base + ttl


class SqliteContainer:
    """Async-shaped container over one SQLite file.

    The methods are `async def` purely to match the hosted client's surface — the work is
    synchronous and fast (single-row, indexed). Making it genuinely async would buy
    nothing here and would add a thread hop to every lease heartbeat.
    """

    def __init__(self, path: str):
        self._path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        _connect(path).close()          # create schema up front, surface I/O errors early

    # -- helpers ---------------------------------------------------------------
    @staticmethod
    def _row_to_doc(row) -> dict:
        doc = json.loads(row[0])
        doc["_etag"] = str(row[1])
        return doc

    def _live(self, con, item_id: str):
        """Fetch a row, treating an expired document as absent (and sweeping it)."""
        row = con.execute("SELECT body, etag, expires FROM control WHERE id=?",
                          (item_id,)).fetchone()
        if row is None:
            return None
        if row[2] is not None and row[2] <= time.time():
            con.execute("DELETE FROM control WHERE id=?", (item_id,))
            return None
        return row

    # -- container operations --------------------------------------------------
    async def read_item(self, item: str, partition_key: str = "", **_kw) -> dict:
        con = _connect(self._path)
        try:
            row = self._live(con, item)
            if row is None:
                raise CosmosResourceNotFoundError(item)
            return self._row_to_doc(row)
        finally:
            con.close()

    async def create_item(self, body: dict, **_kw) -> dict:
        """Insert, or raise Exists — this is the atom idempotency reservation rides on."""
        item_id = str(body.get("id") or "")
        con = _connect(self._path)
        try:
            con.execute("BEGIN IMMEDIATE")
            if self._live(con, item_id) is not None:
                con.execute("ROLLBACK")
                raise CosmosResourceExistsError(item_id)
            # An expired row may still occupy the primary key — _live swept it above.
            con.execute("INSERT OR REPLACE INTO control(id, pk, body, etag, expires) "
                        "VALUES(?,?,?,?,?)",
                        (item_id, str(body.get("pk") or ""), json.dumps(body), 1,
                         _expires_at(body)))
            con.execute("COMMIT")
            return {**body, "_etag": "1"}
        except CosmosResourceExistsError:
            raise
        except Exception as e:  # noqa: BLE001
            try:
                con.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise CosmosHttpResponseError(str(e)) from e
        finally:
            con.close()

    async def replace_item(self, item: str, body: dict, etag: str | None = None,
                           match_condition=None, **_kw) -> dict:
        """Replace; when `etag` is supplied this is a compare-and-swap.

        Losing the CAS raises the access-condition error rather than overwriting — the
        fencing logic in control_store depends on that being a hard failure, because a
        silent overwrite would let two owners believe they hold the same lease.
        """
        con = _connect(self._path)
        try:
            con.execute("BEGIN IMMEDIATE")
            row = self._live(con, item)
            if row is None:
                con.execute("ROLLBACK")
                raise CosmosResourceNotFoundError(item)
            if etag is not None and str(row[1]) != str(etag):
                con.execute("ROLLBACK")
                raise CosmosAccessConditionFailedError(item)
            new_etag = int(row[1]) + 1
            stored = {k: v for k, v in body.items() if k != "_etag"}
            con.execute("UPDATE control SET pk=?, body=?, etag=?, expires=? WHERE id=?",
                        (str(body.get("pk") or ""), json.dumps(stored), new_etag,
                         _expires_at(stored), item))
            con.execute("COMMIT")
            return {**stored, "_etag": str(new_etag)}
        except (CosmosResourceNotFoundError, CosmosAccessConditionFailedError):
            raise
        except Exception as e:  # noqa: BLE001
            try:
                con.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise CosmosHttpResponseError(str(e)) from e
        finally:
            con.close()

    async def upsert_item(self, body: dict, **_kw) -> dict:
        item_id = str(body.get("id") or "")
        con = _connect(self._path)
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT etag FROM control WHERE id=?", (item_id,)).fetchone()
            new_etag = (int(row[0]) + 1) if row else 1
            stored = {k: v for k, v in body.items() if k != "_etag"}
            con.execute("INSERT OR REPLACE INTO control(id, pk, body, etag, expires) "
                        "VALUES(?,?,?,?,?)",
                        (item_id, str(body.get("pk") or ""), json.dumps(stored), new_etag,
                         _expires_at(stored)))
            con.execute("COMMIT")
            return {**stored, "_etag": str(new_etag)}
        except Exception as e:  # noqa: BLE001
            try:
                con.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise CosmosHttpResponseError(str(e)) from e
        finally:
            con.close()

    async def delete_item(self, item: str, partition_key: str = "", **_kw) -> None:
        con = _connect(self._path)
        try:
            if self._live(con, item) is None:
                raise CosmosResourceNotFoundError(item)
            con.execute("DELETE FROM control WHERE id=?", (item,))
        finally:
            con.close()
