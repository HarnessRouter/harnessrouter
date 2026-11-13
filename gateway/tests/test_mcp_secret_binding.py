"""A stored MCP secret goes only where it was stored for: the server it was saved for (its host and port) or the
environment, and the workspaces whose harnesses may name it. Every workspace of an organization shares one secret
store, and the runner writes a resolved token into the session's own files, so both are checked: where the secret
goes, and who may name it."""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import tempfile
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)
import backing  # noqa: E402

ORG = "org-bind"
TOKEN = "victim-token-0123456789"
GOOD = "https://mcp.good.example/mcp"
EVIL = "https://evil.example/mcp"
ORG_WIDE = {"org": ORG, "member": "me@local"}
IN_A = {"org": ORG, "member": "key-a", "via": "api_key", "workspace": "ws-a"}
IN_B = {"org": ORG, "member": "key-b", "via": "api_key", "workspace": "ws-b"}


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setenv("HR_SECRET_KEY", "k")
    s = backing.FileSecretStore(tempfile.mkdtemp(prefix="hr-bind-"))
    monkeypatch.setattr(gw.BACKING, "secrets", s)
    monkeypatch.setattr(gw, "_org_tenant", lambda org: org or None)

    async def ok(_url):
        return ""
    monkeypatch.setattr(gw, "_ssrf_check", ok)
    return s


@pytest.fixture()
def caller(monkeypatch):
    who = {"p": dict(ORG_WIDE)}

    async def principal(request):
        return dict(who["p"])
    monkeypatch.setattr(gw, "_principal", principal)

    async def owned(request, org):
        return dict(who["p"])
    monkeypatch.setattr(gw, "_owned_org", owned)
    return who


@pytest.fixture()
def api(store, caller):
    return TestClient(gw.app)


def run(coro):
    return asyncio.run(coro)


def binding(key: str) -> dict | None:
    return run(gw._mcp_binding_get(ORG, key))


def put(api, caller, as_, ref, token=TOKEN, ws_header=None, **body):
    caller["p"] = dict(as_)
    hdrs = {"x-harness-workspace": ws_header} if ws_header else {}
    return api.put(f"/v1/mcp-secrets/{ref}", json={"token": token, **body}, headers=hdrs)


def make(api, caller, as_, servers=(), env=None, ws_header=None):
    """A harness made by `as_`: through the public route, or with a workspace named, the console's route."""
    caller["p"] = dict(as_)
    body = {"name": f"h-{uuid.uuid4().hex[:6]}", "base": "claude-code", "mcp_servers": list(servers)}
    if env is not None:
        body["env"] = env
    if ws_header:
        return api.post(f"/v1/orgs/{ORG}/harnesses", json=body, headers={"x-harness-workspace": ws_header})
    return api.post("/v1/harnesses", json=body)


def server(ref, url=GOOD, **over):
    return {"name": "s", "url": url, "auth": f"vault:harness-mcp-{ref}", **over}


def turn(vertex, hdr=None):
    """The servers a turn hands the runner for this harness record, and the environment it starts with."""
    mcp = run(gw._harness_plugins("chrn_t", ORG, hdr or {}, hv=vertex))[0]
    env, _ = run(gw._harness_env(vertex, ORG, hdr or {}))
    return mcp, env


def vertex(ws, servers=(), env=None):
    return {"id": "chrn_t", "org": ORG, "base": "claude-code", "workspace": ws,
            "mcp_servers": json.dumps(list(servers)), "env": json.dumps(env or {})}


# ── the address a binding names: one parse ─────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("https://GitHub.com/mcp", "https://github.com./x"),
    ("https://x.example", "https://x.example:443/y"),
    ("http://x.example", "http://x.example:80"),
    ("https://bücher.example/m", "https://xn--bcher-kva.example/m"),
])
def test_one_address_one_use(a, b):
    assert gw._mcp_use_of_url(a) == gw._mcp_use_of_url(b) != ""


@pytest.mark.parametrize("a,b", [
    ("http://x.example", "https://x.example"),
    ("https://x.example", "https://x.example:8443"),
    ("https://good.example", "https://good.example.evil.example"),
])
def test_two_addresses_two_uses(a, b):
    assert gw._mcp_use_of_url(a) != gw._mcp_use_of_url(b)


@pytest.mark.parametrize("url", ["https://ex%61mple.com/m", "https://good.example\\@evil.example/m",
                                 "https://good.example@evil.example/m", "https://user:pw@good.example/m",
                                 "https://good.example/m\tx", "https://good.ex\nample/m", "https://good.example /m",
                                 "https://$headers.X-Host/m", "ftp://x.example/m", "x.example/m", "",
                                 "https://a..b.example/m", "https://x.example:0/m"])
def test_an_address_no_binding_can_name(url):
    assert gw._mcp_use_of_url(url) == ""


def test_ipv6_keeps_its_port():
    assert gw._mcp_use_of_url("https://[::1]:8443/m") == "host:::1:8443"
    assert gw._mcp_use_of_url("https://[::1]/m") == "host:::1:443"


def test_only_the_default_workspace_has_aliases():
    for alias in ("", "default", None, f"{ORG}__hr_default"):
        assert gw._mcp_ws(ORG, alias) == "default"
    assert gw._mcp_ws(ORG, "ws-a") == "ws-a"
    assert gw._mcp_ws(ORG, "orgbindhrdefault") != "default"


def test_a_workspace_cant_be_made_with_a_default_id(api, caller):
    caller["p"] = dict(ORG_WIDE)
    for wid in ("default", f"{ORG}__hr_default"):
        r = api.post("/v1/hr/workspaces", json={"name": "x", "id": wid})
        assert r.status_code == 200, r.text
        assert r.json()["id"] in ("default", gw.re.sub(r"[^a-z0-9-]", "", wid))
        assert gw._mcp_ws(ORG, r.json()["id"]) == "default" or "_" not in r.json()["id"]


# ── storing ───────────────────────────────────────────────────────────────────────────────────

def test_a_store_binds_the_callers_workspace_and_the_address(api, caller):
    assert put(api, caller, IN_A, "gh", url=GOOD).status_code == 200
    assert binding("harness-mcp-gh") == {"uses": {gw._mcp_use_of_url(GOOD)}, "workspaces": {"ws-a"}}


def test_a_scoped_key_acts_in_its_own_workspace_whatever_it_names(api, caller):
    assert put(api, caller, IN_A, "gh", ws_header="ws-b").status_code == 200
    assert binding("harness-mcp-gh")["workspaces"] == {"ws-a"}


def test_another_workspaces_secret_cant_be_written_over_or_deleted(api, caller, store):
    assert put(api, caller, IN_A, "github", url=GOOD).status_code == 200
    r = put(api, caller, IN_B, "github", token="attacker", url=EVIL)
    assert r.status_code == 404
    caller["p"] = dict(IN_B)
    assert api.delete("/v1/mcp-secrets/github").status_code == 404
    assert run(store.get(ORG, "harness-mcp-github")) == TOKEN
    assert binding("harness-mcp-github") == {"uses": {gw._mcp_use_of_url(GOOD)}, "workspaces": {"ws-a"}}


def test_a_scoped_key_cant_take_an_unbound_secret(api, caller, store):
    run(store.put(ORG, "harness-mcp-legacy", TOKEN))          # stored before bindings, named by nothing
    assert put(api, caller, IN_B, "legacy", token="mine").status_code == 404
    assert run(store.get(ORG, "harness-mcp-legacy")) == TOKEN


def test_a_name_another_workspace_took_first_never_carries_the_value_there(api, caller):
    assert put(api, caller, IN_B, "github", token="squat").status_code == 200        # ws-b takes a guessable name
    assert put(api, caller, ORG_WIDE, "github", url=GOOD).status_code == 200        # the real token, stored org-wide
    assert binding("harness-mcp-github")["workspaces"] == {"default"}
    assert make(api, caller, IN_B, [server("github")]).status_code == 422
    caller["p"] = dict(IN_B)
    assert api.delete("/v1/mcp-secrets/github").status_code == 404


def test_a_store_names_a_fixed_address_or_nothing(api, caller):
    assert put(api, caller, IN_A, "x", url="https://$headers.X-Host/m").status_code == 422


def test_a_restore_binds_only_what_it_names(api, caller):
    assert put(api, caller, IN_A, "gh", url=GOOD).status_code == 200
    assert put(api, caller, IN_A, "gh", url="https://other.example/m").status_code == 200
    assert binding("harness-mcp-gh")["uses"] == {gw._mcp_use_of_url("https://other.example/m")}
    assert put(api, caller, IN_A, "gh", env=True).status_code == 200
    assert binding("harness-mcp-gh")["uses"] == {gw.USE_ENV}
    assert put(api, caller, IN_A, "gh").status_code == 200            # names nothing: keeps what it had
    assert binding("harness-mcp-gh")["uses"] == {gw.USE_ENV}


def test_the_binding_record_is_out_of_reach(api, caller, store):
    assert put(api, caller, ORG_WIDE, "bind-x", url=GOOD).status_code == 200
    assert run(store.get(ORG, "harness-mcp-bind-x")) == TOKEN
    for ref in ("vault:harness-mcpbind-bind-x", "vault:harness-mcpbind-x"):
        assert run(gw._resolve_mcp_auth(ORG, ref, use=gw._mcp_use_of_url(GOOD), ws="default", any_ws=True)) == ""
    assert gw._mcp_stored_ref("vault:harness-mcpbind-bind-x") == ""
    caller["p"] = dict(ORG_WIDE)
    api.delete("/v1/mcp-secrets/mcpbind-bind-x")
    assert binding("harness-mcp-bind-x") is not None


# ── naming on a harness ──────────────────────────────────────────────────────────────────────

def test_another_workspaces_secret_cant_be_named(api, caller):
    assert put(api, caller, IN_A, "github", url=GOOD).status_code == 200
    r = make(api, caller, IN_B, [server("github")])
    assert r.status_code == 422 and "invalid_secret_ref" in r.text
    r = make(api, caller, IN_B, env={"T": "vault:harness-mcp-github"})
    assert r.status_code == 422
    assert binding("harness-mcp-github")["workspaces"] == {"ws-a"}


def test_a_caller_that_reaches_everything_extends_a_secret_to_its_workspace(api, caller):
    assert put(api, caller, IN_A, "github", url=GOOD).status_code == 200
    assert make(api, caller, ORG_WIDE, [server("github")], ws_header="ws-b").status_code == 200
    assert binding("harness-mcp-github")["workspaces"] == {"ws-a", "ws-b"}


def test_first_naming_binds_and_another_address_is_refused(api, caller):
    assert put(api, caller, IN_A, "k").status_code == 200
    assert binding("harness-mcp-k")["uses"] == set()
    assert make(api, caller, IN_A, [server("k")]).status_code == 200
    assert binding("harness-mcp-k")["uses"] == {gw._mcp_use_of_url(GOOD)}
    r = make(api, caller, IN_A, [server("k", url=EVIL)])
    assert r.status_code == 422 and "secret_other_use" in r.text
    r = make(api, caller, IN_A, env={"T": "vault:harness-mcp-k"})
    assert r.status_code == 422 and "secret_other_use" in r.text
    # stored again for the new address, it goes there, and no longer to the old one
    assert put(api, caller, IN_A, "k", url=EVIL).status_code == 200
    assert make(api, caller, IN_A, [server("k", url=EVIL)]).status_code == 200
    assert make(api, caller, IN_A, [server("k")]).status_code == 422


def test_one_write_cant_bind_a_fresh_secret_to_two_places(api, caller):
    assert put(api, caller, IN_A, "k").status_code == 200
    r = make(api, caller, IN_A, [server("k"), server("k", url=EVIL, name="t")])
    assert r.status_code == 422
    assert binding("harness-mcp-k")["uses"] == set()           # nothing written when one name fails


def test_a_server_whose_host_is_filled_per_task_names_no_stored_secret(api, caller):
    assert put(api, caller, IN_A, "k").status_code == 200
    r = make(api, caller, IN_A, [server("k", url="https://$headers.X-Host/mcp")])
    assert r.status_code == 422 and "invalid_secret_use" in r.text


def test_a_literal_is_sealed_bound_to_its_server_and_workspace(api, caller):
    caller["p"] = dict(IN_A)
    r = make(api, caller, IN_A, [{"name": "s", "url": GOOD, "auth": TOKEN}])
    assert r.status_code == 200, r.text
    ref = (r.json().get("mcp_servers") or r.json().get("mcpServers"))[0]["auth"]
    key = gw._mcp_stored_ref(ref)
    assert key and binding(key) == {"uses": {gw._mcp_use_of_url(GOOD)}, "workspaces": {"ws-a"}}


# ── a turn ───────────────────────────────────────────────────────────────────────────────────

def bound(store, key, uses, wss):
    run(store.put(ORG, key, TOKEN))
    run(store.put(ORG, gw._mcp_bind_key(key), json.dumps({"uses": sorted(uses), "workspaces": sorted(wss)})))


def test_a_turn_gets_the_secret_at_its_server_in_its_workspace(store):
    bound(store, "harness-mcp-gh", {gw._mcp_use_of_url(GOOD)}, {"ws-a"})
    mcp, _ = turn(vertex("ws-a", [server("gh")]))
    assert mcp[0]["auth"] == TOKEN
    mcp, _ = turn(vertex("ws-b", [server("gh")]))                         # another workspace's harness
    assert "auth" not in mcp[0]
    mcp, env = turn(vertex("ws-a", [server("gh", url=EVIL)], {"T": "vault:harness-mcp-gh"}))
    assert "auth" not in mcp[0] and "T" not in env                         # another address, or the environment


def test_an_unbound_secret_resolves_nothing(store):
    run(store.put(ORG, "harness-mcp-old", TOKEN))
    mcp, env = turn(vertex("default", [server("old")], {"T": "vault:harness-mcp-old"}))
    assert "auth" not in mcp[0] and "T" not in env


def test_what_a_request_puts_in_is_a_literal_everywhere(store):
    bound(store, "harness-mcp-gh", {gw._mcp_use_of_url(GOOD), gw.USE_ENV}, {"default"})
    hdr = {"x-tok": "vault:harness-mcp-gh"}
    v = vertex("default", [{"name": "s", "url": GOOD, "auth": "$headers.X-Tok", "headers": {"A": "$headers.X-Tok"}}],
               {"T": "$headers.X-Tok"})
    mcp, env = turn(v, hdr)
    assert mcp[0]["auth"] == "vault:harness-mcp-gh" and mcp[0]["headers"]["A"] == "vault:harness-mcp-gh"
    assert env["T"] == "vault:harness-mcp-gh"
    assert TOKEN not in json.dumps([mcp, env])


def test_an_address_from_the_request_binds_on_the_final_host(store):
    bound(store, "harness-mcp-gh", {gw._mcp_use_of_url(GOOD)}, {"default"})
    v = vertex("default", [server("gh", url="https://$headers.X-Host/mcp")])
    mcp, _ = turn(v, {"x-host": "evil.example"})
    assert mcp[0]["url"] == EVIL and "auth" not in mcp[0]
    mcp, _ = turn(v, {"x-host": "mcp.good.example"})
    assert mcp[0]["url"] == GOOD and mcp[0]["auth"] == TOKEN


# ── the connection test ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def wire(monkeypatch):
    """Every request the test client makes, answered by `answers` (host -> callable)."""
    seen: list[httpx.Request] = []
    answers: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers.get(request.url.host, lambda r: httpx.Response(404))(request)
    monkeypatch.setattr(gw, "_checked_transport", lambda always, limits=None: httpx.MockTransport(handler))
    monkeypatch.setattr(gw, "_checked_clients", {})
    return seen, answers


def _mcp_ok(request):
    body = json.loads(request.content or b"{}")
    if body.get("method") == "tools/list":
        auth = request.headers.get("authorization", "")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2,
                                         "result": {"tools": [{"name": "echo", "description": f"you sent {auth}"}]}})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": {"serverInfo": {"name": "srv"}}})


def test_the_test_never_sends_a_secret_elsewhere_and_never_answers_with_it(api, caller, wire):
    seen, answers = wire
    answers["mcp.good.example"] = _mcp_ok
    answers["evil.example"] = _mcp_ok
    assert put(api, caller, IN_A, "gh", url=GOOD).status_code == 200
    caller["p"] = dict(IN_A)
    r = api.post("/v1/mcp-test", json={"url": EVIL, "auth": "vault:harness-mcp-gh"})
    assert TOKEN not in r.text
    assert all(TOKEN not in (q.headers.get("authorization") or "") for q in seen)
    seen.clear()
    r = api.post("/v1/mcp-test", json={"url": GOOD, "auth": "vault:harness-mcp-gh"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert any(TOKEN in (q.headers.get("authorization") or "") for q in seen)   # the server it was stored for gets it
    assert TOKEN not in r.text                                                     # and an echo of it comes back redacted
    caller["p"] = dict(IN_B)
    seen.clear()
    api.post("/v1/mcp-test", json={"url": GOOD, "auth": "vault:harness-mcp-gh"})
    assert all(TOKEN not in (q.headers.get("authorization") or "") for q in seen)   # not another workspace's key


def test_a_redirect_from_the_bound_server_is_not_followed(api, caller, wire):
    seen, answers = wire
    answers["mcp.good.example"] = lambda r: httpx.Response(307, headers={"location": EVIL})
    answers["evil.example"] = _mcp_ok
    assert put(api, caller, IN_A, "gh", url=GOOD).status_code == 200
    caller["p"] = dict(IN_A)
    api.post("/v1/mcp-test", json={"url": GOOD, "auth": "vault:harness-mcp-gh"})
    assert [q.url.host for q in seen if q.url.host == "evil.example"] == []
    assert gw._checked_http().follow_redirects is False


# ── a setup's copy of a server ──────────────────────────────────────────────────────────────

def test_a_setup_copy_reads_where_bound_and_is_bound_to_its_own(store):
    bound(store, "harness-mcp-gh", {gw._mcp_use_of_url(GOOD)}, {"ws-a"})
    e = server("gh")
    out = run(gw._setup_build_server_copy(ORG, e, src_ws="ws-a", dst_ws="ws-a"))
    key = gw._mcp_stored_ref(out["auth"])
    assert binding(key) == {"uses": {gw._mcp_use_of_url(GOOD)}, "workspaces": {"ws-a"}}
    with pytest.raises(RuntimeError):
        run(gw._setup_build_server_copy(ORG, e, src_ws="ws-b", dst_ws="ws-b"))


# ── the start's binding of what harnesses already name ───────────────────────────────────────

def _graph(monkeypatch, rows):
    async def find_strict(label):
        if isinstance(rows, Exception):
            raise rows
        return rows
    monkeypatch.setattr(gw.BACKING.graph, "find_strict", find_strict)


def test_the_start_binds_what_harnesses_name(store, monkeypatch):
    run(store.put(ORG, "harness-mcp-a", TOKEN))
    run(store.put(ORG, "harness-mcp-e", TOKEN))
    _graph(monkeypatch, [vertex("ws-a", [server("a")], {"T": "vault:harness-mcp-e"}),
                         vertex("ws-b", [server("a")])])
    assert run(gw._mcp_bind_existing())["bound"] == 2
    assert binding("harness-mcp-a") == {"uses": {gw._mcp_use_of_url(GOOD)}, "workspaces": {"ws-a", "ws-b"}}
    assert binding("harness-mcp-e") == {"uses": {gw.USE_ENV}, "workspaces": {"ws-a"}}
    assert run(gw._mcp_bind_existing())["bound"] == 0                        # again: nothing new


def test_the_start_never_widens_a_binding(store, monkeypatch):
    bound(store, "harness-mcp-a", {gw._mcp_use_of_url(GOOD)}, {"ws-a"})
    _graph(monkeypatch, [vertex("ws-b", [server("a", url=EVIL)])])
    run(gw._mcp_bind_existing())
    assert binding("harness-mcp-a") == {"uses": {gw._mcp_use_of_url(GOOD)}, "workspaces": {"ws-a"}}


def test_an_unread_graph_writes_nothing_and_unbound_stays_unresolved(store, monkeypatch):
    run(store.put(ORG, "harness-mcp-a", TOKEN))
    _graph(monkeypatch, RuntimeError("graph down"))
    with pytest.raises(RuntimeError):
        run(gw._mcp_bind_existing())
    assert binding("harness-mcp-a") is None
    mcp, _ = turn(vertex("default", [server("a")]))
    assert "auth" not in mcp[0]


def test_a_secret_named_in_two_places_is_reported_by_place_each_start(store, monkeypatch, capsys):
    run(store.put(ORG, "harness-mcp-a", TOKEN))
    _graph(monkeypatch, [vertex("ws-a", [server("a"), server("a", url=EVIL, name="t")])])
    run(gw._mcp_bind_existing())
    out = capsys.readouterr().out
    assert "mcp.good.example:443" in out and "evil.example:443" in out and gw._mcp_sha8("harness-mcp-a") in out
    assert TOKEN not in out
    run(gw._mcp_bind_existing())
    assert "evil.example:443" in capsys.readouterr().out                      # at every start, until stored again


def test_strict_holds_a_secret_named_in_two_places(store, monkeypatch, capsys):
    monkeypatch.setattr(gw, "_MCP_BIND_STRICT", True)
    run(store.put(ORG, "harness-mcp-a", TOKEN))
    _graph(monkeypatch, [vertex("ws-a", [server("a"), server("a", url=EVIL, name="t")])])
    assert run(gw._mcp_bind_existing())["held"] == 1
    assert binding("harness-mcp-a") is None
    mcp, _ = turn(vertex("ws-a", [server("a")]))
    assert "auth" not in mcp[0]
