"""A list cursor is checked before a memory provider is called."""
from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graphiti  # noqa: E402
import memory_hindsight  # noqa: E402
import memory_mem0  # noqa: E402
import memory_plane as mp  # noqa: E402
import memory_reme  # noqa: E402

run = asyncio.run


@pytest.mark.parametrize(("make", "calls"), [
    (lambda: memory_hindsight.Hindsight("http://vendor.test"), ("_call",)),
    (lambda: memory_reme.ReMe("http://vendor.test"), ("_rows",)),
    (lambda: memory_graphiti.Graphiti("http://vendor.test"), ("_everything",)),
    (lambda: memory_mem0.Mem0("key"), ("_call",)),
    (lambda: memory_mem0.Mem0Server("key", "http://vendor.test"), ("_entities", "_all")),
], ids=("hindsight", "reme", "graphiti", "mem0-cloud", "mem0-server"))
def test_a_bad_cursor_reaches_no_provider_call(monkeypatch, make, calls):
    provider = make()

    async def called(*args, **kwargs):
        pytest.fail("the provider was called")

    for name in calls:
        monkeypatch.setattr(provider, name, called)
    with pytest.raises(mp.MemoryError) as error:
        run(provider.list("memory", {"cursor": "abc"}))
    assert error.value.status == 422 and error.value.code == "memory_invalid" and error.value.param == "cursor"


@pytest.mark.parametrize("cursor", ("1_0", "١", "-0", "9" * 5000, "99999999999", "2147483648"))
def test_other_invalid_cursors_are_refused(cursor):
    with pytest.raises(mp.MemoryError) as error:
        mp.cursor_at({"cursor": cursor})
    assert error.value.status == 422 and error.value.param == "cursor"


def test_empty_and_decimal_cursors_keep_their_values():
    assert mp.cursor_at({}) == 0
    assert mp.cursor_at({"cursor": ""}, 1) == 1
    assert mp.cursor_at({"cursor": "0"}) == 0
    assert mp.cursor_at({"cursor": "12"}) == 12
    assert mp.cursor_at({"cursor": "2147483647"}) == 2147483647


def test_mem0_cloud_pages_start_at_one(monkeypatch):
    provider = memory_mem0.Mem0("key")

    async def called(*args, **kwargs):
        pytest.fail("the provider was called")

    monkeypatch.setattr(provider, "_call", called)
    with pytest.raises(mp.MemoryError) as error:
        run(provider.list("memory", {"cursor": "0"}))
    assert error.value.status == 422 and error.value.param == "cursor"

    pages = []

    async def answer(method, path, *, body=None, params=None, ok=(200,)):
        pages.append(params["page"])
        return httpx.Response(200, json={"results": []})

    monkeypatch.setattr(provider, "_call", answer)
    assert run(provider.list("memory", {"cursor": "1"})) == {"records": [], "next": None}
    assert pages == [1]
