"""A memory belongs to the workspace it was made in and is reached only from there (Richard, 2026-11-10): listed, read,
written and shared only by someone acting in that workspace, and used only by that workspace's agents. Before, the
person who made a memory saw it in every workspace's list, and an agent in one workspace could be given another's.
Driven through the public routes with the fixture provider behind them."""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_fixture  # noqa: E402
import memory_local  # noqa: E402
import memory_plane as mp  # noqa: E402
from memory_tools import Refused  # noqa: E402

ORG = "wsmemorg"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
run = asyncio.run


def at(ws: str) -> dict:
    return {**ADA, "x-harness-workspace": ws}


RES, OPS = at("research"), at("ops")


@pytest.fixture(scope="module")
def client():
    mp.PROVIDERS.setdefault("fixture", memory_fixture.FixtureProvider())
    with TestClient(gw.app) as c:
        yield c


def _mem(client, headers, name) -> str:
    r = client.post("/v1/memories", headers=headers, json={"provider": "fixture", "name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _agent(client, headers, name) -> str:
    r = client.post("/v1/harnesses", headers=headers, json={"name": name, "base": "claude-code", "memory": "none"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _names(client, headers) -> set[str]:
    r = client.get("/v1/memories", headers=headers, params={"counts": "false"})
    assert r.status_code == 200, r.text
    return {m["name"] for m in r.json()["data"]}


def _code(r) -> str:
    return r.json()["error"]["code"]


@pytest.fixture(scope="module")
def world(client):
    w = {"lab": _mem(client, RES, "Lab notes"), "runbook": _mem(client, OPS, "Runbook"),
         "a_res": _agent(client, RES, "Researcher"), "a_ops": _agent(client, OPS, "On call")}
    assert client.post(f"/v1/memories/{w['lab']}/grants", headers=RES,
                       json={"principal": f"member:{w['a_res']}", "privileges": ["read", "write"]}).status_code == 200
    return w


def test_a_memory_is_listed_only_in_its_own_workspace(client, world):
    assert "Lab notes" in _names(client, RES) and "Runbook" not in _names(client, RES)
    assert "Runbook" in _names(client, OPS) and "Lab notes" not in _names(client, OPS)
    # the person who made both sees neither from a third workspace, nor from the default one
    assert not {"Lab notes", "Runbook"} & (_names(client, at("design")) | _names(client, ADA))


def test_another_workspace_reaches_none_of_it_by_id(client, world):
    mid = world["lab"]
    for method, path, body in (("get", f"/v1/memories/{mid}", None), ("put", f"/v1/memories/{mid}", {"name": "Renamed"}),
                               ("get", f"/v1/memories/{mid}/records", None), ("get", f"/v1/memories/{mid}/grants", None),
                               ("post", f"/v1/memories/{mid}/records", {"type": "note", "content": "from ops"}),
                               ("post", f"/v1/memories/{mid}/recall", {"query": "notes"}),
                               ("post", f"/v1/memories/{mid}/grants", {"principal": "member:cy@example.com", "privileges": ["read"]}),
                               ("delete", f"/v1/memories/{mid}", None)):
        r = getattr(client, method)(path, headers=OPS, **({"json": body} if body is not None else {}))
        assert r.status_code == 404 and _code(r) == "memory_not_found", (method, path, r.text)
    # a memory below it can't be made from there either
    r = client.post("/v1/memories", headers=OPS, json={"provider": "fixture", "name": "Under it", "parent_id": mid})
    assert r.status_code == 404
    # and from its own workspace it is all still there
    got = client.get(f"/v1/memories/{mid}", headers=RES)
    assert got.status_code == 200 and got.json()["name"] == "Lab notes"


def test_an_agent_is_given_only_its_own_workspace_s_memories(client, world):
    r = client.post(f"/v1/memories/{world['lab']}/grants", headers=RES,
                    json={"principal": f"member:{world['a_ops']}", "privileges": ["read"]})
    assert r.status_code == 422 and _code(r) == "memory_other_workspace"
    assert "another workspace" in r.json()["error"]["message"]
    r = client.post(f"/v1/memories/{world['lab']}/grants", headers=RES, json={"principal": "group:ops", "privileges": ["read"]})
    assert r.status_code == 422 and _code(r) == "memory_other_workspace"
    mine = client.get(f"/v1/harnesses/{world['a_res']}/memories", headers=RES).json()["data"]
    assert [m["id"] for m in mine] == [world["lab"]]
    assert client.get(f"/v1/harnesses/{world['a_res']}", headers=RES).json()["memories"] == {"count": 1}


def test_a_grant_from_before_the_rule_gives_another_workspace_s_agent_nothing(client, world):
    # a grant written before memories kept to their workspace: it stays stored and gives nothing
    run(mp._put_grant(ORG, world["lab"], f"member:{world['a_ops']}", ["read", "write"], "before"))
    hv = run(gw._harness_vertex(world["a_ops"]))
    assert client.get(f"/v1/harnesses/{world['a_ops']}/memories", headers=OPS).json()["data"] == []
    assert client.get(f"/v1/harnesses/{world['a_ops']}", headers=OPS).json()["memories"] == {"count": 0}
    assert run(gw._harness_memories(world["a_ops"], ORG, hv)) == []
    seam = memory_local.Local(ORG, world["a_ops"], [], workspace=hv.get("workspace"))
    with pytest.raises(Refused):
        run(seam.recall(world["lab"], {"query": "notes"}))
    with pytest.raises(Refused):
        run(seam.remember(world["lab"], {"type": "note", "content": "from the wrong workspace"}))
    # the memory's own list names only its own workspace's agent as using it
    lab = next(m for m in client.get("/v1/memories", headers=RES, params={"counts": "false"}).json()["data"] if m["id"] == world["lab"])
    assert [u["harness_id"] for u in lab["used_by"]] == [world["a_res"]]


def test_an_agent_can_t_be_made_or_moved_onto_another_workspace_s_memory(client, world):
    r = client.post("/v1/harnesses", headers=OPS, json={"name": "Borrower", "base": "claude-code", "memory": {"id": world["lab"]}})
    assert r.status_code == 404 and _code(r) == "memory_not_found"
    r = client.put(f"/v1/harnesses/{world['a_ops']}/memory", headers=OPS, json={"memory": {"id": world["lab"]}})
    assert r.status_code == 404 and _code(r) == "memory_not_found"
    r = client.put(f"/v1/harnesses/{world['a_ops']}/memories", headers=OPS, json={"default_memory_id": world["lab"]})
    assert r.status_code == 404


def test_the_agent_s_own_workspace_decides_whichever_one_is_open(client, world):
    # the On call agent is in ops: opened from research, it is still given ops' memory and never research's
    hid = _agent(client, OPS, "Pager")
    r = client.put(f"/v1/harnesses/{hid}/memory", headers=RES, json={"memory": {"id": world["lab"]}})
    assert r.status_code == 404
    r = client.put(f"/v1/harnesses/{hid}/memory", headers=RES, json={"memory": {"id": world["runbook"]}})
    assert r.status_code == 200, r.text
    assert [m["id"] for m in client.get(f"/v1/harnesses/{hid}/memories", headers=OPS).json()["data"]] == [world["runbook"]]


def test_a_key_held_to_a_workspace_reaches_only_its_memories(client, world):
    r = client.post(f"/v1/orgs/{ORG}/keys", headers=ADA, json={"name": "ops key", "workspace": "ops", "member_id": "svc@example.com"})
    assert r.status_code == 200, r.text
    key = {"authorization": "Bearer " + (r.json().get("key") or r.json().get("token") or r.json()["secret"])}
    for headers in (key, {**key, "x-harness-workspace": "research"}):       # the key's own workspace, whatever it names
        r = client.get(f"/v1/memories/{world['lab']}", headers=headers)
        assert r.status_code == 404 and _code(r) == "memory_not_found"


def test_principals_that_say_no_workspace_or_two_reach_nothing(client, world):
    m = run(mp._load(ORG, world["lab"]))
    ada = "member:ada@example.com"
    assert run(mp.effective(ORG, m, [ada])) == []
    assert run(mp.effective(ORG, m, [ada, mp.acting_in("research"), mp.acting_in("ops")])) == []
    assert run(mp.effective(ORG, m, [ada, mp.acting_in("ops")])) == []
    assert run(mp.effective(ORG, m, [ada, mp.acting_in("research")])) == list(mp.PRIVILEGES)
    # no grant can name where a caller acts: it is not a principal
    r = client.post(f"/v1/memories/{world['lab']}/grants", headers=RES, json={"principal": "in:ops", "privileges": ["read"]})
    assert r.status_code == 422 and _code(r) == "memory_invalid"


def test_a_memory_from_before_workspaces_is_the_default_workspace_s(client):
    old = run(mp.create(ORG, "ada@example.com", "", mp.placed(["member:ada@example.com"], ""), name="From before", provider="fixture"))
    assert old["workspace"] == "" and mp.place_of(old) == mp.place("default") == mp.place(f"{ORG}__hr_default") == "default"
    assert "From before" in _names(client, ADA) and "From before" in _names(client, at("default"))
    assert "From before" not in _names(client, RES)
