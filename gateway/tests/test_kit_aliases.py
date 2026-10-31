"""A renamed starter kit keeps the Harnesses people launched under its old name.

kit.json says what the kit was called before: `aliases` (its old ids), `harness.replaces_packages`
(its package's old names) and `harness.replaces_names` (its Harness's old default names). A
Harness whose stored `kit` is an alias is the kit's: its record and the catalog report the current
id, a launch under either id reuses it, and a relaunch moves it to the current id, package and
default name. A name the person chose is never touched."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

BOT = {"id": "harness-bot", "aliases": ["workplace"], "title": "Harness Bot",
       "harness": {"name": "Harness Bot recruiter", "mcp_servers": [], "system_prompt": "Recruit.",
                   "replaces_packages": ["harnessrouter-workplace-recruiter"],
                   "replaces_names": ["Workplace recruiter"],
                   "recommended": [{"base": "hermes", "model": "deepseek-v4-pro"}]},
       "app": {"route": "/kits/harness-bot"}}
SLIDES = {"id": "slides", "title": "Slides", "harness": {"name": "Slides", "mcp_servers": [],
          "recommended": [{"base": "hermes", "model": "deepseek-v4-pro"}]}, "app": {"route": "/kits/slides"}}
WS = "org.a__ws1"


def _pkg(name: str, version: str = "1.0.0", body: str = "") -> dict:
    return {"files": [{"path": "plugin.json", "content": json.dumps({"name": name, "version": version})},
                      {"path": "skills/x/SKILL.md", "content": f"---\nname: x\ndescription: x\n---\n{body}"}],
            "enabled": True}


class _Req:
    headers: dict = {}


@pytest.fixture
def world(monkeypatch):
    store: dict = {}
    who = {"org": "org.a", "member": "m@a", "workspace": WS, "workspace_default": False}

    async def _principal(request):
        return dict(who)

    async def _vg_list_by_org(label, org):
        return [dict(v, id=k) for k, v in store.items() if v.get("org") == org]

    async def _vertex_get(vid):
        return dict(store[vid], id=vid) if vid in store else None

    async def _vg_upsert(label, vid, props, **kw):
        store.setdefault(vid, {}).update(props)

    async def _servable_models(org, backend):
        return None

    async def _skills_prepare(skills):
        return list(skills or [])

    async def _plugins_prepare(body, org, previous=None, reserved_mcp=()):
        # what is stored for a package: its name and version, as the real step derives them
        out = []
        for e in body.plugins or []:
            if "files" in e:
                m = gw._plugin_read_package(e["files"])
                out.append({"name": m["name"], "manifest": m.get("manifest") or {}, "enabled": True})
            else:
                out.append(e)
        return out

    async def _mcp_migrate(org, hid, v):
        return v

    async def _plugs_ensure_required(org, hid):
        return False

    async def _env_check(org, env_id):
        return None
    for name, fn in (("_principal", _principal), ("_vg_list_by_org", _vg_list_by_org), ("_vertex_get", _vertex_get),
                     ("_vg_upsert", _vg_upsert), ("_servable_models", _servable_models), ("_skills_prepare", _skills_prepare),
                     ("_plugins_prepare", _plugins_prepare), ("_mcp_migrate", _mcp_migrate),
                     ("_plugs_ensure_required", _plugs_ensure_required), ("_environment_check_ref", _env_check)):
        monkeypatch.setattr(gw, name, fn)
    monkeypatch.setattr(gw, "_kits", lambda: {"slides": SLIDES, "harness-bot": BOT})
    monkeypatch.setattr(gw, "_kit_plugin", lambda kit: _pkg("harnessrouter-harness-bot-recruiter", "1.1.0") if kit is BOT else None)
    monkeypatch.setattr(gw, "_kit_skills", lambda kit: [])
    monkeypatch.setattr(gw, "_kit_launch_database", lambda kit: None)
    monkeypatch.setattr(gw, "_kit_launch_media", lambda kit: None)
    return store


def _legacy(store, hid="chrn_old", name="Workplace recruiter", plugins=None):
    store[hid] = {"org": "org.a", "workspace": WS, "kit": "workplace", "name": name, "base": "hermes",
                  "system_prompt": "Recruit.", "deleted": "0",
                  "plugins": json.dumps(plugins if plugins is not None else
                                        [{"name": "harnessrouter-workplace-recruiter", "manifest": {"version": "1.0.1"}},
                                         {"name": "my-own-package", "manifest": {"version": "2.0.0"}}])}
    return hid


def _names(store, hid):
    return sorted(e["name"] for e in json.loads(store[hid]["plugins"]))


def test_ids_resolve_to_the_current_kit():
    kits = {"harness-bot": BOT, "slides": SLIDES}
    gw._kits, real = (lambda: kits), gw._kits
    try:
        assert [gw._kit_id(k) for k in ("workplace", "harness-bot", "slides", "", None, "gone")] == \
            ["harness-bot", "harness-bot", "slides", "", "", "gone"]
    finally:
        gw._kits = real


def test_a_harness_launched_under_the_old_id_is_the_kits(world):
    hid = _legacy(world)
    assert gw._harness_out(dict(world[hid], id=hid))["kit"] == "harness-bot"
    rows = {k["id"]: k for k in asyncio.run(gw.list_kits(_Req()))["kits"]}
    assert set(rows) == {"slides", "harness-bot"}
    assert rows["harness-bot"]["launched"] and rows["harness-bot"]["harnessId"] == hid
    assert not rows["slides"]["launched"]


@pytest.mark.parametrize("asked", ["harness-bot", "workplace"])
def test_a_relaunch_reuses_it_and_moves_it_to_the_current_id_package_and_name(world, asked):
    hid = _legacy(world)
    out = asyncio.run(gw.launch_kit(asked, _Req(), None))
    assert out["kit"] == "harness-bot" and out["harnessId"] == hid and out["created"] is False
    assert world[hid]["kit"] == "harness-bot"
    assert world[hid]["name"] == "Harness Bot recruiter"
    # the old recruiter package gives way to the new one; a package of the person's own stays
    assert _names(world, hid) == ["harnessrouter-harness-bot-recruiter", "my-own-package"]
    assert len([h for h in world.values() if h.get("kit")]) == 1          # no second recruiter


def test_a_name_the_person_chose_is_never_touched(world):
    hid = _legacy(world, name="Our hiring desk")
    asyncio.run(gw.launch_kit("harness-bot", _Req(), None))
    assert world[hid]["name"] == "Our hiring desk" and world[hid]["kit"] == "harness-bot"


def test_the_old_package_goes_even_when_the_new_one_is_already_current(world):
    # A Harness that already holds the current package at the current version, and still the old
    # one beside it: the "nothing changed" shortcut must not keep both.
    files = _pkg("harnessrouter-harness-bot-recruiter", "1.1.0")["files"]
    hid = _legacy(world, plugins=[{"name": "harnessrouter-workplace-recruiter", "manifest": {"version": "1.0.1"}},
                                  {"name": "harnessrouter-harness-bot-recruiter", "manifest": {"version": "1.1.0"}, "blob": "b1"}])

    async def files_of(entry, org):
        return files
    gw_files = gw._plugin_files_of
    gw._plugin_files_of = files_of
    try:
        v2 = asyncio.run(gw._kit_plugin_ensure("org.a", hid, dict(world[hid], id=hid), _pkg("harnessrouter-harness-bot-recruiter", "1.1.0"),
                                               (), ("harnessrouter-workplace-recruiter",)))
        assert v2 is not None and _names(world, hid) == ["harnessrouter-harness-bot-recruiter"]
        # and once it is gone, the same call is the shortcut again: nothing to rewrite
        world[hid]["plugins"] = json.dumps([{"name": "harnessrouter-harness-bot-recruiter", "manifest": {"version": "1.1.0"}, "blob": "b1"}])
        assert asyncio.run(gw._kit_plugin_ensure("org.a", hid, dict(world[hid], id=hid), _pkg("harnessrouter-harness-bot-recruiter", "1.1.0"),
                                                 (), ("harnessrouter-workplace-recruiter",))) is None
    finally:
        gw._plugin_files_of = gw_files


def test_moving_the_kit_onto_its_own_legacy_harness_is_not_a_conflict(world):
    hid = _legacy(world)
    world["chrn_deck"] = {"org": "org.a", "workspace": WS, "kit": "slides", "name": "Deck", "base": "hermes", "deleted": "0", "plugins": "[]"}
    out = asyncio.run(gw.launch_kit("harness-bot", _Req(), gw.KitLaunchBody(harness=hid)))
    assert out["harnessId"] == hid and world[hid]["kit"] == "harness-bot"
    with pytest.raises(gw.HTTPException) as e:
        asyncio.run(gw.launch_kit("harness-bot", _Req(), gw.KitLaunchBody(harness="chrn_deck")))
    assert e.value.status_code == 409 and world["chrn_deck"]["kit"] == "slides"
