"""Gateway branching contract on real local storage; only runner/model boundaries are fixtures.

The real-Git/runner tests separately prove that a selected tree, not the latest, is restored.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw


@pytest.fixture
def env(monkeypatch):
    suffix = uuid.uuid4().hex
    org, sid, hid = "org.branch." + suffix, "hsess" + suffix, "chrn_" + suffix
    calls = []

    async def principal(_):
        return {"org": org, "member": "fixture@example.invalid"}

    async def chain(*_, **__):
        return ["fixture"]

    async def execute(tr, **kwargs):
        calls.append(kwargs)
        tr.output.append({"id": "msg_branch", "type": "message", "status": "completed", "role": "assistant",
                          "content": [{"type": "output_text", "text": "branched", "annotations": []}]})
        return "completed", [], {"status": "done"}

    async def hydrate(target, params, *, source_sid=None):
        calls.append({"restore_target": target, "source": source_sid, "params": params})
        return httpx.Response(200, json={"ok": True})

    async def checkpoint(_):
        return True, 100, "target-sha", "a" * 7, "a" * 40

    async def none(*_, **__):
        return None

    monkeypatch.setattr(gw, "_mapped_integration_conn", none)
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    monkeypatch.setattr(gw, "_resp_execute", execute)
    monkeypatch.setattr(gw, "_hydrate_relay", hydrate)
    monkeypatch.setattr(gw, "_checkpoint_relay", checkpoint)

    async def seed():
        await gw.BACKING.graph.upsert("Harness", hid, {"org": org, "member": "fixture@example.invalid",
                                                    "workspace": "", "name": hid, "base": "claude-code",
                                                    "custom": "1", "deleted": "0"})
        await gw._vertex_upsert(sid, {"tenant": org, "status": "done", "harness_id": hid,
                                     "ws_sha": "source-sha", "workspace": "", "backend": "claude"})
        ids = []
        for i in range(3):
            rid = "resp_" + suffix + str(i)
            ids.append(rid)
            record = {"id": rid, "status": "completed", "_session_id": sid, "_org": org,
                      "_input": [{"role": "user", "content": [{"type": "input_text", "text": f"user-{i}"}]}],
                      "output": [{"id": f"msg_{i}", "type": "message", "status": "completed", "role": "assistant",
                                  "content": [{"type": "output_text", "text": f"assistant-{i}", "annotations": []}]}],
                      "metadata": {"session_id": sid}, "model": "claude", "usage": {"input_tokens": 100}}
            if i == 0:
                record["_pending_input"] = {"id": "question", "state": "pending"}
            await gw._resp_put(rid, record, org, sid, ids[i-1] if i else None, "completed", 1000.0 + i, True)
        await gw._blob_put(f"responses/{ids[0]}.branch.json", json.dumps({
            "response_id": ids[0], "session_id": sid, "commit": "1" * 40, "ws_sha": "old-sha", "turn_index": 0
        }).encode(), kb=gw.RESP_BLOB_KB)
        await gw._blob_put(f"sessions/{sid}/branch-head.json", json.dumps({
            "commit": "3" * 40, "ws_sha": "source-sha"
        }).encode(), kb=gw.RESP_BLOB_KB)
        return ids

    ids = asyncio.run(seed())
    return {"client": TestClient(gw.app), "org": org, "sid": sid, "hid": hid, "ids": ids, "calls": calls}


def post(env, **extra):
    return env["client"].post("/v1/responses", json={"input": "different approach", "branch": True,
        "previous_response_id": env["ids"][0], "metadata": {"harness_id": env["hid"]}, **extra})


def test_new_session_has_only_history_to_selected_response_and_preserves_original(env):
    original = asyncio.run(gw._vertex_get(env["sid"]))
    response = post(env)
    assert response.status_code == 200, response.text
    body = response.json()
    target = body["metadata"]["session_id"]
    assert target != env["sid"], "branch must create a new session"
    assert body["metadata"]["branched_from"] == env["ids"][0]
    assert asyncio.run(gw._vertex_get(env["sid"])) == original
    source = asyncio.run(gw._resp_get(env["ids"][0]))
    assert source["_pending_input"]["state"] == "pending"
    target_turns = env["client"].get(f"/v1/sessions/{target}/turns").json()["turns"]
    assert len(target_turns) == 2
    assert target_turns[0]["user"] == "user-0"
    assert target_turns[0]["assistant"] == "assistant-0"
    assert target_turns[0]["imported"] is True and target_turns[0]["cost_usd"] == 0
    assert target_turns[0]["id"] not in env["ids"]
    detail = env["client"].get(f"/v1/sessions/{target}").json()
    assert detail["branched_from"] == {"response_id": env["ids"][0], "session_id": env["sid"]}
    reread = env["client"].get(f"/v1/responses/{body['id']}").json()
    assert reread["metadata"]["branched_from"] == env["ids"][0]


@pytest.mark.parametrize("change", ["mapping", "running", "invalid-head"])
def test_unavailable_checkpoint_is_http409_before_any_target_work(env, change):
    async def alter():
        if change == "mapping":
            await gw._blob_delete(f"responses/{env['ids'][0]}.branch.json", kb=gw.RESP_BLOB_KB)
        elif change == "running":
            record = await gw._resp_get(env["ids"][0])
            record["status"] = "in_progress"
            await gw._resp_put(env["ids"][0], record, env["org"], env["sid"], None, "in_progress", 1000, True)
        else:
            await gw._blob_put(f"sessions/{env['sid']}/branch-head.json", json.dumps({"commit": "invalid"}).encode(), kb=gw.RESP_BLOB_KB)
    asyncio.run(alter())
    for mode in ({}, {"stream": True}, {"background": True}):
        response = post(env, **mode)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "branch_unavailable"
    assert not env["calls"]


def test_harness_scope_is_checked_before_checkpoint_availability(env):
    response = post(env, metadata={"harness_id": "another-harness"})
    assert response.status_code == 404
    assert not env["calls"]


def test_branch_does_not_claim_an_answer_to_original_question(env):
    response = post(env, input=[{"type": "input_response", "input_request_id": "question", "answer": "value"}])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "input_not_pending"
    assert not env["calls"]


@pytest.mark.parametrize("value", ["yes", 1, [], {}, None])
def test_nonboolean_branch_is_ignored_not_coerced_or_rejected(value):
    body = gw.CreateResponseBody(input="hello", branch=value, previous_response_id="resp_before")
    assert body.branch is not True
    assert "branch" in gw._ignored_request_fields(body)


def test_false_and_absent_branch_preserve_existing_idempotency_hash():
    before = gw.CreateResponseBody(input="hello", previous_response_id="resp_before")
    false = gw.CreateResponseBody(input="hello", branch=False, previous_response_id="resp_before")
    true = gw.CreateResponseBody(input="hello", branch=True, previous_response_id="resp_before")
    assert gw._req_hash(before) == gw._req_hash(false)
    assert gw._req_hash(before) != gw._req_hash(true)
    assert "branch" in gw._ignored_request_fields(gw.CreateResponseBody(input="hello", branch=True))


def test_missing_full_commit_from_old_runner_writes_no_checkpoint_mapping(env, monkeypatch):
    async def checkpoint(_):
        return True, 100, "source-sha", "1234567", ""
    monkeypatch.setattr(gw, "_checkpoint_relay", checkpoint)
    asyncio.run(gw._blob_delete(f"responses/{env['ids'][0]}.branch.json", kb=gw.RESP_BLOB_KB))
    asyncio.run(gw._checkpoint(env["sid"], {}, response_id=env["ids"][0]))
    assert asyncio.run(gw._blob_get(f"responses/{env['ids'][0]}.branch.json", kb=gw.RESP_BLOB_KB)) is None


def test_app_checkpoint_rewrite_does_not_hide_a_valid_git_point(env):
    asyncio.run(gw._vertex_upsert(env["sid"], {"ws_sha": "app-reprojected-sha"}))
    response = post(env)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["session_id"] != env["sid"]


def test_mapping_failure_does_not_poison_an_acknowledged_checkpoint(env, monkeypatch):
    original_put = gw._blob_put

    async def broken_mapping(key, data, **kwargs):
        if key.endswith(".branch.json"):
            raise OSError("synthetic metadata outage")
        return await original_put(key, data, **kwargs)

    monkeypatch.setattr(gw, "_blob_put", broken_mapping)
    record = {}
    asyncio.run(gw._checkpoint(env["sid"], record, response_id=env["ids"][0]))
    assert record["checkpointed"] is True
    assert "checkpoint_error" not in record
    assert record["branch_checkpoint_unavailable"] is True


def test_deleted_source_is_404_and_private_mapping_is_removed(env):
    response = env["client"].delete(f"/v1/responses/{env['ids'][0]}")
    assert response.status_code == 200, response.text
    assert asyncio.run(gw._blob_get(f"responses/{env['ids'][0]}.branch.json", kb=gw.RESP_BLOB_KB)) is None
    response = post(env)
    assert response.status_code == 404
    assert not env["calls"]


def test_other_org_cannot_probe_checkpoint_availability(env):
    with pytest.raises(gw.HTTPException) as caught:
        asyncio.run(gw._branch_source(env["ids"][0], "org.other", env["hid"], {"org": "org.other"}))
    assert caught.value.status_code == 404
    assert not env["calls"]


def test_runner_refusal_is_retryable_503_not_branch_unavailable(env, monkeypatch):
    attempts = []

    async def refuse(*args, **kwargs):
        attempts.append(args)
        return httpx.Response(429, json={"detail": "synthetic pool capacity"})

    monkeypatch.setattr(gw, "_hydrate_relay", refuse)
    monkeypatch.setattr(gw, "_HYDRATE_PAUSES", (0, None))
    response = post(env)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "server_error"
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_real_idempotency_replay_creates_one_target(env):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        body = {"input": "different approach", "branch": True, "previous_response_id": env["ids"][0],
                "metadata": {"harness_id": env["hid"]}}
        headers = {"Idempotency-Key": "branch-" + env["sid"]}
        first = await client.post("/v1/responses", json=body, headers=headers)
        second = await client.post("/v1/responses", json=body, headers=headers)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["metadata"] == second.json()["metadata"]
    assert len([x for x in env["calls"] if "restore_target" in x]) == 1
    sessions = await gw.BACKING.graph.find_strict("HarnessSession", {"tenant": env["org"]})
    assert len(sessions) == 2  # the original plus exactly one branch


@pytest.mark.asyncio
async def test_true_without_point_is_ignored_over_http(env):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        response = await client.post("/v1/responses", json={"input": "fresh task", "branch": True,
            "metadata": {"harness_id": env["hid"]}})
    assert response.status_code == 200, response.text
    assert "branch" in response.json()["metadata"]["ignored_fields"]
    assert response.json()["metadata"]["session_id"] != env["sid"]
    assert not any("restore_target" in item for item in env["calls"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "stream", "background", "store-false"])
async def test_each_mode_has_its_index_before_the_terminal_checkpoint(env, monkeypatch, mode):
    execute = gw._resp_execute

    async def with_checkpoint(tr, **kwargs):
        outcome = await execute(tr, **kwargs)
        record = {}
        await gw._checkpoint(kwargs["sid"], record, response_id=tr.resp_id)
        assert record["checkpointed"]
        return outcome

    monkeypatch.setattr(gw, "_resp_execute", with_checkpoint)
    options = {"stream": mode == "stream", "background": mode == "background", "store": mode != "store-false"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        response = await client.post("/v1/responses", json={"input": "new point", **options,
            "metadata": {"harness_id": env["hid"]}})
        assert response.status_code == 200, response.text
        if mode == "stream":
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            body = next(event["response"] for event in events if event["type"] == "response.completed")
        else:
            body = response.json()
        for _ in range(100):
            point = await gw._blob_get(f"responses/{body['id']}.branch.json", kb=gw.RESP_BLOB_KB)
            if point:
                break
            await asyncio.sleep(0.01)
        assert point is not None
        assert json.loads(point)["response_id"] == body["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stream", "background"])
async def test_stream_start_and_background_ack_identify_the_branch(env, mode):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        response = await client.post("/v1/responses", json={"input": "different approach", "branch": True,
            "previous_response_id": env["ids"][0], "metadata": {"harness_id": env["hid"]}, mode: True})
        assert response.status_code == 200, response.text
        if mode == "stream":
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            bodies = [event["response"] for event in events if "response" in event]
            assert any(event["type"] == "response.created" for event in events)
        else:
            bodies = [response.json()]
        for body in bodies:
            assert body["metadata"]["session_id"] != env["sid"]
            assert body["metadata"]["branched_from"] == env["ids"][0]
        # Allow the synthetic background execution to finish before closing this test's loop.
        for _ in range(100):
            stored = await gw._resp_get(bodies[-1]["id"])
            if stored and stored["status"] == "completed":
                break
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_partial_import_failure_removes_target_records_and_releases_idempotency(env, monkeypatch):
    real_import = gw._imported_turns_put

    async def partial(turns, **kwargs):
        await real_import(turns[:1], **kwargs)
        raise gw.uhp_error(503, "server_error", "synthetic partial import failure")

    async def checkpoint(target):
        await gw._blob_put(gw._ws_blob(target), b"synthetic target checkpoint")
        await gw._blob_put(f"containers/{target}/cfile_partial", b"synthetic copied artifact", kb=gw.RESP_BLOB_KB)
        await gw._blob_put(f"sessions/{target}/branch-head.json", b"{}", kb=gw.RESP_BLOB_KB)
        return True, 100, "target-sha", "a" * 7, "a" * 40

    monkeypatch.setattr(gw, "_imported_turns_put", partial)
    monkeypatch.setattr(gw, "_checkpoint_relay", checkpoint)
    key = "failure-" + env["sid"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        response = await client.post("/v1/responses", headers={"Idempotency-Key": key}, json={
            "input": "different approach", "branch": True, "previous_response_id": env["ids"][0],
            "metadata": {"harness_id": env["hid"]}})
    assert response.status_code == 503, response.text
    target = next(x["restore_target"] for x in env["calls"] if "restore_target" in x)
    assert await gw._vertex_get(target) is None
    assert await gw._blob_get(gw._ws_blob(target)) is None
    assert await gw._blob_get(f"containers/{target}/cfile_partial", kb=gw.RESP_BLOB_KB) is None
    assert await gw._blob_get(f"sessions/{target}/branch-head.json", kb=gw.RESP_BLOB_KB) is None
    assert not await gw.BACKING.graph.find_strict("HarnessResponse", {"session_id": target})
    assert await gw.control_store.idem_get(env["org"], gw._idem_sha(key)) is None


@pytest.mark.asyncio
async def test_imported_tools_redacted_input_and_artifacts_are_owned_by_target(env, monkeypatch):
    import io
    import tarfile
    record = await gw._resp_get(env["ids"][0])
    record["_input"].append({"type": "input_response", "input_request_id": "secret", "answer": "[redacted]"})
    record["output"].append({"id": "tool_original", "type": "function_call", "call_id": "tool_original",
                             "name": "work", "arguments": "{}"})
    annotations = [
        {"type": "container_file_citation", "container_id": env["sid"], "file_id": gw._wf_id("user.txt"), "filename": "user.txt"},
        {"type": "container_file_citation", "container_id": env["sid"], "file_id": "cfile_stored", "filename": "stored.txt"},
    ]
    record["output"][0]["content"][0]["annotations"] = annotations
    await gw._resp_put(env["ids"][0], record, env["org"], env["sid"], None, "completed", 1000, True)
    await gw._blob_put(f"containers/{env['sid']}/cfile_stored", b"stored-one", kb=gw.RESP_BLOB_KB)
    await gw._blob_put(f"containers/{env['sid']}/cfile_stored.meta", json.dumps({
        "filename": "stored.txt", "media_type": "text/plain", "written_at": 1000}).encode(), kb=gw.RESP_BLOB_KB)

    async def checkpoint(target):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            member = tarfile.TarInfo("./user.txt");member.size = 3
            archive.addfile(member, io.BytesIO(b"one"))
        await gw._blob_put(gw._ws_blob(target), stream.getvalue())
        return True, len(stream.getvalue()), "target-sha", "a" * 7, "a" * 40

    monkeypatch.setattr(gw, "_checkpoint_relay", checkpoint)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        response = await client.post("/v1/responses", json={"input": "different approach", "branch": True,
            "previous_response_id": env["ids"][0], "metadata": {"harness_id": env["hid"]}})
        assert response.status_code == 200, response.text
        target = response.json()["metadata"]["session_id"]
        turns = await gw._session_turns_data(target)
        copied = await gw._resp_get(turns["turns"][0]["id"])
        assert copied["_input"][-1]["answer"] == "[redacted]"
        assert copied["usage"] == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        assert any(item.get("type") == "function_call" for item in copied["output"])
        citations = copied["output"][0]["content"][0]["annotations"]
        for citation, expected in zip(citations, (b"one", b"stored-one")):
            assert citation["container_id"] == target
            actual = await client.get(f"/v1/containers/{target}/files/{citation['file_id']}/content")
            assert actual.status_code == 200 and actual.content == expected
        deleted = await client.delete(f"/v1/sessions/{env['sid']}")
        assert deleted.status_code == 200, deleted.text
        actual = await client.get(f"/v1/containers/{target}/files/{citations[1]['file_id']}/content")
        assert actual.status_code == 200 and actual.content == b"stored-one"


@pytest.mark.asyncio
async def test_orphan_adoption_maps_its_checkpoint_and_keeps_input_chain_and_origin(env, monkeypatch):
    rid = env["ids"][1]
    record = await gw._resp_get(rid)
    record.update(status="in_progress", created_at=1001, previous_response_id=env["ids"][0], _backend="claude")
    record["metadata"]["branched_from"] = "resp_ancestor"
    await gw._resp_put(rid, record, env["org"], env["sid"], env["ids"][0], "in_progress", 1001, True)
    vertex = {**(await gw._vertex_get(env["sid"])), "runner_turn_id": "fixture-turn",
              "running_response_id": rid, "trace_blob": f"{env['org']}/fixture/{env['sid']}", "model": "fixture"}
    await gw._vertex_upsert(env["sid"], vertex)
    events, polls = [], []

    async def runner(*args, **kwargs):
        polls.append(args)
        return {"done": len(polls) > 1, "status": "done", "events": [], "n_total": 0}

    async def lease(*args, **kwargs):
        return {"fence": 0}

    async def none(*args, **kwargs):
        return None

    async def produced(*args, **kwargs):
        return []

    async def output(*args, **kwargs):
        return record["output"]

    monkeypatch.setattr(gw, "POOL_ENDPOINT", "http://synthetic-runner.invalid")
    monkeypatch.setattr(gw, "RESP_POLL_S", 0)
    monkeypatch.setattr(gw, "_sandbox_json", runner)
    monkeypatch.setattr(gw.control_store, "lease_admit", lease)
    monkeypatch.setattr(gw, "_collect_produced", produced)
    monkeypatch.setattr(gw, "_browser_close", none)
    monkeypatch.setattr(gw, "_trace_finalize", none)
    monkeypatch.setattr(gw, "_replay_output_from_trace", output)
    monkeypatch.setattr(gw, "_bus_publish", lambda *args, **kwargs: events.append(args[-1]))
    assert await gw._adopt_orphan_turn(env["sid"], env["org"], vertex)
    stored = await gw._resp_get(rid)
    assert stored["_input"] == record["_input"]
    assert stored["previous_response_id"] == env["ids"][0]
    assert stored["metadata"]["branched_from"] == "resp_ancestor"
    assert stored["created_at"] == 1001
    point = json.loads(await gw._blob_get(f"responses/{rid}.branch.json", kb=gw.RESP_BLOB_KB))
    assert point["response_id"] == rid and point["turn_index"] == 1
    terminal = [event for event in events if event.get("type") == "response.completed"]
    assert terminal and terminal[0]["response"]["metadata"]["branched_from"] == "resp_ancestor"


def test_calibration_refusal_precedes_checkpoint_lookup(env, monkeypatch):
    calls = []

    async def principal(_):
        return {"org": env["org"], "calibration": {"inner": "other-harness"}}

    async def forbidden_lookup(*args, **kwargs):
        calls.append(args)
        raise AssertionError("refused credential must not probe branch state")

    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_branch_source", forbidden_lookup)
    response = post(env)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert not calls


def test_source_read_outage_is_retryable_not_a_500(env, monkeypatch):
    async def outage(*args, **kwargs):
        raise OSError("synthetic source read outage")

    monkeypatch.setattr(gw, "_resp_get", outage)
    response = post(env)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "server_error"


@pytest.mark.parametrize("index", [None, "0", True, -1])
def test_malformed_private_turn_index_is_unavailable_not_a_500(env, index):
    point = {"response_id": env["ids"][0], "session_id": env["sid"], "commit": "1" * 40,
             "ws_sha": "old-sha", "turn_index": index}
    asyncio.run(gw._blob_put(f"responses/{env['ids'][0]}.branch.json", json.dumps(point).encode(), kb=gw.RESP_BLOB_KB))
    response = post(env)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "branch_unavailable"


def test_deleted_earlier_response_is_not_reintroduced_by_branch(env):
    assert env["client"].delete(f"/v1/responses/{env['ids'][1]}").status_code == 200
    point = {"response_id": env["ids"][2], "session_id": env["sid"], "commit": "3" * 40,
             "ws_sha": "source-sha", "turn_index": 2}
    asyncio.run(gw._blob_put(f"responses/{env['ids'][2]}.branch.json", json.dumps(point).encode(), kb=gw.RESP_BLOB_KB))
    response = post(env, previous_response_id=env["ids"][2])
    assert response.status_code == 200, response.text
    turns = env["client"].get(f"/v1/sessions/{response.json()['metadata']['session_id']}/turns").json()["turns"]
    assert [turn["user"] for turn in turns if turn.get("imported")] == ["user-0", "user-2"]


@pytest.mark.parametrize("origin", ["{", "[]", '{"other": "value"}'])
def test_malformed_provenance_does_not_break_detail_or_continuation(env, origin):
    asyncio.run(gw._vertex_upsert(env["sid"], {"branched_from": origin}))
    assert env["client"].get(f"/v1/sessions/{env['sid']}").status_code == 200
    response = post(env, branch=False)
    assert response.status_code == 200, response.text
