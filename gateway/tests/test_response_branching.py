"""Gateway branching contract on real local storage; only runner/model boundaries are fixtures.

The real-Git/runner tests separately prove that a selected tree, not the latest, is restored.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time
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
        return httpx.Response(200, json={"ok": True, "restored": True, "branched": True})

    async def checkpoint(_, commit=True):
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
        await gw._blob_put(gw._branch_point_key(ids[0]), json.dumps({
            "response_id": ids[0], "session_id": sid, "commit": "1" * 40, "ws_sha": "old-sha"
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
    assert detail["branched_from"] == {"response_id": env["ids"][0], "session_id": env["sid"], "turn": 1}
    reread = env["client"].get(f"/v1/responses/{body['id']}").json()
    assert reread["metadata"]["branched_from"] == env["ids"][0]


def test_only_the_branching_response_names_its_origin(env):
    """A later turn in the branch is a continuation: no `branched_from` on it, while the branching
    response and the session's detail keep the origin (Sessions §1.1, §3)."""
    first = post(env)
    assert first.status_code == 200, first.text
    target, branched = first.json()["metadata"]["session_id"], first.json()["id"]
    later = env["client"].post("/v1/responses", json={"input": "go on", "previous_response_id": branched,
                                                       "metadata": {"harness_id": env["hid"]}})
    assert later.status_code == 200, later.text
    assert later.json()["metadata"]["session_id"] == target
    assert "branched_from" not in later.json()["metadata"]
    assert "branched_from" not in env["client"].get(f"/v1/responses/{later.json()['id']}").json()["metadata"]
    assert env["client"].get(f"/v1/responses/{branched}").json()["metadata"]["branched_from"] == env["ids"][0]
    detail = env["client"].get(f"/v1/sessions/{target}").json()
    assert detail["branched_from"] == {"response_id": env["ids"][0], "session_id": env["sid"], "turn": 1}


def test_the_turn_is_the_selected_responses_place_in_its_session(env):
    """Read when the branch is made, from the session's responses in order: the point stores none."""
    point = {"response_id": env["ids"][2], "session_id": env["sid"], "commit": "3" * 40,
             "ws_sha": "source-sha"}
    asyncio.run(gw._blob_put(gw._branch_point_key(env["ids"][2]), json.dumps(point).encode(), kb=gw.RESP_BLOB_KB))
    response = post(env, previous_response_id=env["ids"][2])
    assert response.status_code == 200, response.text
    detail = env["client"].get(f"/v1/sessions/{response.json()['metadata']['session_id']}").json()
    assert detail["branched_from"]["turn"] == 3


@pytest.mark.parametrize("change", ["mapping", "running", "invalid-commit"])
def test_unavailable_checkpoint_is_http409_before_any_target_work(env, change):
    async def alter():
        if change == "mapping":
            await gw._blob_delete(gw._branch_point_key(env["ids"][0]), kb=gw.RESP_BLOB_KB)
        elif change == "running":
            record = await gw._resp_get(env["ids"][0])
            record["status"] = "in_progress"
            await gw._resp_put(env["ids"][0], record, env["org"], env["sid"], None, "in_progress", 1000, True)
        else:
            # main: the `invalid-head` case, a stored copy of the session's latest commit that was
            # not a full commit. No such copy is kept now; the stored point is what is checked.
            await gw._blob_put(gw._branch_point_key(env["ids"][0]), json.dumps({
                "response_id": env["ids"][0], "session_id": env["sid"], "commit": "invalid"
            }).encode(), kb=gw.RESP_BLOB_KB)
    asyncio.run(alter())
    for mode in ({}, {"stream": True}, {"background": True}):
        response = post(env, **mode)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "branch_unavailable"
    assert not env["calls"]


def test_a_branch_sends_the_point_and_no_copy_of_the_sessions_latest_commit(env):
    """A copy of the latest commit beside the tarball fell out of step with it (a failed write, a
    branch racing a new turn's checkpoint) and made every point of the session 409. The runner
    checks the point against the checkpoint's own HEAD, so nothing like it is kept or sent."""
    response = post(env)
    assert response.status_code == 200, response.text
    restore = [c for c in env["calls"] if "restore_target" in c]
    assert restore and restore[0]["params"]["branch_commit"] == "1" * 40
    assert "branch_head" not in restore[0]["params"]


def test_a_branch_hands_the_runner_the_point_and_nothing_of_the_source_turn(env):
    """The restore is told which commit and which base, and nothing of the source's turns: no turn
    credential, no sealed value, no header. The branch's own turns get their own, as every turn does
    (a turn's credential is bound to its session). The files carry none either: the runner restores
    only the commit's tracked files, never `.harness` (runner/tests/test_response_branching.py)."""
    response = post(env)
    assert response.status_code == 200, response.text
    restore = [c for c in env["calls"] if "restore_target" in c]
    assert restore and set(restore[0]["params"]) == {"branch_commit", "branch_backend"}
    assert restore[0]["restore_target"] != restore[0]["source"]


def test_checkpoint_writes_only_the_point_and_reads_nothing_back(env, monkeypatch):
    """The turn's end used to read every response of the session and sort them, at every turn, to
    store the point's place; the place is read when a branch is made now."""
    async def no_read(*args, **kwargs):
        raise AssertionError("a turn's checkpoint read the session's responses")

    monkeypatch.setattr(gw.BACKING.graph, "find_strict", no_read)
    asyncio.run(gw._checkpoint(env["sid"], {}, response_id=env["ids"][1]))
    point = json.loads(asyncio.run(gw._blob_get(gw._branch_point_key(env["ids"][1]), kb=gw.RESP_BLOB_KB)))
    assert point == {"commit": "a" * 40, "ws_sha": "target-sha", "session_id": env["sid"],
                     "response_id": env["ids"][1], "backend": ""}


def test_the_point_has_its_own_prefix_not_the_response_records(env):
    assert gw._branch_point_key("resp_x") == "branch-points/resp_x.json"
    asyncio.run(gw._checkpoint(env["sid"], {}, response_id=env["ids"][1]))
    assert asyncio.run(gw._blob_get(f"responses/{env['ids'][1]}.branch.json", kb=gw.RESP_BLOB_KB)) is None
    listed = asyncio.run(gw._blob_list_all("responses/", kb=gw.RESP_BLOB_KB))
    assert not [it for it in listed if "branch" in str(it.get("file_id"))]


def test_a_mid_turn_checkpoint_never_saves_a_point(env):
    """A mid-turn checkpoint (#505) commits nothing, and its turn has not ended."""
    asyncio.run(gw._checkpoint(env["sid"], {}, mid_turn=True, response_id=env["ids"][1]))
    assert asyncio.run(gw._blob_get(gw._branch_point_key(env["ids"][1]), kb=gw.RESP_BLOB_KB)) is None
    asyncio.run(gw._checkpoint(env["sid"], {}, response_id=env["ids"][1]))
    assert asyncio.run(gw._blob_get(gw._branch_point_key(env["ids"][1]), kb=gw.RESP_BLOB_KB)) is not None


def test_discovery_reports_branching_as_a_capability(env):
    """Optional at every class (VERSIONING): a client reads it before sending `branch: true`, and
    the conformance suite holds only a server that reports it to B-01..B-06."""
    assert gw.UHP_CAPABILITIES["session_branching"] is True
    assert env["client"].get("/v1/uhp").json()["capabilities"]["session_branching"] is True


def test_harness_scope_is_checked_before_checkpoint_availability(env):
    response = post(env, metadata={"harness_id": "another-harness"})
    assert response.status_code == 404
    assert not env["calls"]


def test_branch_does_not_claim_an_answer_to_original_question(env):
    response = post(env, input=[{"type": "input_response", "input_request_id": "question", "answer": "value"}])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_input"
    assert response.json()["error"]["param"] == "branch"
    assert not env["calls"]
    assert asyncio.run(gw._resp_get(env["ids"][0]))["_pending_input"]["state"] == "pending"


@pytest.mark.parametrize("value", ["yes", "true", 1, [], {}])
def test_nonboolean_branch_is_refused_not_coerced(env, value):
    """main: test_nonboolean_branch_is_ignored_not_coerced_or_rejected. Still never coerced to a
    branch; now refused rather than ignored, so the task never runs as something else."""
    sessions = asyncio.run(gw.BACKING.graph.find_strict("HarnessSession", {"tenant": env["org"]}))
    response = post(env, branch=value)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_input"
    assert response.json()["error"]["param"] == "branch"
    assert not env["calls"]
    assert asyncio.run(gw.BACKING.graph.find_strict("HarnessSession", {"tenant": env["org"]})) == sessions


def test_null_branch_is_the_same_as_absent(env):
    """main: the None case of test_nonboolean_branch_is_ignored_not_coerced_or_rejected."""
    response = post(env, branch=None)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["session_id"] == env["sid"]
    assert "branch" not in (response.json()["metadata"].get("ignored_fields") or [])
    assert not any("restore_target" in item for item in env["calls"])


def test_false_and_absent_branch_preserve_existing_idempotency_hash():
    before = gw.CreateResponseBody(input="hello", previous_response_id="resp_before")
    false = gw.CreateResponseBody(input="hello", branch=False, previous_response_id="resp_before")
    true = gw.CreateResponseBody(input="hello", branch=True, previous_response_id="resp_before")
    assert gw._req_hash(before) == gw._req_hash(false)
    assert gw._req_hash(before) != gw._req_hash(true)
    # `branch` is acted on or refused, never listed as ignored
    # (test_true_without_point_is_refused_over_http has the refusal)
    assert "branch" not in gw._ignored_request_fields(gw.CreateResponseBody(input="hello", branch=True))


def test_missing_full_commit_from_old_runner_writes_no_checkpoint_mapping(env, monkeypatch):
    async def checkpoint(_, commit=True):
        return True, 100, "source-sha", "1234567", ""
    monkeypatch.setattr(gw, "_checkpoint_relay", checkpoint)
    asyncio.run(gw._blob_delete(gw._branch_point_key(env["ids"][0]), kb=gw.RESP_BLOB_KB))
    asyncio.run(gw._checkpoint(env["sid"], {}, response_id=env["ids"][0]))
    assert asyncio.run(gw._blob_get(gw._branch_point_key(env["ids"][0]), kb=gw.RESP_BLOB_KB)) is None


def test_app_checkpoint_rewrite_does_not_hide_a_valid_git_point(env):
    asyncio.run(gw._vertex_upsert(env["sid"], {"ws_sha": "app-reprojected-sha"}))
    response = post(env)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["session_id"] != env["sid"]


def test_mapping_failure_does_not_poison_an_acknowledged_checkpoint(env, monkeypatch):
    original_put = gw._blob_put

    async def broken_mapping(key, data, **kwargs):
        if key == gw._branch_point_key(env["ids"][0]):
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
    assert asyncio.run(gw._blob_get(gw._branch_point_key(env["ids"][0]), kb=gw.RESP_BLOB_KB)) is None
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
@pytest.mark.parametrize("hint", [False, True])
async def test_true_without_point_is_refused_over_http(env, hint):
    """main: test_true_without_point_is_ignored_over_http. With a session hint the ignored flag ran
    the task as a new turn of that session, the one a branch leaves alone; now no task runs."""
    turns = env["client"].get(f"/v1/sessions/{env['sid']}/turns").json()["turns"]
    metadata = {"harness_id": env["hid"], **({"session_id": env["sid"]} if hint else {})}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        response = await client.post("/v1/responses", json={"input": "fresh task", "branch": True,
            "metadata": metadata})
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_input"
    assert response.json()["error"]["param"] == "branch"
    assert not env["calls"]
    assert env["client"].get(f"/v1/sessions/{env['sid']}/turns").json()["turns"] == turns


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
            point = await gw._blob_get(gw._branch_point_key(body["id"]), kb=gw.RESP_BLOB_KB)
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

    async def checkpoint(target, commit=True):
        await gw._blob_put(gw._ws_blob(target), b"synthetic target checkpoint")
        await gw._blob_put(f"containers/{target}/cfile_partial", b"synthetic copied artifact", kb=gw.RESP_BLOB_KB)
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

    async def checkpoint(target, commit=True):
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
    point = json.loads(await gw._blob_get(gw._branch_point_key(rid), kb=gw.RESP_BLOB_KB))
    assert point["response_id"] == rid and point["commit"] == "a" * 40
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


@pytest.mark.parametrize("malformed", ["list", "string", "null", "other-response", "other-session",
                                       "int-commit", "list-commit", "no-commit"])
def test_a_malformed_private_point_is_unavailable_not_a_500(env, malformed):
    good = {"response_id": env["ids"][0], "session_id": env["sid"], "commit": "1" * 40}
    point = {"list": [], "string": "point", "null": None,
             "other-response": {**good, "response_id": "resp_other"},
             "other-session": {**good, "session_id": "hsess_other"},
             "int-commit": {**good, "commit": 1}, "list-commit": {**good, "commit": ["1" * 40]},
             "no-commit": {k: v for k, v in good.items() if k != "commit"}}[malformed]
    asyncio.run(gw._blob_put(gw._branch_point_key(env["ids"][0]), json.dumps(point).encode(), kb=gw.RESP_BLOB_KB))
    response = post(env)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "branch_unavailable"


def test_deleted_earlier_response_is_not_reintroduced_by_branch(env):
    assert env["client"].delete(f"/v1/responses/{env['ids'][1]}").status_code == 200
    point = {"response_id": env["ids"][2], "session_id": env["sid"], "commit": "3" * 40,
             "ws_sha": "source-sha"}
    asyncio.run(gw._blob_put(gw._branch_point_key(env["ids"][2]), json.dumps(point).encode(), kb=gw.RESP_BLOB_KB))
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


# ── the runner's confirmation (#639 review, item 2) ──────────────────────────────────────────

def _purge_recorder(monkeypatch):
    """The runner's folder for a session is removed by DELETE /workspace (_session_purge): record it."""
    deleted = []

    async def sandbox(path, sid, method="POST", **kwargs):
        if path == "/workspace" and method == "DELETE":
            deleted.append(sid)
        return httpx.Response(200, json={})

    monkeypatch.setattr(gw, "POOL_ENDPOINT", "http://synthetic-runner.invalid")
    monkeypatch.setattr(gw, "_sandbox", sandbox)
    return deleted


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [{"ok": True}, {"ok": True, "restored": True},
                                    {"ok": True, "branched": "true"}, {"ok": True, "branched": 1},
                                    "not json", ["branched"]])
async def test_a_restore_the_runner_does_not_confirm_is_no_branch(env, monkeypatch, answer):
    """A runner from before branching ignores branch_commit, restores the source's latest workspace
    whole and answers 200 {"ok": true}: a branch with the wrong files, in silence. Only
    `branched: true` is a branch; anything else removes the new session and answers 503."""
    checkpoints = []

    async def old_runner(target, params, *, source_sid=None):
        env["calls"].append({"restore_target": target, "source": source_sid, "params": params})
        if isinstance(answer, str):
            return httpx.Response(200, text=answer)
        return httpx.Response(200, json=answer)

    async def checkpoint(target, commit=True):
        checkpoints.append(target)
        return True, 100, "target-sha", "a" * 7, "a" * 40

    deleted = _purge_recorder(monkeypatch)
    monkeypatch.setattr(gw, "_hydrate_relay", old_runner)
    monkeypatch.setattr(gw, "_checkpoint_relay", checkpoint)
    key = "unconfirmed-" + env["sid"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw.app), base_url="http://gateway") as client:
        response = await client.post("/v1/responses", headers={"Idempotency-Key": key}, json={
            "input": "different approach", "branch": True, "previous_response_id": env["ids"][0],
            "metadata": {"harness_id": env["hid"]}})
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "server_error"
    assert "confirm" in response.json()["error"]["message"]
    restores = [x for x in env["calls"] if "restore_target" in x]
    assert len(restores) == 1, "an unconfirmed restore is not asked again"
    target = restores[0]["restore_target"]
    assert checkpoints == [], "nothing of the wrong workspace is saved"
    assert deleted == [target], "the folder the runner restored is removed"
    assert await gw._vertex_get(target) is None
    assert not await gw.BACKING.graph.find_strict("HarnessResponse", {"session_id": target})
    assert await gw.control_store.idem_get(env["org"], gw._idem_sha(key)) is None
    sessions = await gw.BACKING.graph.find_strict("HarnessSession", {"tenant": env["org"]})
    assert [s.get("id") for s in sessions] == [env["sid"]]


# ── limits (#639 review, item 4) ─────────────────────────────────────────────────────────────

def test_a_restore_that_ran_out_of_time_or_disk_is_not_resent(env, monkeypatch):
    """The runner answers 500 branch_restore_failed for a Git timeout or a disk error. Resending
    it repeats the whole upload and every Git command and meets the same limit: one attempt."""
    attempts = []

    async def failing(target, params, *, source_sid=None):
        attempts.append(target)
        return httpx.Response(500, json={"detail": "branch_restore_failed"})

    deleted = _purge_recorder(monkeypatch)
    monkeypatch.setattr(gw, "_hydrate_relay", failing)
    monkeypatch.setattr(gw, "_HYDRATE_PAUSES", (0, 0, None))
    response = post(env)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "server_error"
    assert "limits" in response.json()["error"]["message"]
    assert len(attempts) == 1
    assert deleted == attempts


def test_branch_preparation_has_one_deadline(env, monkeypatch):
    """A restore that never answers (or resends that never end) is cut at the deadline: 503, and
    the target is removed, before anything is acknowledged."""
    started = []

    async def hangs(target, params, *, source_sid=None):
        started.append(target)
        await asyncio.sleep(30)

    deleted = _purge_recorder(monkeypatch)
    monkeypatch.setattr(gw, "_hydrate_relay", hangs)
    monkeypatch.setattr(gw, "BRANCH_PREPARE_TIMEOUT_S", 0.3)
    began = time.monotonic()
    response = post(env, background=True)
    assert time.monotonic() - began < 10
    assert response.status_code == 503, response.text
    assert "in time" in response.json()["error"]["message"]
    assert started and deleted == started
    assert asyncio.run(gw._vertex_get(started[0])) is None


def _stored_artifacts(env, count, size=10):
    """`count` captured files cited by the first response, each `size` bytes."""
    async def seed():
        record = await gw._resp_get(env["ids"][0])
        annotations = []
        for i in range(count):
            file_id = f"cfile_cap{i}"
            await gw._blob_put(f"containers/{env['sid']}/{file_id}", bytes([65 + i]) * size, kb=gw.RESP_BLOB_KB)
            await gw._blob_put(f"containers/{env['sid']}/{file_id}.meta", json.dumps({
                "filename": f"out/file{i}.txt", "media_type": "text/plain", "written_at": 1000}).encode(),
                kb=gw.RESP_BLOB_KB)
            annotations.append({"type": "container_file_citation", "container_id": env["sid"],
                                "file_id": file_id, "filename": f"out/file{i}.txt"})
        record["output"][0]["content"][0]["annotations"] = annotations
        await gw._resp_put(env["ids"][0], record, env["org"], env["sid"], None, "completed", 1000, True)
    asyncio.run(seed())


def _imported_citations(env, response):
    target = response.json()["metadata"]["session_id"]
    turns = asyncio.run(gw._session_turns_data(target))
    copied = asyncio.run(gw._resp_get(turns["turns"][0]["id"]))
    return target, copied["output"][0]["content"][0]["annotations"]


def test_artifact_copies_stop_at_the_count_and_the_rest_name_their_path(env, monkeypatch):
    monkeypatch.setattr(gw, "BRANCH_COPY_MAX_FILES", 2)
    _stored_artifacts(env, 4)
    response = post(env)
    assert response.status_code == 200, response.text
    target, citations = _imported_citations(env, response)
    assert all(c["container_id"] == target for c in citations), "never an alias of the source"
    copies = [c for c in citations if c["file_id"].startswith("cfile_")]
    paths = [c for c in citations if c["file_id"].startswith("wf_")]
    assert len(copies) == 2 and len(paths) == 2
    for c in copies:
        assert asyncio.run(gw._blob_get(f"containers/{target}/{c['file_id']}", kb=gw.RESP_BLOB_KB))
    assert [gw._wf_path(c["file_id"]) for c in paths] == ["out/file2.txt", "out/file3.txt"]
    listed = asyncio.run(gw._blob_list_all(f"containers/{target}/", kb=gw.RESP_BLOB_KB))
    assert len([it for it in listed if not str(it.get("file_id")).endswith(".meta")]) == 2


def test_artifact_copies_stop_at_the_total_bytes(env, monkeypatch):
    monkeypatch.setattr(gw, "BRANCH_COPY_MAX_BYTES", 25)
    _stored_artifacts(env, 3, size=10)                         # 10 + 10 fit, the third would not
    response = post(env)
    assert response.status_code == 200, response.text
    target, citations = _imported_citations(env, response)
    assert [c["file_id"].startswith("cfile_") for c in citations] == [True, True, False]
    assert gw._wf_path(citations[2]["file_id"]) == "out/file2.txt"


def test_artifact_caps_are_sane_by_default():
    assert gw.BRANCH_COPY_MAX_FILES == 100
    assert gw.BRANCH_COPY_MAX_BYTES == 256 * 1024 * 1024
    assert gw.BRANCH_PREPARE_TIMEOUT_S == 300


# ── a workspace's key (#639 review, item 8) ──────────────────────────────────────────────────

def test_a_workspace_key_cannot_branch_another_workspaces_response(env, monkeypatch):
    """A key held to one workspace reaches that workspace and nothing else of its organization
    (test_workspace_scope.py). Branching names a response, so it is asked there too, before
    anything says whether the response could be a branch point: not found, and no restore."""
    key_a = {"org": env["org"], "member": "svc-a", "workspace": "space.a", "workspace_default": False,
             "via": "api_key"}

    async def principal(_):
        return dict(key_a)

    async def stamp():
        # the harness is the key's workspace's, so the run itself is allowed; the response's
        # session is another workspace's
        await gw.BACKING.graph.upsert("Harness", env["hid"], {
            "org": env["org"], "member": "fixture@example.invalid", "workspace": "space.a",
            "name": env["hid"], "base": "claude-code", "custom": "1", "deleted": "0"})
        await gw._vertex_upsert(env["sid"], {"workspace": "space.b"})

    asyncio.run(stamp())
    monkeypatch.setattr(gw, "_principal", principal)
    sessions = asyncio.run(gw.BACKING.graph.find_strict("HarnessSession", {"tenant": env["org"]}))
    for mode in ({}, {"stream": True}, {"background": True}):
        response = post(env, **mode)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] in ("session_not_found", "response_not_found")
    assert not env["calls"]
    assert asyncio.run(gw.BACKING.graph.find_strict("HarnessSession", {"tenant": env["org"]})) == sessions
    with pytest.raises(gw.HTTPException) as caught:
        asyncio.run(gw._branch_source(env["ids"][0], env["org"], env["hid"], key_a))
    assert caught.value.status_code == 404
    # the same key, the same response, once the session is its workspace's: the scope was the refusal
    asyncio.run(gw._vertex_upsert(env["sid"], {"workspace": "space.a"}))
    response = post(env)
    assert response.status_code == 200, response.text

