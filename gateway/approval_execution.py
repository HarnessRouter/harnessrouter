"""Bound invocation gate for trusted adapters; no native coverage advertised."""
from dataclasses import dataclass
import asyncio
import base64
import copy
import hashlib
import hmac
import json
import os
import uuid

import rfc8785
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from tool_approvals import ApprovalError

MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Invocation:
    command_id: str
    tool: dict
    arguments: bytes
    checkpoint: bytes
    workspace: str
    runtime: dict
    policy_digest: str
    capability_digest: str
    credential_versions: dict
    environment_versions: dict


def canonical_descriptor(value):
    try:
        return rfc8785.dumps(value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ApprovalError('hexa_approval_invalid', 422) from None


class BoundApprovalGate:
    """Internal boundary: scope and current/native facts come from a trusted adapter.

    The adapter must checkpoint before capture, revalidate native policy/config
    under its dispatch lock, and dispatch *only* the returned saved invocation.
    This class supplies no model loop, shell, tool catalog or native checkpoint.
    """
    def __init__(self, journal, key):
        self.journal = journal
        if not isinstance(key, bytes) or len(key) != 32:
            raise ApprovalError('hexa_approval_unavailable', 503)
        self._encryption_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                                   info=b'hexa.approval.encryption.v1').derive(key)
        self._commitment_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                                   info=b'hexa.approval.commitment.v1').derive(key)

    @staticmethod
    def _invalid():
        raise ApprovalError('hexa_approval_invalid', 422)

    def _validate(self, scope, call):
        if not isinstance(call, Invocation):
            self._invalid()
        self.journal._identity(scope, call.command_id)
        if (not isinstance(call.workspace, str) or not 1 <= len(call.workspace) <= 1024
                or not isinstance(call.arguments, bytes) or not 1 <= len(call.arguments) <= MAX_BYTES
                or not isinstance(call.checkpoint, bytes) or not 1 <= len(call.checkpoint) <= MAX_BYTES
                or not isinstance(call.runtime, dict) or set(call.runtime) != {'name', 'version'}
                or any(not isinstance(v, str) or not 1 <= len(v) <= 1024 for v in call.runtime.values())
                or not self.journal._digest(call.policy_digest) or not self.journal._digest(call.capability_digest)):
            self._invalid()
        # Reuse the journal's tool provenance validation rather than maintaining
        # another plugin/MCP identity grammar. This object is never persisted.
        self.journal._validate_request({
            'id': 'approval_validate', 'type': 'tool_approval_request', 'status': 'completed',
            'command_id': call.command_id, 'request_hash': '0' * 64, 'canonicalization': 'RFC8785-v1',
            'policy_digest': call.policy_digest, 'capability_digest': call.capability_digest,
            'tool': call.tool, 'preview': '', 'expires_at': int(self.journal.clock()) + 60})
        for versions in (call.credential_versions, call.environment_versions):
            if (not isinstance(versions, dict) or len(versions) > 100
                    or any(not isinstance(k, str) or not 1 <= len(k) <= 1024
                           or not self.journal._digest(v) for k, v in versions.items())):
                self._invalid()
        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate key')
                result[key] = value
            return result
        def bad_constant(value):
            raise ValueError('nonfinite JSON')
        try:
            decoded = json.loads(call.arguments.decode('utf-8'), object_pairs_hook=object_pairs, parse_constant=bad_constant)
            if not isinstance(decoded, dict):
                self._invalid()
            # Also reject numeric overflow and unpaired surrogate escapes. The
            # canonicalized arguments are validation only; execution uses bytes.
            canonical_descriptor(decoded)
        except (ValueError, UnicodeError, RecursionError):
            self._invalid()

    def _descriptor(self, scope, call):
        self._validate(scope, call)
        def commitment(domain, value):
            return hmac.new(self._commitment_key, domain + b'\x00' + value, hashlib.sha256).hexdigest()
        return {'version': 'hexa.invocation.v1', 'scope': dict(scope.__dict__), 'command_id': call.command_id,
                'workspace': call.workspace, 'runtime': call.runtime, 'tool': call.tool,
                'policy_digest': call.policy_digest, 'capability_digest': call.capability_digest,
                'credential_versions': call.credential_versions, 'environment_versions': call.environment_versions,
                'argument_commitment': commitment(b'arguments', call.arguments),
                'checkpoint_commitment': commitment(b'checkpoint', call.checkpoint)}

    def binding(self, scope, invocation):
        return hashlib.sha256(canonical_descriptor(self._descriptor(scope, invocation))).hexdigest()

    @classmethod
    def from_environment(cls, journal):
        from backing import FileSecretStore
        # Same configured root key derivation as existing encrypted credentials;
        # HKDF above separates the approval keys from every other use.
        return cls(journal, FileSecretStore._derive(os.environ.get('HR_SECRET_KEY', '')))

    def _aad(self, scope, command, binding):
        return canonical_descriptor({'scope': dict(scope.__dict__), 'command_id': command,
                                     'request_hash': binding, 'version': 'hexa.invocation.v1'})

    async def capture(self, scope, invocation, *, expires_at, preview):
        call = copy.deepcopy(invocation)
        descriptor = self._descriptor(scope, call)
        binding = hashlib.sha256(canonical_descriptor(descriptor)).hexdigest()
        payload = {'descriptor': descriptor, 'arguments': base64.b64encode(call.arguments).decode(),
                   'checkpoint': base64.b64encode(call.checkpoint).decode()}
        nonce = os.urandom(12)
        sealed = base64.b64encode(nonce + AESGCM(self._encryption_key).encrypt(
            nonce, canonical_descriptor(payload), self._aad(scope, call.command_id, binding))).decode()
        request = {'id': 'approval_' + uuid.uuid4().hex, 'type': 'tool_approval_request', 'status': 'completed',
                   'command_id': call.command_id, 'request_hash': binding, 'canonicalization': 'RFC8785-v1',
                   'policy_digest': call.policy_digest, 'capability_digest': call.capability_digest,
                   'tool': call.tool, 'preview': preview, 'expires_at': expires_at}
        record = await self.journal.create(scope, request, _sealed_invocation=sealed)
        # A prior unbound record or wrong-key writer cannot masquerade as a
        # successful capture. Random ciphertext from a racing identical capture
        # is fine; the winner must decrypt to the same exact invocation.
        if await self.load(scope, call.command_id) != call:
            raise ApprovalError('hexa_approval_conflict')
        return record

    async def load(self, scope, command):
        request, sealed = await self.journal.trusted_invocation(scope, command)
        try:
            if not isinstance(sealed, str) or len(sealed) > 4 * MAX_BYTES:
                raise ValueError('missing or oversized ciphertext')
            raw = base64.b64decode(sealed, validate=True)
            clear = AESGCM(self._encryption_key).decrypt(raw[:12], raw[12:], self._aad(scope, command, request['request_hash']))
            value = json.loads(clear)
            descriptor = value['descriptor']
            call = Invocation(command_id=descriptor['command_id'], tool=descriptor['tool'],
                              arguments=base64.b64decode(value['arguments'], validate=True),
                              checkpoint=base64.b64decode(value['checkpoint'], validate=True),
                              workspace=descriptor['workspace'], runtime=descriptor['runtime'],
                              policy_digest=descriptor['policy_digest'], capability_digest=descriptor['capability_digest'],
                              credential_versions=descriptor['credential_versions'], environment_versions=descriptor['environment_versions'])
            rebuilt = self._descriptor(scope, call)
            if (descriptor != rebuilt or call.command_id != command
                    or self.binding(scope, call) != request['request_hash']
                    or any(request[key] != getattr(call, key) for key in ('tool', 'policy_digest', 'capability_digest'))):
                raise ValueError('execution binding mismatch')
            return call
        except Exception:
            raise ApprovalError('hexa_approval_unavailable', 503) from None

    async def execute(self, scope, command, continuation, current, *, native_allowed, dispatch):
        saved = await self.load(scope, command)
        current_binding = self.binding(scope, copy.deepcopy(current))
        await self.journal.reserve(scope, command, continuation, current_binding)
        if not await self.journal.start(scope, command, continuation, current_binding, native_allowed=native_allowed):
            return None
        try:
            result = await dispatch(saved)
            await self.journal.finish(scope, command, continuation, 'completed')
            return result
        except BaseException:
            # Exception/timeout/cancellation proves no negative about an external
            # side effect. Never translate it into a retryable failed invocation.
            await asyncio.shield(self.journal.recover(scope, command))
            raise
