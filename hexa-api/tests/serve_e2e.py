"""Disposable integration environment. Never use this fixture as a product server."""
import asyncio
import json
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

gateway = FastAPI()
responses = {}
key = secrets.token_urlsafe(32)
agent_records = [{'id': 'e2e-agent', 'name': '集成测试 Agent', 'base': 'codex', 'defaultModel': 'e2e-model'}]


@gateway.middleware('http')
async def check_key(request, call_next):
    if request.headers.get('authorization') != f'Bearer {key}':
        return Response(status_code=401)
    return await call_next(request)


@gateway.get('/v1/harnesses')
async def agents():
    return {'harnesses': agent_records}


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
    return {'workspaces': [{'id': 'default', 'name': '测试工作区', 'description': ''}], 'default_workspace_id': 'default'}


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
    if text == '追问' and not body.get('previous_response_id'):
        return Response(status_code=400)
    responses[rid] = {'id': rid, 'status': 'in_progress', 'output': []}
    async def stream():
        yield f'data: {json.dumps({"type": "response.created", "response": responses[rid]})}\n\n'
        for delta in ['实时', '回答：', text]:
            await asyncio.sleep(0.6)
            if responses[rid]['status'] == 'cancelled':
                yield f'data: {json.dumps({"type":"response.failed", "response": responses[rid]})}\n\n'
                return
            yield f'data: {json.dumps({"type":"response.output_text.delta", "delta":delta})}\n\n'
        responses[rid] = {'id': rid, 'status': 'completed', 'output': [{'type':'message', 'content': [{'type':'output_text', 'text': '实时回答：' + text, 'annotations': [{'type':'container_file_citation', 'file_id':'out', 'container_id':'session-test', 'filename':'report.txt', 'media_type':'text/plain'}]}]}]}
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
        thread = threading.Thread(target=lambda: uvicorn.run(gateway, host='127.0.0.1', port=4011, log_level='error'), daemon=True)
        thread.start()
        settings = Settings(database_url=f'sqlite:///{Path(temp) / "app.db"}', admin_password_hash=hash_password('integration-password'), session_secret='integration-session-secret', gateway_url='http://127.0.0.1:4011', gateway_api_key=key, cookie_secure=False)
        uvicorn.run(create_app(settings), host='127.0.0.1', port=4012, log_level='error')
