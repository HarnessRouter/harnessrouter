"""A key minted for no one owns the memories it creates: it reads, extends and deletes them, and no other caller does
without a grant. Before, such a key's memories were stamped created_by "" and reached by no caller, the key that
made them included (UHP conformance ME-01..13 failed on 0.41.16).

The access model is unchanged around it: a workspace is a boundary, and inside it the creator or a grant reaches a
memory. So a second key in the same workspace, a person, another workspace and another organization all get 404 on
a key's memory; an empty creator matches no one; and a member id under the reserved key: prefix is no one.
Driven through the public routes with the fixture provider behind them, with real minted keys."""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import memory_fixture  # noqa: E402
import memory_plane as mp  # noqa: E402

ORG, OTHER = "keymemorg", "keymemother"
WS = "lab"
ADA = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-member": "ada@example.com"}
run = asyncio.run


def at(ws: str, base: dict = ADA) -> dict:
    return {**base, "x-harness-workspace": ws}


@pytest.fixture(scope="module")
def client():
    mp.PROVIDERS.setdefault("fixture", memory_fixture.FixtureProvider())
    with TestClient(gw.app) as c:
        yield c


def _mint(client, org: str, workspace: str, member_id: str = "") -> tuple[dict, str]:
    body = {"name": f"key {member_id or 'service'}", "workspace": workspace, **({"member_id": member_id} if member_id else {})}
    r = client.post(f"/v1/orgs/{org}/keys", headers={**ADA, "x-harness-org": org}, json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    return {"authorization": "Bearer " + (j.get("key") or j.get("token") or j["secret"])}, str(j["id"])


@pytest.fixture(scope="module")
def keys(client):
    a, a_id = _mint(client, ORG, WS)
    b, _ = _mint(client, ORG, WS)
    ops, _ = _mint(client, ORG, "ops")
    other, _ = _mint(client, OTHER, WS)
    person, _ = _mint(client, ORG, WS, "ada@example.com")
    return {"a": a, "a_id": a_id, "b": b, "ops": ops, "other": other, "person": person}


def _mem(client, headers, name, **extra):
    return client.post("/v1/memories", headers=headers, json={"provider": "fixture", "name": name, **extra})


def _code(r) -> str:
    return (r.json().get("error") or {}).get("code", "")


def test_a_key_minted_for_no_one_reads_extends_and_deletes_its_own_memory(client, keys):
    r = _mem(client, keys["a"], "Key A notes")
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    assert client.get(f"/v1/memories/{mid}", headers=keys["a"]).status_code == 200
    child = client.post("/v1/memories", headers=keys["a"], json={"name": "accounts", "parent_id": mid})
    assert child.status_code == 200, child.text
    roots = client.get("/v1/memories", headers=keys["a"], params={"counts": "false"})
    assert "Key A notes" in {m["name"] for m in roots.json()["data"]}
    below = client.get("/v1/memories", headers=keys["a"], params={"counts": "false", "parent": mid})
    assert {m["name"] for m in below.json()["data"]} == {"accounts"}
    assert client.delete(f"/v1/memories/{mid}", headers=keys["a"]).status_code == 200
    assert client.get(f"/v1/memories/{mid}", headers=keys["a"]).status_code == 404


def test_no_one_else_reaches_a_keys_memory_without_a_grant(client, keys):
    mid = _mem(client, keys["a"], "Key A private").json()["id"]
    others = {"another key in the same workspace": keys["b"], "a person in the same workspace": at(WS),
              "a key held by that person": keys["person"], "another workspace's key": keys["ops"],
              "another organization's key": keys["other"]}
    for who, headers in others.items():
        assert client.get(f"/v1/memories/{mid}", headers=headers).status_code == 404, who
        assert client.post("/v1/memories", headers=headers, json={"name": "x", "parent_id": mid}).status_code == 404, who
        assert client.put(f"/v1/memories/{mid}", headers=headers, json={"name": "taken"}).status_code == 404, who
        assert client.delete(f"/v1/memories/{mid}", headers=headers).status_code == 404, who
        names = {m["name"] for m in client.get("/v1/memories", headers=headers, params={"counts": "false"}).json()["data"]}
        assert "Key A private" not in names, who
    assert client.get(f"/v1/memories/{mid}", headers=keys["a"]).json()["name"] == "Key A private"


def test_a_grant_from_the_key_still_shares_it(client, keys):
    mid = _mem(client, keys["a"], "Key A shared").json()["id"]
    g = client.post(f"/v1/memories/{mid}/grants", headers=keys["a"],
                    json={"principal": "member:ada@example.com", "privileges": ["read"]})
    assert g.status_code == 200, g.text
    assert client.get(f"/v1/memories/{mid}", headers=at(WS)).status_code == 200
    assert client.get(f"/v1/memories/{mid}", headers=keys["b"]).status_code == 404      # the grant named one person


def test_a_person_and_their_key_work_as_before(client, keys):
    mid = _mem(client, at(WS), "Ada's notes").json()["id"]
    assert client.get(f"/v1/memories/{mid}", headers=keys["person"]).status_code == 200
    assert client.post("/v1/memories", headers=keys["person"], json={"name": "sub", "parent_id": mid}).status_code == 200
    assert client.get(f"/v1/memories/{mid}", headers=keys["a"]).status_code == 404
    assert client.get(f"/v1/memories/{mid}", headers=at("ops")).status_code == 404       # the workspace boundary


def test_an_empty_creator_is_no_one():
    m = {"id": "hmem_empty", "org": ORG, "workspace": WS, "created_by": "", "anc": "", "parent_id": ""}
    for principals in ([], ["group:lab"], ["member:"], ["key:"], ["member:ada@example.com"], ["key:abc"]):
        assert run(mp.effective(ORG, m, mp.placed(principals, WS))) == [], principals
    assert mp.creator_principal("") == "" and mp.creator_principal(None) == ""
    assert mp.creator_principal("ada@example.com") == "member:ada@example.com"
    assert mp.creator_principal("key:abc") == "key:abc"


def test_a_member_named_under_the_key_prefix_is_no_one(client, keys):
    mid = _mem(client, keys["a"], "Key A target").json()["id"]
    forged, _ = _mint(client, ORG, WS, "key:" + keys["a_id"])
    assert client.get(f"/v1/memories/{mid}", headers=forged).status_code == 404
    r = _mem(client, forged, "would be key A's")
    assert r.status_code == 403 and _code(r) == "memory_forbidden"
    assert mp.creator_of({"member": "key:" + keys["a_id"], "via": "api_key", "key_id": "zzz"}) == ""


def test_a_caller_that_could_never_reach_a_memory_cannot_make_one(client):
    nobody = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG, "x-harness-workspace": WS}
    r = _mem(client, nobody, "orphan")
    assert r.status_code == 403 and _code(r) == "memory_forbidden"
    assert mp.creator_of({"via": "api_key"}) == "" and mp.creator_of({"via": "internal", "key_id": "k"}) == ""
