"""Real local blob/control backing and ASGI; no claim of native interception."""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw
import control_store
from tool_approvals import ApprovalJournal, ApprovalScope

AUTHENTICATE = gw._principal


@pytest.fixture
def pending(monkeypatch):
    identity = uuid.uuid4().hex
    scope = ApprovalScope('approval-http-org', 'owner', f'hsess_{identity}', f'resp_{identity}')
    value = {'id': f'approval_{identity}', 'type': 'tool_approval_request', 'status': 'completed',
             'command_id': f'command-{identity}', 'request_hash': 'a' * 64, 'canonicalization': 'RFC8785-v1',
             'policy_digest': 'b' * 64, 'capability_digest': 'c' * 64,
             'tool': {'name': 'write', 'origin': 'runtime'}, 'preview': 'Write report',
             'expires_at': int(time.time()) + 300}
    principal = {'org': scope.org, 'member': scope.principal}
    async def who(request):
        return dict(principal)
    monkeypatch.setattr(gw, '_principal', who)
    record = {'id': scope.response, 'object': 'response', 'created_at': int(time.time()),
              'model': 'fixture', 'status': 'incomplete', 'output': [value],
              '_org': scope.org, '_member': scope.principal, '_session_id': scope.session,
              '_tool_approval_commands': {value['id']: value['command_id']},
              'incomplete_details': {'reason': 'tool_approval_required'}}
    async def seed():
        journal = await ApprovalJournal.configured_control_store()
        await journal.create(scope, value)
        await gw._vertex_upsert(scope.session, {'tenant': scope.org, 'member': scope.principal,
                                                'workspace': 'approval-workspace', 'status': 'incomplete',
                                                'harness_id': 'harness-a'})
        await gw._blob_put(f'responses/{scope.response}.json', json.dumps(record).encode(), kb=gw.RESP_BLOB_KB)
    asyncio.run(seed())
    return TestClient(gw.app), scope, value, record, principal


def path(scope, value):
    return f'/v1/responses/{scope.response}/tool-approvals/{value["id"]}'


def decision(value, **changes):
    return {'type': 'tool_approval_response', 'approval_id': value['id'], 'command_id': value['command_id'],
            'request_hash': value['request_hash'], 'decision': 'approve', **changes}


def post(api, scope, value, body=None, key='decision-key'):
    return api.post(path(scope, value), json=body or decision(value),
                    headers={'Idempotency-Key': key} if key is not None else {})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()['error']['code'] == code
    assert response.headers['UHP-Version'] == gw.UHP_VERSION


def persist(scope, record):
    gw._resp_cache_forget(scope.response)
    asyncio.run(gw._blob_put(f'responses/{scope.response}.json', json.dumps(record).encode(), kb=gw.RESP_BLOB_KB))


def test_http_read_decide_replay_and_reopened_store_never_dispatch(pending, monkeypatch):
    api, scope, value, record, _ = pending
    async def no_execution(*args, **kwargs):
        pytest.fail('decision/read must never start a runtime')
    monkeypatch.setattr(gw, '_resp_execute', no_execution)
    response = api.get(path(scope, value))
    assert response.status_code == 200, response.text
    assert response.json() == {'request': value, 'state': 'pending'}
    assert response.headers['Cache-Control'] == 'no-store'
    first = post(api, scope, value)
    assert first.status_code == 200, first.text
    assert first.json()['side_effect_state'] == 'not_started'
    assert post(api, scope, value).json() == first.json()
    monkeypatch.setattr(control_store, '_cont', None)
    reopened = TestClient(gw.app).get(path(scope, value))
    assert reopened.json()['state'] == 'approved'
    assert reopened.json()['receipt'] == first.json()
    assert '_tool_approval_commands' not in api.get(f'/v1/responses/{scope.response}').json()
    assert_error(post(api, scope, value, decision(value, decision='deny')), 409, 'hexa_approval_conflict')
    assert_error(post(api, scope, value, key='other'), 409, 'hexa_approval_conflict')
    assert asyncio.run(gw._resp_get(scope.response))['status'] == 'incomplete'


@pytest.mark.parametrize('change', ['member', 'org', 'missing_member', 'workspace', 'calibration', 'deleted_session',
                                     'legacy_owner', 'session_mismatch', 'wrong_mapping', 'unknown_approval'])
def test_other_principals_scopes_or_mapping_cannot_read_or_decide(pending, change):
    api, scope, value, record, principal = pending
    if change in ('member', 'org'):
        principal[change] = 'stranger'
    elif change == 'missing_member':
        principal.pop('member')
    elif change == 'workspace':
        principal['workspace'] = 'another-workspace'
        principal['via'] = 'api_key'
    elif change == 'calibration':
        principal['calibration'] = {'inner': 'another-harness'}
    elif change == 'deleted_session':
        asyncio.run(gw._vertex_upsert(scope.session, {'status': 'deleted'}))
    elif change == 'legacy_owner':
        record.pop('_member')
        persist(scope, record)
    elif change == 'session_mismatch':
        record['_session_id'] = 'hsess_missing'
        persist(scope, record)
    elif change == 'wrong_mapping':
        record['_tool_approval_commands'][value['id']] = 'another-command'
        persist(scope, record)
    else:
        value = {**value, 'id': 'approval_unknown'}
    assert_error(api.get(path(scope, value)), 404, 'hexa_approval_not_found')
    assert_error(post(api, scope, value), 404, 'hexa_approval_not_found')


@pytest.mark.parametrize('body,key', [(None, None), (None, ''), (None, 'x' * 256),
                                     ({'type': 'tool_approval_response'}, 'k'),
                                     ({'arguments': 'private-payload-marker'}, 'k'),
                                     (['private-payload-marker'], 'k')])
def test_bad_decision_or_key_is_refused_without_payload_leak(pending, body, key):
    api, scope, value, _, _ = pending
    response = post(api, scope, value, body, key)
    assert_error(response, 422, 'hexa_approval_invalid')
    assert 'private-payload-marker' not in response.text
    assert api.get(path(scope, value)).json()['state'] == 'pending'


def test_decision_body_cannot_address_another_approval(pending):
    api, scope, value, _, _ = pending
    assert_error(post(api, scope, value, decision(value, approval_id='approval_forged')),
                 409, 'hexa_approval_conflict')
    assert api.get(path(scope, value)).json()['state'] == 'pending'


def test_expired_request_reads_as_expired_and_cannot_be_decided(pending):
    api, scope, value, _, _ = pending
    async def expire():
        journal = await ApprovalJournal.configured_control_store()
        journal.clock = lambda: value['expires_at'] + 1
        await journal.read(scope, value['command_id'])
    asyncio.run(expire())
    assert api.get(path(scope, value)).json()['state'] == 'expired'
    assert_error(post(api, scope, value), 410, 'hexa_approval_expired')


@pytest.mark.parametrize('operation', ['cancel', 'delete'])
def test_response_cancellation_or_deletion_voids_journal_first(pending, operation):
    api, scope, value, _, _ = pending
    assert post(api, scope, value).status_code == 200
    endpoint = f'/v1/responses/{scope.response}'
    result = api.post(endpoint + '/cancel') if operation == 'cancel' else api.delete(endpoint)
    assert result.status_code == 200, result.text
    async def read():
        return await (await ApprovalJournal.configured_control_store()).read(scope, value['command_id'])
    stored = asyncio.run(read())
    assert stored['state'] == 'voided'
    assert stored['receipt']['side_effect_state'] == 'not_started'


@pytest.mark.parametrize('method', ['GET', 'POST', 'CANCEL', 'DELETE'])
def test_journal_outage_fails_closed_without_exposing_exception(pending, monkeypatch, method):
    api, scope, value, _, _ = pending
    async def unavailable(*args, **kwargs):
        raise OSError('private-store-marker')
    monkeypatch.setattr(control_store._cont, 'read_item', unavailable)
    if method == 'GET':
        response = api.get(path(scope, value))
    elif method == 'POST':
        response = post(api, scope, value)
    elif method == 'CANCEL':
        response = api.post(f'/v1/responses/{scope.response}/cancel')
    else:
        response = api.delete(f'/v1/responses/{scope.response}')
    assert_error(response, 503, 'hexa_approval_unavailable')
    assert 'private-store-marker' not in response.text
    assert asyncio.run(gw._resp_get(scope.response))['status'] == 'incomplete'


@pytest.mark.parametrize('body', [
    {'tool_approval_policy': {'require': ['external_write']}, 'input': 'write'},
    {'tool_approval_policy': None, 'input': 'write'},
    {'input': [{'type': 'tool_approval_response', 'approval_id': 'forged'}]},
    {'input': {'type': 'tool_approval_response', 'approval_id': 'forged'}},
])
def test_unsupported_policy_or_approval_input_is_refused_before_any_forward_or_execution(pending, monkeypatch, body):
    api, scope, value, _, _ = pending
    async def no_work(*args, **kwargs):
        pytest.fail('approval admission must precede external lookup and idempotency replay')
    monkeypatch.setattr(gw, '_uhp_target', no_work)
    monkeypatch.setattr(control_store, 'idem_get', no_work)
    monkeypatch.setattr(gw, '_resp_execute', no_work)
    response = api.post('/v1/responses', json={**body, 'metadata': {'harness_id': 'external'}},
                        headers={'Idempotency-Key': 'cannot-replay'})
    assert_error(response, 422, 'hexa_approval_unavailable')
    assert api.get('/v1/uhp').json()['capabilities'].get('tool_approvals', False) is False


def test_ordinary_continuation_cannot_skip_an_approval(pending, monkeypatch):
    api, scope, value, _, _ = pending
    async def no_execution(*args, **kwargs):
        pytest.fail('a pending approval cannot become a normal chat continuation')
    monkeypatch.setattr(gw, '_resp_execute', no_execution)
    response = api.post('/v1/responses', json={'previous_response_id': scope.response, 'input': 'go on'})
    assert_error(response, 422, 'hexa_approval_unavailable')
    assert api.get(path(scope, value)).json()['state'] == 'pending'


def test_session_only_continuation_cannot_skip_an_approval(pending, monkeypatch):
    api, scope, value, _, _ = pending
    asyncio.run(gw._vg_upsert('HarnessResponse', scope.response, {
        'org': scope.org, 'session_id': scope.session, 'status': 'incomplete', 'created_at': str(time.time())}))
    async def no_lookup(*args, **kwargs):
        pytest.fail('session approval must be checked before harness/provider routing')
    monkeypatch.setattr(gw, '_uhp_target', no_lookup)
    result = api.post('/v1/responses', json={'metadata': {'session_id': scope.session, 'harness_id': 'external'},
                                            'input': 'go on'})
    assert_error(result, 422, 'hexa_approval_unavailable')


@pytest.mark.parametrize('method', ['GET', 'POST', 'CONTINUE'])
def test_strict_response_read_failure_returns_safe_retryable_error(pending, monkeypatch, method):
    api, scope, value, _, _ = pending
    gw._resp_cache_forget(scope.response)
    async def failed(*args, **kwargs):
        raise gw.backing.BlobUnavailable('private-blob-marker')
    monkeypatch.setattr(gw, '_blob_get_or_raise', failed)
    if method == 'GET':
        result = api.get(path(scope, value))
    elif method == 'POST':
        result = post(api, scope, value)
    else:
        result = api.post('/v1/responses', json={'previous_response_id': scope.response, 'input': 'continue'})
    assert_error(result, 503, 'hexa_approval_unavailable')
    assert 'private-blob-marker' not in result.text


@pytest.mark.parametrize('operation', ['cancel', 'delete'])
def test_foreign_member_cannot_invalidate_owner_approval(pending, operation):
    api, scope, value, _, principal = pending
    principal['member'] = 'another-member'
    endpoint = f'/v1/responses/{scope.response}'
    result = api.post(endpoint + '/cancel') if operation == 'cancel' else api.delete(endpoint)
    assert_error(result, 404, 'hexa_approval_not_found')
    principal['member'] = scope.principal
    assert api.get(path(scope, value)).json()['state'] == 'pending'


def test_authenticated_local_http_decision_journey_with_real_server(pending, monkeypatch):
    """Actual TCP, real internal-header authentication and durable local storage.

    Native dispatch is intentionally unavailable and is not represented by this journey.
    """
    import socket
    import threading
    import httpx
    import uvicorn
    _, scope, value, _, _ = pending
    monkeypatch.setattr(gw, '_principal', AUTHENTICATE)
    headers = {'x-harness-internal': gw.INTERNAL_KEY, 'x-harness-org': scope.org,
               'x-harness-member': scope.principal}
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(gw.app, log_level='error', lifespan='off'))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    worker.start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{listener.getsockname()[1]}', headers=headers, timeout=10) as client:
            result = client.get(path(scope, value))
            assert result.status_code == 200, result.text
            assert result.json()['state'] == 'pending'
            result = client.post(path(scope, value), json=decision(value), headers={'Idempotency-Key': 'tcp-decision'})
            assert result.status_code == 200, result.text
            assert result.json()['side_effect_state'] == 'not_started'
            assert client.post(path(scope, value), json=decision(value), headers={'Idempotency-Key': 'tcp-decision'}).json() == result.json()
            assert_error(client.get(path(scope, value), headers={'x-harness-member': 'stranger'}),
                         404, 'hexa_approval_not_found')
            assert client.post(f'/v1/responses/{scope.response}/cancel').status_code == 200
            assert client.get(path(scope, value)).json()['state'] == 'voided'
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        assert not worker.is_alive()


@pytest.mark.parametrize('operation', ['decision', 'cancel', 'delete'])
def test_journal_write_failure_does_not_report_decision_or_cancellation_success(pending, monkeypatch, operation):
    api, scope, value, _, _ = pending
    async def failed(*args, **kwargs):
        raise OSError('private-write-marker')
    monkeypatch.setattr(control_store._cont, 'replace_item', failed)
    if operation == 'decision':
        response = post(api, scope, value)
    elif operation == 'cancel':
        response = api.post(f'/v1/responses/{scope.response}/cancel')
    else:
        response = api.delete(f'/v1/responses/{scope.response}')
    assert_error(response, 503, 'hexa_approval_unavailable')
    assert 'private-write-marker' not in response.text
    assert api.get(path(scope, value)).json()['state'] == 'pending'


def test_mapping_cannot_alias_an_existing_command_under_another_approval_id(pending):
    api, scope, value, record, _ = pending
    other = 'approval_alias'
    record['_tool_approval_commands'][other] = value['command_id']
    persist(scope, record)
    assert_error(api.get(path(scope, {**value, 'id': other})), 404, 'hexa_approval_not_found')


def test_bad_mapping_cancellation_does_not_claim_to_cancel_unchecked_calls(pending):
    api, scope, value, record, _ = pending
    record['_tool_approval_commands'] = ['invalid']
    persist(scope, record)
    assert_error(api.post(f'/v1/responses/{scope.response}/cancel'), 503, 'hexa_approval_unavailable')
    async def read():
        return await (await ApprovalJournal.configured_control_store()).read(scope, value['command_id'])
    assert asyncio.run(read())['state'] == 'pending'


def test_unrecognized_model_output_item_does_not_create_addressable_approval(pending):
    api, scope, value, record, _ = pending
    record.pop('_tool_approval_commands')
    persist(scope, record)
    assert_error(api.get(path(scope, value)), 404, 'hexa_approval_not_found')


def test_http_rejects_malformed_json_without_echoing_bytes(pending):
    api, scope, value, _, _ = pending
    response = api.post(path(scope, value), content=b'{private-json-marker',
                        headers={'Idempotency-Key': 'key', 'Content-Type': 'application/json'})
    assert_error(response, 422, 'hexa_approval_invalid')
    assert 'private-json-marker' not in response.text


def test_session_authorization_store_failure_is_safe_and_retryable(pending, monkeypatch):
    api, scope, value, _, _ = pending
    async def unavailable(*args, **kwargs):
        raise OSError('private-session-marker')
    monkeypatch.setattr(gw, '_vertex_get', unavailable)
    result = api.get(path(scope, value))
    assert_error(result, 503, 'hexa_approval_unavailable')
    assert 'private-session-marker' not in result.text


def test_session_index_outage_blocks_continuation_before_routing(pending, monkeypatch):
    api, scope, value, _, _ = pending
    async def unavailable(*args, **kwargs):
        raise OSError('private-index-marker')
    monkeypatch.setattr(gw.BACKING.graph, 'find_strict', unavailable)
    result = api.post('/v1/responses', json={'metadata': {'session_id': scope.session}, 'input': 'go on'})
    assert_error(result, 503, 'hexa_approval_unavailable')
    assert 'private-index-marker' not in result.text


def test_cancel_after_started_preserves_unknown_side_effect_state(pending):
    api, scope, value, _, _ = pending
    assert post(api, scope, value).status_code == 200
    async def start():
        journal = await ApprovalJournal.configured_control_store()
        await journal.reserve(scope, value['command_id'], 'resume', value['request_hash'])
        assert await journal.start(scope, value['command_id'], 'resume', value['request_hash'], native_allowed=True)
    asyncio.run(start())
    assert api.post(f'/v1/responses/{scope.response}/cancel').status_code == 200
    record = api.get(path(scope, value)).json()
    assert record['state'] == 'voided'
    assert record['receipt']['side_effect_state'] == 'unknown'
    assert record['receipt']['reconciliation_required'] is True


def test_concurrent_http_decisions_keep_one_durable_winner(pending):
    from concurrent.futures import ThreadPoolExecutor
    api, scope, value, _, _ = pending
    def decide(index):
        return post(api, scope, value, decision(value, decision='approve' if index % 2 else 'deny'), key=f'race-{index}')
    with ThreadPoolExecutor(max_workers=8) as pool:
        replies = list(pool.map(decide, range(8)))
    assert sorted(reply.status_code for reply in replies) == [200] + [409] * 7
    winner = next(reply.json() for reply in replies if reply.status_code == 200)
    assert api.get(path(scope, value)).json()['receipt'] == winner


def test_http_record_and_receipt_conform_to_proposal_shapes(pending):
    from jsonschema import Draft202012Validator
    api, scope, value, _, _ = pending
    schema = json.loads((Path(__file__).resolve().parents[2] /
                         'protocol/proposals/tool-approvals/schema.json').read_text(encoding='utf-8'))
    def validate(payload, name):
        Draft202012Validator({**schema, 'oneOf': [{'$ref': f'#/$defs/{name}'}]}).validate(payload)
    validate(api.get(path(scope, value)).json(), 'Record')
    validate(post(api, scope, value).json(), 'Receipt')
    validate(api.get(path(scope, value)).json(), 'Record')
