"""Attaching a customer's database to a harness — the routes, the agent's tool, and the one rule
that matters more than any of them: the connection string never comes back out.

Every request in this file goes through the real app with local backing (SQLite + encrypted files
in a temp dir), so what is asserted is what a caller would actually receive.

THE CREDENTIAL CHECK IS NOT ONE TEST. `_seen` records every response body and every line the
gateway printed, and the last test asserts the password appears in none of them — so a route added
later that leaks it fails this file even if nobody writes a test for that route.

Tests that need a real database are skipped when one is not reachable; the gate, the record and
the refusal paths run everywhere. Two are seeded on the test VM:
    ssh -f -N -L 55432:localhost:55432 -L 33306:localhost:33306 azureuser@20.98.237.6
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Set BEFORE importing app: the backing, the internal key and the encryption passphrase are all
# read at import time, exactly as they are in a running container.
_DATA = tempfile.mkdtemp(prefix="hr-sqltest-")
os.environ.update({
    "HR_BACKING": "local", "HR_DATA_DIR": _DATA,
    "HR_SECRET_KEY": "test-passphrase-not-a-real-one",
    "HARNESS_INTERNAL_KEY": "test-internal-key",
    "HARNESS_GLOBAL_TENANT": "global",
    # A base URL, so the MCP server is offered to a turn the way it would be in production.
    "HARNESS_PUBLIC_BASE_URL": "https://gateway.example",
    # Self-hosted: the runner is beside the gateway, and a database on localhost is the normal
    # case rather than an attack. The hosted rule is exercised on its own below.
    "HR_POOL_AUTH": "none",
})

import app  # noqa: E402
import backing  # noqa: E402
import sql_plane  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PG_DSN = "postgresql://postgres:devpass@localhost:55432/shop"
MYSQL_DSN = "mysql://root:devpass@localhost:33306/shop"
PASSWORD = "devpass"

ORG = "testorg"
HEADERS = {"x-harness-internal": "test-internal-key", "x-harness-org": ORG,
           "x-harness-member": "tester@example.com"}


def _reachable(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


needs_pg = pytest.mark.skipif(not _reachable(55432), reason="no PostgreSQL on localhost:55432")
needs_mysql = pytest.mark.skipif(not _reachable(33306), reason="no MySQL on localhost:33306")

# Every response body and every printed line this file produces. See the module docstring.
_seen: list[str] = []


@pytest.fixture(scope="module")
def client(capsys=None):
    with TestClient(app.app) as c:
        yield c


class Rec:
    """A client whose every response body is recorded before it is returned."""

    def __init__(self, c: TestClient):
        self.c = c

    def _do(self, method: str, path: str, **kw):
        r = getattr(self.c, method)(path, headers=HEADERS, **kw)
        _seen.append(r.text)
        return r

    def get(self, path, **kw):
        return self._do("get", path, **kw)

    def post(self, path, **kw):
        return self._do("post", path, **kw)

    def put(self, path, **kw):
        return self._do("put", path, **kw)

    def delete(self, path, **kw):
        return self._do("delete", path, **kw)


@pytest.fixture(scope="module")
def api(client):
    return Rec(client)


@pytest.fixture()
def harness(api):
    r = api.post("/v1/harnesses", json={"name": "Dashboard", "base": "claude-code"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── the record, and where the credential is not ──────────────────────────────────

def test_connecting_returns_the_database_but_never_the_credential(api, harness):
    r = api.put(f"/v1/harnesses/{harness}/datasource",
                json={"engine": "postgres", "connection_string": PG_DSN, "sample_rows": True})
    assert r.status_code == 200, r.text
    ds = r.json()["dataSource"]
    # What a person needs to recognise the connection they made…
    assert ds == {"engine": "postgres", "host": "localhost:55432", "database": "shop",
                  "sampleRows": True, "updatedAt": ds["updatedAt"]}
    # …and nothing else. No user, no password, no reference to where the secret is kept.
    assert PASSWORD not in r.text and "postgres:" not in r.text and "secret" not in r.text


def test_the_harness_record_carries_a_reference_and_not_a_connection_string(harness, api):
    """Read the stored vertex directly: this is the shape a graph dump would show."""
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    v = asyncio.run(app.BACKING.graph.get(harness, label="Harness"))
    rec = json.loads(v["datasource"])
    assert rec["secret"] == f"vault:{app._ds_secret_key(harness)}"
    assert PASSWORD not in json.dumps(rec)
    assert PASSWORD not in json.dumps(v)


def test_the_stored_secret_is_encrypted_on_disk(harness, api):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    files = list(Path(_DATA, "secrets").rglob(app._ds_secret_key(harness)))
    assert files, "the credential was not written to the secret store"
    raw = files[0].read_text()
    assert raw.startswith("hrenc1:") and PASSWORD not in raw


def test_a_harness_reports_its_datasource_and_a_fresh_one_reports_none(api, harness):
    assert api.get(f"/v1/harnesses/{harness}").json()["dataSource"] is None
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "mysql", "connection_string": MYSQL_DSN, "sample_rows": False})
    got = api.get(f"/v1/harnesses/{harness}").json()["dataSource"]
    assert got["engine"] == "mysql" and got["database"] == "shop" and got["sampleRows"] is False


def test_disconnecting_removes_the_record(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    r = api.delete(f"/v1/harnesses/{harness}/datasource")
    assert r.status_code == 200 and r.json() == {"harnessId": harness, "dataSource": None,
                                                 "disconnected": True}
    assert api.get(f"/v1/harnesses/{harness}/datasource").json()["dataSource"] is None
    # And the queries stop working, rather than working against a database nobody thinks is
    # attached any more.
    q = api.post(f"/v1/harnesses/{harness}/sql/query", json={"sql": "SELECT 1"})
    assert q.status_code == 404 and q.json()["error"]["code"] == "datasource_not_connected"


def test_deleting_the_harness_does_not_leave_the_credential_behind(api, harness):
    """The most decisive thing the UI offers must not leave a production password on disk."""
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    stored = next(iter(Path(_DATA, "secrets").rglob(app._ds_secret_key(harness))))
    assert PG_DSN == asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], app._ds_secret_key(harness)))

    assert api.delete(f"/v1/harnesses/{harness}").json()["deleted"] is True
    # The file may remain (the store has no delete); what it holds must not.
    assert not asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], app._ds_secret_key(harness)))
    assert PASSWORD not in stored.read_text()


def test_another_org_cannot_see_or_use_a_datasource(client, harness, api):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    other = {**HEADERS, "x-harness-org": "someone-else"}
    for r in (client.get(f"/v1/harnesses/{harness}/datasource", headers=other),
              client.post(f"/v1/harnesses/{harness}/sql/query", headers=other, json={"sql": "SELECT 1"}),
              client.get(f"/v1/harnesses/{harness}/sql/schema", headers=other)):
        _seen.append(r.text)
        assert r.status_code == 404 and r.json()["error"]["code"] == "harness_not_found"


# ── what a bad connection string gets told ───────────────────────────────────────

def test_an_unsupported_engine_says_what_is_supported(api, harness):
    r = api.put(f"/v1/harnesses/{harness}/datasource",
                json={"engine": "snowflake", "connection_string": "snowflake://x/y"})
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "This connects to PostgreSQL and MySQL databases."


def test_the_wrong_kind_of_connection_string_is_caught_before_the_driver_is(api, harness):
    r = api.put(f"/v1/harnesses/{harness}/datasource",
                json={"engine": "postgres", "connection_string": MYSQL_DSN})
    assert r.status_code == 400
    msg = r.json()["error"]["message"]
    assert "PostgreSQL connection string looks like" in msg
    # The example must not be the string they just sent back at them — that is how a password
    # ends up in a UI error banner.
    assert PASSWORD not in msg


def test_a_hosted_instance_refuses_to_be_pointed_at_an_internal_address(api, harness, monkeypatch):
    """Self-hosted, a database on localhost is the operator's own and allowed. Hosted, a customer
    naming an internal host is the same abuse an MCP URL would be, and gets the same answer."""
    monkeypatch.setattr(app, "_pool_is_local", lambda: False)
    r = api.put(f"/v1/harnesses/{harness}/datasource",
                json={"engine": "postgres", "connection_string": PG_DSN})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unreachable_host"
    # And the button that tests a connection refuses it too, rather than passing what the save
    # would then reject.
    t = api.post("/v1/datasource-test", json={"engine": "postgres", "connection_string": PG_DSN})
    assert t.status_code == 400 and t.json()["error"]["code"] == "unreachable_host"


def test_a_connection_string_with_no_database_says_so(api, harness):
    r = api.put(f"/v1/harnesses/{harness}/datasource",
                json={"engine": "postgres", "connection_string": "postgresql://u:p@host:5432"})
    assert r.status_code == 400 and "names no database" in r.json()["error"]["message"]


def test_no_key_to_encrypt_with_is_a_sentence_naming_the_variable(api, harness, monkeypatch):
    """The 501 the operator of a keyless instance must see. Not a 500, and not a plaintext write."""
    monkeypatch.delenv("HR_SECRET_KEY", raising=False)
    monkeypatch.setattr(app.BACKING, "secrets", backing.FileSecretStore(os.path.join(_DATA, "nokey")))
    r = api.put(f"/v1/harnesses/{harness}/datasource",
                json={"engine": "postgres", "connection_string": PG_DSN})
    assert r.status_code == 501
    err = r.json()["error"]
    assert err["code"] == "secrets_not_configured" and "HR_SECRET_KEY" in err["message"]
    assert not list(Path(_DATA, "nokey").rglob("*")), "a credential was written anyway"


# ── testing a connection before saving one ───────────────────────────────────────

@needs_pg
def test_test_connection_reports_the_tables_it_can_see(api):
    r = api.post("/v1/datasource-test", json={"engine": "postgres", "connection_string": PG_DSN})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["database"] == "shop" and body["tableCount"] >= 3
    assert "public.orders" in body["tables"]


@needs_pg
def test_a_wrong_password_is_a_usable_message_and_not_a_stack_trace(api):
    r = api.post("/v1/datasource-test",
                 json={"engine": "postgres",
                       "connection_string": "postgresql://postgres:wrongpass@localhost:55432/shop"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "password" in body["error"].lower() or "authentication" in body["error"].lower()
    assert "wrongpass" not in body["error"], "the failure echoed the password back"


def test_an_unreachable_host_fails_the_test_rather_than_the_request(api):
    r = api.post("/v1/datasource-test",
                 json={"engine": "postgres",
                       "connection_string": f"postgresql://u:{PASSWORD}@127.0.0.1:1/shop"})
    # ok:false with HTTP 200 — "nothing is listening there" is a successful test reporting a
    # failure, and the dialog renders body.error rather than a status code.
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"]
    assert PASSWORD not in r.text


# ── running a query, which is what opening a dashboard does ──────────────────────

@needs_pg
def test_a_panel_refresh_returns_columns_and_rows(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    r = api.post(f"/v1/harnesses/{harness}/sql/query",
                 json={"sql": "SELECT status, count(*) AS n FROM orders GROUP BY status ORDER BY n DESC"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["status", "n"] and body["row_count"] >= 1
    assert body["truncated"] is False


@needs_mysql
def test_the_same_query_shape_works_on_mysql(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "mysql", "connection_string": MYSQL_DSN})
    r = api.post(f"/v1/harnesses/{harness}/sql/query",
                 json={"sql": "SELECT name, price FROM products ORDER BY price DESC"})
    assert r.status_code == 200, r.text
    assert r.json()["columns"] == ["name", "price"] and r.json()["row_count"] >= 1


@needs_pg
def test_a_write_is_refused_before_it_reaches_the_database(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    r = api.post(f"/v1/harnesses/{harness}/sql/query", json={"sql": "DELETE FROM orders"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "sql_refused"
    # The rows are still there.
    n = api.post(f"/v1/harnesses/{harness}/sql/query", json={"sql": "SELECT count(*) FROM orders"})
    assert int(n.json()["rows"][0][0]) > 0


@needs_pg
def test_a_bad_column_comes_back_as_the_databases_own_sentence(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    r = api.post(f"/v1/harnesses/{harness}/sql/query", json={"sql": "SELECT revenu FROM orders"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "sql_failed"
    assert "revenu" in r.json()["error"]["message"]


@needs_pg
def test_the_row_cap_is_applied_and_declared(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    r = api.post(f"/v1/harnesses/{harness}/sql/query",
                 json={"sql": "SELECT * FROM orders", "max_rows": 2})
    body = r.json()
    assert body["row_count"] <= 2 and body["limit_applied"] == 2


@needs_pg
def test_a_caller_cannot_ask_for_more_than_the_engine_allows(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    r = api.post(f"/v1/harnesses/{harness}/sql/query",
                 json={"sql": "SELECT * FROM orders", "max_rows": 10_000_000})
    assert r.json()["limit_applied"] == sql_plane.DEFAULT_MAX_ROWS


# ── the schema, and the sample-rows switch ───────────────────────────────────────

@needs_pg
def test_sampling_on_shows_rows_and_sampling_off_shows_none(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN, "sample_rows": True})
    on = api.get(f"/v1/harnesses/{harness}/sql/schema").json()
    assert on["sampled"] is True
    assert all("sample" in t for t in on["tables"])
    assert {t["name"] for t in on["tables"]} >= {"customers", "orders", "products"}

    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN, "sample_rows": False})
    off = api.get(f"/v1/harnesses/{harness}/sql/schema").json()
    assert off["sampled"] is False
    # The shape is still there; not one value of anyone's data is.
    assert {t["name"] for t in off["tables"]} == {t["name"] for t in on["tables"]}
    assert all("sample" not in t for t in off["tables"])
    assert [c["name"] for c in off["tables"][0]["columns"]]


# ── the agent's tool ─────────────────────────────────────────────────────────────

def _rpc(client, token, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    r = client.post("/v1/mcp/sql", json=body,
                    headers={"authorization": f"Bearer {token}"} if token else {})
    _seen.append(r.text)
    return r


def test_the_tool_endpoint_refuses_without_a_valid_credential(client, harness):
    assert _rpc(client, None, "tools/list").status_code == 401
    assert _rpc(client, "hrs_not-a-real-token", "tools/list").status_code == 401
    # A token whose signature does not match this instance's key.
    good = app._mint_sql_cred(harness, "sess1")
    forged = good[:-1] + ("a" if good[-1] != "a" else "b")
    assert _rpc(client, forged, "tools/list").status_code == 401


def test_a_turn_credential_is_scoped_to_one_harness(client, api, harness):
    """The token IS the authorisation. One minted for another harness must not read this one."""
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    other = api.post("/v1/harnesses", json={"name": "Other", "base": "claude-code"}).json()["id"]
    r = _rpc(client, app._mint_sql_cred(other, "sess1"), "tools/call",
             {"name": "query", "arguments": {"sql": "SELECT 1"}})
    assert r.json()["result"]["isError"] is True
    assert "No database is connected" in r.json()["result"]["content"][0]["text"]


def test_the_tool_list_is_the_two_things_an_agent_needs(client, harness):
    r = _rpc(client, app._mint_sql_cred(harness, "sess1"), "tools/list")
    tools = r.json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["schema", "query"]
    assert all(t["inputSchema"]["type"] == "object" for t in tools)


def test_initialize_and_the_initialized_notification(client, harness):
    tok = app._mint_sql_cred(harness, "sess1")
    r = _rpc(client, tok, "initialize", {"protocolVersion": "2025-06-18"})
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["capabilities"]["tools"] == {}
    # A notification has no id and must be answered with no body.
    n = client.post("/v1/mcp/sql", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert n.status_code == 202


@needs_pg
def test_the_agent_can_read_the_schema_and_run_a_select(client, api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN, "sample_rows": True})
    tok = app._mint_sql_cred(harness, "sess1")

    schema = json.loads(_rpc(client, tok, "tools/call",
                             {"name": "schema"}).json()["result"]["content"][0]["text"])
    assert {t["name"] for t in schema["tables"]} >= {"customers", "orders", "products"}

    out = _rpc(client, tok, "tools/call",
               {"name": "query", "arguments": {"sql": "SELECT count(*) AS n FROM customers"}})
    res = out.json()["result"]
    assert res.get("isError") is not True
    assert json.loads(res["content"][0]["text"])["columns"] == ["n"]


@needs_pg
def test_the_agent_is_told_when_sampling_is_off_rather_than_seeing_an_empty_database(client, api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN, "sample_rows": False})
    schema = json.loads(_rpc(client, app._mint_sql_cred(harness, "s"), "tools/call",
                             {"name": "schema"}).json()["result"]["content"][0]["text"])
    assert schema["sampled"] is False and "turned off" in schema["note"]
    assert all("sample" not in t for t in schema["tables"])


@needs_pg
def test_the_agent_gets_the_error_back_and_can_fix_it(client, api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    tok = app._mint_sql_cred(harness, "sess1")
    bad = _rpc(client, tok, "tools/call",
               {"name": "query", "arguments": {"sql": "SELECT revenu FROM orders"}})
    res = bad.json()["result"]
    assert res["isError"] is True and "revenu" in res["content"][0]["text"]

    refused = _rpc(client, tok, "tools/call",
                   {"name": "query", "arguments": {"sql": "DROP TABLE orders"}})
    assert refused.json()["result"]["isError"] is True
    assert "only select" in refused.json()["result"]["content"][0]["text"].lower()


def test_an_unknown_tool_and_an_unknown_method_are_answered_not_crashed(client, harness):
    tok = app._mint_sql_cred(harness, "sess1")
    r = _rpc(client, tok, "tools/call", {"name": "drop_everything"})
    assert r.json()["result"]["isError"] is True
    m = _rpc(client, tok, "resources/list")
    assert m.json()["error"]["code"] == -32601


# ── how the tool reaches a turn ──────────────────────────────────────────────────

def test_a_connected_harness_hands_its_turn_a_database_tool_and_no_credential(api, harness):
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    v = asyncio.run(app._harness_vertex(harness))
    mcp, _skills, _off, _tools = asyncio.run(app._harness_plugins(harness, ORG, hv=v, sid="sess-42"))
    entry = next(m for m in mcp if m["name"] == "database")
    assert entry["url"] == "https://gateway.example/v1/mcp/sql"
    assert PASSWORD not in json.dumps(entry)
    # What the sandbox receives is a token, and it resolves back to this harness and this session.
    assert app._verify_sql_cred(entry["auth"]) == (harness, "sess-42")


def test_a_harness_with_no_database_hands_its_turn_no_database_tool(api, harness):
    v = asyncio.run(app._harness_vertex(harness))
    mcp, *_ = asyncio.run(app._harness_plugins(harness, ORG, hv=v, sid="sess-42"))
    assert [m for m in mcp if m["name"] == "database"] == []


def test_a_sql_token_is_not_a_model_broker_token_and_the_reverse(harness):
    """Different audiences, so one lifted out of a sandbox cannot be spent at the other."""
    sql_tok = app._mint_sql_cred(harness, "sess1")
    llm_tok = app._mint_turn_cred("sess1", "anthropic")
    assert app._verify_turn_cred(sql_tok) is None
    assert app._verify_sql_cred(llm_tok) is None


# ── launching a kit with a database attached ─────────────────────────────────────

def test_launch_accepts_a_connection_and_a_bad_one_provisions_nothing(api, monkeypatch):
    kit = {"id": "dash", "title": "Dashboards", "app": {"route": "/kits/dash"},
           "harness": {"name": "Dashboards", "datasource": {"required": True},
                       "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}}
    monkeypatch.setattr(app, "_kits", lambda: {"dash": kit})

    bad = api.post("/v1/kits/dash/launch",
                   json={"engine": "postgres", "connection_string": "not-a-connection-string"})
    assert bad.status_code == 400
    # Nothing was provisioned on the way to that error.
    assert next(k for k in api.get("/v1/kits").json()["kits"] if k["id"] == "dash")["launched"] is False

    ok = api.post("/v1/kits/dash/launch",
                  json={"engine": "postgres", "connection_string": PG_DSN, "sample_rows": False})
    assert ok.status_code == 200, ok.text
    assert ok.json()["created"] is True
    assert ok.json()["dataSource"] == {"engine": "postgres", "host": "localhost:55432",
                                       "database": "shop", "sampleRows": False,
                                       "updatedAt": ok.json()["dataSource"]["updatedAt"]}
    # Launched twice: the same Harness, and the connection typed the second time is applied to it
    # rather than silently dropped.
    again = api.post("/v1/kits/dash/launch",
                     json={"engine": "mysql", "connection_string": MYSQL_DSN})
    assert again.json()["harnessId"] == ok.json()["harnessId"]
    assert again.json()["created"] is False
    assert again.json()["dataSource"]["engine"] == "mysql"

    listed = next(k for k in api.get("/v1/kits").json()["kits"] if k["id"] == "dash")
    assert listed["datasource"] == {"required": True, "engines": ["postgres", "mysql"]}
    assert listed["connected"]["engine"] == "mysql"


def test_a_kit_that_reads_no_database_declares_none(api, monkeypatch):
    monkeypatch.setattr(app, "_kits", lambda: {"slides": {"id": "slides", "title": "Slides",
                                                          "app": {"route": "/kits/slides"},
                                                          "harness": {"name": "Slides"}}})
    assert next(k for k in api.get("/v1/kits").json()["kits"]
                if k["id"] == "slides")["datasource"] is None


# ── the whole file, checked at once ──────────────────────────────────────────────

def test_the_password_appears_in_no_response_this_file_produced():
    """Every body recorded above, in one assertion. A new route that leaks the credential fails
    here even if nobody thought to test that route."""
    assert _seen, "nothing was recorded — the recording client stopped being used"
    leaked = [t for t in _seen if PASSWORD in t]
    assert not leaked, f"{len(leaked)} response(s) contained the password: {leaked[:1]}"


def test_the_password_appears_in_nothing_the_gateway_printed(api, harness, capsys):
    """Connect, query, fail — then read the logs the container would have written."""
    capsys.readouterr()
    api.put(f"/v1/harnesses/{harness}/datasource",
            json={"engine": "postgres", "connection_string": PG_DSN})
    api.post(f"/v1/harnesses/{harness}/sql/query", json={"sql": "SELECT 1"})
    api.post("/v1/datasource-test",
             json={"engine": "postgres", "connection_string": f"postgresql://u:{PASSWORD}@127.0.0.1:1/x"})
    api.delete(f"/v1/harnesses/{harness}/datasource")
    out = capsys.readouterr()
    assert PASSWORD not in out.out and PASSWORD not in out.err
    # And it did log something identifying, so this is not passing on an empty string.
    assert "[sql]" in out.out
