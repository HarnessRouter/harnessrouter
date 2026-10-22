"""A starter kit launches once per WORKSPACE: a launched kit's Harness belongs to the workspace it
was launched in, so a second workspace gets its own rather than the first workspace's, which its
members could not see. And a database connection's configuration is recorded on the graph beside
the vault record that alone holds the credential."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

KIT = {"id": "slides", "title": "Slides", "harness": {"name": "Slides", "mcp_servers": [],
       "recommended": [{"base": "hermes", "model": "deepseek-v4-pro"}]}, "app": {"route": "/kits/slides"}}
DB_KIT = {"id": "dashboard", "title": "Dashboards", "harness": {"name": "Dashboards", "mcp_servers": [],
          "launch": {"database": {"engines": ["postgres"], "name": "database", "id": "mcp.database"}},
          "recommended": [{"base": "hermes", "model": "deepseek-v4-pro"}]}, "app": {"route": "/kits/dashboard"}}


class _Req:
    headers: dict = {}


@pytest.fixture
def world(monkeypatch):
    store: dict = {}
    who = {"org": "org.a", "member": "m@a", "workspace": "org.a__ws1", "workspace_default": False}

    async def _principal(request):
        return dict(who)

    async def _vg_list_by_org(label, org):
        return [dict(v, id=k) for k, v in store.items() if v.get("org") == org]

    async def _vertex_get(vid):
        return dict(store[vid], id=vid) if vid in store else None

    async def _vg_upsert(label, vid, props, **kw):
        store.setdefault(vid, {}).update(props)

    async def _find(label, eq=None, neq=None):
        rows = [dict(v, id=k) for k, v in store.items()]
        return [r for r in rows if all(str(r.get(k)) == str(v) for k, v in (eq or {}).items())
                and all(str(r.get(k)) != str(v) for k, v in (neq or {}).items())]

    async def _servable_models(org, backend):
        return None

    async def _skills_prepare(skills):
        return list(skills or [])

    async def _plugins_prepare(body, org, previous=None, reserved_mcp=()):
        return []

    async def _mcp_migrate(org, hid, v):
        return v
    monkeypatch.setattr(gw.BACKING.graph, "find", _find)
    for name, fn in (("_principal", _principal), ("_vg_list_by_org", _vg_list_by_org), ("_vertex_get", _vertex_get),
                     ("_vg_upsert", _vg_upsert), ("_servable_models", _servable_models), ("_skills_prepare", _skills_prepare),
                     ("_plugins_prepare", _plugins_prepare), ("_mcp_migrate", _mcp_migrate)):
        monkeypatch.setattr(gw, name, fn)
    monkeypatch.setattr(gw, "_kits", lambda: {"slides": KIT, "dashboard": DB_KIT})
    monkeypatch.setattr(gw, "_kit_plugin", lambda kit: None)
    monkeypatch.setattr(gw, "_kit_skills", lambda kit: [])
    return store, who


def test_a_kit_launches_once_per_workspace(world):
    store, who = world
    first = asyncio.run(gw.launch_kit("slides", _Req(), None))
    again = asyncio.run(gw.launch_kit("slides", _Req(), None))
    assert first["created"] and not again["created"] and again["harnessId"] == first["harnessId"]
    who["workspace"] = "org.a__ws2"
    other = asyncio.run(gw.launch_kit("slides", _Req(), None))
    assert other["created"] and other["harnessId"] != first["harnessId"]
    assert store[other["harnessId"]]["workspace"] == "org.a__ws2"
    slides = next(k for k in asyncio.run(gw.list_kits(_Req()))["kits"] if k["id"] == "slides")
    assert slides["launched"] and slides["harnessId"] == other["harnessId"]
    who["workspace"] = "org.a__ws3"
    assert not next(k for k in asyncio.run(gw.list_kits(_Req()))["kits"] if k["id"] == "slides")["launched"]


def test_a_legacy_unstamped_kit_harness_belongs_to_the_default_workspace(world):
    store, who = world
    store["chrn_old"] = {"org": "org.a", "kit": "slides", "workspace": "", "deleted": "0", "name": "Slides", "base": "hermes"}
    who.update(workspace="org.a__hr_default", workspace_default=True)
    assert asyncio.run(gw.launch_kit("slides", _Req(), None))["harnessId"] == "chrn_old"
    who.update(workspace="org.a__ws9", workspace_default=False)
    assert asyncio.run(gw.launch_kit("slides", _Req(), None))["harnessId"] != "chrn_old"


def test_a_database_connection_is_recorded_on_the_graph_without_its_credential(world, monkeypatch):
    store, who = world
    records = {}

    async def _db_validate(engine, conn):
        return "postgres", conn, "db.example", "shop"

    async def _hosted_put_record(org, key, record, *, secret=True, param="connection_string"):
        records[key] = record

    async def _mcp_write(hid, servers):
        store[hid]["mcp_servers"] = json.dumps(servers)
    monkeypatch.setattr(gw, "_db_validate", _db_validate)
    monkeypatch.setattr(gw, "_hosted_put_record", _hosted_put_record)
    monkeypatch.setattr(gw, "_mcp_write", _mcp_write)
    monkeypatch.setattr(gw, "_own_origins", lambda: ["https://api.example"])
    body = gw.KitLaunchBody(database=gw.KitDatabaseBody(engine="postgres", connection_string="postgresql://u:p@db.example/shop", sample_rows=False))
    hid = asyncio.run(gw.launch_kit("dashboard", _Req(), body))["harnessId"]
    key = next(iter(records))
    conns = [v for v in store.values() if v.get("kind") == "database"]
    assert len(conns) == 1 and conns[0]["harness"] == hid and conns[0]["secret_key"] == key
    assert conns[0]["workspace"] == "org.a__ws1" and conns[0]["database"] == "shop" and "u:p@" not in json.dumps(conns[0])
    assert asyncio.run(gw._connections_of("org.a", hid))[0]["database"] == "shop"


def test_a_relaunch_carries_the_kits_current_prompt(world, monkeypatch):
    """The prompt is the kit's, like its package: a kit whose prompt changed reaches the Harness a
    workspace already runs on the next launch, and an unchanged prompt rewrites nothing."""
    store, who = world
    kit = json.loads(json.dumps(KIT)); kit["harness"]["system_prompt"] = "Build decks."
    monkeypatch.setattr(gw, "_kits", lambda: {"slides": kit})
    hid = asyncio.run(gw.launch_kit("slides", _Req(), None))["harnessId"]
    assert store[hid]["system_prompt"] == "Build decks."
    stamp = store[hid]["updated_at"]
    again = asyncio.run(gw.launch_kit("slides", _Req(), None))
    assert not again["created"] and store[hid]["updated_at"] == stamp       # same prompt: untouched
    kit["harness"]["system_prompt"] = "Build decks. The person sees only ./deck.json."
    third = asyncio.run(gw.launch_kit("slides", _Req(), None))
    assert not third["created"] and third["harnessId"] == hid
    assert store[hid]["system_prompt"] == "Build decks. The person sees only ./deck.json."
    assert third["harness"]["systemPrompt"] == "Build decks. The person sees only ./deck.json."


def test_a_launch_on_a_base_and_model_nothing_serves_is_422_model_unavailable(world, monkeypatch):
    """UHP Errors §3.1: a model that cannot be served when the work is sent is `model_unavailable`,
    422, the same answer a task gets (#517). It was 400 here."""
    async def serves_nothing(org, base, model):
        return False
    monkeypatch.setattr(gw, "_base_serves", serves_nothing)
    with pytest.raises(gw.HTTPException) as e:
        asyncio.run(gw.launch_kit("slides", _Req(), gw.KitLaunchBody(base="hermes", model="deepseek-v4-pro")))
    assert e.value.status_code == 422
    assert e.value.detail["code"] == "model_unavailable" and e.value.detail["param"] == "model"
    assert "deepseek-v4-pro" in e.value.detail["message"]           # the words are unchanged


def test_a_kit_whose_harness_list_could_not_be_read_is_not_launched(world, monkeypatch):
    """Launch is idempotent on the harness list alone, and the forgiving read answers a failed
    read with the same empty list as an organization that holds no Harness — so provisioning on
    it is exactly how "the second press must not leave them with two Harnesses" is broken. A read
    the store could not answer refuses the launch instead, with nothing written."""
    store, who = world

    async def unreadable(label, eq=None, neq=None):
        raise RuntimeError("graph plane unreachable")
    monkeypatch.setattr(gw.BACKING.graph, "find_strict", unreadable)
    with pytest.raises(gw.HTTPException) as e:
        asyncio.run(gw.launch_kit("slides", _Req(), None))
    assert e.value.status_code == 503 and e.value.detail["type"] == "server_error"
    assert not store                                     # refused BEFORE anything was provisioned


def test_an_organization_holding_no_harness_still_launches_the_kit_once(world, monkeypatch):
    """The distinction the strict read keeps: an empty list the store answered with is a first
    launch, not a failure. The first press provisions, the second hands the same Harness back."""
    store, who = world

    async def nothing(label, eq=None, neq=None):
        return []
    monkeypatch.setattr(gw.BACKING.graph, "find_strict", nothing)
    first = asyncio.run(gw.launch_kit("slides", _Req(), None))
    again = asyncio.run(gw.launch_kit("slides", _Req(), None))
    assert first["created"] and not again["created"]
    assert again["harnessId"] == first["harnessId"] and len([v for v in store.values() if v.get("kit") == "slides"]) == 1
