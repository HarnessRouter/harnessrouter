from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.db.models import AppWorkspace, Artifact, NodeRun, Run, RunDecision, Task, TaskCommand, WorkflowRevision
from app.gateway.client import GatewayError
from app.tasks.domain import NodeSpec, WorkflowSpec, redact, validate_workflow


ACTIVE = ('pending', 'running', 'waiting_human')


def is_human_node(item):
    return item.get('node_type') in {'human', 'human_gate'} or bool(item.get('requires_human'))


class TaskError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def workflow_from_json(value):
    if not isinstance(value, dict) or not isinstance(value.get('nodes'), list):
        raise TaskError('invalid_workflow', '工作流格式无效。', 422)
    try:
        workflow = WorkflowSpec(tuple(NodeSpec(item['id'], tuple(item.get('deps', [])), tuple(item.get('inputRefs', [])), bool(item.get('final_report')), bool(item.get('requires_human'))) for item in value['nodes']))
        validate_workflow(workflow)
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskError('invalid_workflow', '节点、依赖或输入映射无效。', 422) from exc
    if len(encoded(value).encode()) > 2 * 1024 * 1024:
        raise TaskError('storage_limit_exceeded', '工作流超过 2MB 限制。', 422)
    return workflow


def owned_task(db, task_id, user_id):
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    selected = db.scalar(select(AppWorkspace.id).where(AppWorkspace.user_id == user_id, AppWorkspace.selected.is_(True)))
    if task is None or (selected is not None and task.workspace_id != selected):
        raise TaskError('not_found', '任务不存在。', 404)
    return task


def owned_run(db, run_id, user_id):
    run = db.scalar(select(Run).join(Task, Task.id == Run.task_id).where(Run.id == run_id, Task.user_id == user_id))
    selected = db.scalar(select(AppWorkspace.id).where(AppWorkspace.user_id == user_id, AppWorkspace.selected.is_(True)))
    task = db.get(Task, run.task_id) if run is not None else None
    if run is None or task is None or (selected is not None and task.workspace_id != selected):
        raise TaskError('not_found', '运行记录不存在。', 404)
    return run


def current_revision(db, task):
    if task.current_revision_id:
        revision = db.get(WorkflowRevision, task.current_revision_id)
        if revision and revision.task_id == task.id:
            return revision
    return db.scalar(select(WorkflowRevision).where(WorkflowRevision.task_id == task.id, WorkflowRevision.revision == task.current_revision))


def stale_nodes(db, task):
    adopted = json.loads(task.current_result_json)
    stale = set()
    for node_id, attempt_id in adopted.items():
        row = db.get(NodeRun, attempt_id)
        if row is None:
            stale.add(node_id)
            continue
        for ref in json.loads(row.input_json).get('refs', []):
            if ref['node_id'] in adopted and adopted[ref['node_id']] != ref['node_run_id']:
                stale.add(node_id)
    while True:
        before = set(stale)
        for node_id, attempt_id in adopted.items():
            row = db.get(NodeRun, attempt_id)
            if row and any(ref['node_id'] in stale for ref in json.loads(row.input_json).get('refs', [])):
                stale.add(node_id)
        if before == stale:
            return sorted(stale)


def task_json(db, task):
    revision = current_revision(db, task)
    latest = db.scalar(select(Run).where(Run.task_id == task.id).order_by(Run.id.desc()))
    source = None
    if task.source_template_id and task.source_template_version_id:
        source = {'id': task.source_template_id, 'version_id': task.source_template_version_id, 'version': task.source_template_version}
    return {'id': task.id, 'title': task.title, 'description': task.description, 'input': task.input_text, 'workspace_id': task.workspace_id,
            'source_template_id': task.source_template_id, 'source_template_version_id': task.source_template_version_id, 'source_template_version': task.source_template_version,
            'source_template': source, 'status': task.status, 'current_revision': task.current_revision,
            'current_revision_id': revision.id if revision else None,
            'workflow_revision': {'id': revision.id, 'revision': revision.revision, 'kind': 'saved'} if revision else None,
            'workflow_state': 'saved' if revision else 'draft',
            'workflow': json.loads(revision.definition_json) if revision else {'nodes': []},
            'current_result': json.loads(task.current_result_json), 'stale_nodes': stale_nodes(db, task),
            'latest_run_id': latest.id if latest else None}


def node_json(row):
    return {'id': row.id, 'node_id': row.node_id, 'run_id': row.run_id, 'attempt': row.attempt, 'status': row.status,
            'input': json.loads(row.input_json), 'output': json.loads(row.output_json) if row.output_json else None,
            'error_code': row.error_code, 'response_id': row.response_id,
            'progress': redact({'text': row.partial_text or '', 'execution': json.loads(row.execution_json) if row.execution_json else {}}),
            'started_at': row.started_at.isoformat() if row.started_at else None,
            'finished_at': row.finished_at.isoformat() if row.finished_at else None}


def latest_nodes(db, run_id):
    return {row.node_id: row for row in db.scalars(select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.attempt, NodeRun.id)).all()}


def downstream_nodes(definition, target_node):
    affected = {target_node}
    changed = True
    while changed:
        changed = False
        for item in definition.get('nodes', []):
            if item['id'] not in affected and any(dep in affected for dep in item.get('deps', [])):
                affected.add(item['id'])
                changed = True
    return affected


def run_json(db, run):
    snapshot = json.loads(run.snapshot_json)
    revision = db.get(WorkflowRevision, run.workflow_revision_id) if run.workflow_revision_id else None
    revision_ref = {'id': revision.id, 'revision': revision.revision} if revision else {'id': run.workflow_revision_id, 'revision': run.workflow_revision}
    return {'id': run.id, 'task_id': run.task_id, 'workflow_revision': run.workflow_revision, 'workflow_revision_ref': revision_ref,
            'workflow_revision_number': run.workflow_revision, 'workflow_revision_id': run.workflow_revision_id,
            'status': run.status,
            'paused': run.paused, 'kind': run.kind, 'superseded_by': run.superseded_by,
            'workflow': snapshot.get('workflow', {}), 'execution_snapshot': snapshot,
            'nodes': [node_json(row) for row in latest_nodes(db, run.id).values()],
            'decisions': [{'node_id': row.node_id, 'input_refs': json.loads(row.input_refs_json)} for row in db.scalars(select(RunDecision).where(RunDecision.run_id == run.id)).all()]}


def save_workflow(db, task, expected_revision, workflow):
    workflow_from_json(workflow)
    if db.scalar(select(Run.id).where(Run.task_id == task.id, Run.status.in_(ACTIVE))):
        raise TaskError('active_run_exists', '活动运行中配置已锁定，请先取消运行。')
    claimed = db.execute(update(Task).where(Task.id == task.id, Task.current_revision == expected_revision).values(current_revision=expected_revision + 1))
    if claimed.rowcount != 1:
        raise TaskError('revision_conflict', '工作流版本已变化，请刷新后重试。')
    revision = WorkflowRevision(task_id=task.id, revision=expected_revision + 1, definition_json=encoded(redact(workflow)))
    db.add(revision)
    db.flush()
    task.current_revision_id = revision.id
    db.commit()
    db.refresh(task)
    return task_json(db, task)


def command_replay(db, task_id, key, action, body):
    fingerprint = hashlib.sha256(encoded({'action': action, 'body': body}).encode()).hexdigest()
    prior = db.scalar(select(TaskCommand).where(TaskCommand.task_id == task_id, TaskCommand.key == key))
    if prior and prior.fingerprint != fingerprint:
        raise TaskError('idempotency_conflict', '幂等键已用于其他请求。')
    return fingerprint, json.loads(prior.response_json) if prior else None


def save_command(db, task_id, key, fingerprint, result):
    db.add(TaskCommand(task_id=task_id, key=key, fingerprint=fingerprint, response_json=encoded(result)))


async def prepare_run(db, task, body, key, gateway, secrets):
    fingerprint = hashlib.sha256(encoded(body).encode()).hexdigest()
    prior = db.scalar(select(Run).where(Run.task_id == task.id, Run.idempotency_key == key))
    if prior:
        if prior.request_hash != fingerprint:
            raise TaskError('idempotency_conflict', '幂等键已用于其他请求。')
        return prior, True
    if task.status == 'archived' or (task.status == 'completed' and body.get('kind') != 'rerun'):
        raise TaskError('invalid_transition', '请先重新打开任务。')
    revision = current_revision(db, task)
    definition = json.loads(revision.definition_json)
    workflow_from_json(definition)
    if not definition['nodes']:
        raise TaskError('invalid_workflow', '请先添加 Agent 节点。', 422)
    active = db.scalar(select(Run).where(Run.task_id == task.id, Run.status.in_(ACTIVE)))
    if active and not ((active.status == 'waiting_human' or active.paused) and active.workflow_revision != task.current_revision):
        raise TaskError('active_run_exists', '任务已有正在运行的 Run。')
    try:
        agents = {row['id']: row for row in await gateway.list_agents(getattr(gateway, 'api_key', None))}
        catalogs = {}
        for item in definition['nodes']:
            if item.get('node_type') in {'human', 'human_gate'}:
                continue
            agent_id = item.get('agent_id', '')
            if agent_id not in agents:
                raise ValueError('agent unavailable')
            if agent_id not in catalogs:
                catalogs[agent_id] = await gateway.list_agent_models(agent_id)
            available = {row['id'] for row in catalogs[agent_id].get('models', []) if row.get('available', True)}
            if item.get('model') not in available:
                raise ValueError('model unavailable')
    except Exception as exc:
        raise TaskError('configuration_unavailable', '节点 Agent 或模型不可用，请检查配置。', 422) from exc
    snapshot = redact({'workflow': definition, 'input': task.input_text, 'agents': agents,
                       'workflow_revision_id': revision.id,
                       'source': {'kind': 'saved_workflow_revision', 'revision': revision.revision}}, secrets)
    run = Run(task_id=task.id, workflow_revision=task.current_revision, workflow_revision_id=revision.id, idempotency_key=key, request_hash=fingerprint,
              snapshot_json=encoded(snapshot), kind=body.get('kind', 'normal'), target_node=body.get('target_node'))
    if run.kind == 'rerun' and run.target_node not in {item['id'] for item in definition['nodes']}:
        raise TaskError('invalid_workflow', '重跑节点不存在。', 422)
    db.add(run)
    db.flush()
    reused = {}
    if run.kind == 'rerun' and run.target_node:
        affected = downstream_nodes(definition, run.target_node)
        adopted = json.loads(task.current_result_json)
        for node_id, attempt_id in adopted.items():
            row = db.get(NodeRun, attempt_id)
            source = db.get(Run, row.run_id) if row else None
            if node_id not in affected and row and source and source.task_id == task.id and row.status == 'succeeded':
                reused[node_id] = row
    for attempt_id in body.get('reuse_refs', []):
        row = db.get(NodeRun, attempt_id)
        source = db.get(Run, row.run_id) if row else None
        if not row or not source or source.task_id != task.id or row.status != 'succeeded' or row.node_id in stale_nodes(db, task):
            raise TaskError('input_ref_unavailable', '复用结果无效或已过期。', 422)
        reused[row.node_id] = row
    for item in definition['nodes']:
        row = reused.get(item['id'])
        db.add(NodeRun(run_id=run.id, node_id=item['id'], status='succeeded' if row else 'idle',
                       input_json=encoded({'reused_from': row.id}) if row else '{}', output_json=row.output_json if row else None))
    if active:
        active.status = 'completed'
        active.superseded_by = run.id
    task.status = 'running'
    db.commit()
    return run, False


class TaskExecutor:
    def __init__(self, session_factory, gateway, secrets=()):
        self.session_factory, self.gateway, self.secrets = session_factory, gateway, secrets
        self.jobs = {}
        self.locks = {}

    def lock(self, task_id):
        return self.locks.setdefault(task_id, asyncio.Lock())

    def schedule(self, run_id):
        if run_id not in self.jobs or self.jobs[run_id].done():
            job = asyncio.create_task(self.execute(run_id))
            self.jobs[run_id] = job

    async def close(self):
        for job in self.jobs.values():
            job.cancel()
        await asyncio.gather(*self.jobs.values(), return_exceptions=True)

    def recover(self):
        with self.session_factory() as db:
            for run in db.scalars(select(Run).where(Run.status.in_(('pending', 'running')))).all():
                if run.paused:
                    continue
                run.status = 'failed'
                task = db.get(Task, run.task_id)
                task.status = 'failed'
                for row in latest_nodes(db, run.id).values():
                    if row.status in ('queued', 'running'):
                        row.status, row.error_code = 'failed', 'interrupted_unknown_outcome'
            db.commit()

    async def execute(self, run_id):
        try:
            while True:
                with self.session_factory() as db:
                    run = db.get(Run, run_id)
                    if not run or run.status not in ('pending', 'running') or run.paused:
                        return
                    run.status = 'running'
                    task = db.get(Task, run.task_id)
                    snapshot = json.loads(run.snapshot_json)
                    definition = snapshot['workflow']
                    rows = latest_nodes(db, run.id)
                    nodes = {item['id']: item for item in definition['nodes']}
                    decisions = {row.node_id: json.loads(row.input_refs_json) for row in db.scalars(select(RunDecision).where(RunDecision.run_id == run.id)).all()}
                    unfinished = [item for item in nodes.values() if rows[item['id']].status == 'idle']
                    ready = [item for item in unfinished if all(rows[dep].status == 'succeeded' or (rows[dep].status == 'skipped' and item.get('allow_missing_inputs')) for dep in item.get('deps', []))]
                    executable = [item for item in ready if not is_human_node(item) or item['id'] in decisions]
                    if not executable:
                        if ready:
                            run.status, task.status = 'waiting_human', 'waiting'
                        elif any(row.status == 'failed' for row in rows.values()):
                            run.status, task.status = 'failed', 'failed'
                        elif not unfinished:
                            run.status = 'completed'
                            final = next((item for item in nodes.values() if item.get('final_report') and rows[item['id']].status == 'succeeded'), None)
                            if final:
                                task.current_result_json = encoded({final['id']: rows[final['id']].id})
                                task.status = 'completed'
                            else:
                                task.status = 'waiting'
                        else:
                            run.status, task.status = 'failed', 'failed'
                        db.commit()
                        return
                    calls = []
                    space = db.get(AppWorkspace, task.workspace_id) if task.workspace_id else None
                    for item in executable:
                        row = rows[item['id']]
                        refs = decisions.get(item['id'], item.get('inputRefs', []))
                        if item.get('node_type') in {'human', 'human_gate'}:
                            inputs = [{'task_id': task.id, 'run_id': run.id, 'node_id': ref, 'node_run_id': rows[ref].id, 'output': json.loads(rows[ref].output_json)} for ref in refs if rows[ref].status == 'succeeded']
                            row.input_json = encoded({'task_input': snapshot['input'], 'refs': inputs, 'decision': 'human_confirmed'})
                            row.output_json = encoded({'selected_input_refs': refs, 'selected_results': inputs, 'status': 'confirmed'})
                            row.status = 'succeeded'
                            row.started_at = row.started_at or datetime.now(timezone.utc)
                            row.finished_at = datetime.now(timezone.utc)
                            continue
                        inputs = [{'task_id': task.id, 'run_id': run.id, 'node_id': ref, 'node_run_id': rows[ref].id, 'output': json.loads(rows[ref].output_json)} for ref in refs if rows[ref].status == 'succeeded']
                        context = redact({'task_input': snapshot['input'], 'prompt': item.get('prompt', ''), 'refs': inputs}, self.secrets)
                        row.input_json, row.status = encoded(context), 'running'
                        row.started_at = datetime.now(timezone.utc)
                        calls.append((row.id, item, context, space.gateway_id if space else ''))
                    db.commit()
                await asyncio.gather(*(self.execute_node(run_id, *call) for call in calls))
        except asyncio.CancelledError:
            raise
        except Exception:
            with self.session_factory() as db:
                run = db.get(Run, run_id)
                if run and run.status in ('pending', 'running'):
                    run.status = 'failed'
                    task = db.get(Task, run.task_id)
                    if task:
                        task.status = 'failed'
                    for row in latest_nodes(db, run_id).values():
                        if row.status in ('queued', 'running'):
                            row.status = 'failed'
                            row.error_code = 'executor_error'
                    db.commit()

    async def execute_node(self, run_id, attempt_id, item, context, workspace_id):
        result, error = None, None
        def save_progress(*, response_id=None, partial=None, details=None):
            with self.session_factory() as db:
                row, run = db.get(NodeRun, attempt_id), db.get(Run, run_id)
                if not row or not run or row.status != 'running' or run.status != 'running':
                    return
                if response_id:
                    row.response_id = response_id
                if partial is not None:
                    row.partial_text = redact(partial, self.secrets)[:262144]
                if details is not None:
                    from app.gateway.execution import safe_execution
                    row.execution_json = encoded(safe_execution(details, self.secrets))
                db.commit()
        async def progress(response_id, partial):
            save_progress(response_id=response_id, partial=partial)
        async def execution(details):
            save_progress(details=details)
        try:
            result = await self.gateway.create_response(encoded(context), None, f'hexa-task-{run_id}-{attempt_id}', agent_id=item['agent_id'], model=item['model'], workspace_id=workspace_id, on_progress=progress, on_execution=execution)
            if result.get('execution'):
                await execution(result['execution'])
            if result.get('status') != 'completed':
                error = 'agent_incomplete'
            if len(encoded(result).encode()) > 1024 * 1024:
                error = 'storage_limit_exceeded'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = 'agent_failed' if isinstance(exc, GatewayError) and not exc.uncertain else 'interrupted_unknown_outcome'
        with self.session_factory() as db:
            run, row = db.get(Run, run_id), db.get(NodeRun, attempt_id)
            if run is None or row is None or run.status != 'running' or row.status != 'running':
                return
            task = db.get(Task, run.task_id)
            artifacts = []
            for file in (result or {}).get('files', []) if not error and isinstance(result, dict) else []:
                if not file.get('file_id') or not file.get('container_id'):
                    continue
                artifact = Artifact(
                    user_id=task.user_id,
                    workspace_id=task.workspace_id,
                    task_id=task.id,
                    run_id=run.id,
                    node_run_id=row.id,
                    gateway_file_id=str(file['file_id']),
                    gateway_container_id=str(file['container_id']),
                    filename=str(file.get('filename') or '输出文件')[:1024],
                    media_type=str(file.get('media_type') or 'application/octet-stream')[:255],
                    bytes=int(file.get('bytes') or 0),
                )
                db.add(artifact)
                db.flush()
                artifacts.append({'id': artifact.id, 'filename': artifact.filename, 'media_type': artifact.media_type, 'bytes': artifact.bytes})
            row.status = 'failed' if error else 'succeeded'
            row.error_code = error
            if error:
                row.output_json = None
            else:
                safe_result = dict(redact(result, self.secrets)) if isinstance(result, dict) else {'value': redact(result, self.secrets)}
                safe_result.pop('files', None)
                if artifacts:
                    safe_result['artifacts'] = artifacts
                row.output_json = encoded(safe_result)
            row.finished_at = datetime.now(timezone.utc)
            db.commit()
