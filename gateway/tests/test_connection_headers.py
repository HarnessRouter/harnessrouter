"""Request headers on a connection, sent by the broker.

A gateway in front of a provider often wants a header beside the key (Cloudflare AI Gateway's
cf-aig-authorization, Helicone-Auth, OpenRouter's X-Title, an internal gateway's X-Project). A
connection carries them as `headers`; the broker adds them upstream after the credential. A value is
held like the key: never in the sandbox (owner trust brokers such a connection too), masked on read,
carried through an unchanged save, and typed again when the address changes.
"""
import asyncio
import http.server
import json
import sys
import threading
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

S = gw._SECRET_SENTINEL


# ── what can be saved ──────────────────────────────────────────────────────────────────────────

def test_ordinary_gateway_headers_are_accepted():
    assert gw._conn_headers_error("custom", {"cf-aig-authorization": "Bearer cf-tok", "X-Title": "My app",
                                             "HTTP-Referer": "https://example.com", "x-portkey-config": "pc-1"}) == ""
    assert gw._conn_headers_error("openrouter", None) == ""
    assert gw._conn_headers_error("openrouter", {}) == ""


@pytest.mark.parametrize("name", ["Authorization", "x-api-key", "API-Key", "x-goog-api-key", "Host",
                                  "content-length", "Transfer-Encoding", "Connection", "Content-Type",
                                  "traceparent", "TraceState", "Cookie", "x-harness-internal", "X-HR-Session",
                                  "proxy-authorization", "x-forwarded-for"])
def test_a_header_the_gateway_sets_cannot_be_set_on_a_connection(name):
    why = gw._conn_headers_error("custom", {name: "v"})
    assert "set by the gateway" in why, why


# By name and by prefix, in any case, at write and again at send: our credential's names, a client's or a
# hop's, request smuggling's, our own internal ones, AWS signing, and Cloudflare's own markers.
DENIED = ["X-Amz-Date", "x-amz-security-token", "X-AMZ-Content-Sha256", "CF-Connecting-IP", "cf-ray", "Cf-Worker",
          "CF-Access-Jwt-Assertion", "Via", "VIA", "Proxy-Foo", "PROXY-AUTHORIZATION", "X-Forwarded-Server",
          "x-forwarded-prefix", "X-Internal-Key", "x-internal-anything", "X-Harness-Org", "x-hr-anything",
          "Authorization", "API-KEY", "X-Api-Key", "X-Goog-Api-Key", "Cookie", "Host", "Content-Length",
          "Transfer-Encoding", "Upgrade", "TE"]


@pytest.mark.parametrize("name", DENIED)
def test_a_denied_name_in_any_case_is_refused_at_write_and_not_sent(name, capsys):
    assert "set by the gateway" in gw._conn_headers_error("custom", {name: "v"})
    assert gw._conn_headers({"name": "c", "headers": {name: "v", "X-Ok": "fine"}}) == {"X-Ok": "fine"}
    assert f"{name!r} not sent" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["cf-aig-authorization", "CF-AIG-Metadata", "CF-Access-Client-Id",
                                  "cf-access-client-secret", "Ocp-Apim-Subscription-Key", "Helicone-Auth",
                                  "x-portkey-api-key", "X-Project"])
def test_a_customers_own_credential_for_their_own_address_is_allowed(name):
    assert gw._conn_headers_error("custom", {name: "v"}) == ""
    assert gw._conn_headers({"headers": {name: "v"}}) == {name: "v"}


@pytest.mark.parametrize("headers,why", [
    ({"X-Project": "a\r\nAuthorization: Bearer stolen"}, "line break"),
    ({"X-Project": "a\nb"}, "line break"),
    ({"X-Project": "a\x00b"}, "control character"),
    ({"X-Project": "   "}, "has no value"),
    ({"X Project": "a"}, "not a header name"),
    ({"X-Project:": "a"}, "not a header name"),
    ({"": "a"}, "not a header name"),
    ({"X-Project": 7}, "is text"),
    ({"X-Project": "a", "x-project": "b"}, "given twice"),
    (["X-Project", "a"], "an object of header names"),
])
def test_what_is_refused_and_why(headers, why):
    got = gw._conn_headers_error("custom", headers)
    assert why in got, got


def test_limits_on_count_and_size():
    assert "at most 20" in gw._conn_headers_error("custom", {f"X-H{i}": "v" for i in range(21)})
    assert gw._conn_headers_error("custom", {f"X-H{i}": "v" for i in range(20)}) == ""
    assert "8192 bytes" in gw._conn_headers_error("custom", {"X-Big": "v" * 8200})


def test_a_tab_inside_a_value_is_allowed():
    assert gw._conn_headers_error("custom", {"X-Tags": "a\tb"}) == ""


@pytest.mark.parametrize("provider", ["bedrock", "Bedrock", "vertex", "qoder", "elevenlabs"])
def test_providers_the_broker_does_not_carry_refuse_headers(provider):
    assert "not available" in gw._conn_headers_error(provider, {"X-Project": "p"})


def test_the_sentinel_stands_for_a_saved_value_only_where_one_can_be_carried():
    assert gw._conn_headers_error("custom", {"X-Project": S}) == ""
    assert "has no value" in gw._conn_headers_error("custom", {"X-Project": S}, carried_ok=False)


# ── what is sent ───────────────────────────────────────────────────────────────────────────────

def test_the_connections_header_replaces_the_clients_of_the_same_name_in_any_case():
    out = gw._with_conn_headers({"x-title": "from the CLI", "accept": "*/*", "authorization": "Bearer k"},
                                {"headers": {"X-Title": "From the connection"}})
    assert out == {"accept": "*/*", "authorization": "Bearer k", "X-Title": "From the connection"}


def test_a_stored_header_that_would_never_have_been_saved_is_not_sent(capsys):
    """An environment connector or an older store is not checked at write; the broker checks again."""
    conn = {"name": "env-conn", "headers": {"Authorization": "Bearer other", "X-Ok": " fine ", "X-Bad": "a\r\nb",
                                            "X-Unsaved": S, "x-harness-internal": "k"}}
    assert gw._conn_headers(conn) == {"X-Ok": "fine"}
    log = capsys.readouterr().out
    assert "'Authorization' not sent" in log and "a\r\nb" not in log and "Bearer other" not in log
    assert gw._conn_headers({"headers": "X-Project: p"}) == {}
    assert gw._conn_headers(None) == {}


def test_the_setup_builder_sends_them_after_the_key():
    w = gw._setup_build_wire("custom", {"api_key": "k", "base_url": "https://gw.example/v1", "api_format": "openai",
                                        "headers": {"X-Project": "p1", "Authorization": "Bearer nope"}}, "m", "m")
    assert w["headers"] == {"authorization": "Bearer k", "X-Project": "p1"}
    w = gw._setup_build_wire("azure", {"api_key": "az", "base_url": "https://r.openai.azure.com",
                                       "headers": {"X-Project": "p1"}}, "m", "m")
    assert w["headers"] == {"api-key": "az", "X-Project": "p1"}


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        _Upstream.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                               "body": body})
        out = json.dumps({"id": "c1", "object": "chat.completion", "model": "m",
                          "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                       "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def upstream():
    _Upstream.seen = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def _broker_call(monkeypatch, conn, client_headers=None):
    """One chat call through /v1/llm on a turn credential for `conn`; → (status, what upstream saw)."""
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")

    async def resolve(name, org):
        return gw._with_provider_base(dict(conn))

    async def vertex_get(sid):
        return {}
    monkeypatch.setattr(gw, "_broker_resolve", resolve)
    monkeypatch.setattr(gw, "_vertex_get", vertex_get)
    monkeypatch.setattr(gw, "_relay_client", lambda: httpx.AsyncClient(timeout=10.0))
    cred = gw._mint_turn_cred("hsess-hdr", str(conn.get("name") or "integration:GW"), "")

    async def run():
        transport = httpx.ASGITransport(app=gw.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw.test") as c:
            return await c.post("/v1/llm/v1/chat/completions",
                                headers={"authorization": f"Bearer {cred}", **(client_headers or {})},
                                json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    r = asyncio.run(run())
    return r.status_code, _Upstream.seen


def test_the_broker_sends_the_connections_headers_upstream_after_the_key(monkeypatch, upstream):
    conn = {"name": "integration:GW", "provider": "custom", "api_key": "real-key", "base_url": upstream,
            "headers": {"cf-aig-authorization": "Bearer cf-tok", "X-Title": "From the connection"}}
    status, seen = _broker_call(monkeypatch, conn, {"X-Title": "from the CLI", "x-stainless-lang": "js"})
    assert status == 200, seen
    h = seen[-1]["headers"]
    assert seen[-1]["path"] == "/v1/chat/completions"
    assert h["authorization"] == "Bearer real-key"
    assert h["cf-aig-authorization"] == "Bearer cf-tok"
    assert h["x-title"] == "From the connection"          # the connection's, not the client's
    assert h["x-stainless-lang"] == "js"                    # the client's other headers pass as before


def test_a_connection_header_can_never_replace_the_key(monkeypatch, upstream):
    conn = {"name": "integration:GW", "provider": "anthropic", "api_key": "real-key", "base_url": upstream,
            "headers": {"X-Api-Key": "attacker", "Authorization": "Bearer attacker", "X-Project": "p1"}}
    status, seen = _broker_call(monkeypatch, conn)
    assert status == 200
    h = seen[-1]["headers"]
    assert h["x-api-key"] == "real-key" and "attacker" not in json.dumps(h)
    assert h["x-project"] == "p1"


def test_a_connection_without_headers_is_forwarded_exactly_as_before(monkeypatch, upstream):
    conn = {"name": "integration:GW", "provider": "custom", "api_key": "real-key", "base_url": upstream}
    status, seen = _broker_call(monkeypatch, conn, {"X-Title": "from the CLI"})
    assert status == 200 and seen[-1]["headers"]["x-title"] == "from the CLI"


# ── the sandbox never holds a value ────────────────────────────────────────────────────────────

def _owner(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")
    monkeypatch.setenv("HARNESS_GATEWAY_URL", "http://127.0.0.1:8080")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)


def test_in_owner_trust_a_connection_with_headers_is_brokered(monkeypatch):
    _owner(monkeypatch)
    conn = {"name": "integration:GW", "backend": "pi", "provider": "custom", "api_key": "real-key",
            "base_url": "https://gw.example/v1", "headers": {"Helicone-Auth": "Bearer hel-secret"}}
    auth = gw._auth_from_conn(conn, "hsess1")
    assert auth["base_url"] == "http://127.0.0.1:8080/v1/llm"
    assert gw._verify_turn_cred(auth["api_key"]) == ("hsess1", "integration:GW")
    assert "hel-secret" not in json.dumps(auth) and "real-key" not in json.dumps(auth) and "headers" not in auth
    # without headers, owner trust hands the key over as it always did
    plain = gw._auth_from_conn({k: v for k, v in conn.items() if k != "headers"}, "hsess1")
    assert plain["api_key"] == "real-key"


def test_brokered_auth_never_carries_the_headers(monkeypatch):
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "")
    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test-internal-key")
    monkeypatch.setattr(gw, "PUBLIC_BASE_URL", "https://hr.example")
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    auth = gw._auth_from_conn({"name": "c", "backend": "pi", "provider": "openai-api", "api_key": "real-key",
                               "headers": {"X-Project": "p-secret"}}, "hsess1")
    assert auth and "p-secret" not in json.dumps(auth) and "headers" not in auth
    assert "headers" not in gw._AUTH_FIELDS


def test_in_owner_trust_a_native_only_base_is_refused_rather_than_sent_without_its_headers(monkeypatch, capsys):
    _owner(monkeypatch)
    assert gw._auth_from_conn({"name": "g", "backend": "gemini", "provider": "google", "api_key": "k",
                               "headers": {"X-Project": "p"}}, "hsess1") is None
    assert "carries request headers" in capsys.readouterr().out


# ── reading and saving ─────────────────────────────────────────────────────────────────────────

def test_a_reader_sees_the_names_and_never_a_value():
    pub = gw._integration_public({"name": "GW", "provider": "custom",
                                  "config": {"api_key": "k", "base_url": "https://gw.example/v1",
                                             "headers": {"X-Project": "p-secret", "Helicone-Auth": "Bearer h"}}})
    assert pub["config"]["headers"] == {"X-Project": S, "Helicone-Auth": S}
    assert "p-secret" not in json.dumps(pub)
    conn = gw._conn_public({"name": "c", "provider": "custom", "api_key": "k", "headers": {"X-Project": "p-secret"}})
    assert conn["headers"] == {"X-Project": S} and "api_key" not in conn
    assert "headers" not in gw._conn_public({"name": "c", "provider": "custom", "headers": {}})


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
    return {i["name"]: i for i in json.loads(written[gw._INTEGRATIONS_KEY])}


GW = {"name": "GW", "provider": "custom",
      "models": [{"canonical": "m", "provider_id": "m"}],
      "config": {"api_key": "k", "base_url": "https://gw.example/v1", "api_format": "openai",
                 "headers": {" X-Project ": " p1 ", "Helicone-Auth": "Bearer h"}}}


def test_saving_trims_names_and_values(monkeypatch):
    cfg = _save(monkeypatch, [GW])["GW"]["config"]
    assert cfg["headers"] == {"X-Project": "p1", "Helicone-Auth": "Bearer h"}


def test_an_unchanged_save_keeps_each_value_and_an_edit_replaces_only_its_own(monkeypatch):
    first = _save(monkeypatch, [GW])["GW"]
    edited = {**GW, "config": {**GW["config"], "api_key": S,
                               "headers": {"X-Project": S, "Helicone-Auth": "Bearer h2", "X-Title": "t"}}}
    cfg = _save(monkeypatch, [edited], stored=[first])["GW"]["config"]
    assert cfg["headers"] == {"X-Project": "p1", "Helicone-Auth": "Bearer h2", "X-Title": "t"}
    assert cfg["api_key"] == "k"
    # a header left out of the save is removed; an empty map removes them all
    cfg = _save(monkeypatch, [{**edited, "config": {**edited["config"], "headers": {"X-Project": S}}}],
                stored=[first])["GW"]["config"]
    assert cfg["headers"] == {"X-Project": "p1"}
    cfg = _save(monkeypatch, [{**edited, "config": {**edited["config"], "headers": {}}}], stored=[first])["GW"]["config"]
    assert "headers" not in cfg


def test_the_sentinel_for_a_header_never_saved_is_refused(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _save(monkeypatch, [{**GW, "config": {**GW["config"], "headers": {"X-Project": S}}}])
    assert e.value.status_code == 400 and "type the X-Project header's value" in e.value.detail


def test_a_header_value_goes_only_where_it_was_typed_for(monkeypatch):
    """The stored-key rule, for header values: a save that moves the address must type them again."""
    first = _save(monkeypatch, [GW])["GW"]
    moved = {**GW, "config": {**GW["config"], "base_url": "https://elsewhere.example/v1",
                              "headers": {"X-Project": S}}}
    with pytest.raises(HTTPException) as e:
        _save(monkeypatch, [moved], stored=[first])
    assert "type its header values again" in e.value.detail
    retyped = {**moved, "config": {**moved["config"], "headers": {"X-Project": "p1"}}}
    assert _save(monkeypatch, [retyped], stored=[first])["GW"]["config"]["headers"] == {"X-Project": "p1"}


def test_saving_refuses_a_bad_header_with_the_reason(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _save(monkeypatch, [{**GW, "config": {**GW["config"], "headers": {"Authorization": "Bearer x"}}}])
    assert e.value.status_code == 400 and "set by the gateway" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _save(monkeypatch, [{"name": "B", "provider": "bedrock", "config": {"aws_bearer_token": "t", "aws_region": "us-east-1",
                                                                             "headers": {"X-Project": "p"}}}])
    assert "not available on a bedrock connection" in e.value.detail


def test_an_org_connection_takes_headers_and_never_the_sentinel(monkeypatch):
    stored = {}

    async def put(org, key, value, field):
        stored[key] = json.loads(value)
    monkeypatch.setattr(gw, "_vault_put_credential", put)
    out = asyncio.run(gw.put_connection("o1", "gw", gw.ConnBody(backend="pi", provider="openai-api", api_key="k",
                                                                base_url="https://gw.example/v1",
                                                                headers={"X-Project ": " p1"})))
    assert stored["harness-conn-gw"]["headers"] == {"X-Project": "p1"}
    assert out["connection"]["headers"] == {"X-Project": S} and "p1" not in json.dumps(out)
    for bad in ({"X-Project": S}, {"x-api-key": "k2"}):
        with pytest.raises(HTTPException) as e:
            asyncio.run(gw.put_connection("o1", "gw", gw.ConnBody(backend="pi", provider="openai-api", headers=bad)))
        assert e.value.status_code == 400
    asyncio.run(gw.put_connection("o1", "plain", gw.ConnBody(backend="pi", provider="openai-api", api_key="k", headers={})))
    assert "headers" not in stored["harness-conn-plain"]
