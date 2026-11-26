"""Voice calls on a harness: the plane's contract, on ports a test owns.

realtime_plane.py knows nothing of the gateway: it is handed a provider and the gateway's ports.
Here the ports are a dict of records, a list of posted usage and a one-holder lock, and Azure's
realtime API is an httpx MockTransport. So what is asserted is what Azure was asked, what the
caller was answered, what was recorded and what was metered. The routes and the real ports are
tested where they are wired.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import pathlib
import sys

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import realtime_plane as rp  # noqa: E402

ORG = "voiceorg"
HID = "har_1"
AZURE_KEY = "SENTINEL-azure-key-never-leaves"
SECRET = "ek_test_client_secret_1"
PROMPT = "You are Neo, the company's orchestrator."
T0 = 1_900_000_000.0
CONNECTIONS = [
    {"name": "OpenRouter", "provider": "openrouter", "config": {"api_key": "sk-or-not-this-one"}},
    {"name": "Azure OpenAI", "provider": "azure-foundry",
     "config": {"base_url": "https://voice-res.openai.azure.com/openai/v1", "api_key": AZURE_KEY}},
]
MCP_TOOLS = [
    {"name": "github__list_pull_requests", "description": "Open pull requests.",
     "inputSchema": {"$schema": "x", "type": "object", "properties": {"state": {"type": "string"}}}},
    {"name": "github__merge_pull_request", "description": "Merge one.", "inputSchema": {"type": "object"}},
    {"name": "not a name the API takes", "description": "", "inputSchema": {}},
]
P = {"org": ORG, "member": "founder@acme.test", "via": "person"}
HV = {"name": "Neo", "org": ORG, "workspace": "ws1", "system_prompt": PROMPT}


class Azure:
    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.status = 200

    def handle(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": "DeploymentNotFound",
                                                               "message": f"no, and {AZURE_KEY}"}})
        sess = json.loads(r.content)["session"]
        return httpx.Response(200, json={"value": SECRET, "expires_at": T0 + 120,
                                         "session": {**sess, "id": "sess_abc", "object": "realtime.session"}})

    def body(self, i: int = -1) -> dict:
        return json.loads(self.calls[i].content)


class World:
    """The ports: records, cards, posted usage, a lock, and a plugs server that lists and runs tools."""

    def __init__(self, monkeypatch):
        self.az, self.now = Azure(), [T0]
        self.records: dict[str, dict] = {}
        self.cards: list[tuple[str, dict]] = []
        self.posted: list[tuple] = []
        self.locks: set[str] = set()
        self.ran: list[tuple] = []
        self.parked: dict | None = None
        self.tool_result: dict = {"content": [{"type": "text", "text": "2 open pull requests"}]}
        self.put_ok, self.lock_fails, self.reach_ok = True, False, True
        self.connections = [dict(c) for c in CONNECTIONS]
        monkeypatch.setattr(rp, "transport", httpx.MockTransport(self.az.handle))
        monkeypatch.setattr(rp, "clock", lambda: self.now[0])

        async def connections():
            return self.connections
        self.provider = rp.AzureRealtime(connections, deployment="gpt-realtime-2-1", transcribe="gpt-4o-transcribe")
        self.svc = rp.Service(self.provider, rp.Ports(
            plugs=self.plugs, put=self.put, get=self.get, card=self.card,
            prefix=lambda org, sid, created: f"{org}/0001_{sid}", reach=self.reach,
            usage=lambda org, metric, amount, **kw: self.posted.append((org, metric, amount, kw)),
            lock=self.lock, unlock=self.unlock, live=self.live))

    async def plugs(self, hid, sid, method, params):
        if method == "tools/list":
            return {"tools": MCP_TOOLS}, None
        self.ran.append((hid, sid, params))
        return self.tool_result, self.parked

    async def put(self, sid, props):
        if not self.put_ok:
            return False
        self.records.setdefault(sid, {}).update(props)
        return True

    async def get(self, sid):
        rec = self.records.get(sid)
        return dict(rec) if rec else None

    async def card(self, sid, rec):
        self.cards.append((sid, rp.card_of(sid, rec)))

    async def reach(self, p, v):
        return self.reach_ok

    async def lock(self, name, ttl):
        if self.lock_fails:
            raise RuntimeError("the claim store is away")
        if name in self.locks:
            return False
        self.locks.add(name)
        return True

    async def unlock(self, name):
        self.locks.discard(name)

    async def live(self):
        return [{**v, "id": k} for k, v in self.records.items() if v.get("rt_open") == "1"]

    def create(self, **body):
        return asyncio.run(self.svc.create(P, HID, HV, rp.SessionBody(**body)))

    def tool(self, sid, name="github__list_pull_requests", arguments="{}", call_id="call_1", p=P):
        return asyncio.run(self.svc.tool_call(p, sid, rp.ToolCallBody(call_id=call_id, name=name, arguments=arguments)))

    def end(self, sid, p=P):
        return asyncio.run(self.svc.end(p, sid))


@pytest.fixture
def w(monkeypatch):
    return World(monkeypatch)


def _refused(fn) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        fn()
    return e.value


def test_the_switch_is_off_unless_the_instance_sets_it(monkeypatch):
    monkeypatch.delenv("HR_REALTIME", raising=False)
    assert importlib.reload(rp).enabled() is False
    monkeypatch.setenv("HR_REALTIME", "1")
    assert importlib.reload(rp).enabled() is True
    monkeypatch.setenv("HR_REALTIME", "0")
    assert importlib.reload(rp).enabled() is False
    monkeypatch.delenv("HR_REALTIME")
    importlib.reload(rp)


def test_a_call_is_minted_with_the_harness_prompt_its_tools_server_vad_and_transcription(w, capsys):
    out = w.create()
    req = w.az.calls[0]
    assert str(req.url) == "https://voice-res.openai.azure.com/openai/v1/realtime/client_secrets"
    assert req.headers["api-key"] == AZURE_KEY and "authorization" not in req.headers
    body = w.az.body()
    assert body["expires_after"] == {"anchor": "created_at", "seconds": 120}
    s = body["session"]
    assert s["type"] == "realtime" and s["model"] == "gpt-realtime-2-1"        # the deployment, not the model id
    assert s["instructions"] == f"{PROMPT}\n\n{rp.CALL_NOTE}"
    assert s["output_modalities"] == ["audio"]
    assert s["audio"]["input"]["turn_detection"] == {"type": "server_vad", "create_response": True,
                                                     "interrupt_response": True}
    assert s["audio"]["input"]["transcription"] == {"model": "gpt-4o-transcribe"}
    assert s["audio"]["output"] == {"voice": "marin"}
    assert [t["name"] for t in s["tools"]] == ["github__list_pull_requests", "github__merge_pull_request"]
    assert "$schema" not in s["tools"][0]["parameters"] and s["tools"][1]["parameters"]["type"] == "object"
    assert s["tool_choice"] == "auto"
    # what the caller is answered: the secret once, where to offer its SDP, and what the call carries
    sid = out["session_id"]
    assert sid.startswith("hrrt_") and out["client_secret"] == SECRET
    assert out["webrtc_url"] == "https://voice-res.openai.azure.com/openai/v1/realtime/calls"
    assert out["deployment"] == "gpt-realtime-2-1" and out["voice"] == "marin" and out["max_minutes"] == 10
    assert out["tools"] == ["github__list_pull_requests", "github__merge_pull_request"] and out["client_tools"] == []
    assert out["expires_at"].endswith("Z")
    # the record: a session of the harness, live, with its deadline; neither the key nor the secret
    rec = w.records[sid]
    assert rec["kind"] == "realtime" and rec["status"] == "live" and rec["rt_open"] == "1"
    assert rec["harness_id"] == HID and rec["tenant"] == ORG and rec["billing_org"] == ORG
    assert rec["person"] == "founder@acme.test" and rec["source"] == "person"
    assert float(rec["rt_deadline"]) == T0 + 600
    everything = json.dumps([w.records, w.cards, out]) + capsys.readouterr().out
    assert AZURE_KEY not in everything
    assert SECRET not in json.dumps([w.records, w.cards]) + capsys.readouterr().out
    assert w.cards[-1][1]["status"] == "live" and w.cards[-1][1]["title"] == "Voice call"


def test_defaults_and_bounds(w):
    assert w.create(voice="Cedar", max_minutes=999)["max_minutes"] == rp.MAX_MINUTES
    assert w.az.body()["session"]["audio"]["output"]["voice"] == "cedar"
    for body, param in (({"voice": "robot"}, "voice"), ({"max_minutes": 0}, "max_minutes"),
                        ({"max_cost_usd": 0}, "max_cost_usd")):
        n = len(w.az.calls)
        assert _refused(lambda: w.create(**body)).status_code == 422, param
        assert len(w.az.calls) == n                       # refused before anything was minted


def test_a_refused_mint_starts_nothing_and_meters_nothing(w):
    w.az.status = 404
    e = _refused(w.create)
    assert e.status_code == 503 and "HTTP 404, DeploymentNotFound" in str(e.detail)
    assert AZURE_KEY not in str(e.detail)                 # Azure's code, never its body
    (rec,) = w.records.values()
    assert rec["status"] == "failed" and rec["rt_open"] == "0"
    w.az.status = 429
    assert _refused(w.create).status_code == 502          # worth trying again
    assert w.posted == [] and asyncio.run(w.svc.sweep()) == 0


def test_a_call_nothing_would_meter_is_not_minted(w):
    w.put_ok = False
    assert _refused(w.create).status_code == 503
    assert w.az.calls == []


def test_no_azure_connection_means_not_set_up(w):
    w.connections = [w.connections[0]]
    e = _refused(w.create)
    assert e.status_code == 503 and str(e.detail) == rp.NOT_SET_UP
    assert w.az.calls == []


def test_the_picker_takes_either_azure_label_with_a_key_on_an_azure_host():
    def conn(**kw):
        cfg = {"base_url": "https://r.openai.azure.com", "api_key": "k", **kw.pop("config", {})}
        return {"name": "a", "provider": "azure-foundry", "config": cfg, **kw}
    assert rp.pick_integration([conn()])
    assert rp.pick_integration([conn(provider="azure")])
    assert rp.pick_integration([conn(config={"base_url": "https://r.services.ai.azure.com/x"})])
    assert not rp.pick_integration([conn(provider="openai")])
    assert not rp.pick_integration([conn(enabled=False)])
    assert not rp.pick_integration([conn(config={"api_key": ""})])
    assert not rp.pick_integration([conn(config={"base_url": "http://r.openai.azure.com"})])        # not https
    assert not rp.pick_integration([conn(config={"base_url": "https://openai.azure.com.evil.test"})])
    assert not rp.pick_integration([conn(config={"base_url": "https://.openai.azure.com"})])
    assert rp.pick_integration([conn(), conn(name="b")], "b")["name"] == "b"
    assert not rp.pick_integration([conn()], "b")


def test_a_tool_call_runs_through_the_plugs_server_as_the_harness(w):
    sid = w.create()["session_id"]
    assert w.tool(sid, arguments='{"state": "open"}') == {"status": "done", "output": "2 open pull requests"}
    assert w.ran == [(HID, sid, {"name": "github__list_pull_requests", "arguments": {"state": "open"}})]


def test_a_tool_that_waits_for_a_person_is_held_and_names_its_request(w):
    sid = w.create()["session_id"]
    w.parked, w.tool_result = {"run": "run.0001"}, {"content": [{"type": "text", "text": "It waits."}]}
    assert w.tool(sid, "github__merge_pull_request") == {"status": "held", "approval_id": "run.0001",
                                                         "says": "It waits."}


def test_a_retried_call_id_is_answered_not_run_again(w):
    sid = w.create()["session_id"]
    first = w.tool(sid, call_id="call_7")
    assert w.tool(sid, call_id="call_7") == first and len(w.ran) == 1
    w.tool(sid, call_id="call_8")
    assert len(w.ran) == 2


def test_refusals(w):
    sid = w.create()["session_id"]
    assert w.tool(sid, "shell__run")["status"] == "refused"                    # not one of the call's tools
    assert w.tool(sid, arguments="[1]") == {"status": "refused", "detail": "The arguments are not a JSON object."}
    w.tool_result = {"isError": True, "content": [{"type": "text", "text": "GitHub said no."}]}
    assert w.tool(sid, call_id="c2") == {"status": "refused", "detail": "GitHub said no."}
    assert _refused(lambda: w.tool("hrrt_" + "0" * 32)).status_code == 404
    assert _refused(lambda: w.tool("sess_other")).status_code == 404


def test_a_session_is_only_its_organizations_and_its_callers_reach(w):
    sid = w.create()["session_id"]
    assert _refused(lambda: w.tool(sid, p={**P, "org": "another"})).status_code == 404
    assert _refused(lambda: w.end(sid, p={**P, "org": "another"})).status_code == 404
    w.reach_ok = False
    assert _refused(lambda: w.tool(sid)).status_code == 404
    assert w.ran == [] and w.posted == []


def test_end_meters_the_minutes_once_on_the_record_and_the_ledger(w):
    sid = w.create()["session_id"]
    w.now[0] = T0 + 150
    assert w.end(sid) == {"minutes": 2.5, "spend_usd": 0.25}
    rec = w.records[sid]
    assert rec["status"] == "done" and rec["rt_open"] == "0" and rec["rt_end_reason"] == "ended"
    assert float(rec["spend_usd"]) == 0.25
    (org, metric, amount, kw), = w.posted
    assert (org, metric, amount) == (ORG, "media.usd", 0.25)
    assert kw["task_id"] == sid and kw["harness_id"] == HID and kw["workspace"] == "ws1"
    assert w.cards[-1][1]["status"] == "done" and w.cards[-1][1]["spend_usd"] == 0.25
    w.now[0] = T0 + 900
    assert w.end(sid) == {"minutes": 2.5, "spend_usd": 0.25} and len(w.posted) == 1     # asked again: the same figures
    assert w.tool(sid) == {"status": "refused", "detail": rp.ENDED_DETAIL}


def test_spend_is_capped_by_max_cost(w):
    sid = w.create(max_cost_usd=0.1)["session_id"]
    w.now[0] = T0 + 300
    assert w.end(sid) == {"minutes": 5.0, "spend_usd": 0.1}


def test_a_call_nobody_ends_ends_at_max_minutes(w):
    sid = w.create(max_minutes=2)["session_id"]
    w.now[0] = T0 + 60
    assert asyncio.run(w.svc.sweep()) == 0                # still inside its time
    w.now[0] = T0 + 3600
    assert asyncio.run(w.svc.sweep()) == 1
    rec = w.records[sid]
    assert rec["rt_end_reason"] == "max_minutes" and float(rec["rt_minutes"]) == 2.0
    assert w.posted[0][2] == 0.2                          # the most it could have run, not the hour
    assert asyncio.run(w.svc.sweep()) == 0 and len(w.posted) == 1


def test_a_tool_call_past_max_minutes_ends_the_call(w):
    sid = w.create(max_minutes=1)["session_id"]
    w.now[0] = T0 + 61
    assert w.tool(sid) == {"status": "refused", "detail": rp.ENDED_DETAIL}
    assert w.ran == [] and w.records[sid]["status"] == "done" and w.posted[0][2] == 0.1


def test_the_meter():
    assert rp.meter(0, 90, 10, 0.10, None) == (1.5, 0.15)
    assert rp.meter(0, 9000, 10, 0.10, None) == (10.0, 1.0)
    assert rp.meter(0, 600, 10, 0.10, 0.5) == (10.0, 0.5)
    assert rp.meter(100, 50, 10, 0.10, None) == (0.0, 0.0)


def test_a_provider_that_knows_what_a_call_used_is_billed_by_that(w, monkeypatch):
    ended = []

    async def usage(ref):
        return rp.Usage(usd=0.4321, detail={"tokens": 1})

    async def end(ref):
        ended.append(ref)
    monkeypatch.setattr(w.provider, "usage", usage)
    monkeypatch.setattr(w.provider, "end", end)
    sid = w.create(max_cost_usd=0.3)["session_id"]
    w.now[0] = T0 + 60
    assert w.end(sid)["spend_usd"] == 0.3                 # the provider's figure, under the call's cap
    assert ended == [{"provider": "azure", "session": "sess_abc"}]


def test_a_call_whose_session_is_deleted_while_open_is_still_metered(w):
    sid = w.create()["session_id"]
    w.now[0] = T0 + 120
    v = {**w.records[sid], "status": "deleted"}
    assert asyncio.run(w.svc.settle(sid, v, "deleted")) == {"minutes": 2.0, "spend_usd": 0.2}
    rec = w.records[sid]
    assert rec["rt_open"] == "0" and rec["rt_end_reason"] == "deleted" and rec["status"] == "live"   # status is the deleter's to write
    assert asyncio.run(w.svc.settle(sid, w.records[sid], "deleted")) is None
    assert len(w.posted) == 1


def test_a_claim_store_that_does_not_answer_ends_nothing_and_bills_nothing(w):
    sid = w.create()["session_id"]
    w.now[0] = T0 + 60
    w.lock_fails = True
    assert _refused(lambda: w.end(sid)).status_code == 503
    assert w.records[sid]["status"] == "live" and w.posted == []
    w.lock_fails = False
    assert w.end(sid) == {"minutes": 1.0, "spend_usd": 0.1}


def test_a_call_another_replica_is_ending_is_not_metered_here(w):
    sid = w.create()["session_id"]
    w.now[0] = T0 + 60
    w.locks.add(f"realtime-end::{sid}")                   # another replica holds the claim
    assert _refused(lambda: w.end(sid)).status_code == 409
    assert w.posted == [] and w.records[sid]["status"] == "live"
    # it finished: this replica's stale read of a live call answers with the figures that one wrote
    stale = {**w.records[sid], "id": sid}
    w.records[sid].update({"status": "done", "rt_minutes": "1.0", "spend_usd": "0.1"})
    assert asyncio.run(w.svc._finish(stale, "ended")) == {"minutes": 1.0, "spend_usd": 0.1}
    assert w.posted == []


def test_page_tools_join_the_call_at_the_mint_and_are_never_run_here(w):
    page = [{"name": "page_create_company", "description": "Create a company.",
             "parameters": {"properties": {"name": {"type": "string"}}}}]
    out = w.create(client_tools=page)
    assert out["client_tools"] == ["page_create_company"]
    names = [t["name"] for t in w.az.body()["session"]["tools"]]
    assert names == ["github__list_pull_requests", "github__merge_pull_request", "page_create_company"]
    assert w.tool(out["session_id"], "page_create_company")["status"] == "refused" and w.ran == []


def test_page_tools_are_checked(w):
    ok = {"name": "page_a", "parameters": {"type": "object"}}
    for bad in ([{"name": "create"}], [ok, ok], [{**ok, "type": "mcp"}], [{**ok, "parameters": {"type": "array"}}],
                [{**ok, "parameters": {"x": "y" * rp.CLIENT_PARAMS_MAX}}],
                [{"name": f"page_{i}"} for i in range(rp.MAX_CLIENT_TOOLS + 1)]):
        assert _refused(lambda: w.create(client_tools=bad)).status_code == 422
    assert w.az.calls == []


def test_input_transcription_follows_its_setting(w):
    w.provider.transcribe = ""
    w.create()
    assert "transcription" not in w.az.body()["session"]["audio"]["input"]
