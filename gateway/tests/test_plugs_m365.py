"""The Microsoft 365 plane: the organization's own Entra application, run as the signed-in person
(their refresh token, redeemed for an access token; calls with no site or person are their own)
or as the application (client credentials; it must name the site or person). No list of sites or
people: Microsoft's own permissions are the boundary, and its refusal is surfaced as it is."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plugs_plane  # noqa: E402

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET = "m365~SENTINEL_never_returned"
SITE = "contoso.sharepoint.com:/sites/Engineering"


class Graph:
    """Entra's token endpoint (both grants) and the Graph paths the tools use, with requests kept."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.grants: list[str] = []

    def handle(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        host, path = r.url.host, r.url.path
        if host == "login.microsoftonline.com":
            form = dict(x.split("=", 1) for x in r.content.decode().split("&"))
            assert form["client_id"] == CLIENT and form["client_secret"] == SECRET
            self.grants.append(form["grant_type"])
            if form["grant_type"] == "refresh_token":
                if form["refresh_token"] == "rt-revoked":
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "AADSTS50173: The provided grant has expired due to it being revoked."})
                return httpx.Response(200, json={"access_token": f"tok-{form['refresh_token']}", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "tok-app", "expires_in": 3600})
        assert host == "graph.microsoft.com"
        auth = r.headers.get("Authorization", "")
        p = path.removeprefix("/v1.0")
        if p == "/me":
            assert auth == "Bearer tok-rt-ada"
            return httpx.Response(200, json={"displayName": "Ada Example", "userPrincipalName": "ada@contoso.com", "jobTitle": "CTO"})
        if p == "/me/drive/root/children":
            assert auth == "Bearer tok-rt-ada"
            return httpx.Response(200, json={"value": [{"name": "notes.md", "id": "i1", "size": 12, "webUrl": "https://x/notes.md", "file": {"mimeType": "text/markdown"}}]})
        if p == "/sites":
            return httpx.Response(200, json={"value": [{"id": "s1", "name": "Engineering", "displayName": "Engineering", "webUrl": "https://contoso.sharepoint.com/sites/Engineering"}]})
        if p == f"/sites/{SITE}/drive/root/children":
            return httpx.Response(200, json={"value": [{"name": "Reports", "id": "i2", "folder": {"childCount": 3}, "webUrl": "https://x/Reports"}]})
        if p == "/users/bob@contoso.com/drive/root/children":
            return httpx.Response(403, json={"error": {"code": "accessDenied", "message": "Access denied"}})
        if p == "/me/mailFolders/inbox/messages":
            return httpx.Response(200, json={"value": [{"id": "m1", "subject": "Hello", "receivedDateTime": "2026-09-30T00:00:00Z", "from": {"emailAddress": {"name": "Bob", "address": "bob@contoso.com"}}, "bodyPreview": "hi"}]})
        if p == "/users/bob@contoso.com/mailFolders/inbox/messages":
            assert auth == "Bearer tok-app"
            return httpx.Response(200, json={"value": []})
        return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": "not found"}})


@pytest.fixture
def graph(monkeypatch):
    g = Graph()
    monkeypatch.setattr(plugs_plane, "transport", httpx.MockTransport(g.handle))
    plugs_plane._m365_tokens.clear()
    return g


ADA = {"client_secret": SECRET, plugs_plane.m365_person_field("member.ada"): "rt-ada"}
DELEGATED = {"tenant_id": TENANT, "client_id": CLIENT, "mode": "delegated", "member": "member.ada"}
APP = {"tenant_id": TENANT, "client_id": CLIENT, "mode": "application"}


def _call(name, args, fields, config):
    return asyncio.run(plugs_plane.call("microsoft365", name, args, fields, config))


def test_a_signed_in_person_runs_as_themselves(graph):
    out = _call("resources", {}, ADA, DELEGATED)
    assert "signed in as ada@contoso.com" in out and "Ada Example" in out
    out = _call("list_files", {}, ADA, DELEGATED)                       # no site, no user: their own OneDrive
    assert "OneDrive of you" in out and "notes.md" in out
    out = _call("list_mail", {}, ADA, DELEGATED)
    assert "mailbox of you" in out and "Hello" in out
    assert graph.grants == ["refresh_token"]                              # one redemption, then the cached token
    assert all("SENTINEL" not in (r.headers.get("Authorization") or "") for r in graph.calls if r.url.host == "graph.microsoft.com")


def test_a_person_who_never_signed_in_or_whose_sign_in_was_revoked_is_told_so(graph):
    with pytest.raises(plugs_plane.PlugToolError, match="has not signed in with Microsoft"):
        _call("list_files", {}, {"client_secret": SECRET}, {**DELEGATED, "member": "member.bob"})
    with pytest.raises(plugs_plane.PlugToolError, match="did not accept the person's sign-in"):
        _call("list_files", {}, {"client_secret": SECRET, plugs_plane.m365_person_field("member.eve"): "rt-revoked"}, {**DELEGATED, "member": "member.eve"})
    assert not [r for r in graph.calls if r.url.host == "graph.microsoft.com"]


def test_sites_are_addressed_as_microsoft_answers_them_and_a_refusal_is_microsofts(graph):
    out = _call("list_sites", {"query": "Eng"}, ADA, DELEGATED)
    assert f'"site": "{SITE}"' in out
    out = _call("list_files", {"site": SITE}, ADA, DELEGATED)
    assert f"site {SITE}" in out and "Reports" in out
    with pytest.raises(plugs_plane.PlugToolError, match="Microsoft Graph answered 403: Access denied"):
        _call("list_files", {"user": "bob@contoso.com"}, ADA, DELEGATED)   # another person's OneDrive: SharePoint decides, no list here
    with pytest.raises(plugs_plane.PlugToolError, match="hostname:/sites/name"):
        _call("list_files", {"site": "not a site"}, ADA, DELEGATED)


def test_the_application_identity_must_name_the_person(graph):
    with pytest.raises(plugs_plane.PlugToolError, match="has no self"):
        _call("list_mail", {}, {"client_secret": SECRET}, APP)
    out = _call("list_mail", {"user": "bob@contoso.com"}, {"client_secret": SECRET}, APP)
    assert "mailbox of bob@contoso.com" in out and graph.grants == ["client_credentials"]
    out = _call("resources", {}, {"client_secret": SECRET}, APP)
    assert "the application" in out


def test_tool_names_and_the_type_are_served():
    names = [t["name"] for t in plugs_plane.tools_of("microsoft365")]
    assert names == ["resources", "find_people", "list_sites", "list_files", "search_files", "read_file", "list_mail", "read_mail", "list_events"]
    assert plugs_plane.TYPES["microsoft365"] == "Microsoft 365"
    assert all(t["risk"] == "read" for t in plugs_plane.tools_of("microsoft365"))
    f = plugs_plane.m365_person_field("Member.Ada@Acme")
    assert len(f) == 19 and f.startswith("rt-") and f == plugs_plane.m365_person_field(" member.ada@acme ")
