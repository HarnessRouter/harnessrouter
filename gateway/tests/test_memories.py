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


def test_who_acts_on_a_memory_is_one_vocabulary(people, tree):
    ada, _ = people
    url = f"/v1/memories/{tree['acme']}/grants"
    # a grant is held by a member (a person or an agent, the same kind) or a group; a server's own kind is x.-prefixed
    for who in ("member:cy@example.com", "member:chrn_1", "group:sales", "x.team:blue"):
        g = ada.post(url, json={"principal": who, "privileges": ["read"]})
        assert g.status_code == 200, (who, g.text)
        ada.delete(f"{url}/{g.json()['id']}")
    # a provider writes but holds no grant, and a kind nobody defined is refused, not stored
    for who in ("provider:mem0", "harness:chrn_1", "user:cy@example.com", "workspace:w1", "key:k1", "nobody"):
        r = ada.post(url, json={"principal": who, "privileges": ["read"]})
        assert r.status_code == 422 and _code(r) == "memory_invalid", who
    # the writer of a record is the same identity a grant would name
    rec = ada.post(f"/v1/memories/{tree['acme']}/records", json={"type": "note", "content": "who wrote this"}).json()
    w = rec["written_by"]
    assert w == {"kind": "member", "id": "ada@example.com", "type": "human"}
    assert ada.post(url, json={"principal": f"{w['kind']}:{w['id']}", "privileges": ["read"]}).status_code == 200
    ada.delete(f"/v1/memories/{tree['acme']}/records/{rec['id']}")


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
    assert fact["written_by"] == {"kind": "member", "id": "ada@example.com", "type": "human"} and fact["trust"] == "untrusted"
    assert fact["references"] == [{"rel": "derived_from", "record_id": eps[0]["id"],
                                   "memory_id": tree["acme"], "available": True}]
    tree["fact"], tree["episode"] = fact["id"], eps[0]["id"]


def test_a_question_searches_the_subtree_and_each_answer_names_where_it_is(people, tree):
    ada, ben = people
    r = ada.post(f"/v1/memories/{tree['acme']}/recall", json={"query": "when does Acme renew?"}).json()
    assert r["results"][0]["record"]["content"][0]["text"].startswith(("Acme renews", "Dana from Acme"))
    assert r["results"][0]["why"] == ["query"] and r["abstain"] is False and r["degraded"] == []
    assert r["results"][0]["memory"] == {"id": tree["acme"], "name": "Acme"}
    assert r["parent"]["id"] == tree["sales"] and r["children"] == []
    # asked two levels up, the same records are found, and each says which memory holds it: the
    # place to walk from
    top = ada.post(f"/v1/memories/{tree['company']}/recall", json={"query": "when does Acme renew?"}).json()
    assert top["abstain"] is False and {x["memory"]["id"] for x in top["results"]} == {tree["acme"]}
    assert {c["id"] for c in top["children"]} == {tree["sales"], tree["private"]}
    # depth bounds how far below: 0 is this memory alone, 1 its children
    alone = ada.post(f"/v1/memories/{tree['company']}/recall", json={"query": "when does Acme renew?", "depth": 0}).json()
    assert alone["results"] == [] and alone["abstain"] is True
    one = ada.post(f"/v1/memories/{tree['company']}/recall", json={"query": "when does Acme renew?", "depth": 1}).json()
    assert one["results"] == []
    assert ada.post(f"/v1/memories/{tree['sales']}/recall", json={"query": "when does Acme renew?", "depth": 1}).json()["results"]
    assert ada.post(f"/v1/memories/{tree['sales']}/recall", json={"query": "x", "depth": -1}).status_code == 422
    # it never looks up: a child does not find what its parent holds
    ada.post(f"/v1/memories/{tree['sales']}/records", json={"type": "fact", "content": "The sales kickoff is in Lisbon."})
    assert ada.post(f"/v1/memories/{tree['acme']}/recall", json={"text": "Lisbon"}).json()["results"] == []
    # Ben reads Sales and below: his walk up ends where his reach does, and looks like a root
    b = ben.post(f"/v1/memories/{tree['sales']}/recall", json={"text": "pricing"}).json()
    assert "parent" not in b and [c["id"] for c in b["children"]] == [tree["acme"]]


def test_a_question_never_searches_what_the_caller_may_not_read(people, tree):
    ada, ben = people
    ada.post(f"/v1/memories/{tree['private']}/records", json={"type": "note", "content": "Zanzibar offsite budget is secret."})
    deep = ada.post("/v1/memories", json={"name": "Shared corner", "parent_id": tree["private"]}).json()
    ada.post(f"/v1/memories/{deep['id']}/records", json={"type": "note", "content": "Zanzibar flights are booked."})
    g = ada.post(f"/v1/memories/{tree['company']}/grants",
                 json={"principal": "member:ben@example.com", "privileges": ["read"]}).json()
    ask = lambda who: who.post(f"/v1/memories/{tree['company']}/recall", json={"text": "Zanzibar"}).json()   # noqa: E731
    assert {x["memory"]["id"] for x in ask(ada)["results"]} == {tree["private"], deep["id"]}
    assert ask(ben)["results"] == []                    # the restricted branch is not searched for him
    # a grant on a node inside the branch: that node is searched, the one between is not and is not named
    g2 = ada.post(f"/v1/memories/{deep['id']}/grants",
                  json={"principal": "member:ben@example.com", "privileges": ["read"]}).json()
    got = ask(ben)["results"]
    assert [x["memory"] for x in got] == [{"id": deep["id"], "name": "Shared corner"}]
    assert tree["private"] not in str(ask(ben))
    ada.delete(f"/v1/memories/{deep['id']}/grants/{g2['id']}")
    ada.delete(f"/v1/memories/{tree['company']}/grants/{g['id']}")
    ada.delete(f"/v1/memories/{deep['id']}")


def test_the_three_signals_and_what_a_provider_did_not_do(people, tree):
    ada, _ = people
    rec = lambda **b: ada.post(f"/v1/memories/{tree['acme']}/recall", json=b).json()   # noqa: E731
    assert [x["record"]["type"] for x in rec(text="sso")["results"]] == ["episode"]
    f = rec(filters={"field": "attributes.account", "op": "eq", "value": "acme"})
    assert [x["record"]["id"] for x in f["results"]] == [tree["fact"]] and f["results"][0]["why"] == ["filters"]
    both = rec(query="when acme renews", text="march", types=["fact"])
    assert [x["record"]["id"] for x in both["results"]] == [tree["fact"]] and both["results"][0]["why"] == ["text", "query"]
    assert rec(query="what is the weather on Mars")["abstain"] is True
    assert rec(query="renew", depth=3)["degraded"] == []
    r = ada.post(f"/v1/memories/{tree['acme']}/recall", json={})
    assert r.status_code == 422


def test_entities_and_relationships_are_records_and_references_in_one_graph(people, tree):
    ada, ben = people
    acme = f"/v1/memories/{tree['acme']}"
    mk = lambda url, **b: ada.post(url + "/records", json=b).json()   # noqa: E731
    dana = mk(acme, type="entity", content="Dana Okafor", attributes={"labels": ["person"]})
    quil = mk(acme, type="entity", content="Quillon Freight", attributes={"labels": ["company"]})
    boss = mk(f"/v1/memories/{tree['private']}", type="entity", content="The board member Dana reports to")
    assert dana["type"] == "entity" and dana["content"] == [{"type": "text", "text": "Dana Okafor"}]
    # a relationship with something to say is a fact that names its subject and its object
    job = mk(acme, type="fact", content="Dana Okafor is head of procurement at Quillon Freight.",
             attributes={"predicate": "works_at"},
             references=[{"rel": "subject", "record_id": dana["id"]}, {"rel": "object", "record_id": quil["id"]}])
    mk(acme, type="fact", content="Dana reports to a board member.", attributes={"predicate": "reports_to"},
       references=[{"rel": "subject", "record_id": dana["id"]},
                   {"rel": "object", "memory_id": tree["private"], "record_id": boss["id"]}])
    g = ada.post(acme + "/graph", json={"around": dana["id"], "hops": 1}).json()
    assert g["object"] == "memory.graph" and g["truncated"] is False
    ids = {n["record"]["id"]: n for n in g["nodes"]}
    assert dana["id"] in ids and job["id"] in ids and quil["id"] not in ids          # one hop: the facts about Dana
    assert g["nodes"][0]["record"]["id"] == dana["id"] and ids[job["id"]]["memory"] == {"id": tree["acme"], "name": "Acme"}
    edge = lambda g, rel, to: [e for e in g["edges"] if e.get("rel") == rel and e["to"]["record_id"] == to]   # noqa: E731
    assert edge(g, "subject", dana["id"])[0]["from"] == {"memory_id": tree["acme"], "record_id": job["id"]}
    # two hops reach the other end of each relationship, across memories for one who may read both
    g2 = ada.post(acme + "/graph", json={"around": dana["id"], "hops": 2}).json()
    ids2 = {n["record"]["id"]: n["memory"]["id"] for n in g2["nodes"]}
    assert ids2[quil["id"]] == tree["acme"] and ids2[boss["id"]] == tree["private"]
    assert edge(g2, "object", quil["id"]) and edge(g2, "object", boss["id"])[0]["available"] is True
    assert {n["record"]["type"] for n in ada.post(acme + "/graph", json={"around": dana["id"], "hops": 2, "types": ["entity"]}).json()["nodes"]} == {"entity"}
    # the whole memory, no start: its records and what they point at
    whole = ada.post(acme + "/graph", json={}).json()
    assert {dana["id"], quil["id"], job["id"]} <= {n["record"]["id"] for n in whole["nodes"]}
    # Ben reads Sales and below, not the restricted memory: the edge says it leads somewhere he
    # cannot read, and neither the node nor what it is called is there
    ada.post(f"/v1/memories/{tree['sales']}/grants", json={"principal": "member:ben@example.com", "privileges": ["read"]})
    gb = ben.post(acme + "/graph", json={"around": dana["id"], "hops": 2}).json()
    assert boss["id"] not in {n["record"]["id"] for n in gb["nodes"]} and "board member Dana reports to" not in str(gb)
    hidden = [e for e in gb["edges"] if e["to"]["record_id"] == boss["id"]]
    assert hidden == [{"from": hidden[0]["from"], "to": {"memory_id": tree["private"], "record_id": boss["id"]}, "available": False}]
    assert ada.post(acme + "/graph", json={"around": "nope"}).status_code == 404
    assert ada.post(acme + "/graph", json={"hops": 9}).status_code == 422
    caps = next(p for p in ada.get("/v1/memories/providers").json()["data"] if p["id"] == "fixture")
    assert caps["graph"] == {"entities": "stated"}


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
    assert ada.get(base, params={"as_of": before}).json()["content"] == [{"type": "text", "text": "Acme renews in March."}]
    assert ada.post(f"/v1/memories/{tree['acme']}/recall",
                    json={"text": "april", "as_of": before}).json()["results"] == []
    snap = ada.post(f"/v1/memories/{tree['acme']}/snapshots", json={"name": "before-forgetting"}).json()
    assert snap["object"] == "memory.snapshot" and snap["at"] > before
    # forget closes it and keeps the trace
    gone = ada.delete(base).json()
    assert gone["status"] == "forgotten"
    assert ada.post(f"/v1/memories/{tree['acme']}/recall", json={"text": "april"}).json()["results"] == []
    assert len(ada.get(base + "/history").json()["data"]) == 2
    assert ada.get(base, params={"as_of": snap["at"]}).json()["content"] == [{"type": "text", "text": "Acme renews in April."}]


def test_a_reference_crosses_the_tree_and_resolves_for_the_reader(people, tree):
    ada, ben = people
    secret = ada.post(f"/v1/memories/{tree['private']}/records",
                      json={"type": "note", "content": "Dana told me the budget is frozen."}).json()
    shared = ada.post(f"/v1/memories/{tree['sales']}/records", json={
        "type": "fact", "content": "Acme's budget is under review.",
        "references": [{"rel": "derived_from", "memory_id": tree["private"], "record_id": secret["id"]}]}).json()
    assert shared["references"][0]["available"] is True
    seen = ben.get(f"/v1/memories/{tree['sales']}/records/{shared['id']}").json()
    assert seen["content"] == [{"type": "text", "text": "Acme's budget is under review."}]
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
    assert [t["type"] for t in types if t.get("core")] == ["episode", "fact", "note", "procedure", "link", "entity"]
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
    assert run["written_by"] == {"kind": "provider", "id": "fixture"}
    changes = ada.get(base + f"/consolidations/{run['id']}/changes").json()["data"]
    assert len(changes) == 2 and all(c["record"]["written_by"] == {"kind": "provider", "id": "fixture", "consolidation_id": run["id"]} for c in changes)
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


def test_content_is_an_ordered_list_of_text_and_file_parts(people):
    """Two kinds of part, text and file; what a file is (an image, a recording) is its media type.
    A string is shorthand on the way in; what comes back is always the list."""
    ada, ben = people
    mid = ada.post("/v1/memories", json={"provider": "fixture", "name": "Brand"}).json()["id"]
    plain = ada.post(f"/v1/memories/{mid}/records", json={"content": "The brand colour is blue."}).json()
    assert plain["content"] == [{"type": "text", "text": "The brand colour is blue."}]

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
    up = ada.post("/v1/files", files={"file": ("logo.png", png, "image/png")}, data={"purpose": "user_data"})
    assert up.status_code == 200, up.text
    fid = up.json()["id"]
    rec = ada.post(f"/v1/memories/{mid}/records", json={"type": "note", "content": [
        {"type": "text", "text": "The new logo, final on 1 October."},
        {"type": "file", "file": {"id": fid, "name": "forged.exe", "media_type": "application/x-evil", "bytes": 1},
         "text": "A blue circle with a white letter A."},
        {"type": "x.vendor.embedding", "ref": "abc"}]})
    assert rec.status_code == 200, rec.text
    parts = rec.json()["content"]
    assert [p["type"] for p in parts] == ["text", "file", "x.vendor.embedding"]            # in order, the unknown kind kept
    assert parts[1]["file"] == {"id": fid, "name": "logo.png", "media_type": "image/png", "bytes": len(png)}   # the store's, not the caller's
    assert parts[1]["text"] == "A blue circle with a white letter A." and parts[1]["text_source"] == "stated"
    rid = rec.json()["id"]
    # found by the words that stand for the file
    hit = ada.post(f"/v1/memories/{mid}/recall", json={"text": "circle"}).json()["results"]
    assert [x["record"]["id"] for x in hit] == [rid]
    # the bytes are read at their own address, by whoever may read the record
    got = ada.get(f"/v1/memories/{mid}/records/{rid}/content/1")
    assert got.status_code == 200 and got.content == png and got.headers["content-type"] == "image/png"
    assert ada.get(f"/v1/memories/{mid}/records/{rid}/content/0").status_code == 404        # a text part has no bytes
    assert ben.get(f"/v1/memories/{mid}/records/{rid}/content/1").status_code == 404
    # a conversation is the same shape, each part under the role that said it
    eps = ada.post(f"/v1/memories/{mid}/observe", json={"episodes": [{"content": [
        {"type": "text", "role": "user", "text": "Here is our logo."}, {"type": "file", "role": "user", "file": {"id": fid}},
        {"type": "text", "role": "assistant", "text": "Kept."}]}]}).json()["data"]
    assert [(p["type"], p["role"]) for p in eps[0]["content"]] == [("text", "user"), ("file", "user"), ("text", "assistant")]
    for bad in ([{"type": "image", "url": "x"}], [{"type": "text"}], [{"type": "file", "file": {}}],
                [{"type": "text", "text": "x", "role": "narrator"}], [], {"text": "x"},
                [{"type": "file", "file": {"id": "file_does_not_exist"}}]):
        r = ada.post(f"/v1/memories/{mid}/records", json={"content": bad})
        assert r.status_code == 422 and _code(r) == "memory_invalid", (bad, r.text)
    caps = next(p for p in ada.get("/v1/memories/providers").json()["data"] if p["id"] == "fixture")
    assert caps["content"] == {"media": ["*/*"], "bytes": "referenced", "describes": []}
