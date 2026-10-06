"""The matrix runner against a world it is given, with a memory server and an agent that are
both in this file: what it adopts, what it forgets, and what keeping a file has to mean before the
`asset` and `document` scenarios pass. No network, no instance."""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matrix  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
AGENT, OWNER = "mem_agent", "mem_owner"


class Service:
    """Five memories, the records in them, and the bytes of their files."""

    def __init__(self):
        self.mem = {k: {"id": f"sp_{k}", "name": k.capitalize() + " room", "provider": "door"} for k in matrix.ROLES}
        self.rec: dict[str, list[dict]] = {m["id"]: [] for m in self.mem.values()}
        self.blob: dict[tuple, bytes] = {}
        self.n = 0
        self.open_to_all = False

    def write(self, mid, who, title="", content=None, kind="fact", **more):
        self.n += 1
        r = {"id": f"r{self.n}", "memory_id": mid, "type": kind, "title": title, "content": content or [], "status": "active",
             "version": 1, "written_by": {"kind": "member", "id": who, "type": "agent" if who == AGENT else "human"}, **more}
        self.rec[mid].append(r)
        return r

    def keep(self, mid, who, name, kind, data, line, title=""):
        r = self.write(mid, who, title=title, kind="note", content=[
            {"type": "file", "file": {"id": f"f{self.n}", "name": name, "media_type": kind, "bytes": len(data)},
             "text": line, "text_source": "stated"}])
        self.blob[(r["id"], 0)] = data
        return r

    def client(self, outsider=False):
        def call(method, path, body=None, timeout=120, raw=False):
            if outsider and not self.open_to_all:
                return 404, {"error": {"code": "memory_not_found"}}
            path = path.split("?")[0]
            p = path.split("/")[3:]                     # after /v1/memories
            if p == ["providers"]:
                return 200, {"data": [{"id": "door", "graph": {"entities": "stated"}}]}
            mid = p[0]
            if mid not in self.rec:
                return 404, {"error": {"code": "memory_not_found"}}
            if len(p) == 1:
                return 200, next(m for m in self.mem.values() if m["id"] == mid)
            if p[1] == "graph":
                return 200, {"nodes": [], "edges": []}
            if len(p) == 2 and method == "GET":
                return 200, {"data": [r for r in self.rec[mid] if r["status"] == "active"]}
            if len(p) == 2:
                return 200, self.write(mid, OWNER, **{"kind" if k == "type" else k: v for k, v in body.items()})
            r = next((r for r in self.rec[mid] if r["id"] == p[2]), None)
            if r is None:
                return 404, {"error": {"code": "record_not_found"}}
            if len(p) == 5:
                data = self.blob.get((r["id"], int(p[4])))
                return (200, data) if data is not None else (404, {"error": {"code": "file_not_found"}})
            if method == "DELETE":
                if r.get("follows"):
                    return 422, {"error": {"code": "memory_unsupported"}}
                r["status"] = "forgotten"
            return 200, r
        return call


class Instance:
    """Tasks, answered by an agent that keeps files the way `how` says."""

    def __init__(self, svc: Service, how: str = "file"):
        self.svc, self.how, self.done, self.deleted = svc, how, {}, []

    def _agent(self, text: str, sid: str) -> str:
        notes = self.svc.mem["notes"]["id"]
        ref = re.search(r"reference: ([A-Z0-9-]+)", text)
        if text.startswith(("Write a file", "Generate a small image")):
            image = text.startswith("Generate")
            data = PNG if image else text.split("\n")[1].encode() + b"\n"
            line = f"{'A lighthouse poster' if image else 'A status note'}, reference {ref.group(1)}."
            if self.how == "words":
                self.svc.write(notes, AGENT, title=line)
            else:
                r = self.svc.keep(notes, AGENT, "poster.png" if image else "status.md", "image/png" if image else "text/markdown", data, line)
                r["made_in"] = sid
            return "Kept."
        if "In an earlier conversation you kept" in text:
            want = "image/" if "kept an image" in text else "text/"
            kept = [p["text"] for r in self.svc.rec[notes] if r["status"] == "active" for p in r["content"]
                    if p.get("type") == "file" and p["file"]["media_type"].startswith(want)]
            return kept[0] if kept else "I have nothing like that in memory."
        return "Done."

    def call(self, method, path, body=None, timeout=120, raw=False):
        if method == "POST" and path == "/v1/responses":
            rid, sid = f"resp_{len(self.done)}", f"sess_{len(self.done)}"
            self.done[rid] = {"id": rid, "status": "completed", "model": "test", "metadata": {"session_id": sid},
                              "output": [{"content": [{"type": "output_text", "text": self._agent(body["input"], sid)}]}]}
            return 200, {"id": rid}
        if method == "GET" and path.startswith("/v1/responses/"):
            return 200, self.done[path.rsplit("/", 1)[1]]
        if method == "DELETE" and path.startswith("/v1/sessions/"):
            sid = path.rsplit("/", 1)[1]
            self.deleted.append(sid)
            if self.how == "tied":                   # the file was only ever the conversation's own
                for recs in self.svc.rec.values():
                    for r in recs:
                        if r.get("made_in") == sid:
                            self.svc.blob.pop((r["id"], 0), None)
            return 200, {}
        return 404, {"error": {"code": "not_found", "message": f"{method} {path}"}}


def _world(**more) -> dict:
    return {"dedicated": True, "memories": {k: f"sp_{k}" for k in matrix.ROLES},
            "agents": [{"base": "claude-code", "harness_id": "har_1", "writer": AGENT}], **more}


def _cell(svc, how="file", outsider=True, **world):
    inst = Instance(svc, how)
    c = matrix.Cell(inst.call, {"id": "door"}, "claude-code", "", lambda s: None, world=_world(**world), m=svc.client(),
                    outsider=svc.client(outsider=True) if outsider else None)
    c.build()
    return c, inst


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(matrix.Cell, "wait", lambda self, check, seconds=0: check())


def test_a_given_world_is_taken_as_it_stands_emptied_and_seeded():
    svc = Service()
    old = svc.write("sp_notes", AGENT, title="left by an earlier run")
    doc = svc.write("sp_archive", OWNER, title="a section of a document", follows={"kind": "document", "id": "d1", "name": "Guide"})
    c, inst = _cell(svc)
    assert old["status"] == "forgotten" and doc["status"] == "active"          # a record that follows a source is not ours
    assert c.name["archive"] == "Archive room" and c.writer == AGENT and c.hid == "har_1"
    assert [r["title"] for r in c.records("vault")] == [f"The vault folder number is {c.word['vault']}"]
    assert c.unserved == {"viewer": "the world names no agent that may only read"}
    c.teardown()                                                              # forgets what the run left; deletes nothing else
    assert c.records("vault") == [] and [r["id"] for r in c.records("archive")] == [doc["id"]] and inst.deleted == []


def test_an_archive_named_by_the_question_itself_is_refused():
    svc = Service()
    svc.mem["archive"]["name"] = "Archive"
    with pytest.raises(RuntimeError, match="a name of its own"):
        _cell(svc)


def test_a_file_the_agent_wrote_is_kept_byte_for_byte_and_found_later():
    svc = Service()
    c, inst = _cell(svc)
    assert matrix.s_document(c) == (True, "")
    assert inst.deleted == ["sess_0"]                    # read again with the conversation that made it deleted
    assert matrix.s_asset(c) == (True, "")


def test_what_the_scenario_says_when_nothing_else_can_check_it():
    svc = Service()
    c, _ = _cell(svc, outsider=False)
    ok, why = matrix.s_document(c)
    assert ok and why == "not read as another organization: the world names none"


def test_words_about_a_file_are_not_the_file():
    c, _ = _cell(Service(), how="words")
    assert matrix.s_document(c) == (False, "the agent kept words about the file and not the file")


def test_a_file_that_goes_with_its_conversation_fails():
    c, _ = _cell(Service(), how="tied")
    ok, why = matrix.s_asset(c)
    assert ok is False and why.startswith("THE FILE WENT WITH THE CONVERSATION THAT MADE IT")


def test_a_file_another_organization_can_read_fails():
    svc = Service()
    svc.open_to_all = True
    c, _ = _cell(svc)
    ok, why = matrix.s_document(c)
    assert ok is False and why.startswith("ANOTHER ORGANIZATION READ THE FILE")


def test_a_scenario_the_world_cannot_be_asked_reads_as_not_applicable_with_its_reason():
    svc = Service()
    inst = Instance(svc)
    row = matrix.run_cell(inst.call, {"id": "door"}, "claude-code", "", ["task_memory", "viewer", "document"], False, lambda s: None,
                          world=_world(not_served={"task_memory": "a task names no memory here"}), m=svc.client(), outsider=svc.client(outsider=True))
    got = {k: (v["ok"], v["why"]) for k, v in row["scenarios"].items()}
    assert got == {"task_memory": (None, "a task names no memory here"), "viewer": (None, "the world names no agent that may only read"),
                   "document": (True, "")}
    assert not row["why"] and matrix.cell_ok(row, ["task_memory", "viewer", "document"])
    assert json.dumps(row)                               # the row is what --out writes
