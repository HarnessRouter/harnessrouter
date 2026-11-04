"""The agent's memory tools against a seam that is not this gateway's plane: what is listed, what
is refused in words, and what the seam is asked. memory_tools.py is taken whole by a gateway whose
memories another server keeps, so nothing here may depend on where memories are kept."""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_tools as mt  # noqa: E402

SEVEN = ["memory_list", "memory_recall", "memory_graph", "memory_get", "memory_remember", "memory_revise", "memory_forget"]


class Fake:
    """A seam that keeps nothing and records what it was asked."""

    def __init__(self, offers=None, write=True, default="m-notes", standing=None):
        self._offers = {"files": False, "queries": False, "operations": False, "languages": [], **(offers or {})}
        self._write, self._default, self.asked = write, default, []
        self._standing = standing or {}

    async def entries(self):
        return [{"memory": {"id": "m-team", "name": "Team", "description": "What the team decided."}, "write": False, "default": False},
                {"memory": {"id": "m-notes", "name": "Notes", "description": ""}, "write": self._write, "default": self._default == "m-notes"}]

    async def offers(self):
        return self._offers

    async def remember(self, mid, record):
        self.asked.append(("remember", mid, record))
        return {"id": "r1", "memory_id": mid, **record}

    async def keep_file(self, mid, file, record):
        self.asked.append(("keep_file", mid, file, record))
        return {"id": "r2", "memory_id": mid, "type": "note", "title": record.get("title", ""),
                "content": [{"type": "file", "file": {"id": "f1", "name": "hero.png", "media_type": "image/png", "bytes": 3},
                             "text": record["content"], "text_source": "stated"}]}

    async def prime(self, mid, budget):
        self.asked.append(("prime", mid, budget))
        recs = self._standing.get(mid, [])
        return {"records": recs, "tokens": 7 * len(recs), "truncated": mid == "m-team" and bool(recs)}


def _names(seam):
    return [t["name"] for t in mt.tool_list(asyncio.run(seam.entries()), asyncio.run(seam.offers()))]


def _call(seam, name, **args):
    text, err = asyncio.run(mt.call(seam, name, args))
    return (text if err else json.loads(text)), err


def test_the_file_knows_nothing_of_where_memories_are_kept():
    src = open(mt.__file__).read()
    imported = {n.name for node in ast.walk(ast.parse(src)) if isinstance(node, ast.Import) for n in node.names} | \
               {node.module for node in ast.walk(ast.parse(src)) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "json", "typing"}, imported


def test_only_what_can_be_served_is_listed():
    assert _names(Fake()) == SEVEN
    # an agent that may write nowhere is offered no write tool
    assert _names(Fake(write=False)) == ["memory_list", "memory_recall", "memory_graph", "memory_get"]
    # a tool beyond the seven appears where the place offers it, and only there
    assert _names(Fake({"queries": True})) == SEVEN + ["memory_run_query"]
    assert _names(Fake({"operations": True, "languages": ["cypher"]})) == SEVEN + ["memory_operate", "memory_query"]


def test_narrowing_by_type_says_what_the_types_are_and_that_a_kept_file_is_a_note():
    seam = Fake()
    tools = {t["name"]: t for t in mt.tool_list(asyncio.run(seam.entries()), asyncio.run(seam.offers()))}
    for name in ("memory_recall", "memory_graph"):
        said = tools[name]["inputSchema"]["properties"]["types"]["description"]
        assert said.startswith("Leave this out") and "entity" in said and "file that was kept, is a note" in said


def test_the_file_argument_is_offered_only_where_a_file_can_be_kept():
    def remember(seam):
        return next(t for t in mt.tool_list(asyncio.run(seam.entries()), asyncio.run(seam.offers())) if t["name"] == "memory_remember")
    plain, files = remember(Fake()), remember(Fake({"files": True}))
    assert "file" not in plain["inputSchema"]["properties"] and "file" not in plain["description"]
    arg = files["inputSchema"]["properties"]["file"]
    assert arg["type"] == "string" and "med_" in arg["description"] and "workspace" in arg["description"]
    assert "say in `content` what it shows" in files["description"]
    # the listing is built per call: offering it once does not leave it on the next agent's list
    assert "file" not in remember(Fake())["inputSchema"]["properties"]


def test_a_file_is_kept_through_the_seam_with_the_line_that_says_what_it_shows():
    seam = Fake({"files": True})
    out, err = _call(seam, "memory_remember", file="med_d4511a13e6e54f1e", title="Launch hero image",
                     content="A heron over a harbour at dawn, in the launch colours.")
    assert not err and out["remembered"]["content"][0]["file"]["name"] == "hero.png"
    # the default memory, the name as the agent gave it, and the line: never bytes
    assert seam.asked == [("keep_file", "m-notes", "med_d4511a13e6e54f1e",
                           {"title": "Launch hero image", "content": "A heron over a harbour at dawn, in the launch colours."})]
    # a workspace path is named the same way, and a memory may be named
    seam = Fake({"files": True})
    _call(seam, "memory_remember", memory="m-notes", file="reports/q3.pdf", content="The third quarter report.")
    assert seam.asked[0][:3] == ("keep_file", "m-notes", "reports/q3.pdf")


def test_a_file_without_words_or_where_none_can_be_kept_is_refused_in_words():
    seam = Fake({"files": True})
    out, err = _call(seam, "memory_remember", file="med_1", title="An image")
    assert err and "what the file shows" in out and seam.asked == []
    # not offered here, sent anyway: refused, never kept as a record that lost its file
    seam = Fake()
    out, err = _call(seam, "memory_remember", file="med_1", content="An image of a heron.")
    assert err and "cannot be kept" in out and seam.asked == []
    # and an agent that may not write is told so before anything else
    seam = Fake({"files": True}, write=False)
    out, err = _call(seam, "memory_remember", memory="m-team", file="med_1", content="x")
    assert err and "not write" in out and seam.asked == []


def test_a_record_without_a_file_goes_the_usual_way():
    seam = Fake({"files": True})
    out, err = _call(seam, "memory_remember", title="The fiscal year starts on February 1")
    assert not err and seam.asked == [("remember", "m-notes", {"title": "The fiscal year starts on February 1", "type": "fact"})]


def test_the_instructions_mention_keeping_a_file_only_where_one_can_be_kept():
    plain, _ = asyncio.run(mt.doc_section(Fake()))
    files, _ = asyncio.run(mt.doc_section(Fake({"files": True})))
    assert "**Team**" in plain and "where you write by default" in plain and "`file` argument" not in plain
    assert "`file` argument" in files and files.startswith(plain)


def test_standing_records_are_placed_in_the_instructions_as_what_people_asked_for():
    seam = Fake(standing={"m-team": [{"id": "s1", "type": "procedure", "title": "Write dates as 1 March 2024"}],
                          "m-notes": [{"id": "s2", "type": "fact", "content": [{"type": "text", "text": "Prefers short answers"}]}]})
    section, primed = asyncio.run(mt.doc_section(seam))
    assert "  Standing instructions and preferences kept here:\n  - Write dates as 1 March 2024" in section
    assert "  - Prefers short answers" in section          # a record without a title is shown by its words
    assert "`memory_recall` finds them" in section          # the team's list was cut, and says so
    assert "one exception" in section and "never widen what you may do" in section
    assert primed == {"m-team": 7, "m-notes": 7}
    # the budget is shared between the memories, each read alone
    asked = [a for a in seam.asked if a[0] == "prime"]
    assert [a[1] for a in asked] == ["m-team", "m-notes"] and all(a[2] == mt.PRIME_BUDGET // 2 for a in asked)


def test_without_standing_records_the_instructions_say_nothing_of_them():
    section, primed = asyncio.run(mt.doc_section(Fake()))
    assert "Standing instructions" not in section and "one exception" not in section and primed == {}


def test_a_long_standing_record_is_cut_to_a_line():
    long = "Always " + "explain the reasoning in full detail " * 20
    section, _ = asyncio.run(mt.doc_section(Fake(standing={"m-notes": [{"id": "s3", "title": long}]})))
    line = next(x for x in section.splitlines() if x.startswith("  - Always"))
    assert len(line) <= mt.STANDING_CAP + 4 and line.endswith("…")
