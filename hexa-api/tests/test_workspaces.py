def login(client):
    response = client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})
    assert response.status_code == 200


def test_workspace_selection_is_scoped_to_authenticated_user(client):
    login(client)

    initial = client.get("/api/hexa/workspaces")
    assert initial.status_code == 200
    assert initial.json() == {"workspaces": [], "selected_id": None}

    created = client.post("/api/hexa/workspaces", json={"name": "默认工作区", "description": "本机"})
    assert created.status_code == 201
    workspace = created.json()
    assert workspace["name"] == "默认工作区"

    selected = client.post("/api/hexa/workspaces/select", json={"workspace_id": workspace["id"]})
    assert selected.status_code == 200
    assert selected.json() == {"selected_id": workspace["id"]}

    current = client.get("/api/hexa/workspaces")
    assert current.json()["selected_id"] == workspace["id"]


def test_real_gateway_workspace_mapping_is_used_for_execution(client, app):
    login(client)
    workspace = client.post('/api/hexa/workspaces', json={'name': 'Research'}).json()
    cid = client.post('/api/hexa/conversations', json={'workspace_id': workspace['id']}).json()['id']
    assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'scope'}, json={'text': 'hello'}).status_code == 202
    assert app.state.gateway.calls[-1][3]['workspace_id'] == 'gateway-1'
