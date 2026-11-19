from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth.passwords import hash_password  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


class FakeGateway:
    def __init__(self) -> None:
        self.api_key = "server-only-gateway-key"
        self.calls = []
        self.workspaces = []

    async def list_workspaces(self):
        return {'workspaces': self.workspaces, 'default_workspace_id': 'default'}

    async def create_workspace(self, name, description):
        row = {'id': f'gateway-{len(self.workspaces) + 1}', 'name': name, 'description': description}
        self.workspaces.append(row)
        return row

    async def update_workspace(self, workspace_id, name, description):
        for row in self.workspaces:
            if row['id'] == workspace_id:
                row.update(name=name, description=description)
                return row
        raise AssertionError(f'unknown workspace {workspace_id}')

    async def list_agents(self, api_key: str) -> list[dict[str, str]]:
        assert api_key == self.api_key
        return [{"id": "agent-1", "name": "产品分析师", "base": "openai", "default_model": "gpt-6.1"}]

    async def create_response(self, text: str, previous_response_id: str | None, idempotency_key: str, **kwargs) -> dict[str, str]:
        assert text
        self.calls.append((text, previous_response_id, idempotency_key, kwargs))
        return {"response_id": "resp-1", "text": f"已处理：{text}", "status": "completed"}

    async def list_agent_models(self, agent_id: str) -> dict[str, object]:
        assert agent_id == "agent-1"
        return {"backend": "openai", "default": "gpt-6.1", "fallback": "gpt-6.1", "models": [{"id": "gpt-6.1", "label": "gpt-6.1", "available": True, "default": True}]}

    async def create_agent(self, input: dict[str, object]) -> dict[str, object]:
        assert input["name"] == "新 Agent"
        return {"id": "agent-created", "name": input["name"], "base": input["base"], "default_model": input["default_model"]}

    async def delete_agent(self, agent_id: str) -> None:
        assert agent_id == "agent-created"


@pytest.fixture()
def database_url(tmp_path: Path):
    postgres_url = os.getenv('HEXA_TEST_POSTGRES_URL')
    if postgres_url:
        from tests.postgres import isolated_database
        with isolated_database(postgres_url) as url:
            yield url
    else:
        yield f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture()
def app(database_url):
    settings = Settings(
        database_url=database_url,
        admin_username="admin",
        admin_password_hash=hash_password("correct-password"),
        session_secret="test-session-secret",
        gateway_url="http://gateway.test/api/harness",
        gateway_api_key="server-only-gateway-key",
        cookie_secure=False,
    )
    return create_app(settings=settings, gateway=FakeGateway())


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client
