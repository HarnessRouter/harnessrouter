"""mem0 as a memory provider, against the real service. Skipped unless MEM0_API_KEY is set: it
writes into that account (under throwaway memory ids) and removes what it wrote.

    MEM0_API_KEY=... python -m pytest gateway/tests/test_memory_mem0_live.py -q -s

It drives the gateway's own routes, so what is checked is the protocol's behaviour with mem0 behind
it: the workspace's key is connected through the plug registry, never passed per call."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402

KEY = os.environ.get("MEM0_API_KEY", "")
pytestmark = pytest.mark.skipif(not KEY, reason="MEM0_API_KEY is not set")
ORG = "mem0live"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
BEN = {**ADA, "x-harness-member": "ben@example.com"}


@pytest.fixture(scope="module")
def c():
    with TestClient(gw.app) as client:
        yield client


@pytest.fixture(scope="module")
def tree(c):
    r = c.put("/v1/plugs/mem0", headers=ADA, json={"secrets": {"api_key": KEY}})
    assert r.status_code == 200 and r.json()["status"] == "connected", r.text
    assert KEY not in r.text
    mk = lambda **b: c.post("/v1/memories", headers=ADA, json={"provider": "mem0", **b}).json()   # noqa: E731
    team = mk(name="Sales (live test)", description="Accounts and pricing decisions.")
    acme = mk(name="Acme (live test)", description="The Acme account.", parent_id=team["id"])
    ids = {"team": team["id"], "acme": acme["id"]}
    yield ids
    c.delete(f"/v1/memories/{team['id']}", headers=ADA)          # drops both scopes at mem0


def _wait_job(c, mid, job, seconds=90):
    for _ in range(seconds // 2):
        j = c.get(f"/v1/memories/{mid}/jobs/{job}", headers=ADA).json()
        if j["status"] != "pending":
            return j
        time.sleep(2)
    raise AssertionError("mem0 did not finish the job")


def test_a_refused_key_is_found_out_at_connect():
    with TestClient(gw.app) as client:
        other = {**ADA, "x-harness-workspace": "ws-badkey"}
        r = client.put("/v1/plugs/mem0", headers=other, json={"secrets": {"api_key": "m0-not-a-real-key"}})
        assert r.status_code == 200 and r.json()["status"] == "needs_auth" and "refused the key" in r.json()["attention"]
        r = client.post("/v1/memories", headers=other, json={"provider": "mem0", "name": "x"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "memory_unavailable"


def test_the_provider_says_what_it_is(c, tree):
    caps = next(p for p in c.get("/v1/memories/providers", headers=ADA).json()["data"] if p["id"] == "mem0")
    assert caps["isolation"] == "enforced_filter" and caps["recall"]["abstain"] is False
    assert caps["observe"] == {"keeps_episodes": False, "answers": "job"} and caps["consolidate"] is False


def test_remember_recall_revise_history_and_as_of(c, tree):
    acme = tree["acme"]
    fact = c.post(f"/v1/memories/{acme}/records", headers=ADA, json={
        "type": "fact", "content": "Acme renews in March and wants the annual discount kept.",
        "attributes": {"account": "acme"}}).json()
    assert fact["status"] == "active" and fact["version"] == 1 and fact["memory_id"] == acme
    assert fact["written_by"] == {"kind": "member", "id": "ada@example.com"} and fact["attributes"] == {"account": "acme"}
    tree["fact"], t1 = fact["id"], fact["time"]["written_at"]
    time.sleep(2)                                              # mem0 indexes a moment after it stores

    hit = c.post(f"/v1/memories/{acme}/recall", headers=ADA, json={"query": "when does Acme renew?"}).json()
    assert hit["results"][0]["record"]["id"] == fact["id"] and "query" in hit["results"][0]["why"]
    assert hit["abstain"] is False and hit["parent"]["id"] == tree["team"]
    # one memory: the parent holds none of it
    assert c.post(f"/v1/memories/{tree['team']}/recall", headers=ADA, json={"query": "when does Acme renew?"}).json()["results"] == []
    # words alone, and a field
    assert [x["record"]["id"] for x in c.post(f"/v1/memories/{acme}/recall", headers=ADA, json={"text": "discount"}).json()["results"]] == [fact["id"]]
    f = c.post(f"/v1/memories/{acme}/recall", headers=ADA, json={
        "query": "renewal", "filters": {"field": "attributes.account", "op": "eq", "value": "acme"}}).json()
    assert [x["record"]["id"] for x in f["results"]] == [fact["id"]] and f["degraded"] == []
    g = c.post(f"/v1/memories/{acme}/recall", headers=ADA, json={
        "query": "renewal", "filters": {"field": "attributes.account", "op": "in", "value": ["acme", "initech"]}}).json()
    assert [x["record"]["id"] for x in g["results"]] == [fact["id"]] and g["degraded"] == ["filters:applied_after_ranking"]
    assert c.post(f"/v1/memories/{acme}/recall", headers=ADA, json={"query": "renewal", "as_of": t1}).json()["degraded"] == ["as_of:not_supported"]

    time.sleep(1)
    v2 = c.patch(f"/v1/memories/{acme}/records/{fact['id']}", headers=ADA,
                 json={"content": "Acme renews in April and wants the annual discount kept."}).json()
    assert v2["version"] == 2 and v2["supersedes"] == 1 and v2["id"] == fact["id"]
    hist = c.get(f"/v1/memories/{acme}/records/{fact['id']}/history", headers=ADA).json()["data"]
    assert [(h["version"], h["status"]) for h in hist] == [(1, "superseded"), (2, "active")]
    assert "March" in hist[0]["content"] and "April" in hist[1]["content"]
    assert "March" in c.get(f"/v1/memories/{acme}/records/{fact['id']}", headers=ADA, params={"as_of": hist[0]["time"]["written_at"]}).json()["content"]


def test_a_record_of_one_memory_cannot_be_read_through_another(c, tree):
    r = c.get(f"/v1/memories/{tree['team']}/records/{tree['fact']}", headers=ADA)
    assert r.status_code == 404 and r.json()["error"]["code"] == "memory_record_not_found"
    assert c.patch(f"/v1/memories/{tree['team']}/records/{tree['fact']}", headers=ADA, json={"content": "x"}).status_code == 404
    assert c.get(f"/v1/memories/{tree['acme']}", headers=BEN).status_code == 404          # and Ben holds nothing


def test_observe_answers_a_job_and_mem0_keeps_facts_not_the_episode(c, tree):
    r = c.post(f"/v1/memories/{tree['acme']}/observe", headers=ADA, json={"episodes": [{"content": {
        "user": "Dana at Acme told me their budget owner is now Priya, and they prefer invoices by email.",
        "assistant": "Noted."}, "attributes": {"session_id": "sess_live"}}]})
    assert r.status_code == 202 and r.json()["data"] == [] and r.json()["job"]["status"] == "pending"
    done = _wait_job(c, tree["acme"], r.json()["job"]["id"])
    assert done["status"] == "completed" and done["data"], done
    assert all(x["type"] == "fact" and x["written_by"]["kind"] == "provider" for x in done["data"])
    assert all(x["attributes"].get("session_id") == "sess_live" for x in done["data"])
    assert "Priya" in json.dumps(done["data"])
    # the job of one memory is not readable through another
    assert c.get(f"/v1/memories/{tree['team']}/jobs/{r.json()['job']['id']}", headers=ADA).status_code == 404
    eps = c.get(f"/v1/memories/{tree['acme']}/records?type=episode", headers=ADA).json()["data"]
    assert eps == []


def test_forget_closes_and_erase_says_what_mem0_still_holds(c, tree):
    acme, rid = tree["acme"], tree["fact"]
    gone = c.delete(f"/v1/memories/{acme}/records/{rid}", headers=ADA).json()
    assert gone["status"] == "forgotten"
    time.sleep(2)
    assert rid not in [x["record"]["id"] for x in c.post(f"/v1/memories/{acme}/recall", headers=ADA, json={"query": "Acme renews"}).json()["results"]]
    assert c.get(f"/v1/memories/{acme}/records/{rid}", headers=ADA).json()["status"] == "forgotten"     # still there, closed
    assert rid in [x["id"] for x in c.get(f"/v1/memories/{acme}/records?include=all", headers=ADA).json()["data"]]
    out = c.post(f"/v1/memories/{acme}/erase", headers=ADA, json={"record_ids": [rid]}).json()
    assert out["erased"] == [rid] and out["unreachable"] == [rid]      # mem0 still serves its history
    assert c.get(f"/v1/memories/{acme}/records/{rid}", headers=ADA).status_code == 404


def test_an_agent_holds_a_mem0_memory_as_tools(c, tree):
    hid = c.post("/v1/harnesses", headers=ADA, json={"name": "Seller", "base": "claude-code"}).json()["id"]
    r = c.put(f"/v1/harnesses/{hid}/memories", headers=ADA, json={"memories": [
        {"memory_id": tree["team"], "access": "read"}, {"memory_id": tree["acme"], "access": "write", "default": True}]})
    assert r.status_code == 200, r.text
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    tok = gw._mint_hosted_cred(hid, sid, gw._hosted_secret_key(hid, "mcp.memories"))

    def call(name, **args):
        res = c.post("/v1/mcp/memories", headers={"authorization": f"Bearer {tok}"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}).json()["result"]
        return res["content"][0]["text"], res["isError"]

    names = [t["name"] for t in c.post("/v1/mcp/memories", headers={"authorization": f"Bearer {tok}"},
                                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]]
    assert "memory_recall" in names and "memory_remember" in names and "memory_query" not in names   # mem0 runs no free query
    text, err = call("memory_remember", content="Acme's procurement contact is Lee.")
    assert not err and json.loads(text)["remembered"]["written_by"] == {"kind": "harness", "id": hid}
    for _ in range(10):                                        # mem0 indexes a moment after it stores
        time.sleep(2)
        text, err = call("memory_recall", memory=tree["acme"], query="who is the procurement contact at Acme?")
        found = [x["record"]["content"] for x in json.loads(text)["results"]]
        if any("Lee" in x for x in found):
            break
    assert not err and any("Lee" in x for x in found), found
    assert json.loads(text)["parent"]["id"] == tree["team"]
    text, err = call("memory_list", memory=tree["team"])
    assert not err and [k["id"] for k in json.loads(text)["children"]] == [tree["acme"]]
