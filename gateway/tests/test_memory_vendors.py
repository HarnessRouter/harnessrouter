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
    item = w.to("/memories")[-1]["body"]["items"][0]
    assert item["strategy"] == memory_hindsight.STATED and item["document_id"] == x["id"] and x["id"].startswith("hrec_")
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
