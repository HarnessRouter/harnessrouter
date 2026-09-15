"""Plugins (UHP 2026-09-12, Plugins chapter): a package is read as an Agent Plugins client reads
it, what the server derives is what it records, refusals happen at configuration time, and a
harness exports as a package that installs again.

These drive the public UHP surface through the app so they measure the same thing the P-series
of the conformance suite measures, without a live turn: create, read, files, export, refusals.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORG = "plugorg"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "tester@example.com"}
MANIFEST_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def _package(name="demo-plugin", *, manifest=None, mcp=None, skill=True, extra=None):
    files = []
    if manifest is not None:
        files.append({"path": "plugin.json", "content": json.dumps(manifest)})
    if mcp is not None:
        files.append({"path": "mcp.json", "content": json.dumps(mcp)})
    if skill:
        files += [
            {"path": "skills/demo-skill/SKILL.md",
             "content": "---\nname: demo-skill\ndescription: A fixture skill.\n---\n\nSee references/data.md.\n"},
            {"path": "skills/demo-skill/references/data.md", "content": "nested\n"},
            {"path": "bin/tool.bin", "content_b64": "AAECAwQF"},
        ]
    return files + (extra or [])


MANIFEST = {"$schema": MANIFEST_SCHEMA, "name": "demo-plugin", "version": "1.0.0",
            "description": "A fixture.", "author": {"name": "Tester"}}
MCP = {"$schema": MCP_SCHEMA, "mcpServers": {
    "remote": {"type": "streamable-http", "url": "https://mcp.example.invalid/mcp",
               "headers": {"X-Team": "fixture"}},
    "local": {"type": "stdio", "command": "./bin/tool.bin", "args": ["--data", "${PLUGIN_DATA}"],
              "env": {"MODE": "test"}, "cwd": "${PLUGIN_ROOT}"},
}}


@pytest.fixture(scope="module")
def api():
    with TestClient(app.app) as c:
        class Api:
            def __getattr__(self, m):
                def call(path, **kw):
                    kw["headers"] = {**HEADERS, **(kw.get("headers") or {})}
                    return getattr(c, m)(path, **kw)
                return call
        yield Api()


def _create(api, **cfg):
    r = api.post("/v1/harnesses", json={"name": "Plugged", "base": "claude-code", **cfg})
    assert r.status_code == 200, r.text
    return r.json()


def test_discovery_advertises_both_versions_and_the_plugin_schemas(api):
    d = api.get("/v1/uhp").json()
    assert d["versions"] == ["2026-09-12", "2026-08-11"] and d["default_version"] == "2026-09-12"
    assert d["capabilities"]["plugins"] is True
    assert d["plugin_schemas"] == [MANIFEST_SCHEMA]
    # Both versions from one code path: a 2026-08-11 request is honoured and echoed as such.
    r = api.get("/v1/uhp", headers={"UHP-Version": "2026-08-11"})
    assert r.status_code == 200 and r.headers["uhp-version"] == "2026-08-11"
    r = api.get("/v1/uhp", headers={"UHP-Version": "2025-01-01"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_protocol_version"


def test_a_package_is_derived_not_copied(api):
    h = _create(api, plugins=[{"files": _package(manifest=MANIFEST, mcp=MCP)}])
    assert h["mcpServers"] == [] and h["skills"] == [], "the harness's own lists absorbed the plugin's"
    (pl,) = h["plugins"]
    assert pl["name"] == "demo-plugin" and pl["enabled"] is True and pl["blob"]
    assert pl["manifest"]["name"] == "demo-plugin"
    servers = {s["name"]: s for s in pl["mcpServers"]}
    assert servers["remote"]["transport"] == "http" and servers["remote"]["headers"] == {"X-Team": "fixture"}
    assert servers["local"]["transport"] == "stdio" and servers["local"]["command"] == "./bin/tool.bin"
    assert servers["local"]["args"] == ["--data", "${PLUGIN_DATA}"], "placeholders must come back unexpanded"
    assert [s["name"] for s in pl["skills"]] == ["demo-skill"]
    assert pl["skipped"] == []
    # the files endpoint returns the whole package, byte for byte
    r = api.get(f"/v1/harnesses/{h['id']}/plugins/demo-plugin/files")
    assert r.status_code == 200
    paths = sorted(f["path"] for f in r.json()["files"])
    assert paths == ["bin/tool.bin", "mcp.json", "plugin.json", "skills/demo-skill/SKILL.md",
                     "skills/demo-skill/references/data.md"]
    assert any(f.get("content_b64") == "AAECAwQF" for f in r.json()["files"])
    # a read then write keeps the package
    g = api.get(f"/v1/harnesses/{h['id']}").json()
    r = api.put(f"/v1/harnesses/{h['id']}", json={"name": "Renamed", "base": g["base"],
                                                  "plugins": g["plugins"], "skills": g["skills"],
                                                  "mcp_servers": g["mcpServers"]})
    assert r.status_code == 200, r.text
    r = api.get(f"/v1/harnesses/{h['id']}/plugins/demo-plugin/files")
    assert sorted(f["path"] for f in r.json()["files"]) == paths


def test_no_manifest_is_refused(api):
    r = api.post("/v1/harnesses", json={"name": "x", "base": "claude-code",
                                        "plugins": [{"files": _package(manifest=None, mcp=MCP)}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "plugin_invalid"


def test_unknown_schema_is_refused_naming_the_supported_ones(api):
    m = {**MANIFEST, "$schema": "https://agent-plugins.org/schemas/0.0.1/plugin.schema.json"}
    r = api.post("/v1/harnesses", json={"name": "x", "base": "claude-code",
                                        "plugins": [{"files": _package(manifest=m, mcp=None)}]})
    assert r.status_code == 422
    e = r.json()["error"]
    assert e["code"] == "unsupported_plugin_schema" and e["detail"]["supported"] == [MANIFEST_SCHEMA]


def test_a_name_that_contradicts_the_manifest_is_refused(api):
    r = api.post("/v1/harnesses", json={"name": "x", "base": "claude-code",
                                        "plugins": [{"name": "other", "files": _package(manifest=MANIFEST, mcp=None)}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "plugin_invalid"


def test_an_escaping_path_is_refused(api):
    r = api.post("/v1/harnesses", json={"name": "x", "base": "claude-code",
                                        "plugins": [{"files": _package(manifest=MANIFEST, mcp=None,
                                                                       extra=[{"path": "../x", "content": ""}])}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "plugin_invalid"


def test_an_invalid_component_is_skipped_and_recorded(api):
    mcp = {"$schema": MCP_SCHEMA, "mcpServers": {
        "good": {"type": "streamable-http", "url": "https://mcp.example.invalid/mcp"},
        "bad": {"type": "carrier-pigeon", "url": "https://x"},
        "leaky": {"type": "stdio", "command": "./bin/tool.bin", "env": {"PLUGIN_ROOT": "/tmp"}},
    }}
    broken_skill = [{"path": "skills/wrong-name/SKILL.md",
                     "content": "---\nname: other\ndescription: x\n---\n"}]
    h = _create(api, plugins=[{"files": _package(manifest={**MANIFEST, "vendorField": 1},
                                                  mcp=mcp, extra=broken_skill)}])
    (pl,) = h["plugins"]
    assert [s["name"] for s in pl["mcpServers"]] == ["good"]
    assert [s["name"] for s in pl["skills"]] == ["demo-skill"]
    paths = sorted(s["path"] for s in pl["skipped"])
    assert paths == ["mcp.json#/mcpServers/bad", "mcp.json#/mcpServers/leaky",
                     "plugin.json#/vendorField", "skills/wrong-name"]
    assert all(s["reason"] for s in pl["skipped"])


def test_a_component_collision_with_the_harness_is_refused(api):
    direct = [{"name": "remote", "url": "https://direct.example.invalid/mcp", "transport": "http"}]
    r = api.post("/v1/harnesses", json={"name": "x", "base": "claude-code", "mcp_servers": direct,
                                        "plugins": [{"files": _package(manifest=MANIFEST, mcp=MCP)}]})
    assert r.status_code == 409
    e = r.json()["error"]
    assert e["code"] == "plugin_conflict"
    assert e["detail"] == {"component": "mcp_server", "name": "remote", "between": ["harness", "demo-plugin"]}


def test_two_plugins_with_one_name_are_refused(api):
    r = api.post("/v1/harnesses", json={"name": "x", "base": "claude-code",
                                        "plugins": [{"files": _package(manifest=MANIFEST, mcp=None)},
                                                    {"files": _package(manifest=MANIFEST, mcp=None, skill=False)}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "plugin_conflict"


def test_a_disabled_plugin_stays_installed_and_clears_collisions(api):
    direct = [{"name": "remote", "url": "https://direct.example.invalid/mcp", "transport": "http"}]
    h = _create(api, mcp_servers=direct, plugins=[{"files": _package(manifest=MANIFEST, mcp=MCP), "enabled": False}])
    (pl,) = h["plugins"]
    assert pl["name"] == "demo-plugin" and pl["enabled"] is False


def test_a_transport_a_base_cannot_speak_is_recorded_not_refused(api):
    """codex, dsh and goose have no SSE client: an sse server in a package lands in `skipped`
    with the reason and the rest of the package installs; a base with an SSE client keeps it."""
    mcp = {"$schema": MCP_SCHEMA, "mcpServers": {
        "events": {"type": "sse", "url": "https://mcp.example.invalid/sse"},
        "remote": {"type": "streamable-http", "url": "https://mcp.example.invalid/mcp"}}}
    r = api.post("/v1/harnesses", json={"name": "x", "base": "codex", "plugins": [{"files": _package(manifest=MANIFEST, mcp=mcp)}]})
    if r.status_code == 400:
        pytest.skip(f"codex is not a creatable base here: {r.json()['error']['code']}")
    assert r.status_code == 200, r.text
    (pl,) = r.json()["plugins"]
    assert [s["name"] for s in pl["mcpServers"]] == ["remote"] and [s["name"] for s in pl["skills"]] == ["demo-skill"]
    assert pl["skipped"] == [{"path": "mcp.json#/mcpServers/events", "reason": "the codex base's client has no sse transport"}]
    r = api.post("/v1/harnesses", json={"name": "x", "base": "claude-code", "plugins": [{"files": _package(manifest=MANIFEST, mcp=mcp)}]})
    (pl,) = r.json()["plugins"]
    assert {s["name"]: s["transport"] for s in pl["mcpServers"]} == {"events": "sse", "remote": "http"} and pl["skipped"] == []


def test_a_stdio_server_installs_on_every_base(api):
    """pi's MCP adapter and dsh's MCP client each spawn a stdio server themselves (pi-mcp-adapter's
    `command`, dsh-mcp-client's `transport: stdio`), so no base refuses a package for needing a
    process: the runner hands every client the same launcher and the client runs it."""
    for base in ("pi", "dsh", "claude-code"):
        r = api.post("/v1/harnesses", json={"name": "x", "base": base,
                                            "plugins": [{"files": _package(manifest=MANIFEST, mcp=MCP)}]})
        if r.status_code == 400:
            pytest.skip(f"{base} is not a creatable base here: {r.json()['error']['code']}")
        assert r.status_code == 200, r.text
        (pl,) = r.json()["plugins"]
        assert {s["name"]: s["transport"] for s in pl["mcpServers"]} == {"remote": "http", "local": "stdio"}


def test_export_is_a_package_that_installs_again_without_credentials(api):
    direct = [{"name": "vault", "url": "https://mcp.example.invalid/mcp", "transport": "http",
               "headers": {"X-Team": "t"}, "auth": "secret-token"}]
    skill = {"name": "own-skill", "enabled": True, "files": [
        {"path": "SKILL.md", "content": "---\nname: own-skill\ndescription: mine\n---\n"},
        {"path": "references/r.md", "content": "ref"}]}
    h = _create(api, mcp_servers=direct, skills=[skill])
    r = api.get(f"/v1/harnesses/{h['id']}/plugin")
    assert r.status_code == 200, r.text
    pl = r.json()
    files = {f["path"]: f for f in pl["files"]}
    manifest = json.loads(files["plugin.json"]["content"])
    assert manifest["$schema"] == MANIFEST_SCHEMA and manifest["name"] == "plugged" == pl["name"]
    entry = json.loads(files["mcp.json"]["content"])["mcpServers"]["vault"]
    assert entry == {"type": "streamable-http", "url": "https://mcp.example.invalid/mcp"}
    assert "secret-token" not in json.dumps(pl)
    assert {s["path"] for s in pl["skipped"]} == {"mcp.json#/mcpServers/vault/auth", "mcp.json#/mcpServers/vault/headers"}
    assert {"skills/own-skill/SKILL.md", "skills/own-skill/references/r.md"} <= set(files)
    h2 = _create(api, plugins=[{"files": pl["files"]}])
    (got,) = h2["plugins"]
    assert got["name"] == "plugged"
    assert [s["name"] for s in got["mcpServers"]] == ["vault"]
    assert [s["name"] for s in got["skills"]] == ["own-skill"]


def test_a_missing_plugin_is_plugin_not_found(api):
    h = _create(api)
    r = api.get(f"/v1/harnesses/{h['id']}/plugins/nope/files")
    assert r.status_code == 404 and r.json()["error"]["code"] == "plugin_not_found"


def test_export_name_derivation():
    assert app._plugin_export_name({"name": "Contract Review Agent", "id": "chrn_x"}) == "contract-review-agent"
    assert app._plugin_export_name({"name": "acme..Tools  v2", "id": "chrn_x"}) == "acme.tools-v2"
    assert app._plugin_export_name({"name": "!!!", "id": "chrn_08da"}) == "chrn-08da"


def test_a_kit_that_ships_a_package_launches_as_an_installed_plugin(api, tmp_path, monkeypatch):
    """The starter kits carry their skills as an Agent Plugins package; launch installs it, and
    the Harness records the kit as a named, versioned plugin rather than as loose skills."""
    kid = "demo-kit"
    plug = tmp_path / kid / "plugin"
    (plug / "skills" / "demo-skill").mkdir(parents=True)
    (plug / "plugin.json").write_text(json.dumps({"$schema": MANIFEST_SCHEMA, "name": "harnessrouter-demo",
                                                   "version": "1.2.0", "description": "A kit."}))
    (plug / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\ndescription: fixture\n---\n")
    (plug / "skills" / "demo-skill" / "helper.py").write_text("print('hi')\n")
    monkeypatch.setattr(app, "_KITS_DIR", str(tmp_path))
    monkeypatch.setattr(app, "_kits", lambda: {kid: {
        "id": kid, "title": "Demo", "app": {"route": "/kits/demo"},
        "harness": {"name": "Demo", "plugin": "plugin", "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}}})
    r = api.post(f"/v1/kits/{kid}/launch", json={})
    assert r.status_code == 200, r.text
    h = r.json()["harness"]
    assert h["skills"] == [], "the kit's skills come from the package, not the direct list"
    (pl,) = h["plugins"]
    assert pl["name"] == "harnessrouter-demo" and pl["manifest"]["version"] == "1.2.0"
    assert [s["name"] for s in pl["skills"]] == ["demo-skill"] and pl["skipped"] == []
    files = api.get(f"/v1/harnesses/{h['id']}/plugins/harnessrouter-demo/files").json()["files"]
    assert sorted(f["path"] for f in files) == ["plugin.json", "skills/demo-skill/SKILL.md", "skills/demo-skill/helper.py"]
    again = api.post(f"/v1/kits/{kid}/launch", json={})
    assert again.status_code == 200 and again.json()["created"] is False and again.json()["harnessId"] == h["id"]


def test_a_kit_harness_from_before_the_package_gets_it_on_the_next_launch(api, tmp_path, monkeypatch):
    """Three kit Harnesses launched before their kits shipped packages stayed without one through a
    relaunch (hr-oss-test, 2026-09-14). Launch on an existing Harness installs the kit's current
    package, replaces an older version, and leaves a matching one alone."""
    kid = "demo-kit-before-packages"   # its own kit id: the org keeps the previous test's kit Harness
    plug = tmp_path / kid / "plugin"
    (plug / "skills" / "demo-skill").mkdir(parents=True)
    (plug / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\ndescription: fixture\n---\n")
    monkeypatch.setattr(app, "_KITS_DIR", str(tmp_path))
    kit = {"id": kid, "title": "Demo", "app": {"route": "/kits/demo"},
           "harness": {"name": "Demo", "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}}
    monkeypatch.setattr(app, "_kits", lambda: {kid: kit})
    first = api.post(f"/v1/kits/{kid}/launch", json={}).json()          # the kit ships no package yet
    assert first["created"] is True and first["harness"]["plugins"] == []
    hid = first["harnessId"]
    (plug / "plugin.json").write_text(json.dumps({"$schema": MANIFEST_SCHEMA, "name": "harnessrouter-demo",
                                                   "version": "1.0.0", "description": "A kit."}))
    kit["harness"]["plugin"] = "plugin"                                  # the kit now ships one
    again = api.post(f"/v1/kits/{kid}/launch", json={}).json()
    assert again["created"] is False and again["harnessId"] == hid
    (pl,) = again["harness"]["plugins"]
    assert pl["name"] == "harnessrouter-demo" and pl["manifest"]["version"] == "1.0.0"
    assert [s["name"] for s in pl["skills"]] == ["demo-skill"] and again["harness"]["skills"] == []
    blob = pl.get("blob")
    same = api.post(f"/v1/kits/{kid}/launch", json={}).json()["harness"]["plugins"][0]
    assert same.get("blob") == blob, "a matching version is left alone, not re-stored"
    (plug / "plugin.json").write_text(json.dumps({"$schema": MANIFEST_SCHEMA, "name": "harnessrouter-demo",
                                                   "version": "1.1.0", "description": "A kit."}))
    newer = api.post(f"/v1/kits/{kid}/launch", json={}).json()["harness"]["plugins"]
    assert [p["manifest"]["version"] for p in newer] == ["1.1.0"]
    # the same version with different bytes is a changed package too (the 2026-09-14 Skill fix)
    (plug / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\ndescription: fixture, revised\n---\n")
    revised = api.post(f"/v1/kits/{kid}/launch", json={}).json()["harness"]["plugins"][0]
    assert revised.get("blob") != newer[0].get("blob"), "changed files under the same version are installed"
    files = api.get(f"/v1/harnesses/{hid}/plugins/harnessrouter-demo/files").json()["files"]
    assert any("revised" in (f.get("content") or "") for f in files)


def test_a_kit_can_move_to_a_harness_you_already_have(api, tmp_path, monkeypatch):
    """A package migrated to another Harness takes the kit with it: launch with `harness` binds the
    kit to that Harness, installs the kit's package there, and the previous kit Harness keeps its
    sessions and package but is no longer the one the app finds."""
    kid = "demo-kit-moves"
    plug = tmp_path / kid / "plugin"
    (plug / "skills" / "demo-skill").mkdir(parents=True)
    (plug / "plugin.json").write_text(json.dumps({"$schema": MANIFEST_SCHEMA, "name": "harnessrouter-moves", "version": "1.0.0", "description": "A kit."}))
    (plug / "skills" / "demo-skill" / "SKILL.md").write_text("---\nname: demo-skill\ndescription: fixture\n---\n")
    monkeypatch.setattr(app, "_KITS_DIR", str(tmp_path))
    kits = {kid: {"id": kid, "title": "Moves", "app": {"route": "/kits/moves"},
                  "harness": {"name": "Moves", "plugin": "plugin", "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}},
            "other-kit": {"id": "other-kit", "title": "Other", "app": {"route": "/kits/other"},
                          "harness": {"name": "Other", "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}}}
    monkeypatch.setattr(app, "_kits", lambda: kits)
    first = api.post(f"/v1/kits/{kid}/launch", json={}).json(); a = first["harnessId"]
    mine = _create(api, name="Mine")
    moved = api.post(f"/v1/kits/{kid}/launch", json={"harness": mine["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["harnessId"] == mine["id"] and moved.json()["created"] is False
    h = moved.json()["harness"]
    assert h["kit"] == kid and [p["name"] for p in h["plugins"]] == ["harnessrouter-moves"]
    assert api.get(f"/v1/harnesses/{a}").json().get("kit") in (None, "")
    again = api.post(f"/v1/kits/{kid}/launch", json={}).json()
    assert again["harnessId"] == mine["id"], "the kit now finds the Harness it moved to"
    other = api.post("/v1/kits/other-kit/launch", json={"harness": mine["id"]})
    assert other.status_code == 409 and other.json()["error"]["code"] == "kit_conflict"
    r = api.post(f"/v1/kits/{kid}/launch", json={"harness": "chrn_nothere"})
    assert r.status_code == 404


def test_an_update_cannot_change_the_base(api):
    """Harnesses §5.2: id, base and createdAt are immutable on update."""
    h = _create(api)
    r = api.put(f"/v1/harnesses/{h['id']}", json={"name": "Moved", "base": "codex"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "harness_mismatch"
    assert api.get(f"/v1/harnesses/{h['id']}").json()["base"] == "claude-code"
    r = api.put(f"/v1/harnesses/{h['id']}", json={"name": "Renamed", "base": "claude-code"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
