"""A voice call relayed by a Realtime Harness: the plane's second provider, on ports a test owns.

The harness and Azure are one httpx MockTransport that tells them apart by host. What is asserted is what
the harness was asked and with which key, what Azure was asked and when, what the caller was answered,
what was recorded, what was billed and which words were kept. The gateway's own wiring of this (the
per-call token, the route, the plugs server's address) is tested at the end, on the app.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import pathlib
import sys

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import realtime_plane as rp  # noqa: E402
from test_realtime_plane import AZURE_KEY, HID, HV, MCP_TOOLS, ORG, P, PROMPT, SECRET, T0, World  # noqa: E402

OPERATOR_KEY = "SENTINEL-operator-key"
UPSTREAM_TOKEN = "SENTINEL-upstream-token"
PLUGS_CRED = "SENTINEL-plugs-credential"
CONNECT_TOKEN = "connect-token-for-the-device"
BASE, PUBLIC = "http://rth.internal:8790", "wss://voice.example"
SERVERS = [{"name": "plugs", "url": "http://127.0.0.1:8080/v1/mcp/plugs", "transport": "http",
            "headers": {"Authorization": f"Bearer {PLUGS_CRED}"}}]
TURNS = [
    {"id": "resp_1", "object": "response", "status": "completed",
     "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Any open pull requests?"}]}],
     "output": [{"type": "function_call", "call_id": "c1", "name": "github__list_pull_requests", "arguments": "{}"},
                {"type": "function_call_output", "call_id": "c1", "output": "2 open"},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Two are open."}]}],
     "usage": {"input_tokens": 1000, "output_tokens": 300, "total_tokens": 1300, "cache_read_tokens": 200,
               "input_audio_tokens": 600, "output_audio_tokens": 250}},
    {"id": "resp_2", "object": "response", "status": "cancelled", "input": [], "output": [], "usage": None},
]
# 1000 in: 600 audio, 400 text, 200 cached (counted against the text). 300 out: 250 audio, 50 text.
TURNS_USD = (200 * 4.00 + 600 * 32.00 + 200 * 0.40 + 50 * 24.00 + 250 * 64.00) / 1_000_000


class Harness:
    """The Realtime Harness's API as this gateway uses it."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.create_status, self.turns, self.down = 201, [dict(t) for t in TURNS], False
        self.order: list[str] = []

    def handle(self, r: httpx.Request) -> httpx.Response:
        self.calls.append(r)
        if self.down:
            raise httpx.ConnectError("no route to the harness")
        if r.method == "POST" and r.url.path == "/v1/realtime/sessions":
            self.order.append("create")
            if self.create_status != 201:
                return httpx.Response(self.create_status, json={"error": {"code": "invalid_input",
                                                                           "message": f"no, and {OPERATOR_KEY}"}})
            return httpx.Response(201, json={"id": "hsess_relay1", "object": "session", "kind": "realtime", "status": "connecting",
                                             "connect": {"transport": "websocket", "url": "ws://rth.internal:8790/v1/realtime/connect",
                                                         "token": CONNECT_TOKEN, "expires_at": "2030-03-17T17:47:40Z"}})
        if r.method == "POST" and r.url.path == "/v1/sessions/hsess_relay1/cancel":
            self.order.append("cancel")
            return httpx.Response(200, json={"id": "hsess_relay1", "status": "ended"})
        if r.method == "GET" and r.url.path == "/v1/sessions/hsess_relay1":
            self.order.append("read")
            return httpx.Response(200, json={"id": "hsess_relay1", "status": "ended", "responses": self.turns})
        return httpx.Response(404, json={"error": {"code": "session_not_found"}})

    def body(self, i: int = 0) -> dict:
        return json.loads(self.calls[i].content)


class Relay(World):
    """The plane's ports with the harness as the provider, and Azure behind it."""

    def __init__(self, monkeypatch, base=BASE, public=PUBLIC, key=OPERATOR_KEY):
        super().__init__(monkeypatch)
        self.rth, self.kept = Harness(), []
        self.servers_for: list[tuple] = []
        monkeypatch.setattr(rp, "transport", httpx.MockTransport(
            lambda r: self.rth.handle(r) if r.url.host == "rth.internal" else self.az.handle(r)))
        self.azure = self.provider
        self.provider = rp.HarnessRealtime(self.azure, key=lambda: key, base=base, public=public,
                                           upstream=lambda sid: (f"http://127.0.0.1:8080/v1/realtime/upstream?for={sid}", UPSTREAM_TOKEN))
        ports = self.svc.ports
        ports.servers, ports.turns = self.servers, self.turns
        self.svc = rp.Service(self.provider, ports)

    async def servers(self, hid, sid):
        self.servers_for.append((hid, sid))
        return [dict(s) for s in SERVERS]

    async def turns(self, sid, rec, responses):
        self.kept.append((sid, dict(rec), responses))

    def upstream(self, sid):
        return asyncio.run(self.svc.upstream(sid))


@pytest.fixture
def r(monkeypatch):
    return Relay(monkeypatch)


def _refused(fn) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        fn()
    return e.value


# ── placing the call ────────────────────────────────────────────────────────────────────────────
def test_a_relayed_call_is_created_on_the_harness_with_the_gateways_configuration_and_its_two_credentials(r):
    out = r.create(voice="cedar", max_minutes=7)
    sid = out["session_id"]
    (req,) = r.rth.calls
    assert str(req.url) == BASE + "/v1/realtime/sessions" and req.headers["authorization"] == f"Bearer {OPERATOR_KEY}"
    body = r.rth.body()
    assert body["transport"] == "websocket" and body["model"] == rp.MODEL
    h = body["harness"]
    assert h["id"] == HID and h["name"] == "Neo" and h["voice"] == "cedar" and h["max_call_minutes"] == 7
    assert h["instructions"] == f"{PROMPT}\n\n{rp.CALL_NOTE}" and h["mcp_servers"] == SERVERS
    assert body["upstream"] == {"url": f"http://127.0.0.1:8080/v1/realtime/upstream?for={sid}", "token": UPSTREAM_TOKEN}
    assert r.servers_for == [(HID, sid)]
    assert r.az.calls == []                                   # the provider is asked when the harness connects, not now
    # the caller is answered the harness's connect token and the address a device reaches the harness at
    assert out["transport"] == "websocket" and out["connect_url"] == PUBLIC + "/v1/realtime/connect"
    assert out["client_secret"] == CONNECT_TOKEN and "webrtc_url" not in out
    assert out["tools"] == ["github__list_pull_requests", "github__merge_pull_request"] and out["voice"] == "cedar"
    rec = r.records[sid]
    assert rec["status"] == "live" and rec["rt_provider"] == "harness" and rec["rt_relayed"] == "1"
    assert json.loads(rec["rt_tools"]) == [] and json.loads(rec["rt_ref"]) == {"provider": "harness", "session": "hsess_relay1"}
    kept = json.dumps(out) + json.dumps(r.records) + json.dumps(r.cards, default=str)
    for secret in (OPERATOR_KEY, UPSTREAM_TOKEN, PLUGS_CRED, AZURE_KEY):
        assert secret not in kept
    assert CONNECT_TOKEN not in json.dumps(r.records) + json.dumps(r.cards, default=str)


def test_the_transcription_deployment_is_the_harnesss_to_set_when_the_instance_names_one(r, monkeypatch):
    r.create()
    assert "transcription_model" not in r.rth.body()["harness"]
    monkeypatch.setattr(rp, "TRANSCRIBE", "gpt-4o-transcribe")
    r.create()
    assert r.rth.body(1)["harness"]["transcription_model"] == "gpt-4o-transcribe"


def test_page_tools_cannot_join_a_relayed_call_and_nothing_is_started(r):
    e = _refused(lambda: r.create(client_tools=[{"name": "page_make_company"}]))
    assert e.status_code == 422 and "client_tools" in str(e.detail)
    assert r.records == {} and r.rth.calls == []


@pytest.mark.parametrize("missing", ["base", "public", "key"])
def test_a_harness_the_instance_does_not_name_starts_nothing(monkeypatch, missing):
    r = Relay(monkeypatch, **{missing: ""})
    e = _refused(r.create)
    assert e.status_code == 503 and rp.HARNESS_NOT_SET_UP in str(e.detail)
    (rec,) = r.records.values()
    assert rec["status"] == "failed" and rec["rt_open"] == "0" and r.rth.calls == [] and r.posted == []


def test_a_harness_that_refuses_or_cannot_be_reached_starts_nothing_and_its_words_are_not_passed_on(r):
    r.rth.create_status = 400
    e = _refused(r.create)
    assert e.status_code == 503 and "HTTP 400, invalid_input" in str(e.detail) and OPERATOR_KEY not in str(e.detail)
    r.rth.create_status, r.rth.down = 201, True
    e = _refused(r.create)
    assert e.status_code == 502 and "could not be reached (ConnectError)" in str(e.detail)
    assert [v["status"] for v in r.records.values()] == ["failed", "failed"] and r.posted == []


# ── tools ───────────────────────────────────────────────────────────────────────────────────────
def test_the_tool_calls_route_runs_nothing_for_a_relayed_call(r):
    sid = r.create()["session_id"]
    out = r.tool(sid)
    assert out["status"] == "refused" and "run by the harness" in out["detail"] and r.ran == []


# ── the call's way to the provider ──────────────────────────────────────────────────────────────
def test_the_harness_is_given_a_provider_credential_per_connection_and_only_so_many(r):
    sid = r.create(voice="cedar")["session_id"]
    out = r.upstream(sid)
    assert out == {"client_secret": SECRET, "webrtc_url": "https://voice-res.openai.azure.com/openai/v1/realtime/calls",
                   "deployment": "gpt-realtime-2-1"}
    sess = r.az.body()["session"]
    assert sess["instructions"] == "" and "tools" not in sess       # the harness sets both on its connection
    assert sess["audio"]["output"]["voice"] == "cedar" and r.az.calls[0].headers["api-key"] == AZURE_KEY
    for _ in range(rp.MAX_UPSTREAM_MINTS - 1):
        r.upstream(sid)
    e = _refused(lambda: r.upstream(sid))
    assert e.status_code == 429 and len(r.az.calls) == rp.MAX_UPSTREAM_MINTS
    assert r.records[sid]["rt_upstream"] == str(rp.MAX_UPSTREAM_MINTS)


def test_no_credential_for_a_call_that_is_over_past_its_time_unknown_or_not_relayed(r, monkeypatch):
    sid = r.create(max_minutes=1)["session_id"]
    r.now[0] = T0 + 61
    assert _refused(lambda: r.upstream(sid)).status_code == 403            # past its time
    r.now[0] = T0
    r.end(sid)
    assert _refused(lambda: r.upstream(sid)).status_code == 403            # over
    assert _refused(lambda: r.upstream(rp.SID_PREFIX + "0" * 32)).status_code == 403
    assert _refused(lambda: r.upstream("not an id")).status_code == 403
    # a call placed directly before the instance moved to a harness is still not a relayed one
    sid3 = r.create()["session_id"]
    r.records[sid3]["rt_relayed"] = "0"
    assert _refused(lambda: r.upstream(sid3)).status_code == 403 and r.az.calls == []
    direct = World(monkeypatch)                                           # a call the browser holds with Azure itself
    sid2 = direct.create()["session_id"]
    n = len(direct.az.calls)
    assert _refused(lambda: asyncio.run(direct.svc.upstream(sid2))).status_code == 403
    assert len(direct.az.calls) == n and r.az.calls == []


def test_a_credential_that_cannot_be_counted_or_minted_is_not_given(r):
    sid = r.create()["session_id"]
    r.put_ok = False
    assert _refused(lambda: r.upstream(sid)).status_code == 503 and r.az.calls == []
    r.put_ok, r.az.status = True, 404
    e = _refused(lambda: r.upstream(sid))
    assert e.status_code == 503 and "DeploymentNotFound" in str(e.detail) and AZURE_KEY not in str(e.detail)


# ── the end ─────────────────────────────────────────────────────────────────────────────────────
def test_ending_hangs_up_on_the_harness_first_then_bills_by_its_tokens_and_keeps_what_was_said(r):
    sid = r.create()["session_id"]
    r.rth.order.clear()
    r.now[0] = T0 + 90
    out = r.end(sid)
    assert r.rth.order[0] == "cancel" and set(r.rth.order[1:]) == {"read"}        # hung up before it was asked
    assert out == {"minutes": 1.5, "spend_usd": round(TURNS_USD, 6)} and out["spend_usd"] != 0.15   # not the clock's figure
    rec = r.records[sid]
    assert rec["status"] == "done" and rec["rt_billed_by"] == "tokens" and rec["rt_turns"] == "2"
    assert [(u[0], u[1], u[2]) for u in r.posted] == [(ORG, rp.METRIC, round(TURNS_USD, 6))]
    ((kept_sid, kept_rec, responses),) = r.kept
    assert kept_sid == sid and kept_rec["status"] == "done" and [t["id"] for t in responses] == ["resp_1", "resp_2"]
    assert r.end(sid) == out and len(r.posted) == 1 and len(r.kept) == 1          # once


def test_the_log_says_what_a_call_was_billed_by_and_how_many_turns_it_had(r, capsys):
    sid = r.create()["session_id"]
    r.end(sid)
    assert f"ended sid={sid} reason=ended minutes=0.0 usd={round(TURNS_USD, 6)} billed_by=tokens turns=2" in capsys.readouterr().out


def test_the_tokens_figure_is_under_the_calls_cap(r):
    sid = r.create(max_cost_usd=0.01)["session_id"]
    assert r.end(sid)["spend_usd"] == 0.01


def test_a_call_whose_turns_report_no_usage_is_billed_by_the_clock(r):
    r.rth.turns = [{**TURNS[1]}]
    sid = r.create()["session_id"]
    r.now[0] = T0 + 60
    assert r.end(sid) == {"minutes": 1.0, "spend_usd": 0.1}
    assert r.records[sid]["rt_billed_by"] == "clock" and len(r.kept) == 1


def test_a_call_in_which_nothing_was_said_is_billed_nothing(r):
    r.rth.turns = []
    sid = r.create(max_minutes=1)["session_id"]
    r.now[0] = T0 + 60
    assert r.end(sid) == {"minutes": 1.0, "spend_usd": 0.0}                # not the clock's $0.10
    rec = r.records[sid]
    assert rec["rt_billed_by"] == "tokens" and rec["rt_turns"] == "0" and r.kept == []
    assert [(u[1], u[2]) for u in r.posted] == [(rp.METRIC, 0.0)]


def test_a_record_that_does_not_say_it_has_no_turns_is_not_read_as_a_silent_call(r):
    class NoList(type(r.rth)):
        def handle(self, req):
            out = super().handle(req)
            if req.method == "GET":
                return httpx.Response(200, json={"id": "hsess_relay1", "status": "ended"})     # no `responses` at all
            return out
    r.rth.__class__ = NoList
    sid = r.create()["session_id"]
    r.now[0] = T0 + 60
    assert r.end(sid) == {"minutes": 1.0, "spend_usd": 0.1} and r.records[sid]["rt_billed_by"] == "clock"


def test_a_record_the_harness_will_not_give_is_not_read_as_a_silent_call(r):
    class Gone(type(r.rth)):
        def handle(self, req):
            out = super().handle(req)
            return httpx.Response(500, json={"error": {"code": "server_error"}}) if req.method == "GET" else out
    r.rth.__class__ = Gone
    sid = r.create()["session_id"]
    r.now[0] = T0 + 60
    assert r.end(sid) == {"minutes": 1.0, "spend_usd": 0.1} and r.records[sid]["rt_billed_by"] == "clock" and r.kept == []


def test_a_harness_that_is_away_at_the_end_leaves_a_call_that_is_ended_and_billed_by_the_clock(r, capsys):
    sid = r.create()["session_id"]
    r.rth.down = True
    r.now[0] = T0 + 60
    assert r.end(sid) == {"minutes": 1.0, "spend_usd": 0.1}
    assert r.records[sid]["status"] == "done" and r.records[sid]["rt_billed_by"] == "clock" and r.kept == []
    said = capsys.readouterr().out
    assert "provider end failed" in said and "provider usage or transcript failed" in said and OPERATOR_KEY not in said


def test_a_call_nobody_ended_is_hung_up_at_its_max_minutes(r):
    sid = r.create(max_minutes=1)["session_id"]
    r.rth.order.clear()
    r.now[0] = T0 + 200
    assert asyncio.run(r.svc.sweep()) == 1
    assert r.rth.order[0] == "cancel"                                    # the gateway can hang up a relayed call
    assert r.records[sid]["rt_end_reason"] == "max_minutes" and r.records[sid]["rt_billed_by"] == "tokens"


def test_a_call_whose_session_is_being_deleted_is_hung_up_and_billed_and_its_words_are_not_kept(r):
    sid = r.create()["session_id"]
    r.rth.order.clear()
    out = asyncio.run(r.svc.settle(sid, r.records[sid], "deleted"))
    assert out["spend_usd"] == round(TURNS_USD, 6) and r.rth.order[0] == "cancel"
    assert r.kept == [] and len(r.posted) == 1


def test_words_that_cannot_be_kept_do_not_undo_the_end(r, capsys):
    async def broken(sid, rec, responses):
        raise RuntimeError("store down")
    r.svc.ports.turns = broken
    sid = r.create()["session_id"]
    assert r.end(sid)["spend_usd"] == round(TURNS_USD, 6) and r.records[sid]["status"] == "done"
    assert "transcript not kept" in capsys.readouterr().out


# ── the price of a call's tokens ────────────────────────────────────────────────────────────────
def test_tokens_are_priced_by_kind_and_cached_ones_are_counted_against_the_text_first():
    usd, t = rp.tokens_usd(TURNS)
    assert usd == round(TURNS_USD, 6) and t["input_tokens"] == 1000 and t["output_audio_tokens"] == 250
    # more cached than there is text: the rest were audio
    usd, _ = rp.tokens_usd([{"usage": {"input_tokens": 1000, "input_audio_tokens": 900, "cache_read_tokens": 300, "output_tokens": 0}}])
    assert usd == round((0 * 4.00 + 700 * 32.00 + 300 * 0.40) / 1_000_000, 6)
    # figures a provider could not mean are held to what the totals allow
    usd, _ = rp.tokens_usd([{"usage": {"input_tokens": 100, "input_audio_tokens": 500, "cache_read_tokens": 900,
                                       "output_tokens": 10, "output_audio_tokens": 50}}])
    assert usd == round((100 * 0.40 + 10 * 64.00) / 1_000_000, 6)
    assert rp.tokens_usd([{"usage": {"input_tokens": "x", "output_tokens": -5}}]) == (0.0, {
        "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "input_audio_tokens": 0, "output_audio_tokens": 0})


def test_no_usage_reported_is_no_figure_not_zero():
    assert rp.tokens_usd([]) is None and rp.tokens_usd([{"usage": None}, {"id": "r"}, "junk"]) is None


# ── the instance's choice of provider ───────────────────────────────────────────────────────────
def test_calls_run_between_the_browser_and_azure_unless_the_instance_says_harness():
    saved = {k: os.environ.pop(k, None) for k in ("HR_REALTIME_PROVIDER", "HR_REALTIME_HARNESS_URL", "HR_REALTIME_HARNESS_PUBLIC_URL")}
    try:
        m = importlib.reload(rp)
        assert m.PROVIDER == "azure" and m.HARNESS_URL == "" and m.HARNESS_PUBLIC_URL == ""
        os.environ.update({"HR_REALTIME_PROVIDER": " Harness ", "HR_REALTIME_HARNESS_URL": "http://rth:8790/",
                           "HR_REALTIME_HARNESS_PUBLIC_URL": "wss://voice.example/"})
        m = importlib.reload(rp)
        assert (m.PROVIDER, m.HARNESS_URL, m.HARNESS_PUBLIC_URL) == ("harness", "http://rth:8790", "wss://voice.example")
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        importlib.reload(rp)


def test_the_direct_provider_still_answers_a_webrtc_address_and_runs_tools_here(monkeypatch):
    w = World(monkeypatch)
    out = w.create()
    assert out["transport"] == "webrtc" and out["webrtc_url"] == out["connect_url"]
    rec = w.records[out["session_id"]]
    assert rec["rt_provider"] == "azure" and rec["rt_relayed"] == "0" and len(json.loads(rec["rt_tools"])) == 2
    assert w.tool(out["session_id"])["status"] == "done"
    assert MCP_TOOLS and w.end(out["session_id"])["minutes"] == 0.0 and w.records[out["session_id"]]["rt_billed_by"] == "clock"
