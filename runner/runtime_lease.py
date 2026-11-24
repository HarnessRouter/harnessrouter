"""Durable exclusive ownership for a native Runtime session.

This module is deliberately independent of FastAPI, Gateway and optional agent
dependencies.  It is the small cross-process boundary that a native adapter
must hold while reading a checkpoint, binding an invocation and resuming it.
The lease is an ownership fence; it is not an approval and it never grants a
tool permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import math
import os
import sqlite3
import threading
import json
import uuid


NATIVE_CAPABILITIES = frozenset({'checkpoint_before_tool', 'durable_checkpoint',
                                'exact_resume', 'deny_continuation'})


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
    registration_id: str | None = None


@dataclass(frozen=True)
class RuntimeLease:
    runtime_id: str
    owner: str | None
    fence: int
    heartbeat_at: float | None
    expires_at: float | None
    execution_id: str | None = None
    execution_state: str | None = None
    registration_id: str | None = None

    @property
    def token(self) -> RuntimeLeaseToken | None:
        if self.owner is None:
            return None
        return RuntimeLeaseToken(self.runtime_id, self.owner, self.fence, self.registration_id)


def _name(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise LeaseError(f"invalid {label}")
    return value


def _clock(now):
    if type(now) not in (int, float) or not math.isfinite(now):
        raise LeaseError('invalid clock')


def _times(ttl, now):
    _clock(now)
    if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 86400:
        raise LeaseError('invalid ttl')
    if not math.isfinite(float(now) + float(ttl)):
        raise LeaseError('invalid expiry')


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

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self):
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_leases (
                    runtime_id TEXT PRIMARY KEY,
                    owner TEXT,
                    fence INTEGER NOT NULL,
                    heartbeat_at REAL,
                    expires_at REAL
                )
            """)
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(runtime_leases)')}
            if 'execution_id' not in columns:
                conn.execute('ALTER TABLE runtime_leases ADD COLUMN execution_id TEXT')
            if 'execution_state' not in columns:
                conn.execute('ALTER TABLE runtime_leases ADD COLUMN execution_state TEXT')
            if 'registration_id' not in columns:
                conn.execute('ALTER TABLE runtime_leases ADD COLUMN registration_id TEXT')
            conn.execute('CREATE TABLE IF NOT EXISTS runtime_registrations ('
                         'runtime_id TEXT PRIMARY KEY, registration_id TEXT NOT NULL, '
                         'descriptor TEXT NOT NULL, heartbeat_at REAL NOT NULL, expires_at REAL NOT NULL)')

    @staticmethod
    def _descriptor(value):
        fields = {'session_id', 'instance_id', 'runtime_name', 'runtime_version', 'thread_id',
                  'checkpoint_ns', 'checkpoint_backend', 'capabilities'}
        if not isinstance(value, dict) or set(value) != fields:
            raise LeaseError('invalid runtime descriptor')
        for name in fields - {'capabilities', 'checkpoint_ns'}:
            _name(value[name], name)
        capabilities = value['capabilities']
        if (value['checkpoint_ns'] != '' or value['checkpoint_backend'] != 'sqlite'
                or not isinstance(capabilities, list) or any(type(c) is not str for c in capabilities)
                or len(capabilities) != len(NATIVE_CAPABILITIES) or set(capabilities) != NATIVE_CAPABILITIES):
            raise LeaseError('invalid native coverage')
        return {**value, 'capabilities': sorted(capabilities)}

    @staticmethod
    def _registration(row):
        if row is None:
            return None
        return {'runtime_id': row['runtime_id'], 'registration_id': row['registration_id'],
                **json.loads(row['descriptor']), 'heartbeat_at': row['heartbeat_at'],
                'expires_at': row['expires_at']}

    def inspect_registration(self, runtime_id):
        _name(runtime_id, 'runtime_id')
        with self._connect() as conn:
            return self._registration(conn.execute('SELECT * FROM runtime_registrations WHERE runtime_id=?',
                                                    (runtime_id,)).fetchone())

    def register(self, runtime_id, descriptor, *, ttl, now, exclusive=False):
        """Trusted adapter-only registration; no HTTP registration endpoint."""
        _name(runtime_id, 'runtime_id')
        _times(ttl, now)
        descriptor = self._descriptor(descriptor)
        serialized = json.dumps(descriptor, sort_keys=True, separators=(',', ':'))
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = conn.execute('SELECT * FROM runtime_registrations WHERE runtime_id=?', (runtime_id,)).fetchone()
            same = prior and prior['descriptor'] == serialized and prior['expires_at'] > now
            if exclusive and prior and prior['expires_at'] > now:
                raise LeaseConflict('runtime registration is already live')
            lease = self._row(conn.execute('SELECT * FROM runtime_leases WHERE runtime_id=?', (runtime_id,)).fetchone())
            # Do not revive stale registrations under an outstanding owner, or
            # attach capability claims to work already running unregistered.
            if not same and lease and (lease.execution_id is not None or (
                    lease.owner and lease.expires_at is not None and lease.expires_at > now)):
                raise LeaseConflict('runtime registration is in use')
            identity = prior['registration_id'] if same else 'rtreg_' + uuid.uuid4().hex
            conn.execute('INSERT INTO runtime_registrations VALUES (?, ?, ?, ?, ?) '
                         'ON CONFLICT(runtime_id) DO UPDATE SET registration_id=excluded.registration_id, '
                         'descriptor=excluded.descriptor, heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at',
                         (runtime_id, identity, serialized, float(now), float(now) + float(ttl)))
            return self._registration(conn.execute('SELECT * FROM runtime_registrations WHERE runtime_id=?',
                                                    (runtime_id,)).fetchone())

    def renew_registration(self, runtime_id, registration_id, descriptor, *, ttl, now):
        """Keep only the original live descriptor; never recreate after expiry."""
        _name(runtime_id, 'runtime_id')
        _name(registration_id, 'registration_id')
        _times(ttl, now)
        serialized = json.dumps(self._descriptor(descriptor), sort_keys=True, separators=(',', ':'))
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._assert_registration(conn, runtime_id, registration_id, now)
            row = conn.execute('SELECT * FROM runtime_registrations WHERE runtime_id=?', (runtime_id,)).fetchone()
            lease = self._row(conn.execute('SELECT * FROM runtime_leases WHERE runtime_id=?', (runtime_id,)).fetchone())
            if row['descriptor'] != serialized or (lease and lease.execution_state == 'unknown'):
                raise LeaseLost('runtime registration is no longer authoritative')
            conn.execute('UPDATE runtime_registrations SET heartbeat_at=?, expires_at=? '
                         'WHERE runtime_id=? AND registration_id=?',
                         (float(now), float(now) + float(ttl), runtime_id, registration_id))
            return self._registration(conn.execute('SELECT * FROM runtime_registrations WHERE runtime_id=?',
                                                    (runtime_id,)).fetchone())

    def revoke_registration(self, runtime_id, registration_id, *, now):
        """Expire matching identity, preserving uncertain execution and history."""
        _name(runtime_id, 'runtime_id')
        _name(registration_id, 'registration_id')
        _clock(now)
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            changed = conn.execute('UPDATE runtime_registrations SET expires_at=MIN(expires_at, ?) '
                                   'WHERE runtime_id=? AND registration_id=?',
                                   (float(now), runtime_id, registration_id)).rowcount
            if changed:
                conn.execute('UPDATE runtime_leases SET execution_state=? WHERE runtime_id=? '
                             'AND registration_id=? AND execution_id IS NOT NULL',
                             ('unknown', runtime_id, registration_id))

    @staticmethod
    def _assert_registration(conn, runtime_id, registration_id, now, scope=None):
        row = conn.execute('SELECT * FROM runtime_registrations WHERE runtime_id=?', (runtime_id,)).fetchone()
        if row is None and registration_id is None:
            return
        if (row is None or not isinstance(registration_id, str) or not registration_id
                or row['registration_id'] != registration_id or row['expires_at'] <= now):
            raise LeaseLost('runtime registration is no longer authoritative')
        if scope is not None:
            descriptor = json.loads(row['descriptor'])
            if (not isinstance(scope, dict) or set(scope) != {'session_id', 'instance_id'}
                    or any(descriptor[k] != scope[k] for k in scope)):
                raise LeaseLost('runtime registration scope is no longer authoritative')

    @staticmethod
    def _row(row) -> RuntimeLease | None:
        if row is None:
            return None
        return RuntimeLease(row["runtime_id"], row["owner"], int(row["fence"]),
                            row["heartbeat_at"], row["expires_at"], row['execution_id'], row['execution_state'],
                            row['registration_id'])

    def inspect(self, runtime_id: str) -> RuntimeLease | None:
        runtime_id = _name(runtime_id, "runtime_id")
        with self._connect() as conn:
            return self._row(conn.execute(
                "SELECT * "
                "FROM runtime_leases WHERE runtime_id = ?", (runtime_id,)).fetchone())

    def acquire(self, runtime_id: str, owner: str, *, ttl: float, now: float,
                registration_id: str | None = None, registration_scope=None) -> RuntimeLease:
        runtime_id, owner = _name(runtime_id, "runtime_id"), _name(owner, "owner")
        _times(ttl, now)
        expires = float(now) + float(ttl)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runtime_leases WHERE runtime_id = ?",
                               (runtime_id,)).fetchone()
            current = self._row(row)
            if current and current.execution_id is not None:
                raise LeaseConflict('runtime execution requires reconciliation')
            if current and current.registration_id is not None and registration_id is None:
                raise LeaseLost('registered runtime cannot discard its binding')
            self._assert_registration(conn, runtime_id, registration_id, now, registration_scope)
            if current and current.owner and current.expires_at is not None and current.expires_at > now:
                if current.owner == owner and current.registration_id == registration_id:
                    return current
                raise LeaseConflict("runtime lease is held")
            fence = (current.fence + 1) if current else 1
            conn.execute(
                "INSERT INTO runtime_leases(runtime_id, owner, fence, heartbeat_at, expires_at, registration_id) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(runtime_id) DO UPDATE SET owner=excluded.owner, "
                "fence=excluded.fence, heartbeat_at=excluded.heartbeat_at, expires_at=excluded.expires_at, "
                "registration_id=excluded.registration_id",
                (runtime_id, owner, fence, float(now), expires, registration_id))
            return RuntimeLease(runtime_id, owner, fence, float(now), expires, registration_id=registration_id)

    def _assert_active(self, conn, token: RuntimeLeaseToken, now: float, registration_scope=None) -> RuntimeLease:
        if not isinstance(token, RuntimeLeaseToken):
            raise LeaseError('invalid token')
        _name(token.runtime_id, "runtime_id")
        _name(token.owner, "owner")
        if type(token.fence) is not int or token.fence < 1:
            raise LeaseError("invalid fence")
        row = conn.execute("SELECT * FROM runtime_leases WHERE runtime_id = ?",
                           (token.runtime_id,)).fetchone()
        current = self._row(row)
        self._assert_registration(conn, token.runtime_id, token.registration_id, now, registration_scope)
        if (current is None or current.owner != token.owner or current.fence != token.fence
                or current.registration_id != token.registration_id
                or current.expires_at is None or current.expires_at <= now):
            raise LeaseLost("runtime lease is no longer held")
        return current

    def assert_owner(self, token: RuntimeLeaseToken, *, now: float) -> RuntimeLease:
        _clock(now)
        with self._connect() as conn:
            return self._assert_active(conn, token, now)

    def renew(self, token: RuntimeLeaseToken, *, ttl: float, now: float, registration_scope=None) -> RuntimeLease:
        _times(ttl, now)
        expires = float(now) + float(ttl)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._assert_active(conn, token, now, registration_scope)
            if current.execution_state == 'unknown':
                raise LeaseLost('runtime execution requires reconciliation')
            conn.execute("UPDATE runtime_leases SET heartbeat_at=?, expires_at=? "
                         "WHERE runtime_id=? AND owner=? AND fence=?",
                         (float(now), expires, token.runtime_id, token.owner, token.fence))
            return RuntimeLease(token.runtime_id, token.owner, token.fence, float(now), expires,
                                current.execution_id, current.execution_state, current.registration_id)

    def release(self, token: RuntimeLeaseToken, *, now: float, registration_scope=None) -> RuntimeLease:
        _clock(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._assert_active(conn, token, now, registration_scope)
            if current.execution_id is not None:
                raise LeaseConflict('runtime execution requires reconciliation')
            conn.execute("UPDATE runtime_leases SET owner=NULL, heartbeat_at=NULL, expires_at=NULL "
                         "WHERE runtime_id=? AND owner=? AND fence=?",
                         (token.runtime_id, token.owner, token.fence))
            return RuntimeLease(current.runtime_id, None, current.fence, None, None,
                                registration_id=current.registration_id)

    def begin_execution(self, token: RuntimeLeaseToken, operation: str, *, now: float):
        _clock(now)
        _name(operation, 'operation')
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current = self._assert_active(conn, token, now)
            if current.execution_id is not None:
                raise LeaseConflict('runtime execution is pinned')
            conn.execute('UPDATE runtime_leases SET execution_id=?, execution_state=? WHERE runtime_id=?',
                         (operation, 'active', token.runtime_id))

    def assert_execution(self, token: RuntimeLeaseToken, operation: str, *, now: float):
        _clock(now)
        with self._connect() as conn:
            current = self._assert_active(conn, token, now)
            if current.execution_id != operation or current.execution_state != 'active':
                raise LeaseLost('runtime execution is no longer authoritative')
            return current

    def mark_execution_unknown(self, token: RuntimeLeaseToken, operation: str):
        # No expiry check: uncertainty must remain durable after lease loss.
        if not isinstance(token, RuntimeLeaseToken):
            raise LeaseError('invalid token')
        _name(operation, 'operation')
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE runtime_leases SET execution_state=? '
                         'WHERE runtime_id=? AND owner=? AND fence=? AND execution_id=?',
                         ('unknown', token.runtime_id, token.owner, token.fence, operation))

    def end_execution(self, token: RuntimeLeaseToken, operation: str, *, now: float):
        _clock(now)
        error = None
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                current = self._assert_active(conn, token, now)
                if current.execution_id != operation or current.execution_state != 'active':
                    raise LeaseLost('runtime execution is no longer authoritative')
            except LeaseLost as exc:
                # Commit unknown before reporting a late result as lost.
                conn.execute('UPDATE runtime_leases SET execution_state=? '
                             'WHERE runtime_id=? AND owner=? AND fence=? AND execution_id=?',
                             ('unknown', token.runtime_id, token.owner, token.fence, operation))
                error = exc
            else:
                conn.execute('UPDATE runtime_leases SET execution_id=NULL, execution_state=NULL '
                             'WHERE runtime_id=?', (token.runtime_id,))
        if error:
            raise error

    def close(self):
        """Compatibility hook; operations do not keep process-bound connections."""
        return None
