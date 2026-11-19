import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.gateway.client import GatewayClient


PAYLOAD = {'name': '研究模板', 'description': '客户研究流程', 'base': 'codex', 'default_model': 'm1', 'system_prompt': '保持严谨'}


def login(client):
    assert client.post('/api/hexa/auth/login', json={'username': 'admin', 'password': 'correct-password'}).status_code == 200


def test_custom_templates_persist_edit_delete_and_are_separate_from_workflows(client, app):
    login(client)
    created = client.post('/api/hexa/agent-templates', json=PAYLOAD)
    assert created.status_code == 201
    row = created.json()
    assert row == {**PAYLOAD, 'id': row['id'], 'source': 'custom', 'available': True}
    with TestClient(create_app(app.state.settings, app.state.gateway)) as restarted:
        login(restarted)
        assert restarted.get('/api/hexa/agent-templates').json()['templates'] == [row]
        updated = restarted.put(f"/api/hexa/agent-templates/{row['id']}", json={**PAYLOAD, 'name': '修改后'})
        assert updated.status_code == 200
        assert updated.json()['name'] == '修改后'
        assert restarted.get('/api/hexa/templates').json()['templates'] == []
        assert restarted.delete(f"/api/hexa/agent-templates/{row['id']}").status_code == 204
        assert restarted.get('/api/hexa/agent-templates').json() == {'templates': []}


def test_template_auth_validation_and_ownership(client, app):
    for path in ('/api/hexa/agent-templates', '/api/hexa/agent-templates/gateway'):
        assert client.get(path).status_code == 401
    assert client.post('/api/hexa/agent-templates', json=PAYLOAD).status_code == 401
    assert client.put('/api/hexa/agent-templates/1', json=PAYLOAD).status_code == 401
    assert client.delete('/api/hexa/agent-templates/1').status_code == 401
    login(client)
    for field in ('name', 'base', 'default_model'):
        assert client.post('/api/hexa/agent-templates', json={**PAYLOAD, field: '  '}).status_code == 422
    assert client.post('/api/hexa/agent-templates', json={**PAYLOAD, 'system_prompt': 'x' * 20001}).status_code == 422
    from app.db.models import AgentTemplate
    with app.state.session_factory() as db:
        other = AgentTemplate(user_id=999, **PAYLOAD)
        db.add(other)
        db.commit()
        foreign_id = other.id
    assert client.get('/api/hexa/agent-templates').json() == {'templates': []}
    assert client.put(f'/api/hexa/agent-templates/{foreign_id}', json=PAYLOAD).status_code == 404
    assert client.delete(f'/api/hexa/agent-templates/{foreign_id}').status_code == 404


@pytest.mark.asyncio
async def test_gateway_templates_map_existing_bases_and_safe_fields(monkeypatch):
    def handler(request):
        assert request.url.path == '/v1/bases'
        assert request.headers['authorization'] == 'Bearer server-key'
        return httpx.Response(200, json={'bases': [
            {'id': 'codex', 'label': 'Codex', 'status': 'ready', 'defaultModel': 'unavailable', 'systemPrompt': 'Code carefully', 'models': [{'id': 'unavailable', 'available': False}, {'id': 'm1', 'available': True}], 'env': {'SECRET': 'private'}},
            {'id': 'pi', 'label': 'Pi', 'status': 'not_installed', 'models': []},
        ]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    rows = await GatewayClient('http://gateway.test', 'server-key').list_agent_templates()
    assert rows == [
        {'id': 'codex', 'name': 'Codex', 'description': '', 'base': 'codex', 'default_model': 'm1', 'system_prompt': 'Code carefully', 'source': 'gateway', 'available': True},
        {'id': 'pi', 'name': 'Pi', 'description': '', 'base': 'pi', 'default_model': '', 'system_prompt': '', 'source': 'gateway', 'available': False},
    ]


@pytest.mark.asyncio
async def test_gateway_workspace_calls_use_api_key(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'workspaces': [], 'default_workspace_id': 'default'})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))

    result = await GatewayClient('http://gateway.test', 'server-key', cookie='hr_selfhost=session').list_workspaces()

    assert result == {'workspaces': [], 'default_workspace_id': 'default'}
    assert seen[0].headers['authorization'] == 'Bearer server-key'
    assert 'x-harness-internal' not in seen[0].headers
    assert seen[0].headers['cookie'] == 'hr_selfhost=session'


def test_gateway_template_failure_does_not_block_custom_templates(client, app):
    login(client)
    assert client.post('/api/hexa/agent-templates', json=PAYLOAD).status_code == 201
    async def failed():
        raise RuntimeError('Authorization: Bearer server-only-gateway-key')
    app.state.gateway.list_agent_templates = failed
    response = client.get('/api/hexa/agent-templates/gateway')
    assert response.status_code == 502
    assert response.json() == {'detail': 'Gateway 模板暂时无法读取，请重试。'}
    assert client.get('/api/hexa/agent-templates').json()['templates'][0]['name'] == PAYLOAD['name']


def test_missing_template_table_is_recreated_on_application_start(client, app):
    login(client)
    from app.db.models import AgentTemplate

    engine = app.state.session_factory.kw['bind']
    AgentTemplate.__table__.drop(engine)

    response = client.get('/api/hexa/agent-templates')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Agent 模板存储尚未就绪，请重启应用或执行数据库迁移。'}

    with TestClient(create_app(app.state.settings, app.state.gateway)) as restarted:
        login(restarted)
        response = restarted.get('/api/hexa/agent-templates')

    assert response.status_code == 200
    assert response.json() == {'templates': []}


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'bases': None}, {'bases': [None]}, {'bases': [{'id': ''}]}])
async def test_malformed_gateway_catalog_is_an_error_not_an_empty_success(monkeypatch, payload):
    from app.gateway.client import GatewayError
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), **kwargs))
    with pytest.raises(GatewayError):
        await GatewayClient('http://gateway.test', 'server-key').list_agent_templates()
