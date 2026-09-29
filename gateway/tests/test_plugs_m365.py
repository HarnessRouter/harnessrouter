"""The Microsoft 365 plug: the workspace's own Entra application on the sites and people it
approved. What is asserted is what the agent receives and what Microsoft is asked: the
application's sign-in, the resource lists refusing before Microsoft is asked, the eight read
tools on a mocked Graph, Microsoft's own refusal surfaced, and the audit row naming the resource.
The registry is the local one (a self-hosted instance); the credential is in the secret store.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402
import plugs_plane  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORG = "m365org"
WS = "default"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "m@m365", "x-harness-workspace": WS}
TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET = "m365~SENTINEL_never_returned_9z9z"
SITE = "contoso.sharepoint.com:/sites/Engineering"
ALICE = "alice@contoso.com"
_seen: list[str] = []


class Graph:
    """Entra's token endpoint and the Graph paths the tools use, with the requests kept."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.tokens = 0

    def handle(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        host, path = r.url.host, r.url.path
        if host == "login.microsoftonline.com":
            assert path == f"/{TENANT}/oauth2/v2.0/token"
            form = dict(x.split("=", 1) for x in r.content.decode().split("&"))
            assert form["client_id"] == CLIENT and form["client_secret"] == SECRET and form["grant_type"] == "client_credentials"
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"tok{self.tokens}", "expires_in": 3600})
        assert host == "graph.microsoft.com" and r.headers.get("Authorization", "").startswith("Bearer tok")
        p = path.removeprefix("/v1.0")
        if p == "/users" and r.url.params.get("$search"):
            assert r.headers.get("ConsistencyLevel") == "eventual"
            return httpx.Response(200, json={"value": [{"id": "u1", "displayName": "Alice Example", "userPrincipalName": ALICE, "mail": ALICE, "jobTitle": "CTO"}]})
        if p == f"/sites/{SITE}/drive/root/children":
            return httpx.Response(200, json={"value": [
                {"name": "notes.md", "id": "i1", "size": 12, "lastModifiedDateTime": "2026-09-29T00:00:00Z", "webUrl": "https://x/notes.md", "file": {"mimeType": "text/markdown"}},
                {"name": "Reports", "id": "i2", "folder": {"childCount": 3}, "webUrl": "https://x/Reports"}]})
        if p == f"/sites/{SITE}/drive/root:/notes.md":
            return httpx.Response(200, json={"name": "notes.md", "id": "i1", "size": 12, "webUrl": "https://x/notes.md", "file": {"mimeType": "text/markdown"}})
        if p == f"/sites/{SITE}/drive/root:/notes.md:/content":
            return httpx.Response(200, content=b"# Notes\nhello", headers={"content-type": "text/markdown"})
        if p == f"/sites/{SITE}/drive/root:/deck.pptx":
            return httpx.Response(200, json={"name": "deck.pptx", "id": "i3", "size": 99, "webUrl": "https://x/deck.pptx",
                                             "file": {"mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}})
        if p == f"/users/{ALICE}/drive/root/children":
            return httpx.Response(403, json={"error": {"code": "accessDenied", "message": "Tenant does not have a SPO license."}})
        if p == f"/users/{ALICE}/mailFolders/inbox/messages":
            return httpx.Response(200, json={"value": [{"id": "m1", "subject": "Q3 plan", "receivedDateTime": "2026-09-29T08:00:00Z", "isRead": False,
                                                        "from": {"emailAddress": {"name": "Bob", "address": "bob@contoso.com"}}, "bodyPreview": "Draft attached"}]})
        if p == f"/users/{ALICE}/messages/m1":
            assert r.headers.get("Prefer") == 'outlook.body-content-type="text"'
            return httpx.Response(200, json={"id": "m1", "subject": "Q3 plan", "from": {"emailAddress": {"name": "Bob", "address": "bob@contoso.com"}},
                                             "toRecipients": [{"emailAddress": {"name": "Alice", "address": ALICE}}], "body": {"contentType": "text", "content": "Here is the plan."}})
        if p == f"/users/{ALICE}/calendarView":
            assert r.url.params.get("startDateTime") == "2026-09-29T00:00:00Z"
            return httpx.Response(200, json={"value": [{"id": "e1", "subject": "Standup", "start": {"dateTime": "2026-09-29T09:00:00"}, "end": {"dateTime": "2026-09-29T09:15:00"},
                                                        "location": {"displayName": "Teams"}, "organizer": {"emailAddress": {"name": "Alice", "address": ALICE}}, "attendees": []}]})
        return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": f"no mock for {p}"}})


@pytest.fixture(scope="module")
def client():
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture
def world(monkeypatch):
    graph, posted = Graph(), []
    monkeypatch.setattr(gw, "PLUGS_REGISTRY_URL", "")
    monkeypatch.setattr(gw, "_PLUGS_ORGS", {"*"})
    monkeypatch.setattr(plugs_plane, "transport", httpx.MockTransport(graph.handle))
    monkeypatch.setattr(gw, "_report_usage", lambda org, metric, amount, **kw: posted.append((org, metric, amount)))
    plugs_plane._m365_tokens.clear()
    gw._plug_fields_cache.clear()
    gw._plug_trace_handles.clear()
    yield graph, posted


def _req(client, method, path, body=None):
    r = client.request(method, path, json=body, headers=HEADERS)
    _seen.append(r.text)
    return r


def _rpc(client, tok, method, params=None, rid=1):
    r = client.post("/v1/mcp/plugs", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    _seen.append(r.text)
    return r.json().get("result")


def _text(out) -> str:
    return out["content"][0]["text"]


def _calls(hid: str) -> list[dict]:
    return asyncio.run(gw.BACKING.graph.find("PlugCall", {"harness": hid}))


def _connect(client) -> dict:
    r = _req(client, "PUT", "/v1/plugs/microsoft365",
             {"enabled": True, "secrets": {"client_secret": SECRET},
              "config": {"tenant_id": TENANT, "client_id": CLIENT, "sites": [SITE, " contoso.sharepoint.com:/sites/Sales "], "users": f"{ALICE}, {ALICE}"}})
    assert r.status_code == 200, r.text
    return r.json()


def _bound_harness(client) -> tuple[str, str]:
    hid = _req(client, "POST", "/v1/harnesses", {"name": "Office", "base": "claude-code"}).json()["id"]
    r = _req(client, "POST", f"/v1/harnesses/{hid}/servers/plugs", {"plugs": ["microsoft365"]})
    assert r.status_code == 200, r.text
    return hid, gw._mint_hosted_cred(hid, "sess-m365", gw._hosted_secret_key(hid, "mcp.plugs"))


def test_the_plug_is_in_the_catalog_and_connects_with_its_lists(client, world):
    cat = {p["type"]: p for p in _req(client, "GET", "/v1/plugs").json()["plugs"]}
    p = cat["microsoft365"]
    assert p["label"] == "Microsoft 365" and p["status"] == "missing" and p["source"] == "local"
    assert p["secrets_needed"] == ["client_secret"] and p["config_fields"] == ["tenant_id", "client_id", "sites", "users"] and p["tools"] == 8
    got = _connect(client)
    assert got["status"] == "connected" and got["secrets_set"] == ["client_secret"]
    # the lists are trimmed and deduplicated; a comma-separated string is a list too
    assert got["config"]["sites"] == [SITE, "contoso.sharepoint.com:/sites/Sales"] and got["config"]["users"] == [ALICE]
    assert got["config"]["tenant_id"] == TENANT and got["config"]["client_id"] == CLIENT
    # a setting the plug does not have, and a list that is not one
    assert _req(client, "PUT", "/v1/plugs/microsoft365", {"config": {"scopes": "x"}}).status_code == 400
    assert _req(client, "PUT", "/v1/plugs/microsoft365", {"config": {"sites": [1, 2]}}).status_code == 400


def test_the_agent_reads_approved_resources_and_nothing_else(client, world):
    graph, posted = world
    _connect(client)
    hid, tok = _bound_harness(client)
    names = sorted(t["name"] for t in _rpc(client, tok, "tools/list")["tools"])
    assert names == sorted("microsoft365_" + n for n in ("resources", "find_people", "list_files", "search_files", "read_file", "list_mail", "read_mail", "list_events"))
    assert all(t["annotations"] == {"readOnlyHint": True, "destructiveHint": False} for t in _rpc(client, tok, "tools/list")["tools"])

    res = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_resources", "arguments": {}})))
    assert res["sites"] == [SITE, "contoso.sharepoint.com:/sites/Sales"] and res["people"] == [ALICE] and "application" in res["identity"]
    assert graph.calls == []                                     # what is approved is answered without asking Microsoft

    people = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_find_people", "arguments": {"query": "Alice"}})))
    assert people == [{"id": "u1", "displayName": "Alice Example", "userPrincipalName": ALICE, "mail": ALICE, "jobTitle": "CTO"}]
    assert graph.tokens == 1                                     # one sign-in as the application...

    files = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_list_files", "arguments": {"site": SITE}})))
    assert files["resource"] == f"site {SITE}" and [i["name"] for i in files["items"]] == ["notes.md", "Reports"]
    assert files["items"][1]["kind"] == "folder" and files["items"][1]["children"] == 3
    assert graph.tokens == 1                                     # ...kept for the next call

    note = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_read_file", "arguments": {"site": SITE, "path": "/notes.md"}})))
    assert note["content"] == "# Notes\nhello" and note["mimeType"] == "text/markdown"
    deck = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_read_file", "arguments": {"site": SITE, "path": "deck.pptx"}})))
    assert "content" not in deck and "Not a text file" in deck["note"] and deck["webUrl"] == "https://x/deck.pptx"

    mail = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_list_mail", "arguments": {"user": ALICE}})))
    assert mail["resource"] == f"mailbox of {ALICE}" and mail["messages"][0]["subject"] == "Q3 plan" and mail["messages"][0]["from"] == "Bob <bob@contoso.com>"
    msg = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_read_mail", "arguments": {"user": ALICE, "id": "m1"}})))
    assert msg["body"] == "Here is the plan." and msg["to"] == [f"Alice <{ALICE}>"]
    events = json.loads(_text(_rpc(client, tok, "tools/call", {"name": "microsoft365_list_events",
                                                                "arguments": {"user": ALICE, "start": "2026-09-29T00:00:00Z", "end": "2026-09-30T00:00:00Z"}})))
    assert events["events"][0]["subject"] == "Standup" and events["events"][0]["location"] == "Teams"

    # a person and a site outside the lists are refused before Microsoft is asked
    before = len(graph.calls)
    out = _rpc(client, tok, "tools/call", {"name": "microsoft365_list_mail", "arguments": {"user": "mallory@contoso.com"}})
    assert out["isError"] and "not a person this plug was approved for" in _text(out) and ALICE in _text(out)
    out = _rpc(client, tok, "tools/call", {"name": "microsoft365_list_files", "arguments": {"site": "evil.sharepoint.com:/sites/HR"}})
    assert out["isError"] and "not a site this plug was approved for" in _text(out)
    out = _rpc(client, tok, "tools/call", {"name": "microsoft365_read_file", "arguments": {"site": SITE, "path": "../secrets"}})
    assert out["isError"] and ".." in _text(out)
    assert len(graph.calls) == before

    # Microsoft's own refusal is the agent's tool error, in Microsoft's words
    out = _rpc(client, tok, "tools/call", {"name": "microsoft365_list_files", "arguments": {"user": ALICE}})
    assert out["isError"] and "Microsoft Graph answered 403: Tenant does not have a SPO license." in _text(out)

    # every call is an audit row naming the resource it addressed; refusals are rows too
    rows = _calls(hid)
    by_tool = {}
    for row in rows:
        by_tool.setdefault(row["tool"], []).append(row)
    assert all(row["plug"] == "microsoft365" and row["risk"] == "read" and row["session"] == "sess-m365" for row in rows)
    ok_files = [r for r in by_tool["list_files"] if r["outcome"] == "ok"]
    assert ok_files and json.loads(ok_files[0]["detail"])["site"] == SITE
    refused_mail = [r for r in by_tool["list_mail"] if r["outcome"] == "error"]
    assert refused_mail and json.loads(refused_mail[0]["detail"])["user"] == "mallory@contoso.com"
    assert [r for r in by_tool["list_files"] if r["outcome"] == "error" and json.loads(r["detail"]).get("user") == ALICE]   # Microsoft's refusal, on the person
    assert posted and all(m == "plug.call" for _, m, _ in posted)


def test_the_applications_sign_in_failure_is_said_in_entras_words(client, world, monkeypatch):
    _connect(client)
    hid, tok = _bound_harness(client)

    def refuse(r: httpx.Request) -> httpx.Response:
        if r.url.host == "login.microsoftonline.com":
            return httpx.Response(401, json={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided.\nTrace ID: x"})
        return httpx.Response(500, text="never asked")
    monkeypatch.setattr(plugs_plane, "transport", httpx.MockTransport(refuse))
    plugs_plane._m365_tokens.clear()
    out = _rpc(client, tok, "tools/call", {"name": "microsoft365_find_people", "arguments": {"query": "a"}})
    assert out["isError"] and "Microsoft Entra refused the application's sign-in (401): AADSTS7000215: Invalid client secret provided." in _text(out)


def test_the_agents_instructions_name_the_tools_and_the_rule(client, world):
    doc = gw._agent_doc_with_plugs("Be brief.", ["microsoft365"])
    assert doc.startswith("Be brief.") and "## Microsoft 365" in doc and "microsoft365_resources" in doc and "read it first" in doc
    assert "report it" in doc and "write nothing" in doc
    assert "## Microsoft 365" not in gw._agent_doc_with_plugs("Be brief.", ["browser"])


def test_no_secret_ever_reached_a_caller():
    assert not any(SECRET in t for t in _seen)
