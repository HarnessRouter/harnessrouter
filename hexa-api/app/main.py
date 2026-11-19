from __future__ import annotations

from contextlib import asynccontextmanager
import json
import hashlib
import asyncio
import time
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, UploadFile, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.service import COOKIE_NAME, authenticate, create_session, get_session
from app.config import Settings
from app.db.models import AppWorkspace, AuthSession, Conversation, ConversationMessage, ConversationFile, IdempotencyRequest, Run, RunDecision, Task, WorkflowRevision, create_session_factory
from app.gateway.client import GatewayClient, GatewayError, response_text
from app.tasks.router import build_router
from app.tasks.service import TaskError, TaskExecutor
from app.agents.router import build_agent_router


class LoginBody(BaseModel):
    username: str
    password: str


class WorkspaceBody(BaseModel):
    name: str | None = None
    description: str | None = None


class WorkspaceSelectionBody(BaseModel):
    workspace_id: int


class ConversationBody(BaseModel):
    title: str = "新对话"
    workspace_id: int | None = None
    agent_id: str = ''
    model: str = ''


class MessageBody(BaseModel):
    text: str
    previous_response_id: str | None = None
    file_ids: list[int] = Field(default_factory=list, max_length=20)


class AgentBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base: str = Field(min_length=1, max_length=255)
    default_model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default='', max_length=20000)


class TaskBody(BaseModel):
    title: str = "未命名任务"
    description: str = ""
    workspace_id: int | None = None
    workflow: dict[str, Any]


class WorkflowUpdateBody(BaseModel):
    expected_revision: int = Field(ge=1)
    workflow: dict[str, Any]


class ContinueRunBody(BaseModel):
    node_id: str
    input_refs: list[str] = Field(min_length=1, max_length=50)


def create_app(settings: Settings | None = None, gateway: Any | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    adapter = gateway or GatewayClient(resolved.gateway_url, resolved.gateway_api_key, cookie=resolved.gateway_cookie)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved.validate()
        app.state.session_factory = create_session_factory(resolved.database_url)
        app.state.task_executor = TaskExecutor(app.state.session_factory, app.state.gateway, (resolved.gateway_api_key, resolved.session_secret))
        app.state.task_executor.recover()
        yield
        await app.state.task_executor.close()
        app.state.session_factory.kw['bind'].dispose()

    app = FastAPI(title="Hexa App API", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = resolved
    app.state.gateway = adapter
    # Database initialization happens at application startup. Importing this module
    # must not attempt to connect to a production PostgreSQL instance, which also keeps
    # test collection and CLI tooling side-effect free.
    app.state.session_factory = None

    def require_session(request: Request, hexa_session: str | None = Cookie(None, alias=COOKIE_NAME)) -> AuthSession:
        with app.state.session_factory() as db:
            record = get_session(db, hexa_session, resolved.session_secret)
        if record is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要先登录。")
        request.state.auth_session = record
        return record

    def user_id(_: AuthSession) -> int:
        # First release has one configured administrator. The stable internal ID keeps
        # persistence ready for multi-user migration without exposing usernames as keys.
        return 1

    def workspace_json(workspace: AppWorkspace) -> dict[str, Any]:
        return {"id": workspace.id, "name": workspace.name, "description": workspace.description}

    @app.middleware("http")
    async def security_boundary(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")):
                return JSONResponse({"detail": "请求来源不被允许。"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": "请求参数无效。"}, status_code=422)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/hexa/auth/login")
    async def login(body: LoginBody, response: Response) -> dict[str, Any]:
        if not authenticate(resolved, body.username, body.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误。")
        with app.state.session_factory() as db:
            token = create_session(db, resolved, body.username)
        response.set_cookie(COOKIE_NAME, token, httponly=True, secure=resolved.cookie_secure, samesite="lax", max_age=resolved.session_ttl_seconds, path="/")
        return {"authenticated": True, "username": body.username}

    @app.get("/api/hexa/auth/session")
    async def current_session(session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        return {"authenticated": True, "username": session.username}

    @app.post("/api/hexa/auth/logout")
    async def logout(response: Response, hexa_session: str | None = Cookie(None, alias=COOKIE_NAME)) -> dict[str, bool]:
        if hexa_session:
            with app.state.session_factory() as db:
                record = get_session(db, hexa_session, resolved.session_secret)
                if record:
                    record.revoked = True
                    db.commit()
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"authenticated": False}

    @app.get("/api/hexa/agents")
    async def agents(_: AuthSession = Depends(require_session)) -> dict[str, Any]:
        try:
            rows = await app.state.gateway.list_agents(resolved.gateway_api_key)
        except Exception as exc:
            message = "Gateway 暂时无法读取 Agent。"
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message) from exc
        return {"agents": rows}

    @app.get("/api/hexa/agents/{agent_id}/models")
    async def agent_models(agent_id: str, _: AuthSession = Depends(require_session)) -> dict[str, Any]:
        try:
            return await app.state.gateway.list_agent_models(agent_id)
        except Exception as exc:
            message = "Gateway 暂时无法读取模型。"
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message) from exc

    app.include_router(build_router(app, require_session, user_id))
    app.include_router(build_agent_router(app, require_session, user_id))

    @app.exception_handler(TaskError)
    async def invalid_task(request, exc):
        return JSONResponse({'detail': {'code': exc.code, 'message': str(exc)}}, status_code=exc.status)

    @app.post('/api/hexa/agents', status_code=201)
    async def create_agent(body: AgentBody, _: AuthSession = Depends(require_session)):
        try:
            return await app.state.gateway.create_agent(body.model_dump())
        except Exception:
            raise HTTPException(502, 'Agent 创建失败。') from None

    @app.delete('/api/hexa/agents/{agent_id}', status_code=204)
    async def delete_agent(agent_id: str, _: AuthSession = Depends(require_session)):
        try:
            await app.state.gateway.delete_agent(agent_id)
        except Exception:
            raise HTTPException(502, 'Agent 删除失败。') from None
        return Response(status_code=204)

    @app.get("/api/hexa/workspaces")
    async def list_workspaces(session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        try:
            remote = await app.state.gateway.list_workspaces()
        except Exception:
            raise HTTPException(502, '工作空间读取失败。') from None
        with app.state.session_factory() as db:
            for row in remote.get('workspaces', []):
                mapped = db.scalar(select(AppWorkspace).where(AppWorkspace.user_id == user_id(session), AppWorkspace.gateway_id == row['id']))
                if mapped:
                    mapped.name, mapped.description = row['name'], row.get('description', '')
                else:
                    db.add(AppWorkspace(user_id=user_id(session), gateway_id=row['id'], name=row['name'], description=row.get('description', '')))
            db.commit()
            rows = db.scalars(select(AppWorkspace).where(AppWorkspace.user_id == user_id(session)).order_by(AppWorkspace.id)).all()
            selected = next((row.id for row in rows if row.selected), None)
        return {"workspaces": [workspace_json(row) for row in rows], "selected_id": selected}

    @app.post("/api/hexa/workspaces", status_code=status.HTTP_201_CREATED)
    async def create_workspace(body: WorkspaceBody, session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="工作区名称不能为空。")
        try:
            remote = await app.state.gateway.create_workspace(name, (body.description or "").strip())
        except Exception:
            raise HTTPException(502, '工作空间创建失败。') from None
        with app.state.session_factory() as db:
            workspace = AppWorkspace(user_id=user_id(session), gateway_id=remote['id'], name=remote['name'], description=remote.get('description', ''))
            db.add(workspace)
            db.commit()
            db.refresh(workspace)
            return workspace_json(workspace)

    @app.patch("/api/hexa/workspaces/{workspace_id}")
    async def update_workspace(workspace_id: int, body: WorkspaceBody, session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        with app.state.session_factory() as db:
            workspace = db.scalar(select(AppWorkspace).where(AppWorkspace.id == workspace_id, AppWorkspace.user_id == user_id(session)))
            if workspace is None:
                raise HTTPException(status_code=404, detail="工作区不存在。")
            name = body.name.strip() if body.name is not None else workspace.name
            if not name:
                raise HTTPException(status_code=422, detail="工作区名称不能为空。")
            description = body.description.strip() if body.description is not None else workspace.description
            try:
                remote = await app.state.gateway.update_workspace(workspace.gateway_id, name, description)
            except Exception:
                raise HTTPException(502, '工作空间保存失败。') from None
            workspace.name = remote.get('name', name)
            workspace.description = remote.get('description', description)
            db.commit()
            db.refresh(workspace)
            return workspace_json(workspace)

    @app.post("/api/hexa/workspaces/select")
    async def select_workspace(body: WorkspaceSelectionBody, session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        with app.state.session_factory() as db:
            rows = db.scalars(select(AppWorkspace).where(AppWorkspace.user_id == user_id(session))).all()
            selected = next((row for row in rows if row.id == body.workspace_id), None)
            if selected is None:
                raise HTTPException(status_code=404, detail="工作区不存在。")
            for row in rows:
                row.selected = row.id == selected.id
            db.commit()
        return {"selected_id": selected.id}

    @app.post("/api/hexa/conversations", status_code=status.HTTP_201_CREATED)
    async def create_conversation(body: ConversationBody, session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        title = body.title.strip() or "新对话"
        with app.state.session_factory() as db:
            if body.workspace_id is not None and db.scalar(select(AppWorkspace.id).where(AppWorkspace.id == body.workspace_id, AppWorkspace.user_id == user_id(session))) is None:
                raise HTTPException(status_code=404, detail="工作区不存在。")
            conversation = Conversation(user_id=user_id(session), workspace_id=body.workspace_id, title=title, agent_id=body.agent_id, model=body.model)
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            return {"id": conversation.id, "title": conversation.title, "previous_response_id": None, "messages": []}

    @app.get("/api/hexa/conversations")
    async def list_conversations(session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        with app.state.session_factory() as db:
            rows = db.scalars(select(Conversation).where(Conversation.user_id == user_id(session)).order_by(Conversation.id.desc())).all()
            return {"conversations": [{"id": row.id, "title": row.title, "previous_response_id": row.previous_response_id, "status": row.response_status} for row in rows]}

    @app.get("/api/hexa/conversations/{conversation_id}")
    async def get_conversation(conversation_id: int, session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        with app.state.session_factory() as db:
            conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id(session)))
            if conversation is None:
                raise HTTPException(status_code=404, detail="会话不存在。")
            messages = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id).order_by(ConversationMessage.id)).all()
            records = db.scalars(select(IdempotencyRequest).where(IdempotencyRequest.conversation_id == conversation.id)).all()
            executions = {record.key: json.loads(record.execution_json) for record in records if record.execution_json}
            return {
                "id": conversation.id,
                "title": conversation.title,
                "previous_response_id": conversation.previous_response_id,
                "agent_id": conversation.agent_id,
                "model": conversation.model,
                "status": conversation.response_status,
                "messages": [{"id": row.id, "role": row.role, "text": row.text, **({'execution': executions[row.idempotency_key]} if row.role == 'assistant' and row.idempotency_key in executions else {})} for row in messages],
            }

    @app.get("/api/hexa/conversations/{conversation_id}/status")
    async def conversation_status(conversation_id: int, session: AuthSession = Depends(require_session)) -> dict[str, Any]:
        with app.state.session_factory() as db:
            conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id(session)))
            if conversation is None:
                raise HTTPException(status_code=404, detail="会话不存在。")
            if conversation.response_status == 'unknown':
                pending = db.scalar(select(IdempotencyRequest).where(IdempotencyRequest.conversation_id == conversation_id, IdempotencyRequest.status == 'unknown').order_by(IdempotencyRequest.id.desc()))
                if pending and pending.response_id:
                    try:
                        result = await app.state.gateway.get_response(pending.response_id)
                    except Exception:
                        result = {}
                    final = result.get('status')
                    if final in {'completed', 'failed', 'incomplete', 'cancelled'}:
                        from sqlalchemy import update
                        claim = db.execute(update(IdempotencyRequest).where(IdempotencyRequest.id == pending.id, IdempotencyRequest.status == 'unknown').values(status=final))
                        if claim.rowcount == 1:
                            conversation.previous_response_id = pending.response_id
                            conversation.response_status = final
                            conversation.response_error = 'Gateway 执行失败。' if final == 'failed' else None
                            text = response_text(result)
                            if pending.execution_json:
                                from app.gateway.execution import PublicExecution
                                execution = json.loads(pending.execution_json)
                                public = PublicExecution()
                                public.consume({'response': result})
                                details = public.snapshot()
                                if details['reasoning'] or details['steps']:
                                    execution.update(details)
                                execution['status'] = final
                                execution.pop('elapsed_ms', None)
                                if isinstance(result.get('completed_at'), (int, float)) and execution.get('started_at'):
                                    execution['elapsed_ms'] = max(0, round((result['completed_at'] - execution['started_at']) * 1000))
                                pending.execution_json = json.dumps(execution, ensure_ascii=False)
                            if text:
                                db.add(ConversationMessage(conversation_id=conversation_id, role='assistant', text=text, idempotency_key=pending.key))
                            pending.http_status = 502 if final == 'failed' else 200
                            pending.response_json = json.dumps({'detail': 'Gateway 执行失败。'} if final == 'failed' else {'accepted': True, 'response_id': pending.response_id, 'status': final, 'assistant': {'role': 'assistant', 'text': text}}, ensure_ascii=False)
                            db.commit()
            return {"conversation_id": conversation.id, "status": conversation.response_status, "response_id": conversation.previous_response_id, "error": conversation.response_error}

    @app.get('/api/hexa/conversations/{conversation_id}/events')
    async def conversation_events(conversation_id: int, session: AuthSession = Depends(require_session)):
        with app.state.session_factory() as db:
            owned = db.scalar(select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == user_id(session)))
            if owned is None:
                raise HTTPException(404, '会话不存在。')
        async def snapshots():
            last = None
            for _ in range(1200):
                with app.state.session_factory() as db:
                    row = db.get(Conversation, conversation_id)
                    pending = db.scalar(select(IdempotencyRequest).where(IdempotencyRequest.conversation_id == conversation_id).order_by(IdempotencyRequest.id.desc()))
                    snapshot = {'status': row.response_status, 'response_id': pending.response_id if pending else row.previous_response_id, 'text': pending.partial_text if pending else ''}
                    if pending and pending.execution_json:
                        snapshot['execution'] = json.loads(pending.execution_json)
                encoded = json.dumps(snapshot, ensure_ascii=False)
                if encoded != last:
                    yield f'data: {encoded}\n\n'
                    last = encoded
                else:
                    yield ': heartbeat\n\n'
                if snapshot['status'] != 'running':
                    return
                await asyncio.sleep(0.5)
        return StreamingResponse(snapshots(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @app.post('/api/hexa/conversations/{conversation_id}/cancel')
    async def cancel_conversation(conversation_id: int, session: AuthSession = Depends(require_session)):
        with app.state.session_factory() as db:
            row = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id(session)))
            if not row:
                raise HTTPException(404, '会话不存在。')
            pending = db.scalar(select(IdempotencyRequest).where(IdempotencyRequest.conversation_id == conversation_id, IdempotencyRequest.status.in_(['pending', 'unknown'])).order_by(IdempotencyRequest.id.desc()))
            if not pending or not pending.response_id:
                raise HTTPException(409, '尚未获取响应 ID，请刷新状态后重试取消。')
            try:
                result = await app.state.gateway.cancel_response(pending.response_id)
            except Exception:
                raise HTTPException(502, '取消结果不确定，请刷新状态。') from None
            final = result.get('status')
            if final in {'completed', 'cancelled', 'failed', 'incomplete'}:
                row.response_status = final
                row.previous_response_id = pending.response_id
                # Preserve unknown request for the recovery path to project output once.
                pending.status = 'unknown'
                db.commit()
            return {'status': final if final in {'completed', 'cancelled', 'failed', 'incomplete'} else 'running', 'response_id': pending.response_id}

    def file_json(row):
        return {'id': row.id, 'filename': row.filename, 'media_type': row.media_type, 'bytes': row.bytes, 'direction': row.direction}

    @app.post('/api/hexa/files', status_code=201)
    async def upload_attachment(session: AuthSession = Depends(require_session), file: UploadFile = File(...)):
        content = await file.read(25 * 1024 * 1024 + 1)
        await file.close()
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(413, '文件超过 25 MiB 限制。')
        try:
            remote = await app.state.gateway.upload_file(file.filename or '附件', content, file.content_type or 'application/octet-stream')
        except Exception:
            raise HTTPException(502, '文件上传失败。') from None
        with app.state.session_factory() as db:
            row = ConversationFile(user_id=user_id(session), gateway_id=remote['id'], filename=file.filename or '附件', media_type=file.content_type or 'application/octet-stream', bytes=len(content))
            db.add(row); db.commit()
            return file_json(row)

    @app.delete('/api/hexa/files/{file_id}', status_code=204)
    async def delete_attachment(file_id: int, session: AuthSession = Depends(require_session)):
        with app.state.session_factory() as db:
            row = db.scalar(select(ConversationFile).where(ConversationFile.id == file_id, ConversationFile.user_id == user_id(session)))
            if not row:
                raise HTTPException(404, '文件不存在。')
            if row.conversation_id is not None:
                raise HTTPException(409, '会话使用中的文件不能删除。')
            try:
                await app.state.gateway.delete_file(row.gateway_id)
            except Exception:
                raise HTTPException(502, '文件清理失败，请重试。') from None
            db.delete(row); db.commit()
        return Response(status_code=204)

    @app.get('/api/hexa/conversations/{conversation_id}/files')
    async def conversation_files(conversation_id: int, session: AuthSession = Depends(require_session)):
        with app.state.session_factory() as db:
            owned = db.scalar(select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == user_id(session)))
            if owned is None:
                raise HTTPException(404, '会话不存在。')
            return {'files': [file_json(row) for row in db.scalars(select(ConversationFile).where(ConversationFile.conversation_id == conversation_id, ConversationFile.user_id == user_id(session))).all()]}

    @app.get('/api/hexa/files/{file_id}/content')
    async def download_file(file_id: int, session: AuthSession = Depends(require_session)):
        with app.state.session_factory() as db:
            row = db.scalar(select(ConversationFile).where(ConversationFile.id == file_id, ConversationFile.user_id == user_id(session)))
            if not row or not row.container_id:
                raise HTTPException(404, '输出文件不存在。')
            try:
                content = await app.state.gateway.file_content(row.container_id, row.gateway_id)
            except Exception:
                raise HTTPException(502, '文件下载失败。') from None
            from urllib.parse import quote
            return Response(content, media_type='application/octet-stream', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(row.filename, safe='')}"})

    @app.post("/api/hexa/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
    async def create_message(
        conversation_id: int,
        body: MessageBody,
        session: AuthSession = Depends(require_session),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> Response:
        if not idempotency_key or len(idempotency_key) > 255:
            raise HTTPException(status_code=400, detail="缺少有效的幂等键。")
        text = body.text.strip()
        if not text and not body.file_ids:
            raise HTTPException(status_code=422, detail="消息不能为空。")
        uid = user_id(session)
        with app.state.session_factory() as db:
            conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == uid))
            if conversation is None:
                raise HTTPException(status_code=404, detail="会话不存在。")
            fingerprint = hashlib.sha256(json.dumps({"conversation_id": conversation_id, "text": text, **({'file_ids': body.file_ids} if body.file_ids else {})}, sort_keys=True).encode()).hexdigest()
            prior = db.scalar(select(IdempotencyRequest).where(IdempotencyRequest.user_id == uid, IdempotencyRequest.key == idempotency_key))
            if prior:
                if prior.conversation_id != conversation_id or prior.request_hash != fingerprint:
                    # Legacy pending records are intentionally conservative too.
                    raise HTTPException(status_code=409, detail="请求状态不确定，请先刷新会话状态。")
                if prior.response_json:
                    return Response(content=prior.response_json, media_type="application/json", status_code=prior.http_status)
                raise HTTPException(status_code=409, detail="请求状态不确定，请先刷新会话状态。")
            attachments = []
            for fid in body.file_ids:
                row = db.scalar(select(ConversationFile).where(ConversationFile.id == fid, ConversationFile.user_id == uid, ConversationFile.direction == 'input'))
                if not row or row.conversation_id not in (None, conversation_id):
                    raise HTTPException(404, '文件不存在或不属于当前会话。')
                attachments.append(row)
            # Atomic compare-and-set protects even requests with different keys from
            # racing on the same conversation, across processes.
            from sqlalchemy import update
            claim = db.execute(update(Conversation).where(Conversation.id == conversation_id, Conversation.response_status.not_in(["running", "unknown"])).values(response_status="running", response_error=None))
            if claim.rowcount != 1:
                db.rollback()
                raise HTTPException(status_code=409, detail="请求状态不确定，请先刷新会话状态。")
            previous = conversation.previous_response_id
            started_at = time.time()
            execution = {'started_at': started_at, 'harness_id': conversation.agent_id, 'model': conversation.model, 'status': 'running'}
            request_record = IdempotencyRequest(user_id=uid, key=idempotency_key, conversation_id=conversation_id, request_hash=fingerprint, status="pending", execution_json=json.dumps(execution))
            message = ConversationMessage(conversation_id=conversation.id, role="user", text=text, idempotency_key=idempotency_key)
            db.add_all([message, request_record])
            for row in attachments:
                row.conversation_id = conversation_id
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(status_code=409, detail="请求状态不确定，请先刷新会话状态。")
            remote_key = f"hexa-{uid}-{conversation_id}-{hashlib.sha256(idempotency_key.encode()).hexdigest()}"
            space = db.get(AppWorkspace, conversation.workspace_id) if conversation.workspace_id else None
            async def save_progress(rid, partial):
                with app.state.session_factory() as progress_db:
                    record = progress_db.scalar(select(IdempotencyRequest).where(IdempotencyRequest.id == request_record.id))
                    if record:
                        if rid:
                            record.response_id = rid
                        record.partial_text = partial
                        progress_db.commit()
            async def save_execution(details):
                execution.update(details)
                with app.state.session_factory() as progress_db:
                    record = progress_db.get(IdempotencyRequest, request_record.id)
                    if record:
                        record.execution_json = json.dumps(execution, ensure_ascii=False)
                        progress_db.commit()
            try:
                content = ([{'type': 'input_text', 'text': text}] if text else []) + [{'type': 'input_image' if row.media_type.startswith('image/') else 'input_file', 'file_id': row.gateway_id} for row in attachments]
                result = await app.state.gateway.create_response(text, previous, remote_key, agent_id=conversation.agent_id, model=conversation.model, workspace_id=space.gateway_id if space else '', content=content, on_progress=save_progress, on_execution=save_execution)
            except Exception as exc:
                definite = isinstance(exc, GatewayError) and not exc.uncertain
                message_text = "Gateway 请求失败。" if definite else "连接中断，请刷新会话确认状态；请勿重复提交。"
                request_record.status = "failed" if definite else "unknown"
                execution.update(status=request_record.status, elapsed_ms=round((time.time() - started_at) * 1000))
                request_record.execution_json = json.dumps(execution, ensure_ascii=False)
                if isinstance(exc, GatewayError):
                    request_record.response_id = exc.response_id
                request_record.http_status = 502
                if definite:
                    request_record.response_json = json.dumps({"detail": message_text}, ensure_ascii=False)
                conversation.response_status = request_record.status
                conversation.response_error = message_text
                db.commit()
                raise HTTPException(status_code=502, detail=message_text) from None
            response_id = result.get("response_id")
            conversation.previous_response_id = response_id
            conversation.response_status = result.get("status", "completed")
            execution.update(result.get('execution') or {})
            execution.update(status=conversation.response_status, elapsed_ms=round((time.time() - started_at) * 1000))
            request_record.execution_json = json.dumps(execution, ensure_ascii=False)
            assistant = ConversationMessage(conversation_id=conversation.id, role="assistant", text=result.get("text", ""), idempotency_key=idempotency_key)
            db.add(assistant)
            for file in result.get('files', []):
                if file.get('file_id') and file.get('container_id'):
                    db.add(ConversationFile(user_id=uid, conversation_id=conversation_id, gateway_id=file['file_id'], container_id=file['container_id'], filename=file.get('filename', '输出文件'), media_type=file.get('media_type', 'application/octet-stream'), bytes=file.get('bytes', 0), direction='output'))
            db.flush()
            payload = {"accepted": True, "message": {"id": message.id, "role": message.role, "text": message.text}, "assistant": {"id": assistant.id, "role": assistant.role, "text": assistant.text, "execution": execution}, "response_id": response_id, "status": result.get("status", "completed"), "previous_response_id": response_id}
            request_record.response_id = response_id
            request_record.status = result.get("status", "completed")
            request_record.http_status = 200
            request_record.response_json = json.dumps(payload, ensure_ascii=False)
            db.commit()
        return Response(content=json.dumps(payload, ensure_ascii=False), media_type="application/json", status_code=status.HTTP_202_ACCEPTED)

    return app


app = create_app()
