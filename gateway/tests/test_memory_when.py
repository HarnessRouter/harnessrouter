"""When a remembered thing happened, said by the agent, reaches the record and the vendor's own sense of time.

Found running LoCoMo through agent chats (2026-11-06): the agents wrote "On 7 May 2023 Caroline went to a support
group" in words, but no record carried a time, because memory_remember had nowhere to say it. Hindsight dated what
it derived by when it was written (November 2026), and Graphiti's facts from an observed episode were valid from the
moment of the call, whatever the episode said its time was."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_graphiti  # noqa: E402
import memory_hindsight  # noqa: E402
import memory_plane as mp  # noqa: E402
import memory_tools as mt  # noqa: E402
from test_memory_tools_seam import Fake  # noqa: E402

run = asyncio.run
WRITER = {"kind": "member", "id": "ada@example.com"}


@pytest.mark.parametrize("said,kept", [
    ("2023-05-07", "2023-05-07T00:00:00Z"),
    ("2023-05", "2023-05-01T00:00:00Z"),
    ("2023-05-07T14:00:00Z", "2023-05-07T14:00:00Z"),
    ("2023-05-07T14:00:00+02:00", "2023-05-07T12:00:00Z"),
    ("2023-05-07 14:30", "2023-05-07T14:30:00Z"),
])
def test_a_date_or_a_date_and_time_is_kept_as_utc(said, kept):
    assert mt._when_of({"when": said}) == {"valid_from": kept}


@pytest.mark.parametrize("said", ["yesterday", "May 7", "2023-13-07", "2023-02-30"])
def test_what_is_not_a_date_is_refused_in_words(said):
    out = mt._when_of({"when": said})
    assert isinstance(out, str) and "2023-05-07" in out


def test_remember_carries_when_and_until_to_the_record():
    seam = Fake()
    text, err = run(mt.call(seam, "memory_remember", {"title": "Caroline went to a support group", "when": "2023-05-07", "until": "2023-05-08"}))
    assert not err, text
    _, mid, record = seam.asked[-1]
    assert record["time"] == {"valid_from": "2023-05-07T00:00:00Z", "valid_to": "2023-05-08T00:00:00Z"}


def test_remember_without_when_is_as_before():
    seam = Fake()
    text, err = run(mt.call(seam, "memory_remember", {"title": "Melanie paints"}))
    assert not err and "time" not in seam.asked[-1][2]


def test_a_when_that_is_not_a_date_writes_nothing():
    seam = Fake()
    text, err = run(mt.call(seam, "memory_remember", {"title": "x", "when": "last week"}))
    assert err and not seam.asked


def test_both_writing_tools_offer_when():
    by = {t["name"]: t for t in mt._TOOLS}
    for name in ("memory_remember", "memory_revise"):
        props = by[name]["inputSchema"]["properties"]
        assert "when" in props and "until" in props, name


class Wire:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, req):
        body = json.loads(req.content) if req.content else None
        self.calls.append({"path": req.url.path, "body": body})
        return httpx.Response(200, json=self.answer(req.url.path, body))


@pytest.fixture
def wired(monkeypatch):
    def use(module, answer):
        w = Wire(answer)
        monkeypatch.setattr(module, "transport", httpx.MockTransport(w))
        return w
    return use


def test_hindsight_dates_a_remembered_record_by_when_it_happened(wired):
    w = wired(memory_hindsight, lambda p, b: {})
    run(memory_hindsight.Hindsight("http://vendor.test").remember(
        "m", {"type": "fact", "content": [{"type": "text", "text": "Caroline went to a support group."}],
              "time": {"valid_from": "2023-05-07T00:00:00Z"}}, WRITER))
    item = [c for c in w.calls if c["path"].endswith("/memories")][-1]["body"]["items"][0]
    assert item["timestamp"] == "2023-05-07T00:00:00Z"


def test_hindsight_without_a_time_sends_none(wired):
    w = wired(memory_hindsight, lambda p, b: {})
    run(memory_hindsight.Hindsight("http://vendor.test").remember("m", {"type": "fact", "content": [{"type": "text", "text": "x"}]}, WRITER))
    item = [c for c in w.calls if c["path"].endswith("/memories")][-1]["body"]["items"][0]
    assert "timestamp" not in item


def test_hindsight_dates_an_observed_episode_by_its_own_time(wired):
    w = wired(memory_hindsight, lambda p, b: {"operation_ids": ["op1"]})
    run(memory_hindsight.Hindsight("http://vendor.test").observe(
        "m", [{"content": [{"type": "text", "role": "user", "text": "hello"}], "time": {"valid_from": "2023-05-08T13:56:00Z"}}], WRITER))
    item = [c for c in w.calls if c["path"].endswith("/memories")][-1]["body"]["items"][0]
    assert item["timestamp"] == "2023-05-08T13:56:00Z"


def test_graphiti_takes_an_episodes_time_as_its_reference_time(wired, monkeypatch):
    w = wired(memory_graphiti, lambda p, b: {"episode": {"uuid": "ep1", "name": "x", "content": "..."}, "nodes": [], "edges": []} if p == "/episodes" else {})

    async def load(org, mid):
        return {}
    monkeypatch.setattr(mp, "_load", load)
    g = memory_graphiti.Graphiti("http://vendor.test", "", "org")
    run(g.observe("m", [{"content": [{"type": "text", "role": "user", "text": "hello"}], "time": {"valid_from": "2023-05-08T13:56:00Z"}}], WRITER))
    run(g.observe("m", [{"content": [{"type": "text", "role": "user", "text": "hello"}]}], WRITER))
    sent = [c["body"] for c in w.calls if c["path"] == "/episodes"]
    assert sent[0]["reference_time"] == "2023-05-08T13:56:00Z"
    assert "reference_time" not in sent[1], "no time said: the vendor's own now"
