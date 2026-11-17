def login(client):
    response = client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})
    assert response.status_code == 200


def test_conversation_message_persists_previous_response_and_replays_idempotency(client):
    login(client)
    created = client.post("/api/hexa/conversations", json={"title": "产品讨论"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    first = client.post(
        f"/api/hexa/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": "message-1"},
        json={"text": "开始分析", "previous_response_id": None},
    )
    assert first.status_code == 202
    assert first.json()["accepted"] is True
    assert first.json()["message"]["text"] == "开始分析"

    replay = client.post(
        f"/api/hexa/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": "message-1"},
        json={"text": "开始分析", "previous_response_id": None},
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()

    follow_up = client.post(
        f"/api/hexa/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": "message-2"},
        json={"text": "继续", "previous_response_id": "resp-1"},
    )
    assert follow_up.status_code == 202

    conversation = client.get(f"/api/hexa/conversations/{conversation_id}")
    assert conversation.status_code == 200
    assert conversation.json()["previous_response_id"] == "resp-1"
    assert [item["text"] for item in conversation.json()["messages"]] == ["开始分析", "已处理：开始分析", "继续", "已处理：继续"]


def test_conversation_lookup_is_authenticated_and_missing_id_is_safe(client):
    response = client.get("/api/hexa/conversations/999999")
    assert response.status_code == 401

    login(client)
    response = client.get("/api/hexa/conversations/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "会话不存在。"}


def test_pending_idempotency_is_not_replayed_as_a_new_gateway_task(client, app):
    login(client)
    conversation_id = client.post("/api/hexa/conversations", json={"title": "恢复测试"}).json()["id"]
    with app.state.session_factory() as db:
        from app.db.models import IdempotencyRequest
        db.add(IdempotencyRequest(user_id=1, key="pending-1", status="pending"))
        db.commit()

    response = client.post(
        f"/api/hexa/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": "pending-1"},
        json={"text": "不确定", "previous_response_id": None},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "请求状态不确定，请先刷新会话状态。"}


def test_conversation_list_and_status_are_available_for_refresh_recovery(client):
    login(client)
    created = client.post("/api/hexa/conversations", json={"title": "恢复入口"})
    conversation_id = created.json()["id"]

    listing = client.get("/api/hexa/conversations")
    assert listing.status_code == 200
    assert listing.json()["conversations"][0]["id"] == conversation_id

    status = client.get(f"/api/hexa/conversations/{conversation_id}/status")
    assert status.status_code == 200
    assert status.json() == {"conversation_id": conversation_id, "status": "idle", "response_id": None, "error": None}


def test_gateway_failure_keeps_user_message_and_marks_conversation_failed(client, app):
    class BrokenGateway:
        async def create_response(self, text, previous_response_id, idempotency_key, **kwargs):
            from app.gateway.client import GatewayError
            raise GatewayError("Gateway 请求失败。")

    app.state.gateway = BrokenGateway()
    login(client)
    conversation_id = client.post("/api/hexa/conversations", json={"title": "失败恢复"}).json()["id"]

    response = client.post(
        f"/api/hexa/conversations/{conversation_id}/messages",
        headers={"Idempotency-Key": "message-failed"},
        json={"text": "请保留这条输入", "previous_response_id": None},
    )
    assert response.status_code == 502

    conversation = client.get(f"/api/hexa/conversations/{conversation_id}")
    assert conversation.json()["messages"] == [{"id": 1, "role": "user", "text": "请保留这条输入"}]
    assert client.get(f"/api/hexa/conversations/{conversation_id}/status").json()["status"] == "failed"


def test_follow_up_uses_server_response_and_rejects_cross_conversation_replay(client, app):
    login(client)
    cid = client.post('/api/hexa/conversations', json={'title': 'one'}).json()['id']
    other = client.post('/api/hexa/conversations', json={'title': 'two'}).json()['id']
    for key, previous in [('first', 'untrusted-id'), ('follow-up', None)]:
        assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': key}, json={'text': 'hello', 'previous_response_id': previous}).status_code == 202
    assert [call[1] for call in app.state.gateway.calls] == [None, 'resp-1']
    assert client.post(f'/api/hexa/conversations/{other}/messages', headers={'Idempotency-Key': 'first'}, json={'text': 'hello'}).status_code == 409
    assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'first'}, json={'text': 'changed'}).status_code == 409


def test_transport_error_preserves_unknown_request_and_prevents_new_submission(client, app):
    class DisconnectedGateway:
        async def create_response(self, *args, **kwargs):
            import httpx
            raise httpx.ReadError('private upstream body')
    app.state.gateway = DisconnectedGateway()
    login(client)
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    request = {'headers': {'Idempotency-Key': 'unknown'}, 'json': {'text': 'preserve'}}
    assert client.post(f'/api/hexa/conversations/{cid}/messages', **request).status_code == 502
    assert client.post(f'/api/hexa/conversations/{cid}/messages', **request).status_code == 409
    assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'new'}, json={'text': 'preserve'}).status_code == 409
    snapshot = client.get(f'/api/hexa/conversations/{cid}').json()
    assert len(snapshot['messages']) == 1
    assert client.get(f'/api/hexa/conversations/{cid}/status').json()['status'] == 'unknown'


def test_failed_request_replay_retains_failure_http_status(client, app):
    class BrokenGateway:
        async def create_response(self, *args, **kwargs):
            from app.gateway.client import GatewayError
            raise GatewayError('Gateway 请求失败。')
    app.state.gateway = BrokenGateway()
    login(client)
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    for _ in range(2):
        result = client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'failed'}, json={'text': 'hi'})
        assert result.status_code == 502


def test_agent_model_are_fixed_at_creation_and_reused_after_refresh(client, app):
    login(client)
    made = client.post('/api/hexa/conversations', json={'title': 'identity', 'agent_id': 'agent-1', 'model': 'gpt-6.1'})
    cid = made.json()['id']
    assert client.get(f'/api/hexa/conversations/{cid}').json()['agent_id'] == 'agent-1'
    assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'identity'}, json={'text': 'hi'}).status_code == 202
    assert app.state.gateway.calls[-1][3]['agent_id'] == 'agent-1'
    assert app.state.gateway.calls[-1][3]['model'] == 'gpt-6.1'


def test_status_recovers_known_response_without_posting_again(client, app):
    class RecoveringGateway:
        async def create_response(self, *args, **kwargs):
            from app.gateway.client import GatewayError
            raise GatewayError('interrupted', uncertain=True, response_id='recover-id')
        async def get_response(self, rid):
            assert rid == 'recover-id'
            return {'id': rid, 'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '恢复的答案'}]}]}
    app.state.gateway = RecoveringGateway()
    login(client)
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'recover'}, json={'text': 'hello'}).status_code == 502
    for _ in range(2):
        assert client.get(f'/api/hexa/conversations/{cid}/status').json()['status'] == 'completed'
    snapshot = client.get(f'/api/hexa/conversations/{cid}').json()
    assert [m['text'] for m in snapshot['messages']] == ['hello', '恢复的答案']
