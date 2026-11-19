from __future__ import annotations

import pytest


def login(client):
    response = client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})
    assert response.status_code == 200


def workflow():
    return {
        "nodes": [
            {"id": "collect-a", "agent_id": "agent-1", "model": "gpt-6.1", "requires_human": True},
            {"id": "collect-b", "agent_id": "agent-1", "model": "gpt-6.1"},
            {"id": "summary", "agent_id": "agent-1", "model": "gpt-6.1", "deps": ["collect-a", "collect-b"], "inputRefs": ["collect-a"]},
        ]
    }


def test_task_create_get_and_workflow_revision_conflict(client):
    login(client)
    created = client.post("/api/hexa/tasks", json={"title": "安全事件调查", "workflow": workflow()})
    assert created.status_code == 201
    assert created.json()["current_revision"] == 1
    task_id = created.json()["id"]

    fetched = client.get(f"/api/hexa/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["workflow"] == workflow()

    updated = client.put(
        f"/api/hexa/tasks/{task_id}/workflow",
        json={"expected_revision": 1, "workflow": {"nodes": [{"id": "report", "final_report": True}]}},
    )
    assert updated.status_code == 200
    assert updated.json()["current_revision"] == 2

    conflict = client.put(
        f"/api/hexa/tasks/{task_id}/workflow",
        json={"expected_revision": 1, "workflow": workflow()},
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"code": "revision_conflict", "message": "工作流版本已变化，请刷新后重试。"}}


def test_run_creation_is_idempotent_and_blocks_second_active_run(client):
    login(client)
    task = client.post("/api/hexa/tasks", json={"title": "运行测试", "workflow": workflow()}).json()
    headers = {"Idempotency-Key": "run-1"}

    first = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers=headers)
    assert first.status_code == 202
    assert first.json()["status"] == "pending"

    replay = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers=headers)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    blocked = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={"Idempotency-Key": "run-2"})
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": {"code": "active_run_exists", "message": "任务已有正在运行的 Run。"}}


def test_task_routes_require_authentication(client):
    response = client.get("/api/hexa/tasks")
    assert response.status_code == 401


def test_task_and_run_lists_expose_compatible_pagination_and_node_page(client, app):
    login(client)
    task = client.post('/api/hexa/tasks', json={'title': '分页任务', 'workflow': workflow()}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'page-run'}).json()
    tasks = client.get('/api/hexa/tasks?offset=0&limit=1')
    assert tasks.status_code == 200
    assert tasks.json()['pagination'] == {'offset': 0, 'limit': 1, 'has_more': False}
    runs = client.get(f"/api/hexa/tasks/{task['id']}/runs?offset=0&limit=1")
    assert runs.status_code == 200
    assert runs.json()['pagination'] == {'offset': 0, 'limit': 1, 'has_more': False}
    nodes = client.get(f"/api/hexa/runs/{run['id']}/nodes?offset=0&limit=1")
    assert nodes.status_code == 200
    assert len(nodes.json()['nodes']) == 1
    assert nodes.json()['pagination'] == {'offset': 0, 'limit': 1, 'has_more': True}


def test_debug_attempt_pages_never_include_the_lookahead_row(client, app):
    from app.db.models import NodeRun, Run
    login(client)
    task = client.post('/api/hexa/tasks', json={'title': 'Attempt pages'}).json()
    with app.state.session_factory() as db:
        run = Run(task_id=task['id'], workflow_revision=1, idempotency_key='attempt-pages', request_hash='test', snapshot_json='{"workflow":{"nodes":[]}}', status='failed')
        db.add(run)
        db.flush()
        rows = [NodeRun(run_id=run.id, node_id='report', attempt=i, status='failed') for i in range(1, 4)]
        db.add_all(rows)
        db.commit()
        attempt_id = rows[-1].id
    for offset, expected, more in [(0, [1], True), (1, [2], True), (2, [3], False), (3, [], False)]:
        response = client.get(f'/api/hexa/node-runs/{attempt_id}?offset={offset}&limit=1')
        assert response.status_code == 200
        assert [row['attempt'] for row in response.json()['attempts']] == expected
        assert response.json()['attempts_pagination'] == {'offset': offset, 'limit': 1, 'has_more': more}


def test_artifact_cleanup_failure_keeps_history_and_retries_only_failed_files(client, app):
    from app.db.models import Artifact
    login(client)
    task = client.post('/api/hexa/tasks', json={'title': 'Cleanup retry'}).json()
    with app.state.session_factory() as db:
        rows = [Artifact(user_id=1, task_id=task['id'], run_id=1, node_run_id=1, gateway_file_id=f'file-{i}', gateway_container_id='container', filename=f'report-{i}.txt', media_type='text/plain', bytes=1) for i in range(2)]
        db.add_all(rows)
        db.commit()
    calls = []

    async def delete_file(file_id):
        calls.append(file_id)
        if file_id == 'file-1' and calls.count(file_id) == 1:
            raise RuntimeError('remote unavailable')

    app.state.gateway.delete_file = delete_file
    first = client.delete(f"/api/hexa/tasks/{task['id']}")
    assert first.status_code == 502
    assert first.json()['detail']['code'] == 'artifact_cleanup_failed'
    assert client.get(f"/api/hexa/tasks/{task['id']}").status_code == 200
    artifacts = client.get(f"/api/hexa/tasks/{task['id']}/artifacts").json()['artifacts']
    assert {row['filename']: row['cleanup_status'] for row in artifacts} == {'report-0.txt': 'cleaned', 'report-1.txt': 'cleanup_failed'}
    assert client.delete(f"/api/hexa/tasks/{task['id']}").status_code == 204
    assert calls.count('file-0') == 1
    assert calls.count('file-1') == 2
    assert client.get(f"/api/hexa/tasks/{task['id']}").status_code == 404
    with app.state.session_factory() as db:
        assert db.query(Artifact).filter_by(task_id=task['id']).count() == 0


def test_task_artifacts_are_owned_downloadable_and_persist_gateway_reference(client, app):
    login(client)

    async def response(*args, **kwargs):
        return {
            'response_id': 'artifact-response',
            'text': '报告已生成',
            'status': 'completed',
            'files': [{
                'file_id': 'gateway-file-1',
                'container_id': 'gateway-container-1',
                'filename': '<报告>.html',
                'media_type': 'text/html',
                'bytes': 17,
            }],
        }

    async def content(container_id, file_id):
        assert (container_id, file_id) == ('gateway-container-1', 'gateway-file-1')
        return b'<h1>report</h1>'

    app.state.gateway.create_response = response
    app.state.gateway.file_content = content
    task = client.post('/api/hexa/tasks', json={'title': '产物任务', 'workflow': {'nodes': [{'id': 'report', 'agent_id': 'agent-1', 'model': 'gpt-6.1', 'final_report': True}]}}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'artifact-run'}).json()

    import time
    for _ in range(100):
        current = client.get(f"/api/hexa/runs/{run['id']}").json()
        if current['status'] == 'completed':
            break
        time.sleep(0.01)
    artifacts = client.get(f"/api/hexa/tasks/{task['id']}/artifacts?limit=10")
    assert artifacts.status_code == 200
    assert artifacts.json()['pagination']['has_more'] is False
    artifact = artifacts.json()['artifacts'][0]
    assert artifact['filename'] == '<报告>.html'
    assert artifact['task_id'] == task['id']
    assert artifact['run_id'] == run['id']
    assert artifact['node_run_id'] == current['nodes'][0]['id']
    assert 'gateway_file_id' not in artifact
    assert client.get(f"/api/hexa/runs/{run['id']}/artifacts").json()['artifacts'][0]['id'] == artifact['id']
    assert client.get(f"/api/hexa/node-runs/{artifact['node_run_id']}").json()['artifacts'][0]['id'] == artifact['id']
    download = client.get(f"/api/hexa/artifacts/{artifact['id']}/content")
    assert download.status_code == 200
    assert download.content == b'<h1>report</h1>'
    assert download.headers['content-type'] == 'application/octet-stream'
    assert download.headers['x-content-type-options'] == 'nosniff'
    assert download.headers['content-disposition'].startswith('attachment;')


def test_task_artifact_cannot_be_read_or_referenced_by_another_task(client, app):
    login(client)
    from app.db.models import Artifact
    with app.state.session_factory() as db:
        row = Artifact(user_id=999, workspace_id=None, task_id=999, run_id=999, node_run_id=999, gateway_file_id='private-file', gateway_container_id='private-container', filename='private.txt', media_type='text/plain', bytes=1)
        db.add(row)
        db.commit()
        artifact_id = row.id
    assert client.get(f'/api/hexa/artifacts/{artifact_id}').status_code == 404
    assert client.get(f'/api/hexa/artifacts/{artifact_id}/content').status_code == 404


def test_selected_workspace_hides_task_run_template_and_artifact_details(client, app):
    login(client)
    first = client.post('/api/hexa/workspaces', json={'name': '第一空间'}).json()
    second = client.post('/api/hexa/workspaces', json={'name': '第二空间'}).json()
    task_one = client.post('/api/hexa/tasks', json={'title': '第一任务', 'workspace_id': first['id']}).json()
    task_two = client.post('/api/hexa/tasks', json={'title': '第二任务', 'workspace_id': second['id']}).json()
    template_one = client.post('/api/hexa/templates', json={'title': '第一模板', 'workspace_id': first['id'], 'workflow': {'nodes': []}}).json()
    template_two = client.post('/api/hexa/templates', json={'title': '第二模板', 'workspace_id': second['id'], 'workflow': {'nodes': []}}).json()
    run = client.post(f"/api/hexa/tasks/{task_one['id']}/runs", headers={'Idempotency-Key': 'workspace-detail-run'})
    assert run.status_code == 422  # empty workflow is rejected before a run is created
    assert client.post('/api/hexa/workspaces/select', json={'workspace_id': second['id']}).status_code == 200
    assert client.get(f"/api/hexa/tasks/{task_one['id']}").status_code == 404
    assert client.get(f"/api/hexa/tasks/{task_two['id']}").status_code == 200
    assert client.get(f"/api/hexa/templates/{template_one['id']}").status_code == 404
    assert client.get(f"/api/hexa/templates/{template_two['id']}").status_code == 200


def test_template_task_pins_source_and_saved_template_version(client):
    login(client)
    definition = {'nodes': [{'id': 'original', 'name': '原版'}]}
    template = client.post('/api/hexa/templates', json={'title': '来源', 'workflow': definition}).json()
    source = template['versions'][0]
    task = client.post('/api/hexa/tasks', json={'title': '模板任务', 'template_version_id': source['id']}).json()
    assert task.get('source_template_id') == template['id']
    assert task.get('source_template_version_id') == source['id']
    assert task.get('source_template_version') == 1
    client.post(f"/api/hexa/templates/{template['id']}/versions", json={'expected_revision': 1, 'workflow': {'nodes': [{'id': 'upgraded'}]}})
    assert client.get(f"/api/hexa/tasks/{task['id']}").json()['workflow'] == definition
    changed = {'nodes': [{'id': 'changed', 'name': '任务改图'}]}
    client.put(f"/api/hexa/tasks/{task['id']}/workflow", json={'expected_revision': 1, 'workflow': changed})
    assert client.get(f"/api/hexa/tasks/{task['id']}").json()['source_template_version_id'] == source['id']
    exported = client.post(f"/api/hexa/tasks/{task['id']}/save-as-template", json={'workflow_revision': 1}).json()
    assert exported['id'] != template['id']
    assert exported['versions'][0]['workflow'] == definition
    appended = client.post(f"/api/hexa/tasks/{task['id']}/save-as-template", json={'workflow_revision': 2, 'template_id': template['id']})
    assert appended.status_code == 201
    assert len(appended.json()['versions']) == 3
    assert appended.json()['versions'][-1]['workflow'] == changed
    missing = client.post(f"/api/hexa/tasks/{task['id']}/save-as-template", json={'workflow_revision': 999})
    assert missing.status_code == 404
    denied = client.post(f"/api/hexa/tasks/{task['id']}/save-as-template", json={'workflow_revision': 2, 'template_id': 999})
    assert denied.status_code == 404


def test_task_domain_payload_exposes_saved_revision_source_and_run_snapshot(client):
    login(client)
    definition = {'nodes': [{'id': 'source', 'agent_id': 'agent-1', 'model': 'gpt-6.1'}]}
    template = client.post('/api/hexa/templates', json={'title': '领域模板', 'workflow': definition}).json()
    source = template['versions'][0]
    task = client.post('/api/hexa/tasks', json={'title': '领域任务', 'template_version_id': source['id']}).json()

    assert task['workflow_state'] == 'saved'
    assert task['workflow_revision'] == {
        'id': task['current_revision_id'],
        'revision': 1,
        'kind': 'saved',
    }
    assert task['source_template'] == {
        'id': template['id'],
        'version_id': source['id'],
        'version': 1,
    }

    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'domain-run'}).json()
    snapshot = client.get(f"/api/hexa/runs/{run['id']}").json()
    assert snapshot['workflow_revision_id'] == task['current_revision_id']
    assert snapshot['workflow_revision'] == 1
    assert snapshot['workflow_revision_ref'] == {'id': task['current_revision_id'], 'revision': 1}
    assert snapshot['execution_snapshot']['workflow_revision_id'] == task['current_revision_id']
    assert snapshot['execution_snapshot']['workflow'] == definition
    assert snapshot['execution_snapshot']['source'] == {'kind': 'saved_workflow_revision', 'revision': 1}


def test_run_snapshot_keeps_revision_identity_after_task_is_saved_again(client, app):
    login(client)
    first = {'nodes': [{'id': 'first', 'agent_id': 'agent-1', 'model': 'gpt-6.1'}]}
    task = client.post('/api/hexa/tasks', json={'title': '版本快照', 'workflow': first}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'snapshot-identity'}).json()

    # Finish the run, then create a new saved revision and verify the historical identity.
    import time
    for _ in range(100):
        current = client.get(f"/api/hexa/runs/{run['id']}").json()
        if current['status'] == 'completed':
            break
        time.sleep(0.01)
    saved = client.put(
        f"/api/hexa/tasks/{task['id']}/workflow",
        json={'expected_revision': 1, 'workflow': {'nodes': [{'id': 'second', 'agent_id': 'agent-1', 'model': 'gpt-6.1'}]}},
    )
    assert saved.status_code == 200
    history = client.get(f"/api/hexa/runs/{run['id']}").json()
    assert history['workflow_revision'] == 1
    assert history['workflow_revision_ref'] == {'id': task['current_revision_id'], 'revision': 1}
    assert history['execution_snapshot']['workflow']['nodes'][0]['id'] == 'first'
    assert history['workflow']['nodes'][0]['id'] == 'first'


def test_active_paused_run_keeps_task_execution_definition_locked(client):
    login(client)
    task = client.post('/api/hexa/tasks', json={'title': '暂停锁定', 'workflow': workflow()}).json()
    run = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'lock-run'}).json()
    client.post(f"/api/hexa/runs/{run['id']}/pause", headers={'Idempotency-Key': 'pause'})
    response = client.put(f"/api/hexa/tasks/{task['id']}/workflow", json={'expected_revision': 1, 'workflow': {'nodes': []}})
    assert response.status_code == 409


def test_existing_sqlite_tasks_gain_nullable_source_columns_without_rewriting_records(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app.db.models import create_session_factory
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)"))
        db.execute(text("INSERT INTO tasks (id, title) VALUES (71, 'retained task')"))
    factory = create_session_factory(url)
    columns = {column['name'] for column in inspect(factory.kw['bind']).get_columns('tasks')}
    assert {'source_template_id', 'source_template_version_id', 'source_template_version'} <= columns
    with factory() as db:
        row = db.execute(text('SELECT title, source_template_version_id FROM tasks WHERE id = 71')).one()
        assert row == ('retained task', None)
    create_session_factory(url)  # startup upgrade is repeatable


def test_existing_sqlite_versions_backfill_domain_identity_columns(tmp_path):
    from sqlalchemy import create_engine, text
    from app.db.models import create_session_factory
    url = f"sqlite:///{tmp_path / 'versioned-legacy.db'}"
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, current_revision INTEGER)"))
        db.execute(text("CREATE TABLE workflow_revisions (id INTEGER PRIMARY KEY, task_id INTEGER, revision INTEGER, definition_json TEXT)"))
        db.execute(text("CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id INTEGER, workflow_revision INTEGER, snapshot_json TEXT, status TEXT)"))
        db.execute(text("INSERT INTO tasks (id, current_revision) VALUES (10, 2)"))
        db.execute(text("INSERT INTO workflow_revisions (id, task_id, revision, definition_json) VALUES (20, 10, 2, '{}')"))
        db.execute(text("INSERT INTO task_runs (id, task_id, workflow_revision, snapshot_json, status) VALUES (30, 10, 2, '{}', 'completed')"))
    factory = create_session_factory(url)
    with factory() as db:
        task = db.execute(text('SELECT current_revision_id FROM tasks WHERE id = 10')).one()
        run = db.execute(text('SELECT workflow_revision_id FROM task_runs WHERE id = 30')).one()
        assert task == (20,)
        assert run == (20,)


def test_template_export_cannot_append_into_another_workspace_or_owner(client, app):
    from app.db.models import TaskTemplate, TemplateVersion
    login(client)
    task = client.post('/api/hexa/tasks', json={'title': '私有任务'}).json()
    with app.state.session_factory() as db:
        other = TaskTemplate(user_id=999, workspace_id=None, title='其他用户')
        other_space = TaskTemplate(user_id=1, workspace_id=999, title='其他工作区')
        db.add_all([other, other_space]); db.flush()
        ids = [other.id, other_space.id]
        for template_id in ids:
            db.add(TemplateVersion(template_id=template_id, version=1, definition_json='{"nodes":[]}'))
        db.commit()
    for template_id in ids:
        response = client.post(f"/api/hexa/tasks/{task['id']}/save-as-template", json={'workflow_revision': 1, 'template_id': template_id})
        assert response.status_code == 404


def test_run_executes_independent_nodes_and_persists_node_runs(client, app):
    login(client)
    created = client.post(
        "/api/hexa/tasks",
        json={
            "title": "并行执行",
            "workflow": {
                "nodes": [
                    {"id": "a", "agent_id": "agent-1", "model": "gpt-6.1"},
                    {"id": "b", "agent_id": "agent-1", "model": "gpt-6.1"},
                    {"id": "report", "agent_id": "agent-1", "model": "gpt-6.1", "deps": ["a", "b"], "inputRefs": ["a", "b"], "final_report": True},
                ]
            },
        },
    )
    task_id = created.json()["id"]
    started = client.post(f"/api/hexa/tasks/{task_id}/runs", headers={"Idempotency-Key": "parallel-1"})
    assert started.status_code == 202
    run_id = started.json()["id"]

    import asyncio
    for _ in range(20):
        with app.state.session_factory() as db:
            from app.db.models import Run
            if db.get(Run, run_id).status == "completed":
                break
        asyncio.run(asyncio.sleep(0.01))

    result = client.get(f"/api/hexa/runs/{run_id}")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    assert [node["node_id"] for node in result.json()["nodes"]] == ["a", "b", "report"]
    assert all(node["status"] == "succeeded" for node in result.json()["nodes"])


def test_waiting_human_run_continues_with_selected_input(client, app):
    login(client)
    created = client.post(
        "/api/hexa/tasks",
        json={
            "title": "人工选择",
            "workflow": {
                "nodes": [
                    {"id": "a", "agent_id": "agent-1", "model": "gpt-6.1"},
                    {"id": "b", "agent_id": "agent-1", "model": "gpt-6.1"},
                    {"id": "summary", "agent_id": "agent-1", "model": "gpt-6.1", "deps": ["a", "b"], "inputRefs": ["a"], "requires_human": True, "final_report": True},
                ]
            },
        },
    )
    task_id = created.json()["id"]
    run = client.post(f"/api/hexa/tasks/{task_id}/runs", headers={"Idempotency-Key": "human-1"}).json()
    run_id = run["id"]

    import asyncio
    for _ in range(20):
        current = client.get(f"/api/hexa/runs/{run_id}").json()
        if current["status"] == "waiting_human":
            break
        asyncio.run(asyncio.sleep(0.01))
    assert current["status"] == "waiting_human"

    continued = client.post(f"/api/hexa/runs/{run_id}/continue", headers={"Idempotency-Key": "human-choice"}, json={"node_id": "summary", "input_refs": ["a"]})
    assert continued.status_code == 200
    assert continued.json()["status"] == "running"


@pytest.mark.parametrize('node_type', ['human', 'human_gate'])
def test_explicit_human_node_waits_before_execution_and_continues_after_choice(client, app, node_type):
    login(client)
    created = client.post(
        "/api/hexa/tasks",
        json={
            "title": "人工节点不会自动执行",
            "workflow": {
                "nodes": [
                    {"id": "a", "agent_id": "agent-1", "model": "gpt-6.1"},
                    {"id": "review", "node_type": node_type, "requires_human": False, "deps": ["a"]},
                    {"id": "report", "agent_id": "agent-1", "model": "gpt-6.1", "deps": ["review"], "inputRefs": ["review"], "final_report": True},
                ]
            },
        },
    )
    task_id = created.json()["id"]
    run = client.post(f"/api/hexa/tasks/{task_id}/runs", headers={"Idempotency-Key": "human-node-1"}).json()
    run_id = run["id"]

    import asyncio
    for _ in range(30):
        current = client.get(f"/api/hexa/runs/{run_id}").json()
        if current["status"] == "waiting_human":
            break
        asyncio.run(asyncio.sleep(0.01))
    assert current["status"] == "waiting_human"
    review = next(node for node in current["nodes"] if node["node_id"] == "review")
    assert review["status"] == "idle"
    assert review["output"] is None
    assert next(node for node in current["nodes"] if node["node_id"] == "report")["status"] == "idle"
    assert current["decisions"] == []
    assert client.get(f"/api/hexa/tasks/{task_id}").json()["status"] == "waiting"
    assert len(app.state.gateway.calls) == 1

    for index, refs in enumerate([[], ['missing'], ['a', 'a']]):
        invalid = client.post(
            f"/api/hexa/runs/{run_id}/continue",
            headers={"Idempotency-Key": f"invalid-human-choice-{index}"},
            json={"node_id": "review", "input_refs": refs},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "invalid_decision"
        unchanged = client.get(f"/api/hexa/runs/{run_id}").json()
        assert unchanged["status"] == "waiting_human"
        assert unchanged["decisions"] == []
        assert len(app.state.gateway.calls) == 1

    continued = client.post(
        f"/api/hexa/runs/{run_id}/continue",
        headers={"Idempotency-Key": "human-node-choice"},
        json={"node_id": "review", "input_refs": ["a"]},
    )
    assert continued.status_code == 200
    for _ in range(30):
        completed = client.get(f"/api/hexa/runs/{run_id}").json()
        if completed["status"] == "completed":
            break
        asyncio.run(asyncio.sleep(0.01))
    assert completed["status"] == "completed"
    review = next(node for node in completed["nodes"] if node["node_id"] == "review")
    assert review["status"] == "succeeded"
    assert review["response_id"] is None
    assert [ref["node_id"] for ref in review["input"]["refs"]] == ["a"]
    assert review["output"]["selected_input_refs"] == ["a"]
    report = next(node for node in completed["nodes"] if node["node_id"] == "report")
    assert report["status"] == "succeeded"
    assert [ref["node_id"] for ref in report["input"]["refs"]] == ["review"]
    assert completed["decisions"] == [{"node_id": "review", "input_refs": ["a"]}]
    assert client.get(f"/api/hexa/tasks/{task_id}").json()["status"] == "completed"
    assert len(client.get(f"/api/hexa/tasks/{task_id}/runs").json()["runs"]) == 1
    replay = client.post(
        f"/api/hexa/runs/{run_id}/continue",
        headers={"Idempotency-Key": "human-node-choice"},
        json={"node_id": "review", "input_refs": ["a"]},
    )
    assert replay.status_code == 200
    assert client.get(f"/api/hexa/runs/{run_id}").json()["decisions"] == completed["decisions"]
    assert len(app.state.gateway.calls) == 2
