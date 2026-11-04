"""The entry that gives an agent its memories is the server's. A client doesn't see it, can't remove it, can't
repoint it, can't name it by hand and can't copy it onto another agent, and the turn keeps working through all of it."""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_fixture  # noqa: E402
import memory_plane  # noqa: E402

ORG = "memreserved"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
ENTRY = "mcp.memories"
HOSTED = "https://gateway.example/v1/mcp/memories"


@pytest.fixture(scope="module")
def client():
    memory_plane.PROVIDERS["fixture"] = memory_fixture.FixtureProvider()
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture(scope="module")
def mid(client):
    return client.post("/v1/memories", headers=ADA, json={"provider": "fixture", "name": "Kept"}).json()["id"]


def stored(hid):
    return gw._mcp_list(asyncio.run(gw._vertex_get(hid)))


def theirs(hid):
    return next((s for s in stored(hid) if s.get("id") == ENTRY), None)


def harness(client, **b):
    r = client.post("/v1/harnesses", headers=ADA, json={"name": "Helper", "base": "claude-code", **b})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def holding(client, mid, **b):
    hid = harness(client, **b)
    r = client.post(f"/v1/memories/{mid}/grants", headers=ADA, json={"principal": f"member:{hid}", "privileges": ["read"]})
    assert r.status_code == 200, r.text
    assert theirs(hid), "a grant gives the agent its entry"
    return hid


def tools(client, hid, key=None):
    sid = "sess_" + os.urandom(6).hex()
    asyncio.run(gw._vg_upsert("HarnessSession", sid, {"tenant": ORG, "status": "idle", "turn_status": "idle", "harness_id": hid}))
    tok = gw._mint_hosted_cred(hid, sid, key or gw._hosted_secret_key(hid, ENTRY))
    r = client.post("/v1/mcp/memories", headers={"authorization": f"Bearer {tok}"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert r.status_code == 200, r.text
    return [t["name"] for t in r.json()["result"]["tools"]]


def put(client, hid, servers, public=True):
    path = f"/v1/harnesses/{hid}" if public else f"/v1/orgs/{ORG}/harnesses/{hid}"
    return client.put(path, headers=ADA, json={"name": "Helper", "base": "claude-code", "mcp_servers": servers})


def test_no_reader_is_shown_it_and_its_address_doesnt_leave(client, mid):
    hid = holding(client, mid)
    one = client.get(f"/v1/harnesses/{hid}", headers=ADA).json()
    assert one["mcpServers"] == []
    every = client.get("/v1/harnesses", headers=ADA).json()
    row = next(h for h in (every.get("data") or every.get("harnesses")) if h["id"] == hid)
    assert row["mcpServers"] == []
    assert "/v1/mcp/memories" not in json.dumps(one)


@pytest.mark.parametrize("public", [True, False])
def test_a_save_without_it_keeps_it_and_the_agent_keeps_its_tools(client, mid, public):
    hid = holding(client, mid)
    before = theirs(hid)
    assert tools(client, hid)
    r = put(client, hid, [], public)
    assert r.status_code == 200, r.text
    assert theirs(hid) == before
    assert tools(client, hid), "the record behind it wasn't scrubbed"


@pytest.mark.parametrize("public", [True, False])
def test_a_save_can_t_repoint_it_or_change_its_auth(client, mid, public):
    hid = holding(client, mid)
    before = theirs(hid)
    r = put(client, hid, [{"id": ENTRY, "name": "memories", "url": "https://elsewhere.example/mcp", "auth": "a-token-of-mine", "enabled": False}], public)
    assert r.status_code == 200, r.text
    assert theirs(hid) == before
    assert [s for s in stored(hid) if "elsewhere" in str(s.get("url"))] == []


def test_another_id_pointing_at_the_endpoint_isn_t_kept(client, mid):
    hid = holding(client, mid)
    before = stored(hid)
    r = put(client, hid, [{"id": "mine", "name": "mine", "url": HOSTED, "auth": before[0]["auth"]}])
    assert r.status_code == 200, r.text
    assert stored(hid) == before


def test_it_can_t_be_created_by_hand(client):
    hid = harness(client, mcp_servers=[{"id": ENTRY, "name": "memories", "url": HOSTED, "auth": "vault:harness-hosted-someone-mcp-memories"}])
    assert stored(hid) == []
    r = put(client, hid, [{"id": ENTRY, "name": "memories", "url": HOSTED, "auth": "vault:harness-hosted-someone-mcp-memories"}])
    assert r.status_code == 200, r.text
    assert stored(hid) == []


def test_ordinary_servers_are_saved_around_it(client, mid):
    hid = holding(client, mid)
    r = put(client, hid, [{"id": "docs", "name": "docs", "url": "https://docs.example/mcp"}])
    assert r.status_code == 200, r.text
    assert [s.get("id") for s in r.json()["mcpServers"]] == ["docs"]
    assert {s.get("id") for s in stored(hid)} == {"docs", ENTRY}
    r = put(client, hid, [])
    assert {s.get("id") for s in stored(hid)} == {ENTRY}


def test_a_copy_by_read_and_write_doesn_t_carry_it(client, mid):
    first = holding(client, mid)
    read = client.get(f"/v1/harnesses/{first}", headers=ADA).json()
    copy = harness(client, mcp_servers=read["mcpServers"])
    assert stored(copy) == []


def test_an_entry_copied_before_this_can_t_take_the_first_agent_s_memories(client, mid):
    first = holding(client, mid)
    copy = harness(client)
    # how a copy looked when a client could read the entry and write it to another harness
    asyncio.run(gw._mcp_write(copy, [theirs(first)]))
    r = client.post(f"/v1/memories/{mid}/grants", headers=ADA, json={"principal": f"member:{copy}", "privileges": ["read"]})
    assert r.status_code == 200, r.text
    assert tools(client, first), "the first agent still reaches its memories"
    assert gw._vault_key(theirs(copy)["auth"]) == gw._hosted_secret_key(copy, ENTRY)
    assert tools(client, copy), "and the copy reaches its own"


def test_a_server_of_yours_can_t_take_its_name(client, mid):
    hid = holding(client, mid)
    r = put(client, hid, [{"id": "mine", "name": "memories", "url": "https://mine.example/mcp"}])
    assert r.status_code == 400
    assert "memories" in r.json()["error"]["message"] and "another name" in r.json()["error"]["message"]
    assert {s.get("id") for s in stored(hid)} == {ENTRY}


def test_a_server_already_called_memories_keeps_its_name_and_both_reach_the_agent(client, mid):
    hid = harness(client, mcp_servers=[{"id": "mine", "name": "memories", "url": "https://mine.example/mcp"}])
    r = client.post(f"/v1/memories/{mid}/grants", headers=ADA, json={"principal": f"member:{hid}", "privileges": ["read"]})
    assert r.status_code == 200, r.text
    names = [gw._mcp_name(str(s.get("name"))) for s in stored(hid)]
    assert len(names) == len(set(names)) == 2, names
    assert next(s for s in stored(hid) if s["id"] == "mine")["name"] == "memories"
    r = put(client, hid, [{"id": "mine", "name": "memories", "url": "https://mine.example/mcp"}])
    assert r.status_code == 200, r.text


def test_one_left_switched_off_or_pointed_away_is_put_right_when_it_s_next_given(client, mid):
    hid = holding(client, mid)
    want = theirs(hid)
    asyncio.run(gw._mcp_write(hid, [{**want, "url": "https://elsewhere.example/mcp", "enabled": False, "auth": "x"}]))
    r = client.put(f"/v1/harnesses/{hid}/memories", headers=ADA, json={"observe": False})
    assert r.status_code == 200, r.text
    assert theirs(hid) == want
    assert tools(client, hid)


def test_deleting_the_agent_still_removes_the_record_behind_it(client, mid):
    hid = holding(client, mid)
    key = gw._hosted_secret_key(hid, ENTRY)
    assert asyncio.run(gw._hosted_record(ORG, key))
    assert client.delete(f"/v1/harnesses/{hid}", headers=ADA).status_code == 200
    assert not asyncio.run(gw._hosted_record(ORG, key))


def test_the_turn_still_gets_it_after_a_save_that_didn_t_name_it(client, mid):
    hid = holding(client, mid)
    put(client, hid, [{"id": "docs", "name": "docs", "url": "https://docs.example/mcp"}])
    servers = asyncio.run(gw._harness_plugins(hid, ORG, {}, hv=asyncio.run(gw._vertex_get(hid)), sid="sess_x"))[0]
    urls = [s["url"] for s in servers]
    assert HOSTED in urls
    assert any(s.get("auth") for s in servers if s["url"] == HOSTED), "a minted credential, never the stored reference"
    assert not any(str(s.get("auth")).startswith("vault:") for s in servers)
