from __future__ import annotations


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
