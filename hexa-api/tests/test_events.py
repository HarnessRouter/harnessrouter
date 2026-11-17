from tests.test_conversations import login


def test_stream_events_are_durable_and_cancel_uses_known_gateway_id(client, app):
    from app.db.models import Conversation, IdempotencyRequest
    class CancelGateway:
        async def cancel_response(self, response_id):
            assert response_id == 'remote-live'
            return {'id': response_id, 'status': 'cancelled'}
    app.state.gateway = CancelGateway()
    login(client)
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    with app.state.session_factory() as db:
        db.get(Conversation, cid).response_status = 'running'
        db.add(IdempotencyRequest(user_id=1, key='live', conversation_id=cid, response_id='remote-live', status='pending', partial_text='实时中文'))
        db.commit()
    response = client.post(f'/api/hexa/conversations/{cid}/cancel')
    assert response.status_code == 200
    assert response.json()['status'] == 'cancelled'
    events = client.get(f'/api/hexa/conversations/{cid}/events')
    assert events.status_code == 200
    assert '实时中文' in events.text
    assert '"status": "cancelled"' in events.text


def test_cancel_without_response_id_remains_unknown_not_success(client):
    login(client)
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    assert client.post(f'/api/hexa/conversations/{cid}/cancel').status_code == 409
