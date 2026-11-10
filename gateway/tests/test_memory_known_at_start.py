"""What is placed in the Memory section at a turn's start (memory_tools.known_block), from what each engine really
answers a search: the records below are made by each vendor's own adapter from the shapes its server answered on the
test instance (r3, 11-09), not written by hand. Measured there: Graphiti repeated an entity's name ("Quillfeather Labs
Quillfeather Labs cut…"), listed the speaker as an entity ("user Quillfeather Labs cut…") and the raw conversation
("episode-a1488c7e user: …"); Hindsight listed one fact twice; ReMe placed the raw "user: … assistant: …"."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graphiti  # noqa: E402
import memory_hindsight  # noqa: E402
import memory_mem0  # noqa: E402
import memory_reme  # noqa: E402
import memory_tools as mt  # noqa: E402

run = asyncio.run
QUILL = ("Quillfeather Labs cut its Pro plan from 79 to 49 dollars a month and dropped its free tier, signaling a move to "
         "monetize harder and sharpen the offer for paid users.")
TALK = ("user: Quick update for the competitor file: Quillfeather Labs just cut its Pro plan from 79 to 49 dollars a month "
        "and dropped its free tier. Give me a one-line take on what that signals.\nassistant: I'm checking whether there's "
        "any saved context on Quillfeather Labs or the competitor file.")


def _wire(monkeypatch, module, answer):
    def handle(req: httpx.Request) -> httpx.Response:
        out = answer(req.method, req.url.path, dict(req.url.params), json.loads(req.content) if req.content else None)
        return httpx.Response(200, json=out if out is not None else {})
    monkeypatch.setattr(module, "transport", httpx.MockTransport(handle))


def _lines(block: str) -> list[str]:
    """Each finding's words, after the line's "- [where it came from, when] "."""
    rows = block.split("```text\n", 1)[1].rsplit("\n```", 1)[0].splitlines() if block else []
    return [x[2:].split("] ", 1)[1] if x.startswith("- [") else x[2:] for x in rows]


def test_graphiti_says_each_thing_once_never_the_speaker_and_never_the_raw_conversation(monkeypatch):
    def answer(method, path, params, body):
        if path == "/search":       # deploy/memories/graphiti/server.py: edge_out, node_out, episode_out
            return {"edges": [{"uuid": "e1", "name": "CUT_PRICE", "fact": QUILL, "source": "n1", "target": "n2", "episodes": ["ep1"],
                               "attributes": {}, "created_at": "2026-11-09T04:41:20Z", "valid_at": None, "invalid_at": None, "expired_at": None}],
                    "nodes": [{"uuid": "n1", "name": "Quillfeather Labs", "summary": QUILL, "labels": ["Entity", "Organization"],
                               "attributes": {}, "created_at": "2026-11-09T04:41:20Z"},
                              {"uuid": "n2", "name": "user", "summary": QUILL, "labels": ["Entity"], "attributes": {},
                               "created_at": "2026-11-09T04:41:20Z"}],
                    "episodes": [{"uuid": "ep1", "name": "episode-a1488c7e", "content": TALK, "source_description": "member:chrn_x",
                                  "created_at": "2026-11-09T04:41:15Z", "valid_at": "2026-11-09T04:41:15Z"}]}
        if path.endswith("/episodes"):
            return []
        return {}
    _wire(monkeypatch, memory_graphiti, answer)
    found = run(memory_graphiti.Graphiti("http://vendor.test").recall("hmem_g", {"query": "Quillfeather pricing", "limit": 10}))["results"]
    assert {x["record"]["type"] for x in found} == {"fact", "entity", "episode"}, "every kind the server answered reached the block"
    block, n = mt.known_block(found)
    assert _lines(block) == [QUILL] and n == 1
    assert "Quillfeather Labs Quillfeather Labs" not in block and "user Quill" not in block
    assert "episode-" not in block and "user:" not in block


def test_hindsight_says_a_fact_and_its_observation_once(monkeypatch):
    flaky = ("The flaky test in the billing-worker service was caused by a timezone bug in the invoice date parser, "
             "which was fixed by forcing UTC in the parser.")

    def answer(method, path, params, body):
        if path.endswith("/memories/recall"):
            return {"results": [{"id": "u1", "text": flaky, "type": "world", "entities": ["billing-worker"], "document_id": "doc1",
                                 "scores": {"semantic": 0.8, "final": 0.8}},
                                {"id": "o1", "text": flaky, "type": "observation", "source_memory_ids": ["u1"],
                                 "scores": {"semantic": 0.7, "final": 0.7}}]}
        if path.endswith("/entities"):
            return {"items": [{"id": "e1", "canonical_name": "billing-worker"}], "total": 1}
        if path.endswith("/memories/list"):
            return {"items": [{"id": "u1", "document_id": "doc1"}], "total": 1}
        return {}
    _wire(monkeypatch, memory_hindsight, answer)
    found = run(memory_hindsight.Hindsight("http://vendor.test").recall("hmem_h", {"query": "flaky test", "limit": 10}))["results"]
    assert len(found) == 2 and found[1]["record"]["attributes"].get("kind") == "observation"
    block, n = mt.known_block(found)
    assert _lines(block) == [flaky] and n == 1


def test_reme_places_its_note_and_not_the_raw_conversation(monkeypatch):
    note = "digest/hmem_r/notes/hrec_" + "a" * 32 + ".md"
    episode = "digest/hmem_r/episodes/hrec_" + "b" * 32 + ".md"
    talk = ("user: Handbook policy update: everyone gets the first Friday of every month off as a focus day, starting in "
            "December. Reply with a one-line summary of the policy.\n\nassistant: I'm checking the available memory tools.")
    files = {note: ({"hr_id": "hrec_" + "a" * 32, "hr_type": "note", "hr_title": "First Friday focus day policy", "hr_status": "active"},
                    "Everyone gets the first Friday of every month off as a focus day, starting in December."),
             episode: ({"hr_id": "hrec_" + "b" * 32, "hr_type": "episode", "hr_status": "active"}, talk)}

    def answer(method, path, params, body):
        if path == "/search":
            return {"success": True, "metadata": {"counts": {"vector": 2, "keyword": 2}, "results": [
                {"path": episode, "scores": {"score": 0.9, "vector": 0.9}}, {"path": note, "scores": {"score": 0.8, "vector": 0.8}}]}}
        if path == "/stat":
            front, _ = files[body["path"]]
            return {"metadata": {"exists": True, "frontmatter": front}}
        if path == "/load":
            front, said = files[body["path"]]
            return {"answer": "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in front.items()) + "\n---\n\n" + said}
        return {"success": True}
    _wire(monkeypatch, memory_reme, answer)
    found = run(memory_reme.ReMe("http://vendor.test", "", True).recall("hmem_r", {"query": "focus day", "limit": 10}))["results"]
    assert [x["record"]["type"] for x in found] == ["episode", "note"], "the raw conversation ranked first"
    block, n = mt.known_block(found)
    assert _lines(block) == ["First Friday focus day policy: Everyone gets the first Friday of every month off as a focus day, "
                             "starting in December."] and n == 1
    assert "user:" not in block and "assistant:" not in block


def test_mem0_says_the_same_fact_once_however_it_is_cased_or_ended(monkeypatch):
    def answer(method, path, params, body):
        if path == "/search":
            return {"results": [{"id": "r1", "memory": "User is allergic to sesame", "user_id": "hmem_m", "metadata": {}, "score": 0.9,
                                 "created_at": "2026-11-09T04:41:20Z"},
                                {"id": "r2", "memory": "user is allergic to sesame.", "user_id": "hmem_m", "metadata": {}, "score": 0.8,
                                 "created_at": "2026-11-09T04:42:20Z"},
                                {"id": "r3", "memory": "User's name is Bob", "user_id": "hmem_m", "metadata": {}, "score": 0.7,
                                 "created_at": "2026-11-09T04:42:20Z"}]}
        if path == "/hr/entities":
            return []
        return {}
    _wire(monkeypatch, memory_mem0, answer)
    found = run(memory_mem0.Mem0Server("k", "http://vendor.test").recall("hmem_m", {"query": "allergies", "limit": 10}))["results"]
    block, n = mt.known_block(found)
    assert _lines(block) == ["User is allergic to sesame", "User's name is Bob"] and n == 2


def test_a_raw_conversation_is_placed_only_when_nothing_else_was_found_and_each_line_is_short():
    talk = {"record": {"id": "ep1", "type": "episode", "title": "episode-a1488c7e", "content": [{"type": "text", "text": TALK}]}}
    block, n = mt.known_block([talk])
    assert n == 1 and _lines(block)[0].startswith("user: Quick update") and "episode-" not in block
    assert len(_lines(block)[0]) <= mt.RECALL_AT_START_EXCERPT
    # an entity that is only a name says nothing; a title its words begin with is said once
    named = {"record": {"id": "x", "type": "entity", "title": "Globex", "content": []}}
    titled = {"record": {"id": "y", "type": "entity", "title": "Dana", "content": [{"type": "text", "text": "Dana runs the Lisbon office."}]}}
    block, n = mt.known_block([named, titled])
    assert _lines(block) == ["Dana runs the Lisbon office."] and n == 1


def test_more_is_asked_than_is_placed_so_what_is_let_go_leaves_room():
    class Seam:
        asked: list = []

        async def entries(self):
            return [{"memory": {"id": "m1"}, "default": True}]

        async def recall(self, mid, body):
            self.asked.append(body)
            return {"results": []}
    seam = Seam()
    run(mt.recall_at_start(seam, "what do you know"))
    assert seam.asked == [{"query": "what do you know", "limit": mt.RECALL_AT_START_ASK}]
    assert mt.RECALL_AT_START_ASK > mt.RECALL_AT_START_LIMIT
