"""The mem0 adapter against a stand-in that answers the shapes the real service answered on
2026-10-04 (test_memory_mem0_live.py runs the same behaviour against mem0 itself). What is pinned
here is the adapter's own conduct: the memory's id rides every search and listing, a record of
another memory is not found by its id, the key never leaves in an answer, what mem0 cannot do is
said in `degraded`, and an erase names what mem0 still holds."""
from __future__ import annotations

import json
import os
import sys
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_mem0  # noqa: E402

ORG, KEY = "mem0org", "m0-SENTINEL-never-returned"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}


class Mem0Stub:
    """mem0's Platform API, as far as the adapter uses it."""

    def __init__(self):
        self.mem: dict[str, dict] = {}
        self.hist: dict[str, list] = {}
        self.events: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict]] = []

    def _item(self, m):
        return {k: m[k] for k in ("id", "memory", "user_id", "metadata", "created_at", "updated_at", "expiration_date")}

    def _scope(self, flt) -> tuple[str, list[dict]]:
        clauses = flt.get("AND") if "AND" in flt else [flt]
        return next(c["user_id"] for c in clauses if "user_id" in c), [c for c in clauses if "user_id" not in c]

    def _keep(self, m, clauses) -> bool:
        for c in clauses:
            if "metadata" in c:
                for k, v in c["metadata"].items():
                    if isinstance(v, dict):
                        raise ValueError("Unsupported metadata operator")
                    if m["metadata"].get(k) != v:
                        return False
            if "OR" in c and not any(self._keep(m, [x]) for x in c["OR"]):
                return False
        return True

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, body = req.url.path, json.loads(req.content or b"{}")
        self.calls.append((req.method, path, body))
        if req.headers.get("authorization") != f"Token {KEY}":
            return httpx.Response(401, json={"detail": "Invalid API key"})
        if path == "/v1/ping/":
            return httpx.Response(200, json={"status": "ok"})
        now = f"2026-10-04T10:00:{len(self.calls):02d}.000000+00:00"
        if path == "/v3/memories/add/":
            def store(text):
                mid = str(uuid.uuid4())
                self.mem[mid] = {"id": mid, "memory": text, "user_id": body["user_id"], "metadata": dict(body.get("metadata") or {}),
                                 "created_at": now, "updated_at": now, "expiration_date": None}
                self.hist[mid] = [{"event": "ADD", "old_memory": None, "new_memory": text, "updated_at": now}]
                return mid
            if body.get("infer") is False:
                mid = store(body["messages"][0]["content"])
                return httpx.Response(200, json={"status": "SUCCEEDED", "event_id": "e", "results": [{"id": mid, "event": "ADD"}]})
            ev = str(uuid.uuid4())                       # "extraction": one fact per sentence of the user's message
            ids = [store("User said: " + s.strip()) for s in body["messages"][0]["content"].split(".") if s.strip()]
            self.events[ev] = {"id": ev, "status": "SUCCEEDED", "payload": {"user_id": body["user_id"]},
                               "results": [{"id": i, "event": "ADD"} for i in ids]}
            return httpx.Response(200, json={"event_id": ev, "status": "PENDING"})
        if path.startswith("/v1/event/"):
            ev = self.events.get(path.split("/")[3])
            return httpx.Response(200, json=ev) if ev else httpx.Response(404, json={})
        if path in ("/v3/memories/search/", "/v3/memories/"):
            try:
                user, clauses = self._scope(body["filters"])
                rows = [m for m in self.mem.values() if m["user_id"] == user and self._keep(m, clauses)
                        and (body.get("show_expired") or not m["expiration_date"])]
            except ValueError as e:
                return httpx.Response(400, json={"error": str(e)})
            if path == "/v3/memories/":
                return httpx.Response(200, json={"count": len(rows), "next": None, "results": [self._item(m) for m in rows]})
            q = set(body["query"].lower().split())
            out = []
            for m in rows:
                bm = len(q & set(m["memory"].lower().replace(".", "").split())) / max(len(q), 1)
                out.append({**self._item(m), "score": round(0.3 + bm / 2, 4), "score_breakdown": {"semantic": 0.5, "bm25": bm, "entity": 0.0}})
            return httpx.Response(200, json={"results": sorted(out, key=lambda x: -x["score"])[: body.get("top_k", 10)]})
        if path == "/v1/memories/" and req.method == "DELETE":
            for k in [k for k, m in self.mem.items() if m["user_id"] == req.url.params["user_id"]]:
                del self.mem[k]
            return httpx.Response(200, json={"message": "Delete in progress."})
        rid = path.split("/")[3]
        if path.endswith("/history/"):                   # served even after the memory is deleted
            return httpx.Response(200, json=[{**h, "memory_id": rid} for h in self.hist.get(rid, [])])
        m = self.mem.get(rid)
        if not m:
            return httpx.Response(404, json={"error": "Memory not found!"})
        if req.method == "PUT":
            if "text" in body:
                self.hist[rid].append({"event": "UPDATE", "old_memory": m["memory"], "new_memory": body["text"], "updated_at": now})
                m["memory"] = body["text"]
            m["metadata"] = body.get("metadata", m["metadata"])
            m["expiration_date"] = body.get("expiration_date", m["expiration_date"])
            m["updated_at"] = now
        if req.method == "DELETE":
            del self.mem[rid]
            return httpx.Response(200, json={"message": "Memory deleted successfully!"})
        return httpx.Response(200, json=self._item(m))


@pytest.fixture(scope="module")
def world():
    stub = Mem0Stub()
    memory_mem0.transport = httpx.MockTransport(stub)
    try:
        with TestClient(gw.app) as c:
            r = c.put("/v1/plugs/mem0", headers=ADA, json={"secrets": {"api_key": KEY}})
            assert r.json()["status"] == "connected" and KEY not in r.text
            a = c.post("/v1/memories", headers=ADA, json={"provider": "mem0", "name": "A"}).json()["id"]
            b = c.post("/v1/memories", headers=ADA, json={"provider": "mem0", "name": "B"}).json()["id"]
            yield c, stub, a, b
    finally:
        memory_mem0.transport = None


def test_the_provider_is_connected_like_a_plug_and_listed_apart_from_tool_plugs(world):
    c, _, _, _ = world
    assert "mem0" not in [p["type"] for p in c.get("/v1/plugs", headers=ADA).json()["plugs"]]
    row = c.get("/v1/plugs?kind=memory", headers=ADA).json()["plugs"][0]
    assert row["type"] == "mem0" and row["status"] == "connected" and row["secrets_set"] == ["api_key"]
    other = {**ADA, "x-harness-workspace": "elsewhere"}
    r = c.post("/v1/memories", headers=other, json={"provider": "mem0", "name": "x"})
    assert r.status_code == 503 and "not connected for this workspace" in r.json()["error"]["message"]


def test_every_search_and_listing_carries_the_memorys_id_and_nothing_can_remove_it(world):
    c, stub, a, b = world
    ra = c.post(f"/v1/memories/{a}/records", headers=ADA, json={"type": "fact", "content": "Alpha ships on Friday.", "attributes": {"k": "v"}}).json()
    rb = c.post(f"/v1/memories/{b}/records", headers=ADA, json={"type": "note", "content": "Beta ships on Monday."}).json()
    stub.calls.clear()
    got = c.post(f"/v1/memories/{a}/recall", headers=ADA, json={"query": "what ships", "filters": {
        "or": [{"field": "attributes.k", "op": "eq", "value": "v"}, {"field": "attributes.user_id", "op": "eq", "value": b}]}}).json()
    assert [x["record"]["id"] for x in got["results"]] == [ra["id"]] and got["degraded"] == ["filters:applied_after_ranking"]
    c.get(f"/v1/memories/{a}/records?type=fact", headers=ADA)
    sent = [body["filters"] for _, path, body in stub.calls if path in ("/v3/memories/search/", "/v3/memories/")]
    assert sent and all((f.get("AND") or [f])[0] == {"user_id": a} for f in sent)
    # a record of B, asked for through A by its id
    for call in (c.get(f"/v1/memories/{a}/records/{rb['id']}", headers=ADA),
                 c.patch(f"/v1/memories/{a}/records/{rb['id']}", headers=ADA, json={"content": "x"}),
                 c.delete(f"/v1/memories/{a}/records/{rb['id']}", headers=ADA),
                 c.get(f"/v1/memories/{a}/records/{rb['id']}/history", headers=ADA)):
        assert call.status_code == 404 and call.json()["error"]["code"] == "memory_record_not_found"
    assert c.post(f"/v1/memories/{a}/erase", headers=ADA, json={"record_ids": [rb["id"]]}).json()["erased"] == []
    assert c.get(f"/v1/memories/{b}/records/{rb['id']}", headers=ADA).json()["content"] == [{"type": "text", "text": "Beta ships on Monday."}]


def test_what_the_gateway_stamped_survives_the_round_trip_and_the_key_never_does(world):
    c, stub, a, _ = world
    r = c.post(f"/v1/memories/{a}/records", headers=ADA, json={
        "type": "procedure", "content": [{"type": "text", "text": "Ask."}, {"type": "text", "text": "Confirm."}],
        "attributes": {"hr_writer_id": "forged", "team": "x"},
        "references": [{"rel": "derived_from", "record_id": "some-id"}], "time": {"valid_from": "2026-01-01"}})
    rec = r.json()
    assert rec["type"] == "procedure" and rec["written_by"] == {"kind": "member", "id": "ada@example.com"}
    assert rec["attributes"] == {"team": "x"} and rec["time"]["valid_from"] == "2026-01-01"
    assert rec["references"][0]["record_id"] == "some-id"
    assert rec["content"] == [{"type": "text", "text": "Ask.\nConfirm."}]        # mem0 keeps one text per memory
    assert KEY not in r.text and KEY not in c.get("/v1/memories/providers", headers=ADA).text


def test_observe_is_a_job_whose_records_are_the_facts_mem0_derived(world):
    c, _, a, b = world
    r = c.post(f"/v1/memories/{a}/observe", headers=ADA, json={"episodes": [
        {"content": [{"type": "text", "role": "user", "text": "I moved to Austin. My dog is Max."},
                     {"type": "text", "role": "assistant", "text": "Noted."}], "attributes": {"session_id": "s1"}}]})
    assert r.status_code == 202 and r.json()["data"] == []
    job = c.get(f"/v1/memories/{a}/jobs/{r.json()['job']['id']}", headers=ADA).json()
    assert job["status"] == "completed" and [x["content"][0]["text"] for x in job["data"]] == ["User said: I moved to Austin", "User said: My dog is Max"]
    assert all(x["written_by"] == {"kind": "provider", "id": "mem0", "observed_by": "member:ada@example.com"} for x in job["data"])
    assert c.get(f"/v1/memories/{b}/jobs/{r.json()['job']['id']}", headers=ADA).status_code == 404


def test_forget_is_mem0s_expiry_and_erase_names_what_it_still_serves(world):
    c, stub, a, _ = world
    rid = c.post(f"/v1/memories/{a}/records", headers=ADA, json={"type": "fact", "content": "Gamma is cancelled."}).json()["id"]
    c.patch(f"/v1/memories/{a}/records/{rid}", headers=ADA, json={"content": "Gamma is postponed."})
    hist = c.get(f"/v1/memories/{a}/records/{rid}/history", headers=ADA).json()["data"]
    assert [(h["version"], h["status"], h["content"][0]["text"]) for h in hist] == [(1, "superseded", "Gamma is cancelled."), (2, "active", "Gamma is postponed.")]
    assert c.delete(f"/v1/memories/{a}/records/{rid}", headers=ADA).json()["status"] == "forgotten"
    assert stub.mem[rid]["expiration_date"] < "2026-10-05" and rid in stub.mem           # closed, still stored
    assert rid not in [x["record"]["id"] for x in c.post(f"/v1/memories/{a}/recall", headers=ADA, json={"query": "Gamma"}).json()["results"]]
    out = c.post(f"/v1/memories/{a}/erase", headers=ADA, json={"record_ids": [rid]}).json()
    assert out["erased"] == [rid] and out["unreachable"] == [rid] and rid not in stub.mem and stub.hist[rid]


def test_deleting_a_memory_removes_its_scope_at_mem0(world):
    c, stub, _, b = world
    assert any(m["user_id"] == b for m in stub.mem.values())
    c.delete(f"/v1/memories/{b}", headers=ADA)
    assert not any(m["user_id"] == b for m in stub.mem.values())


def test_mem0_keeps_text_and_a_file_part_is_refused_not_dropped(world):
    c, stub, a, _ = world
    caps = next(p for p in c.get("/v1/memories/providers", headers=ADA).json()["data"] if p["id"] == "mem0")
    assert caps["content"] == {"media": ["text/*"], "describes": []}
    up = c.post("/v1/files", headers=ADA, files={"file": ("chart.png", b"\x89PNG\r\n\x1a\n", "image/png")}, data={"purpose": "user_data"})
    before = len(stub.mem)
    r = c.post(f"/v1/memories/{a}/records", headers=ADA, json={"content": [
        {"type": "text", "text": "Q3 chart."}, {"type": "file", "file": {"id": up.json()["id"]}, "text": "Revenue up 12%."}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "memory_unsupported"
    assert "image/png" in r.json()["error"]["message"] and len(stub.mem) == before          # nothing half-written
    # several text parts are one mem0 memory, and read back as one text part
    ok = c.post(f"/v1/memories/{a}/records", headers=ADA, json={"content": [
        {"type": "text", "text": "Q3 revenue rose."}, {"type": "text", "text": "Churn fell."}]}).json()
    assert ok["content"] == [{"type": "text", "text": "Q3 revenue rose.\nChurn fell."}]
