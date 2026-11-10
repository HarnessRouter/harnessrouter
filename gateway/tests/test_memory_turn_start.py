"""A turn's start with per-person memory: what it waits on, and what it keeps of it.

Measured on the test instance (r3, 11-09): time to first token went from 2.05 s without memory to 6.97 s with it.
The memory work ran one step after another after the workspace was restored: the recall at the turn's start, each
memory's record count (twice), the recall's neighbours, each memory's standing records. Here the engine answers
every one of those after D seconds, and the restore takes its own time: the turn reaches its runner after the longer
of the restore and the memory work, never their sum, and the memory work is one engine round, never one per step."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_fixture  # noqa: E402
import memory_plane  # noqa: E402
import memory_tools  # noqa: E402

ORG = "turnstartorg"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
D = 0.5          # what the engine takes to answer anything: a search, a count, a memory's standing records


class Slow(memory_fixture.FixtureProvider):
    id = "slowfixture"
    asked: list = []

    async def count(self, mid):
        self.asked.append("count")
        await asyncio.sleep(D)
        return await super().count(mid)

    async def prime(self, mid, budget):
        self.asked.append("prime")
        await asyncio.sleep(D)
        return await super().prime(mid, budget)

    async def recall(self, mid, req):
        self.asked.append("recall")
        await asyncio.sleep(D)
        return await super().recall(mid, req)


@pytest.fixture(scope="module")
def client():
    memory_plane.PROVIDERS["slowfixture"] = Slow()
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture(scope="module")
def agent(client):
    mid = client.post("/v1/memories", headers=ADA, json={"provider": "slowfixture", "name": "Front desk"}).json()["id"]
    assert client.post(f"/v1/memories/{mid}/records", headers=ADA, json={"type": "fact", "content": "Breakfast is served until ten."}).status_code == 200
    r = client.post("/v1/harnesses", headers=ADA, json={"name": "Concierge", "base": "claude-code", "memory": {"id": mid},
                                                        "system_prompt": "Help each guest."})
    assert r.status_code == 200, r.text
    hid = r.json()["id"]
    asyncio.run(gw._vg_upsert("Harness", hid, {"memory_scope": "per_user"}))      # each guest's memory apart
    return hid, mid


def _turn(monkeypatch, hid: str, hydrate_s: float, user: str = "dana@guests.example"):
    """_resp_execute up to its runner, with the real memory work against the slow engine and a restore of
    `hydrate_s`. Returns (seconds until the runner was asked to start, what it was given, the turn's record, its
    translator, its session)."""
    sid = "hsess" + uuid.uuid4().hex
    asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    hv = asyncio.run(gw._harness_vertex(hid))
    started: dict = {}

    async def nothing(*a, **kw):
        return None

    async def sandbox(path, sid, method="POST", body=None, **kw):
        if path == "/turn":
            started.setdefault("at", time.monotonic())
            started.setdefault("body", body)
            return {"turn_id": "t1", "status": "running"}
        if path.startswith("/turn/"):
            return {"done": True, "status": "done", "n_total": 1, "events": [{"type": "result", "subtype": "success", "result": "Done."}]}
        return {}

    async def hydrate(sid, rec):
        await asyncio.sleep(hydrate_s)

    async def connection(org, name):
        return ({"provider": "anthropic", "base_url": "https://proxy.example/v1"}, "tenant-1")

    async def plugins(*a, **kw):
        return ([], [], [], [], [])

    async def env(*a, **kw):
        return ({}, [])

    async def no(*a, **kw):
        return False

    async def empty(*a, **kw):
        return []

    async def yes(*a, **kw):
        return True
    for name, fn in (("_sandbox_json", sandbox), ("_hydrate", hydrate), ("_harness_plugins", plugins), ("_harness_env", env),
                     ("_image_auth", nothing), ("_get_connection", connection),
                     ("_auth_from_conn", lambda *a, **kw: {"token": "t", "base_url": "https://proxy.example/v1"}),
                     ("_turn_cancelled", no), ("_collect_produced", empty), ("_blob_put", nothing), ("_checkpoint", nothing),
                     ("_trace_finalize", nothing), ("_browser_close", nothing), ("_recover_trace_cursor", nothing),
                     ("_trace_flush", yes), ("_memories_observe", nothing), ("_memories_note_kept", nothing),
                     ("_write_running_card", nothing)):
        monkeypatch.setattr(gw, name, fn)
    monkeypatch.setattr(gw, "RESP_POLL_S", 0)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)
    tr = gw._RespTranslator("resp_" + uuid.uuid4().hex[:16], "m", None, True, time.time())

    async def go():
        t0 = time.monotonic()
        status, _, rec = await gw._resp_execute(
            tr, org=ORG, member="me@local", sid=sid, backend="claude", chain=["anthropic"], prompt="hi", files_in=[], resume=None,
            harness_id=hid, hv=hv, emit=lambda ev: asyncio.sleep(0), user_text="When is breakfast served?",
            task_person={"user": user})
        assert status == "completed", rec.get("tried")
        return started["at"] - t0, rec
    took, rec = asyncio.run(go())
    return took, started["body"]["agent_doc"], rec, tr, sid


@pytest.mark.parametrize("hydrate_s", [0.1, 0.9])
def test_a_turns_start_waits_on_the_longer_of_its_restore_and_its_memory_never_their_sum(client, agent, monkeypatch, hydrate_s):
    hid, _ = agent
    _turn(monkeypatch, hid, 0.0)                    # the guest's own memory is made on their first task
    Slow.asked.clear()
    took, doc, rec, _, _ = _turn(monkeypatch, hid, hydrate_s)
    # what it knows was recalled for it and placed in its instructions: the memory work was waited for
    assert "Breakfast is served until ten." in doc and rec["memories"]["recalled_at_start"] == 1
    longest = max(hydrate_s, D)
    assert took < hydrate_s + D, f"{took:.2f} s: the sum of the restore and one engine round"
    assert longest <= took < longest + 0.3, (took, longest)
    # the guest's memory and the agent's are searched at once, and each memory's standing records asked beside the
    # search: one engine round in all, beside the restore. Nothing asks a count (only memory_list shows one).
    assert "count" not in Slow.asked and Slow.asked.count("recall") == 2 and Slow.asked.count("prime") == 2


def test_how_many_findings_were_recalled_at_the_start_is_kept_on_the_turn(client, agent, monkeypatch):
    hid, _ = agent
    _, _, rec, tr, sid = _turn(monkeypatch, hid, 0.0, user="eli@guests.example")
    monkeypatch.undo()                              # the turn's record is written by the real store from here
    n = rec["memories"]["recalled_at_start"]
    assert n == 1
    assert tr._response_obj("completed")["metadata"]["memory"] == {"recalled_at_start": n}
    asyncio.run(gw._resp_put(tr.resp_id, {"id": tr.resp_id, "status": "completed", "output": [], "_input": [{"content": "hi"}]},
                             ORG, sid, None, "completed", time.time(), True))
    turn = asyncio.run(gw._session_turns_data(sid))["turns"][0]
    assert turn["memory"] == {"recalled_at_start": n}
    # and it stays when the turn's note is written after it (what the finished task kept)
    asyncio.run(gw._memories_note(ORG, sid, tr.resp_id, [{"id": "hrec_k", "memory_id": "hmem_x"}], []))
    turn = asyncio.run(gw._session_turns_data(sid))["turns"][0]
    assert turn["memory"] == {"remembered": 1, "records": [{"id": "hrec_k", "memory_id": "hmem_x"}], "pending": False,
                              "recalled_at_start": n}


def test_a_tool_list_asks_the_engine_nothing_and_memory_list_still_counts(client, agent):
    hid, mid = agent
    sid = "hsess" + uuid.uuid4().hex
    asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    tok = gw._mint_hosted_cred(hid, sid, gw._hosted_secret_key(hid, "mcp.memories"))

    def rpc(method, params=None):
        r = client.post("/v1/mcp/memories", headers={"authorization": f"Bearer {tok}"},
                        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        assert r.status_code == 200, r.text
        return r.json()["result"]
    Slow.asked.clear()
    assert "memory_recall" in [t["name"] for t in rpc("tools/list")["tools"]]
    assert Slow.asked == [], "a CLI lists the tools before its first model call"
    listed = rpc("tools/call", {"name": "memory_list", "arguments": {}})
    assert not listed["isError"] and '"count": 1' in listed["content"][0]["text"] and Slow.asked == ["count"]


def test_what_a_seam_is_asked_twice_at_once_is_asked_of_the_engine_once(client, agent):
    hid, mid = agent
    hv = asyncio.run(gw._harness_vertex(hid))

    async def go():
        seam = await gw._memories_seam(hid, ORG, hv, counts=True)
        Slow.asked.clear()
        a, b = await asyncio.gather(seam.entries(), seam.entries())
        p, q = await asyncio.gather(seam.prime(mid, 100), seam.prime(mid, 100))
        return a, b, p, q
    a, b, p, q = asyncio.run(go())
    assert a == b and p == q and Slow.asked == ["count", "prime"]
    assert memory_tools.prime_share([{}] * 2) == memory_tools.PRIME_BUDGET // 2
