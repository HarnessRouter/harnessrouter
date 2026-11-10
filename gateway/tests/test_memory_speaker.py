"""Who is speaking, as a memory names them (Richard 2026-11-10): by the name they sign in with, never "user". The
graph drew a node called "user" for whoever spoke, and the name they gave ("I'm Caroline") became a second node."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_graphiti  # noqa: E402
import memory_plane as mp  # noqa: E402

KEY = {"org": "o", "member": "svc@example.com", "via": "api_key"}
CONSOLE = {"org": "o", "member": "ada@example.com"}


def body(user=None, meta_user=None):
    return SimpleNamespace(user=user, metadata=({"user": meta_user} if meta_user is not None else {}))


def test_the_speaker_is_the_person_the_task_is_for_then_whoever_the_request_names_then_the_console_person():
    assert gw._task_speaker({"user": "u-17"}, body("other"), KEY) == "u-17"
    assert gw._task_speaker({}, body("u-18"), KEY) == "u-18"
    assert gw._task_speaker({}, body(None, "u-19"), KEY) == "u-19"
    assert gw._task_speaker({}, body(), CONSOLE) == "ada@example.com"
    # a key's own call names nobody: the memory says "you", never the key's own identity
    assert gw._task_speaker({}, body(), KEY) == ""
    assert gw._task_speaker({}, body(), {**CONSOLE, "calibration": {"inner": "h"}}) == ""


class _Answer:
    status_code = 200

    def json(self):
        return {"episode": {"uuid": "e1", "name": "episode-1", "content": "", "created_at": "2026-11-10T00:00:00Z"},
                "nodes": [], "edges": []}


def test_graphiti_is_told_each_line_under_the_speakers_name():
    sent = []
    g = memory_graphiti.Graphiti("http://graphiti.test", "k", "o")

    async def no_extraction(mid):
        return {}

    async def call(method, path, body=None, **kw):
        sent.append(body)
        return _Answer()
    g._extraction, g._call = no_extraction, call
    asyncio.run(g.observe("hmem_x", [{"content": [
        {"type": "text", "role": "user", "name": "Caroline", "text": "I went to a support group yesterday."},
        {"type": "text", "role": "assistant", "text": "That sounds like a good step."}]}], {"kind": "member", "id": "h"}))
    assert sent[0]["content"] == "Caroline: I went to a support group yesterday.\nassistant: That sounds like a good step."
    assert "user:" not in sent[0]["content"]


def test_a_speakers_name_is_cleaned_like_their_words():
    parts = mp._clean_parts([{"type": "text", "role": "user", "name": "sk-ant-api03-" + "A" * 40, "text": "hi"}])
    assert "A" * 40 not in parts[0]["name"]
