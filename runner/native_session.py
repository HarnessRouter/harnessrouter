"""Trusted native adapter lifecycle; no public registration or Provider factory.

The caller owns the graph/checkpointer and must keep them open for this context.
Only adapters created here carry its liveness guard. This module is optional and
does not install or advertise a LangGraph Runner backend.
"""
import asyncio
import contextlib
import copy
from importlib.metadata import version
import math
import time

from langgraph_approval import LangGraphApprovalAdapter, NativeApprovalError
from runtime_lease import RuntimeLeaseRegistry, RuntimeLeaseToken, NATIVE_CAPABILITIES


class LangGraphNativeSession:
    def __init__(self, graph, config, catalog, *, registry, runtime_id, session_id, instance_id,
                 ttl=30.0, clock=time.time):
        if (not isinstance(registry, RuntimeLeaseRegistry)
                or any(not isinstance(s, str) or not 1 <= len(s) <= 1024
                       for s in (runtime_id, session_id, instance_id))
                or type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 86400):
            raise NativeApprovalError('native_session_unavailable')
        self.graph, self.config, self.catalog = graph, copy.deepcopy(config), copy.deepcopy(catalog)
        self.registry, self.runtime_id = registry, runtime_id
        self.session_id, self.instance_id, self.ttl, self.clock = session_id, instance_id, ttl, clock
        self._registration = None
        self._descriptor = None
        self._heartbeat_task = None
        self._alive = False
        self._entered = False
        self._lost = asyncio.Event()

    async def _health(self):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        supplied = self.config.get('configurable', {})
        saver = self.graph.checkpointer
        if (not isinstance(saver, AsyncSqliteSaver) or not isinstance(supplied, dict)
                or not isinstance(supplied.get('thread_id'), str) or not supplied['thread_id']
                or supplied.get('checkpoint_ns', '') != '' or 'checkpoint_id' in supplied):
            raise NativeApprovalError('native_session_unavailable')
        async with saver.conn.execute('PRAGMA database_list') as cursor:
            databases = await cursor.fetchall()
        if not any(row[1] == 'main' and row[2] for row in databases):
            raise NativeApprovalError('native_session_unavailable')

    def _assert_live(self):
        if (not self._alive or self._lost.is_set() or self._registration is None
                or self._registration['expires_at'] <= self.clock()):
            raise NativeApprovalError('native_session_unavailable')

    def _invalidate(self):
        self._alive = False
        self._lost.set()
        if self._registration is not None:
            self.registry.revoke_registration(self.runtime_id, self._registration['registration_id'], now=self.clock())

    async def __aenter__(self):
        if self._entered:
            raise NativeApprovalError('native_session_unavailable')
        self._entered = True
        try:
            await asyncio.wait_for(self._health(), timeout=self.ttl / 3)
            self._descriptor = {'session_id': self.session_id, 'instance_id': self.instance_id,
                'runtime_name': 'langgraph', 'runtime_version': version('langgraph'),
                'thread_id': self.config['configurable']['thread_id'], 'checkpoint_ns': '',
                'checkpoint_backend': 'sqlite', 'capabilities': sorted(NATIVE_CAPABILITIES)}
            self._registration = self.registry.register(self.runtime_id, self._descriptor,
                ttl=self.ttl, now=self.clock(), exclusive=True)
            self._alive = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat())
            return self
        except asyncio.CancelledError:
            self._invalidate()
            raise
        except Exception:
            self._invalidate()
            raise NativeApprovalError('native_session_unavailable') from None

    async def _heartbeat(self):
        try:
            while True:
                await asyncio.sleep(self.ttl / 3)
                await asyncio.wait_for(self._health(), timeout=self.ttl / 3)
                self._registration = self.registry.renew_registration(self.runtime_id,
                    self._registration['registration_id'], self._descriptor, ttl=self.ttl, now=self.clock())
        except asyncio.CancelledError:
            raise
        except Exception:
            # Stop local dispatch immediately, even if durable revocation itself
            # fails. Remote readers then lose the registration at its TTL.
            self._alive = False
            self._lost.set()
            with contextlib.suppress(Exception):
                self._invalidate()

    async def wait_lost(self):
        await self._lost.wait()

    def adapter(self, token):
        self._assert_live()
        if (not isinstance(token, RuntimeLeaseToken) or token.runtime_id != self.runtime_id
                or token.registration_id != self._registration['registration_id']):
            raise NativeApprovalError('native_session_unavailable')
        try:
            self.registry.assert_owner(token, now=self.clock())
        except Exception:
            raise NativeApprovalError('native_session_unavailable') from None
        return LangGraphApprovalAdapter(self.graph, self.config, self.catalog,
            lease_registry=self.registry, lease_token=token, clock=self.clock, session_guard=self._assert_live)

    async def __aexit__(self, exc_type, exc, tb):
        # Invalidate before awaiting heartbeat cleanup; a retained adapter cannot
        # race context teardown to start a new native continuation.
        self._alive = False
        self._lost.set()
        try:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._heartbeat_task
        finally:
            try:
                self._invalidate()
            except Exception:
                raise NativeApprovalError('native_session_unavailable') from None
