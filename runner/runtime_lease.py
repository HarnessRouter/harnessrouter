"""Durable exclusive ownership for a native Runtime session.

This module is deliberately independent of FastAPI, Gateway and optional agent
dependencies.  It is the small cross-process boundary that a native adapter
must hold while reading a checkpoint, binding an invocation and resuming it.
The lease is an ownership fence; it is not an approval and it never grants a
tool permission.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import sqlite3
import threading


class LeaseError(RuntimeError):
    """Base class for safe lease failures."""


class LeaseConflict(LeaseError):
    """Another live owner holds the runtime lease."""


class LeaseLost(LeaseError):
    """The supplied owner/fence is no longer authoritative."""


@dataclass(frozen=True)
class RuntimeLeaseToken:
    runtime_id: str
    owner: str
    fence: int


@dataclass(frozen=True)
class RuntimeLease:
    runtime_id: str
    owner: str | None
    fence: int
    heartbeat_at: float | None
    expires_at: float | None

    @property
    def token(self) -> RuntimeLeaseToken | None:
        if self.owner is None:
            return None
        return RuntimeLeaseToken(self.runtime_id, self.owner, self.fence)


def _name(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise LeaseError(f"invalid {label}")
    return value


class RuntimeLeaseRegistry:
    """SQLite-backed CAS registry safe for independent Runner processes.

    A separate connection is opened for every operation.  SQLite's
    ``BEGIN IMMEDIATE`` serializes the ownership transition across processes;
    no process-local lock is treated as the authority.  Callers must pass a
    monotonic-enough wall clock from the same deployment for expiry decisions.
    """

    def __init__(self, path: str):
        if not isinstance(path, str) or not path:
            raise LeaseError("invalid lease store")
        self.path = path
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_leases (
                    runtime_id TEXT PRIMARY KEY,
                    owner TEXT,
                    fence INTEGER NOT NULL,
                    heartbeat_at REAL,
                    expires_at REAL
                )
            """)

    @staticmethod
    def _row(row) -> RuntimeLease | None:
        if row is None:
            return None
        return RuntimeLease(row["runtime_id"], row["owner"], int(row["fence"]),
                            row["heartbeat_at"], row["expires_at"])

    def inspect(self, runtime_id: str) -> RuntimeLease | None:
        runtime_id = _name(runtime_id, "runtime_id")
        with self._connect() as conn:
            return self._row(conn.execute(
                "SELECT runtime_id, owner, fence, heartbeat_at, expires_at "
                "FROM runtime_leases WHERE runtime_id = ?", (runtime_id,)).fetchone())

    def acquire(self, runtime_id: str, owner: str, *, ttl: float, now: float) -> RuntimeLease:
        runtime_id, owner = _name(runtime_id, "runtime_id"), _name(owner, "owner")
        if type(ttl) not in (int, float) or ttl <= 0 or ttl > 86400:
            raise LeaseError("invalid ttl")
        if type(now) not in (int, float):
            raise LeaseError("invalid clock")
        expires = float(now) + float(ttl)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runtime_leases WHERE runtime_id = ?",
                               (runtime_id,)).fetchone()
            current = self._row(row)
            if current and current.owner and current.expires_at is not None and current.expires_at > now:
                if current.owner == owner:
                    return current
                raise LeaseConflict("runtime lease is held")
            fence = (current.fence + 1) if current else 1
            conn.execute(
                "INSERT INTO runtime_leases(runtime_id, owner, fence, heartbeat_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(runtime_id) DO UPDATE SET owner=excluded.owner, "
                "fence=excluded.fence, heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at",
                (runtime_id, owner, fence, float(now), expires))
            return RuntimeLease(runtime_id, owner, fence, float(now), expires)

    def _assert_active(self, conn, token: RuntimeLeaseToken, now: float) -> RuntimeLease:
        _name(token.runtime_id, "runtime_id")
        _name(token.owner, "owner")
        if type(token.fence) is not int or token.fence < 1:
            raise LeaseError("invalid fence")
        row = conn.execute("SELECT * FROM runtime_leases WHERE runtime_id = ?",
                           (token.runtime_id,)).fetchone()
        current = self._row(row)
        if (current is None or current.owner != token.owner or current.fence != token.fence
                or current.expires_at is None or current.expires_at <= now):
            raise LeaseLost("runtime lease is no longer held")
        return current

    def assert_owner(self, token: RuntimeLeaseToken, *, now: float) -> RuntimeLease:
        if type(now) not in (int, float):
            raise LeaseError("invalid clock")
        with self._connect() as conn:
            return self._assert_active(conn, token, now)

    def renew(self, token: RuntimeLeaseToken, *, ttl: float, now: float) -> RuntimeLease:
        if type(ttl) not in (int, float) or ttl <= 0 or ttl > 86400:
            raise LeaseError("invalid ttl")
        if type(now) not in (int, float):
            raise LeaseError("invalid clock")
        expires = float(now) + float(ttl)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._assert_active(conn, token, now)
            conn.execute("UPDATE runtime_leases SET heartbeat_at=?, expires_at=? "
                         "WHERE runtime_id=? AND owner=? AND fence=?",
                         (float(now), expires, token.runtime_id, token.owner, token.fence))
            return RuntimeLease(token.runtime_id, token.owner, token.fence, float(now), expires)

    def release(self, token: RuntimeLeaseToken, *, now: float) -> RuntimeLease:
        if type(now) not in (int, float):
            raise LeaseError("invalid clock")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._assert_active(conn, token, now)
            conn.execute("UPDATE runtime_leases SET owner=NULL, heartbeat_at=NULL, expires_at=NULL "
                         "WHERE runtime_id=? AND owner=? AND fence=?",
                         (token.runtime_id, token.owner, token.fence))
            return RuntimeLease(current.runtime_id, None, current.fence, None, None)

    def close(self):
        """Compatibility hook; operations do not keep process-bound connections."""
        return None
