"""Plugs on the hosted gateway: a workspace's services (GitHub, Vercel, InsForge) attached to a
harness and reached through the hosted `plugs` MCP server.

Every request goes through the real app with local backing; the plug registry (the engine's door)
and every vendor are httpx MockTransports, so what is asserted is what a caller receives and what
the vendor was actually sent. The credential is a sentinel string: the last tests assert it appears
in no response the agent could read, whatever the route.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402
import plugs_plane  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORG = "plugorg"
WS = "plugorg__hrws1"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "m@plug", "x-harness-workspace": WS}
TOKEN = "ghs_SENTINEL_never_returned_7f3a9c"
VC_TOKEN = "vc_SENTINEL_never_returned_11aa"
INF_KEY = "ik_SENTINEL_never_returned_22bb"
TENANT = "plugorg-1a2b3c4d"
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
_seen: list[str] = []


def _record(plug: str, *, status: str = "connected", version: int = 1, org: str = ORG, refs=None, tenant=TENANT) -> dict:
    cfg = {"github": {"repo": "acme/site", "owner": "acme", "default_branch": "main"},
           "vercel": {"project": "site", "project_id": "prj_1", "team_id": "team_1"},
           "insforge": {"project": "site", "project_id": "p1", "url": "https://acme.insforge.app", "region": "eu-central"}}[plug]
    field = {"github": "token", "vercel": "token", "insforge": "api_key"}[plug]
    return {"id": f"plug.{plug}1", "org_id": org, "workspace": WS, "type": plug, "status": status,
            "effective_status": status, "source": "provisioned", "config": cfg, "vault_tenant": tenant,
            "key_refs": refs if refs is not None else [{"field": field, "ref": f"plug-plugorg-hrws1-{plug}-{field}"}],
            "version": version, "expires_at": ""}


class Registry:
    """The engine's read door: one record per (workspace, type), or 404."""

    def __init__(self):
        self.records: dict[tuple[str, str], dict] = {}
        self.fail = False
        self.reads = 0

    def handle(self, r: httpx.Request) -> httpx.Response:
        assert r.url.path == "/v1/plugs/by" and r.method == "GET", r.url
        if r.headers.get("X-Internal-Key") != "test-internal-key":
            return httpx.Response(401, json={"detail": "who?"})
        self.reads += 1
        if self.fail:
            return httpx.Response(500, text="boom")
        rec = self.records.get((r.url.params.get("workspace"), r.url.params.get("type")))
        return httpx.Response(200, json=rec) if rec else httpx.Response(404, json={"detail": "no such plug"})


class Vendor:
    """GitHub, Vercel and InsForge, answering the shapes the tools read."""

    def __init__(self):
        self.calls: list[httpx.Request] = []

    def handle(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        host, path = r.url.host, r.url.path
        if host == "api.github.com":
            assert r.headers.get("Authorization") == f"Bearer {TOKEN}", "the plug's own token, always"
            if path == "/repos/acme/site/contents/README.md":
                return httpx.Response(200, json={"type": "file", "encoding": "base64", "path": "README.md", "sha": "abc",
                                                 "size": 5, "content": base64.b64encode(b"hello").decode()})
            if path == "/repos/acme/site/contents/bad.md":
                return httpx.Response(422, json={"message": "Validation Failed"})
            if path == "/repos/acme/site/git/ref/heads/main":
                return httpx.Response(200, json={"object": {"sha": "head1"}})
            if path == "/repos/acme/site/git/commits/head1":
                return httpx.Response(200, json={"tree": {"sha": "tree0"}})
            if path == "/repos/acme/site/git/trees" and r.method == "POST":
                return httpx.Response(201, json={"sha": "tree1"})
            if path == "/repos/acme/site/git/commits" and r.method == "POST":
                return httpx.Response(201, json={"sha": "commit1"})
            if path == "/repos/acme/site/git/refs/heads/main" and r.method == "PATCH":
                return httpx.Response(200, json={"object": {"sha": "commit1"}})
            if path == "/repos/acme/site/pulls" and r.method == "POST":
                body = json.loads(r.content)
                return httpx.Response(201, json={"number": 7, "title": body["title"], "state": "open", "html_url": "https://github.com/acme/site/pull/7",
                                                 "head": {"ref": body["head"]}, "base": {"ref": body["base"]}, "user": {"login": "bot"}})
            return httpx.Response(404, json={"message": f"no mock for {r.method} {path}"})
        if host == "api.vercel.com":
            assert r.headers.get("Authorization") == f"Bearer {VC_TOKEN}"
            assert r.url.params.get("teamId") == "team_1"
            if path == "/v9/projects/prj_1":
                return httpx.Response(200, json={"id": "prj_1", "name": "site", "framework": "nextjs",
                                                 "link": {"type": "github", "org": "acme", "repo": "site", "repoId": 42, "productionBranch": "main"},
                                                 "latestDeployments": []})
            if path == "/v9/projects/prj_1/domains":
                return httpx.Response(200, json={"domains": [{"name": "site.vercel.app"}]})
            if path == "/v13/deployments" and r.method == "POST":
                body = json.loads(r.content)
                assert body["gitSource"] == {"type": "github", "repoId": 42, "ref": "main"}
                return httpx.Response(200, json={"id": "dpl_1", "url": "site-abc.vercel.app", "readyState": "QUEUED"})
            if path == "/v13/deployments/dpl_1":
                return httpx.Response(200, json={"id": "dpl_1", "url": "site-abc.vercel.app", "readyState": "READY", "target": "production"})
            return httpx.Response(404, json={"error": {"message": f"no mock for {path}"}})
        if host == "acme.insforge.app":
            assert r.headers.get("Authorization") == f"Bearer {INF_KEY}"
            if path == "/api/database/records/orders" and r.method == "GET":
                return httpx.Response(200, json=[{"id": 1, "status": "open"}])
            if path == "/api/database/records/orders" and r.method == "POST":
                assert r.headers.get("Prefer") == "return=representation"
                return httpx.Response(201, json=json.loads(r.content))
            if path == "/api/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(404, text=f"no mock for {path}")
        return httpx.Response(500, text=f"unexpected host {host}")


@pytest.fixture(scope="module")
def client():
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture
def world(monkeypatch):
    reg, ven, posted = Registry(), Vendor(), []
    rc = httpx.AsyncClient(transport=httpx.MockTransport(reg.handle))
    monkeypatch.setattr(gw, "PLUGS_REGISTRY_URL", "https://registry.example")
    monkeypatch.setattr(gw, "_PLUGS_ORGS", {ORG})
    monkeypatch.setattr(gw, "_client", lambda: rc)
    monkeypatch.setattr(plugs_plane, "transport", httpx.MockTransport(ven.handle))
    monkeypatch.setattr(plugs_plane, "DEPLOY_POLL_S", 0)
    monkeypatch.setattr(gw, "_report_usage", lambda org, metric, amount, **kw: posted.append((org, metric, amount, kw)))
    gw._plug_fields_cache.clear()
    asyncio.run(gw._vault_put(TENANT, "plug-plugorg-hrws1-github-token", TOKEN))
    asyncio.run(gw._vault_put(TENANT, "plug-plugorg-hrws1-vercel-token", VC_TOKEN))
    asyncio.run(gw._vault_put(TENANT, "plug-plugorg-hrws1-insforge-api_key", INF_KEY))
    yield reg, ven, posted
    asyncio.run(rc.aclose())


def _post(client, path, body=None, headers=None):
    r = client.post(path, json=body, headers={**HEADERS, **(headers or {})})
    _seen.append(r.text)
    return r


def _get(client, path):
    r = client.get(path, headers=HEADERS)
    _seen.append(r.text)
    return r


def _delete(client, path):
    r = client.delete(path, headers=HEADERS)
    _seen.append(r.text)
    return r


def _harness(client, headers=None) -> str:
    return _post(client, "/v1/harnesses", {"name": "Plugged", "base": "claude-code"}, headers).json()["id"]


def _key(hid: str) -> str:
    return gw._hosted_secret_key(hid, "mcp.plugs")


def _rpc(client, tok: str, method: str, params: dict | None = None, rid=1):
    r = client.post("/v1/mcp/plugs", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    _seen.append(r.text)
    return r.json().get("result") if r.status_code == 200 else r


def _calls(hid: str) -> list[dict]:
    return asyncio.run(gw.BACKING.graph.find("PlugCall", {"harness": hid}))


# ── attach, read, detach ─────────────────────────────────────────────────────────────────────
def test_attach_binds_the_harness_workspace_and_detach_scrubs(client, world):
    reg, _, _ = world
    hid = _harness(client)
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "mcp.plugs", "name": "plugs", "enabled": True, "workspace": WS,
                        "plugs": ["github"], "status": {"github": "missing"}}
    v = asyncio.run(gw._vertex_get(hid))
    entries = gw._mcp_list(v)
    assert [e["url"] for e in entries] == ["https://gateway.example/v1/mcp/plugs"]
    assert entries[0]["auth"] == f"vault:{_key(hid)}"
    rec = asyncio.run(gw._hosted_record(ORG, _key(hid)))
    assert rec["server"] == "plugs" and rec["harness"] == hid and rec["workspace"] == WS and rec["plugs"] == ["github"]

    # again, with more plugs and a narrowed tool list: still one entry, the record replaced
    reg.records[(WS, "github")] = _record("github")
    reg.records[(WS, "vercel")] = _record("vercel", status="needs_auth")
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github", "vercel"], "tools": {"vercel": ["get_project"]}})
    assert r.status_code == 200, r.text
    assert r.json()["plugs"] == ["github", "vercel"] and r.json()["tools"] == {"vercel": ["get_project"]}
    assert r.json()["status"] == {"github": "connected", "vercel": "needs_auth"}
    assert len(gw._mcp_list(asyncio.run(gw._vertex_get(hid)))) == 1
    assert _get(client, f"/v1/harnesses/{hid}/servers/mcp.plugs").json()["plugs"] == ["github", "vercel"]

    assert _delete(client, f"/v1/harnesses/{hid}/servers/plugs").json() == {"id": "mcp.plugs", "detached": True}
    assert gw._mcp_list(asyncio.run(gw._vertex_get(hid))) == []
    assert not asyncio.run(gw._hosted_record(ORG, _key(hid)))
    assert _get(client, f"/v1/harnesses/{hid}/servers/mcp.plugs").status_code == 404
    assert _delete(client, f"/v1/harnesses/{hid}/servers/plugs").status_code == 404


def test_attach_refusals(client, world, monkeypatch):
    hid = _harness(client)
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["stripe"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_plug"
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"], "tools": {"github": ["rm_rf"]}})
    assert r.status_code == 400 and "rm_rf" in r.json()["error"]["message"]
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": []})
    assert r.status_code == 400
    # a harness outside a named workspace has no company to bind
    bare = _harness(client, {"x-harness-workspace": ""})
    r = _post(client, f"/v1/harnesses/{bare}/servers/plugs", {"plugs": ["github"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "workspace_required"
    # while the feature is held, an org not on the list gets nothing
    monkeypatch.setattr(gw, "_PLUGS_ORGS", set())
    r = _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "plugs_unavailable"
    monkeypatch.setattr(gw, "_PLUGS_ORGS", {"*"})
    assert _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]}).status_code == 200


# ── the server the agent talks to ────────────────────────────────────────────────────────────
def test_the_agent_lists_and_calls_the_bound_plugs(client, world):
    reg, ven, posted = world
    hid = _harness(client)
    _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github", "insforge"], "tools": {"insforge": ["query_rows"]}})
    reg.records[(WS, "github")] = _record("github")
    reg.records[(WS, "insforge")] = _record("insforge")
    tok = gw._mint_hosted_cred(hid, "sess1", _key(hid))

    assert _rpc(client, tok, "initialize")["serverInfo"]["name"] == "plugs"
    names = [t["name"] for t in _rpc(client, tok, "tools/list")["tools"]]
    assert "github.get_file_contents" in names and "github.merge_pull_request" in names
    assert [n for n in names if n.startswith("insforge.")] == ["insforge.query_rows"]      # narrowed
    assert not [n for n in names if n.startswith("vercel.")]                                # not bound
    listed = next(t for t in _rpc(client, tok, "tools/list")["tools"] if t["name"] == "github.merge_pull_request")
    assert listed["annotations"] == {"readOnlyHint": False, "destructiveHint": True}

    out = _rpc(client, tok, "tools/call", {"name": "github.get_file_contents", "arguments": {"path": "README.md"}})
    assert out["isError"] is False, out
    assert json.loads(out["content"][0]["text"]) == {"path": "README.md", "sha": "abc", "size": 5, "content": "hello"}
    assert ven.calls[-1].url.path == "/repos/acme/site/contents/README.md"
    rows = _calls(hid)
    assert len(rows) == 1 and rows[0]["outcome"] == "ok" and rows[0]["tool"] == "get_file_contents"
    assert rows[0]["plug"] == "github" and rows[0]["risk"] == "read" and rows[0]["workspace"] == WS and rows[0]["session"] == "sess1"
    assert posted == [(ORG, "plug.call", 1.0, {"workspace": WS, "task_id": "sess1", "harness_id": hid})]

    out = _rpc(client, tok, "tools/call", {"name": "insforge.query_rows",
                                           "arguments": {"table": "orders", "filters": {"status": "eq.open"}, "limit": 5}})
    assert out["isError"] is False and json.loads(out["content"][0]["text"]) == [{"id": 1, "status": "open"}]
    assert dict(ven.calls[-1].url.params) == {"status": "eq.open", "limit": "5"}
    # a tool the binding narrowed away, and one from a plug that is not bound
    for name in ("insforge.insert_rows", "vercel.get_project", "github.nothing", "nonsense"):
        out = _rpc(client, tok, "tools/call", {"name": name, "arguments": {}})
        assert out["isError"] and "No tool named" in out["content"][0]["text"], name


def test_the_vendors_refusal_is_the_agents_tool_error_and_still_a_call(client, world):
    reg, ven, posted = world
    hid = _harness(client)
    _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]})
    reg.records[(WS, "github")] = _record("github")
    tok = gw._mint_hosted_cred(hid, "sess2", _key(hid))
    out = _rpc(client, tok, "tools/call", {"name": "github.get_file_contents", "arguments": {"path": "bad.md"}})
    assert out["isError"] and out["content"][0]["text"] == "GitHub answered 422: Validation Failed"
    rows = _calls(hid)
    assert rows[0]["outcome"] == "error" and rows[0]["error"] == "GitHub answered 422: Validation Failed"
    assert len(posted) == 1
    # missing arguments never reach the vendor
    out = _rpc(client, tok, "tools/call", {"name": "github.get_issue", "arguments": {}})
    assert out["isError"] and out["content"][0]["text"] == "number is required"
    assert not [c for c in ven.calls if "/issues" in c.url.path]


def test_refusals_by_plug_state_are_not_metered(client, world, monkeypatch):
    reg, ven, posted = world
    hid = _harness(client)
    _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]})
    tok = gw._mint_hosted_cred(hid, "sess3", _key(hid))
    call = {"name": "github.get_file_contents", "arguments": {"path": "README.md"}}

    def refused(contains: str):
        out = _rpc(client, tok, "tools/call", call)
        assert out["isError"] and contains in out["content"][0]["text"], out
    refused("no GitHub plugin connected")                                       # nothing in the registry
    reg.records[(WS, "github")] = _record("github", status="needs_auth")
    refused("needs attention")
    reg.records[(WS, "github")] = _record("github", status="disabled")
    refused("turned off")
    reg.records[(WS, "github")] = _record("github", org="someone.else")        # the registry's answer is not this org's
    refused("no GitHub plugin connected")
    reg.fail = True
    refused("did not answer")
    reg.fail = False
    reg.records[(WS, "github")] = _record("github", refs=[{"field": "token", "ref": "harness-conn-openai"}])   # outside plug-
    refused("needs attention")
    reg.records[(WS, "github")] = _record("github", tenant="global")            # never the platform pool
    refused("needs attention")
    monkeypatch.setattr(gw, "_PLUGS_ORGS", set())
    reg.records[(WS, "github")] = _record("github")
    refused("not available on this account")
    assert ven.calls == [] and posted == []
    assert {r["outcome"] for r in _calls(hid)} == {"refused"}

    # a switched-off entry and a token for another harness's record answer the same way
    monkeypatch.setattr(gw, "_PLUGS_ORGS", {ORG})
    thief = _harness(client)
    _post(client, f"/v1/harnesses/{thief}/servers/plugs", {"plugs": ["github"]})
    stolen = gw._mint_hosted_cred(thief, "sessX", _key(hid))
    out = _rpc(client, stolen, "tools/call", call)
    assert out["isError"] and "No plugins are connected to this agent" in out["content"][0]["text"]
    assert _rpc(client, stolen, "tools/list") == {"tools": []}
    v = asyncio.run(gw._vertex_get(hid))
    asyncio.run(gw._mcp_write(hid, [{**e, "enabled": False} for e in gw._mcp_list(v)]))
    out = _rpc(client, tok, "tools/call", call)
    assert out["isError"] and "No plugins are connected to this agent" in out["content"][0]["text"]
    assert ven.calls == []


def test_the_credential_is_read_again_only_when_the_version_changes(client, world):
    reg, ven, _ = world
    hid = _harness(client)
    _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]})
    reg.records[(WS, "github")] = _record("github", version=3)
    tok = gw._mint_hosted_cred(hid, "sess4", _key(hid))
    call = {"name": "github.get_file_contents", "arguments": {"path": "README.md"}}
    reg.reads = 0                                                            # the attach read the status once
    assert _rpc(client, tok, "tools/call", call)["isError"] is False
    assert reg.reads == 1
    asyncio.run(gw._vault_put(TENANT, "plug-plugorg-hrws1-github-token", "ghs_ROTATED"))
    assert _rpc(client, tok, "tools/call", call)["isError"] is False          # same version: the cached token
    assert ven.calls[-1].headers["Authorization"] == f"Bearer {TOKEN}" and reg.reads == 2
    reg.records[(WS, "github")] = _record("github", version=4)
    out = _rpc(client, tok, "tools/call", call)                              # new version: the vault again
    assert ven.calls[-1].headers["Authorization"] == "Bearer ghs_ROTATED"
    assert out["isError"], "the mock vendor only knows the first token, so the rotated one is refused there"
    asyncio.run(gw._vault_put(TENANT, "plug-plugorg-hrws1-github-token", TOKEN))


def test_every_call_lands_in_the_sessions_trace(client, world, monkeypatch):
    reg, _, _ = world
    hid = _harness(client)
    _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]})
    reg.records[(WS, "github")] = _record("github")
    chunks = []

    async def _put(file_id, data):
        chunks.append((file_id, data))
        return True
    monkeypatch.setattr(gw, "_trace_put", _put)
    monkeypatch.setitem(gw._session_trace, "sess5", {"prefix": "traces/sess5", "count": 0})
    tok = gw._mint_hosted_cred(hid, "sess5", _key(hid))
    _rpc(client, tok, "tools/call", {"name": "github.get_file_contents", "arguments": {"path": "README.md"}})
    assert len(chunks) == 1 and chunks[0][0].startswith("traces/sess5/events/")
    ev = json.loads(chunks[0][1])
    assert ev["type"] == "plug" and ev["plug"] == "github" and ev["tool"] == "get_file_contents"
    assert ev["risk"] == "read" and ev["outcome"] == "ok" and "error" not in ev and isinstance(ev["ms"], int)
    assert gw._session_trace["sess5"]["count"] == 1


# ── packages that need plugs ─────────────────────────────────────────────────────────────────
def _package(requires):
    manifest = {"$schema": PLUGIN_SCHEMA, "name": "needs-plugs", "version": "1.0.0", "requires": requires}
    return {"files": [{"path": "plugin.json", "content": json.dumps(manifest)}]}


def test_a_package_that_requires_plugs_gets_them_on_install(client, world, monkeypatch):
    r = _post(client, "/v1/harnesses", {"name": "Packaged", "base": "claude-code",
                                        "plugins": [_package({"plugs": ["github", "nope"]})]})
    assert r.status_code == 200, r.text
    hid = r.json()["id"]
    assert r.json()["plugins"][0]["skipped"] == [{"path": "plugin.json#/requires/plugs/nope",
                                                  "reason": "no plug of that type on this server, ignored"}]
    assert [e["id"] for e in r.json()["mcpServers"]] == ["mcp.plugs"]
    assert _get(client, f"/v1/harnesses/{hid}/servers/mcp.plugs").json()["plugs"] == ["github"]
    # an update that keeps the package keeps the binding; one that adds a requirement widens it
    r = client.put(f"/v1/harnesses/{hid}", headers=HEADERS,
                   json={"name": "Packaged", "base": "claude-code", "mcpServers": r.json()["mcpServers"],
                         "plugins": [_package({"plugs": ["github", "vercel"]})]})
    assert r.status_code == 200, r.text
    assert _get(client, f"/v1/harnesses/{hid}/servers/mcp.plugs").json()["plugs"] == ["github", "vercel"]
    # a malformed requires is refused, not guessed at
    r = _post(client, "/v1/harnesses", {"name": "Bad", "base": "claude-code", "plugins": [_package({"plugs": "github"})]})
    assert r.status_code == 422 and "requires" in r.text
    # held: the package installs, the plugs wait for the org to be let in
    monkeypatch.setattr(gw, "_PLUGS_ORGS", set())
    r = _post(client, "/v1/harnesses", {"name": "Held", "base": "claude-code", "plugins": [_package({"plugs": ["github"]})]})
    assert r.status_code == 200 and r.json()["mcpServers"] == []


# ── the tool surface itself ──────────────────────────────────────────────────────────────────
def test_the_tool_table_is_well_formed():
    for plug in plugs_plane.TYPES:
        tools = plugs_plane.tools_of(plug)
        assert tools, plug
        names = [t["name"] for t in tools]
        assert len(names) == len(set(names)), plug
        for t in tools:
            assert t["risk"] in plugs_plane.RISKS and t["inputSchema"]["type"] == "object" and t["description"]
    assert plugs_plane.tools_of("github_app") == plugs_plane.tools_of("github")
    assert plugs_plane.find("github", "push_files")["risk"] == "destructive"
    assert plugs_plane.find("insforge", "delete_rows")["risk"] == "destructive"
    assert plugs_plane.find("vercel", "deploy_from_repo")["risk"] == "write"
    listed = plugs_plane.tool_list(["github"], {"github": ["get_repo"]})
    assert [t["name"] for t in listed] == ["github.get_repo"] and listed[0]["description"].startswith("[GitHub, read]")


def test_push_files_deploy_and_insert_drive_the_vendors_as_documented(world):
    _, ven, _ = world
    out = json.loads(asyncio.run(plugs_plane.call("github", "push_files",
                                                  {"branch": "main", "message": "m", "files": [{"path": "a.txt", "content": "A"}]},
                                                  {"token": TOKEN}, _record("github")["config"])))
    assert out == {"branch": "main", "commit": "commit1", "files": 1}
    assert [(c.method, c.url.path) for c in ven.calls] == [
        ("GET", "/repos/acme/site/git/ref/heads/main"), ("GET", "/repos/acme/site/git/commits/head1"),
        ("POST", "/repos/acme/site/git/trees"), ("POST", "/repos/acme/site/git/commits"),
        ("PATCH", "/repos/acme/site/git/refs/heads/main")]
    assert json.loads(ven.calls[2].content)["tree"] == [{"path": "a.txt", "mode": "100644", "type": "blob", "content": "A"}]
    out = json.loads(asyncio.run(plugs_plane.call("github", "create_pull_request", {"title": "T", "head": "feat"},
                                                  {"token": TOKEN}, _record("github")["config"])))
    assert out["number"] == 7 and out["base"] == "main"

    ven.calls.clear()
    out = json.loads(asyncio.run(plugs_plane.call("vercel", "deploy_from_repo", {"production": True},
                                                  {"token": VC_TOKEN}, _record("vercel")["config"])))
    assert out["id"] == "dpl_1" and out["readyState"] == "READY"
    assert json.loads(ven.calls[1].content)["target"] == "production"
    out = json.loads(asyncio.run(plugs_plane.call("vercel", "get_project", {}, {"token": VC_TOKEN}, _record("vercel")["config"])))
    assert out["domains"] == ["site.vercel.app"] and out["link"]["repo"] == "site"

    out = json.loads(asyncio.run(plugs_plane.call("insforge", "insert_rows", {"table": "orders", "rows": [{"status": "new"}]},
                                                  {"api_key": INF_KEY}, _record("insforge")["config"])))
    assert out == [{"status": "new"}]
    with pytest.raises(plugs_plane.PlugToolError):
        asyncio.run(plugs_plane.call("insforge", "delete_rows", {"table": "orders", "filters": {}}, {"api_key": INF_KEY},
                                     _record("insforge")["config"]))
    with pytest.raises(plugs_plane.PlugToolError):
        asyncio.run(plugs_plane.call("insforge", "request", {"method": "GET", "path": "/etc/passwd"}, {"api_key": INF_KEY},
                                     _record("insforge")["config"]))


def test_a_plug_over_several_repositories_takes_the_one_meant(world):
    _, ven, _ = world
    many = {"repos": ["acme/site", "acme/docs"], "default_branch": "main"}
    out = json.loads(asyncio.run(plugs_plane.call("github_app", "get_file_contents", {"path": "README.md", "repo": "acme/site"},
                                                  {"token": TOKEN}, many)))
    assert out["content"] == "hello" and ven.calls[-1].url.path == "/repos/acme/site/contents/README.md"
    with pytest.raises(plugs_plane.PlugToolError, match="covers several"):
        asyncio.run(plugs_plane.call("github_app", "get_file_contents", {"path": "README.md"}, {"token": TOKEN}, many))
    with pytest.raises(plugs_plane.PlugToolError, match="does not cover"):
        asyncio.run(plugs_plane.call("github_app", "get_file_contents", {"path": "README.md", "repo": "evil/repo"}, {"token": TOKEN}, many))
    with pytest.raises(plugs_plane.PlugToolError, match="does not cover"):
        asyncio.run(plugs_plane.call("github", "get_file_contents", {"path": "README.md", "repo": "evil/repo"}, {"token": TOKEN},
                                     _record("github")["config"]))
    assert "repo" in plugs_plane.find("github", "merge_pull_request")["inputSchema"]["properties"]
    assert plugs_plane.permission_of("github", "create_issue") == "issues" and plugs_plane.permission_of("vercel", "deploy_from_repo") is None


def test_a_missing_grant_is_named_before_the_vendor_is_asked(client, world):
    reg, ven, posted = world
    hid = _harness(client)
    _post(client, f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["github"]})
    rec = _record("github")
    rec["config"]["permissions_missing"] = ["issues", "actions"]
    reg.records[(WS, "github")] = rec
    tok = gw._mint_hosted_cred(hid, "sess6", _key(hid))
    out = _rpc(client, tok, "tools/call", {"name": "github.create_issue", "arguments": {"title": "x"}})
    assert out["isError"] and "not granted issues access" in out["content"][0]["text"]
    assert ven.calls == [] and posted == [] and _calls(hid)[0]["error"] == "no issues permission"
    out = _rpc(client, tok, "tools/call", {"name": "github.get_file_contents", "arguments": {"path": "README.md"}})
    assert out["isError"] is False                                            # contents was granted


def test_no_credential_ever_came_back_out():
    for s in (TOKEN, VC_TOKEN, INF_KEY):
        assert not [b for b in _seen if s in b], "a credential left the gateway"
