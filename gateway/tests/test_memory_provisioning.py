"""A new agent remembers from its first task: the gateway chooses its engine (memory_choice), makes its memory,
grants it read and write through the grant path, and keeps each finished task. An agent that serves people keeps
each person's memory apart. Against mem0's Platform as the stand-in in test_memory_mem0.py answers it (the shapes
the real service answered), so what is checked is what reaches the engine and what comes back from it."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_choice  # noqa: E402
import memory_fixture  # noqa: E402
import memory_graphiti  # noqa: E402
import memory_hindsight  # noqa: E402
import memory_mem0  # noqa: E402
import memory_plane  # noqa: E402
import memory_reme  # noqa: E402
import setup_builder  # noqa: E402
from test_memory_mem0 import KEY, Mem0Stub  # noqa: E402

ORG = "provorg"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
BEN = {**ADA, "x-harness-member": "ben@example.com"}
run = asyncio.run


@pytest.fixture(scope="module")
def stub():
    s = Mem0Stub()
    memory_mem0.transport = httpx.MockTransport(s)
    yield s
    memory_mem0.transport = None


@pytest.fixture(scope="module")
def client(stub):
    memory_plane.PROVIDERS.setdefault("fixture", memory_fixture.FixtureProvider())
    with TestClient(gw.app) as c:
        r = c.put("/v1/plugs/mem0", headers=ADA, json={"secrets": {"api_key": KEY}})
        assert r.status_code == 200 and r.json()["status"] == "connected", r.text
        yield c


def _key(client, ws: str = "", member: str = "svc@example.com") -> dict:
    r = client.post(f"/v1/orgs/{ORG}/keys", headers=ADA, json={"name": "k", "workspace": ws, "member_id": member})
    assert r.status_code == 200, r.text
    return {"authorization": "Bearer " + (r.json().get("key") or r.json().get("token") or r.json()["secret"])}


def _agent(client, name="Support replies", prompt="Answer our customers' questions about their plan.", **extra):
    r = client.post("/v1/harnesses", headers=extra.pop("headers", ADA),
                    json={"name": name, "base": "claude-code", "system_prompt": prompt, **extra})
    return r


def _session(hid: str, person: dict | None = None, org: str = ORG) -> tuple[str, str]:
    """A task of this agent: its session, begun as a turn begins (whose task it is), and its tools' credential."""
    sid = "sess_" + uuid.uuid4().hex[:12]
    run(gw._vg_upsert("HarnessSession", sid, {"tenant": org, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    tr = gw._RespTranslator("resp_" + uuid.uuid4().hex[:12], "m", None, True, time.time(), sid=sid)
    rec: dict = {}
    run(gw._memories_person_begin(org, hid, run(gw._harness_vertex(hid)), sid, person or {}, tr, rec))
    return sid, gw._mint_hosted_cred(hid, sid, gw._hosted_secret_key(hid, "mcp.memories"))


def _rpc(client, tok, method, params=None):
    r = client.post("/v1/mcp/memories", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _call(client, tok, name, **args):
    res = _rpc(client, tok, "tools/call", {"name": name, "arguments": args})
    text = res["content"][0]["text"]
    return (json.loads(text) if not res["isError"] else text), res["isError"]


def _words(found) -> str:
    return json.dumps(found)


# ── provisioning on create ───────────────────────────────────────────────────────────────────
def test_auto_is_the_default_and_gives_a_new_agent_its_own_memory(client, stub):
    r = _agent(client)
    assert r.status_code == 200, r.text
    h = r.json()
    m = h["memory"]
    assert m["engine"] == "mem0" and m["scope"] == "per_user" and m["observe"] is True
    assert m["name"] == "Support replies" and m["reason"] == memory_choice.REASON["mem0"] and "memory_reason" not in h
    # granted read and write through the grant path, its default, its tools, every finished task kept
    mine = client.get(f"/v1/harnesses/{h['id']}/memories", headers=ADA).json()
    assert mine["default_memory_id"] == m["id"] and mine["observe"] is True
    assert [(x["id"], x["privileges"]) for x in mine["data"]] == [(m["id"], ["read", "write"])]
    grants = client.get(f"/v1/memories/{m['id']}/grants", headers=ADA).json()["data"]
    assert [(g["principal"], g["privileges"]) for g in grants] == [(f"member:{h['id']}", ["read", "write"])]
    # the same on a read, plainly: memory is on and each finished task is kept
    again = client.get(f"/v1/harnesses/{h['id']}", headers=ADA).json()
    assert again["memory"] == m
    # the person who made the agent manages its memory like any of theirs
    assert client.get(f"/v1/memories/{m['id']}", headers=ADA).json()["privileges"] == ["read", "write", "create", "delete"]


def test_none_gives_no_memory_and_says_so(client):
    h = _agent(client, name="Quiet", memory="none").json()
    assert h["memory"] is None and h["memory_reason"] == "Memory is off for this agent."
    assert client.get(f"/v1/harnesses/{h['id']}/memories", headers=ADA).json()["data"] == []


def test_an_agent_that_works_on_what_it_is_given_gets_none(client):
    h = _agent(client, name="Translator", prompt="Translate the given text into French.").json()
    assert h["memory"] is None and h["memory_reason"] == memory_choice.REASON["none"]


def test_an_engine_named_is_used_and_one_not_running_is_refused_before_anything_is_made(client):
    h = _agent(client, name="Team wiki", prompt="Keep the handbook.", memory={"engine": "mem0"}).json()
    assert h["memory"]["engine"] == "mem0" and h["memory"]["scope"] == "shared" and "Mem0" in h["memory"]["reason"]
    before = len(client.get(f"/v1/orgs/{ORG}/harnesses", headers=ADA).json()["harnesses"])
    r = _agent(client, name="Graph", memory={"engine": "graphiti"})
    assert r.status_code == 422 and "Graphiti isn't running here" in r.json()["error"]["message"]
    assert len(client.get(f"/v1/orgs/{ORG}/harnesses", headers=ADA).json()["harnesses"]) == before
    assert _agent(client, name="Bad", memory="sometimes").status_code == 422
    assert _agent(client, name="Bad", memory={"engine": "redis"}).status_code == 422


def test_an_existing_memory_the_caller_may_share(client):
    mid = client.post("/v1/memories", headers=ADA, json={"provider": "mem0", "name": "Company facts"}).json()["id"]
    h = _agent(client, name="Facts helper", memory={"id": mid}).json()
    assert h["memory"]["id"] == mid and h["memory"]["name"] == "Company facts"
    assert client.get(f"/v1/harnesses/{h['id']}/memories", headers=ADA).json()["default_memory_id"] == mid
    # someone who holds nothing on it can't hand it to an agent, and the answer is the one for a memory that isn't there
    r = _agent(client, name="Not yours", memory={"id": mid}, headers=BEN)
    assert r.status_code == 404 and r.json()["error"]["code"] == "memory_not_found"


def test_nothing_connected_means_no_memory_and_the_command_that_starts_one(client):
    other = {**ADA, "x-harness-org": "provorg-empty"}
    h = client.post("/v1/harnesses", headers=other, json={"name": "Support replies", "base": "claude-code"}).json()
    assert h["memory"] is None and h["memory_reason"] == memory_choice.NO_ENGINE


def test_the_org_route_provisions_too(client):
    h = client.post(f"/v1/orgs/{ORG}/harnesses", headers=ADA, json={"name": "Account briefs", "base": "claude-code",
                                                                      "system_prompt": "Track our key accounts and deals."}).json()
    # Graphiti fits best and isn't running here: Mem0 keeps it, and says so
    assert h["memory"]["engine"] == "mem0" and h["memory"]["scope"] == "shared"
    assert "Graphiti fits best; it isn't running here, so Mem0 keeps it for now." in h["memory"]["reason"]


def test_a_save_of_the_harness_never_touches_its_memory(client):
    h = _agent(client, name="Saved").json()
    sent = {**h, "name": "Saved again"}
    sent.pop("id")
    r = client.put(f"/v1/harnesses/{h['id']}", headers=ADA, json=sent)
    assert r.status_code == 200, r.text
    assert r.json()["memory"] == h["memory"] and r.json()["name"] == "Saved again"
    r = client.put(f"/v1/harnesses/{h['id']}", headers=ADA, json={**sent, "memory": "none"})
    assert r.json()["memory"] == h["memory"], "only PUT .../memory changes it"


def test_a_harness_made_before_says_nothing_new_and_saves_as_before(client):
    hid = gw._rid("chrn")
    run(gw._vg_upsert("Harness", hid, {"org": ORG, "name": "Old", "base": "claude-code", "deleted": "0", "custom": "1",
                                       "member": "ada@example.com", "workspace": "", "mcp_servers": "[]"}))
    got = client.get(f"/v1/harnesses/{hid}", headers=ADA).json()
    assert "memory" not in got and "memory_reason" not in got
    assert client.get(f"/v1/harnesses/{hid}/memories", headers=ADA).json()["data"] == []


# ── changed in one place ─────────────────────────────────────────────────────────────────────
def test_put_memory_turns_it_off_and_on_and_keeps_the_old_memory(client):
    h = _agent(client, name="Switcher").json()
    old = h["memory"]["id"]
    url = f"/v1/harnesses/{h['id']}/memory"
    off = client.put(url, headers=ADA, json={"observe": False}).json()
    assert off["memory"]["observe"] is False and off["memory"]["id"] == old
    none = client.put(url, headers=ADA, json={"memory": "none"}).json()
    assert none["memory"] is None and none["memory_reason"] == "Memory is off for this agent."
    assert client.get(f"/v1/harnesses/{h['id']}/memories", headers=ADA).json()["data"] == []
    assert client.get(f"/v1/memories/{old}", headers=ADA).status_code == 200, "nothing is deleted"
    back = client.put(url, headers=ADA, json={"memory": "auto"}).json()
    assert back["memory"]["engine"] == "mem0" and back["memory"]["id"] != old
    same = client.put(url, headers=ADA, json={"memory": "auto"}).json()
    assert same["memory"]["id"] == back["memory"]["id"], "the same choice again is the same memory"
    for bad in ({}, {"memory": "auto", "url": "http://x"}, {"observe": "yes"}, {"memory": 3}):
        assert client.put(url, headers=ADA, json=bad).status_code == 422, bad


def test_put_memory_is_held_to_the_callers_workspace(client):
    h = _agent(client, name="Mine").json()
    assert h["memory"] is not None
    held = _key(client, ws="ws.two")
    r = client.put(f"/v1/harnesses/{h['id']}/memory", headers=held, json={"memory": "none"})
    assert r.status_code == 404
    assert client.get(f"/v1/harnesses/{h['id']}", headers=ADA).json()["memory"] is not None


# ── one person's memory ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def per_person(client):
    h = _agent(client, name="Concierge", prompt="Help each guest with bookings.").json()
    assert h["memory"]["scope"] == "per_user"
    shared = h["memory"]["id"]
    r = client.post(f"/v1/memories/{shared}/records", headers=ADA, json={"type": "fact", "content": "Breakfast is served until ten."})
    assert r.status_code == 200, r.text
    return h["id"], shared


def test_a_person_never_recalls_another_persons_facts_through_the_tool(client, per_person):
    hid, shared = per_person
    _, dana = _session(hid, {"user": "dana@guests.example"})
    _, eli = _session(hid, {"user": "eli@guests.example"})
    kept, err = _call(client, dana, "memory_remember", content="Dana's dog is called Rex.")
    assert not err and kept["remembered"]["memory_id"] != shared
    found, err = _call(client, eli, "memory_recall", query="dog")
    assert not err and "Rex" not in _words(found)
    # nor by asking from the top: every person's memory is restricted, so the agent's own grant stops above it
    found, err = _call(client, eli, "memory_recall", memory=shared, query="dog")
    assert not err and "Rex" not in _words(found)
    # both read what the agent knows for everyone
    for tok in (dana, eli):
        got, err = _call(client, tok, "memory_recall", query="breakfast")
        assert not err and "Breakfast is served until ten." in _words(got)
    mine, _ = _call(client, dana, "memory_recall", query="dog")
    assert "Rex" in _words(mine)
    # naming the other person's memory by its id reaches nothing
    node = kept["remembered"]["memory_id"]
    for tool, args in (("memory_recall", {"query": "dog"}), ("memory_list", {}), ("memory_get", {"record": kept["remembered"]["id"]})):
        out, err = _call(client, eli, tool, memory=node, **args)
        assert err and out == "There is no such memory within your reach." and "Rex" not in str(out)


def test_a_persons_task_writes_only_their_own_memory(client, per_person):
    hid, shared = per_person
    _, dana = _session(hid, {"user": "dana@guests.example"})
    out, err = _call(client, dana, "memory_remember", memory=shared, content="Every guest gets a free upgrade.")
    assert err and "upgrade" not in _words(client.get(f"/v1/memories/{shared}/records", headers=ADA).json())
    listed, _ = _call(client, dana, "memory_list")
    assert [(x["name"], x["default"]) for x in listed["memories"]][0] == ("This person's memory", True)
    assert "dana@guests.example" not in _words(listed), "the agent is not told who the person is"


def test_a_person_never_recalls_another_persons_facts_through_what_was_kept_after_a_task(client, per_person):
    hid, _ = per_person
    sa, dana = _session(hid, {"user": "dana@guests.example"})
    _, eli = _session(hid, {"user": "eli@guests.example"})
    hv = run(gw._harness_vertex(hid))
    run(gw._memories_observe(ORG, hid, sa, hv, {"user_text": "My locker code is 4512.", "model": "m"}, "Noted.", resp_id="resp_x"))
    assert "4512" in _words(_call(client, dana, "memory_recall", query="locker")[0])
    assert "4512" not in _words(_call(client, eli, "memory_recall", query="locker")[0])


def test_the_operator_sees_each_persons_memory_by_who_they_are(client, per_person):
    hid, shared = per_person
    _session(hid, {"user": "dana@guests.example"})
    kids = client.get("/v1/memories", params={"parent": shared}, headers=ADA).json()["data"]
    people = {k["end_user"]: k for k in kids}
    assert "dana@guests.example" in people and people["dana@guests.example"]["restricted"] is True
    assert people["dana@guests.example"]["name"] == memory_plane.end_user_hash("dana@guests.example")
    # someone else holds nothing on a person's memory: it is not there for them
    assert client.get(f"/v1/memories/{people['dana@guests.example']['id']}", headers=BEN).status_code == 404


def test_a_task_from_an_api_key_that_names_nobody_runs_without_memory_and_says_so(client, per_person, stub):
    hid, _ = per_person
    hv = run(gw._harness_vertex(hid))
    key = {"org": ORG, "member": "svc@example.com", "workspace": "", "via": "api_key"}
    person = run(gw._task_person(ORG, hid, hv, SimpleNamespace(user=None, metadata={}), key))
    assert person == {"skipped": "no end user named"}
    sid = "sess_" + uuid.uuid4().hex[:12]
    run(gw._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    tr = gw._RespTranslator("resp_skip1", "m", None, True, time.time(), sid=sid)
    rec: dict = {}
    run(gw._memories_person_begin(ORG, hid, hv, sid, person, tr, rec))
    assert tr._response_obj("completed")["metadata"]["memory"] == {"skipped": "no end user named"}
    assert rec["memory"] == {"skipped": "no end user named"}
    # no tools, no recall, no remember, and nothing kept after the task
    tok = gw._mint_hosted_cred(hid, sid, gw._hosted_secret_key(hid, "mcp.memories"))
    assert _rpc(client, tok, "tools/list")["tools"] == []
    out, err = _call(client, tok, "memory_recall", query="breakfast")
    assert err and "Breakfast" not in out
    asked = len(stub.calls)
    run(gw._memories_observe(ORG, hid, sid, hv, {"user_text": "Remember me.", "model": "m"}, "Sure."))
    assert len(stub.calls) == asked
    section, _ = run(gw.memory_tools.doc_section(gw.memory_local.Local(ORG, hid, run(gw._harness_memories(hid, ORG, hv, sid=sid)))))
    assert section == ""
    # and the turn's record says the same
    run(gw._resp_put("resp_skip1", {"id": "resp_skip1", "status": "completed", "output": [], "_input": [{"content": "hi"}]},
                     ORG, sid, None, "completed", time.time(), True))
    turns = run(gw._session_turns_data(sid))["turns"]
    assert turns[0]["memory"] == {"skipped": "no end user named"}


def test_who_a_task_is_for(client, per_person):
    hid, _ = per_person
    hv = run(gw._harness_vertex(hid))
    key = {"org": ORG, "member": "svc@example.com", "via": "api_key"}
    person_at_console = {"org": ORG, "member": "ada@example.com"}
    who = lambda body, p: run(gw._task_person(ORG, hid, hv, SimpleNamespace(**body), p))   # noqa: E731
    assert who({"user": "u-17", "metadata": {"user": "other"}}, key) == {"user": "u-17"}
    assert who({"user": None, "metadata": {"user": "u-18"}}, key) == {"user": "u-18"}
    assert who({"user": None, "metadata": {}}, person_at_console) == {"user": "ada@example.com"}
    assert who({"user": None, "metadata": {}}, {**key, "calibration": {"inner": hid}}) == {"skipped": "no end user named"}
    # an agent that keeps one memory for everyone needs nobody named
    shared_agent = _agent(client, name="Market research", prompt="Research competitors.").json()
    assert run(gw._task_person(ORG, shared_agent["id"], run(gw._harness_vertex(shared_agent["id"])),
                               SimpleNamespace(user=None, metadata={}), key)) == {}


def test_the_user_field_is_taken_and_kept_out_of_the_request_hash_when_absent():
    body = gw.CreateResponseBody(model="m", input="hi")
    assert body.user is None and gw._req_hash(body) == gw._req_hash(gw.CreateResponseBody(model="m", input="hi"))
    assert gw._req_hash(gw.CreateResponseBody(model="m", input="hi", user="u-1")) != gw._req_hash(body)


# ── what is never kept ───────────────────────────────────────────────────────────────────────
SECRETS = ["sk-live-abcdef1234567890", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVl",
           "hrm_msvc_0123456789abcdef.deadbeefdeadbeef", "Bearer abcdefghijklmnop1234"]
PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ\n-----END PRIVATE KEY-----"


def test_a_pasted_key_is_never_kept_by_remember_or_by_what_a_task_leaves(client, per_person, stub):
    hid, _ = per_person
    sa, dana = _session(hid, {"user": "dana@guests.example"})
    made, err = _call(client, dana, "memory_remember", title="Dana's keys", content="Her key is " + " and ".join(SECRETS) + "\n" + PEM)
    assert not err
    hv = run(gw._harness_vertex(hid))
    run(gw._memories_observe(ORG, hid, sa, hv, {"user_text": f"Use my key {SECRETS[0]}. Also {SECRETS[1]}.", "model": "m"}, "Done."))
    stored = json.dumps(list(stub.mem.values()))
    for s in [*SECRETS, "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ"]:
        assert s.split(" ")[-1] not in stored, s
    assert "[redacted]" in stored
    found, _ = _call(client, dana, "memory_recall", query="key")
    for s in SECRETS:
        assert s.split(" ")[-1] not in _words(found)


# ── failures said on the memory ──────────────────────────────────────────────────────────────
def test_failures_and_successes_are_kept_on_the_memory(client, stub, monkeypatch):
    h = _agent(client, name="Fragile", prompt="Help each customer.").json()
    mid = h["memory"]["id"]
    sid, tok = _session(h["id"], {"user": "zoe@example.com"})
    node = client.get("/v1/memories", params={"parent": mid}, headers=ADA).json()["data"][0]["id"]
    memory_plane._MARKED.clear()
    made, err = _call(client, tok, "memory_remember", content="Zoe prefers mornings.")
    assert not err and client.get(f"/v1/memories/{node}", headers=ADA).json()["last_ok_at"]
    real = stub.__call__

    def broken(req):
        if req.url.path == "/v3/memories/add/":
            return httpx.Response(500, json={"error": "database is down"})
        return real(req)
    monkeypatch.setattr(memory_mem0, "transport", httpx.MockTransport(broken))
    out, err = _call(client, tok, "memory_remember", content="Zoe moved to Lisbon.")
    assert err
    got = client.get(f"/v1/memories/{node}", headers=ADA).json()
    assert got["last_error"].startswith("mem0 did not answer") and got["last_error_at"] >= got["last_ok_at"]
    run(gw._memories_observe(ORG, h["id"], sid, run(gw._harness_vertex(h["id"])), {"user_text": "x", "model": "m"}, "y"))
    assert client.get(f"/v1/memories/{node}", headers=ADA).json()["last_error_at"] >= got["last_error_at"]
    # a connection refused again says so on the memories that live there
    monkeypatch.setattr(memory_mem0, "transport", httpx.MockTransport(real))
    r = client.put("/v1/plugs/mem0", headers=ADA, json={"secrets": {"api_key": "m0-wrong-key"}})
    assert r.status_code == 422
    assert "refused" in client.get(f"/v1/memories/{mid}", headers=ADA).json()["last_error"]
    assert client.put("/v1/plugs/mem0", headers=ADA, json={"secrets": {"api_key": KEY}}).json()["status"] == "connected"


# ── what a turn kept ─────────────────────────────────────────────────────────────────────────
def test_the_turn_says_what_was_remembered(client, per_person):
    hid, _ = per_person
    sid, tok = _session(hid, {"user": "fay@guests.example"})
    made, err = _call(client, tok, "memory_remember", content="Fay is vegetarian.")
    assert not err
    rid = "resp_" + uuid.uuid4().hex[:12]
    run(gw._resp_put(rid, {"id": rid, "status": "completed", "output": [], "_input": [{"content": "hi"}]},
                     ORG, sid, None, "completed", time.time(), True))
    run(gw._memories_observe(ORG, hid, sid, run(gw._harness_vertex(hid)), {"user_text": "I am vegetarian.", "model": "m"},
                             "Noted.", resp_id=rid))
    turn = run(gw._session_turns_data(sid))["turns"][0]
    # the record the agent kept is counted; mem0 is still drawing facts from the task, and says so
    assert turn["memory"] == {"remembered": 1, "records": [made["remembered"]["id"]], "pending": True}


def test_a_finished_task_on_an_engine_that_keeps_at_once_is_counted(client):
    mid = client.post("/v1/memories", headers=ADA, json={"provider": "fixture", "name": "At once"}).json()["id"]
    h = _agent(client, name="Fixture user", memory={"id": mid}, prompt="Keep notes for the team.").json()
    sid, _tok = _session(h["id"])
    rid = "resp_" + uuid.uuid4().hex[:12]
    run(gw._resp_put(rid, {"id": rid, "status": "completed", "output": [], "_input": [{"content": "hi"}]},
                     ORG, sid, None, "completed", time.time(), True))

    async def derive(self, m, episodes, writer):
        return {"records": [{"id": "hrec_derived1", "type": "fact"}, {"id": "hrec_ep", "type": "episode"}], "job": None}
    with pytest.MonkeyPatch.context() as mp_:
        mp_.setattr(memory_fixture.FixtureProvider, "observe", derive)
        run(gw._memories_observe(ORG, h["id"], sid, run(gw._harness_vertex(h["id"])), {"user_text": "x", "model": "m"}, "y", resp_id=rid))
    assert run(gw._session_turns_data(sid))["turns"][0]["memory"] == {"remembered": 1, "records": ["hrec_derived1"]}


# ── the list: search, recently used, who uses each ───────────────────────────────────────────
def test_the_list_searches_sorts_by_use_and_says_who_uses_each(client):
    a = _agent(client, name="Billing desk", prompt="Help each customer with billing.").json()
    b = _agent(client, name="Returns desk", prompt="Help each customer with returns.").json()
    found = client.get("/v1/memories", params={"q": "billing", "counts": "false"}, headers=ADA).json()["data"]
    assert [x["name"] for x in found] == ["Billing desk"]
    assert found[0]["used_by"] == [{"harness_id": a["id"], "name": "Billing desk"}] and found[0]["engine"] == "mem0"
    _, tok = _session(b["id"], {"user": "gus@example.com"})
    _call(client, tok, "memory_recall", query="anything")
    recent = client.get("/v1/memories", params={"sort": "recent", "counts": "false"}, headers=ADA).json()["data"]
    assert recent[0]["id"] == b["memory"]["id"] and recent[0]["last_used_at"]
    assert client.get("/v1/memories", params={"sort": "sideways"}, headers=ADA).status_code == 422
    # a key held to another workspace sees no agent of this one
    held = _key(client, ws="ws.elsewhere")
    seen = client.get("/v1/memories", params={"counts": "false"}, headers=held).json()["data"]
    assert all(x["used_by"] == [] for x in seen)


# ── New setup ────────────────────────────────────────────────────────────────────────────────
def test_the_builder_is_told_memory_is_the_platforms_and_its_save_provisions(client):
    inv = {"bases": {"claude-code": {"name": "Claude Code", "default": "m", "models": ["m"], "skills": True, "auto": True}}}
    assert "never write memory policy or mechanisms" in setup_builder.system(inv, "claude-code", "m", setup_builder.sx.Lang("", "", ""))
    schema = setup_builder.configure_schema(inv, "claude-code", "m", {})
    assert "memory_hint" in schema["properties"] and "memory_hint" not in schema["required"]
    cfg = setup_builder.settle({"name": "Guest help", "instructions": "You help each hotel guest with bookings. " * 8,
                                "example_task": "Book me a table.", "memory_hint": "each guest's dietary needs"},
                               inv, "claude-code", "m", {}, "help guests")
    assert cfg["memoryHint"] == "each guest's dietary needs"
    p = {"org": ORG, "member": "ada@example.com", "workspace": ""}
    hid = gw._rid("chrn")
    run(gw._setup_build_save(p, {**cfg, "model": ""}, hid, {}))
    v = run(gw._harness_vertex(hid))
    info = json.loads(v["memory_info"])
    assert info["engine"] == "mem0" and info["scope"] == "per_user" and v["memory_hint"] == "each guest's dietary needs"
    assert v["memory_default"] == info["id"]


# ── the instructions ─────────────────────────────────────────────────────────────────────────
def test_the_memory_section_says_the_rules_first(client, per_person):
    hid, _ = per_person
    sid, _ = _session(hid, {"user": "dana@guests.example"})
    hv = run(gw._harness_vertex(hid))
    seam = run(gw._memories_seam(hid, ORG, hv, sid))
    section, _ = run(gw.memory_tools.doc_section(seam, kept_after=True, person=True))
    for rule in (gw.memory_tools.RULE_RECALL, gw.memory_tools.RULE_KEPT, gw.memory_tools.RULE_REMEMBER,
                 gw.memory_tools.RULE_OWN, gw.memory_tools.RULE_PERSON):
        assert rule in section
    assert "dana@guests.example" not in section and "This person's memory" in section
    off, _ = run(gw.memory_tools.doc_section(seam, kept_after=False))
    assert gw.memory_tools.RULE_NOT_KEPT in off and gw.memory_tools.RULE_KEPT not in off


# ── the connection check: a real round trip, its probe never left behind ─────────────────────
def test_a_connection_writes_reads_back_and_deletes_a_probe(stub):
    before, n = dict(stub.mem), len(stub.calls)
    assert run(gw._memory_round_trip("mem0", KEY, "", ORG)) == ""
    deleted = [p for (m, p, _b) in stub.calls[n:] if m == "DELETE"]
    assert len(deleted) == 2 and deleted[-1] == "/v1/memories/", "the record, then the memory it was in"
    adds = [b for (m, p, b) in stub.calls if p == "/v3/memories/add/" and b["metadata"].get("hr_type") == "note"]
    probe_user = adds[-1]["user_id"]
    assert adds[-1]["messages"][0]["content"].startswith(memory_plane.PROBE_PREFIX)
    assert stub.mem == before and probe_user.startswith("hmem_00000000"), "the probe and its memory are gone"


def test_a_probe_that_cant_be_read_back_is_still_deleted_and_the_reason_is_plain(stub, monkeypatch):
    real = stub.__call__
    seen = []

    def no_read(req):
        seen.append((req.method, req.url.path))
        if req.method == "GET" and req.url.path.startswith("/v1/memories/") and req.url.path.count("/") == 4:
            return httpx.Response(404, json={"error": "Memory not found!"})
        return real(req)
    monkeypatch.setattr(memory_mem0, "transport", httpx.MockTransport(no_read))
    before = dict(stub.mem)
    why = run(gw._memory_round_trip("mem0", KEY, "", ORG))
    assert why.startswith("Mem0 took a record but couldn't give it back") and "connect it again" in why
    assert stub.mem == before and ("DELETE", "/v1/memories/") in seen


def test_an_engine_with_no_model_key_is_said_in_words(stub, monkeypatch):
    real = stub.__call__

    def no_model(req):
        if req.url.path == "/v3/memories/add/":
            return httpx.Response(500, json={"error": "The api_key client option must be set (OPENAI_API_KEY)"})
        return real(req)
    monkeypatch.setattr(memory_mem0, "transport", httpx.MockTransport(no_model))
    why = run(gw._memory_round_trip("mem0", KEY, "", ORG))
    assert why == (f"Mem0 answers, but it can't read with a model: it has no working model key. Run {memory_choice.START_COMMAND} "
                   "again, or give Mem0 a model key, then connect it.")


def test_a_probe_record_is_never_an_answer(client):
    mid = client.post("/v1/memories", headers=ADA, json={"provider": "fixture", "name": "Probe test"}).json()["id"]
    for title in (memory_plane.PROBE_PREFIX + " connection check", "Real fact about probes"):
        run(memory_plane.PROVIDERS["fixture"].remember(mid, {"type": "note", "title": title, "content": [], "attributes": {}},
                                                       {"kind": "member", "id": "ada@example.com"}))
    found = client.post(f"/v1/memories/{mid}/recall", headers=ADA,
                        json={"filters": {"field": "status", "op": "eq", "value": "active"}}).json()["results"]
    listed = client.get(f"/v1/memories/{mid}/records", headers=ADA).json()["data"]
    assert [x["record"]["title"] for x in found] == ["Real fact about probes"]
    assert [x["title"] for x in listed] == ["Real fact about probes"]


# ── engines found beside this instance ───────────────────────────────────────────────────────
def test_discovery_takes_no_address(client):
    for body in ({"url": "http://169.254.169.254"}, {"host": "evil"}, {"port": 22}, ["x"]):
        r = client.post("/v1/memory-services/discover", headers=ADA, json=body)
        assert r.status_code == 422, body
    assert client.post("/v1/memory-services/discover?host=evil", headers=ADA).status_code == 422


def test_discovery_is_refused_on_a_shared_pool_and_to_a_key(client, monkeypatch):
    assert client.post("/v1/memory-services/discover", headers=_key(client)).status_code == 403
    monkeypatch.setenv("HR_POOL_AUTH", "cloud")
    r = client.post("/v1/memory-services/discover", headers=ADA)
    assert r.status_code == 403 and "one operator" in r.text
    with pytest.raises(Exception) as refused:
        run(gw._memory_discover(ORG, "default"))
    assert refused.value.status_code == 403


def test_discovery_tries_the_fixed_names_only_and_connects_only_what_needs_no_key(client, monkeypatch):
    asked: list[str] = []

    def answer(name):
        def go(req):
            asked.append(f"{req.url.host}:{req.url.port}")
            if name == "mem0":
                return httpx.Response(401, json={"detail": "Missing API key"})
            if name == "graphiti":
                raise httpx.ConnectError("no such host")
            return httpx.Response(200, json={"banks": []} if name == "hindsight" else {"version": "1"})
        return go
    for mod, name in ((memory_mem0, "mem0"), (memory_graphiti, "graphiti"), (memory_hindsight, "hindsight"), (memory_reme, "reme")):
        monkeypatch.setattr(mod, "transport", httpx.MockTransport(answer(name)))
    tried = []

    async def round_trip(engine, key, base, org):
        tried.append((engine, base))
        return ""
    monkeypatch.setattr(gw, "_memory_round_trip", round_trip)
    ws = {**ADA, "x-harness-workspace": "ws.found"}
    got = {x["engine"]: x for x in client.post("/v1/memory-services/discover", headers=ws).json()["data"]}
    assert set(asked) <= {"mem0:8000", "graphiti:8000", "hindsight:8888", "reme:2333"} and asked
    assert got["hindsight"]["state"] == "connected" and got["reme"]["state"] == "connected"
    assert got["mem0"]["state"] == "running" and "up.sh" in got["mem0"]["message"]
    assert got["graphiti"]["state"] == "not_running"
    assert tried == [("hindsight", "http://hindsight:8888"), ("reme", "http://reme:2333")]
    plugs = {p["type"]: p["status"] for p in client.get("/v1/plugs?kind=memory", headers=ws).json()["plugs"]}
    assert plugs.get("hindsight") == "connected" and plugs.get("reme") == "connected" and plugs.get("mem0") != "connected"


def test_the_fixed_names_are_the_bundled_stacks_own():
    compose = open(os.path.join(os.path.dirname(gw.__file__), "..", "deploy", "memories", "docker-compose.yml")).read()
    for engine, url in gw._MEMORY_STACK.items():
        assert f"Address: {url}" in compose, (engine, url)
