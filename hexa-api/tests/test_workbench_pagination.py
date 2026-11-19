import json

from app.db.models import Run, Task, TaskTemplate, TemplateVersion
from .test_tasks_api import login


def test_workbench_search_filters_before_paging_and_runs_are_workspace_scoped(client, app):
    login(client)
    first = client.post('/api/hexa/workspaces', json={'name': 'pagination-first'}).json()['id']
    second = client.post('/api/hexa/workspaces', json={'name': 'pagination-second'}).json()['id']
    with app.state.session_factory() as db:
        tasks = [Task(user_id=1, workspace_id=first, title=f'分页任务 {i}', status='failed' if i == 0 else 'draft') for i in range(25)]
        hidden = Task(user_id=1, workspace_id=second, title='分页任务 hidden', status='failed')
        foreign = Task(user_id=999, workspace_id=first, title='分页任务 foreign', status='failed')
        db.add_all([*tasks, hidden, foreign]); db.flush()
        runs = [Run(task_id=t.id, workflow_revision=1, status='failed', snapshot_json=json.dumps({'workflow': {'nodes': []}})) for t in [tasks[0], hidden, foreign]]
        db.add_all(runs); db.commit()
        ids = [r.id for r in runs]
    client.post('/api/hexa/workspaces/select', json={'workspace_id': first})
    page = client.get(f'/api/hexa/tasks?workspace_id={first}&limit=2&status=failed&q=分页任务').json()
    assert [row['title'] for row in page['tasks']] == ['分页任务 0']
    assert page['pagination']['has_more'] is False
    all_runs = client.get('/api/hexa/runs?limit=1&status=failed&q=分页任务')
    assert all_runs.status_code == 200
    assert [row['id'] for row in all_runs.json()['runs']] == ids[:1]
    assert all_runs.json()['pagination']['has_more'] is False
    assert client.get('/api/hexa/runs?offset=1&limit=1').json()['runs'] == []
    assert client.get('/api/hexa/runs?q=missing').json()['runs'] == []
    assert client.get('/api/hexa/runs?status=completed').json()['runs'] == []
    assert client.get('/api/hexa/runs').json()['runs'][0]['task_title'] == '分页任务 0'


def test_template_latest_is_independent_of_history_page_and_search_is_literal(client, app):
    login(client)
    with app.state.session_factory() as db:
        row = TaskTemplate(user_id=1, title='模板 100%')
        other = TaskTemplate(user_id=1, title='模板 other')
        db.add_all([row, other]); db.flush()
        for i in range(1, 104):
            db.add(TemplateVersion(template_id=row.id, version=i, definition_json=json.dumps({'nodes': [{'id': f'node-{i}'}]})))
        db.commit(); template_id = row.id
    result = client.get(f'/api/hexa/templates/{template_id}?versions_limit=2').json()
    assert [v['version'] for v in result['versions']] == [1, 2]
    assert result['versions_pagination'] == {'offset': 0, 'limit': 2, 'has_more': True}
    assert result['latest_version']['version'] == 103
    assert result['latest_version']['workflow']['nodes'][0]['id'] == 'node-103'
    page = client.get('/api/hexa/templates?q=%25&limit=1').json()
    assert [r['id'] for r in page['templates']] == [template_id]
    assert page['pagination']['has_more'] is False
    last = client.get(f'/api/hexa/templates/{template_id}?versions_offset=102&versions_limit=2').json()
    assert [v['version'] for v in last['versions']] == [103]
    assert last['versions_pagination']['has_more'] is False


def test_debug_artifact_preview_is_bounded_and_node_artifacts_page_separately(client, app):
    from app.db.models import Artifact, NodeRun
    login(client)
    task = client.post('/api/hexa/tasks', json={'title': 'bounded debug'}).json()
    with app.state.session_factory() as db:
        run = Run(task_id=task['id'], workflow_revision=1, status='failed', snapshot_json='{"workflow":{"nodes":[]}}')
        db.add(run); db.flush()
        node = NodeRun(run_id=run.id, node_id='report', attempt=1, status='failed')
        db.add(node); db.flush()
        db.add_all([Artifact(user_id=1, task_id=task['id'], run_id=run.id, node_run_id=node.id,
                            gateway_file_id=f'file-{i}', gateway_container_id='container',
                            filename=f'report-{i}.txt', media_type='text/plain', bytes=1) for i in range(55)])
        db.commit(); node_id = node.id
    debug = client.get(f'/api/hexa/node-runs/{node_id}?limit=1').json()
    assert len(debug['artifacts']) == 50
    assert debug['artifacts_pagination'] == {'offset': 0, 'limit': 50, 'has_more': True}
    first = client.get(f'/api/hexa/node-runs/{node_id}/artifacts?limit=50').json()
    last = client.get(f'/api/hexa/node-runs/{node_id}/artifacts?offset=50&limit=50').json()
    assert len(first['artifacts']) == 50
    assert len(last['artifacts']) == 5
    assert last['pagination']['has_more'] is False
    assert set(row['id'] for row in first['artifacts']).isdisjoint(row['id'] for row in last['artifacts'])
