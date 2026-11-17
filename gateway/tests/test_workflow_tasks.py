from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gateway


def _snapshot(*, deps: list[str] | None = None) -> dict:
    return {
        "template_id": "tpl-product",
        "template_version": 3,
        "title": "产品评估",
        "description": "固定模板快照",
        "nodes": [
            {"id": "market", "name": "市场分析", "agent_id": "chrn_market",
             "agent_name": "市场 Agent", "deps": [], "retry_limit": 2},
            {"id": "summary", "name": "总结", "agent_id": "chrn_summary",
             "agent_name": "总结 Agent", "deps": deps if deps is not None else ["market"],
             "retry_limit": 1},
        ],
    }


def test_workflow_task_persists_snapshot_and_updates_status(monkeypatch):
    org = "org.workflow." + uuid.uuid4().hex

    async def principal(_request):
        return {"org": org, "member": "workflow@example.invalid", "workspace": ""}

    monkeypatch.setattr(gateway, "_principal", principal)
    with TestClient(gateway.app) as client:
        created = client.post("/v1/workflow-tasks", json={
            "title": "一次评估", "input": "分析产品", "snapshot": _snapshot()
        })
        assert created.status_code == 200, created.text
        task = created.json()
        assert task["object"] == "workflow.task"
        assert task["snapshot"]["template_version"] == 3
        task_id = task["id"]

        listed = client.get("/v1/workflow-tasks")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["tasks"]] == [task_id]

        updated_snapshot = _snapshot()
        updated_snapshot["nodes"][0].update({"status": "done", "attempts": 1, "output": "市场结论"})
        updated = client.patch(f"/v1/workflow-tasks/{task_id}", json={
            "status": "running", "snapshot": updated_snapshot
        })
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "running"
        assert updated.json()["snapshot"]["nodes"][0]["output"] == "市场结论"

        fetched = client.get(f"/v1/workflow-tasks/{task_id}")
        assert fetched.status_code == 200
        assert fetched.json()["updated_at"] >= task["updated_at"]


def test_workflow_task_rejects_cycles(monkeypatch):
    org = "org.workflow.cycle." + uuid.uuid4().hex

    async def principal(_request):
        return {"org": org, "member": "workflow@example.invalid", "workspace": ""}

    monkeypatch.setattr(gateway, "_principal", principal)
    body = _snapshot()
    body["nodes"][0]["deps"] = ["summary"]
    with TestClient(gateway.app) as client:
        response = client.post("/v1/workflow-tasks", json={
            "title": "循环", "input": "", "snapshot": body
        })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "workflow_invalid"


def test_workflow_task_is_org_scoped(monkeypatch):
    owner = "org.workflow.owner." + uuid.uuid4().hex
    other = "org.workflow.other." + uuid.uuid4().hex
    current = {"org": owner, "member": "owner@example.invalid", "workspace": ""}

    async def principal(_request):
        return current

    monkeypatch.setattr(gateway, "_principal", principal)
    with TestClient(gateway.app) as client:
        created = client.post("/v1/workflow-tasks", json={
            "title": "私有", "snapshot": _snapshot()
        })
        assert created.status_code == 200
        task_id = created.json()["id"]
        current = {"org": other, "member": "other@example.invalid", "workspace": ""}
        assert client.get(f"/v1/workflow-tasks/{task_id}").status_code == 404
        assert client.get("/v1/workflow-tasks").json()["tasks"] == []


def test_workflow_task_idempotency_replays_first_task(monkeypatch):
    org = "org.workflow.idem." + uuid.uuid4().hex

    async def principal(_request):
        return {"org": org, "member": "workflow@example.invalid", "workspace": ""}

    monkeypatch.setattr(gateway, "_principal", principal)
    headers = {"Idempotency-Key": "same-workflow-request"}
    with TestClient(gateway.app) as client:
        first = client.post("/v1/workflow-tasks", headers=headers, json={
            "title": "幂等任务", "input": "a", "snapshot": _snapshot()
        })
        second = client.post("/v1/workflow-tasks", headers=headers, json={
            "title": "幂等任务", "input": "a", "snapshot": _snapshot()
        })
        changed = client.post("/v1/workflow-tasks", headers=headers, json={
            "title": "不同请求", "input": "b", "snapshot": _snapshot()
        })
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert changed.status_code == 409


def test_workflow_run_executes_ready_nodes_and_persists_results(monkeypatch):
    org = "org.workflow.run." + uuid.uuid4().hex
    calls: list[str] = []

    async def principal(_request):
        return {"org": org, "member": "workflow@example.invalid", "workspace": ""}

    async def fake_call(_headers, node, prompt):
        calls.append(node["name"])
        return f"output:{node['name']}", f"resp_{node['id']}"

    monkeypatch.setattr(gateway, "_principal", principal)
    monkeypatch.setattr(gateway, "_workflow_call_response", fake_call)
    body = _snapshot()
    body["nodes"].append({"id": "final", "name": "最终", "agent_id": "",
                          "agent_name": "默认 Agent", "deps": ["summary"], "retry_limit": 0})
    with TestClient(gateway.app) as client:
        created = client.post("/v1/workflow-tasks", json={
            "title": "运行任务", "input": "执行", "snapshot": body
        })
        assert created.status_code == 200
        task_id = created.json()["id"]
        accepted = client.post(f"/v1/workflow-tasks/{task_id}/run")
        assert accepted.status_code == 202
        running = gateway._WORKFLOW_RUNS.pop(task_id, None)
        if running:
            running.cancel()
        asyncio.run(gateway._workflow_execute(task_id, {}))
        result = client.get(f"/v1/workflow-tasks/{task_id}").json()
    assert result["status"] == "completed"
    assert set(calls[:2]) == {"市场分析", "总结"} or set(calls[:2]) == {"市场分析", "总结"}
    assert calls[-1] == "最终"
    assert all(node["status"] == "done" for node in result["snapshot"]["nodes"])


def test_workflow_recovery_restarts_durable_running_task(monkeypatch):
    org = "org.workflow.recovery." + uuid.uuid4().hex
    task_id = "wtask_recover_" + uuid.uuid4().hex
    calls: list[str] = []

    async def fake_call(_headers, node, _prompt):
        calls.append(node["name"])
        return "recovered output", "resp_recovered"

    monkeypatch.setattr(gateway, "_workflow_call_response", fake_call)

    async def go():
        snapshot = _snapshot()
        props = {"org": org, "workspace": "", "member": "recovered@example.invalid",
                 "title": "恢复任务", "input": "继续执行", "status": "running",
                 "created_at": gateway._now_ms(), "updated_at": gateway._now_ms(),
                 "snapshot": gateway.json.dumps(snapshot, ensure_ascii=False)}
        await gateway._vg_upsert("WorkflowTask", task_id, props, raise_on_fail=True)
        assert await gateway._workflow_recover() == 1
        running = gateway._WORKFLOW_RUNS.get(task_id)
        assert running is not None
        await running
        row = await gateway._vertex_get(task_id)
        return row

    row = asyncio.run(go())
    assert row["status"] == "completed"
    assert calls == ["市场分析", "总结"]
    assert task_id not in gateway._WORKFLOW_RUNS


def test_workflow_recovery_requeues_interrupted_running_nodes(monkeypatch):
    org = "org.workflow.recovery.running." + uuid.uuid4().hex
    task_id = "wtask_recover_running_" + uuid.uuid4().hex
    calls: list[str] = []

    async def fake_call(_headers, node, _prompt):
        calls.append(node["name"])
        return "replayed output", f"resp_{node['id']}"

    monkeypatch.setattr(gateway, "_workflow_call_response", fake_call)

    async def go():
        snapshot = _snapshot()
        snapshot["nodes"][0].update({"status": "running", "attempts": 1})
        props = {"org": org, "workspace": "", "member": "recovered@example.invalid",
                 "title": "恢复中断节点", "input": "重试中断节点", "status": "running",
                 "created_at": gateway._now_ms(), "updated_at": gateway._now_ms(),
                 "snapshot": gateway.json.dumps(snapshot, ensure_ascii=False)}
        await gateway._vg_upsert("WorkflowTask", task_id, props, raise_on_fail=True)
        assert await gateway._workflow_recover() == 1
        running = gateway._WORKFLOW_RUNS.get(task_id)
        assert running is not None
        await running
        return await gateway._vertex_get(task_id)

    row = asyncio.run(go())
    assert row["status"] == "completed"
    assert calls == ["市场分析", "总结"]
    assert all(node["status"] == "done" for node in gateway._json_obj(row["snapshot"])["nodes"])


def test_workflow_run_does_not_steal_live_lease(monkeypatch):
    org = "org.workflow.lease." + uuid.uuid4().hex
    task_id = "wtask_lease_" + uuid.uuid4().hex
    called = False

    async def admit(*_args, **_kwargs):
        return {"fence": 0, "conflict": True, "rejected": True, "holder": "other-worker"}

    async def fake_call(*_args, **_kwargs):
        nonlocal called
        called = True
        return "must not run", "resp_never"

    async def go():
        snapshot = _snapshot()
        await gateway._vg_upsert("WorkflowTask", task_id, {
            "org": org, "workspace": "", "member": "lease@example.invalid", "title": "租约",
            "input": "不要抢占", "status": "running", "created_at": gateway._now_ms(),
            "updated_at": gateway._now_ms(), "snapshot": gateway.json.dumps(snapshot, ensure_ascii=False)},
            raise_on_fail=True)
        monkeypatch.setattr(gateway.control_store, "enabled", lambda: True)
        monkeypatch.setattr(gateway.control_store, "lease_admit", admit)
        monkeypatch.setattr(gateway, "_workflow_call_response", fake_call)
        await gateway._workflow_execute(task_id, {})
        return await gateway._vertex_get(task_id)

    row = asyncio.run(go())
    assert called is False
    assert row["status"] == "running"


def test_workflow_is_advertised_in_discovery_and_public_openapi():
    discovery = TestClient(gateway.app).get("/v1/uhp")
    assert discovery.status_code == 200
    assert discovery.json()["capabilities"]["workflow_tasks"] is True
    schema = TestClient(gateway.app).get("/v1/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/v1/workflow-tasks" in paths
    assert "/v1/workflow-tasks/{task_id}/run" in paths


@pytest.mark.parametrize("response_shape", ["dict", "json_response"])
def test_workflow_run_preserves_service_identity_and_response_output(monkeypatch, response_shape):
    org = "org.workflow.service." + uuid.uuid4().hex
    callers = []

    async def response(body, request):
        principal = await gateway._principal(request)
        callers.append(principal)
        payload = {"id": "resp_workflow_service", "status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "service output"}]}]}
        return payload if response_shape == "dict" else gateway.JSONResponse(payload)

    monkeypatch.setattr(gateway, "create_response", response)

    async def go():
        headers = {"x-harness-internal": gateway.INTERNAL_KEY, "x-harness-org": org,
                   "x-harness-member": "service@example.invalid", "x-harness-workspace": "service-ws"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(gateway.app), base_url="http://gateway") as client:
            created = await client.post("/v1/workflow-tasks", headers=headers, json={
                "title": "服务调用", "snapshot": _snapshot()})
            assert created.status_code == 200, created.text
            task_id = created.json()["id"]
            started = await client.post(f"/v1/workflow-tasks/{task_id}/run", headers=headers)
            assert started.status_code == 202, started.text
            running = gateway._WORKFLOW_RUNS.get(task_id)
            if running:
                await running
            return (await client.get(f"/v1/workflow-tasks/{task_id}", headers=headers)).json()

    task = asyncio.run(go())
    assert task["status"] == "completed", task
    assert len(callers) == 2
    assert all(p["org"] == org and p["workspace"] == "service-ws" for p in callers)
    assert all(node["output"] == "service output" and node["response_id"] == "resp_workflow_service"
               for node in task["snapshot"]["nodes"])
