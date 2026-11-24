"""Gateway coordinator for the internal native approval bridge.

The coordinator owns no Runtime state.  It reads a pending invocation through
the authenticated Runner transport, seals it in the existing BoundApprovalGate,
and later resumes only the exact saved pending bytes.
"""
import asyncio
import base64
import copy

from approval_execution import BoundApprovalGate, Invocation
from dataclasses import dataclass
from runtime_ownership import RuntimeOwnership
from tool_approvals import ApprovalError, ApprovalScope


@dataclass(frozen=True)
class PendingInvocation:
    command_id: str
    tool: dict
    arguments: bytes
    checkpoint: bytes


class NativeApprovalCoordinator:
    def __init__(self, gate: BoundApprovalGate, ownership: RuntimeOwnership, transport):
        if not isinstance(gate, BoundApprovalGate) or not isinstance(ownership, RuntimeOwnership):
            raise ApprovalError('hexa_approval_unavailable', 503)
        self.gate, self.ownership, self.transport = gate, ownership, transport

    @staticmethod
    def _decode_pending(value):
        fields = {'command_id', 'tool', 'arguments', 'checkpoint'}
        if not isinstance(value, dict) or set(value) != fields:
            raise ApprovalError('hexa_approval_invalid', 422)
        command = value['command_id']
        tool = value['tool']
        if (not isinstance(command, str) or not 1 <= len(command) <= 1024
                or not isinstance(tool, dict) or set(tool) - {'name', 'origin', 'plugin_name', 'plugin_version', 'plugin_digest', 'mcp_server'}
                or not {'name', 'origin'} <= set(tool)
                or tool['origin'] not in ('direct', 'plugin', 'builtin', 'runtime')
                or any(not isinstance(v, str) or not 1 <= len(v) <= 1024 for v in tool.values())):
            raise ApprovalError('hexa_approval_invalid', 422)
        decoded = []
        for item in ('arguments', 'checkpoint'):
            value_item = value[item]
            if not isinstance(value_item, str) or not value_item:
                raise ApprovalError('hexa_approval_invalid', 422)
            try:
                raw = base64.b64decode(value_item, validate=True)
            except (ValueError, TypeError):
                raise ApprovalError('hexa_approval_invalid', 422) from None
            if not 1 <= len(raw) <= 1024 * 1024 or base64.b64encode(raw).decode() != value_item:
                raise ApprovalError('hexa_approval_invalid', 422)
            decoded.append(raw)
        return PendingInvocation(command, copy.deepcopy(tool), *decoded)

    @staticmethod
    def _expected(expected):
        if (not isinstance(expected, dict) or not isinstance(expected.get('runtime_name'), str)
                or not isinstance(expected.get('runtime_version'), str)
                or not expected['runtime_name'] or not expected['runtime_version']):
            raise ApprovalError('hexa_approval_invalid', 422)

    @staticmethod
    def _execution(execution):
        fields = {'workspace', 'policy_digest', 'capability_digest',
                  'credential_versions', 'environment_versions'}
        if (not isinstance(execution, dict) or set(execution) != fields
                or not isinstance(execution['workspace'], str) or not execution['workspace']
                or not isinstance(execution['policy_digest'], str)
                or not isinstance(execution['capability_digest'], str)):
            raise ApprovalError('hexa_approval_invalid', 422)
        return execution

    @staticmethod
    def _token_body(token, *, pending=None, decision=None):
        if (not isinstance(token, dict) or set(token) -
                {'runtime_id', 'owner', 'fence', 'registration_id'}
                or not isinstance(token.get('runtime_id'), str) or not isinstance(token.get('owner'), str)
                or type(token.get('fence')) is not int or token['fence'] < 1
                or not isinstance(token.get('registration_id'), str) or not token['registration_id']):
            raise ApprovalError('hexa_approval_unavailable', 503)
        body = dict(token)
        if pending is not None:
            if isinstance(pending, dict):
                body['pending'] = copy.deepcopy(pending)
            else:
                body['pending'] = {'command_id': pending.command_id, 'tool': copy.deepcopy(pending.tool),
                    'arguments': base64.b64encode(pending.arguments).decode(),
                    'checkpoint': base64.b64encode(pending.checkpoint).decode()}
        if decision is not None:
            if decision not in ('approve', 'deny'):
                raise ApprovalError('hexa_approval_invalid', 422)
            body['decision'] = decision
        return body

    async def _native(self, path, sid, body):
        try:
            return await asyncio.wait_for(self.transport(path, sid, method='POST', body=body),
                                          timeout=self.ownership.ttl / 3)
        except ApprovalError:
            raise
        except Exception:
            raise ApprovalError('hexa_approval_unavailable', 503) from None

    def _invocation(self, scope, pending, expected, execution):
        return Invocation(command_id=pending.command_id, tool=pending.tool,
                          arguments=pending.arguments, checkpoint=pending.checkpoint,
                          workspace=execution['workspace'],
                          runtime={'name': expected['runtime_name'], 'version': expected['runtime_version']},
                          policy_digest=execution['policy_digest'],
                          capability_digest=execution['capability_digest'],
                          credential_versions=execution['credential_versions'],
                          environment_versions=execution['environment_versions'])

    async def capture(self, scope: ApprovalScope, runtime_id, expected, execution, *, expires_at, preview):
        self._expected(expected)
        execution = self._execution(execution)
        async def operation(token):
            value = await self._native('/internal/native-approvals/pending', scope.session,
                                       self._token_body(token))
            pending = self._decode_pending(value)
            call = self._invocation(scope, pending, expected, execution)
            return await self.gate.capture(scope, call, expires_at=expires_at, preview=preview)
        return await self.ownership.run_registered(scope.session, runtime_id, expected, operation)

    async def resume(self, scope: ApprovalScope, runtime_id, expected, execution, command,
                     continuation, *, native_allowed):
        self._expected(expected)
        execution = self._execution(execution)
        # A completed receipt is a durable read, not a new native request.
        existing = await self.gate.journal.continuation_state(scope, command)
        if (existing.get('continuation') == continuation
                and ((existing.get('receipt') or {}).get('side_effect_state') == 'completed'
                     or (existing.get('continuation_receipt') or {}).get('state') == 'completed')):
            return await self.gate.journal.read(scope, command)
        if existing.get('continuation') is not None and existing.get('continuation') != continuation:
            raise ApprovalError('hexa_approval_conflict')

        async def operation(token):
            value = await self._native('/internal/native-approvals/pending', scope.session,
                                       self._token_body(token))
            pending = self._decode_pending(value)
            current = self._invocation(scope, pending, expected, execution)

            async def dispatch(saved):
                current_record = await self.gate.journal.read(scope, command)
                native_pending = {'command_id': saved.command_id, 'tool': copy.deepcopy(saved.tool),
                    'arguments': base64.b64encode(saved.arguments).decode(),
                    'checkpoint': base64.b64encode(saved.checkpoint).decode()}
                await self._native('/internal/native-approvals/resume', scope.session,
                                   self._token_body(token, pending=native_pending,
                                                    decision='approve' if current_record['state'] == 'approved' else 'deny'))
                return {'status': 'completed'}

            record = await (self.gate.execute if (await self.gate.journal.read(scope, command))['state'] == 'approved'
                            else self.gate.resume_denial)(scope, command, continuation, current,
                                                         native_allowed=native_allowed, dispatch=dispatch)
            return await self.gate.journal.read(scope, command)

        return await self.ownership.run_registered(scope.session, runtime_id, expected, operation)
