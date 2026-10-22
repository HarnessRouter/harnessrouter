"""A workspace list the store could not read is never taken for an organization with none.

`_workspace_rows` read through the forgiving `find`, which answers a failed read with the same `[]` as
an organization that holds no workspace. Each of its three callers acts on that answer:
  the list backfills the default when it is missing, with an upsert, so a renamed default went back to
  "Default Workspace" and every other workspace vanished from the answer;
  create picks a free id against the ids it read, so "Research" took `research` again and wrote over it;
  rename looked the workspace up, and answered 404 for one that is there.
The read is strict now (#562's `_vg_list_by_org_strict`): a failure is a 503, nothing is written, and an
organization that really has no workspace still gets its default.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402

ORG = "local"


@pytest.fixture()
def world(monkeypatch):
    store: dict[str, dict] = {}
    broken = {"on": False}

    async def fake_upsert(label, vid, props, *, raise_on_fail=False):
        store[vid] = {**props}

    async def plain_list(label, org):
        # the forgiving read: a failure is the same [] as nothing there
        if broken["on"]:
            return []
        return [v for v in store.values() if v.get("org") == org and label == "Workspace"]

    async def strict_find(label, eq=None, neq=None):
        if broken["on"]:
            raise RuntimeError("store unreachable")
        return [v for v in store.values() if v.get("org") == (eq or {}).get("org") and label == "Workspace"]

    async def fake_principal(request):
        return {"org": ORG, "member": "local@localhost", "workspace": "", "workspace_default": False}

    monkeypatch.setattr(gw, "_vg_upsert", fake_upsert)
    monkeypatch.setattr(gw, "_vg_list_by_org", plain_list)
    monkeypatch.setattr(gw.BACKING.graph, "find_strict", strict_find)
    monkeypatch.setattr(gw, "_principal", fake_principal)
    return TestClient(gw.app), store, broken


def _renamed_default_and_research(api):
    assert api.get("/v1/hr/workspaces").status_code == 200
    assert api.patch("/v1/hr/workspaces/default", json={"name": "Acme HQ"}).status_code == 200
    assert api.post("/v1/hr/workspaces", json={"name": "Research", "description": "papers"}).status_code == 200


def test_a_list_that_could_not_be_read_is_said_and_writes_nothing(world):
    api, store, broken = world
    _renamed_default_and_research(api)
    kept = {k: dict(v) for k, v in store.items()}
    broken["on"] = True
    r = api.get("/v1/hr/workspaces")
    assert r.status_code == 503, r.text
    assert r.json()["error"]["message"] == "Your workspaces could not be read just now. Try again in a moment."
    assert store == kept, "the default was written back over the renamed one"
    broken["on"] = False
    names = {w["id"]: w["name"] for w in api.get("/v1/hr/workspaces").json()["workspaces"]}
    assert names == {"default": "Acme HQ", "research": "Research"}


def test_create_over_a_list_that_could_not_be_read_takes_no_ones_id(world):
    api, store, broken = world
    _renamed_default_and_research(api)
    kept = {k: dict(v) for k, v in store.items()}
    broken["on"] = True
    assert api.post("/v1/hr/workspaces", json={"name": "Research", "description": "overwritten"}).status_code == 503
    assert api.post("/v1/hr/workspaces", json={"name": "x", "id": "research"}).status_code == 503
    assert store == kept
    broken["on"] = False
    # and with the list readable, a second Research is a new workspace beside the first
    assert api.post("/v1/hr/workspaces", json={"name": "Research"}).json()["id"] == "research-2"


def test_rename_over_a_list_that_could_not_be_read_is_not_a_missing_workspace(world):
    api, store, broken = world
    _renamed_default_and_research(api)
    broken["on"] = True
    r = api.patch("/v1/hr/workspaces/research", json={"name": "Lab"})
    assert r.status_code == 503, r.text
    broken["on"] = False
    assert api.patch("/v1/hr/workspaces/research", json={"name": "Lab"}).json()["name"] == "Lab"


def test_an_organization_with_no_workspace_still_gets_its_default(world):
    api, store, _ = world
    d = api.get("/v1/hr/workspaces").json()
    assert [w["id"] for w in d["workspaces"]] == ["default"]
    assert store[f"ws.{ORG}.default"]["name"] == "Default Workspace"
