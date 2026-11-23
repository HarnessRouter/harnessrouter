import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, delete, or_, select

from app.db.models import AppWorkspace, Artifact, NodeRun, Run, RunDecision, Task, TaskCommand, TaskTemplate, TemplateVersion, WorkflowRevision
from app.tasks.domain import redact
from app.tasks.fanout import node_record_usage, retry_fanout, manifest_records
from app.tasks.service import ACTIVE, TaskError, all_node_runs, command_replay, current_revision, encoded, is_human_node, latest_nodes, node_json, owned_run, owned_task, prepare_run, run_json, save_command, save_workflow, stale_nodes, task_json, workflow_from_json


class TaskBody(BaseModel):
    title: str = Field(default='未命名任务', max_length=255)
    description: str = Field(default='', max_length=20000)
    input: str = Field(default='', max_length=200000)
    workspace_id: int | None = None
    workflow: dict = Field(default_factory=lambda: {'nodes': []})
    template_version_id: int | None = None


class WorkflowBody(BaseModel):
    expected_revision: int = Field(ge=1)
    workflow: dict


class TaskInputBody(BaseModel):
    input: str = Field(max_length=200000)
    expected_input: str = Field(max_length=200000)


class RunBody(BaseModel):
    model_config = {'extra': 'forbid'}
    kind: str = Field(default='normal', pattern='^(normal|rerun)$')
    target_node: str | None = None
    reuse_refs: list[int] = Field(default_factory=list, max_length=50)
    resume_from_run_id: int | None = Field(default=None, ge=1, strict=True)
    item_node_run_id: int | None = Field(default=None, ge=1, strict=True)


class NodeControlBody(BaseModel):
    model_config = {'extra': 'forbid'}
    item_node_run_id: int | None = Field(default=None, ge=1, strict=True)


class SaveTemplateBody(BaseModel):
    workflow_revision: int | None = Field(default=None, ge=1)
    template_id: int | None = Field(default=None, ge=1)


def build_router(app, require_session, user_id):
    router = APIRouter(prefix='/api/hexa')

    def check_space(db, workspace_id, uid):
        if workspace_id is not None and not db.scalar(select(AppWorkspace.id).where(AppWorkspace.id == workspace_id, AppWorkspace.user_id == uid)):
            raise TaskError('not_found', '工作区不存在。', 404)

    def selected_space(db, uid):
        return db.scalar(select(AppWorkspace.id).where(AppWorkspace.user_id == uid, AppWorkspace.selected.is_(True)))

    def visible_template(db, template_id, uid):
        row = db.scalar(select(TaskTemplate).where(TaskTemplate.id == template_id, TaskTemplate.user_id == uid))
        selected = selected_space(db, uid)
        if row is None or (selected is not None and row.workspace_id != selected):
            raise TaskError('not_found', '模板不存在。', 404)
        return row

    def secrets():
        return (app.state.settings.gateway_api_key, app.state.settings.session_secret)

    def key_value(key):
        if not key or len(key) > 255:
            raise TaskError('invalid_idempotency_key', '缺少有效的幂等键。', 400)
        return key

    def page(offset, limit, maximum=100):
        safe_offset = max(0, offset)
        safe_limit = min(max(limit, 1), maximum)
        return safe_offset, safe_limit

    def page_result(name, rows, offset, limit):
        has_more = len(rows) > limit
        return {name: rows[:limit], 'pagination': {'offset': offset, 'limit': limit, 'has_more': has_more}}

    def artifact_json(row):
        return {'id': row.id, 'task_id': row.task_id, 'run_id': row.run_id, 'node_run_id': row.node_run_id,
                'filename': row.filename, 'media_type': row.media_type, 'bytes': row.bytes,
                'cleanup_status': row.cleanup_status, 'created_at': row.created_at.isoformat() if row.created_at else None}

    def owned_artifact(db, artifact_id, uid):
        row = db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.user_id == uid))
        if row is None:
            raise TaskError('not_found', '产物不存在。', 404)
        task = db.scalar(select(Task).where(Task.id == row.task_id, Task.user_id == uid))
        selected = selected_space(db, uid)
        if task is None or (selected is not None and task.workspace_id != selected):
            raise TaskError('not_found', '产物不存在。', 404)
        return row

    @router.post('/tasks', status_code=201)
    async def create_task(body: TaskBody, session=Depends(require_session)):
        with app.state.session_factory() as db:
            uid = user_id(session)
            check_space(db, body.workspace_id, uid)
            definition = body.workflow
            version = None
            if body.template_version_id:
                version = db.scalar(select(TemplateVersion).join(TaskTemplate, TaskTemplate.id == TemplateVersion.template_id).where(TemplateVersion.id == body.template_version_id, TaskTemplate.user_id == uid, TaskTemplate.workspace_id == body.workspace_id))
                if not version:
                    raise TaskError('not_found', '模板版本不存在。', 404)
                definition = json.loads(version.definition_json)
            workflow_from_json(definition)
            task = Task(user_id=uid, workspace_id=body.workspace_id, title=body.title.strip() or '未命名任务', description=redact(body.description, secrets()), input_text=redact(body.input, secrets()), current_revision=1)
            if version is not None:
                task.source_template_id, task.source_template_version_id, task.source_template_version = version.template_id, version.id, version.version
            db.add(task)
            db.flush()
            revision = WorkflowRevision(task_id=task.id, revision=1, definition_json=encoded(redact(definition, secrets())))
            db.add(revision)
            db.flush()
            task.current_revision_id = revision.id
            db.commit()
            return task_json(db, task)

    @router.get('/tasks')
    async def list_tasks(offset: int = 0, limit: int = 50, workspace_id: int | None = None, q: str = '', status: str = '', session=Depends(require_session)):
        with app.state.session_factory() as db:
            uid = user_id(session)
            if workspace_id is None:
                workspace_id = selected_space(db, uid)
            check_space(db, workspace_id, uid)
            offset, limit = page(offset, limit)
            query = select(Task).where(Task.user_id == uid)
            if workspace_id is not None:
                query = query.where(Task.workspace_id == workspace_id)
            if q.strip():
                query = query.where(or_(Task.title.icontains(q.strip(), autoescape=True), cast(Task.id, String).contains(q.strip(), autoescape=True)))
            if status and status != 'all':
                query = query.where(Task.status == status)
            rows = db.scalars(query.order_by(Task.id.desc()).offset(offset).limit(limit + 1)).all()
            return page_result('tasks', [task_json(db, row) for row in rows], offset, limit)

    @router.get('/runs')
    async def list_runs(offset: int = 0, limit: int = 20, workspace_id: int | None = None, q: str = '', status: str = '', session=Depends(require_session)):
        with app.state.session_factory() as db:
            uid = user_id(session)
            if workspace_id is None:
                workspace_id = selected_space(db, uid)
            check_space(db, workspace_id, uid)
            offset, limit = page(offset, limit)
            query = select(Run, Task.title).join(Task, Run.task_id == Task.id).where(Task.user_id == uid)
            if workspace_id is not None:
                query = query.where(Task.workspace_id == workspace_id)
            if q.strip():
                query = query.where(or_(Task.title.icontains(q.strip(), autoescape=True), cast(Run.id, String).contains(q.strip(), autoescape=True)))
            if status and status != 'all':
                query = query.where(Run.status == status)
            rows = db.execute(query.order_by(Run.id.desc()).offset(offset).limit(limit + 1)).all()
            return page_result('runs', [{**run_json(db, run), 'task_title': title} for run, title in rows], offset, limit)

    @router.get('/tasks/{task_id}')
    async def get_task(task_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            return task_json(db, owned_task(db, task_id, user_id(session)))

    @router.put('/tasks/{task_id}/workflow')
    async def workflow(task_id: int, body: WorkflowBody, session=Depends(require_session)):
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                task = owned_task(db, task_id, user_id(session))
                if task.status in ('completed', 'archived'):
                    raise TaskError('invalid_transition', '请先重新打开任务。')
                return save_workflow(db, task, body.expected_revision, redact(body.workflow, secrets()))

    @router.put('/tasks/{task_id}/input')
    async def update_task_input(task_id: int, body: TaskInputBody, session=Depends(require_session)):
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                task = owned_task(db, task_id, user_id(session))
                if task.status in ('completed', 'archived') or db.scalar(select(Run.id).where(Run.task_id == task.id, Run.status.in_(ACTIVE))):
                    raise TaskError('invalid_transition', '当前任务不能修改输入。')
                if task.input_text != body.expected_input:
                    raise TaskError('input_conflict', '任务输入已变化，请刷新后重试。')
                task.input_text = redact(body.input, secrets())
                db.commit()
                return task_json(db, task)

    @router.post('/tasks/{task_id}/runs')
    async def start(task_id: int, body: RunBody = RunBody(), session=Depends(require_session), key: str | None = Header(None, alias='Idempotency-Key')):
        key_value(key)
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                task = owned_task(db, task_id, user_id(session))
                run, replay = await prepare_run(db, task, body.model_dump(), key, app.state.gateway, secrets())
                payload = run_json(db, run)
                if not replay:
                    app.state.task_executor.schedule(run.id)
                return JSONResponse(payload, status_code=200 if replay else 202)

    @router.get('/tasks/{task_id}/runs')
    async def history(task_id: int, offset: int = 0, limit: int = 30, session=Depends(require_session)):
        with app.state.session_factory() as db:
            owned_task(db, task_id, user_id(session))
            offset, limit = page(offset, limit)
            rows = db.scalars(select(Run).where(Run.task_id == task_id).order_by(Run.id.desc()).offset(offset).limit(limit + 1)).all()
            return page_result('runs', [run_json(db, row) for row in rows], offset, limit)

    @router.get('/runs/{run_id}/nodes')
    async def nodes(run_id: int, offset: int = 0, limit: int = 100, session=Depends(require_session)):
        with app.state.session_factory() as db:
            run = owned_run(db, run_id, user_id(session))
            offset, limit = page(offset, limit)
            all_rows = list(latest_nodes(db, run.id).values())
            rows = all_rows[offset:offset + limit + 1]
            return page_result('nodes', [node_json(row) for row in rows], offset, limit)

    @router.get('/runs/{run_id}')
    async def get_run(run_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            return run_json(db, owned_run(db, run_id, user_id(session)))

    @router.get('/runs/{run_id}/events')
    async def events(run_id: int, request: Request, session=Depends(require_session)):
        uid = user_id(session)
        with app.state.session_factory() as db:
            owned_run(db, run_id, uid)
        async def snapshots():
            previous = ''
            while not await request.is_disconnected():
                with app.state.session_factory() as db:
                    snapshot = run_json(db, owned_run(db, run_id, uid))
                text = encoded(snapshot)
                if text != previous:
                    yield f'data: {text}\n\n'
                    previous = text
                else:
                    yield ': heartbeat\n\n'
                if snapshot['status'] not in ('pending', 'running') or snapshot['paused']:
                    return
                await asyncio.sleep(0.3)
        return StreamingResponse(snapshots(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @router.post('/runs/{run_id}/{action}')
    async def control(run_id: int, action: str, body: dict = {}, session=Depends(require_session), key: str | None = Header(None, alias='Idempotency-Key')):
        key_value(key)
        with app.state.session_factory() as db:
            task_id = owned_run(db, run_id, user_id(session)).task_id
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                run = owned_run(db, run_id, user_id(session))
                fingerprint, replay = command_replay(db, task_id, key, f'{run_id}:{action}', body)
                if replay is not None:
                    return replay
                if run.status not in ACTIVE:
                    raise TaskError('invalid_transition', '当前运行已经结束。')
                task = db.get(Task, task_id)
                rows = latest_nodes(db, run_id)
                if action == 'continue':
                    if run.paused:
                        if task.current_revision != run.workflow_revision:
                            raise TaskError('revision_conflict', '工作流已改变，请启动续编运行。')
                        run.paused = False
                    else:
                        if run.status != 'waiting_human':
                            raise TaskError('invalid_transition', '当前运行不在等待人工处理状态。')
                        definition = json.loads(run.snapshot_json)['workflow']
                        item = next((item for item in definition['nodes'] if item['id'] == body.get('node_id')), None)
                        refs = body.get('input_refs', [])
                        if not item or not is_human_node(item) or not refs or len(set(refs)) != len(refs) or set(refs) - set(item.get('deps', [])) or any(rows[ref].status != 'succeeded' for ref in refs):
                            raise TaskError('invalid_decision', '人工选择的节点或结果无效。', 422)
                        db.add(RunDecision(run_id=run_id, node_id=item['id'], iteration=rows[item['id']].iteration, input_refs_json=encoded(refs)))
                    run.status, task.status = 'running', 'running'
                elif action == 'pause':
                    run.paused, task.status = True, 'waiting'
                elif action == 'cancel':
                    run.status, task.status = 'canceled', 'waiting'
                    for row in all_node_runs(db, run_id):
                        if row.status not in ('succeeded', 'failed', 'skipped', 'canceled'):
                            row.error_code = 'interrupted_unknown_outcome' if row.status == 'running' else None
                            row.status = 'canceled'
                else:
                    raise TaskError('invalid_transition', '运行操作无效。', 422)
                result = {'id': run.id, 'status': run.status, 'paused': run.paused}
                save_command(db, task_id, key, fingerprint, result)
                db.commit()
            if action == 'continue':
                app.state.task_executor.schedule(run_id)
            if action == 'cancel':
                with app.state.session_factory() as db:
                    cancel_rows = all_node_runs(db, run_id)
                for row in cancel_rows:
                    if row.response_id and row.status == 'canceled':
                        try:
                            await app.state.gateway.cancel_response(row.response_id)
                        except Exception:
                            pass
            return result

    @router.post('/runs/{run_id}/nodes/{node_id}/{action}')
    async def node_control(run_id: int, node_id: str, action: str, body: NodeControlBody = NodeControlBody(), session=Depends(require_session), key: str | None = Header(None, alias='Idempotency-Key')):
        key_value(key)
        with app.state.session_factory() as db:
            run = owned_run(db, run_id, user_id(session))
            task_id = run.task_id
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                run = owned_run(db, run_id, user_id(session))
                payload = body.model_dump(exclude_none=True)
                fingerprint, replay = command_replay(db, task_id, key, f'{run_id}:{node_id}:{action}', payload)
                if replay is not None:
                    return replay
                row = latest_nodes(db, run_id).get(node_id)
                if run.status not in ACTIVE or not row:
                    raise TaskError('invalid_transition', '终态运行请创建新的 Run。')
                definition = json.loads(run.snapshot_json)['workflow']
                item = next(item for item in definition['nodes'] if item['id'] == node_id)
                if body.item_node_run_id is not None and (action != 'retry' or not (item.get('foreach') or item.get('dynamic_plan'))):
                    raise TaskError('invalid_retry_item', '只有集合重试支持指定执行项。', 422)
                if action == 'skip' and item.get('allow_skip') and row.status in ('idle', 'failed', 'canceled'):
                    row.status = 'skipped'
                elif action == 'retry' and row.status in ('failed', 'canceled'):
                    if item.get('foreach') or item.get('dynamic_plan'):
                        retry_fanout(db, run, item, row, body.item_node_run_id, encoded=encoded, error=TaskError)
                    else:
                        if node_record_usage(db, run_id) >= 500:
                            raise TaskError('storage_limit_exceeded', '运行超过 500 次尝试限制。', 422)
                        db.add(NodeRun(run_id=run_id, node_id=node_id, attempt=row.attempt + 1, iteration=row.iteration, status='idle'))
                else:
                    raise TaskError('invalid_transition', '节点操作不被当前状态或配置允许。')
                run.status = 'running'
                result = {'id': run.id, 'status': run.status}
                save_command(db, task_id, key, fingerprint, result)
                db.commit()
                app.state.task_executor.schedule(run_id)
                return result

    async def debug_paged(attempt_id: int, offset: int, limit: int, session):
        with app.state.session_factory() as db:
            row = db.get(NodeRun, attempt_id)
            if not row:
                raise TaskError('not_found', '节点记录不存在。', 404)
            run = owned_run(db, row.run_id, user_id(session))
            offset, limit = page(offset, limit, 500)
            attempts = db.scalars(select(NodeRun).where(NodeRun.run_id == run.id, NodeRun.node_id == row.node_id).order_by(NodeRun.iteration, NodeRun.attempt, NodeRun.id).offset(offset).limit(limit + 1)).all()
            artifacts = db.scalars(select(Artifact).where(Artifact.node_run_id == row.id, Artifact.user_id == user_id(session)).order_by(Artifact.id.desc()).limit(51)).all()
            result = {**node_json(row), 'environment': json.loads(run.snapshot_json), 'attempts': [node_json(attempt) for attempt in attempts[:limit]],
                      'attempts_pagination': {'offset': offset, 'limit': limit, 'has_more': len(attempts) > limit}, 'artifacts': [artifact_json(item) for item in artifacts[:50]],
                      'artifacts_pagination': {'offset': 0, 'limit': 50, 'has_more': len(artifacts) > 50}}
            return result

    @router.get('/node-runs/{attempt_id}')
    async def debug(attempt_id: int, offset: int = 0, limit: int = 100, session=Depends(require_session)):
        return await debug_paged(attempt_id, offset, limit, session)

    @router.get('/node-runs/{attempt_id}/items')
    async def manifest_page(attempt_id: int, offset: int = Query(0, ge=0),
                            limit: int = Query(50, ge=1, le=100), session=Depends(require_session)):
        with app.state.session_factory() as db:
            anchor = db.get(NodeRun, attempt_id)
            if anchor is None:
                raise TaskError('not_found', '节点记录不存在。', 404)
            owned_run(db, anchor.run_id, user_id(session))
            try:
                rows = manifest_records(db, anchor)
            except (ValueError, TypeError, KeyError):
                raise TaskError('fanout_manifest_unavailable', '集合执行清单不可用，请刷新后重试。', 409) from None
            return {'anchor_node_run_id': anchor.id,
                    **page_result('items', [node_json(row) for row in rows[offset:offset + limit + 1]], offset, limit)}

    @router.get('/tasks/{task_id}/artifacts')
    async def task_artifacts(task_id: int, offset: int = 0, limit: int = 50, session=Depends(require_session)):
        with app.state.session_factory() as db:
            task = owned_task(db, task_id, user_id(session))
            offset, limit = page(offset, limit)
            rows = db.scalars(select(Artifact).where(Artifact.task_id == task.id, Artifact.user_id == user_id(session)).order_by(Artifact.id.desc()).offset(offset).limit(limit + 1)).all()
            return page_result('artifacts', [artifact_json(row) for row in rows], offset, limit)

    @router.get('/runs/{run_id}/artifacts')
    async def run_artifacts(run_id: int, offset: int = 0, limit: int = 50, session=Depends(require_session)):
        with app.state.session_factory() as db:
            run = owned_run(db, run_id, user_id(session))
            offset, limit = page(offset, limit)
            rows = db.scalars(select(Artifact).where(Artifact.run_id == run.id, Artifact.user_id == user_id(session)).order_by(Artifact.id.desc()).offset(offset).limit(limit + 1)).all()
            return page_result('artifacts', [artifact_json(row) for row in rows], offset, limit)

    @router.get('/artifacts/{artifact_id}')
    async def get_artifact(artifact_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            return artifact_json(owned_artifact(db, artifact_id, user_id(session)))

    @router.get('/node-runs/{attempt_id}/artifacts')
    async def node_artifacts(attempt_id: int, offset: int = 0, limit: int = 50, session=Depends(require_session)):
        with app.state.session_factory() as db:
            row = db.get(NodeRun, attempt_id)
            if row is None:
                raise TaskError('not_found', '节点记录不存在。', 404)
            owned_run(db, row.run_id, user_id(session))
            offset, limit = page(offset, limit)
            rows = db.scalars(select(Artifact).where(Artifact.node_run_id == attempt_id, Artifact.user_id == user_id(session)).order_by(Artifact.id.desc()).offset(offset).limit(limit + 1)).all()
            return page_result('artifacts', [artifact_json(item) for item in rows], offset, limit)

    @router.get('/artifacts/{artifact_id}/content')
    async def artifact_content(artifact_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            artifact = owned_artifact(db, artifact_id, user_id(session))
            gateway_file_id, container_id, filename = artifact.gateway_file_id, artifact.gateway_container_id, artifact.filename
        try:
            content = await app.state.gateway.file_content(container_id, gateway_file_id)
        except Exception:
            raise TaskError('artifact_unavailable', '产物下载失败，请稍后重试。', 502) from None
        from urllib.parse import quote
        return Response(content, media_type='application/octet-stream', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename, safe='')}", 'X-Content-Type-Options': 'nosniff'})

    @router.post('/tasks/{task_id}/nodes/{node_id}/adopt')
    async def adopt(task_id: int, node_id: str, body: dict, session=Depends(require_session), key: str | None = Header(None, alias='Idempotency-Key')):
        key_value(key)
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                task = owned_task(db, task_id, user_id(session))
                fingerprint, replay = command_replay(db, task_id, key, f'adopt:{node_id}', body)
                if replay is not None:
                    return replay
                row = db.get(NodeRun, body.get('node_run_id'))
                source = db.get(Run, row.run_id) if row else None
                if not row or not source or source.task_id != task.id or row.node_id != node_id or row.status != 'succeeded':
                    raise TaskError('input_ref_unavailable', '结果不可用。', 422)
                current = json.loads(task.current_result_json)
                current[node_id] = row.id
                task.current_result_json = encoded(current)
                result = {'current_result': current}
                save_command(db, task_id, key, fingerprint, result)
                db.commit()
                return result

    @router.post('/tasks/{task_id}/state')
    async def state(task_id: int, body: dict, session=Depends(require_session)):
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                task = owned_task(db, task_id, user_id(session))
                if db.scalar(select(Run.id).where(Run.task_id == task_id, Run.status.in_(ACTIVE))):
                    raise TaskError('active_run_exists', '请先结束活动运行。')
                action = body.get('action')
                if action == 'reopen' and task.status in ('completed', 'failed', 'waiting'):
                    task.status = 'draft'
                elif action == 'finish' and task.status != 'archived':
                    task.status = 'completed'
                elif action == 'archive' and task.status in ('draft', 'completed', 'failed'):
                    task.archived_status, task.status = task.status, 'archived'
                elif action == 'unarchive' and task.status == 'archived':
                    task.status = task.archived_status or 'draft'
                else:
                    raise TaskError('invalid_transition', '任务状态操作无效。')
                db.commit()
                return task_json(db, task)

    def template_json(db, template, versions_offset=0, versions_limit=100):
        versions = db.scalars(select(TemplateVersion).where(TemplateVersion.template_id == template.id).order_by(TemplateVersion.version).offset(versions_offset).limit(versions_limit + 1)).all()
        latest = db.scalar(select(TemplateVersion).where(TemplateVersion.template_id == template.id).order_by(TemplateVersion.version.desc()).limit(1))
        return {'id': template.id, 'title': template.title, 'workspace_id': template.workspace_id,
                'latest_version': {'id': latest.id, 'version': latest.version, 'workflow': json.loads(latest.definition_json)} if latest else None,
                'versions': [{'id': row.id, 'version': row.version, 'workflow': json.loads(row.definition_json)} for row in versions[:versions_limit]],
                'versions_pagination': {'offset': versions_offset, 'limit': versions_limit, 'has_more': len(versions) > versions_limit}}

    def safe_definition(definition):
        workflow_from_json(definition)
        fields = ('id', 'name', 'agent_id', 'model', 'prompt', 'deps', 'inputRefs', 'requires_human', 'node_type', 'human_action', 'final_report', 'allow_skip', 'allow_missing_inputs', 'condition', 'repeat', 'foreach', 'loop', 'dynamic_plan', 'x', 'y')
        result = {'nodes': [{key: value for key, value in item.items() if key in fields} for item in definition['nodes']]}
        if 'max_concurrency' in definition:
            result['max_concurrency'] = definition['max_concurrency']
        return result

    @router.get('/templates')
    async def templates(offset: int = 0, limit: int = 50, workspace_id: int | None = None, q: str = '', session=Depends(require_session)):
        with app.state.session_factory() as db:
            uid = user_id(session)
            if workspace_id is None:
                workspace_id = selected_space(db, uid)
            check_space(db, workspace_id, uid)
            offset, limit = page(offset, limit)
            query = select(TaskTemplate).where(TaskTemplate.user_id == uid)
            if workspace_id is not None:
                query = query.where(TaskTemplate.workspace_id == workspace_id)
            if q.strip():
                query = query.where(or_(TaskTemplate.title.icontains(q.strip(), autoescape=True), cast(TaskTemplate.id, String).contains(q.strip(), autoescape=True)))
            rows = db.scalars(query.order_by(TaskTemplate.id.desc()).offset(offset).limit(limit + 1)).all()
            return page_result('templates', [template_json(db, row) for row in rows], offset, limit)

    @router.get('/templates/{template_id}')
    async def template(template_id: int, versions_offset: int = 0, versions_limit: int = 100, session=Depends(require_session)):
        with app.state.session_factory() as db:
            row = visible_template(db, template_id, user_id(session))
            versions_offset, versions_limit = page(versions_offset, versions_limit)
            return template_json(db, row, versions_offset, versions_limit)

    @router.post('/templates', status_code=201)
    async def create_template(body: TaskBody, session=Depends(require_session)):
        with app.state.session_factory() as db:
            check_space(db, body.workspace_id, user_id(session))
            definition = safe_definition(redact(body.workflow, secrets()))
            row = TaskTemplate(user_id=user_id(session), workspace_id=body.workspace_id, title=body.title)
            db.add(row)
            db.flush()
            db.add(TemplateVersion(template_id=row.id, version=1, definition_json=encoded(definition)))
            db.commit()
            return template_json(db, row)

    @router.post('/templates/{template_id}/versions', status_code=201)
    async def version(template_id: int, body: WorkflowBody, session=Depends(require_session)):
        with app.state.session_factory() as db:
            row = db.scalar(select(TaskTemplate).where(TaskTemplate.id == template_id, TaskTemplate.user_id == user_id(session)))
            if not row:
                raise TaskError('not_found', '模板不存在。', 404)
            latest = db.scalar(select(TemplateVersion).where(TemplateVersion.template_id == row.id).order_by(TemplateVersion.version.desc()))
            if latest.version != body.expected_revision:
                raise TaskError('revision_conflict', '模板版本已变化。')
            db.add(TemplateVersion(template_id=row.id, version=latest.version + 1, definition_json=encoded(safe_definition(redact(body.workflow, secrets())))))
            db.commit()
            return template_json(db, row)

    @router.post('/tasks/{task_id}/save-as-template', status_code=201)
    async def save_template(task_id: int, body: SaveTemplateBody = SaveTemplateBody(), session=Depends(require_session)):
        with app.state.session_factory() as db:
            task = owned_task(db, task_id, user_id(session))
            revision = db.scalar(select(WorkflowRevision).where(WorkflowRevision.task_id == task.id, WorkflowRevision.revision == (body.workflow_revision or task.current_revision)))
            if revision is None:
                raise TaskError('not_found', '工作流版本不存在。', 404)
            definition = safe_definition(redact(json.loads(revision.definition_json), secrets()))
            if body.template_id is not None:
                row = db.scalar(select(TaskTemplate).where(TaskTemplate.id == body.template_id, TaskTemplate.user_id == task.user_id, TaskTemplate.workspace_id == task.workspace_id))
                if row is None:
                    raise TaskError('not_found', '模板不存在。', 404)
                latest = db.scalar(select(TemplateVersion).where(TemplateVersion.template_id == row.id).order_by(TemplateVersion.version.desc()))
                version_number = latest.version + 1
            else:
                row = TaskTemplate(user_id=task.user_id, workspace_id=task.workspace_id, title=task.title)
                db.add(row)
                db.flush()
                version_number = 1
            db.add(TemplateVersion(template_id=row.id, version=version_number, definition_json=encoded(definition)))
            db.commit()
            return template_json(db, row)

    @router.delete('/tasks/{task_id}', status_code=204)
    async def remove(task_id: int, session=Depends(require_session)):
        cleanup = []
        with app.state.session_factory() as db:
            task = owned_task(db, task_id, user_id(session))
            if db.scalar(select(Run.id).where(Run.task_id == task.id, Run.status.in_(ACTIVE))):
                raise TaskError('active_run_exists', '请先取消活动运行。')
            cleanup = db.scalars(select(Artifact).where(Artifact.task_id == task.id, Artifact.user_id == user_id(session), Artifact.cleanup_status != 'cleaned')).all()
        cleanup_errors = []
        for artifact in cleanup:
            try:
                await app.state.gateway.delete_file(artifact.gateway_file_id)
                with app.state.session_factory() as db:
                    row = db.scalar(select(Artifact).where(Artifact.id == artifact.id))
                    if row:
                        row.cleanup_status = 'cleaned'
                        db.commit()
            except Exception:
                cleanup_errors.append(artifact.id)
        if cleanup_errors:
            with app.state.session_factory() as db:
                db.execute(Artifact.__table__.update().where(Artifact.id.in_(cleanup_errors)).values(cleanup_status='cleanup_failed'))
                db.commit()
            raise TaskError('artifact_cleanup_failed', '任务删除未完成，部分远端产物清理失败，请稍后重试。', 502)
        with app.state.session_factory() as db:
            task = owned_task(db, task_id, user_id(session))
            ids = select(Run.id).where(Run.task_id == task.id)
            # PostgreSQL enforces the current revision foreign key while the
            # immutable revision rows are removed below. Clear the pointer
            # first; SQLite's default foreign-key setting did not expose this.
            task.current_revision_id = None
            db.flush()
            db.execute(delete(Artifact).where(Artifact.task_id == task.id))
            db.execute(delete(NodeRun).where(NodeRun.run_id.in_(ids)))
            db.execute(delete(RunDecision).where(RunDecision.run_id.in_(ids)))
            db.execute(delete(Run).where(Run.task_id == task.id))
            db.execute(delete(WorkflowRevision).where(WorkflowRevision.task_id == task.id))
            db.execute(delete(TaskCommand).where(TaskCommand.task_id == task.id))
            db.delete(task)
            db.commit()

    return router
