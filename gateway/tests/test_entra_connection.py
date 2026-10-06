"""An Azure connection that signs in with Microsoft Entra instead of an API key.

An organization that issues no API keys reaches Azure OpenAI and Foundry as an application in its own
directory (tenant id, client id, client secret). The broker asks Entra for a token by the
client-credentials grant, keeps it until shortly before it expires, and presents it as the bearer.
Built and first tested on the hosted service; the last three tests are this tree's own, where such a
connection is brokered in owner trust too.
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

TENANT, CLIENT = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CONN = {"provider": "azure", "auth": "entra", "tenant_id": TENANT, "client_id": CLIENT,
        "client_secret": "s3cret-value", "base_url": "https://res.openai.azure.com"}


class _Resp:
    def __init__(self, status, doc):
        self.status_code, self._doc, self.content = status, doc, b"x"

    def json(self):
        return self._doc


class _Entra:
    """Stands in for Entra's token endpoint; records what it was asked."""
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    async def post(self, url, data=None, timeout=None):
        self.calls.append((url, dict(data or {})))
        return self.answers.pop(0)


@pytest.fixture(autouse=True)
def _fresh():
    gw._entra_tokens.clear()
    gw._entra_locks.clear()
    yield


def test_the_token_is_asked_for_once_and_kept_until_shortly_before_it_expires(monkeypatch):
    entra = _Entra([_Resp(200, {"access_token": "tok-1", "expires_in": 3600}),
                    _Resp(200, {"access_token": "tok-2", "expires_in": 3600})])
    monkeypatch.setattr(gw, "_client", lambda: entra)
    now = [1000.0]
    monkeypatch.setattr(gw.time, "time", lambda: now[0])

    async def run():
        a = await gw._entra_token(CONN)
        b = await gw._entra_token(dict(CONN))
        now[0] += 3600 - gw._ENTRA_EARLY_S + 1          # inside the last minutes of the token's life
        c = await gw._entra_token(CONN)
        return a, b, c
    assert asyncio.run(run()) == ("tok-1", "tok-1", "tok-2")
    url, form = entra.calls[0]
    assert url == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token" and len(entra.calls) == 2
    assert form == {"grant_type": "client_credentials", "client_id": CLIENT, "client_secret": "s3cret-value",
                    "scope": "https://cognitiveservices.azure.com/.default"}


def test_a_sign_in_leaves_one_log_line_with_the_applications_id_and_nothing_secret(monkeypatch, capsys):
    monkeypatch.setattr(gw, "_client", lambda: _Entra([_Resp(200, {"access_token": "tok-LOGGED", "expires_in": 3599})]))
    for _ in range(3):
        asyncio.run(gw._entra_token(CONN))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[entra]")]
    assert lines == [f"[entra] signed in as application ••••{CLIENT[-4:]}; asking again in 3299 s"]
    assert "tok-LOGGED" not in lines[0] and CONN["client_secret"] not in lines[0]


def test_two_calls_at_once_ask_entra_once(monkeypatch):
    entra = _Entra([_Resp(200, {"access_token": "tok-1", "expires_in": 3600})])
    monkeypatch.setattr(gw, "_client", lambda: entra)

    async def run():
        return await asyncio.gather(gw._entra_token(CONN), gw._entra_token(CONN), gw._entra_token(CONN))
    assert asyncio.run(run()) == ["tok-1"] * 3 and len(entra.calls) == 1


def test_a_refused_sign_in_says_what_entra_said_and_never_the_secret(monkeypatch):
    entra = _Entra([_Resp(401, {"error": "invalid_client",
                                "error_description": "AADSTS7000215: Invalid client secret provided. Ensure the secret is the value.\r\nTrace ID: abc"})])
    monkeypatch.setattr(gw, "_client", lambda: entra)
    with pytest.raises(HTTPException) as e:
        asyncio.run(gw._entra_token(CONN))
    # 401, as a provider refusing an API key answers: the agent stops and the turn says so
    assert e.value.status_code == 401 and "AADSTS7000215" in e.value.detail
    assert e.value.detail.startswith("Microsoft Entra refused this connection's sign-in: ")
    assert "Trace ID" not in e.value.detail and "s3cret-value" not in e.value.detail
    assert not gw._entra_tokens                       # a refusal is not remembered: the next call asks again
    # an unknown directory's description carries its trace id on the same line (seen 2026-10-06)
    monkeypatch.setattr(gw, "_client", lambda: _Entra([_Resp(400, {"error": "invalid_request", "error_description":
        "AADSTS90002: Tenant 'x' not found. Check with your subscription administrator. Trace ID: 62635bf8 Correlation ID: 9a"})]))
    with pytest.raises(HTTPException) as e:
        asyncio.run(gw._entra_token(CONN))
    assert e.value.status_code == 401
    assert e.value.detail == "Microsoft Entra refused this connection's sign-in: AADSTS90002: Tenant 'x' not found. Check with your subscription administrator."


def test_entra_failing_is_not_a_refusal_of_the_connection(monkeypatch):
    for status, doc in ((429, {"error": "temporarily_unavailable", "error_description": "AADSTS90055: Too many requests."}),
                        (503, {}), (200, {"token_type": "Bearer"})):
        gw._entra_tokens.clear()
        monkeypatch.setattr(gw, "_client", lambda status=status, doc=doc: _Entra([_Resp(status, doc)]))
        with pytest.raises(HTTPException) as e:
            asyncio.run(gw._entra_token(CONN))
        assert e.value.status_code == 502 and e.value.detail.startswith("Microsoft Entra did not sign this connection in: "), status
        assert not gw._provider_refused(f"hr API error (502): {e.value.detail}"), status


def test_a_turn_refused_on_an_entra_connection_does_not_speak_of_a_key():
    entra = "hr API error (401): Microsoft Entra refused this connection's sign-in: AADSTS7000215: Invalid client secret provided."
    role = 'hr API error (401): {"code":"PermissionDenied","message":"The principal lacks the required data action"}'
    for err in (entra, role):
        assert gw._provider_refused(err)             # so the turn stops here and does not try another connection
        said = gw._refusal_message({"provider": "azure", "auth": "entra"}, err)
        assert said == f"Your azure connection was refused: {err}" and " key " not in said
    assert gw._refusal_message({"provider": "azure"}, role) == f"Your azure key was refused: {role}"
    assert gw._refusal_message({"provider": "openai"}, "") == "Your openai key was refused: the provider returned an error"


def test_another_secret_or_scope_is_another_token(monkeypatch):
    entra = _Entra([_Resp(200, {"access_token": "tok-1", "expires_in": 3600}),
                    _Resp(200, {"access_token": "tok-2", "expires_in": 3600}),
                    _Resp(200, {"access_token": "tok-3", "expires_in": 3600})])
    monkeypatch.setattr(gw, "_client", lambda: entra)

    async def run():
        return (await gw._entra_token(CONN), await gw._entra_token({**CONN, "client_secret": "rotated"}),
                await gw._entra_token({**CONN, "entra_scope": "https://ai.azure.com/.default"}))
    assert asyncio.run(run()) == ("tok-1", "tok-2", "tok-3")
    assert entra.calls[2][1]["scope"] == "https://ai.azure.com/.default"


def test_what_can_be_saved_as_an_entra_connection():
    ok = {k: v for k, v in CONN.items() if k != "provider"}
    assert gw._entra_config_error("azure", ok) == "" == gw._entra_config_error("azure-foundry", ok)
    assert "Azure" in gw._entra_config_error("openai", ok)
    assert gw._entra_config_error("azure", {**ok, "client_secret": ""}) == "missing the Client secret"
    assert gw._entra_config_error("azure", {**ok, "client_secret": "", "tenant_id": ""}) == \
        "missing the Directory (tenant) ID, the Client secret"
    why = gw._entra_config_error("azure", {**ok, "tenant_id": "contoso.onmicrosoft.com"})
    assert why.startswith("the Directory (tenant) ID is written as a GUID") and "tenant_id" not in why
    assert "Endpoint URL" in gw._entra_config_error("azure", {**ok, "base_url": ""})
    assert gw._entra_conn(CONN) and not gw._entra_conn({"provider": "azure", "api_key": "k"}) and not gw._entra_conn(None)


def test_the_secret_is_one_of_the_fields_the_console_never_gets_back_and_a_sandbox_never_sees():
    assert "client_secret" in gw._INTEGRATION_SECRET_FIELDS
    shown = gw._integration_public({"name": "Azure", "provider": "azure-foundry", "config": dict(CONN)})
    assert shown["config"]["client_secret"] == gw._SECRET_SENTINEL and shown["config"]["tenant_id"] == TENANT
    for f in ("client_secret", "tenant_id", "client_id", "auth"):
        assert f not in gw._AUTH_FIELDS


def test_in_owner_trust_an_entra_connection_is_still_brokered(monkeypatch):
    """Owner trust hands a connection's key to the agent. An Entra connection has no key to hand: it
    has a secret that buys a token good for about an hour, and a turn may run for six. The broker
    asks again as the token ages, and the agent holds neither."""
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test")
    monkeypatch.setenv("HARNESS_GATEWAY_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    entra = {"name": "integration:Azure Entra", "backend": "codex", **CONN}
    auth = gw._auth_from_conn(entra, "hsess1")
    assert auth and auth["base_url"] == "http://127.0.0.1:8080/v1/llm"
    assert gw._verify_turn_cred(auth["api_key"]) == ("hsess1", "integration:Azure Entra")
    assert "s3cret-value" not in str(auth) and "client_secret" not in auth and "tenant_id" not in auth
    # a connection with a key is handed over in owner trust, as it always was
    keyed = gw._auth_from_conn({"name": "integration:Azure", "backend": "codex", "provider": "azure",
                                "api_key": "az-key", "base_url": "https://res.openai.azure.com"}, "hsess1")
    assert keyed["api_key"] == "az-key" and keyed["base_url"] == "https://res.openai.azure.com/openai/v1"


def test_the_broker_presents_the_token_as_the_bearer_and_a_key_as_the_api_key_header():
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()
    i = src.index("async def llm_broker(")
    body = src[i:src.index("body = _strip_unsupported(", i)]
    assert 'if _entra_conn(conn):\n            headers["authorization"] = f"Bearer {await _entra_token(conn)}"' in body
    assert 'else:\n            headers["api-key"] = key' in body


def _save(monkeypatch, integrations, stored=()):
    """PUT /v1/admin/integrations with its storage stood in for; → what was written."""
    written = {}

    async def allow(request):
        return None

    async def doc():
        return list(stored)

    async def vget(tenant, key):
        return None

    async def vput(tenant, key, value):
        written[key] = value
        return True
    monkeypatch.setattr(gw, "_require_integrations_admin", allow)
    monkeypatch.setattr(gw, "_integrations_doc", doc)
    monkeypatch.setattr(gw, "_vault_get", vget)
    monkeypatch.setattr(gw, "_vault_put", vput)
    asyncio.run(gw.admin_integrations_put(gw.IntegrationsBody(integrations=list(integrations)), None))
    import json
    return {i["name"]: i for i in json.loads(written[gw._INTEGRATIONS_KEY])}


def test_saving_takes_a_key_or_entra_and_never_both(monkeypatch):
    entra_cfg = {"auth": "entra", "tenant_id": f" {TENANT} ", "client_id": CLIENT, "client_secret": "s3cret-value",
                 "base_url": "https://res.openai.azure.com", "api_key": "left-over-key"}
    out = _save(monkeypatch, [{"name": "Azure Entra", "provider": "azure-foundry", "config": entra_cfg},
                              {"name": "Azure Key", "provider": "azure-foundry",
                               "config": {"auth": "key", "api_key": "az-key", "base_url": "https://res.openai.azure.com"}}])
    cfg = out["Azure Entra"]["config"]
    assert cfg["auth"] == "entra" and cfg["tenant_id"] == TENANT and cfg["client_secret"] == "s3cret-value"
    assert "api_key" not in cfg                                # one way in per connection
    assert "auth" not in out["Azure Key"]["config"] and out["Azure Key"]["config"]["api_key"] == "az-key"
    # an unchanged edit sends the sentinel back and the stored secret is carried through
    again = _save(monkeypatch, [{"name": "Azure Entra", "provider": "azure-foundry",
                                 "config": {**cfg, "client_secret": gw._SECRET_SENTINEL}}],
                  stored=[out["Azure Entra"]])
    assert again["Azure Entra"]["config"]["client_secret"] == "s3cret-value"
    for bad, why in (({**entra_cfg, "client_secret": ""}, "missing the Client secret"),
                     ({**entra_cfg, "tenant_id": "contoso.onmicrosoft.com"}, "GUID"),
                     ({**entra_cfg, "auth": "certificate"}, 'auth is "key" or "entra"')):
        with pytest.raises(HTTPException) as e:
            _save(monkeypatch, [{"name": "Azure Entra", "provider": "azure-foundry", "config": bad}])
        assert e.value.status_code == 400 and why in e.value.detail, e.value.detail
    with pytest.raises(HTTPException) as e:                    # Entra is for the two Azure kinds
        _save(monkeypatch, [{"name": "TR", "provider": "tokenrouter", "config": {**entra_cfg}}])
    assert "Azure OpenAI and Azure AI Foundry" in e.value.detail


def test_a_connection_switched_back_to_a_key_keeps_nothing_of_the_application(monkeypatch):
    out = _save(monkeypatch, [{"name": "Azure", "provider": "azure-foundry",
                               "config": {"auth": "", "api_key": "az-key", "base_url": "https://res.openai.azure.com",
                                          "tenant_id": TENANT, "client_id": CLIENT, "client_secret": "s3cret-value"}}])
    assert out["Azure"]["config"] == {"api_key": "az-key", "base_url": "https://res.openai.azure.com"}


def test_the_form_is_told_which_provider_offers_entra_and_what_to_ask():
    by_id = {p["id"]: p for p in gw._provider_catalog_public()}
    entra = by_id["azure-foundry"]["entra"]
    assert [f["key"] for f in entra["fields"]] == ["tenant_id", "client_id"] and entra["secret"] == "client_secret"
    assert entra["secret"] in gw._INTEGRATION_SECRET_FIELDS
    assert all("entra" not in p for pid, p in by_id.items() if pid != "azure-foundry")
    # the words a refusal uses are the form's own labels
    labels = {f["key"]: f["label"] for f in entra["fields"]} | {entra["secret"]: entra["secret_label"]}
    assert labels == gw._ENTRA_LABELS
