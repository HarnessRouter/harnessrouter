"""Internal durable journal; not native interception or advertised UHP support."""
from dataclasses import dataclass
import copy
import hashlib
import json
import re
import time


@dataclass(frozen=True)
class ApprovalScope:
    org: str
    principal: str
    session: str
    response: str


class ApprovalError(Exception):
    def __init__(self, code, status_code=409):
        super().__init__(code)
        self.code, self.status_code = code, status_code


class ApprovalJournal:
    """CAS journal for trusted native adapters; no method dispatches a tool.

    The caller authenticates scope, computes the canonical execution binding and
    supplies fresh native permission facts. Never construct these from model or
    client claims. A positive start permit is consumed even if the caller dies.
    """

    def __init__(self, container, exceptions, clock=time.time):
        self.container, self.exceptions, self.clock = container, exceptions, clock

    @classmethod
    async def configured_control_store(cls):
        """Use the existing configured backing, without creating another store."""
        import control_store
        return cls(await control_store._container(), control_store._exceptions())

    @staticmethod
    def _identity(scope, command):
        fields = [scope.org, scope.principal, scope.session, scope.response, command]
        if any(not isinstance(value, str) or not value or len(value) > 1024 for value in fields):
            raise ApprovalError('hexa_approval_invalid', 422)
        digest = hashlib.sha256(json.dumps(fields, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
        return f'approval::{digest}', f'org::{scope.org}'

    @staticmethod
    def _view(doc):
        return copy.deepcopy({key: doc[key] for key in ('request', 'state', 'receipt') if key in doc})

    @staticmethod
    def _invalid():
        raise ApprovalError('hexa_approval_invalid', 422)

    @staticmethod
    def _digest(value):
        return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None

    def _validate_request(self, value):
        required = {'id', 'type', 'status', 'command_id', 'request_hash', 'canonicalization',
                    'policy_digest', 'capability_digest', 'tool', 'preview', 'expires_at'}
        if not isinstance(value, dict) or set(value) != required:
            self._invalid()
        if (not isinstance(value['id'], str) or re.fullmatch(r'approval_[A-Za-z0-9_-]{1,255}', value['id']) is None
                or value['type'] != 'tool_approval_request' or value['status'] != 'completed'
                or value['canonicalization'] != 'RFC8785-v1'
                or not all(self._digest(value[key]) for key in ('request_hash', 'policy_digest', 'capability_digest'))
                or not isinstance(value['preview'], str) or len(value['preview']) > 20000
                or type(value['expires_at']) is not int
                or not self.clock() < value['expires_at'] <= self.clock() + 86400):
            self._invalid()
        tool = value['tool']
        tool_keys = {'name', 'origin', 'plugin_name', 'plugin_version', 'plugin_digest', 'mcp_server'}
        if (not isinstance(tool, dict) or set(tool) - tool_keys or not {'name', 'origin'} <= tool.keys()
                or any(not isinstance(part, str) or not part or len(part) > 1024 for part in tool.values())
                or tool['origin'] not in ('direct', 'plugin', 'builtin', 'runtime')):
            self._invalid()
        if tool['origin'] == 'plugin' and not {'plugin_name', 'plugin_version', 'plugin_digest'} <= tool.keys():
            self._invalid()
        if 'plugin_digest' in tool and not self._digest(tool['plugin_digest']):
            self._invalid()

    def _expire(self, doc):
        # Once execution may have started, expiry cannot pretend it did not run.
        if (doc['state'] in ('pending', 'approved') and self.clock() >= doc['request']['expires_at']
                and doc.get('receipt', {}).get('side_effect_state', 'not_started') == 'not_started'):
            doc['state'] = 'expired'

    @staticmethod
    def _active_error(doc):
        if doc['state'] == 'expired':
            return ApprovalError('hexa_approval_expired', 410)
        if doc['state'] == 'voided':
            return ApprovalError('hexa_approval_not_pending')
        return None

    async def _change(self, scope, command, mutate):
        identity, partition = self._identity(scope, command)
        for _ in range(16):
            try:
                doc = await self.container.read_item(identity, partition_key=partition)
            except self.exceptions.CosmosResourceNotFoundError:
                raise ApprovalError('hexa_approval_not_found', 404) from None
            # Defense in depth: the local compatibility container ignores pk.
            if doc.get('scope') != scope.__dict__ or doc.get('request', {}).get('command_id') != command:
                raise ApprovalError('hexa_approval_not_found', 404)
            before = copy.deepcopy(doc)
            self._expire(doc)
            result, error = mutate(doc)
            if doc != before:
                try:
                    # Both backings enforce etag. MatchConditions is needed by
                    # the optional hosted adapter; do not use its fail-open lease.
                    from control_store import _IF_MATCH
                    await self.container.replace_item(identity, doc, etag=before['_etag'], match_condition=_IF_MATCH)
                except self.exceptions.CosmosAccessConditionFailedError:
                    continue
            if error:
                raise error
            return result
        raise ApprovalError('hexa_approval_conflict')

    async def create(self, scope, request):
        self._validate_request(request)
        identity, partition = self._identity(scope, request['command_id'])
        doc = {'id': identity, 'pk': partition, 'kind': 'tool_approval', 'scope': dict(scope.__dict__),
               'request': copy.deepcopy(request), 'state': 'pending'}
        try:
            await self.container.create_item(doc)
            return self._view(doc)
        except self.exceptions.CosmosResourceExistsError:
            existing = await self.read(scope, request['command_id'])
            # A racing adapter may allocate a different output ID. The winner's
            # ID is authoritative; a changed descriptor can never replace it.
            if ({key: value for key, value in existing['request'].items() if key != 'id'}
                    != {key: value for key, value in request.items() if key != 'id'}):
                raise ApprovalError('hexa_approval_conflict') from None
            return existing

    async def read(self, scope, command):
        return await self._change(scope, command, lambda doc: (self._view(doc), None))

    async def decide(self, scope, command, decision, key):
        fields = {'type', 'approval_id', 'command_id', 'request_hash', 'decision'}
        if (not isinstance(key, str) or not 1 <= len(key) <= 255 or not isinstance(decision, dict)
                or set(decision) != fields or decision['type'] != 'tool_approval_response'
                or decision['decision'] not in ('approve', 'deny')):
            self._invalid()
        key_digest = hashlib.sha256(key.encode()).hexdigest()

        def mutate(doc):
            req = doc['request']
            expected = {'type': 'tool_approval_response', 'approval_id': req['id'],
                        'command_id': command, 'request_hash': req['request_hash'], 'decision': decision['decision']}
            if decision != expected:
                return None, ApprovalError('hexa_approval_conflict')
            if 'decision' in doc:
                if doc['decision'] == decision and doc['decision_key'] == key_digest:
                    return copy.deepcopy(doc['decision_receipt']), None
                return None, ApprovalError('hexa_approval_conflict')
            if self._active_error(doc):
                return None, self._active_error(doc)
            if doc['state'] != 'pending':
                return None, ApprovalError('hexa_approval_not_pending')
            receipt = {name: decision[name] for name in ('approval_id', 'command_id', 'request_hash', 'decision')}
            receipt.update(side_effect_state='not_started', reconciliation_required=False)
            doc.update(state='approved' if decision['decision'] == 'approve' else 'denied',
                       decision=copy.deepcopy(decision), decision_key=key_digest,
                       decision_receipt=copy.deepcopy(receipt), receipt=receipt)
            return copy.deepcopy(receipt), None
        return await self._change(scope, command, mutate)

    def _check_binding(self, doc, binding):
        if binding != doc['request']['request_hash']:
            doc['state'] = 'voided'
            self._mark_unknown(doc, only_started=True)
            return ApprovalError('hexa_approval_changed')
        return self._active_error(doc)

    def _continuation(self, continuation, binding):
        if not isinstance(continuation, str) or not 1 <= len(continuation) <= 1024 or not self._digest(binding):
            self._invalid()

    async def reserve(self, scope, command, continuation, binding):
        self._continuation(continuation, binding)

        def mutate(doc):
            error = self._check_binding(doc, binding)
            if error:
                return None, error
            if doc['state'] not in ('approved', 'denied'):
                return None, ApprovalError('hexa_approval_not_pending')
            if 'continuation' in doc and doc['continuation'] != continuation:
                return None, ApprovalError('hexa_approval_conflict')
            doc['continuation'] = continuation
            return self._view(doc), None
        return await self._change(scope, command, mutate)

    async def start(self, scope, command, continuation, binding, *, native_allowed):
        self._continuation(continuation, binding)
        if type(native_allowed) is not bool:
            self._invalid()

        def mutate(doc):
            error = self._check_binding(doc, binding)
            if error:
                return None, error
            if doc['state'] != 'approved':
                return None, ApprovalError('hexa_approval_not_pending')
            if doc.get('continuation') != continuation:
                return None, ApprovalError('hexa_approval_not_pending')
            if not native_allowed:
                doc['state'] = 'voided'
                self._mark_unknown(doc, only_started=True)
                return None, ApprovalError('hexa_approval_changed')
            if doc['receipt']['side_effect_state'] != 'not_started':
                return False, None
            doc['receipt']['side_effect_state'] = 'started'
            return True, None
        return await self._change(scope, command, mutate)

    async def finish(self, scope, command, continuation, outcome):
        if outcome not in ('completed', 'failed'):
            self._invalid()

        def mutate(doc):
            if doc.get('continuation') != continuation or doc['state'] != 'approved':
                return None, ApprovalError('hexa_approval_not_pending')
            current = doc['receipt']['side_effect_state']
            if current == outcome:
                return self._view(doc), None
            if current != 'started':
                return None, ApprovalError('hexa_approval_conflict')
            doc['receipt']['side_effect_state'] = outcome
            return self._view(doc), None
        return await self._change(scope, command, mutate)

    @staticmethod
    def _mark_unknown(doc, *, only_started=False):
        receipt = doc.get('receipt')
        if (receipt and receipt['decision'] == 'approve' and
                (receipt['side_effect_state'] == 'started' or
                 (not only_started and 'continuation' in doc and receipt['side_effect_state'] == 'not_started'))):
            receipt.update(side_effect_state='unknown', reconciliation_required=True)

    async def void(self, scope, command):
        def mutate(doc):
            self._mark_unknown(doc, only_started=True)
            doc['state'] = 'voided'
            return self._view(doc), None
        return await self._change(scope, command, mutate)

    async def recover(self, scope, command):
        """Called only after the owning runtime/lease is confirmed stopped.

        This is deliberately not an automatic read/start hook: recovering a live
        owner would discard its result. Unknown requires native reconciliation,
        which is outside this journal's authority.
        """
        def mutate(doc):
            self._mark_unknown(doc)
            return self._view(doc), None
        return await self._change(scope, command, mutate)
