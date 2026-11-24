"""Strict internal native invocation byte contract; no optional Runtime needed."""
import base64
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from langgraph_approval import PendingInvocation, NativeApprovalError
try:
    from native_approval_http import encode_pending, decode_pending, NativeSessionDirectory
except ModuleNotFoundError:
    encode_pending = decode_pending = NativeSessionDirectory = None


def wire(**changes):
    return {'command_id': 'command', 'tool': {'name': 'write', 'origin': 'runtime'},
            'arguments': base64.b64encode(b'{ "text": "private-marker" }').decode(),
            'checkpoint': base64.b64encode(b'checkpoint').decode(), **changes}


def test_internal_pending_roundtrip_preserves_exact_bytes():
    assert decode_pending is not None, 'internal native HTTP bridge missing'
    value = decode_pending(wire())
    assert value == PendingInvocation('command', {'name': 'write', 'origin': 'runtime'},
                                     b'{ "text": "private-marker" }', b'checkpoint')
    assert encode_pending(value) == wire()


@pytest.mark.parametrize('changes', [{'arguments': '%invalid%'}, {'checkpoint': ''},
    {'command_id': ''}, {'command_id': True}, {'tool': {'name': 'write'}},
    {'tool': {'name': 'write', 'origin': 'unknown'}}, {'headers': 'private-marker'},
    {'arguments': 'a' * (1400000 + 1)}, {'checkpoint': 123}])
def test_malformed_internal_pending_is_rejected_without_input_echo(changes):
    assert decode_pending is not None, 'internal native HTTP bridge missing'
    with pytest.raises(NativeApprovalError, match='^native_approval_invalid$'):
        decode_pending(wire(**changes))


def test_missing_session_directory_is_fail_closed():
    assert NativeSessionDirectory is not None, 'trusted native session directory missing'
    with pytest.raises(NativeApprovalError, match='native_session_unavailable'):
        NativeSessionDirectory().get('runtime', 'session')
