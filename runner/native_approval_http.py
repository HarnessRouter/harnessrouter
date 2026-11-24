"""Strict internal wire and in-process directory for native approval sessions.

This module has no public registration or execution factory.  The directory is
owned by one Runner process and is only reachable through the authenticated
internal routes installed by ``server.py``.
"""
from contextlib import contextmanager
import base64
import copy
import threading

from langgraph_approval import NativeApprovalError, PendingInvocation

MAX_BYTES = 1024 * 1024
_FIELDS = {'command_id', 'tool', 'arguments', 'checkpoint'}
_TOOL_FIELDS = {'name', 'origin', 'plugin_name', 'plugin_version', 'plugin_digest', 'mcp_server'}


def _invalid():
    raise NativeApprovalError('native_approval_invalid')


def _text(value, *, limit=1024):
    if not isinstance(value, str) or not 1 <= len(value) <= limit:
        _invalid()
    return value


def _decode(value):
    if not isinstance(value, str) or not value or len(value) > 4 * MAX_BYTES + 4:
        _invalid()
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        _invalid()
    if not 1 <= len(raw) <= MAX_BYTES or base64.b64encode(raw).decode('ascii') != value:
        _invalid()
    return raw


def decode_pending(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        _invalid()
    command = _text(value['command_id'])
    tool = value['tool']
    if (not isinstance(tool, dict) or set(tool) - _TOOL_FIELDS
            or not {'name', 'origin'} <= set(tool)
            or any(not isinstance(v, str) or not 1 <= len(v) <= 1024 for v in tool.values())
            or tool['origin'] not in ('direct', 'plugin', 'builtin', 'runtime')):
        _invalid()
    arguments, checkpoint = _decode(value['arguments']), _decode(value['checkpoint'])
    return PendingInvocation(command, copy.deepcopy(tool), arguments, checkpoint)


def encode_pending(value):
    if not isinstance(value, PendingInvocation):
        _invalid()
    result = {'command_id': value.command_id, 'tool': copy.deepcopy(value.tool),
              'arguments': base64.b64encode(value.arguments).decode('ascii'),
              'checkpoint': base64.b64encode(value.checkpoint).decode('ascii')}
    # Keep one validator for both directions so the wire contract cannot drift.
    decode_pending(result)
    return result


class NativeSessionDirectory:
    """Process-local lookup for already-created trusted native sessions."""

    def __init__(self):
        self._lock = threading.RLock()
        self._entries = {}

    @contextmanager
    def publish(self, session, *, registry, instance_id):
        if (getattr(session, 'registry', None) is not registry
                or getattr(session, 'instance_id', None) != instance_id):
            raise NativeApprovalError('native_session_unavailable')
        session._assert_live()
        key = (session.runtime_id, session.session_id)
        with self._lock:
            if key in self._entries:
                raise NativeApprovalError('native_session_conflict')
            self._entries[key] = session
        try:
            yield session
        finally:
            with self._lock:
                if self._entries.get(key) is session:
                    del self._entries[key]

    def get(self, runtime_id, session_id):
        if (not isinstance(runtime_id, str) or not runtime_id
                or not isinstance(session_id, str) or not session_id):
            raise NativeApprovalError('native_session_unavailable')
        with self._lock:
            session = self._entries.get((runtime_id, session_id))
        if session is None:
            raise NativeApprovalError('native_session_unavailable')
        session._assert_live()
        return session
