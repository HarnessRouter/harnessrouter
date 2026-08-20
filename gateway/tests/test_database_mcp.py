"""A database as an ORDINARY MCP server on a harness — the entry, the agent's tool, the app's
data plane, and the one rule that matters more than any of them: the connection string never
comes back out.

Every request in this file goes through the real app with local backing (SQLite + encrypted files
in a temp dir), so what is asserted is what a caller would actually receive.

THE CREDENTIAL CHECK IS NOT ONE TEST. `_seen` records every response body and every line the
gateway printed, and the last test asserts the password appears in none of them — so a route added
later that leaks it fails this file even if nobody writes a test for that route.

Tests that need a real database are skipped when one is not reachable; the gate, the entry and
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
import time
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
    # A base URL, so the MCP server is offered to a turn the way it would be in production — and
    # so it is an address this gateway recognises as its own.
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

MCP_URL = "https://gateway.example/v1/mcp/database"
ENTRY_ID = "mcp.database"

# The kit that connects one. Connecting a database is something the kit that reads one drives,
# so every attach in this file goes through launch — there is no other way in.
_KIT = {"id": "dash", "title": "Dashboards", "app": {"route": "/kits/dash"},
        "harness": {"name": "Dashboards",
                    "mcp_servers": [],
                    "launch": {"database": {"engines": ["postgres", "mysql"],
                                            "name": "database", "id": ENTRY_ID}},
                    "recommended": [{"base": "claude-code", "model": "claude-opus-5"}]}}


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
def kit(monkeypatch):
    """This kit, with a fresh id per test so launch's idempotence isn't a shared fixture."""
    kid = f"dash{int(time.time() * 1e6) % 10_000_000}"
    monkeypatch.setattr(app, "_kits", lambda: {kid: {**_KIT, "id": kid}})
    return kid


@pytest.fixture()
def harness(api, kit):
    """A launched-but-unconnected harness of a kit that reads no database."""
    r = api.post("/v1/harnesses", json={"name": "Dashboard", "base": "claude-code"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _attach(api, kit, dsn=PG_DSN, engine="postgres", sample_rows=True):
    """Connect a database the only way there is: launch the kit that reads one."""
    r = api.post(f"/v1/kits/{kit}/launch",
                 json={"database": {"engine": engine, "connection_string": dsn,
                                    "sample_rows": sample_rows}})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def connected(api, kit):
    """A harness with a database connected, and the kit that connected it."""
    return _attach(api, kit)["harnessId"]


def _db_row(harness_out: dict) -> dict | None:
    """The database entry in a harness's own list of servers, found by its id — there is no field
    that says which one it is, and that is the point."""
    return next((s for s in harness_out.get("mcpServers") or []
                 if s.get("id") == ENTRY_ID), None)


def _vertex(hid: str) -> dict:
    return asyncio.run(app.BACKING.graph.get(hid, label="Harness"))


def _stored(hid: str) -> list[dict]:
    return json.loads(_vertex(hid).get("mcp_servers") or "[]")


def _key(hid: str) -> str:
    """The record key the harness's database entry references."""
    return app._vault_key(next(s for s in _stored(hid) if s.get("id") == ENTRY_ID)["auth"])


def _record(hid: str) -> dict | None:
    return asyncio.run(app._hosted_record(ORG, _key(hid)))


def _secrets_root() -> Path:
    """Where the running process's secret store actually is.

    Read off the store rather than rebuilt from this module's own temp dir: `app` is imported once
    per process, so whichever test module got there first decided HR_DATA_DIR — and an assertion
    about "what is on disk" that looks in an empty directory passes for the wrong reason."""
    return Path(app.BACKING.secrets._root)


def _save_config(api, hid: str, servers: list[dict], name="Dashboard"):
    """What the console does when someone presses Save: a whole-config PUT."""
    return api.put(f"/v1/harnesses/{hid}",
                   json={"name": name, "base": "claude-code", "mcp_servers": servers})


def _entry_of(hid: str) -> dict:
    return next(s for s in _stored(hid) if s.get("id") == ENTRY_ID)


def _make_legacy(hid: str, *, shape: int) -> str:
    """Rewrite a connected harness into an earlier shape, and return the old secret key.

    Shape 0 is what every deployed customer's vertex looks like the moment this build ships: the
    record on its own `datasource` prop, nothing in mcp_servers. Shape 1 is the refactor this
    replaces: an mcp_servers entry carrying `managed` and `config`. Both hold a BARE DSN at
    harness-ds-<hid-safe>.
    """
    rec = _record(hid)
    old_key = "harness-ds-" + hid.lower().replace("_", "-")
    cfg = {"engine": rec["engine"], "secret": f"vault:{old_key}", "host": rec["host"],
           "database": rec["database"], "sample_rows": rec["sample_rows"],
           "updated_at": rec["updated_at"]}
    tenant = app._tenants_for(ORG)[0]
    asyncio.run(app.BACKING.secrets.put(tenant, old_key, rec["dsn"], require_encryption=True))
    asyncio.run(app.BACKING.secrets.put(tenant, _key(hid), "", require_encryption=True))
    if shape == 0:
        asyncio.run(app._vg_upsert("Harness", hid,
                                   {"datasource": json.dumps(cfg), "mcp_servers": "[]"}))
    else:
        entry = {"id": ENTRY_ID, "name": "database", "enabled": True,
                 "managed": "database", "config": cfg}
        asyncio.run(app._vg_upsert("Harness", hid,
                                   {"datasource": "", "mcp_servers": json.dumps([entry])}))
    return old_key


# ── the entry, and where the credential is not ───────────────────────────────────

def test_connecting_returns_the_harness_and_never_the_credential(api, kit):
    row = _db_row(_attach(api, kit)["harness"])
    # What a person needs to recognise the server they connected…
    assert row["name"] == "database" and row["enabled"] is True
    assert row["url"] == MCP_URL and row["transport"] == "http"
    # …and nothing else. No user, no password, no host, no database name, no engine.
    body = _seen[-1]
    assert PASSWORD not in body and "postgres:" not in body
    assert "localhost:55432" not in body and "shop" not in body


def test_the_entry_carries_a_reference_and_not_a_connection_string(api, kit, harness):
    """Read the stored vertex directly: this is the shape a graph dump would show."""
    hid = _attach(api, kit)["harnessId"]
    entry = _entry_of(hid)
    assert entry["auth"].startswith("vault:" + app._HOSTED_SECRET_PREFIX)
    assert PASSWORD not in json.dumps(entry)
    assert PASSWORD not in json.dumps(_vertex(hid))

    # THE WHOLE POINT, asserted: its key set is a third-party entry's key set. Nothing stored
    # distinguishes them, so nothing can branch on the difference.
    assert _save_config(api, harness, [{"id": "mcp.remote", "name": "remote",
                                        "url": "https://mcp.example.com/mcp",
                                        "transport": "http", "auth": "vault:harness-mcp-theirs",
                                        "enabled": True}]).status_code == 200
    assert set(entry) == set(_stored(harness)[0]) == {"id", "name", "url", "transport",
                                                      "auth", "enabled"}


def test_the_whole_connection_record_is_encrypted_on_disk(api, kit):
    hid = _attach(api, kit)["harnessId"]
    files = list(_secrets_root().rglob(_key(hid)))
    assert files, "the record was not written to the secret store"
    raw = files[0].read_text()
    assert raw.startswith("hrenc1:")
    assert PASSWORD not in raw and "localhost:55432" not in raw and "shop" not in raw
    # And NONE of it is on the vertex — host and database used to sit there in plaintext.
    v = json.dumps(_vertex(hid))
    assert "localhost:55432" not in v and "shop" not in v


def test_a_harness_lists_its_database_and_a_fresh_one_lists_none(api, kit, harness):
    assert _db_row(api.get(f"/v1/harnesses/{harness}").json()) is None
    hid = _attach(api, kit, MYSQL_DSN, engine="mysql", sample_rows=False)["harnessId"]
    row = _db_row(api.get(f"/v1/harnesses/{hid}").json())
    assert row["url"] == MCP_URL
    # The harness read says nothing about WHICH database. The server that owns the connection is
    # the one that names it.
    got = api.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}").json()
    assert got["connection"] == {"engine": "mysql", "host": "localhost:33306",
                                 "database": "shop", "sampleRows": False}
    assert got["id"] == ENTRY_ID and got["name"] == "database" and got["enabled"] is True


def test_removing_the_entry_by_saving_the_configuration_scrubs_its_record(api, connected):
    """There is no keep-if-omitted exemption: an entry the caller did not send is gone, and the
    record behind it is scrubbed rather than orphaned."""
    key = _key(connected)
    r = _save_config(api, connected, [])
    assert r.status_code == 200 and _db_row(r.json()) is None
    assert _db_row(api.get(f"/v1/harnesses/{connected}").json()) is None
    assert not asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], key))
    # And the queries stop working, rather than working against a database nobody thinks is
    # connected any more.
    q = api.post(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}/query", json={"sql": "SELECT 1"})
    assert q.status_code == 404 and q.json()["error"]["code"] == "database_not_connected"


def test_a_record_whose_entry_is_gone_is_not_left_on_disk(api, connected):
    """Not only when the whole list is emptied: the scrub is driven off which records the entries
    still reference, so dropping one entry among several scrubs exactly that one."""
    key = _key(connected)
    remote = {"id": "mcp.remote", "name": "remote", "url": "https://mcp.example/mcp",
              "transport": "http", "auth": "vault:harness-mcp-theirs", "enabled": True}
    assert _save_config(api, connected, [remote]).status_code == 200
    assert _stored(connected) == [remote], "the surviving entry was disturbed"
    assert not asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], key))


@pytest.mark.parametrize("how", ["save", "delete"])
def test_one_harness_cannot_scrub_another_harnesss_record(api, connected, harness, how):
    """`auth` is client-writable and harness ids are public, so anyone may name another agent's
    record on an entry of their own. Removing that entry — or deleting the whole harness — must
    not disconnect a database they were never given: the read is refused by the record naming its
    harness, and so is the scrub."""
    key = _key(connected)
    assert _save_config(api, harness, [{"id": "mcp.x", "name": "x",
                                        "url": "https://evil.example/mcp", "transport": "http",
                                        "auth": f"vault:{key}", "enabled": True}],
                        name="borrower").status_code == 200
    if how == "save":
        assert _save_config(api, harness, [], name="borrower").status_code == 200
    else:
        assert api.delete(f"/v1/harnesses/{harness}").json()["deleted"] is True

    assert asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], key)), \
        "another harness's write destroyed this connection"
    assert _record(connected)["dsn"] == PG_DSN
    # And the harness that actually owns it still resolves its own server.
    assert api.get(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}"
                   ).json()["connection"]["database"] == "shop"


def test_renaming_an_entry_is_not_a_removal(api, connected):
    """The record belongs to the entry that references it, not to an id or a name. Renaming
    either must keep the server working rather than quietly scrub what it reads."""
    key = _key(connected)
    assert _save_config(api, connected, [{**_entry_of(connected), "id": "mcp.other",
                                          "name": "shop"}]).status_code == 200
    assert asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], key))
    got = api.get(f"/v1/harnesses/{connected}/servers/mcp.other").json()
    assert got["name"] == "shop" and got["connection"]["database"] == "shop"


def test_deleting_the_harness_does_not_leave_the_credential_behind(api, connected):
    """The most decisive thing the UI offers must not leave a production password on disk."""
    key = _key(connected)
    stored = next(iter(_secrets_root().rglob(key)))
    assert PG_DSN == (_record(connected) or {})["dsn"]

    assert api.delete(f"/v1/harnesses/{connected}").json()["deleted"] is True
    # The file may remain (the store has no delete); what it holds must not.
    assert not asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], key))
    assert PASSWORD not in stored.read_text()


def test_another_org_cannot_see_or_use_a_database(client, api, connected):
    other = {**HEADERS, "x-harness-org": "someone-else"}
    for r in (client.get(f"/v1/harnesses/{connected}", headers=other),
              client.get(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}", headers=other),
              client.post(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}/query", headers=other,
                          json={"sql": "SELECT 1"}),
              client.get(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}/schema", headers=other)):
        _seen.append(r.text)
        assert r.status_code == 404 and r.json()["error"]["code"] == "harness_not_found"
    # And the entry is still there for the org that owns it — a refused read is not a delete.
    assert _db_row(api.get(f"/v1/harnesses/{connected}").json())


# ── what saving the configuration may and may not do ─────────────────────────────

def test_a_client_may_rename_and_disable_the_database(api, connected):
    """An ordinary entry, edited the ordinary way."""
    r = _save_config(api, connected, [{**_entry_of(connected), "name": "shop db",
                                       "enabled": False}])
    assert r.status_code == 200, r.text
    row = _db_row(r.json())
    assert row["name"] == "shop db" and row["enabled"] is False
    # The connection itself is untouched by a rename.
    assert api.get(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}").json()["connection"]["database"] == "shop"


def test_saving_the_configuration_cannot_change_what_is_connected(api, connected):
    """The connection is not on the entry, so there is nothing on it to rewrite. A caller who
    invents fields naming another engine and another host changes exactly nothing."""
    assert _save_config(api, connected, [{**_entry_of(connected), "managed": "database",
                                          "config": {"engine": "mysql", "host": "evil:3306",
                                                     "database": "theirs", "sample_rows": 5000,
                                                     "secret": "vault:harness-mcp-mine"}}]).status_code == 200
    assert api.get(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}").json()["connection"] == {
        "engine": "postgres", "host": "localhost:55432", "database": "shop", "sampleRows": True}
    assert _record(connected)["dsn"] == PG_DSN


def test_the_secret_route_cannot_write_into_the_hosted_namespace(api):
    """The namespace argument, checked: a caller-chosen ref is prefixed, so no ref reaches the
    keys a hosted server's records live under."""
    r = api.put("/v1/mcp-secrets/hosted-chrn-anything-mcp-database", json={"token": "t"})
    assert r.status_code == 200
    assert not r.json()["ref"][len("vault:"):].startswith(app._HOSTED_SECRET_PREFIX)


def test_two_servers_cannot_share_a_name(api, connected):
    """Sanitised, `my server` and `my-server` are one server to every backend: the runner keys
    them by name and the last wins, so half the tool list would vanish with no error."""
    r = _save_config(api, connected, [{"name": "my server", "url": "https://a.example/mcp"},
                                      {"name": "my-server", "url": "https://b.example/mcp"}])
    assert r.status_code == 400 and r.json()["error"]["code"] == "duplicate_server_name"
    # Including against the database, which is a server with a name like any other.
    clash = _save_config(api, connected, [_entry_of(connected),
                                          {"name": "database", "url": "https://c.example/mcp"}])
    assert clash.status_code == 400 and clash.json()["error"]["code"] == "duplicate_server_name"


def test_a_remote_server_still_needs_a_url(api, harness):
    r = _save_config(api, harness, [{"name": "nowhere"}])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_mcp_server"


# ── what a bad connection string gets told ───────────────────────────────────────

def _launch(api, kit, engine, conn):
    return api.post(f"/v1/kits/{kit}/launch",
                    json={"database": {"engine": engine, "connection_string": conn}})


def test_an_unsupported_engine_says_what_is_supported(api, kit):
    r = _launch(api, kit, "snowflake", "snowflake://x/y")
    assert r.status_code == 400
    assert r.json()["error"]["message"] == "This connects to PostgreSQL and MySQL databases."


def test_the_wrong_kind_of_connection_string_is_caught_before_the_driver_is(api, kit):
    r = _launch(api, kit, "postgres", MYSQL_DSN)
    assert r.status_code == 400
    msg = r.json()["error"]["message"]
    assert "PostgreSQL connection string looks like" in msg
    # The example must not be the string they just sent back at them — that is how a password
    # ends up in a UI error banner.
    assert PASSWORD not in msg


def test_a_hosted_instance_refuses_to_be_pointed_at_an_internal_address(api, kit, monkeypatch):
    """Self-hosted, a database on localhost is the operator's own and allowed. Hosted, a customer
    naming an internal host is the same abuse an MCP URL would be, and gets the same answer."""
    monkeypatch.setattr(app, "_pool_is_local", lambda: False)
    r = _launch(api, kit, "postgres", PG_DSN)
    assert r.status_code == 400 and r.json()["error"]["code"] == "unreachable_host"
    # And the button that tests a connection refuses it too, rather than passing what the save
    # would then reject.
    t = api.post("/v1/mcp-test/database", json={"engine": "postgres", "connection_string": PG_DSN})
    assert t.status_code == 400 and t.json()["error"]["code"] == "unreachable_host"


def test_a_connection_string_with_no_database_says_so(api, kit):
    r = _launch(api, kit, "postgres", "postgresql://u:p@host:5432")
    assert r.status_code == 400 and "names no database" in r.json()["error"]["message"]


def test_no_key_to_encrypt_with_is_a_sentence_naming_the_variable(api, kit, monkeypatch):
    """The 501 the operator of a keyless instance must see. Not a 500, and not a plaintext write."""
    monkeypatch.delenv("HR_SECRET_KEY", raising=False)
    monkeypatch.setattr(app.BACKING, "secrets", backing.FileSecretStore(os.path.join(_DATA, "nokey")))
    r = _launch(api, kit, "postgres", PG_DSN)
    assert r.status_code == 501
    err = r.json()["error"]
    assert err["code"] == "secrets_not_configured" and "HR_SECRET_KEY" in err["message"]
    assert not list(Path(_DATA, "nokey").rglob("*")), "a credential was written anyway"


# ── testing a connection before saving one ───────────────────────────────────────

@needs_pg
def test_test_connection_reports_the_tables_it_can_see(api):
    r = api.post("/v1/mcp-test/database", json={"engine": "postgres", "connection_string": PG_DSN})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["database"] == "shop" and body["tableCount"] >= 3
    assert "public.orders" in body["tables"]
    # The org-scoped twin exists so a console testing either kind of server has one auth shape.
    same = api.post(f"/v1/orgs/{ORG}/mcp-test/database",
                    json={"engine": "postgres", "connection_string": PG_DSN})
    assert same.status_code == 200 and same.json()["tables"] == body["tables"]


@needs_pg
def test_a_wrong_password_is_a_usable_message_and_not_a_stack_trace(api):
    r = api.post("/v1/mcp-test/database",
                 json={"engine": "postgres",
                       "connection_string": "postgresql://postgres:wrongpass@localhost:55432/shop"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "password" in body["error"].lower() or "authentication" in body["error"].lower()
    assert "wrongpass" not in body["error"], "the failure echoed the password back"


def test_an_unreachable_host_fails_the_test_rather_than_the_request(api):
    r = api.post("/v1/mcp-test/database",
                 json={"engine": "postgres",
                       "connection_string": f"postgresql://u:{PASSWORD}@127.0.0.1:1/shop"})
    # ok:false with HTTP 200 — "nothing is listening there" is a successful test reporting a
    # failure, and the dialog renders body.error rather than a status code.
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"]
    assert PASSWORD not in r.text


# ── running a query, which is what opening a dashboard does ──────────────────────

def _query(api, hid, sql, **kw):
    return api.post(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/query", json={"sql": sql, **kw})


@needs_pg
def test_a_panel_refresh_returns_columns_and_rows(api, connected):
    r = _query(api, connected,
               "SELECT status, count(*) AS n FROM orders GROUP BY status ORDER BY n DESC")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["status", "n"] and body["row_count"] >= 1
    assert body["truncated"] is False


@needs_mysql
def test_the_same_query_shape_works_on_mysql(api, kit):
    hid = _attach(api, kit, MYSQL_DSN, engine="mysql")["harnessId"]
    r = _query(api, hid, "SELECT name, price FROM products ORDER BY price DESC")
    assert r.status_code == 200, r.text
    assert r.json()["columns"] == ["name", "price"] and r.json()["row_count"] >= 1


@needs_pg
def test_a_write_is_refused_before_it_reaches_the_database(api, connected):
    r = _query(api, connected, "DELETE FROM orders")
    assert r.status_code == 400 and r.json()["error"]["code"] == "sql_refused"
    # The rows are still there.
    n = _query(api, connected, "SELECT count(*) FROM orders")
    assert int(n.json()["rows"][0][0]) > 0


@needs_pg
def test_a_bad_column_comes_back_as_the_databases_own_sentence(api, connected):
    r = _query(api, connected, "SELECT revenu FROM orders")
    assert r.status_code == 502 and r.json()["error"]["code"] == "sql_failed"
    assert "revenu" in r.json()["error"]["message"]


@needs_pg
def test_the_row_cap_is_applied_and_declared(api, connected):
    body = _query(api, connected, "SELECT * FROM orders", max_rows=2).json()
    assert body["row_count"] <= 2 and body["limit_applied"] == 2


@needs_pg
def test_a_caller_cannot_ask_for_more_than_the_engine_allows(api, connected):
    r = _query(api, connected, "SELECT * FROM orders", max_rows=10_000_000)
    assert r.json()["limit_applied"] == sql_plane.DEFAULT_MAX_ROWS


@needs_pg
def test_disabling_the_database_does_not_stop_a_dashboard_refreshing(api, connected):
    """`enabled` decides what the AGENT is handed for a turn. A dashboard refresh is not a turn:
    it is the app's own data plane, authorised by the caller's own key."""
    assert _save_config(api, connected,
                        [{**_entry_of(connected), "enabled": False}]).status_code == 200
    r = _query(api, connected, "SELECT 1 AS one")
    assert r.status_code == 200 and r.json()["columns"] == ["one"]
    assert api.get(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}/schema").status_code == 200
    assert api.get(f"/v1/harnesses/{connected}/servers/{ENTRY_ID}").json()["enabled"] is False


# ── the schema, and the sample-rows switch ───────────────────────────────────────

@needs_pg
def test_sampling_on_shows_rows_and_sampling_off_shows_none(api, kit):
    hid = _attach(api, kit, sample_rows=True)["harnessId"]
    on = api.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/schema").json()
    assert on["sampled"] is True
    assert all("sample" in t for t in on["tables"])
    assert {t["name"] for t in on["tables"]} >= {"customers", "orders", "products"}

    _attach(api, kit, sample_rows=False)
    off = api.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}/schema").json()
    assert off["sampled"] is False
    # The shape is still there; not one value of anyone's data is.
    assert {t["name"] for t in off["tables"]} == {t["name"] for t in on["tables"]}
    assert all("sample" not in t for t in off["tables"])
    assert [c["name"] for c in off["tables"][0]["columns"]]


def test_sample_rows_is_stored_as_a_count_and_not_a_flag(api, kit):
    """The one line that decides how much data leaves the customer's database."""
    hid = _attach(api, kit, sample_rows=True)["harnessId"]
    assert _record(hid)["sample_rows"] == app._DB_SAMPLE_ROWS
    _attach(api, kit, sample_rows=False)
    assert _record(hid)["sample_rows"] == 0


# ── the agent's tool ─────────────────────────────────────────────────────────────

def _rpc(client, token, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    r = client.post("/v1/mcp/database", json=body,
                    headers={"authorization": f"Bearer {token}"} if token else {})
    _seen.append(r.text)
    return r


def _cred(hid: str, sid: str = "sess1") -> str:
    return app._mint_hosted_cred(hid, sid, _key(hid))


def _refused(r) -> bool:
    res = r.json()["result"]
    return res["isError"] is True and "No database is connected" in res["content"][0]["text"]


def test_the_tool_endpoint_refuses_without_a_valid_credential(client, connected):
    assert _rpc(client, None, "tools/list").status_code == 401
    assert _rpc(client, "hrs_not-a-real-token", "tools/list").status_code == 401
    # A token whose signature does not match this instance's key.
    good = _cred(connected)
    forged = good[:-1] + ("a" if good[-1] != "a" else "b")
    assert _rpc(client, forged, "tools/list").status_code == 401


def test_an_expired_credential_is_refused(client, connected, monkeypatch):
    """"and expires" is half the promise. A token minted six hours ago must not work now."""
    monkeypatch.setattr(app, "_BROKER_TTL_S", -1)
    stale = _cred(connected)
    monkeypatch.undo()
    assert _rpc(client, stale, "tools/list").status_code == 401


def test_a_turn_credential_is_scoped_to_one_harness(client, api, connected):
    """The token IS the authorisation. One minted for another harness must not read this one."""
    other = api.post("/v1/harnesses", json={"name": "Other", "base": "claude-code"}).json()["id"]
    tok = app._mint_hosted_cred(other, "sess1", _key(connected))
    assert _refused(_rpc(client, tok, "tools/call",
                         {"name": "query", "arguments": {"sql": "SELECT 1"}}))


def test_a_credential_naming_another_harnesss_record_is_refused(client, api, kit, connected):
    """The binding that replaces a key derived from the harness id: `auth` is a client-writable
    field on an ordinary entry, so a caller can write someone else's ref onto their own entry.
    The record names its harness, and the endpoint refuses a mismatch."""
    thief = api.post("/v1/harnesses", json={"name": "Thief", "base": "claude-code"}).json()["id"]
    stolen = _key(connected)
    assert _save_config(api, thief, [{"id": ENTRY_ID, "name": "database", "url": MCP_URL,
                                      "transport": "http", "auth": f"vault:{stolen}",
                                      "enabled": True}]).status_code == 200
    tok = app._mint_hosted_cred(thief, "sess1", stolen)
    assert _refused(_rpc(client, tok, "tools/call",
                         {"name": "query", "arguments": {"sql": "SELECT 1"}}))
    # And the app's data plane, which is a different authorization path to the same record.
    for r in (api.get(f"/v1/harnesses/{thief}/servers/{ENTRY_ID}"),
              api.post(f"/v1/harnesses/{thief}/servers/{ENTRY_ID}/query", json={"sql": "SELECT 1"})):
        assert r.status_code == 404 and r.json()["error"]["code"] == "database_not_connected"


def test_a_deleted_harness_stops_answering_its_own_turn_credential(client, api, connected):
    """A credential is live for hours; deleting the agent must end its database access now."""
    tok = _cred(connected)
    api.delete(f"/v1/harnesses/{connected}")
    assert _refused(_rpc(client, tok, "tools/call",
                         {"name": "query", "arguments": {"sql": "SELECT 1"}}))


def test_a_disabled_database_is_not_handed_to_the_turn_and_its_endpoint_refuses(client, api, connected):
    """A disabled entry MUST NOT be contacted — and a token minted before it was switched off is
    valid for another six hours, so the endpoint has to refuse too."""
    tok = _cred(connected)
    assert _save_config(api, connected,
                        [{**_entry_of(connected), "enabled": False}]).status_code == 200

    v = asyncio.run(app._harness_vertex(connected))
    mcp, *_ = asyncio.run(app._harness_plugins(connected, ORG, hv=v, sid="sess1"))
    assert [m for m in mcp if m["name"] == "database"] == []

    assert _refused(_rpc(client, tok, "tools/call",
                         {"name": "query", "arguments": {"sql": "SELECT 1"}}))


def test_the_tool_list_is_the_two_things_an_agent_needs(client, connected):
    r = _rpc(client, _cred(connected), "tools/list")
    tools = r.json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["schema", "query"]
    assert all(t["inputSchema"]["type"] == "object" for t in tools)


def test_initialize_and_the_initialized_notification(client, connected):
    tok = _cred(connected)
    r = _rpc(client, tok, "initialize", {"protocolVersion": "2025-06-18"})
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["capabilities"]["tools"] == {}
    # A notification has no id and must be answered with no body.
    n = client.post("/v1/mcp/database", headers={"authorization": f"Bearer {tok}"},
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert n.status_code == 202


@needs_pg
def test_the_agent_can_read_the_schema_and_run_a_select(client, api, kit):
    hid = _attach(api, kit, sample_rows=True)["harnessId"]
    tok = _cred(hid)

    schema = json.loads(_rpc(client, tok, "tools/call",
                             {"name": "schema"}).json()["result"]["content"][0]["text"])
    assert {t["name"] for t in schema["tables"]} >= {"customers", "orders", "products"}
    # And it is told WHICH database it is reading, from the record that owns the connection —
    # the kit's skill tells it to copy this into the dashboard it writes.
    assert schema["connection"] == {"engine": "postgres", "host": "localhost:55432",
                                    "database": "shop", "sampleRows": True}

    out = _rpc(client, tok, "tools/call",
               {"name": "query", "arguments": {"sql": "SELECT count(*) AS n FROM customers"}})
    res = out.json()["result"]
    assert res.get("isError") is not True
    assert json.loads(res["content"][0]["text"])["columns"] == ["n"]


@needs_pg
def test_the_agent_is_told_when_sampling_is_off_rather_than_seeing_an_empty_database(client, api, kit):
    hid = _attach(api, kit, sample_rows=False)["harnessId"]
    schema = json.loads(_rpc(client, _cred(hid), "tools/call",
                             {"name": "schema"}).json()["result"]["content"][0]["text"])
    assert schema["sampled"] is False and "turned off" in schema["note"]
    assert all("sample" not in t for t in schema["tables"])


@needs_pg
def test_the_agent_gets_the_error_back_and_can_fix_it(client, connected):
    tok = _cred(connected)
    bad = _rpc(client, tok, "tools/call",
               {"name": "query", "arguments": {"sql": "SELECT revenu FROM orders"}})
    res = bad.json()["result"]
    assert res["isError"] is True and "revenu" in res["content"][0]["text"]

    refused = _rpc(client, tok, "tools/call",
                   {"name": "query", "arguments": {"sql": "DROP TABLE orders"}})
    assert refused.json()["result"]["isError"] is True
    assert "only select" in refused.json()["result"]["content"][0]["text"].lower()


def test_an_unknown_tool_and_an_unknown_method_are_answered_not_crashed(client, connected):
    tok = _cred(connected)
    r = _rpc(client, tok, "tools/call", {"name": "drop_everything"})
    assert r.json()["result"]["isError"] is True
    m = _rpc(client, tok, "resources/list")
    assert m.json()["error"]["code"] == -32601


# ── how the tool reaches a turn ──────────────────────────────────────────────────

def _plugins(hid: str, sid: str = "sess-42") -> list[dict]:
    v = asyncio.run(app._harness_vertex(hid))
    mcp, *_ = asyncio.run(app._harness_plugins(hid, ORG, hv=v, sid=sid))
    return mcp


def test_a_connected_harness_hands_its_turn_a_database_tool_and_no_credential(connected):
    mcp = _plugins(connected)
    entry = next(m for m in mcp if m["name"] == "database")
    assert entry["url"] == MCP_URL
    # What the sandbox receives is a token, and it resolves back to this harness, this session and
    # this record.
    assert app._verify_hosted_cred(entry["auth"]) == (connected, "sess-42", _key(connected))


def test_no_turn_of_a_connected_harness_carries_a_connection_string(api, connected):
    """The whole plugin list, not one entry: this is the line that says a DSN never reaches a
    sandbox, whatever else the harness has on it."""
    assert _save_config(api, connected,
                        [_entry_of(connected),
                         {"id": "mcp.remote", "name": "remote", "url": "https://mcp.example/mcp",
                          "transport": "http", "auth": "vault:harness-mcp-theirs",
                          "enabled": True}]).status_code == 200
    out = json.dumps(_plugins(connected))
    assert PASSWORD not in out and "localhost:55432" not in out


def test_a_hosted_entry_pointed_elsewhere_hands_that_server_nothing(api, connected):
    """Editing a harness is a strictly weaker permission than knowing the database password, so
    pointing a hosted entry's url at somewhere else must buy exactly nothing."""
    assert _save_config(api, connected,
                        [{**_entry_of(connected), "url": "https://evil.example/mcp"}]).status_code == 200
    entry = next(m for m in _plugins(connected) if m["url"] == "https://evil.example/mcp")
    assert "auth" not in entry
    assert PASSWORD not in json.dumps(entry)


def test_a_remote_entry_naming_a_hosted_record_resolves_to_nothing(connected):
    """The refusal at the funnel every outbound credential passes through, so it holds for callers
    that do not exist yet."""
    assert asyncio.run(app._resolve_mcp_auth(ORG, f"vault:{_key(connected)}")) == ""


def test_a_url_that_only_looks_like_ours_is_not_treated_as_ours(api, connected):
    """`/v1/mcp/../../v1/admin` starts with our prefix and is a different endpoint the moment any
    client normalises it. Hosted is what earns a minted credential and a pass on the SSRF rule;
    neither is owed to a string that merely begins the right way."""
    for path in ("/v1/mcp/../../v1/admin", "/v1/mcp/database/../../admin", "/v1/mcp/"):
        assert app._hosted_mcp_path("https://gateway.example" + path) is None, path
    assert app._hosted_mcp_path(MCP_URL) == "/v1/mcp/database"

    assert _save_config(api, connected, [{**_entry_of(connected),
                                          "url": "https://gateway.example/v1/mcp/../../v1/admin"}
                                         ]).status_code == 200
    entry = next(m for m in _plugins(connected) if "admin" in m["url"])
    assert "auth" not in entry, "a traversal url was handed a minted credential"


def test_an_entry_here_that_names_no_record_is_not_offered(api, harness):
    """A url of ours with a third-party auth is not a server we can serve: minting for it would
    hand out a capability to a record this harness does not have."""
    assert _save_config(api, harness, [{"id": "mcp.fake", "name": "database", "url": MCP_URL,
                                        "transport": "http", "auth": "vault:harness-mcp-theirs",
                                        "enabled": True}]).status_code == 200
    assert _plugins(harness) == []


def test_a_harness_with_no_database_hands_its_turn_no_database_tool(harness):
    assert [m for m in _plugins(harness) if m["name"] == "database"] == []


def test_a_hosted_token_is_not_a_model_broker_token_and_the_reverse(connected):
    """Different audiences, so one lifted out of a sandbox cannot be spent at the other."""
    db_tok = _cred(connected)
    llm_tok = app._mint_turn_cred("sess1", "anthropic")
    assert app._verify_turn_cred(db_tok) is None
    assert app._verify_hosted_cred(llm_tok) is None


# ── a harness connected before the database was an ordinary MCP server ───────────

@pytest.mark.parametrize("shape", [0, 1])
def test_a_harness_connected_under_the_old_shape_still_hands_its_turn_the_tool(api, kit, shape):
    """Converted on the first read that needs it, so an already-connected customer has no
    downtime and nobody has to remember to run anything."""
    hid = _attach(api, kit)["harnessId"]
    _make_legacy(hid, shape=shape)

    entry = next(m for m in _plugins(hid) if m["name"] == "database")
    assert entry["url"] == MCP_URL
    assert app._verify_hosted_cred(entry["auth"]) == (hid, "sess-42", _key(hid))
    # And the console lists it, as an entry indistinguishable from any other server.
    row = _db_row(api.get(f"/v1/harnesses/{hid}").json())
    assert set(row) == {"id", "name", "url", "transport", "auth", "enabled"}


@needs_pg
@pytest.mark.parametrize("shape", [0, 1])
def test_a_harness_connected_under_the_old_shape_still_refreshes_its_dashboard(api, kit, shape):
    hid = _attach(api, kit)["harnessId"]
    _make_legacy(hid, shape=shape)
    r = _query(api, hid, "SELECT 1 AS one")
    assert r.status_code == 200 and r.json()["columns"] == ["one"]


def test_the_old_record_is_dropped_the_first_time_the_harness_is_read(api, kit, capsys):
    hid = _attach(api, kit)["harnessId"]
    _make_legacy(hid, shape=0)
    capsys.readouterr()

    assert api.get(f"/v1/harnesses/{hid}").status_code == 200
    v = _vertex(hid)
    assert not v.get("datasource"), "the old record survived a read"
    assert _entry_of(hid)["auth"].startswith("vault:" + app._HOSTED_SECRET_PREFIX)
    assert "[migrate]" in capsys.readouterr().out, "a drain nobody can count is a drain nobody sees"


def test_a_harness_migrated_on_a_read_is_migrated_only_once(api, kit, capsys):
    hid = _attach(api, kit)["harnessId"]
    _make_legacy(hid, shape=1)
    capsys.readouterr()

    api.get(f"/v1/harnesses/{hid}")
    assert "[migrate]" in capsys.readouterr().out
    api.get(f"/v1/harnesses/{hid}")
    assert "[migrate]" not in capsys.readouterr().out


def test_migration_moves_the_credential_without_reading_it_wrong(api, kit):
    """The payload changes — a bare string becomes a JSON record at a new key — so this is a
    converter. What must not change is the connection string itself, and the old key must not be
    left holding it."""
    hid = _attach(api, kit)["harnessId"]
    old_key = _make_legacy(hid, shape=0)

    assert api.get(f"/v1/harnesses/{hid}").status_code == 200
    rec = _record(hid)
    assert rec["dsn"] == PG_DSN and rec["harness"] == hid and rec["server"] == "database"
    assert rec["host"] == "localhost:55432" and rec["database"] == "shop"
    assert not asyncio.run(app.BACKING.secrets.get(app._tenants_for(ORG)[0], old_key))


def test_disconnecting_a_legacy_harness_scrubs_the_credential(api, kit):
    hid = _attach(api, kit)["harnessId"]
    old_key = _make_legacy(hid, shape=1)
    r = _save_config(api, hid, [])
    assert r.status_code == 200 and _db_row(r.json()) is None
    assert not _vertex(hid).get("datasource")
    tenant = app._tenants_for(ORG)[0]
    assert not asyncio.run(app.BACKING.secrets.get(tenant, old_key))
    assert not asyncio.run(app.BACKING.secrets.get(
        tenant, app._hosted_secret_key(hid, ENTRY_ID)))


# ── launching a kit with a database attached ─────────────────────────────────────

def test_launch_accepts_a_connection_and_a_bad_one_provisions_nothing(api, kit):
    bad = api.post(f"/v1/kits/{kit}/launch",
                   json={"database": {"engine": "postgres",
                                      "connection_string": "not-a-connection-string"}})
    assert bad.status_code == 400
    # Nothing was provisioned on the way to that error.
    assert next(k for k in api.get("/v1/kits").json()["kits"] if k["id"] == kit)["launched"] is False

    ok = api.post(f"/v1/kits/{kit}/launch",
                  json={"database": {"engine": "postgres", "connection_string": PG_DSN,
                                     "sample_rows": False}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["created"] is True
    hid = ok.json()["harnessId"]
    assert api.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}").json()["connection"] == {
        "engine": "postgres", "host": "localhost:55432", "database": "shop", "sampleRows": False}

    # Launched twice: the same Harness, the connection typed the second time applied to it rather
    # than silently dropped, and no orphaned record left behind by the replacement.
    key_before = _key(hid)
    again = api.post(f"/v1/kits/{kit}/launch",
                     json={"database": {"engine": "mysql", "connection_string": MYSQL_DSN}})
    assert again.json()["harnessId"] == hid and again.json()["created"] is False
    assert _key(hid) == key_before
    assert api.get(f"/v1/harnesses/{hid}/servers/{ENTRY_ID}").json()["connection"]["engine"] == "mysql"

    listed = next(k for k in api.get("/v1/kits").json()["kits"] if k["id"] == kit)
    assert listed["database"] == {"engines": ["postgres", "mysql"]}
    # What a launched kit is pointed AT has no successor here: nobody reads their data on this
    # page, and naming it would put connection state back on a harness read.
    assert "connected" not in json.dumps(listed)


def test_a_kit_that_declares_a_database_will_not_launch_without_one(api, kit):
    r = api.post(f"/v1/kits/{kit}/launch", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "connection_required"
    assert next(k for k in api.get("/v1/kits").json()["kits"] if k["id"] == kit)["launched"] is False


def test_the_database_tool_exists_because_the_kit_declares_it(api, kit):
    """The tool belongs to the KIT DEFINITION, not to the credential.

    A dashboard harness whose connection never landed used to carry only the base harness's
    built-in tools and no database tool at all, which reads as "this kit cannot query a database"
    rather than "this kit is not finished being set up". The entry is now provisioned at launch
    the way the media kit's is.
    """
    hid = _launch(api, kit, "postgres", PG_DSN).json()["harnessId"]
    ids = [e["id"] for e in api.get(f"/v1/harnesses/{hid}").json()["mcpServers"]]
    assert ENTRY_ID in ids, "the kit declares a database, so the tool must be listed"


def test_relaunching_restores_a_harness_that_lost_its_database_tool(api, kit):
    """Pressing Launch again is the documented way to reconnect, so it is also the repair.

    A harness created before the entry was provisioned at launch has no database tool and no way
    to get one: the kit card offers Open rather than Launch, and the tool list has no database to
    add. Relaunching has to be able to put it back.
    """
    hid = _launch(api, kit, "postgres", PG_DSN).json()["harnessId"]
    asyncio.run(app._mcp_write(hid, []))          # the shape of an older harness
    assert api.get(f"/v1/harnesses/{hid}").json()["mcpServers"] == []

    again = api.post(f"/v1/kits/{kit}/launch", json={})
    assert again.status_code == 200 and again.json()["created"] is False
    ids = [e["id"] for e in api.get(f"/v1/harnesses/{hid}").json()["mcpServers"]]
    assert ENTRY_ID in ids, "a second Launch must restore the tool"


def test_a_kit_that_reads_no_database_declares_none(api, monkeypatch):
    monkeypatch.setattr(app, "_kits", lambda: {"slides": {"id": "slides", "title": "Slides",
                                                          "app": {"route": "/kits/slides"},
                                                          "harness": {"name": "Slides"}}})
    listed = next(k for k in api.get("/v1/kits").json()["kits"] if k["id"] == "slides")
    assert "database" not in listed
    # …and a connection string offered to it is named rather than quietly dropped.
    r = api.post("/v1/kits/slides/launch",
                 json={"database": {"engine": "postgres", "connection_string": PG_DSN}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "connection_not_used"


def test_a_launched_kits_ordinary_servers_are_stored_verbatim(api, monkeypatch):
    """`harness.mcp_servers` is now exclusively ordinary servers and passes straight through."""
    remote = {"id": "mcp.sis", "name": "sis", "url": "https://sis.example/mcp",
              "transport": "http", "enabled": True}
    monkeypatch.setattr(app, "_kits", lambda: {"k2": {"id": "k2", "title": "K2",
                                                      "app": {"route": "/kits/k2"},
                                                      "harness": {"name": "K2",
                                                                  "mcp_servers": [remote]}}})
    r = api.post("/v1/kits/k2/launch", json={})
    assert r.status_code == 200, r.text
    assert _stored(r.json()["harnessId"]) == [remote]


# ── the whole file, checked at once ──────────────────────────────────────────────

def test_the_password_appears_in_no_response_this_file_produced():
    """Every body recorded above, in one assertion. A new route that leaks the credential fails
    here even if nobody thought to test that route."""
    assert _seen, "nothing was recorded — the recording client stopped being used"
    leaked = [t for t in _seen if PASSWORD in t]
    assert not leaked, f"{len(leaked)} response(s) contained the password: {leaked[:1]}"


def test_the_password_appears_in_nothing_the_gateway_printed(api, kit, capsys):
    """Connect, query, fail, disconnect — then read the logs the container would have written."""
    capsys.readouterr()
    hid = _attach(api, kit)["harnessId"]
    _query(api, hid, "SELECT 1")
    api.post("/v1/mcp-test/database",
             json={"engine": "postgres", "connection_string": f"postgresql://u:{PASSWORD}@127.0.0.1:1/x"})
    _save_config(api, hid, [])
    out = capsys.readouterr()
    assert PASSWORD not in out.out and PASSWORD not in out.err
    # And it did log something identifying, so this is not passing on an empty string.
    assert "[sql]" in out.out
