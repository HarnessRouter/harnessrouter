"""Memories (the Harness Memories sub-protocol), driven through the public surface with the fixture
provider behind it: the tree and its grants, the cutoff, the walk in both directions, references
that cross the tree, versions and time, the two ways to write and to remove, recall and its honesty
fields, named and free queries, an extension type, consolidation runs.

Two people act throughout. Ada creates the tree; Ben holds only what he is granted. What Ben may not
read must be absent from every answer he gets, not merely refused when he asks for it."""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import memory_fixture  # noqa: E402
import memory_plane  # noqa: E402

ORG = "memorg"


def _h(member):
    return {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": member}


class Who:
    def __init__(self, c, member):
        self.c, self.h = c, _h(member)

    def __getattr__(self, m):
        def call(path, **kw):
            kw["headers"] = {**self.h, **(kw.get("headers") or {})}
            return getattr(self.c, m)(path, **kw)
        return call


@pytest.fixture(scope="module")
def people():
    # this server keeps no memory of its own: the test connects the fixture provider, as a
    # deployment connects a real one
    memory_plane.PROVIDERS["fixture"] = memory_fixture.FixtureProvider()
    with TestClient(app.app) as c:
        yield Who(c, "ada@example.com"), Who(c, "ben@example.com")


@pytest.fixture(scope="module")
def tree(people):
    """company > sales > acme, and company > ada-private (restricted)."""
    ada, _ = people
    mk = lambda **b: ada.post("/v1/memories", json={"provider": "fixture", **b}).json()   # noqa: E731
    company = mk(name="Company", description="What everyone here should know.")
    sales = mk(name="Sales", description="Accounts and pricing decisions.", parent_id=company["id"])
    acme = mk(name="Acme", description="Everything about the Acme account.", parent_id=sales["id"])
    private = mk(name="Ada private", description="Ada's own notes.", parent_id=company["id"], restricted=True)
    return {"company": company["id"], "sales": sales["id"], "acme": acme["id"], "private": private["id"]}


def _code(r):
    return r.json()["error"]["code"]


def test_the_capability_is_declared_and_a_provider_describes_itself(people):
    ada, _ = people
    assert ada.get("/v1/uhp").json()["capabilities"]["memories"] is True
    caps = ada.get("/v1/memories/providers").json()["data"]
    fx = next(p for p in caps if p["id"] == "fixture")
    assert fx["isolation"] == "container" and fx["recall"]["signals"] == ["query", "text", "filters"]
    assert fx["history"]["content"] == "versions" and fx["consolidate"] == "runs"


def test_a_memory_is_a_node_with_a_parent_and_its_creator_holds_it(people, tree):
    ada, _ = people
    m = ada.get(f"/v1/memories/{tree['acme']}").json()
    assert m["object"] == "memory" and m["parent_id"] == tree["sales"]
    assert m["ancestors"] == [tree["company"], tree["sales"]]
    assert m["privileges"] == ["read", "write", "create", "delete"] and m["restricted"] is False
    # no provider named and none inherited is refused: this server keeps no memory of its own
    r = ada.post("/v1/memories", json={"name": "Nowhere"})
    assert r.status_code == 422 and _code(r) == "memory_invalid"
    # a child takes its parent's provider
    kid = ada.post("/v1/memories", json={"name": "Renewals", "parent_id": tree["acme"]}).json()
    assert kid["provider"] == "fixture"
    assert ada.delete(f"/v1/memories/{kid['id']}").json()["memories"] == [kid["id"]]


def test_what_a_caller_holds_nothing_on_does_not_exist_for_it(people, tree):
    _, ben = people
    for mid in tree.values():
        r = ben.get(f"/v1/memories/{mid}")
        assert r.status_code == 404 and _code(r) == "memory_not_found"
    assert ben.get("/v1/memories").json()["data"] == []
    r = ben.post(f"/v1/memories/{tree['acme']}/recall", json={"query": "anything"})
    assert r.status_code == 404
    # a made-up id answers the same way: unknown and forbidden are one answer
    assert ben.get("/v1/memories/hmem_" + "0" * 32).json() == ben.get(f"/v1/memories/{tree['acme']}").json()


def test_a_grant_flows_down_and_the_caller_enters_where_it_was_granted(people, tree):
    ada, ben = people
    g = ada.post(f"/v1/memories/{tree['sales']}/grants",
                 json={"principal": "member:ben@example.com", "privileges": ["read"]}).json()
    assert g["object"] == "memory.grant" and g["privileges"] == ["read"]
    # Ben enters at Sales: Company, which he holds nothing on, is not a root of his and not an ancestor he sees
    mine = ben.get("/v1/memories").json()["data"]
    assert [m["id"] for m in mine] == [tree["sales"]]
    assert mine[0]["parent_id"] is None and mine[0]["ancestors"] == [] and mine[0]["privileges"] == ["read"]
    # the grant reaches the child
    acme = ben.get(f"/v1/memories/{tree['acme']}").json()
    assert acme["privileges"] == ["read"] and acme["ancestors"] == [tree["sales"]]
    # read is not write
    r = ben.post(f"/v1/memories/{tree['acme']}/records", json={"type": "fact", "content": "x"})
    assert r.status_code == 403 and _code(r) == "memory_forbidden"
    # the grants of a node name where each one sits
    rows = ada.get(f"/v1/memories/{tree['acme']}/grants").json()["data"]
    assert [(x["memory_id"], x["inherited"]) for x in rows] == [(tree["sales"], True)]


def test_a_restricted_memory_stops_what_flows_from_above(people, tree):
    ada, ben = people
    g = ada.post(f"/v1/memories/{tree['company']}/grants",
                 json={"principal": "member:ben@example.com", "privileges": ["read", "write"]}).json()
    assert ben.get(f"/v1/memories/{tree['company']}").status_code == 200
    assert ben.get(f"/v1/memories/{tree['private']}").status_code == 404        # the cutoff
    kids = [m["id"] for m in ben.get(f"/v1/memories?parent={tree['company']}").json()["data"]]
    assert kids == [tree["sales"]]
    assert tree["private"] not in [m["id"] for m in ben.get(f"/v1/memories?ancestor={tree['company']}").json()["data"]]
    ada.delete(f"/v1/memories/{tree['company']}/grants/{g['id']}")
    assert ben.get(f"/v1/memories/{tree['company']}").status_code == 404


def test_the_two_ways_to_write_and_a_writer_the_client_cannot_supply(people, tree):
    ada, _ = people
    eps = ada.post(f"/v1/memories/{tree['acme']}/observe", json={"episodes": [
        {"content": "Dana from Acme said they renew in March and want the annual discount kept."},
        {"content": "Acme asked whether SSO is included in the team plan."}]}).json()["data"]
    assert [e["type"] for e in eps] == ["episode", "episode"]
    r = ada.post(f"/v1/memories/{tree['acme']}/records", json={
        "type": "fact", "content": "Acme renews in March.", "attributes": {"account": "acme"},
        "written_by": {"kind": "member", "id": "someone-else"},
        "references": [{"rel": "derived_from", "record_id": eps[0]["id"]}]})
    fact = r.json()
    assert fact["object"] == "memory.record" and fact["version"] == 1 and fact["status"] == "active"
    assert fact["written_by"] == {"kind": "member", "id": "ada@example.com"} and fact["trust"] == "untrusted"
    assert fact["references"] == [{"rel": "derived_from", "record_id": eps[0]["id"],
                                   "memory_id": tree["acme"], "available": True}]
    tree["fact"], tree["episode"] = fact["id"], eps[0]["id"]


def test_recall_acts_on_one_memory_and_says_where_the_caller_can_go(people, tree):
    ada, ben = people
    r = ada.post(f"/v1/memories/{tree['acme']}/recall", json={"query": "when does Acme renew?"}).json()
    assert r["results"][0]["record"]["content"].startswith(("Acme renews", "Dana from Acme"))
    assert r["results"][0]["why"] == ["query"] and r["abstain"] is False and r["degraded"] == []
    assert r["parent"]["id"] == tree["sales"] and r["children"] == []
    # one memory: the parent holds none of the child's records
    up = ada.post(f"/v1/memories/{tree['sales']}/recall", json={"query": "when does Acme renew?"}).json()
    assert up["results"] == [] and up["abstain"] is True
    assert [c["id"] for c in up["children"]] == [tree["acme"]] and up["parent"]["id"] == tree["company"]
    assert up["children"][0]["description"] == "Everything about the Acme account."
    # Ben reads Sales and below: his walk up ends where his reach does, and looks like a root
    b = ben.post(f"/v1/memories/{tree['sales']}/recall", json={"text": "pricing"}).json()
    assert "parent" not in b and [c["id"] for c in b["children"]] == [tree["acme"]]


def test_the_three_signals_and_what_a_provider_did_not_do(people, tree):
    ada, _ = people
    rec = lambda **b: ada.post(f"/v1/memories/{tree['acme']}/recall", json=b).json()   # noqa: E731
    assert [x["record"]["type"] for x in rec(text="sso")["results"]] == ["episode"]
    f = rec(filters={"field": "attributes.account", "op": "eq", "value": "acme"})
    assert [x["record"]["id"] for x in f["results"]] == [tree["fact"]] and f["results"][0]["why"] == ["filters"]
    both = rec(query="when acme renews", text="march", types=["fact"])
    assert [x["record"]["id"] for x in both["results"]] == [tree["fact"]] and both["results"][0]["why"] == ["text", "query"]
    assert rec(query="what is the weather on Mars")["abstain"] is True
    assert rec(query="renew", depth=3)["degraded"] == ["depth:capped_at_0"]
    r = ada.post(f"/v1/memories/{tree['acme']}/recall", json={})
    assert r.status_code == 422


def test_nothing_is_overwritten(people, tree):
    ada, _ = people
    base = f"/v1/memories/{tree['acme']}/records/{tree['fact']}"
    before = ada.get(base).json()["time"]["written_at"]
    v2 = ada.patch(base, json={"content": "Acme renews in April."}).json()
    assert v2["version"] == 2 and v2["supersedes"] == 1 and v2["id"] == tree["fact"]
    hist = ada.get(base + "/history").json()["data"]
    assert [(h["version"], h["status"]) for h in hist] == [(1, "superseded"), (2, "active")]
    assert hist[0]["time"]["invalidated_at"] == hist[1]["time"]["written_at"]
    # as of the first write, the memory still says March
    assert ada.get(base, params={"as_of": before}).json()["content"] == "Acme renews in March."
    assert ada.post(f"/v1/memories/{tree['acme']}/recall",
                    json={"text": "april", "as_of": before}).json()["results"] == []
    snap = ada.post(f"/v1/memories/{tree['acme']}/snapshots", json={"name": "before-forgetting"}).json()
    assert snap["object"] == "memory.snapshot" and snap["at"] > before
    # forget closes it and keeps the trace
    gone = ada.delete(base).json()
    assert gone["status"] == "forgotten"
    assert ada.post(f"/v1/memories/{tree['acme']}/recall", json={"text": "april"}).json()["results"] == []
    assert len(ada.get(base + "/history").json()["data"]) == 2
    assert ada.get(base, params={"as_of": snap["at"]}).json()["content"] == "Acme renews in April."


def test_a_reference_crosses_the_tree_and_resolves_for_the_reader(people, tree):
    ada, ben = people
    secret = ada.post(f"/v1/memories/{tree['private']}/records",
                      json={"type": "note", "content": "Dana told me the budget is frozen."}).json()
    shared = ada.post(f"/v1/memories/{tree['sales']}/records", json={
        "type": "fact", "content": "Acme's budget is under review.",
        "references": [{"rel": "derived_from", "memory_id": tree["private"], "record_id": secret["id"]}]}).json()
    assert shared["references"][0]["available"] is True
    seen = ben.get(f"/v1/memories/{tree['sales']}/records/{shared['id']}").json()
    assert seen["content"] == "Acme's budget is under review."
    assert seen["references"] == [{"memory_id": tree["private"], "record_id": secret["id"], "available": False}]
    assert "Dana" not in str(ben.post(f"/v1/memories/{tree['sales']}/recall", json={"text": "budget"}).json())


def test_erase_reports_what_it_could_not_reach(people, tree):
    ada, ben = people
    ada.post(f"/v1/memories/{tree['sales']}/grants", json={"principal": "member:ben@example.com", "privileges": ["read", "write"]})
    r = ben.post(f"/v1/memories/{tree['acme']}/erase", json={"record_ids": [tree["episode"]]})
    assert r.status_code == 403                                   # erase is `delete`, and write is not it
    derived = ada.post(f"/v1/memories/{tree['acme']}/records", json={
        "type": "fact", "content": "Acme wants the discount kept.",
        "references": [{"rel": "derived_from", "record_id": tree["episode"]}]}).json()
    out = ada.post(f"/v1/memories/{tree['acme']}/erase", json={"record_ids": [tree["episode"]]}).json()
    # two records were derived from that episode: the new one, and the forgotten fact whose history
    # still says what the episode said. Both are named; neither is silently kept.
    assert out == {"object": "memory.erasure", "erased": [tree["episode"]],
                   "unreachable": sorted([derived["id"], tree["fact"]])}
    assert ada.get(f"/v1/memories/{tree['acme']}/records/{tree['episode']}").status_code == 404
    assert ada.get(f"/v1/memories/{tree['acme']}/records/{tree['episode']}/history").status_code == 404


def test_a_named_query_and_a_free_one_stay_inside_the_memory(people, tree):
    ada, ben = people
    q = ada.put(f"/v1/memories/{tree['acme']}/queries/by_type", json={
        "description": "Records of one type.", "language": "fixture-filter",
        "params": {"type": "object", "properties": {"t": {"type": "string"}}, "required": ["t"]},
        "body": '{"field": "type", "op": "eq", "value": "{t}"}'}).json()
    assert q["name"] == "by_type" and q["requires"] == "read"
    assert [x["name"] for x in ben.get(f"/v1/memories/{tree['acme']}/queries").json()["data"]] == ["by_type"]
    res = ben.post(f"/v1/memories/{tree['acme']}/queries/by_type", json={"params": {"t": "fact"}}).json()
    assert res["results"] and all(x["record"]["type"] == "fact" for x in res["results"])
    assert ben.post(f"/v1/memories/{tree['acme']}/queries/by_type", json={}).status_code == 422
    free = ben.post(f"/v1/memories/{tree['acme']}/query", json={
        "language": "fixture-filter", "statement": '{"field": "type", "op": "in", "value": ["fact", "note", "episode"]}'}).json()
    ids = {x["record"]["memory_id"] for x in free["results"]}
    assert ids == {tree["acme"]}                                   # every record there, and none from anywhere else
    r = ben.post(f"/v1/memories/{tree['private']}/query", json={"language": "fixture-filter", "statement": "{}"})
    assert r.status_code == 404
    r = ben.put(f"/v1/memories/{tree['company']}/queries/x", json={"language": "fixture-filter", "body": "{}"})
    assert r.status_code == 404


def test_an_extension_type_carries_its_own_operations_under_the_memorys_access(people, tree):
    ada, ben = people
    types = ada.get("/v1/memories/types").json()["data"]
    assert [t["type"] for t in types if t.get("core")] == ["episode", "fact", "note", "procedure", "link"]
    ext = next(t for t in types if t["type"] == "x.fixture.counter")
    assert {o["name"]: o["requires"] for o in ext["operations"]} == {"increment": "write", "peek": "read"}
    c = ada.post(f"/v1/memories/{tree['company']}/records",
                 json={"type": "x.fixture.counter", "content": "deals closed", "attributes": {"n": 2}}).json()
    op = f"/v1/memories/{tree['company']}/records/{c['id']}/operations"
    assert ada.post(op + "/increment", json={"by": 3}).json()["result"] == {"n": 5, "version": 2}
    ada.post(f"/v1/memories/{tree['company']}/grants", json={"principal": "member:ben@example.com", "privileges": ["read"]})
    assert ben.post(op + "/peek", json={}).json()["result"] == {"n": 5}
    assert ben.post(op + "/increment", json={}).status_code == 403
    # found by recall through its text like any record
    assert [x["record"]["id"] for x in ben.post(f"/v1/memories/{tree['company']}/recall",
                                                 json={"text": "deals"}).json()["results"]] == [c["id"]]


def test_a_consolidation_is_a_run_one_can_read_bound_and_revert(people, tree):
    ada, _ = people
    base = f"/v1/memories/{tree['sales']}"
    ada.post(base + "/observe", json={"episodes": [{"content": f"call {i}: pricing objection"} for i in range(3)]})
    run = ada.post(base + "/consolidations", json={"budget": {"limit": 2}}).json()
    assert run["object"] == "memory.consolidation" and run["status"] == "stopped"
    assert run["budget"]["exhausted"] is True and run["changes"]["created"] == 2 and run["read"]["episodes"] == 2
    assert run["written_by"] == {"kind": "consolidator", "id": "fixture"}
    changes = ada.get(base + f"/consolidations/{run['id']}/changes").json()["data"]
    assert len(changes) == 2 and all(c["record"]["written_by"]["kind"] == "consolidator" for c in changes)
    nxt = ada.post(base + "/consolidations", json={}).json()          # resumes after what was read
    assert nxt["status"] == "completed" and nxt["changes"]["created"] == 1
    assert [r["id"] for r in ada.get(base + "/consolidations").json()["data"]] == [nxt["id"], run["id"]]
    made = changes[0]["record"]["id"]
    ada.post(base + f"/consolidations/{run['id']}/revert")
    assert ada.get(base + f"/records/{made}").json()["status"] == "forgotten"
    assert len(ada.get(base + f"/records/{made}/history").json()["data"]) == 1   # reverted by closing, not by removing


def test_a_move_carries_the_subtree_and_a_delete_takes_it(people, tree):
    ada, _ = people
    region = ada.post("/v1/memories", json={"name": "EMEA", "parent_id": tree["company"]}).json()
    r = ada.put(f"/v1/memories/{tree['sales']}", json={"parent_id": tree["acme"]})
    assert r.status_code == 422 and _code(r) == "memory_invalid"          # under its own child
    moved = ada.put(f"/v1/memories/{tree['sales']}", json={"parent_id": region["id"]}).json()
    assert moved["ancestors"] == [tree["company"], region["id"]]
    assert ada.get(f"/v1/memories/{tree['acme']}").json()["ancestors"] == [tree["company"], region["id"], tree["sales"]]
    gone = ada.delete(f"/v1/memories/{region['id']}").json()["memories"]
    assert set(gone) == {region["id"], tree["sales"], tree["acme"]}
    assert ada.get(f"/v1/memories/{tree['acme']}").status_code == 404
