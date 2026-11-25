"""Revising or forgetting a record on Graphiti never deletes the record.

Graphiti reads a copy of each stated record as an episode, and its extraction can link the record's own node to that
copy. Graphiti's remove_episode deletes a node only the removed episode mentions, so replacing a record's copy (a
revision) or dropping it (forget) deleted the record once the copy had been read: the PATCH answered 200 and the
record was gone (UHP conformance ME-05 and ME-06, measured on a live instance).

Our Graphiti server now cuts those links before it removes an episode, and says so on /healthz
(keeps_stated_records). The gateway deletes a record's old copies only on a server that says so; on one that predates
it, it forgets them, which keeps the record. An erase deletes them either way. Driven against a fake server here; the
server's own change is read from its source, as test_memory_old_engine_servers does, since its graphiti-core is not
installed in this suite."""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graphiti as mg  # noqa: E402

run = asyncio.run
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MID, U, EP = "hmem_keep", "0b6a0d5e-1111-4222-8333-444455556666", "ep-copy-1"
WRITER = {"kind": "member", "id": "ada@example.com"}


def _node(text: str) -> dict:
    return {"uuid": U, "name": text[:120], "summary": text, "labels": ["Entity"], "group_id": MID,
            "created_at": "2026-11-15T08:00:00Z", "episodes": [EP],
            "attributes": {"hr_stated": "1", "hr_type": "fact", "hr_version": 1, "hr_written_at": "2026-11-15T08:00:00Z",
                           "hr_text": text, "hr_attributes": "{}", "hr_refs": "[]",
                           "hr_writer": json.dumps(WRITER)}}


def _engine(monkeypatch, keeps: bool) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    state = {"node": _node("Quillon Freight renews its contract every March.")}

    def handle(req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        calls.append((m, path))
        if path.endswith("/healthz"):
            return httpx.Response(200, json={"ok": True, **({"keeps_stated_records": True} if keeps else {})})
        if path.endswith(f"/groups/{MID}/pending"):
            return httpx.Response(200, json={"pending": 0})      # nothing left to read in the background
        if path.endswith(f"/groups/{MID}/episodes") and m == "GET":
            return httpx.Response(200, json=[{"uuid": EP, "name": mg.READ + U, "content": "Quillon Freight renews its contract every March.",
                                              "created_at": "2026-11-15T08:00:01Z", "group_id": MID}])
        if path.endswith(f"/groups/{MID}/nodes/{U}"):
            if m == "DELETE":
                state["gone"] = True
                return httpx.Response(200, json={"deleted": U})
            if state.get("gone"):
                return httpx.Response(404, json={"detail": "no such node"})     # a deleted node reads gone, as on our server
            if m == "PUT":
                b = json.loads(req.content)
                state["node"] = {**state["node"], "name": b.get("name"), "summary": b.get("summary"), "attributes": b.get("attributes")}
            return httpx.Response(200, json=state["node"])
        return httpx.Response(200, json={"uuid": "ep-new", "deleted": True, "ok": True})

    monkeypatch.setattr(mg, "transport", httpx.MockTransport(handle))
    mg._KEEPS.clear()
    return calls


def _copy_calls(calls) -> list[tuple[str, str]]:
    return [(m, p) for m, p in calls if f"/episodes/{EP}" in p]


@pytest.mark.parametrize("keeps", [True, False])
def test_a_revision_keeps_the_record_on_either_server(monkeypatch, keeps):
    calls = _engine(monkeypatch, keeps)
    out = run(mg.Graphiti("http://graphiti.test", "k").revise(
        MID, mg.NODE + U, {"content": [{"type": "text", "text": "Quillon Freight renews its contract every April."}]}, WRITER))
    assert out["id"] == mg.NODE + U and out["version"] == 2
    copies = _copy_calls(calls)
    if keeps:
        assert copies == [("DELETE", f"/groups/{MID}/episodes/{EP}")]           # what it taught goes with it
    else:
        assert copies == [("POST", f"/groups/{MID}/episodes/{EP}/forget")]      # forgotten: the old server keeps the node
    assert not any(m == "DELETE" and "/nodes/" in p for m, p in calls)


@pytest.mark.parametrize("keeps", [True, False])
def test_forgetting_a_record_keeps_its_trace_on_either_server(monkeypatch, keeps):
    calls = _engine(monkeypatch, keeps)
    out = run(mg.Graphiti("http://graphiti.test", "k").forget(MID, mg.NODE + U, WRITER))
    assert out["status"] == "forgotten"
    assert _copy_calls(calls) == ([("DELETE", f"/groups/{MID}/episodes/{EP}")] if keeps
                                  else [("POST", f"/groups/{MID}/episodes/{EP}/forget")])


def test_an_erase_deletes_the_copy_even_on_an_old_server(monkeypatch):
    calls = _engine(monkeypatch, keeps=False)
    out = run(mg.Graphiti("http://graphiti.test", "k").erase(MID, [mg.NODE + U]))
    assert out["erased"] == [mg.NODE + U]
    assert ("DELETE", f"/groups/{MID}/episodes/{EP}") in calls and ("DELETE", f"/groups/{MID}/nodes/{U}") in calls
    assert ("POST", f"/groups/{MID}/episodes/{EP}/forget") not in calls      # a forgotten copy keeps its words


def test_what_a_server_says_is_read_once_in_a_while(monkeypatch):
    calls = _engine(monkeypatch, keeps=True)
    g = mg.Graphiti("http://graphiti.test", "k")
    assert run(g._keeps_stated()) and run(g._keeps_stated())
    assert sum(1 for _, p in calls if p.endswith("/healthz")) == 1


def test_our_server_cuts_a_stated_records_links_before_it_removes_an_episode():
    src = open(os.path.join(ROOT, "deploy", "memories", "graphiti", "server.py")).read()
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    body = ast.get_source_segment(src, fns["del_episode"])
    assert body.index("keep_stated(g, uid)") < body.index("remove_episode(uid)")
    keep = ast.get_source_segment(src, fns["keep_stated"])
    assert "hr_stated" in keep and "MENTIONS" in keep and "DELETE r" in keep
    assert '"keeps_stated_records": True' in ast.get_source_segment(src, fns["healthz"])


# ── a field of our own is never something extraction fills ──────────────────────────────────────────────────────────
import memory_plane as mp  # noqa: E402


@pytest.mark.parametrize("schema", [
    {"types": [{"name": "Account", "properties": [{"name": "hr_stated", "type": "text"}]}]},
    {"types": [{"name": "Account", "properties": [{"name": "HR_text", "type": "text"}]}]},
    {"types": [{"name": "hr_Account", "properties": []}]},
])
def test_a_schema_never_names_one_of_our_own_fields(schema):
    with pytest.raises(mp.MemoryError) as e:
        mp.schema_clean(schema)
    assert e.value.status == 422 and "reserved for HarnessRouter's own fields" in e.value.message
    ok = mp.schema_clean({"types": [{"name": "Account", "properties": [{"name": "region", "type": "text"}]}]})
    assert ok["types"][0]["properties"][0]["name"] == "region"


def test_our_server_never_extracts_into_one_of_our_fields_and_keeps_only_records_we_stated():
    src = open(os.path.join(ROOT, "deploy", "memories", "graphiti", "server.py")).read()
    tree = ast.parse(src)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert 'fname.lower().startswith("hr_")' in ast.get_source_segment(src, fns["models_of"])   # a schema stored before
    assert '.get("hr_stated") == "1"' in ast.get_source_segment(src, fns["keep_stated"])
