"""Internal, unregistered HITL adapter. Not a Runner/UHP approval capability.

The owner must hold the native Runtime's exclusive execution lease across reading
pending(), Gateway binding/start checks and resume(). This module does not own a
model, dispatch arbitrary tool arguments, authenticate a caller or create a lease.
Only root, single-action interrupts backed by real SQLite are covered here.
"""
from dataclasses import dataclass
import asyncio
import copy
import hashlib
import json
import time
import uuid

from runtime_lease import LeaseError, LeaseLost, RuntimeLeaseRegistry, RuntimeLeaseToken


class NativeApprovalError(Exception):
    """Safe diagnostic: never include arguments, state or native exception text."""


@dataclass(frozen=True)
class PendingInvocation:
    command_id: str
    tool: dict
    arguments: bytes
    checkpoint: bytes


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


class LangGraphApprovalAdapter:
    def __init__(self, graph, config, catalog, *, lease_registry: RuntimeLeaseRegistry | None = None,
                 lease_token: RuntimeLeaseToken | None = None, clock=time.time, session_guard=None):
        self.graph = graph
        self.config = copy.deepcopy(config)
        self.catalog = copy.deepcopy(catalog)
        self.lease_registry = lease_registry
        self.lease_token = lease_token
        self.clock = clock
        self._session_guard = session_guard
        self._lock = asyncio.Lock()

    @staticmethod
    def _unavailable():
        raise NativeApprovalError('native_approval_unavailable')

    def _assert_runtime_lease(self, operation=None):
        """Require the durable owner fence when this adapter is production-bound.

        The optional arguments keep the controlled adapter usable for format
        tests. A registered runtime must always provide both values; without
        them a native checkpoint cannot safely be read or resumed.
        """
        if self._session_guard is not None:
            self._session_guard()
        if self.lease_registry is None and self.lease_token is None:
            return
        if not isinstance(self.lease_registry, RuntimeLeaseRegistry) or not isinstance(
                self.lease_token, RuntimeLeaseToken):
            raise NativeApprovalError('runtime_lease_required')
        try:
            current = self.lease_registry.assert_owner(self.lease_token, now=self.clock())
            if current.registration_id is not None:
                registration = self.lease_registry.inspect_registration(self.lease_token.runtime_id)
                supplied = self.config.get('configurable', {})
                if (registration is None or registration['registration_id'] != current.registration_id
                        or registration['thread_id'] != supplied.get('thread_id')
                        or registration['checkpoint_ns'] != supplied.get('checkpoint_ns', '')
                        or registration['runtime_name'] != 'langgraph'
                        or registration['checkpoint_backend'] != 'sqlite'):
                    raise LeaseLost('runtime registration does not match native session')
            if operation is not None:
                self.lease_registry.assert_execution(self.lease_token, operation, now=self.clock())
            elif current.execution_id is not None:
                raise LeaseLost('runtime is pinned')
        except LeaseError:
            raise NativeApprovalError('runtime_lease_lost') from None

    def _action(self, snapshot):
        """Validate the intentionally narrow HITL coverage before binding anything."""
        interrupts = snapshot.interrupts
        if len(interrupts) != 1 or not snapshot.next or len(snapshot.tasks) != 1:
            self._unavailable()
        task = snapshot.tasks[0]
        if task.state is not None or task.error or tuple(task.interrupts) != tuple(interrupts):
            self._unavailable()
        item = interrupts[0]
        if not isinstance(item.id, str) or not item.id:
            self._unavailable()
        value = item.value
        if not isinstance(value, dict) or set(value) != {'action_requests', 'review_configs'}:
            self._unavailable()
        actions, reviews = value['action_requests'], value['review_configs']
        if not isinstance(actions, list) or len(actions) != 1 or not isinstance(reviews, list) or len(reviews) != 1:
            self._unavailable()
        action, review = actions[0], reviews[0]
        if (not isinstance(action, dict) or set(action) - {'name', 'args', 'description'}
                or not {'name', 'args'} <= action.keys() or not isinstance(action['name'], str)
                or not isinstance(action['args'], dict) or not isinstance(review, dict)
                or set(review) != {'action_name', 'allowed_decisions'}
                or review['action_name'] != action['name']
                or review['allowed_decisions'] != ['approve', 'reject']):
            self._unavailable()
        identity = self.catalog.get(action['name'])
        if not isinstance(identity, dict) or identity.get('name') != action['name']:
            self._unavailable()
        return item, action, identity

    async def pending(self, *, _operation=None):
        """Read the latest durable native checkpoint, never a client-supplied call."""
        self._assert_runtime_lease(_operation)
        # Optional backend dependencies stay out of the common Runner environment.
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        try:
            saver = self.graph.checkpointer
            if not isinstance(saver, AsyncSqliteSaver):
                self._unavailable()
            supplied = self.config.get('configurable', {})
            if (not isinstance(supplied.get('thread_id'), str) or not supplied['thread_id']
                    or supplied.get('checkpoint_ns', '') != '' or 'checkpoint_id' in supplied):
                self._unavailable()
            # SQLite :memory: (including URI variants) cannot survive process death.
            async with saver.conn.execute('PRAGMA database_list') as cursor:
                databases = await cursor.fetchall()
            if not any(row[1] == 'main' and row[2] for row in databases):
                self._unavailable()
            snapshot = await self.graph.aget_state(self.config)
            item, action, identity = self._action(snapshot)
            position = snapshot.config.get('configurable', {})
            if (position.get('thread_id') != supplied['thread_id'] or position.get('checkpoint_ns', '') != ''
                    or not isinstance(position.get('checkpoint_id'), str) or not position['checkpoint_id']):
                self._unavailable()
            saved = await saver.aget_tuple(snapshot.config)
            if saved is None:
                self._unavailable()
            # Private integrity commitment includes saved interrupt writes as well
            # as state channels. It is sealed/HMAC-bound by Gateway, never public.
            kind, data = saver.serde.dumps_typed((saved.checkpoint, saved.pending_writes))
            checkpoint = _json({'version': 'hexa.langgraph.pending.v1',
                                'thread_id': position['thread_id'], 'checkpoint_ns': '',
                                'checkpoint_id': position['checkpoint_id'], 'interrupt_id': item.id,
                                'state_digest': hashlib.sha256(kind.encode() + b'\0' + data).hexdigest()})
            arguments = _json(action['args'])
            if len(arguments) > 1024 * 1024 or len(checkpoint) > 1024 * 1024:
                self._unavailable()
            command = 'cmd_lg_' + hashlib.sha256(_json({
                'thread': position['thread_id'], 'checkpoint': position['checkpoint_id'],
                'interrupt': item.id})).hexdigest()
            self._assert_runtime_lease(_operation)
            return PendingInvocation(command, copy.deepcopy(identity), arguments, checkpoint)
        except NativeApprovalError:
            raise
        except Exception:
            raise NativeApprovalError('native_approval_unavailable') from None

    async def resume(self, pending, decision):
        """Resume one saved interrupt; caller supplies authorization, never new args.

        This local lock protects a single adapter object only. Native ownership
        and Gateway's durable single-start permit remain mandatory for dispatch.
        Errors after ainvoke starts must be classified as unknown by the owner.
        """
        from langgraph.types import Command

        if decision not in ('approve', 'deny') or not isinstance(pending, PendingInvocation):
            self._unavailable()
        async with self._lock:
            self._assert_runtime_lease()
            operation = None
            try:
                if self.lease_registry is not None:
                    operation = uuid.uuid4().hex
                    self.lease_registry.begin_execution(self.lease_token, operation, now=self.clock())
                try:
                    current = await self.pending(_operation=operation)
                except NativeApprovalError as exc:
                    if str(exc).startswith('runtime_lease_'):
                        raise
                    raise NativeApprovalError('native_approval_changed') from None
                if current != pending:
                    raise NativeApprovalError('native_approval_changed')
                checkpoint = json.loads(pending.checkpoint)
                config = copy.deepcopy(self.config)
                config['configurable']['checkpoint_id'] = checkpoint['checkpoint_id']
                self._assert_runtime_lease(operation)
                result = await self.graph.ainvoke(Command(resume={checkpoint['interrupt_id']: {
                    'decisions': [{'type': 'approve' if decision == 'approve' else 'reject'}]}}), config)
                self._assert_runtime_lease(operation)
                if operation is not None:
                    self.lease_registry.end_execution(self.lease_token, operation, now=self.clock())
                return result
            except BaseException as exc:
                if operation is not None:
                    self.lease_registry.mark_execution_unknown(self.lease_token, operation)
                if isinstance(exc, LeaseError):
                    raise NativeApprovalError('runtime_lease_lost') from None
                raise
