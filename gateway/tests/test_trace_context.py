"""The caller's W3C trace context reaches the turn (#473).

A client that traces its own request sends `traceparent` (and often `tracestate`) on
`POST /v1/responses`. The gateway read none of them, so the trace stopped at the gateway's door:
the turn ran with no trace context, and the model calls the runner forwarded carried no trace
either, so the caller's trace never reached the provider's log and the two halves of one request
could not be joined.

Only `traceparent` and `tracestate` are read. `baggage` carries the caller's own data to whoever
reads it, and it never leaves the box. A malformed value is DROPPED, never refused: a broken
tracing header must not fail a turn.
"""
import asyncio
import json
import os
import pathlib
import sys
import time

import pytest
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


ORG = "org_e"

# A W3C traceparent: version 00, a trace id, a span id and the sampled flag.
TRACE_PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_response_in_reach", lambda p, rec: asyncio.sleep(0, True))
    monkeypatch.setattr(gw, "_harness_in_reach", lambda p: asyncio.sleep(0, True))
    return TestClient(gw.app)


# ── the helper ────────────────────────────────────────────────────────────────────────────────

def test_a_valid_traceparent_is_kept():
    assert gw._trace_context(TRACE_PARENT, "") == {"traceparent": TRACE_PARENT}
    # A client that sends the hex in upper case still means the same trace.
    assert gw._trace_context(TRACE_PARENT.upper(), "") == {"traceparent": TRACE_PARENT}


def test_a_malformed_traceparent_is_dropped_and_never_refused():
    """A broken tracing header must not fail a turn: it is dropped, and the helper cannot raise."""
    for bad in ("not-a-traceparent",
                "00-" + "0" * 32 + "-00f067aa0ba902b7-01",      # an all-zero trace-id
                "00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01",   # an all-zero span-id
                "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",  # version ff
                "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7",     # no flags
                ""):
        assert gw._trace_context(bad, "vendor=1") == {}, f"{bad!r} was accepted as a trace context"


def test_a_tracestate_without_a_traceparent_is_dropped():
    """A tracestate is state ABOUT a trace: with no trace there is nothing for it to hang on."""
    assert gw._trace_context("", "vendor=1") == {}
    assert gw._trace_context(None, "vendor=1") == {}


def test_a_malformed_tracestate_is_dropped_but_the_traceparent_stays():
    """The vendor state is the expendable half: a member that does not parse costs the tracestate,
    not the trace."""
    assert gw._trace_context(TRACE_PARENT, "vendor=1") == {"traceparent": TRACE_PARENT, "tracestate": "vendor=1"}
    assert gw._trace_context(TRACE_PARENT, "not a member") == {"traceparent": TRACE_PARENT}
    assert gw._trace_context(TRACE_PARENT, "v=" + "x" * 300) == {"traceparent": TRACE_PARENT}
    assert gw._trace_context(TRACE_PARENT, ",".join(f"v{i}=1" for i in range(40))) == {"traceparent": TRACE_PARENT}


def test_a_tracestate_follows_the_specs_rules_for_its_members():
    """A value may hold a space anywhere but its last character and must not be empty, and only
    one entry per key may exist."""
    assert gw._trace_context(TRACE_PARENT, "vendor=a b") == {"traceparent": TRACE_PARENT,
                                                             "tracestate": "vendor=a b"}
    assert gw._trace_context(TRACE_PARENT, "vendor=") == {"traceparent": TRACE_PARENT}
    assert gw._trace_context(TRACE_PARENT, "vendor=1,vendor=2") == {"traceparent": TRACE_PARENT}
    assert gw._trace_context(TRACE_PARENT, "a=1,b=2") == {"traceparent": TRACE_PARENT,
                                                           "tracestate": "a=1,b=2"}


def test_a_newer_traceparent_version_keeps_its_trace():
    """The spec parses the first 55 characters of a version it does not know and ignores the rest,
    so a forward-compatible header keeps the caller's trace instead of losing it."""
    assert gw._trace_context("01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-extra", "") == {
        "traceparent": "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    # Version `00` has no trailing data, so the extra makes the value invalid.
    assert gw._trace_context(TRACE_PARENT + "-extra", "") == {}


def test_baggage_never_leaves():
    """`baggage` carries the caller's own data to whoever reads it, so it is never read here."""
    ctx = gw._trace_context(TRACE_PARENT, "vendor=1")
    assert "baggage" not in ctx and "baggage" not in json.dumps(ctx)


# ── the turn request the runner receives ──────────────────────────────────────────────────────

def _drive_the_turn_body(monkeypatch, trace_ctx):
    """Run `_resp_execute` with the world's edges stubbed and return the body it handed the
    runner's /turn. The turn is driven end to end so the body is the real one."""
    seen: dict = {}

    async def _sandbox_json(path, sid, method="POST", body=None, **kw):
        if path == "/turn":
            seen["body"] = body
            return {"turn_id": "t1", "status": "running"}
        if path.startswith("/turn/"):
            return {"done": True, "status": "done", "events": [], "n_total": 0}
        return {}

    async def _nothing(*a, **kw):
        return None

    async def _get_connection(org, name):
        return ({"provider": "anthropic", "base_url": "https://proxy.example/v1"}, "tenant-1")

    async def _harness_plugins(*a, **kw):
        return ([], [], [], [], [])

    async def _harness_env(*a, **kw):
        return ({}, [])

    async def _image_auth(*a, **kw):
        return None

    def _auth_from_conn(*a, **kw):
        return {"token": "t", "base_url": "https://proxy.example/v1"}

    async def _turn_cancelled(*a, **kw):
        return False

    async def _collect_produced(*a, **kw):
        return []

    monkeypatch.setattr(gw, "_sandbox_json", _sandbox_json)
    monkeypatch.setattr(gw, "_vertex_get", _nothing)
    monkeypatch.setattr(gw, "_vertex_upsert", _nothing)
    monkeypatch.setattr(gw, "_hydrate", _nothing)
    monkeypatch.setattr(gw, "_harness_plugins", _harness_plugins)
    monkeypatch.setattr(gw, "_harness_env", _harness_env)
    monkeypatch.setattr(gw, "_image_auth", _image_auth)
    monkeypatch.setattr(gw, "_get_connection", _get_connection)
    monkeypatch.setattr(gw, "_auth_from_conn", _auth_from_conn)
    monkeypatch.setattr(gw, "_turn_cancelled", _turn_cancelled)
    monkeypatch.setattr(gw, "_collect_produced", _collect_produced)
    monkeypatch.setattr(gw, "_blob_put", _nothing)
    monkeypatch.setattr(gw, "_checkpoint", _nothing)
    monkeypatch.setattr(gw, "_trace_finalize", _nothing)
    monkeypatch.setattr(gw, "_browser_close", _nothing)
    monkeypatch.setattr(gw, "_recover_trace_cursor", _nothing)
    monkeypatch.setattr(gw, "RESP_POLL_S", 0)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)

    translator = gw._RespTranslator("resp_trace", "m", None, True, time.time())
    status, _produced, rec = asyncio.run(gw._resp_execute(
        translator, org=ORG, member="me@local", sid="sess_trace", backend="claude",
        chain=["anthropic"], prompt="hi", files_in=[], resume=None, emit=lambda ev: asyncio.sleep(0),
        trace_ctx=trace_ctx))
    assert status == "completed", f"the turn did not run: {status} {rec.get('tried')}"
    assert seen.get("body") is not None, "the turn never reached the runner's /turn"
    return seen["body"]


def test_the_trace_context_reaches_the_turn_request(monkeypatch):
    body = _drive_the_turn_body(monkeypatch, {"traceparent": TRACE_PARENT, "tracestate": "vendor=1"})
    assert body.get("traceparent") == TRACE_PARENT, (
        f"the /turn body carries {body.get('traceparent')!r} instead of the caller's traceparent")
    assert body.get("tracestate") == "vendor=1", (
        f"the /turn body carries {body.get('tracestate')!r} instead of the caller's tracestate")


def test_a_turn_with_no_trace_context_carries_none(monkeypatch):
    body = _drive_the_turn_body(monkeypatch, None)
    assert "traceparent" not in body, f"the /turn body carries {body.get('traceparent')!r} with no trace in"
    assert "tracestate" not in body, f"the /turn body carries {body.get('tracestate')!r} with no trace in"


# ── the request path ──────────────────────────────────────────────────────────────────────────

def test_the_request_path_reads_the_header_and_the_turn_record_keeps_it(api, monkeypatch):
    """The whole path, driven through the real endpoint: the header is read, the executor is
    handed it, the turn record keeps it, and the response object the caller gets does not."""
    monkeypatch.setattr(gw, "_base_catalog_get", lambda h: {"id": h, "base": "dsh"}, raising=False)

    async def _chain(org, backend, model):
        return [{"backend": backend}]
    monkeypatch.setattr(gw, "_resolve_chain", _chain)

    captured: dict = {}

    async def _exec(tr, **kw):
        captured.update(kw)
        return "completed", [], {}
    monkeypatch.setattr(gw, "_resp_execute", _exec)

    r = api.post("/v1/responses", json={"input": "hi", "harness_id": "h1"},
                 headers={"traceparent": TRACE_PARENT, "tracestate": "vendor=1",
                          "baggage": "userid=secret"})
    assert r.status_code == 200, r.text
    assert captured.get("trace_ctx") == {"traceparent": TRACE_PARENT, "tracestate": "vendor=1"}, (
        f"the executor was handed {captured.get('trace_ctx')!r}")

    rec = asyncio.run(gw._resp_get(r.json()["id"]))
    assert rec.get("_traceparent") == TRACE_PARENT, (
        f"the turn record carries {rec.get('_traceparent')!r} instead of the caller's traceparent")
    assert rec.get("_tracestate") == "vendor=1", (
        f"the turn record carries {rec.get('_tracestate')!r} instead of the caller's tracestate")
    assert "secret" not in json.dumps(rec), "the caller's baggage reached the turn record"

    public = gw._public_response(rec)
    assert "traceparent" not in public and "_traceparent" not in public, (
        "the trace context leaked into the response object the caller reads")


def test_a_request_with_no_trace_header_keeps_none(api, monkeypatch):
    monkeypatch.setattr(gw, "_base_catalog_get", lambda h: {"id": h, "base": "dsh"}, raising=False)

    async def _chain(org, backend, model):
        return [{"backend": backend}]
    monkeypatch.setattr(gw, "_resolve_chain", _chain)

    captured: dict = {}

    async def _exec(tr, **kw):
        captured.update(kw)
        return "completed", [], {}
    monkeypatch.setattr(gw, "_resp_execute", _exec)

    r = api.post("/v1/responses", json={"input": "hi", "harness_id": "h1"})
    assert r.status_code == 200, r.text
    assert not captured.get("trace_ctx"), f"the executor was handed {captured.get('trace_ctx')!r}"
    rec = asyncio.run(gw._resp_get(r.json()["id"]))
    assert "_traceparent" not in rec and "_tracestate" not in rec, (
        f"the turn record carries {rec.get('_traceparent')!r} with no trace in")


def test_a_malformed_trace_header_does_not_refuse_the_request(api, monkeypatch):
    """A broken tracing header is dropped, never refused: the turn still runs."""
    monkeypatch.setattr(gw, "_base_catalog_get", lambda h: {"id": h, "base": "dsh"}, raising=False)

    async def _chain(org, backend, model):
        return [{"backend": backend}]
    monkeypatch.setattr(gw, "_resolve_chain", _chain)

    captured: dict = {}

    async def _exec(tr, **kw):
        captured.update(kw)
        return "completed", [], {}
    monkeypatch.setattr(gw, "_resp_execute", _exec)

    r = api.post("/v1/responses", json={"input": "hi", "harness_id": "h1"},
                 headers={"traceparent": "not-a-traceparent"})
    assert r.status_code == 200, r.text
    assert not captured.get("trace_ctx"), f"the executor was handed {captured.get('trace_ctx')!r}"
