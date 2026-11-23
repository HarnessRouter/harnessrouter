"""Disposable integration environment. Never use this fixture as a product server."""
import asyncio
import json
import os
import re
import secrets
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import StreamingResponse, Response
from app.config import Settings
from app.main import create_app
from app.auth.passwords import hash_password

GATEWAY_PORT = int(os.getenv('HEXA_E2E_GATEWAY_PORT', '4011'))
APP_PORT = int(os.getenv('HEXA_E2E_APP_PORT', '4012'))

gateway = FastAPI()
responses = {}
failed_once = set()
key = secrets.token_urlsafe(32)
workspace_records = [{'id': 'default', 'name': '测试工作区', 'description': ''}]
agent_records = [{
    'id': 'e2e-agent',
    'name': '集成测试 Agent',
    'base': 'codex',
    'defaultModel': 'e2e-model',
    'systemPrompt': '你是端到端测试使用的分析助手，先校验证据再给出结论。',
    'reasoningEffort': 'medium',
    'skills': ['analysis', {'name': 'reporting', 'description': '输出结构化报告'}],
    'mcpServers': [{'id': 'docs', 'url': 'https://docs.example.com/mcp'}],
    'plugins': [{'name': 'report-kit'}],
    'disabledTools': ['shell'],
    'env': {'E2E_TOKEN': 'vault:team-secret', 'EMPTY_FLAG': ''},
    'additionalHeaders': ['X-Tenant'],
    'maxStep': 12,
    'timeoutSeconds': 90,
    'environment': 'env-e2e',
    'memory': {'id': 'mem-1', 'name': '工作记忆', 'engine': 'sqlite', 'scope': 'workspace', 'observe': True},
    'createdAt': 1760000000000,
}]


def request_context(text: str) -> dict:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def marker_text(text: str) -> str:
    context = request_context(text)
    if not context:
        return text
    return f"{context.get('prompt') or ''}\n{context.get('task_input') or ''}"


@gateway.middleware('http')
async def check_key(request, call_next):
    if request.headers.get('authorization') != f'Bearer {key}':
        return Response(status_code=401)
    return await call_next(request)


@gateway.get('/v1/harnesses')
async def agents():
    return {'harnesses': agent_records}


@gateway.get('/v1/bases')
async def bases():
    return {'bases': [
        {'id': 'codex', 'label': 'Codex HTTP 模板', 'status': 'ready', 'defaultModel': 'e2e-model', 'systemPrompt': 'HTTP 模板提示词', 'models': [{'id': 'e2e-model', 'available': True}]},
        {'id': 'analyst', 'label': '分析 HTTP 模板', 'status': 'ready', 'defaultModel': 'e2e-model', 'systemPrompt': '先收集证据，再输出风险评估。', 'models': [{'id': 'e2e-model', 'available': True}]},
    ]}


@gateway.post('/v1/harnesses')
async def create_agent(request: Request):
    body = await request.json()
    row = {'id': 'e2e-created', 'name': body['name'], 'base': body['base'], 'defaultModel': body['default_model']}
    agent_records.append(row)
    return row


@gateway.delete('/v1/harnesses/{aid}')
async def delete_agent(aid: str):
    agent_records[:] = [row for row in agent_records if row['id'] != aid]
    return {'deleted': True}


@gateway.get('/v1/harnesses/{aid}/models')
async def models(aid: str):
    return {'default': 'e2e-model', 'models': [{'id': 'e2e-model', 'label': '测试模型', 'available': True}]}


@gateway.get('/v1/hr/workspaces')
async def workspaces():
    return {'workspaces': list(workspace_records), 'default_workspace_id': 'default'}


@gateway.post('/v1/hr/workspaces')
async def create_workspace(request: Request):
    body = await request.json()
    row = {'id': f'gateway-w{len(workspace_records) + 1}', 'name': body['name'], 'description': body.get('description', '')}
    workspace_records.append(row)
    return row


@gateway.patch('/v1/hr/workspaces/{workspace_id}')
async def update_workspace(workspace_id: str, request: Request):
    body = await request.json()
    row = next((item for item in workspace_records if item['id'] == workspace_id), None)
    if row is None:
        return Response(status_code=404)
    row['name'] = body.get('name', row['name'])
    row['description'] = body.get('description', row['description'])
    return row


@gateway.post('/v1/files')
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    return {'id': 'file-input', 'filename': file.filename, 'bytes': len(content)}


@gateway.delete('/v1/files/{fid}')
async def delete_file(fid: str):
    return {'deleted': True}


@gateway.get('/v1/containers/{sid}/files/{fid}/content')
async def output(sid: str, fid: str):
    return Response(b'generated report', media_type='text/plain')


@gateway.post('/v1/responses')
async def response(request: Request):
    body = await request.json()
    rid = f'response-{len(responses)+1}'
    content = body['input'][0]['content']
    text = content if isinstance(content, str) else ''.join(part.get('text', '') for part in content)
    context = request_context(text)
    haystack = marker_text(text)
    if text == '追问' and not body.get('previous_response_id'):
        return Response(status_code=400)
    if context.get('prompt') == 'E2E_DAG_PLAN':
        output = json.dumps([
            {'id': 'join', 'prompt': 'combine', 'deps': ['a', 'b'], 'inputRefs': ['a', 'b']},
            {'id': 'a', 'prompt': 'first'}, {'id': 'b', 'prompt': 'second'},
        ])
    elif 'E2E_MARKDOWN' in haystack:
        output = '\n'.join([
            '## 分析结果',
            '',
            '**重点**：先验证 `Gateway` 状态。',
            '',
            '- 第一项',
            '- 第二项',
            '',
            '| 能力 | 状态 |',
            '| --- | --- |',
            '| Markdown | 已支持 |',
            '',
            '```ts',
            'const ready = true;',
            '```',
        ])
    elif context.get('refs'):
        marker = re.search(r'E2E_OUT:([^\n"]+)', haystack)
        prefix = f'E2E-OUT:{marker.group(1).strip()}|' if marker else ''
        output = prefix + 'REFS:' + ','.join(str(ref.get('node_id')) for ref in context['refs']) + '|' + ';'.join(
            str((ref.get('output') or {}).get('text', '')) for ref in context['refs'])
    else:
        marker = re.search(r'E2E_OUT:([^\n"]+)', haystack)
        output = f'E2E-OUT:{marker.group(1).strip()}' if marker else '实时回答：' + text
    slow = re.search(r'E2E_SLOW:(\d+(?:\.\d+)?)', haystack)
    total_delay = float(slow.group(1)) if slow else 1.2
    failure = re.search(r'E2E_FAIL:([A-Za-z0-9_-]+)', haystack)
    failure_scope = failure.group(1) if failure else ''
    fail = bool(failure_scope) and failure_scope not in failed_once
    if fail:
        failed_once.add(failure_scope)
    if 'E2E_RUNNING' in haystack:
        responses[rid] = {'id': rid, 'status': 'in_progress', 'output': []}
        async def stalled():
            yield f'data: {json.dumps({"type": "response.created", "response": responses[rid]})}\n\n'
            for _ in range(600):
                await asyncio.sleep(0.5)
                if responses[rid]['status'] == 'cancelled':
                    yield f'data: {json.dumps({"type": "response.failed", "response": responses[rid]})}\n\n'
                    return
                yield f'data: {json.dumps({"type": "response.output_text.delta", "delta": "仍在执行"})}\n\n'
        return StreamingResponse(stalled(), media_type='text/event-stream')
    responses[rid] = {'id': rid, 'status': 'in_progress', 'output': []}
    async def stream():
        yield f'data: {json.dumps({"type": "response.created", "response": responses[rid]})}\n\n'
        if 'E2E_EXECUTION' in haystack:
            yield f'data: {json.dumps({"type": "response.reasoning_summary_text.delta", "delta": "核对公开资料后整理答案。"})}\n\n'
            yield f'data: {json.dumps({"type": "response.output_item.done", "item": {"id": "search-1", "type": "function_call", "name": "web_search", "status": "completed"}})}\n\n'
        await asyncio.sleep(min(total_delay, 0.4))
        if fail:
            yield f'data: {json.dumps({"type": "response.failed", "response": {"id": rid, "status": "failed", "error": {"message": "fixture failure"}}})}\n\n'
            return
        size = max(1, len(output) // 3)
        chunks = [output[index:index + size] for index in range(0, len(output), size)] or ['']
        for delta in chunks:
            await asyncio.sleep(total_delay / len(chunks))
            if responses[rid]['status'] == 'cancelled':
                yield f'data: {json.dumps({"type":"response.failed", "response": responses[rid]})}\n\n'
                return
            yield f'data: {json.dumps({"type":"response.output_text.delta", "delta":delta})}\n\n'
        annotations = [{'type': 'container_file_citation', 'file_id': 'out', 'container_id': 'session-test', 'filename': 'report.txt', 'media_type': 'text/plain'}]
        responses[rid] = {'id': rid, 'status': 'completed', 'output': [{'type':'message', 'content': [{'type':'output_text', 'text': output, 'annotations': annotations}]}]}
        yield f'data: {json.dumps({"type":"response.completed", "response":responses[rid]})}\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream')


@gateway.get('/v1/responses/{rid}')
async def get_response(rid: str):
    return responses[rid]


@gateway.post('/v1/responses/{rid}/cancel')
async def cancel(rid: str):
    responses[rid]['status'] = 'cancelled'
    return responses[rid]


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='hexa-e2e-') as temp:
        thread = threading.Thread(target=lambda: uvicorn.run(gateway, host='127.0.0.1', port=GATEWAY_PORT, log_level='error'), daemon=True)
        thread.start()
        settings = Settings(database_url=f'sqlite:///{Path(temp) / "app.db"}', admin_password_hash=hash_password('integration-password'), session_secret='integration-session-secret', gateway_url=f'http://127.0.0.1:{GATEWAY_PORT}', gateway_api_key=key, cookie_secure=False)
        uvicorn.run(create_app(settings), host='127.0.0.1', port=APP_PORT, log_level='error')
