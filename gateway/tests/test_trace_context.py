"""The caller's W3C trace context reaches the runner (#473). `traceparent` and `tracestate` on
POST /v1/responses are kept on the turn and its stored record and passed to the runner's /turn, which
hands them to the CLI and sends a child on every relayed model call. A value that is not W3C syntax
is dropped without refusing the request, `baggage` is never read, and a request without them sends
none."""
import asyncio
import os
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

ORG = "org_trace"
PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
STATE = "congo=t61rcWkgMzE"


@pytest.fixture()
def turns(monkeypatch):
    """POST /v1/responses with the turn's execution stubbed: what it hands _resp_execute, and the
    record it stores."""
    seen: dict = {"stored": []}

    async def principal(request):
        return {"org": ORG, "member": "me@local"}

    async def chain(org, backend, model):
        return [{"backend": backend}]

    async def execute(tr, **kw):
        seen["trace"] = dict(tr.trace)
        return "completed", [], {}

    async def resp_put(rid, rec, *a, **k):
        seen["stored"].append(rec)
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_base_catalog_get", lambda h: {"id": h, "base": "dsh"}, raising=False)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    monkeypatch.setattr(gw, "_resp_execute", execute)
    monkeypatch.setattr(gw, "_resp_put", resp_put)
    api = TestClient(gw.app)

    def post(**headers):
        r = api.post("/v1/responses", json={"input": "hi", "harness_id": "h1"}, headers=headers)
        assert r.status_code == 200, r.text
        return seen, r.json()
    return post


def test_the_callers_context_is_kept_on_the_turn_and_its_record_not_on_the_response(turns):
    seen, out = turns(traceparent=PARENT, tracestate=STATE, baggage="user=alice")
    assert seen["trace"] == {"traceparent": PARENT, "tracestate": STATE}
    assert seen["stored"] and all(rec["_trace"] == seen["trace"] for rec in seen["stored"])
    assert "baggage" not in str(seen["stored"]) and "alice" not in str(seen["stored"])
    assert "_trace" not in out and PARENT not in str(out)


def test_an_invalid_context_is_dropped_and_the_request_still_runs(turns):
    seen, _ = turns(traceparent="00-not-a-trace", tracestate=STATE)
    assert seen["trace"] == {}
    assert all("_trace" not in rec for rec in seen["stored"])


def test_no_context_in_means_none_kept(turns):
    seen, _ = turns()
    assert seen["trace"] == {}
    assert all("_trace" not in rec for rec in seen["stored"])


class _Dispatched(BaseException):
    """Stops _resp_execute at the /turn call: an Exception there is a connection that failed, and
    the chain would move on."""


def _turn_body(monkeypatch, trace: dict) -> dict:
    """The body _resp_execute sends to the runner's /turn, with everything before it stubbed."""
    async def nothing(*a, **k):
        return None

    async def none_of(*a, **k):
        return []

    async def plugins(*a, **k):
        return [], [], [], [], []

    async def env(*a, **k):
        return {}, []

    async def mapped(backend, model):
        return {"name": "conn1", "backend": backend, "provider": "anthropic", "model": "m", "_model_resolved": True}

    async def false(*a, **k):
        return False
    sent: dict = {}

    async def sandbox_json(path, sid, method="POST", body=None, **k):
        sent.update(path=path, body=body)
        raise _Dispatched
    monkeypatch.setattr(gw, "LEASE_MODE", "off")
    monkeypatch.setattr(gw, "_prefix_from_vertex", lambda sid, v: None)
    monkeypatch.setattr(gw, "_vertex_get", nothing)
    monkeypatch.setattr(gw, "_vertex_upsert", nothing)
    monkeypatch.setattr(gw, "_recover_trace_cursor", nothing)
    monkeypatch.setattr(gw, "_hydrate", nothing)
    monkeypatch.setattr(gw, "_harness_plugins", plugins)
    monkeypatch.setattr(gw, "_harness_env", env)
    monkeypatch.setattr(gw, "_harness_plug_types", none_of)
    monkeypatch.setattr(gw, "_mapped_integration_conn", mapped)
    monkeypatch.setattr(gw, "_image_auth", nothing)
    monkeypatch.setattr(gw, "_auth_from_conn", lambda conn, sid, effort: {"api_key": "hr-broker"})
    monkeypatch.setattr(gw, "_turn_cancelled", false)
    monkeypatch.setattr(gw, "_sandbox_json", sandbox_json)
    tr = gw._RespTranslator("resp_trace", "m", None, True, 0.0, sid="hsess_trace")
    tr.trace = trace
    with pytest.raises(_Dispatched):
        asyncio.run(gw._resp_execute(tr, org=ORG, member="me", sid="hsess_trace", backend="claude",
                                     chain=[], prompt="hi", files_in=[], resume=None, emit=nothing,
                                     model_req="m"))
    assert sent["path"] == "/turn"
    return sent["body"]


def test_the_context_is_passed_to_the_runners_turn(monkeypatch):
    body = _turn_body(monkeypatch, {"traceparent": PARENT, "tracestate": STATE})
    assert body["traceparent"] == PARENT and body["tracestate"] == STATE


def test_a_turn_without_context_passes_none(monkeypatch):
    body = _turn_body(monkeypatch, {})
    assert body["traceparent"] is None and body["tracestate"] is None
