"""A token or header value written on a harness goes to the secret store. The record, a row in a
database in the clear, keeps only the reference, and a turn still gets the real value."""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)
import backing  # noqa: E402

ORG = "org-sealed"
TOKEN = "literal-token-value-1234"
HEADER = "literal-header-value-5678"


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setenv("HR_SECRET_KEY", "k")
    s = backing.FileSecretStore(tempfile.mkdtemp(prefix="hr-sealed-"))
    monkeypatch.setattr(gw.BACKING, "secrets", s)
    monkeypatch.setattr(gw, "_org_tenant", lambda org: org)
    return s


@pytest.fixture()
def api(monkeypatch):
    async def who(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", who)
    return TestClient(gw.app)


def _server(**over) -> dict:
    return {"name": "s", "url": "https://mcp.example/x", "auth": TOKEN, "headers": {"X-Api": HEADER, "X-Plain": ""}, **over}


def test_literals_become_references_and_the_store_seals_them(store):
    out = asyncio.run(gw._mcp_seal_literals(ORG, [_server()]))[0]
    assert out["auth"].startswith("vault:") and out["headers"]["X-Api"].startswith("vault:")
    assert TOKEN not in json.dumps(out) and HEADER not in json.dumps(out)
    for f in pathlib.Path(store._root).rglob("*"):
        if f.is_file():
            raw = f.read_text()
            assert raw.startswith("hrenc1:") and TOKEN not in raw and HEADER not in raw


def test_references_and_per_request_headers_are_left_as_they_are(store):
    given = {"name": "s", "url": "u", "auth": "vault:harness-mcp-x", "headers": {"A": "$headers.X-Tok", "B": "vault:harness-mcp-y"}}
    assert asyncio.run(gw._mcp_seal_literals(ORG, [given]))[0] == given


def test_a_store_with_no_key_keeps_what_it_was_given(monkeypatch):
    monkeypatch.delenv("HR_SECRET_KEY", raising=False)
    monkeypatch.setattr(gw.BACKING, "secrets", backing.FileSecretStore(tempfile.mkdtemp(prefix="hr-sealed-")))
    monkeypatch.setattr(gw, "_org_tenant", lambda org: org)
    assert asyncio.run(gw._mcp_seal_literals(ORG, [_server()]))[0]["auth"] == TOKEN


def test_a_harness_keeps_the_reference_and_a_turn_gets_the_value(store, api, monkeypatch):
    async def ok(_url):
        return ""
    monkeypatch.setattr(gw, "_ssrf_check", ok)
    r = api.post("/v1/harnesses", json={"name": f"h-{uuid.uuid4().hex[:6]}", "base": "claude-code", "mcp_servers": [_server()]})
    assert r.status_code == 200, r.text
    assert TOKEN not in r.text and HEADER not in r.text
    hid = r.json()["id"]
    stored = asyncio.run(gw._harness_read(hid)) if hasattr(gw, "_harness_read") else None
    if stored:
        assert TOKEN not in json.dumps(stored) and HEADER not in json.dumps(stored)
    hv = api.get(f"/v1/harnesses/{hid}").json()
    assert TOKEN not in json.dumps(hv)
    servers = asyncio.run(gw._mcp_seal_literals(ORG, hv.get("mcp_servers") or hv.get("mcpServers") or []))
    assert servers and servers[0]["auth"].startswith("vault:")
    # each sealed value is bound to its server's address and the harness's workspace, and resolves there only
    at = dict(use=gw._mcp_use_of_url(_server()["url"]), ws=hv.get("workspace") or "")
    assert asyncio.run(gw._resolve_mcp_auth(ORG, servers[0]["auth"], **at)) == TOKEN
    assert asyncio.run(gw._resolve_mcp_auth(ORG, servers[0]["headers"]["X-Api"], **at)) == HEADER
    elsewhere = dict(use=gw._mcp_use_of_url("https://elsewhere.example/x"), ws=at["ws"])
    assert asyncio.run(gw._resolve_mcp_auth(ORG, servers[0]["auth"], **elsewhere)) == ""
    assert asyncio.run(gw._resolve_mcp_auth(ORG, servers[0]["auth"], use=gw.USE_ENV, ws=at["ws"])) == ""


def test_an_older_record_is_moved_on_the_first_read(store, monkeypatch):
    written: list[dict] = []

    async def upsert(kind, hid, props):
        written.append(props)
    monkeypatch.setattr(gw, "_vg_upsert", upsert)
    v = {"org": ORG, "mcp_servers": json.dumps([_server()])}
    out = asyncio.run(gw._mcp_migrate(ORG, "hrn_x", v))
    assert written and TOKEN not in written[0]["mcp_servers"] and HEADER not in written[0]["mcp_servers"]
    assert TOKEN not in out["mcp_servers"]
    again = asyncio.run(gw._mcp_migrate(ORG, "hrn_x", out))
    assert len(written) == 1 and again == out, "a second read has nothing to move"


def test_every_writer_goes_through_it():
    src = (pathlib.Path(gw.__file__)).read_text()
    # a create has nothing stored, and an update hands over what is, so the server's own entry stays (_is_memories_entry)
    # each names its caller and the harness's workspace, which the stored secrets it names are checked against
    assert src.count("await _mcp_servers_stored(org, body.mcp_servers, p=p, ws=") == 3
    assert src.count("await _mcp_servers_stored(org, body.mcp_servers, cur, p=_caller, ws=cur.get(\"workspace\"),") + \
        src.count("await _mcp_servers_stored(org, body.mcp_servers, v, p=_p, ws=v.get(\"workspace\"), env=body.env)") == 2
    # the variables are checked in the same one call, before anything is stored
    assert "_mcp_refs_named" not in src and src.count("env=body.env)") == 5
    assert src.count("_mcp_servers_prepare(body.mcp_servers)") == 0
