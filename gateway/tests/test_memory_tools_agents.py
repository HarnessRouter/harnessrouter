"""What agent CLIs actually send the memory tools, measured running LoCoMo through dsh agents (2026-11-06), and what
each used to cost them: a numeric or list argument sent as a string, a read that names no memory, a recall that asks
for nothing in particular (an agent listing what it holds), and a record named by an empty id."""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_tools as mt  # noqa: E402
from test_memory_tools_seam import Fake  # noqa: E402


class Reading(Fake):
    async def recall(self, mid, body):
        self.asked.append(("recall", mid, body))
        return {"results": [], "degraded": []}

    async def graph(self, mid, body):
        self.asked.append(("graph", mid, body))
        return {"nodes": [], "edges": []}

    async def get(self, mid, rid):
        self.asked.append(("get", mid, rid))
        return None


class OneMemory(Reading):
    async def entries(self):
        return [{"memory": {"id": "m-only", "name": "Only", "description": ""}, "write": False, "default": False}]


def call(seam, name, **args):
    return asyncio.run(mt.call(seam, name, args))


def test_numbers_and_lists_sent_as_strings_are_read_as_what_they_say():
    seam = Reading()
    text, err = call(seam, "memory_recall", memory="m-notes", query="support group", limit="50", depth="3", types="['entity']")
    assert not err, text
    _, mid, body = seam.asked[-1]
    assert body["limit"] == 50 and body["depth"] == 3 and body["types"] == ["entity"]
    call(seam, "memory_recall", memory="m-notes", query="x", types='["fact", "entity"]')
    assert seam.asked[-1][2]["types"] == ["fact", "entity"]
    call(seam, "memory_recall", memory="m-notes", query="x", types="entity, fact")
    assert seam.asked[-1][2]["types"] == ["entity", "fact"]


def test_attributes_sent_as_a_json_string_are_an_object():
    seam = Fake()
    text, err = call(seam, "memory_remember", title="Caroline", type="entity", attributes='{"kind": "person"}')
    assert not err, text
    assert seam.asked[-1][2]["attributes"] == {"kind": "person"}


def test_a_read_naming_no_memory_reads_the_default_one():
    seam = Reading()
    text, err = call(seam, "memory_recall", query="Caroline")
    assert not err, text
    assert seam.asked[-1][:2] == ("recall", "m-notes")


def test_a_read_naming_no_memory_reads_the_only_one():
    seam = OneMemory()
    text, err = call(seam, "memory_recall", query="Caroline")
    assert not err, text
    assert seam.asked[-1][:2] == ("recall", "m-only")


def test_with_no_default_and_several_memories_it_names_them():
    seam = Reading(default="")
    text, err = call(seam, "memory_recall", query="Caroline")
    assert err and "m-team" in text and "m-notes" in text and not seam.asked


def test_a_recall_asking_for_nothing_lists_what_is_held_of_the_types_named():
    seam = Reading()
    text, err = call(seam, "memory_recall", memory="m-notes", types=["entity"], limit=10)
    assert not err, text
    body = seam.asked[-1][2]
    assert body["filters"] == {"field": "status", "op": "eq", "value": "active"} and body["types"] == ["entity"] and body["limit"] == 10
    text, err = call(seam, "memory_recall", memory="m-notes")
    assert not err and seam.asked[-1][2]["filters"]["field"] == "status"


def test_a_record_named_by_an_empty_id_is_refused_before_any_vendor_is_asked():
    for name in ("memory_get", "memory_forget"):
        seam = Reading()
        text, err = call(seam, name, memory="m-notes", record="")
        assert err and "id" in text and not seam.asked, name
