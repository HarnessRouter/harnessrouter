"""The local plugin registry: a self-hosted instance has no engine, so a workspace connects a
plugin through this gateway's own routes and the records live in its own store. The plugs server
reads them exactly as it reads the hosted registry's, so the same tools, the same include, the
same audit rows follow. The browser is a platform plug (no credential); GitHub carries one.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as gw  # noqa: E402
import browser_plane  # noqa: E402
import plugs_plane  # noqa: E402
import test_browser as tb  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORG = "localorg"
WS = "default"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "m@local", "x-harness-workspace": WS}
GH_TOKEN = "ghp_SENTINEL_never_returned_3c3c"
_seen: list[str] = []


@pytest.fixture(scope="module")
def client():
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture
def world(monkeypatch):
    ven, posted = tb.Vendor(), []
    monkeypatch.setattr(gw, "PLUGS_REGISTRY_URL", "")          # no engine: the local registry answers
    monkeypatch.setattr(gw, "_PLUGS_ORGS", {"*"})
    monkeypatch.setattr(browser_plane, "API_KEY", tb.VENDOR_KEY)
    monkeypatch.setattr(browser_plane, "transport", httpx.MockTransport(ven.handle))
    monkeypatch.setattr(browser_plane, "connector", tb._connect)
    monkeypatch.setattr(browser_plane, "resolves_private", tb._resolves)
    monkeypatch.setattr(gw, "_report_usage", lambda org, metric, amount, **kw: posted.append((org, metric, amount)))
    tb.browsers.clear()
    for s in list(browser_plane.sessions().values()):
        s.closed = True
    browser_plane.sessions().clear()
    browser_plane.registry = browser_plane.LocalRegistry()
    gw._browser_open_locks.clear()
    gw._plug_trace_handles.clear()
    gw._plug_fields_cache.clear()
    yield ven, posted


def _req(client, method, path, body=None, headers=None):
    r = client.request(method, path, json=body, headers={**HEADERS, **(headers or {})})
    _seen.append(r.text)
    return r


def _harness(client, **extra) -> str:
    return _req(client, "POST", "/v1/harnesses", {"name": "Local", "base": "claude-code", **extra}).json()["id"]


def _rpc(client, tok: str, name: str, args: dict | None = None):
    r = client.post("/v1/mcp/plugs", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
    _seen.append(r.text)
    return r.json()["result"]


def _rows(hid: str, plug: str) -> list[dict]:
    rows = [r for r in asyncio.run(gw.BACKING.graph.find("PlugCall", {"harness": hid})) if r.get("plug") == plug]
    return sorted(rows, key=lambda r: (int(r["finished"]), -int(r["started"])))


def test_the_catalog_and_the_browser_connected_here(client, world):
    ven, posted = world
    cat = _req(client, "GET", "/v1/plugs").json()
    assert cat["workspace"] == WS
    assert [p["type"] for p in cat["plugs"]] == ["browser", "github", "vercel", "insforge"]
    b = cat["plugs"][0]
    assert b["status"] == "missing" and b["source"] == "platform" and b["official"] is True and b["tools"] == 13
    assert b["pricing"]["usd_per_unit"] == 0.02 and b["pricing"]["markup"] == 0.0 and b["secrets_needed"] == []
    assert cat["plugs"][1]["secrets_needed"] == ["token"] and cat["plugs"][1]["status"] == "missing"

    # a harness may include it before the workspace connects it: the tool list is there, a call says so
    hid = _harness(client)
    r = _req(client, "POST", f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["browser"]})
    assert r.status_code == 200 and r.json()["status"] == {"browser": "missing"}
    tok = gw._mint_hosted_cred(hid, "sess1", gw._hosted_secret_key(hid, "mcp.plugs"))
    out = _rpc(client, tok, "browser.get_url")
    assert out["isError"] and out["content"][0]["text"].startswith("The workspace has no Browser plugin connected")

    # the workspace turns it on, with its site lists
    r = _req(client, "PUT", "/v1/plugs/browser", {"enabled": True, "config": {"allow_domains": ["Example.com", "*.iana.org"], "deny_domains": ["ads.example.com"]}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "connected" and d["config"] == {"allow_domains": ["example.com", "iana.org"], "deny_domains": ["ads.example.com"], "proxy": False}
    assert d["version"] == 1 and d["secrets_set"] == []
    assert _req(client, "GET", f"/v1/harnesses/{hid}/servers/mcp.plugs").json()["status"] == {"browser": "connected"}
    # the agent browses; the site lists come from the record
    out = _rpc(client, tok, "browser.navigate", {"url": "https://example.com/"})
    assert out["isError"] is False, out
    assert out["content"][0]["text"].startswith("Opened https://example.com/ (Example Domain)")
    out = _rpc(client, tok, "browser.navigate", {"url": "https://public.example/leak"})
    assert out["isError"] and "outside the ones" in out["content"][0]["text"]
    # a settings change is a new version, read on the next call
    r = _req(client, "PUT", "/v1/plugs/browser", {"enabled": True, "config": {"allow_domains": []}})
    assert r.json()["version"] == 2 and r.json()["config"]["allow_domains"] == [] and r.json()["config"]["deny_domains"] == ["ads.example.com"]
    assert _rpc(client, tok, "browser.navigate", {"url": "https://public.example/leak"})["isError"] is False
    # the count the Plugins page shows
    other = _harness(client)
    a = _req(client, "GET", "/v1/plugs/browser/attachments").json()
    assert a["attached"] == 1 and a["harnesses"] >= 2 and a["harness_list"][0]["id"] == hid and other not in [h["id"] for h in a["harness_list"]]
    # the stop writes the session row with the vendor's dollars, and the meter is asked
    asyncio.run(gw._browser_close("sess1", "turn_end"))
    end = _rows(hid, "browser")[-1]
    assert end["unit"] == "browser.usd" and end["usd"] == "0.000667" and json.loads(end["detail"])["reason"] == "turn_end"
    assert posted[-1] == (ORG, "browser.usd", 0.000667) and ven.stopped == ["bu_1"]
    # turned off: the tools refuse in a sentence, the record stays
    r = _req(client, "PUT", "/v1/plugs/browser", {"enabled": False})
    assert r.json()["status"] == "disabled"
    out = _rpc(client, tok, "browser.get_url")
    assert out["isError"] and "turned off" in out["content"][0]["text"]
    assert _req(client, "GET", "/v1/plugs").json()["plugs"][0]["status"] == "disabled"


def test_a_credentialed_plugin_keeps_its_secret_in_the_store(client, world, monkeypatch):
    calls = []

    def vendor(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        assert r.headers.get("Authorization") == f"Bearer {GH_TOKEN}"
        if r.url.path == "/repos/acme/site/contents/README.md":
            return httpx.Response(200, json={"type": "file", "encoding": "base64", "path": "README.md", "sha": "abc", "size": 5, "content": "aGVsbG8="})
        return httpx.Response(404, json={"message": "no"})
    monkeypatch.setattr(plugs_plane, "transport", httpx.MockTransport(vendor))
    # without its token the plug needs auth; with it, connected; the token is in the store, not the record
    r = _req(client, "PUT", "/v1/plugs/github", {"enabled": True, "config": {"repo": "acme/site", "owner": "acme", "default_branch": "main"}})
    assert r.status_code == 200 and r.json()["status"] == "needs_auth" and r.json()["secrets_set"] == []
    r = _req(client, "PUT", "/v1/plugs/github", {"enabled": True, "secrets": {"token": GH_TOKEN}})
    assert r.json()["status"] == "connected" and r.json()["secrets_set"] == ["token"] and r.json()["config"]["repo"] == "acme/site"
    assert asyncio.run(gw._vault_get(ORG, "plug-default-github-token")) == GH_TOKEN
    row = asyncio.run(gw.BACKING.graph.find("Plug", {"workspace": WS, "type": "github"}))[0]
    assert GH_TOKEN not in json.dumps(row)
    hid = _harness(client)
    assert _req(client, "POST", f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]}).json()["status"] == {"github": "connected"}
    tok = gw._mint_hosted_cred(hid, "sess2", gw._hosted_secret_key(hid, "mcp.plugs"))
    out = _rpc(client, tok, "github.get_file_contents", {"path": "README.md"})
    assert out["isError"] is False, out
    assert json.loads(out["content"][0]["text"])["content"] == "hello" and calls[-1].url.host == "api.github.com"
    assert _rows(hid, "github")[-1]["outcome"] == "ok"
    # a bad setting and an unknown plugin are refused
    assert _req(client, "PUT", "/v1/plugs/github", {"config": {"colour": "red"}}).status_code == 400
    assert _req(client, "PUT", "/v1/plugs/github", {"secrets": {"password": "x"}}).status_code == 400
    assert _req(client, "PUT", "/v1/plugs/printer", {"enabled": True}).status_code == 404
    # another workspace of the same instance has its own records
    other = _req(client, "GET", "/v1/plugs", headers={"x-harness-workspace": "ws2"}).json()
    assert other["workspace"] == "ws2" and all(p["status"] == "missing" for p in other["plugs"])


def test_a_package_that_requires_the_browser_includes_it_here_too(client, world):
    _req(client, "PUT", "/v1/plugs/browser", {"enabled": True})
    manifest = {"$schema": tb.PLUGIN_SCHEMA, "name": "needs-browser", "version": "1.0.0", "requires": {"plugs": ["browser"]}}
    r = _req(client, "POST", "/v1/harnesses", {"name": "Packaged", "base": "claude-code",
                                                "plugins": [{"files": [{"path": "plugin.json", "content": json.dumps(manifest)}]}]})
    assert r.status_code == 200, r.text
    assert [e["id"] for e in r.json()["mcpServers"]] == ["mcp.plugs"]
    assert _req(client, "GET", f"/v1/harnesses/{r.json()['id']}/servers/mcp.plugs").json()["status"] == {"browser": "connected"}


def test_no_secret_ever_reached_a_caller():
    assert _seen
    for body in _seen:
        assert GH_TOKEN not in body and tb.VENDOR_KEY not in body and "SENTINEL" not in body


def test_a_harness_created_without_a_workspace_header_is_in_the_default_workspace(client, world):
    """The guide's bare API calls carry no workspace header: PUT /v1/plugs/browser lands in the
    default workspace, and a harness created the same way carries no stamp. On a self-hosted
    instance that harness is in the default workspace, the leniency its listing already applies,
    so the include succeeds, binds to "default", and the attachment count sees it."""
    bare = {k: v for k, v in HEADERS.items() if k != "x-harness-workspace"}
    _req(client, "PUT", "/v1/plugs/browser", {"enabled": True})
    r = client.request("POST", "/v1/harnesses", json={"name": "Bare", "base": "claude-code"}, headers=bare)
    hid = r.json()["id"]
    assert not r.json().get("workspace")
    r = client.request("POST", f"/v1/harnesses/{hid}/servers/plugs", json={"plugs": ["browser"]}, headers=bare)
    assert r.status_code == 200, r.text
    assert r.json()["workspace"] == "default" and r.json()["status"]["browser"] == "connected"
    a = _req(client, "GET", "/v1/plugs/browser/attachments").json()
    assert hid in {h["id"] for h in a["harness_list"]} and a["attached"] <= a["harnesses"]
    # behind a registry the stamp is required: a tenant is never guessed there
    import unittest.mock as um
    with um.patch.object(gw, "PLUGS_REGISTRY_URL", "http://registry"):
        assert gw._harness_workspace_for_plugs({"workspace": ""}) == ""
        assert gw._harness_workspace_for_plugs({"workspace": "ws1"}) == "ws1"
