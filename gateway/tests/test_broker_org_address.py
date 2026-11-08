"""An organization's own connection address, on a deployment shared by several organizations, is held where the broker
opens it: refused before any socket when the address text can't be used, and at the socket (_CheckedNetwork) when its
name resolves inside this deployment's networks, so a name that rebinds can't slip between a check and the connect. The
operator's own integrations and a single-operator install are unchanged."""
import os
import socket
import sys
from pathlib import Path

import httpcore
import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

PUBLIC = "93.184.216.34"


@pytest.fixture
def broker(monkeypatch):
    seen: list[httpx.Request] = []
    sockets: list[tuple[str, int]] = []
    conns: dict = {}

    def upstream(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"ok": True})

    async def vertex(sid):
        return {"tenant": "org-a"}

    async def get_connection(org, name):
        return conns.get(name, (None, None))

    async def integrations():
        return [{"name": "ops", "provider": "custom", "config": {"api_format": "openai", "base_url": "http://10.0.0.7/v1", "api_key": "sk-ops"}}]

    async def resolve(host, port):
        table = {"llm.example.com": PUBLIC, "rebind.example.com": "10.1.2.3"}
        ip = table.get(host, host)
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, 6, "", (ip, port))]

    async def no_network(self, host, port, timeout=None, local_address=None, socket_options=None):
        sockets.append((host, port))
        raise httpcore.ConnectError("test: no network")

    async def entra_token(conn):
        return "entra-tok"

    monkeypatch.setattr(gw, "INTERNAL_KEY", "k-test")
    monkeypatch.setattr(gw, "_vertex_get", vertex)
    monkeypatch.setattr(gw, "_get_connection", get_connection)
    monkeypatch.setattr(gw, "_integrations_doc", integrations)
    monkeypatch.setattr(gw, "_resolve", resolve)
    monkeypatch.setattr(gw, "_entra_token", entra_token)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", no_network)
    monkeypatch.setattr(gw, "_relay_http", httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    gw._checked_clients.pop("relay", None)
    monkeypatch.setattr(gw, "_pool_is_local", lambda: False)
    c = TestClient(gw.app, raise_server_exceptions=False)

    def call(base_url, *, conn=None, name="mine", tenant="org-a"):
        conns[name] = ({"provider": "custom", "api_format": "openai", "base_url": base_url, "api_key": "sk-org",
                        **(conn or {})}, tenant)
        tok = gw._mint_turn_cred("sess-1", name)
        return c.post("/v1/llm/v1/chat/completions", headers={"authorization": f"Bearer {tok}"},
                      json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    yield call, seen, sockets, monkeypatch
    gw._checked_clients.pop("relay", None)


@pytest.mark.parametrize("base", ["http://127.0.0.1:8081/v1", "http://169.254.169.254/latest", "http://10.0.0.5/v1",
                                  "http://192.168.1.10/v1", "http://[::1]:8080/v1", "https://rebind.example.com/v1"])
def test_an_organizations_address_inside_this_deployment_is_refused_at_the_socket(broker, base):
    call, seen, sockets, _ = broker
    r = call(base)
    assert r.status_code == 403 and "This connection's address can't be used" in r.json()["detail"], r.text
    assert "internal" in r.json()["detail"]
    assert not seen and not sockets, "nothing was sent, and no socket opened"


@pytest.mark.parametrize("base,why", [("http://user:pw@llm.example.com/v1", "user name or password"),
                                      ("https://llm.example.com/v1?", "? or #"),
                                      ("https://llm.example.com/v1#x", "? or #"),
                                      ("ftp://llm.example.com/v1", "https://")])
def test_an_address_that_cant_be_used_as_written_is_refused_before_any_lookup(broker, base, why):
    call, seen, sockets, _ = broker
    r = call(base)
    assert r.status_code == 403 and why in r.json()["detail"], r.text
    assert not seen and not sockets


def test_a_public_address_is_opened_to_the_very_address_it_was_classified_as(broker):
    call, seen, sockets, _ = broker
    r = call("https://llm.example.com/v1")
    assert sockets == [(PUBLIC, 443)], "the socket goes to the address the check classified"
    assert not seen, "an organization's own address never takes the unchecked pool"
    assert r.status_code >= 500


def test_an_entra_azure_connection_of_an_organization_is_held_the_same_way(broker):
    call, seen, sockets, _ = broker
    r = call("http://169.254.169.254", conn={"provider": "azure-foundry", "auth": "entra", "tenant_id": "t",
                                             "client_id": "c", "client_secret": "s", "api_key": None})
    assert r.status_code == 403 and "internal" in r.json()["detail"], r.text
    assert not seen and not sockets


def test_the_operators_own_integration_is_unchanged(broker):
    call, seen, sockets, monkeypatch = broker
    c = TestClient(gw.app, raise_server_exceptions=False)
    tok = gw._mint_turn_cred("sess-1", "integration:ops")
    r = c.post("/v1/llm/v1/chat/completions", headers={"authorization": f"Bearer {tok}"}, json={"model": "m", "messages": []})
    assert r.status_code == 200 and str(seen[-1].url) == "http://10.0.0.7/v1/chat/completions"


def test_a_platform_connection_is_unchanged(broker):
    call, seen, sockets, _ = broker
    r = call("http://10.0.0.8/v1", name="platform", tenant=gw.GLOBAL_TENANT)
    assert r.status_code == 200 and str(seen[-1].url) == "http://10.0.0.8/v1/chat/completions"


def test_a_single_operator_install_reaches_its_own_network_as_before(broker):
    call, seen, sockets, monkeypatch = broker
    monkeypatch.setattr(gw, "_pool_is_local", lambda: True)
    r = call("http://127.0.0.1:1234/v1")
    assert r.status_code == 200 and str(seen[-1].url) == "http://127.0.0.1:1234/v1/chat/completions"


def test_every_send_in_the_broker_says_a_refused_address_the_same_way():
    """The retries (a field Google refuses, a thinking shape an aggregator refuses) open a socket again, and the name
    could answer differently by then: each send is the refusal-aware one."""
    import inspect
    src = inspect.getsource(gw.llm_broker)
    assert "rc.send(" not in src and src.count("_broker_send(") == 3
