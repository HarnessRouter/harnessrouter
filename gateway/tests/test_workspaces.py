"""The server-side workspace registry — the fix for the localStorage split-brain.

The defect: harnesses/tasks/keys were stamped with workspace ids in the store, but the
REGISTRY (id, name, description) lived in each browser's localStorage on self-host, so two
laptops on one instance saw different workspace lists and could not reach each other's
records. These tests pin the contract the console's existing calls expect, plus the two
properties the migration depends on: browser-minted ids are adopted verbatim, and the
server's slug rules match the old localStorage minting exactly.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    store: dict[str, dict] = {}

    async def fake_upsert(label, vid, props, *, raise_on_fail=False):
        store[vid] = {**props}

    async def fake_list(label, org):
        return [v for v in store.values() if v.get("org") == org and label == "Workspace"]

    async def fake_principal(request):
        return {"org": "local", "member": "local@localhost", "workspace": "", "workspace_default": False}

    monkeypatch.setattr(gw, "_vg_upsert", fake_upsert)
    monkeypatch.setattr(gw, "_vg_list_by_org", fake_list)
    monkeypatch.setattr(gw, "_principal", fake_principal)
    return TestClient(gw.app)


def test_list_seeds_default_idempotently(client):
    for _ in range(2):
        r = client.get("/v1/hr/workspaces")
        assert r.status_code == 200
        d = r.json()
        assert d["default_workspace_id"] == "default"
        assert [w["id"] for w in d["workspaces"]].count("default") == 1


def test_create_and_list_across_clients(client):
    r = client.post("/v1/hr/workspaces", json={"name": "Research", "description": "papers"})
    assert r.status_code == 200
    assert r.json() == {"id": "research", "name": "Research", "description": "papers"}
    # "another laptop" is just another GET: the registry is server truth now
    ids = [w["id"] for w in client.get("/v1/hr/workspaces").json()["workspaces"]]
    assert "research" in ids and "default" in ids


def test_slug_rules_match_the_old_localstorage_mint(client):
    assert client.post("/v1/hr/workspaces", json={"name": "My Team!"}).json()["id"] == "my-team"
    assert client.post("/v1/hr/workspaces", json={"name": "My Team?"}).json()["id"] == "my-team-2"


def test_migration_adopts_browser_minted_id_verbatim_and_idempotently(client):
    r1 = client.post("/v1/hr/workspaces", json={"id": "research", "name": "Research"})
    assert r1.json()["id"] == "research"
    # a second tab racing the migration lands on the SAME workspace, not a duplicate
    r2 = client.post("/v1/hr/workspaces", json={"id": "research", "name": "Research"})
    assert r2.json()["id"] == "research"
    ids = [w["id"] for w in client.get("/v1/hr/workspaces").json()["workspaces"]]
    assert ids.count("research") == 1


def test_rename_persists(client):
    client.post("/v1/hr/workspaces", json={"name": "Ops"})
    r = client.patch("/v1/hr/workspaces/ops", json={"name": "Operations"})
    assert r.status_code == 200 and r.json()["name"] == "Operations"
    names = {w["id"]: w["name"] for w in client.get("/v1/hr/workspaces").json()["workspaces"]}
    assert names["ops"] == "Operations"


def test_unknown_workspace_404s(client):
    assert client.patch("/v1/hr/workspaces/nope", json={"name": "x"}).status_code == 404
