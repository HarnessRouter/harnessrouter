from __future__ import annotations

from typing import Any
import hashlib
import json
from urllib.parse import quote

import httpx


class GatewayError(RuntimeError):
    """A safe, user-facing Gateway failure without upstream secrets."""

    def __init__(self, message: str, *, uncertain: bool = False, response_id: str | None = None):
        super().__init__(message)
        self.uncertain = uncertain
        self.response_id = response_id


class GatewayClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0, cookie: str = '') -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._cookie = cookie
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json", "authorization": f"Bearer {self._api_key}"}
        if self._cookie:
            headers['cookie'] = self._cookie
        return headers

    def _internal_headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "x-harness-internal": self._api_key,
            "x-harness-org": "local",
            "x-harness-member": "hexa",
        }
        if self._cookie:
            headers['cookie'] = self._cookie
        return headers

    async def json_request(self, method: str, path: str, **kwargs):
        try:
            headers = kwargs.pop('headers', None) or self._headers()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, f'{self.base_url}{path}', headers=headers, **kwargs)
            if not response.is_success:
                raise GatewayError('Gateway 请求失败。')
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise GatewayError('Gateway 当前不可达。') from None

    async def list_workspaces(self):
        return await self.json_request('GET', '/v1/hr/workspaces')

    async def create_workspace(self, name: str, description: str):
        return await self.json_request('POST', '/v1/hr/workspaces', json={'name': name, 'description': description})

    async def update_workspace(self, workspace_id: str, name: str, description: str):
        return await self.json_request('PATCH', f'/v1/hr/workspaces/{quote(workspace_id, safe="")}', json={'name': name, 'description': description})

    async def upload_file(self, name, content, media_type):
        return await self.json_request('POST', '/v1/files', data={'purpose': 'user_data'}, files={'file': (name, content, media_type)})

    async def delete_file(self, file_id):
        return await self.json_request('DELETE', f'/v1/files/{quote(file_id, safe="")}')

    async def file_content(self, container_id, file_id):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f'{self.base_url}/v1/containers/{quote(container_id, safe="")}/files/{quote(file_id, safe="")}/content', headers=self._headers())
        if not response.is_success:
            raise GatewayError('文件下载失败。')
        return response.content

    async def list_agents(self, api_key: str | None = None) -> list[dict[str, Any]]:
        # api_key is accepted for the fake adapter contract; production always uses the
        # server-side value and never exposes it to route handlers or response models.
        del api_key
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/v1/harnesses", headers=self._headers())
        except httpx.HTTPError as exc:
            raise GatewayError("Gateway 当前不可达。") from exc
        if response.status_code in (401, 403):
            raise GatewayError("Gateway 鉴权失败。")
        if not response.is_success:
            raise GatewayError("Gateway 暂时无法读取 Agent。")
        try:
            body = response.json()
        except ValueError as exc:
            raise GatewayError("Gateway 返回的数据格式无效。") from exc
        agents = body.get("harnesses", []) if isinstance(body, dict) else []
        return agents if isinstance(agents, list) else []

    async def list_agent_templates(self) -> list[dict[str, Any]]:
        body = await self.json_request('GET', '/v1/bases')
        if not isinstance(body, dict) or not isinstance(body.get('bases'), list):
            raise GatewayError('Gateway 模板数据格式无效。')
        templates = []
        for row in body['bases']:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
                raise GatewayError('Gateway 模板数据格式无效。')
            models = row.get('models', [])
            available = [item['id'] for item in models if isinstance(item, dict) and isinstance(item.get('id'), str) and item['id'] and item.get('available') is True] if isinstance(models, list) else []
            preferred = row.get('defaultModel', '')
            default = preferred if preferred in available else next(iter(available), '')
            templates.append({
                'id': row['id'], 'name': row.get('label') if isinstance(row.get('label'), str) and row['label'] else row['id'], 'description': '',
                'base': row['id'], 'default_model': default,
                'system_prompt': row.get('systemPrompt') if isinstance(row.get('systemPrompt'), str) else '',
                'source': 'gateway', 'available': row.get('status') == 'ready' and bool(default),
            })
        return templates

    async def list_agent_models(self, agent_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/v1/harnesses/{quote(agent_id, safe='')}/models", headers=self._headers())
        except (httpx.HTTPError, UnicodeError) as exc:
            raise GatewayError("Gateway 当前不可达。") from exc
        if response.status_code in (401, 403):
            raise GatewayError("Gateway 鉴权失败。")
        if response.status_code == 404:
            raise GatewayError("Agent 不存在。")
        if not response.is_success:
            raise GatewayError("Gateway 暂时无法读取模型。")
        try:
            body = response.json()
        except ValueError as exc:
            raise GatewayError("Gateway 返回的数据格式无效。") from exc
        return body if isinstance(body, dict) else {}

    async def get_uhp_discovery(self) -> dict[str, Any]:
        """Read the unauthenticated UHP capability document before using optional fields."""
        result = await self.json_request('GET', '/v1/uhp')
        return result if isinstance(result, dict) else {}

    async def get_agent_capabilities(self, agent_id: str) -> dict[str, Any]:
        """Read the Gateway's direct and plugin-derived Harness composition.

        The returned package is intentionally not expanded here. Gateway remains responsible for
        parsing and materialising plugin files; Hexa only snapshots the safe composition summary.
        """
        result = await self.json_request('GET', f'/v1/harnesses/{quote(agent_id, safe="")}')
        if not isinstance(result, dict):
            return {}
        plugins = result.get('plugins')
        if isinstance(plugins, list):
            for plugin in plugins:
                if not isinstance(plugin, dict) or not plugin.get('name'):
                    continue
                try:
                    files = await self.json_request(
                        'GET',
                        f'/v1/harnesses/{quote(agent_id, safe="")}/plugins/{quote(str(plugin["name"]), safe="")}/files',
                    )
                except GatewayError:
                    # The Harness summary remains useful for preflight; the missing package is
                    # represented by the Gateway's own skipped/plugin_not_found error path.
                    plugin['_package_read_error'] = 'plugin package could not be read'
                    continue
                if isinstance(files, dict) and isinstance(files.get('files'), list):
                    normalized = []
                    for item in files['files']:
                        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
                            continue
                        payload = item.get('content_b64') if isinstance(item.get('content_b64'), str) else item.get('content', '')
                        normalized.append({'path': item['path'], 'content': payload})
                    plugin['_package_digest'] = hashlib.sha256(
                        json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
                    ).hexdigest()
        return result

    async def create_agent(self, input: dict[str, Any]) -> dict[str, Any]:
        payload = {'name': input['name'], 'base': input['base'], 'default_model': input['default_model'], 'system_prompt': input.get('system_prompt', ''), 'mcp_servers': [], 'skills': [], 'disabled_tools': []}
        result = await self.json_request('POST', '/v1/harnesses', json=payload)
        return result if isinstance(result, dict) else {}

    async def delete_agent(self, agent_id: str) -> None:
        await self.json_request('DELETE', f'/v1/harnesses/{quote(agent_id, safe="")}')

    async def get_response(self, response_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f'{self.base_url}/v1/responses/{quote(response_id, safe="")}', headers=self._headers())
        if not response.is_success:
            raise GatewayError('响应状态暂时无法读取。', uncertain=True, response_id=response_id)
        data = response.json()
        if not isinstance(data, dict):
            raise GatewayError('响应状态暂时无法读取。', uncertain=True, response_id=response_id)
        return data

    async def cancel_response(self, response_id: str):
        return await self.json_request('POST', f'/v1/responses/{quote(response_id, safe="")}/cancel')

    async def create_response(self, text: str, previous_response_id: str | None, idempotency_key: str, *, agent_id: str = '', model: str = '', workspace_id: str = '', content: list | None = None, on_progress=None, on_execution=None) -> dict[str, Any]:
        from app.gateway.execution import PublicExecution
        execution = PublicExecution()
        payload: dict[str, Any] = {"input": [{"role": "user", "content": content or text}], "stream": True, "store": True}
        if agent_id:
            payload['metadata'] = {'harness_id': agent_id}
        if model:
            payload['model'] = model
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        response_id = ""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15)) as client:
                async with client.stream("POST", f"{self.base_url}/v1/responses", headers={**self._headers(), **({'x-harness-workspace': workspace_id, **({'x-harness-workspace-default': '1'} if workspace_id == 'default' else {})} if workspace_id else {}), "content-type": "application/json", "idempotency-key": idempotency_key}, json=payload) as response:
                    if response.status_code in (401, 403):
                        raise GatewayError("Gateway 鉴权失败。")
                    if not response.is_success:
                        raise GatewayError("Gateway 请求失败。", uncertain=response.status_code >= 500)
                    response_id = ""
                    text_parts: list[str] = []
                    final_status = ""
                    files = {}
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            event = json.loads(raw)
                        except ValueError as exc:
                            raise GatewayError("Gateway 返回的数据格式无效。", uncertain=True, response_id=response_id or None) from exc
                        if not isinstance(event, dict):
                            raise GatewayError("Gateway 返回的数据格式无效。", uncertain=True)
                        nested = event.get("response")
                        before_execution = execution.snapshot()
                        execution.consume(event)
                        if on_execution and execution.snapshot() != before_execution:
                            await on_execution(execution.snapshot())
                        for citation in citations(event):
                            files[citation['file_id']] = citation
                        if isinstance(nested, dict) and isinstance(nested.get("id"), str):
                            response_id = nested["id"]
                        if event.get("type") == "response.output_text.delta" and isinstance(event.get("delta"), str):
                            text_parts.append(event["delta"])
                        if on_progress and (event.get('type') == 'response.output_text.delta' or (isinstance(nested, dict) and nested.get('id'))):
                            await on_progress(response_id or None, ''.join(text_parts))
                        if event.get("type") in {"response.completed", "response.incomplete", "response.cancelled", "response.failed", "error"}:
                            wire_status = nested.get('status') if isinstance(nested, dict) else None
                            final_status = wire_status if wire_status in {'completed', 'incomplete', 'cancelled', 'failed'} else event['type'].removeprefix('response.')
                            if not text_parts and isinstance(nested, dict):
                                text_parts.append(response_text(nested))
                            if final_status in {'failed', 'error'}:
                                raise GatewayError("Gateway 执行失败。", response_id=response_id or None)
                    if not response_id or not final_status:
                        raise GatewayError("Gateway 响应在完成前中断。", uncertain=True, response_id=response_id or None)
                    details = execution.snapshot()
                    return {"response_id": response_id, "text": "".join(text_parts), "status": final_status, **({'files': list(files.values())} if files else {}), **({'execution': details} if details['reasoning'] or details['steps'] else {})}
        except GatewayError:
            raise
        except httpx.HTTPError as exc:
            raise GatewayError("Gateway 当前不可达。", uncertain=True, response_id=response_id or None) from exc


def response_text(value: dict) -> str:
    return ''.join(part.get('text', '') for item in value.get('output', []) if isinstance(item, dict) and item.get('type') == 'message' for part in item.get('content', []) if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str))


def citations(value):
    if isinstance(value, dict):
        if value.get('type') == 'container_file_citation' and value.get('file_id') and value.get('container_id'):
            yield value
        for child in value.values():
            yield from citations(child)
    elif isinstance(value, list):
        for child in value:
            yield from citations(child)
