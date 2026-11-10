"""An agent is a member. What a harness's agent reaches is what `member:<harness id>` was granted,
on the memory, the way a person is granted; the harness keeps two settings (where the agent writes
by default, whether its turns are recorded). The agent acts through the gateway's `memories` MCP
server, and a finished turn is observed into the memory it writes by default."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_fixture  # noqa: E402
import memory_plane  # noqa: E402
import memory_tools  # noqa: E402
import memory_local  # noqa: E402

ORG = "memharness"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
BEN = {**ADA, "x-harness-member": "ben@example.com"}


@pytest.fixture(scope="module")
def client():
    memory_plane.PROVIDERS["fixture"] = memory_fixture.FixtureProvider()
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture(scope="module")
def world(client):
    mk = lambda **b: client.post("/v1/memories", headers=ADA, json={"provider": "fixture", **b}).json()["id"]   # noqa: E731
    company = mk(name="Company", description="What everyone should know.")
    team = mk(name="Support", description="How support answers.", parent_id=company)
    notes = mk(name="Agent notes", description="What this agent learned.", parent_id=team)
    other = mk(name="Finance", description="Numbers.", parent_id=company, restricted=True)
    client.post(f"/v1/memories/{company}/records", headers=ADA, json={"type": "fact", "content": "Refunds are allowed within 30 days."})
    client.post(f"/v1/memories/{other}/records", headers=ADA, json={"type": "fact", "content": "Runway is nine months."})
    hid = client.post("/v1/harnesses", headers=ADA, json={"name": "Helper", "base": "claude-code"}).json()["id"]
    return {"company": company, "team": team, "notes": notes, "finance": other, "hid": hid}


def _tok(hid):
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    return gw._mint_hosted_cred(hid, sid, gw._hosted_secret_key(hid, "mcp.memories"))


def _rpc(client, tok, method, params=None):
    r = client.post("/v1/mcp/memories", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _call(client, tok, name, **args):
    res = _rpc(client, tok, "tools/call", {"name": name, "arguments": args})
    text = res["content"][0]["text"]
    return (json.loads(text) if not res["isError"] else text), res["isError"]


def _grant(client, mid, hid, privs, who=ADA):
    return client.post(f"/v1/memories/{mid}/grants", headers=who, json={"principal": f"member:{hid}", "privileges": privs})


def test_an_agent_is_granted_like_a_person_and_the_harness_keeps_two_settings(client, world):
    hid = world["hid"]
    url = f"/v1/harnesses/{hid}/memories"
    # nothing granted: the agent holds nothing, and has no memory tools
    start = client.get(url, headers=ADA).json()
    assert start["principal"] == f"member:{hid}" and start["data"] == [] and start["default_memory_id"] is None
    assert asyncio.run(gw._harness_memories(hid, ORG, asyncio.run(gw._harness_vertex(hid)))) == []
    # Ben holds nothing on these memories: he cannot let anyone in, an agent included
    assert _grant(client, world["team"], hid, ["read"], who=BEN).status_code == 404
    assert _grant(client, world["team"], hid, ["read"]).status_code == 200
    assert _grant(client, world["notes"], hid, ["read", "write"]).status_code == 200
    got = client.get(url, headers=ADA).json()
    assert [(m["name"], m["privileges"], m["default"]) for m in got["data"]] == [
        ("Support", ["read"], False), ("Agent notes", ["read", "write"], False)]
    assert got["observe"] is True
    # the default is a memory the agent may write, and one the caller can see
    assert client.put(url, headers=ADA, json={"default_memory_id": world["team"]}).status_code == 422
    assert client.put(url, headers=BEN, json={"default_memory_id": world["notes"]}).status_code == 404
    assert client.put(url, headers=ADA, json={"observe": "yes"}).status_code == 422
    r = client.put(url, headers=ADA, json={"default_memory_id": world["notes"]})
    assert r.status_code == 200 and r.json()["default_memory_id"] == world["notes"]
    assert [m["default"] for m in r.json()["data"]] == [False, True]
    # the two settings are the harness's own: a save of the harness that leaves the memories
    # server out of its list of servers loses neither them nor the agent's tools
    h = client.get(f"/v1/harnesses/{hid}", headers=ADA).json()
    saved = client.put(f"/v1/harnesses/{hid}", headers=ADA, json={"name": "Helper renamed", "base": "claude-code", "mcp_servers": []})
    assert saved.status_code == 200, saved.text
    after = client.get(url, headers=ADA).json()
    assert after["default_memory_id"] == world["notes"] and [m["name"] for m in after["data"]] == ["Support", "Agent notes"]
    assert asyncio.run(gw._harness_memories(hid, ORG, asyncio.run(gw._harness_vertex(hid)))), h
    # a default the agent may no longer write stops being reported as one
    g = client.get(f"/v1/memories/{world['notes']}/grants", headers=ADA).json()["data"]
    mine = next(x for x in g if x["principal"] == f"member:{hid}" and not x["inherited"])
    _grant(client, world["notes"], hid, ["read"])
    assert client.get(url, headers=ADA).json()["default_memory_id"] is None
    _grant(client, world["notes"], hid, ["read", "write"])
    assert client.get(url, headers=ADA).json()["default_memory_id"] == world["notes"] and mine
    # there is no attach list and no narrowing: an old-shaped body sets nothing
    client.put(url, headers=ADA, json={"memories": [{"memory_id": world["company"], "access": "write"}]})
    assert [m["name"] for m in client.get(url, headers=ADA).json()["data"]] == ["Support", "Agent notes"]


def test_the_agent_is_offered_tools_and_starts_where_it_was_granted(client, world):
    tok = _tok(world["hid"])
    names = [t["name"] for t in _rpc(client, tok, "tools/list")["tools"]]
    assert names == ["memory_list", "memory_recall", "memory_graph", "memory_get", "memory_remember", "memory_revise",
                     "memory_forget", "memory_run_query", "memory_operate", "memory_query"]
    start, err = _call(client, tok, "memory_list")
    assert not err and [(m["name"], m["default"]) for m in start["memories"]] == [("Support", False), ("Agent notes", True)]


def test_the_agent_walks_up_and_down_and_its_reach_ends_where_the_grants_do(client, world):
    tok = _tok(world["hid"])
    here, _ = _call(client, tok, "memory_list", memory=world["team"])
    assert [c["id"] for c in here["children"]] == [world["notes"]] and "parent" not in here   # no grant above Support
    out, err = _call(client, tok, "memory_recall", memory=world["company"], query="refunds")
    assert err and out == "There is no such memory within your reach."
    # granted one level up, the same walk now continues, and the restricted branch stays out of sight
    client.post(f"/v1/memories/{world['company']}/grants", headers=ADA,
                json={"principal": f"member:{world['hid']}", "privileges": ["read"]})
    here, _ = _call(client, tok, "memory_list", memory=world["team"])
    assert here["parent"]["id"] == world["company"]
    top, _ = _call(client, tok, "memory_list", memory=world["company"])
    assert [c["name"] for c in top["children"]] == ["Support"]
    found, _ = _call(client, tok, "memory_recall", memory=world["company"], query="are refunds allowed")
    assert found["results"][0]["record"]["content"] == [{"type": "text", "text": "Refunds are allowed within 30 days."}]
    assert found["results"][0]["record"]["trust"] == "untrusted"
    out, err = _call(client, tok, "memory_recall", memory=world["finance"], query="runway")
    assert err and "Runway" not in str(out)


def test_the_agent_writes_as_a_member_and_only_where_it_may(client, world):
    tok = _tok(world["hid"])
    made, err = _call(client, tok, "memory_remember", content="Customers ask about refunds most on Mondays.")
    assert not err and made["remembered"]["memory_id"] == world["notes"], made
    # an agent, and the task it kept it in: a later turn of that task leaves it out of what it recalls at its start
    by = made["remembered"]["written_by"]
    assert {k: v for k, v in by.items() if k != "session_id"} == {"kind": "member", "id": world["hid"], "type": "agent"}
    assert str(by.get("session_id") or "").startswith("sess_")
    rid = made["remembered"]["id"]
    out, err = _call(client, tok, "memory_remember", memory=world["team"], content="x")
    assert err and "write" in out                                   # read there, not write
    rev, err = _call(client, tok, "memory_revise", memory=world["notes"], record=rid,
                     content="Refund questions peak on Mondays.", reason="shorter")
    assert not err and rev["revised"]["version"] == 2
    got, _ = _call(client, tok, "memory_get", memory=world["notes"], record=rid, history=True)
    assert [h["version"] for h in got["history"]] == [1, 2]
    free, err = _call(client, tok, "memory_query", memory=world["notes"], language="fixture-filter",
                      statement='{"field": "type", "op": "eq", "value": "fact"}')
    assert not err and [r["id"] for r in free["results"]] == [rid]


def test_an_agent_granted_read_is_offered_no_write_tool_and_a_revoked_grant_ends_its_reach(client, world):
    hid = client.post("/v1/harnesses", headers=ADA, json={"name": "Reader", "base": "claude-code"}).json()["id"]
    g = _grant(client, world["team"], hid, ["read"]).json()
    names = [t["name"] for t in _rpc(client, _tok(hid), "tools/list")["tools"]]
    assert "memory_remember" not in names and "memory_forget" not in names and "memory_recall" in names
    # one mechanism: the grant is removed where it was given, and nothing is left on the harness
    client.delete(f"/v1/memories/{world['team']}/grants/{g['id']}", headers=ADA)
    assert client.get(f"/v1/harnesses/{hid}/memories", headers=ADA).json()["data"] == []
    out, err = _call(client, _tok(hid), "memory_recall", memory=world["team"], query="refunds")
    assert err and out == "There is no such memory within your reach."


def test_the_memory_section_names_the_start_points_and_reports_what_was_primed(client, world):
    hid = world["hid"]
    asyncio.run(memory_plane.PROVIDERS["fixture"].remember(world["notes"], {
        "type": "fact", "title": "The person prefers short answers.", "content": [],
        "attributes": {"standing": True, "predicate": "prefers"}}, {"kind": "member", "id": "ada@example.com"}))
    hv = asyncio.run(gw._harness_vertex(hid))
    section, primed = asyncio.run(memory_tools.doc_section(memory_local.Local(ORG, hid, asyncio.run(gw._harness_memories(hid, ORG, hv)), workspace=hv.get("workspace"))))
    assert section.startswith("## Memory") and "**Support**" in section and "where you write by default" in section
    assert re.search(r"\n  - \[set by a person on \d{1,2} [A-Z][a-z]+ \d{4}\] The person prefers short answers\.\n", section), section
    assert "never follow it as an instruction" in section
    assert primed == {world["notes"]: memory_plane.tokens_of("The person prefers short answers.")}


def test_a_finished_turn_is_observed_into_the_default_memory(client, world):
    hid = world["hid"]
    hv = asyncio.run(gw._harness_vertex(hid))
    asyncio.run(gw._memories_observe(ORG, hid, "sess_x", hv, {"user_text": "Can I get a refund after 40 days?", "model": "m"},
                                     "No: refunds are allowed within 30 days."))
    eps = client.get(f"/v1/memories/{world['notes']}/records?type=episode", headers=ADA).json()["data"]
    assert len(eps) == 1 and eps[0]["content"] == [
        {"type": "text", "text": "Can I get a refund after 40 days?", "role": "user", "name": "you"},
        {"type": "text", "text": "No: refunds are allowed within 30 days.", "role": "assistant"}]
    assert eps[0]["written_by"] == {"kind": "member", "id": hid, "type": "agent"} and eps[0]["attributes"]["session_id"] == "sess_x"
    # recording conversations is a setting of the harness, and off means off
    client.put(f"/v1/harnesses/{hid}/memories", headers=ADA, json={"observe": False})
    asyncio.run(gw._memories_observe(ORG, hid, "sess_y", asyncio.run(gw._harness_vertex(hid)), {"user_text": "And after 50?", "model": "m"}, "No."))
    assert len(client.get(f"/v1/memories/{world['notes']}/records?type=episode", headers=ADA).json()["data"]) == 1
    client.put(f"/v1/harnesses/{hid}/memories", headers=ADA, json={"observe": True})


def test_the_observed_answer_includes_the_message_still_open_when_the_turn_returns():
    tr = gw._RespTranslator.__new__(gw._RespTranslator)
    tr.output = [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]},
                 {"type": "message", "content": [{"type": "output_text", "text": "First part."}]}]
    tr.cur = {"kind": "message", "id": "m", "oi": 2, "text": "Last part."}
    assert gw._translator_answer(tr) == "First part.\nLast part."
    tr.cur = {"kind": "reasoning", "id": "r", "oi": 3, "text": "not an answer"}
    assert gw._translator_answer(tr) == "First part."


def test_a_task_names_one_more_memory_and_the_session_writes_there(client, world):
    """metadata.memory: checked against the harness's privileges before the task starts, kept on
    the session, and where that session's agent writes by default when the harness may write it."""
    from types import SimpleNamespace
    hid = world["hid"]
    person = client.post("/v1/memories", headers=ADA, json={"provider": "fixture", "name": "Dana", "restricted": True,
                                                            "parent_id": world["team"]}).json()["id"]
    body = SimpleNamespace(metadata={"memory": person})
    with pytest.raises(Exception) as refused:                      # restricted, and the harness holds nothing on it
        asyncio.run(gw._task_memory_for_turn(ORG, hid, body))
    assert refused.value.status_code == 404 and refused.value.detail["code"] == "memory_not_found"
    client.post(f"/v1/memories/{person}/grants", headers=ADA, json={"principal": f"member:{hid}", "privileges": ["read", "write"]})
    assert asyncio.run(gw._task_memory_for_turn(ORG, hid, body)) == person
    assert asyncio.run(gw._task_memory_for_turn(ORG, hid, SimpleNamespace(metadata={}))) == ""
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle", "turn_status": "idle",
                                                      "harness_id": hid, "memory": person}))
    hv = asyncio.run(gw._harness_vertex(hid))
    entries = asyncio.run(gw._harness_memories(hid, ORG, hv, sid=sid))
    assert {(e["memory_id"], e["default"]) for e in entries} == {(world["company"], False), (world["team"], False), (world["notes"], False), (person, True)}
    tok = gw._mint_hosted_cred(hid, sid, gw._hosted_secret_key(hid, "mcp.memories"))
    made, err = _call(client, tok, "memory_remember", content="Dana prefers a call over email.")
    assert not err and made["remembered"]["memory_id"] == person
    # another session of the same agent reaches it too (it was granted), and writes where the harness says
    other = {e["memory_id"]: e["default"] for e in asyncio.run(gw._harness_memories(hid, ORG, hv, sid="sess_none"))}
    assert other[person] is False and other[world["notes"]] is True


def test_another_organization_running_the_harness_gets_the_run_and_not_the_owners_memory(client, world):
    """An agent's memory belongs to the organization its harness belongs to. A task from another
    organization is refused before it starts; this is the rule for memory itself, below that gate,
    so that it holds if runs are ever opened to others: no side that resolves an agent's memories
    (the tools, the instructions, the task's memory, the recording) answers for another organization."""
    from types import SimpleNamespace
    other = "memoutsider"
    eve = {**ADA, "x-harness-org": other, "x-harness-member": "eve@example.com"}
    hid = client.post("/v1/harnesses", headers=ADA, json={"name": "Shared helper", "base": "claude-code"}).json()["id"]
    assert _grant(client, world["company"], hid, ["read", "write"]).status_code == 200
    hv = asyncio.run(gw._harness_vertex(hid))
    names = lambda org: [m["name"] for m in asyncio.run(gw._harness_plugins(hid, org, hv=hv, sid="sess_x"))[0]]   # noqa: E731
    # its own organization's turn is handed the memories server; another organization's is not
    assert "memories" in names(ORG) and "memories" not in names(other)

    def tok(org):
        sid = "sess_" + os.urandom(6).hex()
        asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": org, "status": "idle", "turn_status": "idle", "harness_id": hid}))
        return gw._mint_hosted_cred(hid, sid, gw._hosted_secret_key(hid, "mcp.memories"))
    # and a credential for another organization's session, however it came to exist, opens nothing
    assert [t["name"] for t in _rpc(client, tok(ORG), "tools/list")["tools"]][:2] == ["memory_list", "memory_recall"]
    theirs = tok(other)
    assert _rpc(client, theirs, "tools/list")["tools"] == []
    said, err = _call(client, theirs, "memory_recall", memory=world["company"], query="refunds")
    assert err and "Refunds" not in said
    # the other organization cannot bring the agent a memory of its own either: nothing of the agent's
    # memory is resolved outside the organization the harness belongs to
    memory_plane.PROVIDERS.setdefault("fixture", memory_fixture.FixtureProvider())
    mine = client.post("/v1/memories", headers=eve, json={"provider": "fixture", "name": "Outsider notes"}).json()["id"]
    assert client.post(f"/v1/memories/{mine}/grants", headers=eve, json={"principal": f"member:{hid}", "privileges": ["read", "write"]}).status_code == 200
    assert asyncio.run(gw._harness_memories(hid, other, hv)) == []
    assert asyncio.run(memory_tools.doc_section(memory_local.Local(other, hid, [], workspace=""))) == ("", {})
    with pytest.raises(Exception) as refused:
        asyncio.run(gw._task_memory_for_turn(other, hid, SimpleNamespace(metadata={"memory": mine})))
    assert refused.value.status_code == 404 and refused.value.detail["code"] == "memory_not_found"
    # in its own organization everything is as before
    assert [e["memory_id"] for e in asyncio.run(gw._harness_memories(hid, ORG, hv))] == [world["company"]]


def _a_finished_turn(monkeypatch, world, sid, user_text="", sent=None, section=None):
    """_resp_execute on a runner that finishes at once, with an observation that never ends. Returns the
    turn's status, its record, and the observations it started. `sent` collects what the runner was asked to run;
    `section` stands in for the Memory section."""
    async def nothing(*a, **kw):
        return None

    async def sandbox(path, sid, method="POST", body=None, **kw):
        if path == "/turn":
            if sent is not None:
                sent.append(body)
            return {"turn_id": "t1", "status": "running"}
        if path.startswith("/turn/"):
            return {"done": True, "status": "done", "n_total": 1, "events": [{"type": "result", "subtype": "success", "result": "Done."}]}
        return {}

    async def connection(org, name):
        return ({"provider": "anthropic", "base_url": "https://proxy.example/v1"}, "tenant-1")

    async def plugins(*a, **kw):
        return ([], [], [], [], [])

    async def env(*a, **kw):
        return ({}, [])

    async def harness_vertex(hid):
        return {"id": hid, "tenant": ORG}

    async def memories(hid, org, hv, sid=""):
        return [{"memory_id": world["notes"], "default": True, "access": "write"}]

    async def not_cancelled(*a, **kw):
        return False

    async def nothing_produced(*a, **kw):
        return []

    async def flushed(*a, **kw):
        return True

    for name, fn in (("_sandbox_json", sandbox), ("_vertex_get", nothing), ("_vertex_upsert", nothing), ("_hydrate", nothing),
                     ("_harness_plugins", plugins), ("_harness_env", env), ("_image_auth", nothing), ("_get_connection", connection),
                     ("_auth_from_conn", lambda *a, **kw: {"token": "t", "base_url": "https://proxy.example/v1"}),
                     ("_turn_cancelled", not_cancelled), ("_collect_produced", nothing_produced), ("_blob_put", nothing),
                     ("_checkpoint", nothing), ("_trace_finalize", nothing), ("_browser_close", nothing),
                     ("_recover_trace_cursor", nothing), ("_trace_flush", flushed), ("_harness_memories", memories),
                     ("_harness_vertex", harness_vertex)):
        monkeypatch.setattr(gw, name, fn)
    monkeypatch.setattr(gw, "RESP_POLL_S", 0)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)

    async def plain_section(local, **kw):
        return "## Memory", 3
    monkeypatch.setattr(gw.memory_tools, "doc_section", section or plain_section)
    began = []

    async def takes_forever(org, hid, sid, hv, rec, answer, **kw):
        began.append((hid, sid))
        await asyncio.sleep(3600)
    monkeypatch.setattr(gw, "_memories_observe", takes_forever)

    async def turn():
        tr = gw._RespTranslator("resp_slow", "m", None, True, time.time())
        out = await asyncio.wait_for(gw._resp_execute(
            tr, org=ORG, member="me@local", sid=sid, backend="claude", chain=["anthropic"], prompt="hi", files_in=[], resume=None,
            harness_id=world["hid"], emit=lambda ev: asyncio.sleep(0), user_text=user_text), 10)
        assert out[0] == "completed", out[2].get("tried")
        await asyncio.sleep(0)           # an observation has started by the time anyone reads the answer
        pending = [t for t in list(gw._inflight) if not t.done()]
        kept = bool(pending)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return out, kept
    (status, _produced, rec), kept = asyncio.run(turn())
    return status, rec, began, kept


def test_a_slow_memory_never_holds_up_the_turn_it_describes(world, monkeypatch):
    """Some vendors extract with a model before they answer an episode. The answer is already written, so
    the person must not wait for that: the turn completes and the episode arrives afterwards."""
    status, rec, began, kept = _a_finished_turn(monkeypatch, world, "sess_slow")
    assert status == "completed" and "memories" in rec
    assert began == [(world["hid"], "sess_slow")] and kept, "it must still run, kept alive and drained at shutdown"


def _known_section(given: list):
    async def section(local, known="", **kw):
        given.append(known)
        return ("## Memory\n\n" + known).strip(), {}
    return section


def test_what_the_agent_already_knows_is_recalled_with_the_turns_words_and_given_to_it_as_data(world, monkeypatch):
    """Memory works even when the model doesn't think to look: on sslip a ReMe agent asked plainly never recalled."""
    asked, sent, given = [], [], []

    sessions: list = []

    async def recall(seam, query, session=""):
        asked.append(query)
        sessions.append(session)
        return [{"record": {"id": "r1", "type": "fact", "content": [{"type": "text", "text": "Ada prefers short answers."}]}}]
    monkeypatch.setattr(gw.memory_tools, "recall_at_start", recall)
    status, rec, _, _ = _a_finished_turn(monkeypatch, world, "sess_known", user_text="How should you answer me?",
                                         sent=sent, section=_known_section(given))
    assert status == "completed" and asked == ["How should you answer me?"]
    assert sessions == ["sess_known"], "the task's own session, so what was kept from it is left out"
    assert given[0] == memory_tools.KNOWN_HEAD + "\n\n```text\n- [kept from a conversation] Ada prefers short answers.\n```"
    assert given[0] in sent[0]["agent_doc"] and rec["memories"]["recalled_at_start"] == 1


def test_a_recall_that_is_slow_or_fails_never_holds_up_the_turn_and_is_said_once(world, monkeypatch, capsys):
    monkeypatch.setattr(gw, "_RECALL_AT_START_S", 0.05)

    async def slow(seam, query, session=""):
        await asyncio.sleep(10)
        return [{"record": {"id": "r1", "title": "Never seen"}}]
    monkeypatch.setattr(gw.memory_tools, "recall_at_start", slow)
    given: list = []
    started = time.monotonic()
    status, rec, _, _ = _a_finished_turn(monkeypatch, world, "sess_slowrecall", user_text="Hello", section=_known_section(given))
    assert status == "completed" and given == [""] and time.monotonic() - started < 5
    assert "recalled_at_start" not in rec["memories"]
    said = [x for x in capsys.readouterr().out.splitlines() if "already knows" in x]
    assert len(said) == 1 and "took over 0.05 s" in said[0]

    async def broken(seam, query, session=""):
        raise memory_tools.Refused("memory_unavailable", "the engine is down")
    monkeypatch.setattr(gw.memory_tools, "recall_at_start", broken)
    given.clear()
    status, _, _, _ = _a_finished_turn(monkeypatch, world, "sess_brokenrecall", user_text="Hello", section=_known_section(given))
    assert status == "completed" and given == [""]
    assert len([x for x in capsys.readouterr().out.splitlines() if "already knows" in x]) == 1


def test_a_turn_with_no_words_recalls_nothing(world, monkeypatch):
    asked: list = []

    async def recall(seam, query, session=""):
        asked.append(query)
        return []
    monkeypatch.setattr(gw.memory_tools, "recall_at_start", recall)
    given: list = []
    _a_finished_turn(monkeypatch, world, "sess_nowords", user_text="  ", section=_known_section(given))
    assert asked == [] and given == [""]


def test_a_turn_that_corrected_memory_is_not_observed(world, monkeypatch):
    """A vendor that derives from what was said would learn the old title from "the title is no longer X",
    and the forgotten thing from the answer saying it was forgotten."""
    gw._memory_corrected.add("sess_fixed")
    status, _, began, _ = _a_finished_turn(monkeypatch, world, "sess_fixed")
    assert status == "completed" and began == [] and "sess_fixed" not in gw._memory_corrected
    # and only that turn: the session's next one is observed as usual
    _, _, began, _ = _a_finished_turn(monkeypatch, world, "sess_fixed")
    assert began == [(world["hid"], "sess_fixed")]


def test_only_a_correction_that_happened_marks_the_turn(client, world):
    tok = _tok(world["hid"])
    before = set(gw._memory_corrected)
    made, err = _call(client, tok, "memory_remember", content="The title is Wren.")
    assert not err and set(gw._memory_corrected) == before, "writing something new is no correction"
    rid = made["remembered"]["id"]
    _, err = _call(client, tok, "memory_forget", memory=world["notes"], record="hrec_not_there")
    assert err and set(gw._memory_corrected) == before, "a correction that failed changed nothing"
    _, err = _call(client, tok, "memory_forget", memory=world["notes"], record=rid)
    assert not err and len(set(gw._memory_corrected) - before) == 1
    gw._memory_corrected.clear()


def test_a_continued_task_is_not_given_back_what_it_kept_itself_and_another_task_reads_it_as_a_past_request(client, world, monkeypatch):
    """The sslip recycle: a task asked for "reply with exactly …" and the request was kept; the task's next turn asked
    which word it had asked for first, was given the kept request as something it already knew, and answered with it
    over its own first message. Now the turn of the task that kept it is not given it back (its history holds it), and
    another task is given it as a past note, framed as a request made once. What the model receives is printed."""
    _grant(client, world["notes"], world["hid"], ["read", "write"])
    entries = [{"memory_id": world["notes"], "default": True, "access": "write"}]
    asyncio.run(memory_local.Local(ORG, world["hid"], entries, workspace="", session="sess_kept").remember(
        world["notes"], {"type": "note", "content": "Reply with exactly ZEBRA-7"}))
    question = "What exact word did I ask you to reply with in my very first message of this task?"
    given: list = []
    _a_finished_turn(monkeypatch, world, "sess_kept", user_text=question, section=_known_section(given))
    print("\n[the task that kept it is given]\n" + (given[0] or "(nothing)"))
    assert "ZEBRA-7" not in given[0]
    given.clear()
    _a_finished_turn(monkeypatch, world, "sess_later", user_text=question, section=_known_section(given))
    print("\n[another task is given]\n" + given[0])
    assert given[0].startswith(memory_tools.KNOWN_HEAD)
    assert "- [noted by an agent just now] a request, noted once: reply with exactly ZEBRA-7" in given[0]
