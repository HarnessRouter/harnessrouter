from __future__ import annotations

import json
import types

from app.tasks.service import capability_snapshot


def test_capability_snapshot_keeps_sources_and_omits_secrets():
    agent = {
        "id": "agent-1",
        "base": "claude-code",
        "mcpServers": [{
            "name": "direct-search", "transport": "http", "url": "https://mcp.example/search",
            "headers": {"authorization": "Bearer secret"},
        }],
        "skills": [{"name": "direct-skill", "description": "direct"}],
        "disabledTools": ["shell_exec"],
        "plugins": [{
            "name": "research-pack", "enabled": True,
            "manifest": {"name": "research-pack", "version": "1.2.0", "description": "research"},
            "mcpServers": [{
                "name": "plugin-search", "transport": "stdio", "command": "./bin/search",
                "env": {"TOKEN": "secret"},
            }],
            "skills": [{"name": "plugin-skill", "description": "plugin"}], "skipped": [],
        }, {
            "name": "disabled-pack", "enabled": False,
            "manifest": {"name": "disabled-pack", "version": "1.0.0"},
            "mcpServers": [], "skills": [], "skipped": [],
        }],
    }
    result = capability_snapshot(agent, {
        "versions": ["2026-10-19"], "capabilities": {"plugins": True},
    })
    assert result["agent_id"] == "agent-1"
    assert result["discovery"]["capabilities"]["plugins"] is True
    assert result["disabled_tools"] == ["shell_exec"]
    assert {item["source"] for item in result["components"]} == {"direct", "plugin"}
    assert {item["name"] for item in result["plugins"]} == {"research-pack", "disabled-pack"}
    assert result["plugins"][1]["enabled"] is False
    assert "secret" not in json.dumps(result)
    assert result["digest"]


def test_run_preflight_rejects_skipped_enabled_plugin(client, app):
    assert client.post('/api/hexa/auth/login', json={
        'username': 'admin', 'password': 'correct-password',
    }).status_code == 200

    async def discovery(self):
        return {'versions': ['2026-10-19'], 'capabilities': {'plugins': True}}

    async def capabilities(self, agent_id):
        return {
            'id': agent_id, 'base': 'claude-code', 'mcpServers': [], 'skills': [],
            'disabledTools': [], 'plugins': [{
                'name': 'broken-pack', 'enabled': True,
                'manifest': {'name': 'broken-pack', 'version': '1.0.0'},
                'mcpServers': [], 'skills': [],
                'skipped': [{'path': 'skills/broken', 'reason': 'invalid skill'}],
            }],
        }

    app.state.gateway.get_uhp_discovery = types.MethodType(discovery, app.state.gateway)
    app.state.gateway.get_agent_capabilities = types.MethodType(capabilities, app.state.gateway)
    task = client.post('/api/hexa/tasks', json={
        'title': 'Plugin preflight',
        'workflow': {'nodes': [{'id': 'a', 'agent_id': 'agent-1', 'model': 'gpt-6.1'}]},
    }).json()
    response = client.post(
        f'/api/hexa/tasks/{task["id"]}/runs',
        headers={'Idempotency-Key': 'plugin-preflight'},
    )
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'configuration_unavailable'


def test_run_dispatch_carries_gateway_capability_digest_from_the_run_snapshot(client, app):
    from tests.test_task_workflows import node, wait_run
    from tests.test_conversations import login

    digest = 'a' * 64
    captured = []
    login(client)

    async def listed_agents(_api_key):
        return [{"id": "agent-1", "name": "产品分析师", "base": "openai",
                 "default_model": "gpt-6.1", "capabilityDigest": digest}]

    async def response(text, previous, key, **kwargs):
        captured.append(kwargs)
        return {"response_id": "capability-bound", "text": "ok", "status": "completed"}

    app.state.gateway.list_agents = listed_agents
    app.state.gateway.create_response = response
    task = client.post('/api/hexa/tasks', json={
        'title': 'Capability binding',
        'workflow': {'nodes': [node('work', model='gpt-6.1', final_report=True)]},
    }).json()
    started = client.post(f'/api/hexa/tasks/{task["id"]}/runs', headers={'Idempotency-Key': 'capability-bound'}).json()
    completed = wait_run(client, started['id'], {'completed', 'failed'})
    assert completed['status'] == 'completed', completed
    assert captured and captured[0]['capability_digest'] == digest
