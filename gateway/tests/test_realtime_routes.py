"""Voice calls on a harness: the three routes, on this gateway's own ports.

test_realtime_plane.py tests the plane on ports a test owns. Here the ports are the gateway's: the
record is its graph (a dict here), the tools are its plugs server (a stand-in that records the
request it was sent), the provider is Azure's realtime API as an httpx MockTransport, and the caller
is whoever `_principal` says. So what is asserted is who may place, use and end a call, what the
plugs server and Azure were asked, and that nothing happens while the switch is off.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import sys

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

rp = gw.realtime_plane
ORG = "org-a"
PERSON = {"org": ORG, "member": "ana@example.com", "workspace": "space.a", "workspace_default": False, "via": "person"}
KEY_A = {"org": ORG, "member": "svc-a", "workspace": "space.a", "workspace_default": False, "via": "api_key"}
KEY_B = {"org": ORG, "member": "svc-b", "workspace": "space.b", "workspace_default": False, "via": "api_key"}
OTHER_ORG = {"org": "org-x", "member": "eve", "workspace": "", "workspace_default": False, "via": "api_key"}
AZURE_KEY = "SENTINEL-azure-key-never-leaves"
PLUGS_RECORD = gw._HOSTED_SECRET_PREFIX + "plugs-1"
T0 = 1_900_000_000.0
MCP_TOOLS = [{"name": "github__list_pull_requests", "description": "Open pull requests.",
              "inputSchema": {"type": "object", "properties": {"state": {"type": "string"}}}}]


class _Req:
    def __init__(self, headers=None, path="/", method="POST"):
        self.headers, self.method = headers or {}, method
        self.url = type("U", (), {"path": path})()


def _plugs_entry() -> dict:
    return {"name": "plugs", "url": gw._own_origins()[0] + gw._HOSTED_MCP_PREFIX + gw._PLUGS_SERVER,
            "auth": "vault:" + PLUGS_RECORD}


def _harness(hid, org=ORG, ws="space.a", deleted="0", plugs=True) -> dict:
    return {"id": hid, "org": org, "workspace": ws, "deleted": deleted, "name": "Neo",
            "system_prompt": "You are Neo.", "mcp_servers": json.dumps([_plugs_entry()] if plugs else [])}


class World:
    def __init__(self, monkeypatch):
        self.graph = {"chrn_a": _harness("chrn_a"), "chrn_b": _harness("chrn_b", ws="space.b"),
                      "chrn_gone": _harness("chrn_gone", deleted="1"), "chrn_x": _harness("chrn_x", org="org-x"),
                      "chrn_bare": _harness("chrn_bare", plugs=False)}
        self.now = [T0]
        self.azure: list[httpx.Request] = []
        self.plugs: list[tuple] = []                 # (claims of the credential, the JSON-RPC request)
        self.plugs_answer = lambda req: {"result": ({"tools": MCP_TOOLS} if req["method"] == "tools/list" else
                                                     {"content": [{"type": "text", "text": "2 open pull requests"}]})}
        self.usage: list[tuple] = []
        self.cards: list[dict] = []
        self.spawned: list[str] = []
        self.connections = [{"name": "Azure OpenAI", "provider": "azure-foundry",
                             "config": {"base_url": "https://voice-res.openai.azure.com/openai/v1", "api_key": AZURE_KEY}}]
        self.who = dict(PERSON)
        self._mp = monkeypatch
        mp = monkeypatch

        async def principal(request):
            return dict(self.who)

        async def vertex_get(vid):
            return dict(self.graph[vid]) if vid in self.graph else None

        async def graph_get(vid):
            return dict(self.graph[vid]) if vid in self.graph else None

        async def graph_upsert(label, vid, props, **kw):
            self.graph.setdefault(vid, {}).update({k: v for k, v in props.items()})

        async def graph_find(label, where):
            return [{**v, "id": k} for k, v in self.graph.items() if all(str(v.get(f)) == str(x) for f, x in where.items())]

        async def integrations():
            return self.connections

        async def index_manifest(base, manifest, **kw):
            self.cards.append(dict(manifest))

        async def plugs_mcp(request):
            claims = gw._verify_hosted_cred(gw._broker_token(request))
            req = json.loads(await request.body())
            self.plugs.append((claims, req))
            answer = self.plugs_answer(req)
            if isinstance(answer, Exception):
                raise answer
            return JSONResponse({"jsonrpc": "2.0", "id": req.get("id"), **answer})

        def azure(request: httpx.Request) -> httpx.Response:
            self.azure.append(request)
            return httpx.Response(200, json={"value": "ek_secret_1", "expires_at": self.now[0] + 120,
                                             "session": {"id": "sess_1", "audio": {"output": {"voice": "marin"}}}})

        mp.setattr(gw, "_principal", principal)
        mp.setattr(gw, "_vertex_get", vertex_get)
        mp.setattr(gw, "_harness_vertex", vertex_get)
        mp.setattr(gw.BACKING.graph, "get", graph_get)
        mp.setattr(gw.BACKING.graph, "upsert", graph_upsert)
        mp.setattr(gw.BACKING.graph, "find", graph_find)
        mp.setattr(gw, "_integrations_doc", integrations)
        mp.setattr(gw, "_index_manifest", index_manifest)
        mp.setattr(gw, "plugs_mcp", plugs_mcp)
        mp.setattr(gw, "_report_usage", lambda org, metric, amount, **kw: self.usage.append((org, metric, amount, kw)))
        mp.setattr(gw, "_spawn_forever", lambda name, fn: self.spawned.append(name))
        mp.setattr(gw.control_store, "enabled", lambda: False)
        mp.setattr(gw, "_REALTIME_LOCKS", {})
        mp.setattr(rp, "transport", httpx.MockTransport(azure))
        mp.setattr(rp, "clock", lambda: self.now[0])
        mp.setattr(rp, "ENABLED", True)

    def off(self):
        self._mp.setattr(rp, "ENABLED", False)

    def create(self, hid="chrn_a", **body):
        return asyncio.run(gw.realtime_session_create(hid, _Req(), rp.SessionBody(**body)))

    def tool(self, sid, name="github__list_pull_requests", arguments="{}", call_id="call_1"):
        return asyncio.run(gw.realtime_tool_call(sid, rp.ToolCallBody(call_id=call_id, name=name, arguments=arguments), _Req()))

    def end(self, sid):
        return asyncio.run(gw.realtime_session_end(sid, _Req()))

    def sessions(self) -> dict:
        return {k: v for k, v in self.graph.items() if k.startswith(rp.SID_PREFIX)}


@pytest.fixture
def w(monkeypatch):
    return World(monkeypatch)


def _refused(fn) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        fn()
    return e.value


def _code(e: HTTPException) -> str:
    return str(e.detail.get("code")) if isinstance(e.detail, dict) else ""


# ── the switch ──────────────────────────────────────────────────────────────────────────────────
def test_the_instance_serves_no_call_until_its_operator_turns_them_on(w):
    w.off()
    e = _refused(w.create)
    assert e.status_code == 403 and _code(e) == "realtime_not_enabled" and e.detail["message"] == rp.NOT_OPEN
    e = _refused(lambda: w.tool(rp.SID_PREFIX + "0" * 32))
    assert e.status_code == 403 and _code(e) == "realtime_not_enabled"
    assert w.azure == [] and w.plugs == [] and w.sessions() == {}


def test_the_switch_is_off_as_shipped():
    import importlib
    saved = os.environ.pop("HR_REALTIME", None)
    try:
        assert importlib.reload(rp).enabled() is False
    finally:
        if saved is not None:
            os.environ["HR_REALTIME"] = saved
        importlib.reload(rp)
        rp.error = lambda *a, **k: gw.uhp_error(*a, **k)       # what app.py installed at import


def test_the_sweep_runs_only_where_calls_are_served(w):
    asyncio.run(gw._start_realtime_sweep())
    assert w.spawned == ["realtime-sweep"]
    w.spawned.clear()
    w.off()
    asyncio.run(gw._start_realtime_sweep())
    assert w.spawned == []


def test_a_call_that_started_is_ended_and_metered_after_the_switch_goes_off(w):
    sid = w.create()["session_id"]
    w.now[0] += 90
    w.off()
    out = w.end(sid)
    assert out["minutes"] == pytest.approx(1.5) and out["spend_usd"] == pytest.approx(0.15)
    assert [(u[0], u[1]) for u in w.usage] == [(ORG, rp.METRIC)] and w.usage[0][2] == pytest.approx(0.15)


# ── who may place a call ────────────────────────────────────────────────────────────────────────
def test_a_call_is_placed_on_the_callers_own_harness_and_recorded_before_it_is_minted(w):
    out = w.create()
    sid = out["session_id"]
    assert out["client_secret"] == "ek_secret_1" and out["webrtc_url"] == "https://voice-res.openai.azure.com/openai/v1/realtime/calls"
    assert out["tools"] == ["github__list_pull_requests"]
    rec = w.graph[sid]
    assert rec["tenant"] == ORG and rec["harness_id"] == "chrn_a" and rec["workspace"] == "space.a"
    assert rec["kind"] == rp.KIND and rec["status"] == rp.LIVE and rec["rt_open"] == "1"
    assert rec["member_id"] == "ana@example.com" and rec["acting_for"] == "ana@example.com"
    assert rec["trace_blob"].startswith(f"{ORG}/") and rec["trace_blob"].endswith("_" + sid)
    assert w.cards and w.cards[-1]["session_id"] == sid and w.cards[-1]["title"] == "Voice call"
    body = json.loads(w.azure[0].content)
    assert body["session"]["instructions"].startswith("You are Neo.")
    assert [t["name"] for t in body["session"]["tools"]] == ["github__list_pull_requests"]
    seen = json.dumps(out) + json.dumps(w.graph, default=str) + json.dumps(w.cards, default=str)
    assert AZURE_KEY not in seen and "ek_secret_1" not in json.dumps(w.graph, default=str)


@pytest.mark.parametrize("who, hid", [
    (KEY_B, "chrn_a"),            # another workspace's key
    (KEY_A, "chrn_b"),            # another workspace's harness
    (PERSON, "chrn_x"),           # another organization's harness
    (OTHER_ORG, "chrn_a"),        # another organization's caller
    (PERSON, "chrn_gone"),        # a deleted harness
    (PERSON, "chrn_nope"),        # no such harness
    (PERSON, "claude-code"),      # a built-in base: no record, so no call
], ids=["key-of-b", "harness-of-b", "harness-of-x", "caller-of-x", "deleted", "unknown", "base-id"])
def test_a_harness_that_is_not_the_callers_takes_no_call_and_nothing_is_written(w, who, hid):
    w.who = dict(who)
    e = _refused(lambda: w.create(hid))
    assert e.status_code == 404 and _code(e) == "harness_not_found"
    assert w.azure == [] and w.plugs == [] and w.sessions() == {}


def test_a_caller_with_no_organization_is_refused(w):
    w.who = {"org": "", "member": "x"}
    assert _refused(w.create).status_code == 400
    assert _refused(lambda: w.end(rp.SID_PREFIX + "0" * 32)).status_code == 400


# ── the tools are the harness's plugs, asked as its own CLI asks ────────────────────────────────
def test_the_plugs_server_is_asked_with_a_credential_for_this_harness_this_call_and_its_record(w):
    sid = w.create()["session_id"]
    assert w.tool(sid, arguments='{"state": "open"}') == {"status": "done", "output": "2 open pull requests"}
    (listed_as, listed), (ran_as, ran) = w.plugs
    assert listed_as == ran_as == ("chrn_a", sid, PLUGS_RECORD)
    assert listed["method"] == "tools/list"
    assert ran["method"] == "tools/call" and ran["params"] == {
        "name": "github__list_pull_requests", "arguments": {"state": "open"}}


def test_a_harness_with_no_plugs_starts_a_call_with_no_tools_and_the_server_is_not_asked(w):
    out = w.create("chrn_bare")
    assert out["tools"] == [] and w.plugs == []
    assert "tools" not in json.loads(w.azure[0].content)["session"]
    assert asyncio.run(gw._realtime_plugs("chrn_bare", out["session_id"], "tools/call", {"name": "x"})) == (
        gw._tool_text("No plugins are included on this agent.", True), None)


def test_an_entry_that_names_no_record_this_server_holds_is_not_a_plugs_entry():
    entry = _plugs_entry()
    assert gw._realtime_plugs_key({"mcp_servers": json.dumps([entry])}) == PLUGS_RECORD
    assert gw._realtime_plugs_key({"mcp_servers": json.dumps([{**entry, "auth": "vault:harness-mcp-other"}])}) == ""
    assert gw._realtime_plugs_key({"mcp_servers": json.dumps([{**entry, "auth": "a-literal-token"}])}) == ""
    assert gw._realtime_plugs_key({"mcp_servers": json.dumps([{**entry, "url": "https://elsewhere.example/v1/mcp/plugs"}])}) == ""
    assert gw._realtime_plugs_key(None) == ""


def test_a_plugs_server_that_refuses_or_errs_is_a_call_with_no_tools_and_a_tool_answer_in_words(w, capsys):
    w.plugs_answer = lambda req: HTTPException(401, "invalid or expired turn credential")
    out = w.create()
    assert out["tools"] == [] and "could not be listed" in capsys.readouterr().out
    w.plugs_answer = lambda req: {"error": {"code": -32601, "message": "method not found: tools/call"}}
    result, parked = asyncio.run(gw._realtime_plugs("chrn_a", out["session_id"], "tools/call", {"name": "x"}))
    assert parked is None and result == gw._tool_text("method not found: tools/call", True)


# ── a call is its caller's to use and to end ────────────────────────────────────────────────────
@pytest.mark.parametrize("who", [KEY_B, OTHER_ORG], ids=["another-workspace", "another-organization"])
def test_another_callers_call_is_not_found_and_nothing_runs_or_is_metered(w, who):
    sid = w.create()["session_id"]
    asked = len(w.plugs)
    w.who = dict(who)
    w.now[0] += 60
    for call in (lambda: w.tool(sid), lambda: w.end(sid)):
        e = _refused(call)
        assert e.status_code == 404 and _code(e) == "session_not_found"
    assert len(w.plugs) == asked and w.usage == [] and w.graph[sid]["status"] == rp.LIVE


def test_a_session_that_is_not_a_call_is_not_one_on_these_routes(w):
    w.graph["hsess_a"] = {"tenant": ORG, "workspace": "space.a", "status": "idle", "harness_id": "chrn_a"}
    for call in (lambda: w.tool("hsess_a"), lambda: w.end("hsess_a"), lambda: w.end(rp.SID_PREFIX + "f" * 32)):
        e = _refused(call)
        assert e.status_code == 404 and _code(e) == "session_not_found"
    assert w.plugs == [] and w.usage == []


def test_a_key_of_the_calls_own_workspace_uses_and_ends_it(w):
    sid = w.create()["session_id"]
    w.who = dict(KEY_A)
    assert w.tool(sid)["status"] == "done"
    w.now[0] += 60
    assert w.end(sid)["minutes"] == pytest.approx(1.0)
    assert w.end(sid)["minutes"] == pytest.approx(1.0)                 # asked again: the same figures
    assert len(w.usage) == 1                                           # and metered once


def test_a_calibration_credential_reaches_only_calls_of_the_harness_it_drives():
    held = {"org": ORG, "calibration": {"inner": "chrn_a"}}
    assert asyncio.run(gw._realtime_reach(held, {"harness_id": "chrn_a", "workspace": "space.a"}))
    assert not asyncio.run(gw._realtime_reach(held, {"harness_id": "chrn_b", "workspace": "space.a"}))
    assert not asyncio.run(gw._realtime_reach(KEY_B, {"harness_id": "chrn_a", "workspace": "space.a"}))
    assert asyncio.run(gw._realtime_reach(PERSON, {"harness_id": "chrn_a", "workspace": "space.b"}))   # a person is not narrowed


# ── the provider's connection ───────────────────────────────────────────────────────────────────
def test_an_entra_connection_mints_with_the_gateways_own_sign_in_on_the_deployment_its_row_names(w, monkeypatch):
    asked = []

    async def entra_token(conn):
        asked.append(conn)
        return "entra-token-1"
    monkeypatch.setattr(gw, "_entra_token", entra_token)
    cfg = {"base_url": "https://voice-res.openai.azure.com/openai/v1", "auth": "entra",
           "tenant_id": "t-1", "client_id": "c-1", "client_secret": "SENTINEL-entra-secret"}
    w.connections = [{"name": "Azure", "provider": "azure-foundry", "config": cfg, "rows_v": 2,
                      "models": [{"canonical": rp.MODEL, "provider_id": "gpt-realtime-2-1"}]}]
    out = w.create()
    req = w.azure[0]
    assert req.headers["authorization"] == "Bearer entra-token-1" and "api-key" not in req.headers
    assert asked == [{**cfg, "provider": "azure-foundry"}]
    assert out["deployment"] == "gpt-realtime-2-1" == json.loads(req.content)["session"]["model"]
    assert "SENTINEL-entra-secret" not in json.dumps(out) + json.dumps(w.graph, default=str)


def test_an_instance_with_no_azure_connection_says_so_and_keeps_no_open_call(w):
    w.connections = [{"name": "OpenRouter", "provider": "openrouter", "config": {"api_key": "sk-or"}}]
    e = _refused(w.create)
    assert e.status_code == 503 and e.detail["message"] == rp.NOT_SET_UP
    (rec,) = w.sessions().values()
    assert rec["status"] == "failed" and rec["rt_open"] == "0" and w.usage == []


# ── a call whose session is deleted ─────────────────────────────────────────────────────────────
def _delete(w, sid, monkeypatch):
    """DELETE /v1/sessions/{sid} with its storage steps stood in; what the record said when the tombstone landed."""
    seen = {}

    async def tombstone(label, vid, props, **kw):
        seen.update(w.graph.get(vid) or {})
        w.graph.setdefault(vid, {}).update(props)

    async def nothing(*a, **k):
        return None

    async def strip(vid, v):
        w.graph[vid] = {k: w.graph[vid][k] for k in gw._SESSION_MARKER if w.graph[vid].get(k)}
    monkeypatch.setattr(gw, "_vg_upsert", tombstone)
    monkeypatch.setattr(gw, "_session_purge", nothing)
    monkeypatch.setattr(gw, "_session_strip", strip)
    out = asyncio.run(gw.delete_trace(sid, _Req(method="DELETE")))
    return out, seen


def test_a_call_still_open_when_its_session_is_deleted_is_metered_before_the_record_is_reduced(w, monkeypatch):
    sid = w.create()["session_id"]
    w.now[0] += 90
    out, at_tombstone = _delete(w, sid, monkeypatch)
    assert out["deleted"] is True
    assert [(u[0], u[1]) for u in w.usage] == [(ORG, rp.METRIC)] and w.usage[0][2] == pytest.approx(0.15)
    assert at_tombstone["rt_open"] == "0" and at_tombstone["rt_end_reason"] == "deleted"
    assert w.graph[sid]["status"] == "deleted" and "rt_open" not in w.graph[sid]      # the marker says nothing of a call
    assert asyncio.run(gw.REALTIME.sweep()) == 0 and len(w.usage) == 1                # and nothing is left to find


def test_deleting_a_call_that_was_ended_or_a_session_that_is_no_call_meters_nothing_more(w, monkeypatch):
    sid = w.create()["session_id"]
    w.now[0] += 60
    w.end(sid)
    _delete(w, sid, monkeypatch)
    assert len(w.usage) == 1
    w.graph["sess_text"] = {"tenant": ORG, "workspace": "space.a", "status": "done"}
    _delete(w, "sess_text", monkeypatch)
    assert len(w.usage) == 1 and w.graph["sess_text"]["status"] == "deleted"


# ── the ports ───────────────────────────────────────────────────────────────────────────────────
def test_a_record_that_cannot_be_written_is_answered_not_raised(w, monkeypatch, capsys):
    sid = rp.SID_PREFIX + "a" * 32
    assert asyncio.run(gw._realtime_put(sid, {"status": "live"})) is True
    w.graph[sid]["status"] = "deleted"
    assert asyncio.run(gw._realtime_put(sid, {"status": "done"})) is False          # a tombstone is final
    assert w.graph[sid]["status"] == "deleted"

    async def broken(label, vid, props, **kw):
        raise RuntimeError("store down")
    monkeypatch.setattr(gw.BACKING.graph, "upsert", broken)
    assert asyncio.run(gw._realtime_put(rp.SID_PREFIX + "b" * 32, {"rt_open": "1"})) is False
    assert "could not be written: RuntimeError" in capsys.readouterr().out


def test_the_lock_has_one_holder_until_it_is_let_go_or_its_time_is_up(w, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(gw.time, "time", lambda: clock[0])
    lock = lambda: asyncio.run(gw._realtime_lock("end:x", 30))      # noqa: E731
    assert lock() is True and lock() is False
    asyncio.run(gw._realtime_unlock("end:x"))
    assert lock() is True
    clock[0] += 31
    assert lock() is True


def test_the_control_stores_lock_is_let_go_by_unlock(tmp_path, monkeypatch):
    import control_sqlite
    monkeypatch.setattr(gw.control_store, "_cont", control_sqlite.SqliteContainer(str(tmp_path / "control.db")))
    monkeypatch.setattr(gw.control_store, "_local_mode", lambda: True)
    cs = gw.control_store
    assert asyncio.run(cs.try_lock("realtime-end:x", 60)) is True
    assert asyncio.run(cs.try_lock("realtime-end:x", 60)) is False
    asyncio.run(cs.unlock("realtime-end:x"))
    asyncio.run(cs.unlock("realtime-end:x"))                        # letting go of nothing is not an error
    assert asyncio.run(cs.try_lock("realtime-end:x", 60)) is True


# ── a call relayed by a Realtime Harness: the gateway's own part ────────────────────────────────
def test_an_upstream_token_names_one_call_and_is_no_other_credential(monkeypatch):
    sid = rp.SID_PREFIX + "c" * 32
    tok = gw._mint_realtime_upstream(sid)
    assert tok.startswith("hru_") and gw._verify_realtime_upstream(tok) == sid
    assert gw._verify_realtime_upstream(tok[:-1] + ("0" if tok[-1] != "0" else "1")) == ""      # a changed signature
    head, sig = tok.rsplit(".", 1)
    forged = "hru_" + base64.urlsafe_b64encode(f"upstream|{rp.SID_PREFIX}{'d' * 32}|9999999999".encode()).decode().rstrip("=")
    assert gw._verify_realtime_upstream(f"{forged}.{sig}") == ""                                # another call, the old signature
    assert gw._verify_realtime_upstream("") == "" and gw._verify_realtime_upstream("hru_junk") == ""
    # it is not a plugs credential, and a plugs credential is not it
    assert gw._verify_hosted_cred(tok) is None
    assert gw._verify_realtime_upstream(gw._mint_hosted_cred("chrn_a", sid, PLUGS_RECORD)) == ""
    now = gw.time.time()
    monkeypatch.setattr(gw.time, "time", lambda: now + gw._REALTIME_UPSTREAM_TTL_S + 1)
    assert gw._verify_realtime_upstream(tok) == ""                                              # past a call's longest life
    assert gw._REALTIME_UPSTREAM_TTL_S > rp.MAX_MINUTES * 60


def test_the_upstream_route_answers_only_the_holder_of_a_calls_token(w, monkeypatch):
    asked = []

    async def upstream(sid):
        asked.append(sid)
        return {"client_secret": "ek_x", "webrtc_url": "https://voice-res.openai.azure.com/x", "deployment": "d"}
    monkeypatch.setattr(gw.REALTIME, "upstream", upstream)
    sid = rp.SID_PREFIX + "e" * 32
    for headers in ({}, {"authorization": "Bearer nope"}, {"authorization": "Bearer " + gw._mint_hosted_cred("chrn_a", sid, PLUGS_RECORD)}):
        e = _refused(lambda: asyncio.run(gw.realtime_upstream(_Req(headers))))
        assert e.status_code == 401 and _code(e) == "invalid_credential"
    assert asked == []
    out = asyncio.run(gw.realtime_upstream(_Req({"authorization": "Bearer " + gw._mint_realtime_upstream(sid)})))
    assert asked == [sid] and out["client_secret"] == "ek_x"
    w.off()                                              # a call that started goes on after the switch
    asyncio.run(gw.realtime_upstream(_Req({"authorization": "Bearer " + gw._mint_realtime_upstream(sid)})))
    assert asked == [sid, sid]


def test_a_relayed_calls_tools_are_reached_at_the_plugs_server_with_a_credential_for_this_harness_and_call(w):
    sid = rp.SID_PREFIX + "f" * 32
    (server,) = asyncio.run(gw._realtime_servers("chrn_a", sid))
    assert server["name"] == "plugs" and server["url"] == gw._own_origins()[0] + "/v1/mcp/plugs"
    scheme, cred = server["headers"]["Authorization"].split(" ", 1)
    assert scheme == "Bearer" and gw._verify_hosted_cred(cred) == ("chrn_a", sid, PLUGS_RECORD)
    assert asyncio.run(gw._realtime_servers("chrn_bare", sid)) == []          # a harness with no plugs: no server


def test_the_harness_calls_this_gateway_back_at_the_address_a_runner_beside_it_uses(monkeypatch):
    sid = rp.SID_PREFIX + "a" * 32
    url, tok = gw._realtime_upstream_of(sid)
    assert url == gw._own_origins()[0] + "/v1/realtime/upstream" and gw._verify_realtime_upstream(tok) == sid
    monkeypatch.setattr(gw, "_own_origins", lambda: [])
    with pytest.raises(rp.ProviderError) as e:
        gw._realtime_upstream_of(sid)
    assert e.value.status == 503


def test_as_shipped_calls_run_on_azure_and_the_relay_is_wired_for_when_they_do_not():
    assert rp.PROVIDER == "azure" and gw.REALTIME.provider.name == "azure" and gw.REALTIME.provider.runs_tools is False
    assert gw.REALTIME.ports.servers is not None
    assert "/v1/realtime/upstream" in [r.path for r in gw.app.routes]


# ── what a relayed call said, kept in its session's conversation ────────────────────────────────
CALL_TURNS = [
    {"id": "resp_h1", "status": "completed", "created_at": 1_900_000_010,
     "input": [{"id": "item_1", "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Any open pull requests?"}]}],
     "output": [{"type": "function_call", "call_id": "c1", "name": "github__list_pull_requests", "arguments": "{\"state\":\"open\"}"},
                {"type": "function_call_output", "call_id": "c1", "output": "2 open pull requests"},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Two are open."}],
                 "audio": "AAAA"}],
     "usage": {"input_tokens": 900, "output_tokens": 120, "total_tokens": 1020, "input_audio_tokens": 500}},
    {"id": "resp_h2", "status": "in_progress", "created_at": 1_900_000_005, "input": [], "usage": None,
     "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "And the first one is"}]}]},
    {"id": "resp_h3", "status": "cancelled", "input": [], "output": [], "usage": None},
    "junk",
]


def _keep(w, monkeypatch, turns=CALL_TURNS, sid=None):
    blobs: dict[str, bytes] = {}

    async def blob_put(file_id, data, kb=None):
        blobs[file_id] = data
        return w.blob_ok

    async def blob_get(file_id, kb=None):
        return blobs.get(file_id)

    async def find_strict(label, where=None, **kw):
        return [{**v, "id": k} for k, v in w.graph.items() if all(str(v.get(f)) == str(x) for f, x in (where or {}).items())]
    w.blob_ok = True
    monkeypatch.setattr(gw, "_blob_put", blob_put)
    monkeypatch.setattr(gw, "_blob_get", blob_get)
    monkeypatch.setattr(gw.BACKING.graph, "find_strict", find_strict)
    sid = sid or rp.SID_PREFIX + "9" * 32
    rec = {"tenant": ORG, "member_id": "ana@example.com", "model": "gpt-realtime-2.1", "created_at": str(T0)}
    return sid, rec, blobs


def test_a_relayed_calls_turns_read_in_the_sessions_conversation_as_a_text_tasks_do(w, monkeypatch):
    sid, rec, blobs = _keep(w, monkeypatch)
    asyncio.run(gw._realtime_turns(sid, rec, CALL_TURNS))
    turns = asyncio.run(gw._session_turns_data(sid))["turns"]
    assert len(turns) == 2                                           # the turn with nothing said is not one
    first, second = turns
    assert first["user"] == "Any open pull requests?" and first["assistant"] == "Two are open."
    assert first["tools"] == [{"name": "github__list_pull_requests", "arguments": "{\"state\":\"open\"}"}]
    assert first["status"] == "completed" and first["model"] == "gpt-realtime-2.1"
    assert second["user"] == "" and second["assistant"] == "And the first one is" and second["status"] == "cancelled"
    assert first["created_at"] <= second["created_at"]              # in the order said, whatever the harness's clock says
    stored = [json.loads(b) for b in blobs.values()]
    a = next(x for x in stored if x["metadata"]["realtime_turn"] == "resp_h1")
    b = next(x for x in stored if x["metadata"]["realtime_turn"] == "resp_h2")
    assert a["id"].startswith("resp_") and a["id"] != "resp_h1" and b["previous_response_id"] == a["id"]
    assert a["previous_response_id"] is None and a["_session_id"] == sid and a["_org"] == ORG and a["_backend"] == "realtime"
    assert a["usage"] == {"input_tokens": 900, "output_tokens": 120, "total_tokens": 1020} and b["usage"] is None
    assert "AAAA" not in json.dumps(stored) and "item_1" not in json.dumps(stored)      # words only, no audio, no foreign ids
    idx = [v for v in w.graph.values() if v.get("session_id") == sid]
    assert len(idx) == 2 and {v["org"] for v in idx} == {ORG} and {v["store"] for v in idx} == {"1"}


def test_what_was_said_is_cut_to_a_length_and_a_call_to_a_number_of_turns(w, monkeypatch):
    sid, rec, blobs = _keep(w, monkeypatch)
    monkeypatch.setattr(gw, "_REALTIME_TEXT_MAX", 10)
    monkeypatch.setattr(gw, "_REALTIME_TURNS_MAX", 3)
    long = {"id": "t", "status": "completed", "input": [{"type": "message", "content": "x" * 50}],
            "output": [{"type": "function_call", "call_id": "c", "name": "n", "arguments": {"q": "y" * 50}},
                       {"type": "function_call_output", "call_id": "c", "output": {"rows": "z" * 50}},
                       {"type": "message", "content": [{"type": "output_text", "text": "w" * 50}]},
                       {"type": "reasoning", "summary": "not a thing a call's record keeps"}]}
    asyncio.run(gw._realtime_turns(sid, rec, [long] * 5))
    stored = [json.loads(b) for b in blobs.values()]
    assert len(stored) == 3
    one = stored[0]
    assert one["_input"][0]["content"][0]["text"] == "x" * 10
    assert [o["type"] for o in one["output"]] == ["function_call", "function_call_output", "message"]
    assert len(one["output"][0]["arguments"]) == 10 and len(one["output"][1]["output"]) == 10
    assert one["output"][2]["content"][0]["text"] == "w" * 10


def test_a_turn_that_cannot_be_written_is_an_error_the_plane_logs(w, monkeypatch):
    sid, rec, blobs = _keep(w, monkeypatch)
    w.blob_ok = False
    with pytest.raises(RuntimeError):
        asyncio.run(gw._realtime_turns(sid, rec, CALL_TURNS))
    assert [v for v in w.graph.values() if v.get("session_id") == sid] == []       # no index entry for a record that is not there
    assert gw.REALTIME.ports.turns is not None
