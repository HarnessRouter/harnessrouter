"""Hindsight, Graphiti, ReMe and a self-hosted mem0, each against a stub answering what its real server
answered on 2026-11-04, and what the server does around any of them: a memory's schema, a fact that holds
one value, a disagreement kept on both records, and a vendor's connection tried before it is kept.

A real server of each was held to the same protocol by the conformance suite and the support matrix. These
cover what those can't repeat without a model: the exact request a vendor receives, and what a memory must
never reach."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_fixture  # noqa: E402
import memory_graphiti  # noqa: E402
import memory_hindsight  # noqa: E402
import memory_mem0  # noqa: E402
import memory_plane as mp  # noqa: E402
import memory_reme  # noqa: E402

ORG = "vendororg"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
SECRET = "vendor-key-SENTINEL-never-returned"
WRITER = {"kind": "member", "id": "ada@example.com"}
run = asyncio.run


class Wire:
    """Every request a vendor received, and an answer from the test."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        self.calls.append({"method": req.method, "path": req.url.path, "params": dict(req.url.params), "body": body, "headers": dict(req.headers)})
        out = self.answer(req.method, req.url.path, dict(req.url.params), body)
        return out if isinstance(out, httpx.Response) else httpx.Response(200, json=out if out is not None else {})

    def to(self, path_end: str) -> list[dict]:
        return [c for c in self.calls if c["path"].endswith(path_end)]


@pytest.fixture(autouse=True)
def _connect_answers_alone(monkeypatch):
    """These stubs answer one route each, as the vendor's health route answered; the record a connection writes, reads
    back and deletes is held to real answers in test_memory_provisioning.py (the round trip)."""
    async def kept(engine, key, base, org):
        return ""
    monkeypatch.setattr(gw, "_memory_round_trip", kept)


@pytest.fixture
def wired(monkeypatch):
    def use(module, answer):
        w = Wire(answer)
        monkeypatch.setattr(module, "transport", httpx.MockTransport(w))
        return w
    return use


# ── Hindsight: labels classify facts, and are never entities ──────────────────────────────────
BANK = "/v1/default/banks/m"


def _hs(method, path, params, body):
    if path == BANK + "/entities":
        return {"items": [{"id": "e1", "canonical_name": "Globex", "mention_count": 2}, {"id": "e2", "canonical_name": "type:Company"}], "total": 2}
    if path == BANK + "/entities/e2":
        return {"id": "e2", "canonical_name": "type:Company"}
    if path == BANK + "/memories/list":
        return {"items": [{"id": "u1", "text": "Globex uses Photon Lite", "entities": "Globex, type:Company, type:Product", "document_id": "hrec_d", "state": "valid", "fact_type": "world"}], "total": 1}
    if path == BANK + "/memories/recall":
        return {"results": [{"id": "u1", "text": "Globex uses Photon Lite", "entities": ["Globex", "type:Company"], "document_id": "hrec_d", "type": "world", "scores": {"semantic": 0.9, "final": 0.9}}]}
    return {}


def test_a_label_is_on_the_fact_and_never_an_entity(wired):
    wired(memory_hindsight, _hs)
    h = memory_hindsight.Hindsight("http://vendor.test")
    assert [x["title"] for x in run(h.list("m", {"types": ["entity"]}))["records"]] == ["Globex"]
    fact = next(x for x in run(h.list("m", {"limit": 10}))["records"] if x["type"] == "fact")
    assert fact["attributes"]["labels"] == ["Company", "Product"]
    about = [r["record_id"] for r in fact["references"] if r["rel"] == "about"]
    assert about == ["ent_e1"], "a label must not become an edge of the graph"


def test_a_fact_says_its_sentence_and_nothing_else_is_passed_off_as_it():
    """Measured: "<what> | When: … | Where: … | Involving: … | <why>", which read as a title on the page."""
    h = memory_hindsight.Hindsight("http://vendor.test")
    x = h._fact_out("m", {"id": "u", "state": "valid", "text": "Acme signed up | When: on October 28, 2026 | Where: Lisbon | Involving: Acme | they needed seats",
                          "occurred_start": "2026-10-28", "occurred_end": "2026-10-28", "fact_type": "world"}, {})
    assert x["content"][0]["text"] == "Acme signed up"
    assert x["attributes"] == {"where": "Lisbon", "why": "they needed seats"}, "a date is in the time, and who is in the references"
    assert x["time"]["valid_from"] == "2026-10-28" and x["time"]["valid_to"] is None, "one event's end isn't when a fact stopped being true"
    y = h._fact_out("m", {"id": "u", "state": "valid", "text": "Dana worked there | When: for years", "occurred_start": "2019-01-01", "occurred_end": "2021-01-01", "fact_type": "observation"}, {})
    assert y["time"]["valid_to"] == "2021-01-01" and y["attributes"] == {"kind": "observation"}
    z = h._fact_out("m", {"id": "u", "state": "valid", "text": "Dana runs it | When: every Tuesday"}, {})
    assert z["attributes"] == {"when": "every Tuesday"}, "with no date, its words are all there is"


def test_a_labels_entity_cant_be_read_by_its_id(wired):
    wired(memory_hindsight, _hs)
    assert run(memory_hindsight.Hindsight("http://vendor.test").get("m", "ent_e2")) is None


def test_the_labels_reach_the_vendor_as_a_vocabulary_with_the_measured_wording(wired):
    w = wired(memory_hindsight, lambda *a: {})
    h = memory_hindsight.Hindsight("http://vendor.test")
    run(h.apply_schema("m", {"types": [{"name": "Company", "description": "A customer."}, {"name": "Person", "description": ""}]}))
    labels = w.to("/config")[-1]["body"]["updates"]["entity_labels"]["attributes"]
    assert len(labels) == 1
    g = labels[0]
    assert g["key"] == "type" and g["type"] == "multi-values" and g["tag"] is True and g["optional"] is True
    assert g["description"] == memory_hindsight.LABEL_ASK
    assert g["values"] == [{"value": "Company", "description": "A customer."}, {"value": "Person", "description": ""}]
    run(h.apply_schema("m", {"types": []}))
    assert w.to("/config")[-1]["body"]["updates"]["entity_labels"] is None, "no types takes the labels away"


def test_a_search_by_label_is_scoped_at_the_vendor_and_says_nothing_was_lost(wired):
    w = wired(memory_hindsight, _hs)
    h = memory_hindsight.Hindsight("http://vendor.test")
    out = run(h.recall("m", {"query": "who", "filters": {"field": "attributes.labels", "op": "contains", "value": "Company"}}))
    sent = w.to("/recall")[-1]["body"]
    assert sent["tags"] == ["type:Company"] and sent["tags_match"] == "any_strict"
    assert out["degraded"] == [] and out["results"][0]["record"]["attributes"]["labels"] == ["Company"]


def test_a_label_filters_a_read_with_no_question_too(wired):
    wired(memory_hindsight, _hs)
    h = memory_hindsight.Hindsight("http://vendor.test")
    flt = lambda v: {"field": "attributes.labels", "op": "contains", "value": v}   # noqa: E731
    assert len(run(h.recall("m", {"filters": flt("Company")}))["results"]) == 1
    assert run(h.recall("m", {"filters": flt("Person")}))["results"] == []


def test_any_other_filter_is_said_to_run_after_the_ranking(wired):
    wired(memory_hindsight, _hs)
    out = run(memory_hindsight.Hindsight("http://vendor.test").recall("m", {"query": "who", "filters": {"field": "attributes.kind", "op": "eq", "value": "nope"}}))
    assert out["degraded"] == ["filters:applied_after_ranking"] and out["results"] == []


def test_a_search_for_facts_reads_what_episodes_derived_and_a_search_for_episodes_says_it_cant(wired):
    w = wired(memory_hindsight, _hs)
    h = memory_hindsight.Hindsight("http://vendor.test")
    out = run(h.recall("m", {"query": "who", "types": ["fact"]}))
    assert set(w.to("/recall")[-1]["body"]["tags"]) == {"t:fact", "t:episode"} and len(out["results"]) == 1
    out = run(h.recall("m", {"query": "who", "types": ["episode"]}))
    assert out["results"] == [] and "types:episodes_are_not_searched" in out["degraded"]


def test_a_stated_record_is_kept_word_for_word_under_an_id_we_chose(wired):
    w = wired(memory_hindsight, lambda *a: {})
    x = run(memory_hindsight.Hindsight("http://vendor.test").remember("m", {"type": "fact", "content": [{"type": "text", "text": "Refunds take 30 days."}]}, WRITER))
    item = next(c["body"]["items"][0] for c in w.to("/memories") if c["body"]["items"][0]["document_id"] == x["id"])
    assert item["strategy"] == memory_hindsight.STATED and x["id"].startswith("hrec_")
    assert item["content"] == "Refunds take 30 days." and "t:fact" in item["tags"]
    bank = w.to("/config")[0]["body"]["updates"]["retain_strategies"][memory_hindsight.STATED]
    assert bank == {"retain_extraction_mode": "chunks"}, "words are kept only with no extraction"


def test_a_memorys_count_is_what_its_lists_hold(wired):
    """Its /stats route stayed at zero for minutes while facts were there to read."""
    def answer(method, path, params, body):
        if path == BANK + "/stats":
            return {"total_nodes": 0}
        if path == BANK + "/memories/list":
            return {"items": [], "total": 3}
        if path == BANK + "/documents":
            return {"items": [], "total": 1}
        return _hs(method, path, params, body)
    wired(memory_hindsight, answer)
    assert run(memory_hindsight.Hindsight("http://vendor.test").count("m")) == 5, "3 facts, 1 episode, 1 entity, and a label is not an entity"


def test_erasing_a_derived_fact_reports_it_stays_stored(wired):
    wired(memory_hindsight, lambda *a: {})
    out = run(memory_hindsight.Hindsight("http://vendor.test").erase("m", ["u1"]))
    assert out == {"erased": ["u1"], "unreachable": ["u1"]}


# ── Graphiti: a schema guides the extraction ──────────────────────────────────────────────────
SCHEMA = {"types": [{"name": "Company", "description": "A customer.", "properties": [{"name": "seats", "type": "number", "description": ""}]},
                    {"name": "Product", "description": "", "properties": []}],
          "relations": [{"name": "BUYS", "description": "Bought.", "from": "Company", "to": "Product"}]}


def _graphiti(method, path, params, body):
    if path == "/episodes":
        return {"episode": {"uuid": "ep1", "name": "x", "content": "..."},
                "nodes": [{"uuid": "n1", "name": "Globex", "labels": ["Entity", "Company"], "attributes": {"seats": 12}},
                          {"uuid": "n2", "name": "Dana", "labels": ["Entity"], "attributes": {}}],
                "edges": [{"uuid": "r1", "name": "BUYS", "fact": "Globex uses Photon Lite.", "source": "n1", "target": "n2", "episodes": ["ep1"]},
                          {"uuid": "r2", "name": "RELATES_TO", "fact": "Dana reports to Priya.", "source": "n2", "target": "n1", "invalid_at": "2026-01-01T00:00:00Z"}]}
    return {}


def test_a_memorys_schema_goes_with_every_episode_as_the_vendor_wants_it(wired, monkeypatch):
    w = wired(memory_graphiti, _graphiti)
    async def load(org, mid):
        return {"schema": json.dumps(SCHEMA)}
    monkeypatch.setattr(mp, "_load", load)
    g = memory_graphiti.Graphiti("http://vendor.test", "", ORG)
    out = run(g.observe("m", [{"type": "episode", "content": [{"type": "text", "text": "hello", "role": "user"}]}], WRITER))
    sent = w.to("/episodes")[0]["body"]
    assert sent["group_id"] == "m" and sent["content"] == "user: hello"
    assert sent["entity_types"][0]["properties"][0]["name"] == "seats"
    assert sent["edge_types"] == [{"name": "BUYS", "description": "Bought.", "properties": []}]
    assert sent["edge_type_map"] == [{"from": "Company", "to": "Product", "names": ["BUYS"]}]
    by = {r["id"]: r for r in out["records"]}
    assert by["node_n1"]["attributes"] == {"seats": 12, "entity_type": "Company"}
    assert by["node_n2"]["attributes"] == {}, "Entity is every node's label, not a type"
    assert by["edge_r1"]["attributes"]["predicate"] == "BUYS" and by["edge_r1"]["status"] == "active"
    assert by["edge_r2"]["content"][0]["text"] == "Dana reports to Priya.", "the sentence stays when the name is lost"
    assert by["edge_r2"]["status"] == "superseded"


def test_with_no_schema_the_extraction_is_left_to_itself(wired, monkeypatch):
    w = wired(memory_graphiti, _graphiti)
    async def load(org, mid):
        return {}
    monkeypatch.setattr(mp, "_load", load)
    run(memory_graphiti.Graphiti("http://vendor.test", "", ORG).observe("m", [{"type": "episode", "content": [{"type": "text", "text": "hi"}]}], WRITER))
    sent = w.to("/episodes")[0]["body"]
    assert sent["entity_types"] == [] and sent["edge_types"] == [] and sent["edge_type_map"] == []


def _reads_its_copy(monkeypatch):
    """A Graphiti server where a stated node is n_s, and the copy it read of it (ep_c) found Caroline and a fact."""
    async def load(org, mid):
        return {}
    monkeypatch.setattr(mp, "_load", load)
    state = {"episodes": [{"uuid": "ep_c", "name": "hr_read:n_s", "content": "copy"}, {"uuid": "ep_o", "name": "turn", "content": "observed"}],
             "nodes": {}, "deleted": [], "posted": []}

    def answer(method, path, params, body):
        if method == "POST" and path == "/nodes":
            n = {"uuid": "n_s", "name": body["name"], "summary": body["summary"], "labels": body["labels"], "attributes": body["attributes"]}
            state["nodes"]["n_s"] = n
            return n
        if method == "POST" and path == "/episodes":
            state["posted"].append(body)
            return {"queued": True, "pending": 1}
        if method == "GET" and path == "/groups/m/episodes":
            return [e for e in state["episodes"] if e["uuid"] not in state["deleted"]]
        if method == "DELETE" and path.startswith("/groups/m/episodes/"):
            state["deleted"].append(path.rsplit("/", 1)[1])
            return {"deleted": True}
        if method == "GET" and path == "/groups/m/nodes":
            # Graphiti rewrote the stated node's summary when it matched it, and found Caroline in the copy
            stated = {**state["nodes"].get("n_s", {}), "summary": "Graphiti's own words", "episodes": ["ep_c"]}
            return [stated, {"uuid": "n_c", "name": "Caroline", "labels": ["Entity"], "attributes": {}, "episodes": ["ep_c", "ep_o"]}]
        if method == "GET" and path == "/groups/m/edges":
            return [{"uuid": "e1", "name": "ATTENDED", "fact": "Caroline went to a support group.", "source": "n_c", "target": "n_c", "episodes": ["ep_c"], "attributes": {}}]
        if method == "DELETE" and path == "/groups/m/nodes/n_s":
            return {"deleted": "n_s"}
        if method == "GET" and path == "/groups/m/nodes/n_s":
            return state["nodes"]["n_s"]
        return {}
    return state, answer


def test_graphiti_reads_a_copy_of_what_is_stated_and_what_it_finds_comes_from_the_record(wired, monkeypatch):
    state, answer = _reads_its_copy(monkeypatch)
    wired(memory_graphiti, answer)
    g = memory_graphiti.Graphiti("http://vendor.test", "", ORG)
    rec = run(g.remember("m", {"type": "note", "title": "Support group", "content": [{"type": "text", "text": "Caroline went to an LGBTQ support group on 7 May 2023."}],
                              "time": {"valid_from": "2023-05-07T00:00:00Z"}}, WRITER))
    sent = state["posted"][0]
    assert sent["background"] is True and sent["name"] == "hr_read:n_s" and sent["reference_time"] == "2023-05-07T00:00:00Z"
    assert "Caroline went to an LGBTQ support group" in sent["content"] and sent["group_id"] == "m"
    rows = {r["id"]: r for r in run(g.list("m", {"limit": 50}))["records"]}
    assert rows["node_n_s"]["content"][0]["text"] == "Caroline went to an LGBTQ support group on 7 May 2023.", "the stated words, not Graphiti's rewrite"
    assert "ep_ep_c" not in rows, "the copy is the record, already listed"
    assert "ep_ep_o" in rows
    came = lambda r: [x["record_id"] for x in r["references"] if x["rel"] == "derived_from"]   # noqa: E731
    assert came(rows["edge_e1"]) == ["node_n_s"], "a fact Graphiti found came from the stated record"
    assert came(rows["node_n_c"]) == ["node_n_s", "ep_ep_o"]
    assert came(rows["node_n_s"]) == [], "a stated node matched in its own copy didn't come from itself"
    assert rec["id"] == "node_n_s"


def test_forgetting_or_erasing_what_was_stated_takes_what_graphiti_read_in_it(wired, monkeypatch):
    state, answer = _reads_its_copy(monkeypatch)
    wired(memory_graphiti, answer)
    g = memory_graphiti.Graphiti("http://vendor.test", "", ORG)
    run(g.remember("m", {"type": "note", "content": [{"type": "text", "text": "Caroline went to a support group."}]}, WRITER))
    out = run(g.erase("m", ["node_n_s"]))
    assert out["erased"] == ["node_n_s"] and state["deleted"] == ["ep_c"], "the copy goes, and only the copy"


def test_forgetting_an_episode_closes_it_and_keeps_its_trace(wired):
    """It holds what was said, so a forgotten thing left in it would still be in the memory."""
    episodes = [{"uuid": "ep1", "name": "x", "content": "the title is Wren", "created_at": "2026-11-04T00:00:00Z"}]

    def answer(method, path, params, body):
        if path == "/groups/m/episodes":
            return episodes
        if path == "/groups/m/episodes/ep1/forget":
            episodes[0]["forgotten_at"] = body["at"]
            return {"uuid": "ep1", "forgotten_at": body["at"]}
        if path.endswith(("/nodes", "/edges")):
            return []
        return {}
    wired(memory_graphiti, answer)
    g = memory_graphiti.Graphiti("http://vendor.test", "", ORG)
    assert [x["id"] for x in run(g.list("m", {"types": ["episode"]}))["records"]] == ["ep_ep1"]
    out = run(g.forget("m", "ep_ep1", WRITER))
    assert out["status"] == "forgotten" and out["time"]["invalidated_at"]
    assert run(g.list("m", {"types": ["episode"]}))["records"] == [], "closed means no longer read"
    kept = run(g.list("m", {"types": ["episode"], "include": "all"}))["records"]
    assert kept[0]["status"] == "forgotten" and kept[0]["content"][0]["text"] == "the title is Wren"
    with pytest.raises(mp.MemoryError):
        run(g.forget("m", "ep_ep1", WRITER))     # already closed: nothing to close


@pytest.mark.parametrize("make", [lambda: memory_mem0.Mem0Server("k", "http://vendor.test"), lambda: memory_mem0.Mem0("k")], ids=["server", "platform"])
def test_mem0_gives_what_is_standing_and_nothing_else(wired, make):
    """Its metadata is kept and filtered on by mem0: a preference one agent keeps reaches the next one here as well."""
    def item(i, meta, memory):
        return {"id": i, "user_id": "m", "memory": memory, "created_at": "2026-11-04T00:00:00Z", "metadata": {"hr_type": "note", **meta}}
    rows = [item("a", {"standing": True}, "Sign notes with Thanks, Ops"), item("b", {}, "Acme renews in March")]
    asked = []

    def answer(method, path, params, body):
        asked.append(body)
        if method == "POST" and path.endswith("/memories/"):      # the Platform filters it, as it is asked to
            want = (body or {}).get("filters")
            assert {"metadata": {"standing": True}} in want["AND"] and {"user_id": "m"} in want["AND"]
            return {"results": rows[:1]}
        return {"results": rows}
    wired(memory_mem0, answer)
    out = run(make().prime("m", 4000))
    assert [x["id"] for x in out["records"]] == ["a"] and out["tokens"] > 0 and out["truncated"] is False


def test_mem0_reads_a_copy_in_a_scope_of_its_own_and_its_facts_are_about_what_it_linked(wired):
    """What an agent states is kept as stated (infer off); Mem0 also reads a copy (infer on) as agent hr_read, so its
    merging never touches the stated record, and links each fact it draws to the names in it."""
    stated = {"id": "s1", "user_id": "m", "memory": "Caroline went to a support group.", "metadata": memory_mem0.Mem0._meta({"type": "note"}, WRITER)}
    drawn = {"id": "f1", "user_id": "m", "memory": "Caroline attended an LGBTQ support group",
             "metadata": memory_mem0.Mem0._meta({"type": "fact", "references": [{"rel": "derived_from", "memory_id": "m", "record_id": "s1"}]}, {"kind": "provider", "id": "mem0"})}
    calls = []

    def answer(method, path, params, body):
        calls.append((method, path, body))
        if method == "POST" and path.endswith("/memories"):
            return {"results": [{"id": "s1", "event": "ADD"}] if body.get("infer") is False else []}
        if method == "GET" and path.endswith("/memories/s1"):
            return stated
        if method == "GET" and path.endswith("/memories/f1"):
            return drawn
        if method == "GET" and path.endswith("/memories"):
            return {"results": [stated, drawn]}
        if method == "GET" and path.endswith("/hr/entities"):
            return [{"id": "e1", "text": "Caroline", "kind": "PROPER", "memory_ids": ["f1"]}]
        return {"message": "ok"}
    wired(memory_mem0, answer)

    async def go():
        m = memory_mem0.Mem0Server("k", "http://vendor.test")
        rec = await m.remember("m", {"type": "note", "content": [{"type": "text", "text": "Caroline went to a support group."}]}, WRITER)
        await asyncio.gather(*list(memory_mem0._TASKS))
        listed = await m.list("m", {"limit": 50})
        erased = await m.erase("m", ["s1"])
        return rec, listed, erased
    rec, listed, erased = run(go())
    copy = [b for (method, path, b) in calls if method == "POST" and path.endswith("/memories") and b.get("infer") is True]
    assert rec["id"] == "s1" and len(copy) == 1
    assert copy[0]["agent_id"] == "hr_read" and copy[0]["user_id"] == "m" and copy[0]["messages"][0]["content"] == "Caroline went to a support group."
    assert json.loads(copy[0]["metadata"]["hr_refs"]) == [{"rel": "derived_from", "memory_id": "m", "record_id": "s1"}]
    rows = {r["id"]: r for r in listed["records"]}
    assert rows["ment_e1"]["type"] == "entity" and rows["ment_e1"]["title"] == "Caroline" and rows["ment_e1"]["attributes"] == {"kind": "proper"}
    assert {"rel": "about", "memory_id": "m", "record_id": "ment_e1"} in rows["f1"]["references"]
    assert rows["s1"]["references"] == [], "the stated record is as it was stated"
    deletes = [path for (method, path, _b) in calls if method == "DELETE"]
    assert [d.rsplit("/", 1)[1] for d in deletes] == ["f1", "s1"] and erased["erased"] == ["s1"], "what Mem0 drew from it goes first"


def test_mem0s_listing_of_metadata_as_text_does_not_change_what_a_record_says():
    meta = memory_mem0.Mem0._meta({"type": "note", "attributes": {"standing": True, "seats": 15}}, WRITER)
    listed = {k: (str(v) if k in ("standing", "seats") else v) for k, v in meta.items()}
    assert meta["standing"] is True, "the plain key is what mem0 filters on"
    out = memory_mem0.Mem0._out({"id": "a", "memory": "x", "metadata": listed})
    assert out["attributes"] == {"standing": True, "seats": 15}


def test_a_records_link_to_an_entity_is_not_shown_as_a_fact_of_its_own(wired):
    """A fact naming its subject and object made two edges whose only words were "subject" and
    "object", and they were listed, searched and counted as facts."""
    made = []
    said = {"uuid": "e1", "name": "OWNS", "fact": "Dana owns the account.", "source": "n1", "target": "n2", "attributes": {}}

    def answer(method, path, params, body):
        if method == "POST" and path == "/nodes":
            return {"uuid": "n3", "name": "Dana owns it", "attributes": body["attributes"]}
        if method == "POST" and path == "/edges":
            made.append({"uuid": f"l{len(made)}", "source": body["source"], "target": body["target"], **{k: body[k] for k in ("name", "fact", "attributes")}})
            return made[-1]
        if path == "/groups/m/edges":
            return [said, *made]
        if path == "/search":
            return {"edges": [*made, said], "nodes": [], "episodes": []}
        if path in ("/groups/m/nodes", "/groups/m/episodes"):
            return []
        return {}
    wired(memory_graphiti, answer)
    g = memory_graphiti.Graphiti("http://vendor.test", "", ORG)
    rec = run(g.remember("m", {"type": "fact", "title": "Dana owns it", "references": [
        {"rel": "subject", "record_id": "node_n1"}, {"rel": "object", "record_id": "node_n2"}]}, WRITER))
    assert [x["name"] for x in made] == ["subject", "object"] and [x["rel"] for x in rec["references"]] == ["subject", "object"]
    assert [x["id"] for x in run(g.list("m", {"types": ["fact"]}))["records"]] == ["edge_e1"]
    assert [x["record"]["id"] for x in run(g.recall("m", {"query": "subject"}))["results"]] == ["edge_e1"]
    assert run(g.count("m")) == 1


@pytest.mark.parametrize("status,ok", [(200, True), (401, False), (500, False)])
def test_graphitis_check_tries_the_key_not_just_the_address(wired, status, ok):
    w = wired(memory_graphiti, lambda *a: httpx.Response(status, json={}))
    why = run(memory_graphiti.check("k", "http://vendor.test"))
    assert (why == "") is ok
    assert w.calls[0]["path"] == "/check" and w.calls[0]["headers"]["authorization"] == "Bearer k"


# ── ReMe: a memory is a folder, and nothing leaves it ─────────────────────────────────────────
@pytest.mark.parametrize("given,kept", [
    ("", ""), ("notes", "notes"), ("notes/2026", "notes/2026"), ("../../etc", "etc"), ("..", ""),
    ("a/../../b", "a/b"), ("/abs/path", "abs/path"), ("./.hidden", "hidden"), ("a\\..\\b", "a..b"), ("x%2f..", "x2f"),
])
def test_a_folder_named_by_a_writer_stays_inside_the_memory(given, kept):
    assert memory_reme._folder({"folder": given}) == kept


def test_an_episode_is_kept_in_plain_words(wired):
    """A person reads this title in the tree, and markdown there reads as stray asterisks."""
    w = wired(memory_reme, lambda *a: {"success": True, "metadata": {}})
    run(memory_reme.ReMe("http://vendor.test").observe("hmem_a", [{"content": [{"type": "text", "text": "hello", "role": "user"}]}], WRITER))
    assert "user: hello" in w.to("/save")[0]["body"]["content"] and "**" not in w.to("/save")[0]["body"]["content"]


def test_remember_never_writes_outside_the_memorys_folder(wired):
    w = wired(memory_reme, lambda *a: {"success": True, "metadata": {"items": []}})
    r = memory_reme.ReMe("http://vendor.test")
    x = run(r.remember("hmem_a", {"type": "note", "content": [{"type": "text", "text": "x"}], "attributes": {"folder": "../../hmem_b"}}, WRITER))
    saved = [c["body"]["path"] for c in w.to("/save")]
    assert saved and all(p.startswith("digest/hmem_a/") for p in saved), saved
    assert saved[0] == f"digest/hmem_a/hmem_b/{x['id']}.md"


def test_a_search_of_one_memory_never_returns_anothers_file_or_a_kept_version(wired):
    mine, theirs, kept = "digest/hmem_a/hrec_" + "a" * 32 + ".md", "digest/hmem_b/hrec_" + "b" * 32 + ".md", "digest/hmem_a/.history/hrec_c.md"
    reads = []
    def answer(method, path, params, body):
        if path == "/search":
            return {"success": True, "metadata": {"results": [{"path": theirs, "scores": {"keyword": 9}}, {"path": kept, "scores": {"keyword": 9}}, {"path": mine, "scores": {"keyword": 1}}]}}
        if path == "/stat":
            reads.append(body["path"])
            return {"metadata": {"exists": True, "frontmatter": {"hr_type": "note"}}}
        if path == "/load":
            return {"answer": "---\n---\nwords"}
        return {"success": True}
    wired(memory_reme, answer)
    out = run(memory_reme.ReMe("http://vendor.test").recall("hmem_a", {"query": "", "text": "words"}))
    assert [x["record"]["id"] for x in out["results"]] == ["hrec_" + "a" * 32]
    assert reads == [mine], "another memory's file must not even be read"


@pytest.mark.parametrize("rid", ["../hmem_b/hrec_" + "b" * 32, "hrec_short", "", "hrec_" + "Z" * 32])
def test_an_id_that_isnt_ours_is_no_path(wired, rid):
    w = wired(memory_reme, lambda *a: {"success": True})
    assert run(memory_reme.ReMe("http://vendor.test")._path_of("hmem_a", rid)) is None
    assert w.calls == [], "nothing is asked of the server for a made-up id"


@pytest.mark.parametrize("store,signals", [({}, ["text", "filters"]), ({"default": {"is_started": True}}, ["query", "text", "filters"])])
def test_search_by_meaning_is_declared_from_what_this_server_says(wired, monkeypatch, store, signals):
    """Its embeddings are off unless its config turns them on, so a vendor's name can't say."""
    async def creds(org, ws, pid):
        return {"base_url": f"http://vendor.test/{len(store)}"}
    monkeypatch.setattr(mp, "CREDENTIALS", creds)
    monkeypatch.setattr(memory_reme, "_MEANING", {})
    w = wired(memory_reme, lambda *a: {"answer": "ReMe - healthy", "success": True, "metadata": {"health": {"healthy": True, "components": {"embedding_store": store}}}})
    bound = run(memory_reme.ReMe().bind(ORG, "default"))
    assert bound.capabilities()["recall"]["signals"] == signals
    run(memory_reme.ReMe().bind(ORG, "default"))
    assert len(w.calls) == 1, "bind runs on every call, so the answer is kept for a minute"


@pytest.mark.parametrize("by_meaning,counts,said", [
    (False, {"vector": 0, "keyword": 1, "hybrid": False}, True),       # no embeddings on this server
    (False, {"vector": 0, "keyword": 0, "hybrid": False}, True),
    (True, {"vector": 3, "keyword": 0, "hybrid": False}, False),       # measured: only vectors matched, and hybrid is false
    (True, {"vector": 3, "keyword": 1, "hybrid": True}, False),
    (True, {"vector": 0, "keyword": 1, "hybrid": False}, True),        # embeddings failed for this search
    (True, {"vector": 0, "keyword": 0, "hybrid": False}, False),       # nothing there at all
])
def test_a_search_by_meaning_says_when_it_ran_on_words(wired, by_meaning, counts, said):
    wired(memory_reme, lambda *a: {"success": True, "metadata": {"counts": counts, "results": []}})
    out = run(memory_reme.ReMe("http://vendor.test", "", by_meaning).recall("hmem_a", {"query": "exercise habits"}))
    assert ("query:searched_as_words" in out["degraded"]) is said


# ── mem0 on your own server: one memory is one user, checked on every read ────────────────────
def _item(uid):
    return {"id": "r1", "memory": "words", "user_id": uid, "metadata": {}, "created_at": "2026-11-04T00:00:00Z"}


def test_a_record_of_another_memory_is_not_found_through_this_one(wired):
    wired(memory_mem0, lambda *a: _item("hmem_other"))
    m = memory_mem0.Mem0Server("k", "http://vendor.test")
    assert run(m.get("hmem_mine", "r1")) is None
    with pytest.raises(mp.MemoryError) as e:
        run(m.revise("hmem_mine", "r1", {"content": [{"type": "text", "text": "x"}]}, WRITER))
    assert e.value.status == 404
    with pytest.raises(mp.MemoryError):
        run(m.forget("hmem_mine", "r1", WRITER))


def test_an_address_picks_the_self_hosted_server_and_no_address_picks_the_platform(monkeypatch):
    async def creds(org, ws, pid):
        return creds.fields
    monkeypatch.setattr(mp, "CREDENTIALS", creds)
    creds.fields = {"api_key": "k", "base_url": "http://vendor.test/"}
    bound = run(memory_mem0.Mem0().bind(ORG, "default"))
    assert isinstance(bound, memory_mem0.Mem0Server) and bound.base == "http://vendor.test"
    assert bound.capabilities()["recall"]["signals"] == ["query", "filters"], "its server has no search by words"
    creds.fields = {"api_key": "k"}
    bound = run(memory_mem0.Mem0().bind(ORG, "default"))
    assert type(bound) is memory_mem0.Mem0


# ── an id is an id: nothing a caller sends becomes a walk on a vendor's server ───────────────
WALKS = ["../../hmem_b/documents/hrec_x", "hrec_../../hmem_b/documents/hrec_x", "node_../../hmem_b/nodes/x", "..%2f..%2fhmem_b", ".%2e/hmem_b", "x?user_id=hmem_b", "x#y", "x y", "x\\y"]


@pytest.mark.parametrize("rid", WALKS)
@pytest.mark.parametrize("module,make", [
    (memory_hindsight, lambda: memory_hindsight.Hindsight("http://vendor.test")),
    (memory_graphiti, lambda: memory_graphiti.Graphiti("http://vendor.test", "", ORG)),
    (memory_mem0, lambda: memory_mem0.Mem0Server("k", "http://vendor.test")),
    (memory_mem0, lambda: memory_mem0.Mem0("k")),
], ids=["hindsight", "graphiti", "mem0-server", "mem0-platform"])
def test_a_walk_in_a_record_id_never_reaches_the_vendor(wired, module, make, rid):
    w = wired(module, lambda *a: {"id": "x", "uuid": "x", "memory": "stolen", "user_id": "hmem_a", "original_text": "stolen"})
    p = make()
    for act in (lambda: p.get("hmem_a", rid), lambda: p.history("hmem_a", rid),
                lambda: p.revise("hmem_a", rid, {"content": [{"type": "text", "text": "x"}]}, WRITER), lambda: p.forget("hmem_a", rid, WRITER)):
        before = len(w.calls)
        try:
            out = run(act())
        except mp.MemoryError as e:
            assert e.status in (404, 422), str(e)
            out = None
        sent = [c["path"] for c in w.calls[before:]]
        assert not any(".." in x or "%" in x or "hmem_b" in x for x in sent), sent
        assert "stolen" not in json.dumps(out or {}), "an id that is no id reads nothing"


def test_a_plain_id_still_goes_through():
    assert mp.vendor_path("/v1/default/banks/hmem_a/documents/hrec_0a") == "/v1/default/banks/hmem_a/documents/hrec_0a"
    assert mp.vendor_path("/groups/hmem_a/nodes/abda90f0-c7a1-4e1d") == "/groups/hmem_a/nodes/abda90f0-c7a1-4e1d"
    assert mp.vendor_path("/v1/memories/9b9208a9-ca7a-43fb/history/") == "/v1/memories/9b9208a9-ca7a-43fb/history/"


def test_a_principal_is_read_in_time_bounded_by_what_a_real_one_can_be():
    import time
    assert mp._PRINCIPAL.fullmatch("x.acme.team:someone@example.com")
    t0 = time.time()
    assert mp._PRINCIPAL.fullmatch("x." * 200000) is None and mp._PRINCIPAL.fullmatch("x." + "a" * 65 + ":b") is None
    assert time.time() - t0 < 0.2


# ── what the capability document promises is what the routes do ───────────────────────────────
@pytest.mark.parametrize("cls,mode", [(memory_hindsight.Hindsight, "labels"), (memory_graphiti.Graphiti, "guides"),
                                      (memory_reme.ReMe, "none"), (memory_mem0.Mem0, "none"), (memory_mem0.Mem0Server, "none")])
def test_each_vendor_declares_what_reads_a_schema(cls, mode):
    assert cls().capabilities()["schema"]["mode"] == mode


class Declares(memory_fixture.FixtureProvider):
    """The fixture, declaring what a vendor declares."""

    def __init__(self, pid, schema):
        super().__init__()
        self.id, self.schema, self.applied = pid, schema, []

    def capabilities(self):
        return {**super().capabilities(), "id": self.id, "holds": True, "schema": self.schema}

    async def apply_schema(self, mid, schema):
        self.applied.append((mid, schema))


@pytest.fixture(scope="module")
def client():
    mp.PROVIDERS["vguides"] = Declares("vguides", {"mode": "guides", "properties": True, "relations": True})
    mp.PROVIDERS["vlabels"] = Declares("vlabels", {"mode": "labels"})
    mp.PROVIDERS["vnone"] = Declares("vnone", {"mode": "none"})
    try:
        with TestClient(gw.app) as c:
            yield c
    finally:
        for p in ("vguides", "vlabels", "vnone"):
            mp.PROVIDERS.pop(p, None)


def _memory(c, provider):
    return c.post("/v1/memories", headers=ADA, json={"provider": provider, "name": provider}).json()["id"]


def test_a_provider_with_nothing_that_reads_a_schema_refuses_one(client):
    r = client.put(f"/v1/memories/{_memory(client, 'vnone')}/schema", headers=ADA, json={"types": [{"name": "Company"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "memory_unsupported"
    assert mp.PROVIDERS["vnone"].applied == []


def test_labels_take_names_and_refuse_what_nothing_would_read(client):
    mid = _memory(client, "vlabels")
    r = client.put(f"/v1/memories/{mid}/schema", headers=ADA, json={"types": [{"name": "Company", "properties": [{"name": "seats", "type": "number"}]}]})
    assert r.status_code == 422 and "properties" in r.text
    r = client.put(f"/v1/memories/{mid}/schema", headers=ADA, json={"types": [{"name": "A"}, {"name": "B"}], "relations": [{"name": "R", "from": "A", "to": "B"}]})
    assert r.status_code == 422 and "relations" in r.text
    assert mp.PROVIDERS["vlabels"].applied == [], "a refused schema reaches nobody"
    r = client.put(f"/v1/memories/{mid}/schema", headers=ADA, json={"types": [{"name": "Company", "description": "A customer."}]})
    assert r.status_code == 200 and r.json()["applies"] == {"mode": "labels"}
    assert mp.PROVIDERS["vlabels"].applied[-1][0] == mid


def test_a_schema_round_trips_and_reaches_the_provider(client):
    mid = _memory(client, "vguides")
    r = client.put(f"/v1/memories/{mid}/schema", headers=ADA, json=SCHEMA)
    assert r.status_code == 200, r.text
    got = client.get(f"/v1/memories/{mid}/schema", headers=ADA).json()
    assert got["applies"]["mode"] == "guides" and got["types"][0]["properties"][0]["name"] == "seats"
    assert got["relations"][0]["name"] == "BUYS"
    assert mp.PROVIDERS["vguides"].applied[-1][1]["relations"][0]["from"] == "Company"


@pytest.mark.parametrize("bad,word", [
    ({"types": [{"name": "two words"}]}, "one word"),
    ({"types": [{"name": "A"}, {"name": "A"}]}, "Two types"),
    ({"types": [{"name": "A", "properties": [{"name": "p", "type": "colour"}]}]}, "property"),
    ({"types": [{"name": "A"}], "relations": [{"name": "R", "from": "A", "to": "Nowhere"}]}, "must join"),
    ({"types": [{"name": "A"}], "relations": [{"name": "two words", "from": "A", "to": "A"}]}, "one word"),
])
def test_a_schema_is_refused_whole_and_in_words(client, bad, word):
    mid = _memory(client, "vguides")
    before = len(mp.PROVIDERS["vguides"].applied)
    r = client.put(f"/v1/memories/{mid}/schema", headers=ADA, json=bad)
    assert r.status_code == 422 and word in r.json()["error"]["message"], r.text
    assert len(mp.PROVIDERS["vguides"].applied) == before
    assert client.get(f"/v1/memories/{mid}/schema", headers=ADA).json()["types"] == []


# ── what is forgotten stays forgotten ─────────────────────────────────────────────────────────
def _episode_and_fact(client, provider="vguides"):
    mid = _memory(client, provider)
    ep = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "episode", "content": "user: the title is Wren. also Dana runs it."}).json()["id"]
    mk = lambda text: client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "fact", "content": text, "references": [{"rel": "derived_from", "record_id": ep}]}).json()["id"]   # noqa: E731
    return mid, ep, mk("The title is Wren."), mk("Dana runs it.")


def test_forgetting_a_fact_closes_the_conversation_that_taught_it_and_nothing_else(client):
    """Its words are in that conversation, and an agent can't be relied on to know: real turns left just this."""
    mid, ep, title, other = _episode_and_fact(client)
    assert client.delete(f"/v1/memories/{mid}/records/{title}", headers=ADA).status_code == 200
    read = lambda rid: client.get(f"/v1/memories/{mid}/records/{rid}", headers=ADA).json()["status"]   # noqa: E731
    assert read(title) == "forgotten" and read(ep) == "forgotten"
    assert read(other) == "active", "what else it taught stays"
    # forgetting another fact it taught finds it already closed, and that is no error
    assert client.delete(f"/v1/memories/{mid}/records/{other}", headers=ADA).status_code == 200


def test_a_fact_with_no_conversation_behind_it_closes_alone(client):
    mid = _memory(client, "vguides")
    a = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "fact", "content": "A"}).json()["id"]
    note = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "note", "content": "B"}).json()["id"]
    b = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "fact", "content": "C", "references": [{"rel": "derived_from", "record_id": note}]}).json()["id"]
    assert client.delete(f"/v1/memories/{mid}/records/{a}", headers=ADA).status_code == 200
    assert client.delete(f"/v1/memories/{mid}/records/{b}", headers=ADA).status_code == 200
    assert client.get(f"/v1/memories/{mid}/records/{note}", headers=ADA).json()["status"] == "active", "only a conversation closes this way"


def test_hindsights_conversation_closes_without_taking_what_it_taught(wired):
    doc = {"id": "hrec_d", "tags": ["t:episode"], "document_metadata": {}, "original_text": "the title is Wren"}
    patched = []

    def answer(method, path, params, body):
        if path == BANK + "/documents/hrec_d":
            if method == "PATCH":
                patched.append(("doc", body))
                doc["tags"] = body["tags"]
            return doc
        if path.startswith(BANK + "/memories/"):
            patched.append(("fact", path))
        return {}
    wired(memory_hindsight, answer)
    h = memory_hindsight.Hindsight("http://vendor.test")
    run(h.close_episode("m", "hrec_d", WRITER))
    assert patched == [("doc", {"tags": ["t:episode", "forgotten"]})], "its facts aren't touched"
    assert run(h.get("m", "hrec_d"))["status"] == "forgotten"
    run(h.close_episode("m", "hrec_d", WRITER))
    assert len(patched) == 1, "already closed"


def test_hindsight_lists_everything_a_person_has_to_see_to_forget_it(wired):
    """Facts alone hid the conversations and the entities, from the console's tree and from an agent."""
    def answer(method, path, params, body):
        if path == BANK + "/documents":
            return {"items": [{"id": "hrec_ep", "tags": ["t:episode"]}], "total": 1}
        if path == BANK + "/documents/hrec_ep":
            return {"id": "hrec_ep", "tags": ["t:episode"], "document_metadata": {}, "original_text": "said"}
        return _hs(method, path, params, body)
    wired(memory_hindsight, answer)
    h = memory_hindsight.Hindsight("http://vendor.test")
    rows = run(h.list("m", {"limit": 50}))["records"]
    assert [r["type"] for r in rows] == ["episode", "entity", "fact"]
    # the cursor is a position across all three, and pages don't repeat
    first = run(h.list("m", {"limit": 2}))
    assert [r["type"] for r in first["records"]] == ["episode", "entity"] and first["next"] == "2"
    assert [r["type"] for r in run(h.list("m", {"limit": 2, "cursor": first["next"]}))["records"]][-1] == "fact"


def test_an_observation_names_the_records_it_was_drawn_from(wired):
    """Measured 11-06: 172 of a bank's 211 facts were observations, with no document and no entities, so they drew as
    loose dots. Each names its sources; a stated record's own fact is read as that record."""
    units = [
        {"id": "u_s", "text": "Caroline went to a support group", "document_id": "hrec_s", "metadata": {"hr_stated": "1"}, "state": "valid", "fact_type": "world"},
        {"id": "u_w", "text": "Caroline paints", "document_id": "ep_1", "entities": "", "state": "valid", "fact_type": "world"},
        {"id": "u_o", "text": "Caroline finds support in her community", "document_id": None, "entities": "", "state": "valid",
         "fact_type": "observation", "source_memory_ids": ["u_s", "u_w", "u_w"]},
    ]
    def answer(method, path, params, body):
        if path == BANK + "/memories/list":
            return {"items": units, "total": len(units)}
        if path == BANK + "/entities":
            return {"items": [], "total": 0}
        return {}
    wired(memory_hindsight, answer)
    h = memory_hindsight.Hindsight("http://vendor.test")
    rows = run(h.list("m", {"types": ["fact"], "limit": 50}))["records"]
    obs = next(r for r in rows if r["id"] == "u_o")
    assert [r["record_id"] for r in obs["references"] if r["rel"] == "derived_from"] == ["hrec_s", "u_w"], \
        "the stated record as itself, a derived fact as itself, each once"
    assert obs["attributes"]["kind"] == "observation"


@pytest.mark.parametrize("cls", [memory_graphiti.Graphiti, memory_hindsight.Hindsight, memory_mem0.Mem0, memory_mem0.Mem0Server, memory_reme.ReMe])
def test_every_vendor_says_what_it_makes_itself(cls):
    """The part of a memory's schema nobody sets, which the console draws locked: each link joins two of its own types."""
    b = cls().capabilities()["schema"]["builtin"]
    names = [t["name"] for t in b["types"]]
    assert names and len(names) == len(set(names))
    assert set(names) <= {"episode", "entity", "fact", "note"}, "the record types the adapter answers"
    for r in b["relations"]:
        assert r["from"] in names and r["to"] in names, r
        assert r["name"] in ("about", "derived_from"), "the rels its records carry"
    for x in b["types"] + b["relations"]:
        assert x["description"] and "\u2014" not in x["description"] and "\u2013" not in x["description"]


def test_hindsight_reads_a_copy_of_what_is_stated_and_what_it_learns_comes_from_the_record(wired):
    retained, deleted = [], []
    units = [
        {"id": "u_s", "text": "Caroline went to a support group on 7 May 2023", "document_id": "hrec_1", "metadata": {"hr_stated": "1"}, "state": "valid", "fact_type": "world"},
        {"id": "u_x", "text": "Caroline attended an LGBTQ support group", "document_id": "hrx_1", "entities": "Caroline", "metadata": {"hr_read": "hrec_1"}, "state": "valid", "fact_type": "world"},
    ]
    def answer(method, path, params, body):
        if method == "POST" and path == BANK + "/memories":
            retained.append(body)
            return {"success": True}
        if path == BANK + "/memories/list":
            return {"items": units, "total": len(units)}
        if path == BANK + "/entities":
            return {"items": [{"id": "e1", "canonical_name": "Caroline"}], "total": 1}
        if method == "DELETE":
            deleted.append(path.rsplit("/", 1)[1])
            return {}
        if method == "GET" and path.startswith(BANK + "/banks") or path == BANK:
            return {}
        return {}
    wired(memory_hindsight, answer)
    h = memory_hindsight.Hindsight("http://vendor.test")
    h._ready.add("m")
    rec = run(h.remember("m", {"type": "note", "content": [{"type": "text", "text": "Caroline went to a support group on 7 May 2023"}], "time": {"valid_from": "2023-05-07T00:00:00Z"}}, WRITER))
    stated, copy = retained[0]["items"][0], retained[1]["items"][0]
    assert stated["strategy"] == "hr_stated" and retained[0]["async"] is False
    assert copy["document_id"] == "hrx_" + rec["id"][len("hrec_"):] and "strategy" not in copy and retained[1]["async"] is True
    assert copy["tags"] == ["t:read"] and copy["timestamp"] == "2023-05-07T00:00:00Z" and copy["content"] == stated["content"]
    found = next(r for r in run(h.list("m", {"types": ["fact"], "limit": 50}))["records"] if r["id"] == "u_x")
    assert {(x["rel"], x["record_id"]) for x in found["references"]} == {("about", "ent_e1"), ("derived_from", "hrec_1")}, \
        "what Hindsight learned from the copy came from the stated record, and is about who it names"
    run(h.erase("m", ["hrec_1"]))
    assert deleted == ["hrx_1", "hrec_1"], "the copy goes with the record"


def test_a_graphiti_entity_names_the_conversations_that_mention_it():
    g = memory_graphiti.Graphiti("http://vendor.test", "", ORG)
    x = g._node_out("m", {"uuid": "n1", "name": "Acme", "labels": ["Entity"], "attributes": {}, "episodes": ["ep1"]})
    assert {"rel": "derived_from", "memory_id": "m", "record_id": "ep_ep1"} in x["references"]


# ── facts that change, and disagreements ──────────────────────────────────────────────────────
def _fact(c, mid, subject, value, at):
    r = c.post(f"/v1/memories/{mid}/records", headers=ADA, json={
        "type": "fact", "content": f"Lives in {value}", "time": {"valid_from": at},
        "attributes": {"predicate": "home_city", "value": value, "holds": "one"},
        "references": [{"rel": "subject", "record_id": subject}]})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_a_fact_that_holds_one_value_takes_its_place_and_says_what_it_did(client):
    mid = _memory(client, "vguides")
    who = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "entity", "title": "Ada", "content": "A person"}).json()["id"]
    first = _fact(client, mid, who, "Lisbon", "2026-01-01T00:00:00Z")
    assert first["closed"] == [] and first["conflicts"] == []
    second = _fact(client, mid, who, "Porto", "2026-03-01T00:00:00Z")
    assert second["closed"] == [first["id"]] and second["conflicts"] == []
    read = client.get(f"/v1/memories/{mid}/records/{first['id']}", headers=ADA).json()
    assert read["time"]["valid_to"] == "2026-03-01T00:00:00Z"
    # learned late: it lands between them and ends where the next one starts
    between = _fact(client, mid, who, "Faro", "2026-02-01T00:00:00Z")
    assert between["time"]["valid_to"] == "2026-03-01T00:00:00Z"
    # the same instant, another value: nobody can say which is right, so both are kept and marked
    clash = _fact(client, mid, who, "Braga", "2026-03-01T00:00:00Z")
    assert clash["conflicts"] == [second["id"]]
    other = client.get(f"/v1/memories/{mid}/records/{second['id']}", headers=ADA).json()
    assert any(x["rel"] == "contradicts" and x["record_id"] == clash["id"] for x in other["references"])


def test_a_provider_that_doesnt_declare_holds_keeps_the_attributes_as_written(client):
    class Plain(Declares):
        def capabilities(self):
            return {**super().capabilities(), "holds": False}
    mp.PROVIDERS["vplain"] = Plain("vplain", {"mode": "none"})
    try:
        mid = _memory(client, "vplain")
        who = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "entity", "title": "Ada", "content": "A person"}).json()["id"]
        first = _fact(client, mid, who, "Lisbon", "2026-01-01T00:00:00Z")
        second = _fact(client, mid, who, "Porto", "2026-03-01T00:00:00Z")
        assert "closed" not in second and "conflicts" not in second
        assert client.get(f"/v1/memories/{mid}/records/{first['id']}", headers=ADA).json()["time"]["valid_to"] is None
    finally:
        mp.PROVIDERS.pop("vplain", None)


def test_a_disagreement_is_kept_on_both_records_and_a_search_brings_the_other_side(client):
    mid = _memory(client, "vguides")
    a = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "fact", "content": "The lease on Hollin ends in June."}).json()
    b = client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "fact", "content": "It is signed through December, as the owner said.",
                                                                       "references": [{"rel": "contradicts", "record_id": a["id"]}]}).json()
    held = client.get(f"/v1/memories/{mid}/records/{a['id']}", headers=ADA).json()
    assert any(x["rel"] == "contradicts" and x["record_id"] == b["id"] for x in held["references"])
    out = client.post(f"/v1/memories/{mid}/recall", headers=ADA, json={"text": "lease Hollin", "limit": 1}).json()
    ids = {x["record"]["id"]: x for x in out["results"]}
    assert set(ids) == {a["id"], b["id"]}, "one answer must bring the other side, past the limit"
    other = ids[b["id"]]
    assert other["score"] is None and other["why"] == ["contradicts"]


# ── a key held to a workspace stays in it ─────────────────────────────────────────────────────
def _scoped_key(client, ws):
    r = client.post(f"/v1/orgs/{ORG}/keys", headers=ADA, json={"name": "scoped", "workspace": ws, "member_id": "bot@example.com"})
    assert r.status_code == 200, r.text
    return {"authorization": "Bearer " + (r.json().get("key") or r.json().get("token") or r.json()["secret"])}


def test_a_key_held_to_a_workspace_cant_use_anothers_vendor_by_naming_it(client, wired):
    """The plug routes already hold a scoped key to its own workspace, and these routes said they followed them.
    Naming another workspace in the header would have spent that workspace's vendor account."""
    wired(memory_hindsight, lambda *a: {"banks": []})
    assert client.put("/v1/plugs/hindsight", headers={**ADA, "x-harness-workspace": "wsowner"},
                      json={"config": {"base_url": "http://vendor.test"}}).json()["status"] == "connected"
    key = _scoped_key(client, "wsother")
    named = {**key, "x-harness-workspace": "wsowner"}
    caps = {p["id"]: p for p in client.get("/v1/memories/providers", headers=named).json()["data"]}
    assert caps["hindsight"]["connected"] is False, "it reads as its own workspace, whatever it names"
    r = client.post("/v1/memories", headers=named, json={"provider": "hindsight", "name": "Not mine"})
    assert r.status_code >= 400 and "wsowner" not in r.text, r.text
    # the workspace itself still reaches it
    ok = client.post("/v1/memories", headers={**ADA, "x-harness-workspace": "wsowner"}, json={"provider": "hindsight", "name": "Mine"})
    assert ok.status_code in (200, 201), ok.text


def test_what_a_plug_is_connected_on_is_what_a_memory_reads(client, wired):
    """One rule for both. They disagreed for a Default Workspace key, whose plug went to the default workspace
    while its memories looked in its own: connected here, not connected there."""
    r = client.post(f"/v1/orgs/{ORG}/keys", headers=ADA, json={"name": "d", "workspace": "wsdefault", "member_id": "bot@example.com", "workspace_default": True})
    assert r.status_code == 200, r.text
    key = {"authorization": "Bearer " + (r.json().get("key") or r.json().get("token") or r.json()["secret"])}
    wired(memory_reme, lambda *a: {"success": True, "metadata": {"health": {"components": {}}}})
    assert client.put("/v1/plugs/reme", headers=key, json={"config": {"base_url": "http://vendor.test/one-rule"}}).json()["status"] == "connected"
    caps = {p["id"]: p for p in client.get("/v1/memories/providers", headers=key).json()["data"]}
    assert caps["reme"]["connected"] is True


# ── a vendor's connection is tried before it is kept ──────────────────────────────────────────
def test_a_self_hosted_vendor_needs_its_address_and_a_wrong_one_is_refused_with_the_reason(client, wired):
    wired(memory_graphiti, lambda *a: httpx.Response(401, json={}))
    r = client.put("/v1/plugs/graphiti", headers=ADA, json={"config": {"base_url": "http://vendor.test"}, "secrets": {"api_key": SECRET}})
    assert r.status_code == 422 and "401" in r.json()["error"]["message"] and SECRET not in r.text
    caps = {p["id"]: p for p in client.get("/v1/memories/providers", headers=ADA).json()["data"]}
    assert caps["graphiti"]["connected"] is False


def test_a_vendor_connected_shows_connected_and_its_key_never_comes_back(client, wired):
    wired(memory_hindsight, lambda *a: {"banks": []})
    r = client.put("/v1/plugs/hindsight", headers=ADA, json={"config": {"base_url": "http://vendor.test"}, "secrets": {"api_key": SECRET}})
    assert r.status_code == 200 and r.json()["status"] == "connected" and SECRET not in r.text
    caps = {p["id"]: p for p in client.get("/v1/memories/providers", headers=ADA).json()["data"]}
    assert caps["hindsight"]["connected"] is True and SECRET not in json.dumps(caps)


@pytest.mark.parametrize("address", ["http://localhost:8080", "http://127.0.0.1:3000", "http://[::1]:8081"])
def test_this_instance_itself_is_not_a_memory_service(client, wired, address):
    w = wired(memory_reme, lambda *a: {})
    r = client.put("/v1/plugs/reme", headers=ADA, json={"config": {"base_url": address}})
    assert r.status_code == 422 and "this instance" in r.json()["error"]["message"]
    assert w.calls == [], "the address is refused before anything is sent to it"


@pytest.mark.parametrize("address", ["ftp://vendor.test", "http://"])
def test_an_address_that_isnt_one_is_refused(client, wired, address):
    w = wired(memory_hindsight, lambda *a: {})
    r = client.put("/v1/plugs/hindsight", headers=ADA, json={"config": {"base_url": address}})
    assert r.status_code == 422 and w.calls == []


def test_a_vendor_without_an_address_asks_for_one(client):
    r = client.put("/v1/plugs/reme", headers=ADA, json={"secrets": {"api_key": SECRET}})
    assert r.status_code == 422 and "address" in r.json()["error"]["message"]


# ── the Memories list: what each memory's provider makes, as its own workspace reaches it ─────────────
def test_the_list_says_what_each_memorys_provider_makes_where_it_is_kept_and_asks_no_provider(client, wired):
    """A card draws a provider's own concepts. Mem0's own service makes facts and a Mem0 server facts and the names in
    them, so two Mem0 memories in two workspaces draw differently, whichever workspace the list is read from. Without
    counts the list calls no provider at all."""
    w = wired(memory_mem0, lambda *a: {"results": [], "memories": []} if a[0] == "GET" else {})
    for ws, cfg in (("wsplatform", {"secrets": {"api_key": "m0-platform"}}),
                    ("wsserver", {"config": {"base_url": "http://vendor.test"}, "secrets": {"api_key": "m0-server"}})):
        assert client.put("/v1/plugs/mem0", headers={**ADA, "x-harness-workspace": ws}, json=cfg).json()["status"] == "connected"
        r = client.post("/v1/memories", headers={**ADA, "x-harness-workspace": ws}, json={"provider": "mem0", "name": f"Kept in {ws}"})
        assert r.status_code in (200, 201), r.text
    before = len(w.calls)
    got = client.get("/v1/memories", params={"counts": "false"}, headers={**ADA, "x-harness-workspace": "wsplatform"}).json()["data"]
    made = {m["name"]: [t["name"] for t in (m["builtin"] or {}).get("types", [])] for m in got if m["name"].startswith("Kept in ws")}
    assert made == {"Kept in wsplatform": ["fact"], "Kept in wsserver": ["fact", "entity"]}
    assert all(m["records"]["count"] is None for m in got) and len(w.calls) == before, "no provider was called"
