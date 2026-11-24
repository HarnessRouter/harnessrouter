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
    def __init__(self, graph, config, catalog):
        self.graph = graph
        self.config = copy.deepcopy(config)
        self.catalog = copy.deepcopy(catalog)
        self._lock = asyncio.Lock()

    @staticmethod
    def _unavailable():
        raise NativeApprovalError('native_approval_unavailable')

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

    async def pending(self):
        """Read the latest durable native checkpoint, never a client-supplied call."""
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
            try:
                current = await self.pending()
            except NativeApprovalError:
                raise NativeApprovalError('native_approval_changed') from None
            if current != pending:
                raise NativeApprovalError('native_approval_changed')
            checkpoint = json.loads(pending.checkpoint)
            config = copy.deepcopy(self.config)
            config['configurable']['checkpoint_id'] = checkpoint['checkpoint_id']
            return await self.graph.ainvoke(Command(resume={checkpoint['interrupt_id']: {
                'decisions': [{'type': 'approve' if decision == 'approve' else 'reject'}]}}), config)
