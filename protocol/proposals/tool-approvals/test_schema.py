"""Proposal shape checks only; not live tool-approval conformance."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


SCHEMA = json.loads(Path(__file__).with_name('schema.json').read_text(encoding='utf-8'))


def validate(value, definition):
    Draft202012Validator({**SCHEMA, 'oneOf': [{'$ref': f'#/$defs/{definition}'}]}).validate(value)


def request():
    return {'id': 'approval_1', 'type': 'tool_approval_request', 'status': 'completed',
            'command_id': 'cmd_1', 'request_hash': 'a' * 64, 'canonicalization': 'RFC8785-v1',
            'policy_digest': 'b' * 64, 'capability_digest': 'c' * 64,
            'tool': {'name': 'write', 'origin': 'direct'}, 'preview': 'Write report', 'expires_at': 1800000000}


def test_request_and_plugin_provenance():
    Draft202012Validator.check_schema(SCHEMA)
    value = request()
    validate(value, 'Request')
    value['tool']['origin'] = 'plugin'
    with pytest.raises(ValidationError):
        validate(value, 'Request')
    value['tool'].update(plugin_name='report', plugin_version='1.0.0', plugin_digest='d' * 64)
    validate(value, 'Request')


@pytest.mark.parametrize('field', ['command_id', 'request_hash', 'expires_at', 'capability_digest'])
def test_request_binding_fields_are_required(field):
    value = request()
    value.pop(field)
    with pytest.raises(ValidationError):
        validate(value, 'Request')


def test_decision_and_unknown_receipt_require_explicit_reconciliation():
    decision = {'type': 'tool_approval_response', 'approval_id': 'approval_1', 'command_id': 'cmd_1',
                'request_hash': 'a' * 64, 'decision': 'approve'}
    validate(decision, 'Decision')
    receipt = {key: value for key, value in decision.items() if key != 'type'}
    receipt.update(side_effect_state='unknown', reconciliation_required=True)
    validate(receipt, 'Receipt')
    invalid = copy.deepcopy(receipt)
    invalid['reconciliation_required'] = False
    with pytest.raises(ValidationError):
        validate(invalid, 'Receipt')
    invalid.update(decision='deny', side_effect_state='started')
    with pytest.raises(ValidationError):
        validate(invalid, 'Receipt')


def test_denial_continuation_unknown_is_separate_from_tool_effects():
    value = {'decision': 'deny', 'state': 'unknown', 'reconciliation_required': True}
    validate(value, 'ContinuationReceipt')
    for changes in ({'reconciliation_required': False}, {'decision': 'approve'}, {'state': 'not_started'}):
        with pytest.raises(ValidationError):
            validate({**value, **changes}, 'ContinuationReceipt')
    completed = {**value, 'state': 'completed', 'reconciliation_required': False}
    validate(completed, 'ContinuationReceipt')
    with pytest.raises(ValidationError):
        validate({**completed, 'reconciliation_required': True}, 'ContinuationReceipt')
