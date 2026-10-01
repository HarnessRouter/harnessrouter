"""Microsoft 365 on the self-hosted registry: the application is checked at Entra when the plug is
connected; a delegated plug waits for each person's sign-in with Microsoft (start -> Entra ->
complete keeps their refresh token under their own field and remembers who they are; sign-out
forgets both); the application identity is connected at once."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402
import plugs_plane  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ORG = "localorg"
WS = "default"
MEMBER = "ada@local"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": MEMBER, "x-harness-workspace": WS}
TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET = "m365~SENTINEL_never_returned"


class Entra:
    """Entra's token endpoint (client credentials, the authorization code, a refresh) and Graph's /me and /organization."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.grants: list[str] = []

    def handle(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        if r.url.host == "login.microsoftonline.com":
            form = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
            assert form["client_id"] == CLIENT and form["client_secret"] == SECRET
            self.grants.append(form["grant_type"])
            if form["grant_type"] == "authorization_code":
                assert form["code"] == "code-1" and form["redirect_uri"] == "https://console.example/plugins"
                assert "offline_access" in form["scope"]
                return httpx.Response(200, json={"access_token": "at-ada", "refresh_token": "rt-ada-secret", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "tok-app", "expires_in": 3600})
        assert r.url.host == "graph.microsoft.com"
        if r.url.path.endswith("/me"):
            assert r.headers["Authorization"] == "Bearer at-ada"
            return httpx.Response(200, json={"id": "u1", "displayName": "Ada Example", "userPrincipalName": "ada@contoso.com"})
        if r.url.path.endswith("/organization"):
            return httpx.Response(200, json={"value": [{"id": TENANT, "displayName": "Contoso"}]})
        return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": "not found"}})


@pytest.fixture(scope="module")
def client():
    with TestClient(gw.app) as c:
        yield c


@pytest.fixture
def entra(monkeypatch):
    e = Entra()
    monkeypatch.setattr(gw, "PLUGS_REGISTRY_URL", "")
    monkeypatch.setattr(plugs_plane, "transport", httpx.MockTransport(e.handle))
    plugs_plane._m365_tokens.clear()
    gw._plug_fields_cache.clear()
    return e


def _req(client, method, path, body=None, headers=None):
    return client.request(method, path, json=body, headers={**HEADERS, **(headers or {})})


def test_a_delegated_plug_is_checked_at_entra_then_waits_for_each_persons_sign_in(client, entra):
    r = _req(client, "PUT", "/v1/plugs/microsoft365", {"enabled": True, "config": {"tenant_id": TENANT, "client_id": CLIENT},
                                                        "secrets": {"client_secret": SECRET}})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "needs_auth" and "Sign in with Microsoft" in p["attention"]
    assert p["config"]["mode"] == "delegated" and p["config"]["accounts"] == {} and "secrets_set" in p and SECRET not in r.text
    assert entra.grants == ["client_credentials"]          # the ids and the secret were checked at Entra, nothing else

    r = _req(client, "POST", "/v1/plugs/microsoft365/microsoft/start", {"redirect_uri": "http://evil.example/plugins"})
    assert r.status_code == 400 and "https" in r.text          # the return address is the console's own
    r = _req(client, "POST", "/v1/plugs/microsoft365/microsoft/start", {"redirect_uri": "https://console.example/plugins"})
    assert r.status_code == 200, r.text
    url, state = r.json()["auth_url"], r.json()["state"]
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).path == f"/{TENANT}/oauth2/v2.0/authorize"
    assert q["client_id"] == [CLIENT] and q["response_type"] == ["code"] and q["prompt"] == ["select_account"]
    assert q["redirect_uri"] == ["https://console.example/plugins"] and q["state"] == [state]
    assert set(q["scope"][0].split()) == set(plugs_plane.M365_DELEGATED_SCOPES)

    # another person cannot finish this sign-in: the state names who started it
    r = _req(client, "POST", "/v1/plugs/microsoft/complete", {"code": "code-1", "state": state}, {"x-harness-member": "eve@local"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_state"

    r = _req(client, "POST", "/v1/plugs/microsoft/complete", {"code": "code-1", "state": state})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "connected" and "attention" not in p
    assert p["config"]["accounts"][MEMBER]["upn"] == "ada@contoso.com" and p["config"]["accounts"][MEMBER]["name"] == "Ada Example"
    assert plugs_plane.m365_person_field(MEMBER) in p["secrets_set"] and "rt-ada-secret" not in r.text
    assert entra.grants == ["client_credentials", "authorization_code"]

    # the plane is handed that person's token under their field, and nobody else's
    import asyncio
    _status, rec = asyncio.run(gw._plug_lookup_local(ORG, WS, "microsoft365"))
    fields = asyncio.run(gw._plug_fields(rec))
    assert fields[plugs_plane.m365_person_field(MEMBER)] == "rt-ada-secret" and fields["client_secret"] == SECRET

    r = _req(client, "POST", "/v1/plugs/microsoft365/microsoft/signout", {})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "needs_auth" and p["config"]["accounts"] == {} and p["secrets_set"] == ["client_secret"]   # no orphaned sign-in field


def test_the_application_identity_connects_at_once_and_does_not_sign_people_in(client, entra):
    r = _req(client, "PUT", "/v1/plugs/microsoft365", {"enabled": True, "config": {"tenant_id": TENANT, "client_id": CLIENT, "mode": "application"},
                                                        "secrets": {"client_secret": SECRET}})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "connected" and p["config"]["directory"] == "Contoso" and "attention" not in p
    assert entra.grants == ["client_credentials"] and any(c.url.path.endswith("/organization") for c in entra.calls)
    r = _req(client, "POST", "/v1/plugs/microsoft365/microsoft/start", {"redirect_uri": "https://console.example/plugins"})
    assert r.status_code == 400 and "does not sign people in" in r.text


def test_a_wrong_secret_is_refused_where_it_is_typed(client, entra, monkeypatch):
    def refuse(r: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided."})
    monkeypatch.setattr(plugs_plane, "transport", httpx.MockTransport(refuse))
    r = _req(client, "PUT", "/v1/plugs/microsoft365", {"enabled": True, "config": {"tenant_id": TENANT, "client_id": CLIENT},
                                                        "secrets": {"client_secret": "wrong"}})
    assert r.status_code == 400 and "AADSTS7000215" in r.text and r.json()["error"]["code"] == "invalid_credential"
