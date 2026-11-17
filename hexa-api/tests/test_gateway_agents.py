def test_agents_are_read_through_server_gateway_adapter(client):
    client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})

    response = client.get("/api/hexa/agents")

    assert response.status_code == 200
    assert response.json() == {"agents": [{"id": "agent-1", "name": "产品分析师", "base": "openai", "default_model": "gpt-6.1"}]}
    assert "server-only-gateway-key" not in response.text


def test_agents_require_authentication(client):
    response = client.get("/api/hexa/agents")

    assert response.status_code == 401


def test_agent_models_are_read_through_server_gateway_adapter(client):
    client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})

    response = client.get("/api/hexa/agents/agent-1/models")

    assert response.status_code == 200
    assert response.json()["default"] == "gpt-6.1"
    assert "server-only-gateway-key" not in response.text


def test_agent_create_and_delete_are_server_side_gateway_operations(client):
    client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})

    created = client.post("/api/hexa/agents", json={"name": "新 Agent", "base": "openai", "default_model": "gpt-6.1", "system_prompt": "专注分析"})
    assert created.status_code == 201
    assert created.json()["id"] == "agent-created"
    assert "server-only-gateway-key" not in created.text

    deleted = client.delete("/api/hexa/agents/agent-created")
    assert deleted.status_code == 204


def test_agent_mutations_require_authentication(client):
    assert client.post("/api/hexa/agents", json={"name": "x", "base": "openai", "default_model": "m"}).status_code == 401
    assert client.delete("/api/hexa/agents/agent-created").status_code == 401


def test_gateway_failure_is_redacted(client):
    client.app.state.gateway = BrokenGateway()
    client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})

    response = client.get("/api/hexa/agents")

    assert response.status_code == 502
    assert response.json() == {"detail": "Gateway 暂时无法读取 Agent。"}
    assert "server-only-gateway-key" not in response.text


class BrokenGateway:
    async def list_agents(self, api_key: str) -> list[dict[str, str]]:
        raise RuntimeError(f"upstream body contains {api_key}")
