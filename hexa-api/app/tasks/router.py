import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.db.models import AppWorkspace, NodeRun, Run, RunDecision, Task, TaskCommand, TaskTemplate, TemplateVersion, WorkflowRevision
from app.tasks.domain import redact
from app.tasks.service import ACTIVE, TaskError, command_replay, current_revision, encoded, latest_nodes, node_json, owned_run, owned_task, prepare_run, run_json, save_command, save_workflow, stale_nodes, task_json, workflow_from_json


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


class RunBody(BaseModel):
    kind: str = Field(default='normal', pattern='^(normal|rerun)$')
    target_node: str | None = None
    reuse_refs: list[int] = Field(default_factory=list, max_length=50)


def build_router(app, require_session, user_id):
    router = APIRouter(prefix='/api/hexa')

    def check_space(db, workspace_id, uid):
        if workspace_id is not None and not db.scalar(select(AppWorkspace.id).where(AppWorkspace.id == workspace_id, AppWorkspace.user_id == uid)):
            raise TaskError('not_found', '工作区不存在。', 404)

    def secrets():
        return (app.state.settings.gateway_api_key, app.state.settings.session_secret)

    def key_value(key):
        if not key or len(key) > 255:
            raise TaskError('invalid_idempotency_key', '缺少有效的幂等键。', 400)
        return key

    @router.post('/tasks', status_code=201)
    async def create_task(body: TaskBody, session=Depends(require_session)):
        with app.state.session_factory() as db:
            uid = user_id(session)
            check_space(db, body.workspace_id, uid)
            definition = body.workflow
            if body.template_version_id:
                version = db.scalar(select(TemplateVersion).join(TaskTemplate, TaskTemplate.id == TemplateVersion.template_id).where(TemplateVersion.id == body.template_version_id, TaskTemplate.user_id == uid, TaskTemplate.workspace_id == body.workspace_id))
                if not version:
                    raise TaskError('not_found', '模板版本不存在。', 404)
                definition = json.loads(version.definition_json)
            workflow_from_json(definition)
            task = Task(user_id=uid, workspace_id=body.workspace_id, title=body.title.strip() or '未命名任务', description=redact(body.description, secrets()), input_text=redact(body.input, secrets()), current_revision=1)
            db.add(task)
            db.flush()
            db.add(WorkflowRevision(task_id=task.id, revision=1, definition_json=encoded(redact(definition, secrets()))))
            db.commit()
            return task_json(db, task)

    @router.get('/tasks')
    async def list_tasks(offset: int = 0, limit: int = 50, workspace_id: int | None = None, session=Depends(require_session)):
        with app.state.session_factory() as db:
            check_space(db, workspace_id, user_id(session))
            query = select(Task).where(Task.user_id == user_id(session))
            if workspace_id is not None:
                query = query.where(Task.workspace_id == workspace_id)
            rows = db.scalars(query.order_by(Task.id.desc()).offset(max(0, offset)).limit(min(max(limit, 1), 100))).all()
            return {'tasks': [task_json(db, row) for row in rows]}

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
            rows = db.scalars(select(Run).where(Run.task_id == task_id).order_by(Run.id.desc()).offset(max(0, offset)).limit(min(max(limit, 1), 100))).all()
            return {'runs': [run_json(db, row) for row in rows]}

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
                        if not item or not item.get('requires_human') or not refs or len(set(refs)) != len(refs) or set(refs) - set(item.get('deps', [])) or any(rows[ref].status != 'succeeded' for ref in refs):
                            raise TaskError('invalid_decision', '人工选择的节点或结果无效。', 422)
                        db.add(RunDecision(run_id=run_id, node_id=item['id'], input_refs_json=encoded(refs)))
                    run.status, task.status = 'running', 'running'
                elif action == 'pause':
                    run.paused, task.status = True, 'waiting'
                elif action == 'cancel':
                    run.status, task.status = 'canceled', 'waiting'
                    for row in rows.values():
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
                for row in rows.values():
                    if row.response_id and row.status == 'canceled':
                        try:
                            await app.state.gateway.cancel_response(row.response_id)
                        except Exception:
                            pass
            return result

    @router.post('/runs/{run_id}/nodes/{node_id}/{action}')
    async def node_control(run_id: int, node_id: str, action: str, session=Depends(require_session), key: str | None = Header(None, alias='Idempotency-Key')):
        key_value(key)
        with app.state.session_factory() as db:
            run = owned_run(db, run_id, user_id(session))
            task_id = run.task_id
        async with app.state.task_executor.lock(task_id):
            with app.state.session_factory() as db:
                run = owned_run(db, run_id, user_id(session))
                fingerprint, replay = command_replay(db, task_id, key, f'{run_id}:{node_id}:{action}', {})
                if replay is not None:
                    return replay
                row = latest_nodes(db, run_id).get(node_id)
                if run.status not in ACTIVE or not row:
                    raise TaskError('invalid_transition', '终态运行请创建新的 Run。')
                definition = json.loads(run.snapshot_json)['workflow']
                item = next(item for item in definition['nodes'] if item['id'] == node_id)
                if action == 'skip' and item.get('allow_skip') and row.status in ('idle', 'failed', 'canceled'):
                    row.status = 'skipped'
                elif action == 'retry' and row.status in ('failed', 'canceled'):
                    if db.query(NodeRun).filter_by(run_id=run_id).count() >= 500:
                        raise TaskError('storage_limit_exceeded', '运行超过 500 次尝试限制。', 422)
                    db.add(NodeRun(run_id=run_id, node_id=node_id, attempt=row.attempt + 1, status='idle'))
                else:
                    raise TaskError('invalid_transition', '节点操作不被当前状态或配置允许。')
                run.status = 'running'
                result = {'id': run.id, 'status': run.status}
                save_command(db, task_id, key, fingerprint, result)
                db.commit()
                app.state.task_executor.schedule(run_id)
                return result

    @router.get('/node-runs/{attempt_id}')
    async def debug(attempt_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            row = db.get(NodeRun, attempt_id)
            if not row:
                raise TaskError('not_found', '节点记录不存在。', 404)
            run = owned_run(db, row.run_id, user_id(session))
            attempts = db.scalars(select(NodeRun).where(NodeRun.run_id == run.id, NodeRun.node_id == row.node_id).order_by(NodeRun.attempt).limit(500)).all()
            return {**node_json(row), 'environment': json.loads(run.snapshot_json), 'attempts': [node_json(attempt) for attempt in attempts]}

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

    def template_json(db, template):
        versions = db.scalars(select(TemplateVersion).where(TemplateVersion.template_id == template.id).order_by(TemplateVersion.version)).all()
        return {'id': template.id, 'title': template.title, 'workspace_id': template.workspace_id, 'versions': [{'id': row.id, 'version': row.version, 'workflow': json.loads(row.definition_json)} for row in versions]}

    def safe_definition(definition):
        workflow_from_json(definition)
        fields = ('id', 'name', 'agent_id', 'model', 'prompt', 'deps', 'inputRefs', 'requires_human', 'final_report', 'allow_skip', 'allow_missing_inputs', 'x', 'y')
        return {'nodes': [{key: value for key, value in item.items() if key in fields} for item in definition['nodes']]}

    @router.get('/templates')
    async def templates(session=Depends(require_session)):
        with app.state.session_factory() as db:
            return {'templates': [template_json(db, row) for row in db.scalars(select(TaskTemplate).where(TaskTemplate.user_id == user_id(session)).limit(100)).all()]}

    @router.get('/templates/{template_id}')
    async def template(template_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            row = db.scalar(select(TaskTemplate).where(TaskTemplate.id == template_id, TaskTemplate.user_id == user_id(session)))
            if not row:
                raise TaskError('not_found', '模板不存在。', 404)
            return template_json(db, row)

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
    async def save_template(task_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            task = owned_task(db, task_id, user_id(session))
            definition = safe_definition(json.loads(current_revision(db, task).definition_json))
            row = TaskTemplate(user_id=task.user_id, workspace_id=task.workspace_id, title=task.title)
            db.add(row)
            db.flush()
            db.add(TemplateVersion(template_id=row.id, version=1, definition_json=encoded(definition)))
            db.commit()
            return template_json(db, row)

    @router.delete('/tasks/{task_id}', status_code=204)
    async def remove(task_id: int, session=Depends(require_session)):
        with app.state.session_factory() as db:
            task = owned_task(db, task_id, user_id(session))
            if db.scalar(select(Run.id).where(Run.task_id == task.id, Run.status.in_(ACTIVE))):
                raise TaskError('active_run_exists', '请先取消活动运行。')
            ids = select(Run.id).where(Run.task_id == task.id)
            db.execute(delete(NodeRun).where(NodeRun.run_id.in_(ids)))
            db.execute(delete(RunDecision).where(RunDecision.run_id.in_(ids)))
            db.execute(delete(Run).where(Run.task_id == task.id))
            db.execute(delete(WorkflowRevision).where(WorkflowRevision.task_id == task.id))
            db.execute(delete(TaskCommand).where(TaskCommand.task_id == task.id))
            db.delete(task)
            db.commit()

    return router
