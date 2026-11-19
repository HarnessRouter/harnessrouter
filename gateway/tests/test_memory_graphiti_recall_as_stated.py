"""A recall on Graphiti answers a fact read from a stated record as that record, so one side of a disagreement brings
the other.

Graphiti reads a copy of each stated record and draws facts from it, and its search answers those facts ahead of the
records themselves. A fact drawn from "Hollin has never signed a lease" carries no `contradicts`: that reference is on
the stated record. So a recall with limit 1 answered the drawn fact alone, and the record on the other side of the
disagreement never came (UHP conformance ME-12, failing on a live instance's Graphiti engine and passing on Hindsight).
Now the drawn fact is answered as the stated record at the fact's place, and the plane brings the other side (§6.3).
A fact from a conversation, even in part, stays a fact. Driven against a fake Graphiti server."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graphiti as mg  # noqa: E402
import memory_plane as mp  # noqa: E402

run = asyncio.run
MID = "hmem_lease"
UX, UY, UN = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
EPX, EPY, EPO = "ep-copy-x", "ep-copy-y", "ep-conversation"
WRITER = {"kind": "member", "id": "ada@example.com"}
SIGNED, NEVER = "Hollin signed the warehouse lease in May.", "Hollin has never signed a lease."


def _stated(u: str, text: str, ep: str, refs: list, status: str = "active") -> dict:
    return {"uuid": u, "name": text[:120], "summary": text, "labels": ["Entity"], "group_id": MID,
            "created_at": "2026-11-19T02:00:00Z", "episodes": [ep],
            "attributes": {"hr_stated": "1", "hr_type": "fact", "hr_version": 1, "hr_status": status,
                           "hr_written_at": "2026-11-19T02:00:00Z", "hr_text": text, "hr_attributes": "{}",
                           "hr_refs": json.dumps(refs), "hr_writer": json.dumps(WRITER)}}


X = _stated(UX, SIGNED, EPX, [{"rel": "contradicts", "memory_id": "", "record_id": mg.NODE + UY}])
Y = _stated(UY, NEVER, EPY, [{"rel": "contradicts", "memory_id": "", "record_id": mg.NODE + UX}])
ENTITY = {"uuid": UN, "name": "Hollin", "summary": f"{SIGNED} {NEVER}", "labels": ["Entity", "Person"], "group_id": MID,
          "created_at": "2026-11-19T02:00:05Z", "episodes": [EPX, EPY], "attributes": {}}
EPISODES = [{"uuid": EPX, "name": mg.READ + UX, "content": SIGNED, "created_at": "2026-11-19T02:00:01Z", "group_id": MID},
            {"uuid": EPY, "name": mg.READ + UY, "content": NEVER, "created_at": "2026-11-19T02:00:02Z", "group_id": MID},
            {"uuid": EPO, "name": "turn", "content": "user: Hollin? never signed anything", "created_at": "2026-11-19T02:00:03Z",
             "group_id": MID, "source_description": "member ada session: hsess_1"}]


def _edge(u: str, fact: str, episodes: list[str], closed: bool = False) -> dict:
    return {"uuid": u, "name": "SIGNED", "fact": fact, "source": UN, "target": UN, "episodes": episodes,
            "valid_at": "2026-05-01T00:00:00Z", "invalid_at": "2026-11-19T02:00:04Z" if closed else None,
            "expired_at": None, "created_at": "2026-11-19T02:00:04Z", "attributes": {}}


def _server(monkeypatch, edges: list[dict], nodes: list[dict], stored: dict | None = None) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    stored = stored if stored is not None else {UX: X, UY: Y, UN: ENTITY}

    def handle(req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        calls.append((m, path))
        if path.endswith("/search"):
            return httpx.Response(200, json={"edges": edges, "nodes": nodes, "episodes": []})
        if path.endswith(f"/groups/{MID}/episodes") and m == "GET":
            return httpx.Response(200, json=EPISODES)
        for u, n in stored.items():
            if path.endswith(f"/groups/{MID}/nodes/{u}"):
                return httpx.Response(200, json=n)
        return httpx.Response(404, json={"detail": "not found"})

    monkeypatch.setattr(mg, "transport", httpx.MockTransport(handle))
    return calls


def _recall(req: dict) -> list[tuple[str, str]]:
    out = run(mg.Graphiti("http://graphiti.test", "k").recall(MID, req))["results"]
    return [(r["record"]["id"], r["record"]["type"]) for r in out]


def test_a_fact_read_from_a_stated_record_is_answered_as_that_record_once(monkeypatch):
    _server(monkeypatch, edges=[_edge("e1", NEVER, [EPY])], nodes=[Y, X, ENTITY])
    got = _recall({"query": "did Hollin sign the lease?", "limit": 5})
    # the fact's place goes to the record it was read from; that record's own hit is not answered twice
    assert got == [(mg.NODE + UY, "fact"), (mg.NODE + UX, "fact"), (mg.NODE + UN, "entity")]


def test_with_limit_one_the_best_hit_is_the_stated_record_and_brings_the_other_side(monkeypatch):
    _server(monkeypatch, edges=[_edge("e1", NEVER, [EPY])], nodes=[Y, X, ENTITY])
    g = mg.Graphiti("http://graphiti.test", "k")

    async def provider_of(_m):
        return g
    monkeypatch.setattr(mp, "provider_of", provider_of)
    res = run(mp.recall("org", [{"id": MID, "provider": "graphiti"}], {"query": "did Hollin sign the lease?", "limit": 1}))
    rows = [(r["record"]["id"], r["score"], r["why"]) for r in res["results"]]
    assert rows == [(mg.NODE + UY, 1.0, ["query"]), (mg.NODE + UX, None, ["contradicts"])]     # ME-12, as the suite reads it


def test_a_record_the_server_revised_on_its_writers_behalf_is_still_the_stated_record(monkeypatch):
    # Writing Y, which contradicts X, adds the mirror reference to X as a revise by the server on the member's behalf,
    # so X's latest version is written_by the provider. A fact drawn from X that ranks first is still answered as X,
    # and X brings Y. Judging the record by its writer left that fact answered alone (ME-12, 2 recalls in 4 live).
    by_server = {"kind": "provider", "id": "graphiti", "on_behalf_of": "member:ada@example.com"}
    revised = dict(X, attributes={**X["attributes"], "hr_version": 2, "hr_writer": json.dumps(by_server)})
    _server(monkeypatch, edges=[_edge("e1", SIGNED, [EPX])], nodes=[Y, revised, ENTITY], stored={UX: revised, UY: Y, UN: ENTITY})
    g = mg.Graphiti("http://graphiti.test", "k")

    async def provider_of(_m):
        return g
    monkeypatch.setattr(mp, "provider_of", provider_of)
    res = run(mp.recall("org", [{"id": MID, "provider": "graphiti"}], {"query": "did Hollin sign the lease?", "limit": 1}))
    rows = [(r["record"]["id"], r["score"], r["why"]) for r in res["results"]]
    assert rows == [(mg.NODE + UX, 1.0, ["query"]), (mg.NODE + UY, None, ["contradicts"])]


def test_a_stated_record_the_search_did_not_answer_is_read_for_its_fact(monkeypatch):
    calls = _server(monkeypatch, edges=[_edge("e1", NEVER, [EPY])], nodes=[ENTITY])
    assert _recall({"query": "Hollin lease", "limit": 5}) == [(mg.NODE + UY, "fact"), (mg.NODE + UN, "entity")]
    assert ("GET", f"/groups/{MID}/nodes/{UY}") in calls


def test_a_fact_from_a_conversation_even_in_part_stays_a_fact(monkeypatch):
    _server(monkeypatch, edges=[_edge("e1", NEVER, [EPO]), _edge("e2", NEVER, [EPY, EPO])], nodes=[Y])
    got = _recall({"query": "did Hollin sign the lease?", "limit": 5})
    assert got == [(mg.EDGE + "e1", "fact"), (mg.EDGE + "e2", "fact"), (mg.NODE + UY, "fact")]


def test_a_fact_whose_stated_record_is_gone_or_forgotten_stays_as_it_is(monkeypatch):
    gone = dict(Y, attributes={**Y["attributes"], "hr_status": "forgotten"})
    _server(monkeypatch, edges=[_edge("e1", NEVER, [EPY]), _edge("e2", SIGNED, [EPX])], nodes=[], stored={UY: gone})
    got = _recall({"query": "Hollin lease", "limit": 5})
    assert got == [(mg.EDGE + "e1", "fact"), (mg.EDGE + "e2", "fact")]      # forgotten is not shown; X can't be read


def test_a_closed_fact_is_still_left_out_and_does_not_bring_its_record(monkeypatch):
    _server(monkeypatch, edges=[_edge("e1", SIGNED, [EPX], closed=True)], nodes=[ENTITY])
    assert _recall({"query": "Hollin lease", "limit": 5}) == [(mg.NODE + UN, "entity")]


def test_a_type_the_recall_leaves_out_keeps_the_fact_as_it_is(monkeypatch):
    proc = dict(Y, attributes={**Y["attributes"], "hr_type": "procedure"})
    _server(monkeypatch, edges=[_edge("e1", NEVER, [EPY])], nodes=[], stored={UY: proc})
    assert _recall({"query": "Hollin lease", "limit": 5, "types": ["fact"]}) == [(mg.EDGE + "e1", "fact")]
