"""The conformance checks.

Each one enforces a specific requirement of the specification and names it. Checks assert only what
the specification actually says: where the specification allows a server latitude, the check allows
it too, because a suite that enforces the reference implementation's preferences rather than the
standard's requirements would make every other implementation fail for being different rather than
for being wrong.

Running a real agent task costs money and minutes, so the two tasks this suite needs are run once
and shared by every check that inspects them.
"""
from __future__ import annotations

import base64
import json
import time
import uuid

from .registry import Skip, check

SPEC = "protocol/versions/2026-08-11"


# ── shared fixtures ────────────────────────────────────────────────────────────────────
# Small, deterministic work: the point is to exercise the protocol, not the model.
PROMPT = "Reply with exactly: ok"


def _harness(ctx) -> dict:
    """A harness to run against, chosen once. Prefers one the caller named."""
    if ctx.state.get("harness"):
        return ctx.state["harness"]
    r = ctx.client.get("/v1/harnesses")
    if r.status != 200 or not isinstance(r.json, dict):
        raise Skip(f"cannot list harnesses (HTTP {r.status})")
    items = r.json.get("harnesses") or []
    if not items:
        raise Skip("this server has no configured harnesses, so no task can be run")
    if ctx.harness_id:
        items = [h for h in items if h.get("id") == ctx.harness_id] or items
    ctx.state["harness"] = items[0]
    return items[0]


def _run_blocking(ctx) -> dict:
    """One non-streaming task, run once and cached."""
    if "blocking" in ctx.state:
        return ctx.state["blocking"]
    h = _harness(ctx)
    body = {"input": PROMPT, "metadata": {"harness_id": h["id"]}, "stream": False}
    if ctx.model:
        body["model"] = ctx.model
    r = ctx.client.post("/v1/responses", body=body)
    ctx.state["blocking"] = r
    return r


def _run_stream(ctx) -> list[dict]:
    """One streaming task, run once and cached."""
    if "stream" in ctx.state:
        return ctx.state["stream"]
    h = _harness(ctx)
    body = {"input": PROMPT, "metadata": {"harness_id": h["id"]}, "stream": True}
    if ctx.model:
        body["model"] = ctx.model
    evs = ctx.client.stream("/v1/responses", body, max_seconds=ctx.task_timeout)
    ctx.state["stream"] = evs
    return evs


def _terminal(evs: list[dict]) -> dict | None:
    term = {"response.completed", "response.incomplete", "response.failed"}
    return next((e for e in reversed(evs) if e.get("type") in term), None)


# ══════════════════════════════════════════════════════════════════════════════════════
# Core — discovery and version negotiation
# ══════════════════════════════════════════════════════════════════════════════════════

@check("D-01", "Discovery document is served", "core", f"{SPEC}/lifecycle.md#2-capability-discovery")
def d01(ctx):
    r = ctx.client.get("/v1/uhp", auth=False)
    assert r.status == 200, f"GET /v1/uhp returned HTTP {r.status}, expected 200"
    d = r.json
    assert isinstance(d, dict), "discovery document is not a JSON object"
    ctx.state["discovery"] = d
    return f"conformance_class={d.get('conformance_class')} versions={d.get('versions')}"


@check("D-02", "Discovery is served without authentication", "core",
       f"{SPEC}/lifecycle.md#2-capability-discovery")
def d02(ctx):
    r = ctx.client.get("/v1/uhp", auth=False)
    assert r.status == 200, (
        f"GET /v1/uhp requires authentication (HTTP {r.status}). A client must be able to discover "
        "whether this is a UHP server before deciding what credential to present.")


@check("D-03", "Discovery document matches the schema", "core", f"{SPEC}/schema.md")
def d03(ctx):
    d = ctx.state.get("discovery") or ctx.client.get("/v1/uhp", auth=False).json
    ctx.validate(d, "Discovery")


@check("D-04", "default_version is one of versions", "core",
       f"{SPEC}/lifecycle.md#2-capability-discovery")
def d04(ctx):
    d = ctx.state.get("discovery") or {}
    vs, dv = d.get("versions") or [], d.get("default_version")
    assert dv in vs, f"default_version {dv!r} is not in versions {vs!r}"


@check("D-05", "conformance_class agrees with capabilities", "core",
       f"{SPEC}/lifecycle.md#2-capability-discovery")
def d05(ctx):
    d = ctx.state.get("discovery") or {}
    cls = (d.get("conformance_class") or "").lower()
    caps = d.get("capabilities") or {}
    required = {
        "core": ["streaming", "sessions", "cancellation"],
        "extended": ["streaming", "sessions", "cancellation", "files_input", "files_output",
                     "session_listing"],
        "full": ["streaming", "sessions", "cancellation", "files_input", "files_output",
                 "session_listing", "harness_management"],
    }.get(cls)
    assert required is not None, f"conformance_class {cls!r} is not core, extended or full"
    missing = [c for c in required if not caps.get(c)]
    assert not missing, (
        f"server claims class {cls!r} but reports these capabilities false or absent: {missing}. "
        "A class claim that contradicts the capability list tells a client two different things.")
    return f"class={cls}"


@check("V-01", "UHP-Version header on every response", "core",
       f"{SPEC}/lifecycle.md#1-version-negotiation")
def v01(ctx):
    r = ctx.client.get("/v1/uhp", auth=False)
    got = r.header("uhp-version")
    assert got, "response has no UHP-Version header, so a client cannot tell which contract it got"
    return f"UHP-Version: {got}"


@check("V-02", "A supported version is honoured", "core",
       f"{SPEC}/lifecycle.md#1-version-negotiation")
def v02(ctx):
    d = ctx.state.get("discovery") or {}
    ver = (d.get("versions") or [None])[0]
    if not ver:
        raise Skip("discovery did not advertise any version")
    r = ctx.client.get("/v1/uhp", auth=False, headers={"UHP-Version": ver})
    assert r.status == 200, f"requesting the advertised version {ver!r} returned HTTP {r.status}"
    assert r.header("uhp-version") == ver, (
        f"asked for {ver!r}, server served {r.header('uhp-version')!r}")


@check("V-03", "An unsupported version is refused, not silently substituted", "core",
       f"{SPEC}/lifecycle.md#1-version-negotiation")
def v03(ctx):
    r = ctx.client.get("/v1/uhp", auth=False, headers={"UHP-Version": "1999-01-01"})
    assert r.status == 400, (
        f"requesting an unsupported version returned HTTP {r.status}, expected 400. Serving a "
        "different version silently gives the client a body it may not be able to parse.")
    err = (r.json or {}).get("error") or {}
    assert err.get("code") == "unsupported_protocol_version", (
        f"expected code 'unsupported_protocol_version', got {err.get('code')!r}")
    supported = ((err.get("detail") or {}).get("supported")) or []
    assert supported, "error detail does not list the versions the server does support"
    return f"supported={supported}"


# ══════════════════════════════════════════════════════════════════════════════════════
# Core — authentication and the error envelope
# ══════════════════════════════════════════════════════════════════════════════════════

@check("A-01", "Authenticated endpoints reject an absent credential", "core",
       f"{SPEC}/architecture.md#5-authentication")
def a01(ctx):
    r = ctx.client.get("/v1/harnesses", auth=False)
    assert r.status == 401, f"GET /v1/harnesses without a token returned HTTP {r.status}, expected 401"


@check("A-02", "Authenticated endpoints reject an invalid credential", "core",
       f"{SPEC}/architecture.md#5-authentication")
def a02(ctx):
    r = ctx.client.get("/v1/harnesses", headers={"authorization": "Bearer uhp-conformance-not-a-key"})
    assert r.status == 401, f"an unknown token returned HTTP {r.status}, expected 401"
    err = (r.json or {}).get("error") or {}
    assert err.get("type") == "authentication_error", (
        f"expected error.type 'authentication_error', got {err.get('type')!r}")


@check("E-01", "Errors use the structured envelope", "core", f"{SPEC}/errors.md#1-the-error-envelope")
def e01(ctx):
    r = ctx.client.get("/v1/harnesses/chrn_uhpconformancenosuchharness00")
    assert r.status == 404, f"unknown harness returned HTTP {r.status}, expected 404"
    ctx.validate(r.json, "ErrorEnvelope")
    err = r.json["error"]
    for f in ("type", "code", "message"):
        assert err.get(f), f"error.{f} is missing or empty"
    return f"code={err['code']}"


@check("E-02", "Unknown harness reports harness_not_found", "core", f"{SPEC}/errors.md#31-request-and-routing")
def e02(ctx):
    r = ctx.client.get("/v1/harnesses/chrn_uhpconformancenosuchharness00")
    err = (r.json or {}).get("error") or {}
    assert err.get("code") == "harness_not_found", (
        f"expected code 'harness_not_found', got {err.get('code')!r}")


@check("E-03", "Unknown response reports response_not_found", "core", f"{SPEC}/errors.md#31-request-and-routing")
def e03(ctx):
    r = ctx.client.get("/v1/responses/resp_uhpconformancenosuchresponse")
    assert r.status == 404, f"unknown response returned HTTP {r.status}, expected 404"
    err = (r.json or {}).get("error") or {}
    assert err.get("code") == "response_not_found", (
        f"expected code 'response_not_found', got {err.get('code')!r}")


@check("E-04", "Error messages carry no stack traces", "core", f"{SPEC}/errors.md#1-the-error-envelope")
def e04(ctx):
    r = ctx.client.get("/v1/harnesses/chrn_uhpconformancenosuchharness00")
    msg = ((r.json or {}).get("error") or {}).get("message") or ""
    for leak in ("Traceback", "File \"/", "  at ", "\n  File"):
        assert leak not in msg, f"error.message leaks internals ({leak!r} present): {msg[:120]!r}"


# ══════════════════════════════════════════════════════════════════════════════════════
# Core — harnesses and models
# ══════════════════════════════════════════════════════════════════════════════════════

@check("H-01", "Harness list is served and well formed", "core", f"{SPEC}/harnesses.md#1-discovering-harnesses")
def h01(ctx):
    r = ctx.client.get("/v1/harnesses")
    assert r.status == 200, f"GET /v1/harnesses returned HTTP {r.status}"
    assert isinstance(r.json, dict) and isinstance(r.json.get("harnesses"), list), (
        "response has no `harnesses` array")
    for h in r.json["harnesses"]:
        ctx.validate(h, "Harness")
    return f"{len(r.json['harnesses'])} harness(es)"


@check("H-02", "A harness can be fetched by id", "core", f"{SPEC}/harnesses.md#1-discovering-harnesses")
def h02(ctx):
    h = _harness(ctx)
    r = ctx.client.get(f"/v1/harnesses/{h['id']}")
    assert r.status == 200, f"GET /v1/harnesses/{{id}} returned HTTP {r.status}"
    assert r.json.get("id") == h["id"], "returned harness has a different id than requested"
    ctx.validate(r.json, "Harness")


@check("H-03", "Model catalogue is served and availability is a boolean", "core",
       f"{SPEC}/harnesses.md#3-models")
def h03(ctx):
    r = ctx.client.get("/v1/models")
    assert r.status == 200, f"GET /v1/models returned HTTP {r.status}"
    ctx.validate(r.json, "ModelCatalog")
    n = avail = 0
    for b in (r.json.get("backends") or {}).values():
        for m in b.get("models") or []:
            n += 1
            assert isinstance(m.get("available"), bool), (
                f"model {m.get('id')!r} has non-boolean `available` {m.get('available')!r}")
            avail += bool(m["available"])
    return f"{avail}/{n} models available"


@check("H-04", "Per-harness model list is served", "core", f"{SPEC}/harnesses.md#3-models")
def h04(ctx):
    h = _harness(ctx)
    r = ctx.client.get(f"/v1/harnesses/{h['id']}/models")
    assert r.status == 200, f"GET /v1/harnesses/{{id}}/models returned HTTP {r.status}"
    ctx.validate(r.json, "HarnessModels")


# ══════════════════════════════════════════════════════════════════════════════════════
# Core — running a task
# ══════════════════════════════════════════════════════════════════════════════════════

@check("T-01", "A non-streaming task returns a valid Response", "core", f"{SPEC}/tasks.md#3-the-response-object")
def t01(ctx):
    r = _run_blocking(ctx)
    assert r.status == 200, f"POST /v1/responses returned HTTP {r.status}: {r.body[:200]!r}"
    ctx.validate(r.json, "Response")
    return f"status={r.json.get('status')} in {r.elapsed_s:.1f}s"


@check("T-02", "A finished task is in a terminal state", "core", f"{SPEC}/lifecycle.md#3-task-lifecycle")
def t02(ctx):
    r = _run_blocking(ctx)
    st = (r.json or {}).get("status")
    assert st in {"completed", "failed", "incomplete", "cancelled"}, (
        f"a returned non-streaming task has non-terminal status {st!r}")


@check("T-03", "The response names the model that actually ran", "core", f"{SPEC}/tasks.md#13-model-selection-and-substitution")
def t03(ctx):
    r = _run_blocking(ctx)
    d = r.json or {}
    assert d.get("model"), "response has no `model`, so a client cannot tell what ran"
    meta = d.get("metadata") or {}
    if meta.get("requested_model") and meta["requested_model"] != d["model"]:
        assert meta.get("model_fallback") is True, (
            "the server substituted a model but did not set metadata.model_fallback")
        return f"substituted {meta['requested_model']} -> {d['model']} (correctly reported)"
    return f"model={d['model']}"


@check("T-04", "The response reports its session", "core", f"{SPEC}/lifecycle.md#4-session-lifecycle")
def t04(ctx):
    r = _run_blocking(ctx)
    sid = ((r.json or {}).get("metadata") or {}).get("session_id")
    assert sid, "response metadata has no session_id, so the session cannot be continued or inspected"
    ctx.state["session_id"] = sid
    return f"session_id={sid}"


@check("T-05", "usage is an object or explicitly null, never fabricated", "core",
       f"{SPEC}/tasks.md#3-the-response-object")
def t05(ctx):
    r = _run_blocking(ctx)
    d = r.json or {}
    assert "usage" in d, "response has no `usage` key at all"
    u = d["usage"]
    assert u is None or isinstance(u, dict), f"usage is neither null nor an object: {type(u).__name__}"


@check("T-06", "A stored response can be read back", "core", f"{SPEC}/tasks.md#4-reading-a-task-back")
def t06(ctx):
    r = _run_blocking(ctx)
    rid = (r.json or {}).get("id")
    if not rid:
        raise Skip("the task did not return an id")
    got = ctx.client.get(f"/v1/responses/{rid}")
    assert got.status == 200, f"GET /v1/responses/{{id}} returned HTTP {got.status}"
    assert got.json.get("id") == rid, "read-back returned a different id"
    assert got.json.get("status") == r.json.get("status"), (
        "read-back status differs from the status the task returned; terminal states must not change")


@check("T-07", "Response ids are prefixed", "core", f"{SPEC}/architecture.md#3-object-model")
def t07(ctx):
    rid = (_run_blocking(ctx).json or {}).get("id") or ""
    assert rid.startswith("resp_"), f"response id {rid!r} is not `resp_`-prefixed"


# ══════════════════════════════════════════════════════════════════════════════════════
# Core — streaming
# ══════════════════════════════════════════════════════════════════════════════════════

@check("S-01", "A streaming task emits events", "core", f"{SPEC}/streaming.md#1-opening-a-stream")
def s01(ctx):
    evs = _run_stream(ctx)
    assert evs, (f"the stream produced no events "
                 f"(HTTP {getattr(ctx.client, 'stream_status', '?')}: "
                 f"{getattr(ctx.client, 'stream_error', '')[:200]})")
    return f"{len(evs)} events"


@check("S-02", "Stream content type is text/event-stream", "core", f"{SPEC}/streaming.md#1-opening-a-stream")
def s02(ctx):
    _run_stream(ctx)
    ct = (getattr(ctx.client, "stream_headers", {}) or {}).get("content-type", "")
    assert "text/event-stream" in ct, f"stream Content-Type is {ct!r}, expected text/event-stream"


@check("S-03", "Every event validates against the schema", "core", f"{SPEC}/schema.md")
def s03(ctx):
    evs = _run_stream(ctx)
    if not evs:
        raise Skip("no events to validate")
    for e in evs:
        ctx.validate({k: v for k, v in e.items() if k != "__t"}, "Event")
    return f"{len(evs)} events valid"


@check("S-04", "sequence_number starts at 0 and has no gaps", "core",
       f"{SPEC}/streaming.md#3-ordering-guarantees")
def s04(ctx):
    evs = _run_stream(ctx)
    if not evs:
        raise Skip("no events to check")
    seqs = [e.get("sequence_number") for e in evs]
    assert all(isinstance(s, int) for s in seqs), "some events have no integer sequence_number"
    assert seqs[0] == 0, f"first sequence_number is {seqs[0]}, expected 0"
    expected = list(range(len(seqs)))
    assert seqs == expected, (
        f"sequence_number is not gapless and monotonic; first divergence at index "
        f"{next(i for i, (a, b) in enumerate(zip(seqs, expected)) if a != b)}. "
        "A client cannot distinguish a dropped event from a server that skips numbers.")


@check("S-05", "The first event is response.created", "core", f"{SPEC}/streaming.md#3-ordering-guarantees")
def s05(ctx):
    evs = _run_stream(ctx)
    if not evs:
        raise Skip("no events to check")
    assert evs[0].get("type") == "response.created", (
        f"first event is {evs[0].get('type')!r}, expected 'response.created'")


@check("S-06", "The stream ends with exactly one terminal event", "core",
       f"{SPEC}/streaming.md#4-terminal-events")
def s06(ctx):
    evs = _run_stream(ctx)
    if not evs:
        raise Skip("no events to check")
    term = {"response.completed", "response.incomplete", "response.failed"}
    finals = [e for e in evs if e.get("type") in term]
    assert len(finals) == 1, f"found {len(finals)} terminal events, expected exactly 1"
    assert evs[-1].get("type") in term, (
        f"the last event is {evs[-1].get('type')!r}, not a terminal event")
    return f"terminal={finals[0]['type']}"


@check("S-07", "The terminal event carries the complete response", "core",
       f"{SPEC}/streaming.md#4-terminal-events")
def s07(ctx):
    evs = _run_stream(ctx)
    t = _terminal(evs)
    if not t:
        raise Skip("no terminal event")
    resp = t.get("response")
    assert isinstance(resp, dict), "the terminal event has no `response` object"
    ctx.validate(resp, "Response")
    assert resp.get("status") in {"completed", "failed", "incomplete", "cancelled"}, (
        f"terminal response has non-terminal status {resp.get('status')!r}")


@check("S-08", "Streaming and non-streaming agree on the result shape", "core",
       f"{SPEC}/streaming.md#6-non-streaming")
def s08(ctx):
    b = (_run_blocking(ctx).json or {})
    t = _terminal(_run_stream(ctx)) or {}
    sresp = t.get("response") or {}
    if not b or not sresp:
        raise Skip("need both a streaming and a non-streaming result")
    for f in ("object", "status"):
        assert f in b and f in sresp, f"{f!r} missing from one of the two paths"
    assert b.get("object") == sresp.get("object") == "response", (
        "the two paths do not both return `object: response`")


@check("S-09", "The stream is progressive, not buffered to the end", "core",
       f"{SPEC}/streaming.md#1-opening-a-stream")
def s09(ctx):
    evs = _run_stream(ctx)
    if len(evs) < 3:
        raise Skip("too few events to judge progressiveness")
    first, last = evs[0].get("__t", 0), evs[-1].get("__t", 0)
    if last < 0.5:
        raise Skip(f"the whole task finished in {last:.2f}s — too fast to distinguish buffering")
    spread = last - first
    assert spread > 0.05, (
        f"all {len(evs)} events arrived within {spread*1000:.0f}ms of each other after {last:.1f}s. "
        "The stream appears to be buffered and flushed at the end, which a client cannot "
        "distinguish from a hang. Check for response buffering in a proxy.")
    return f"events spread over {spread:.1f}s"


# ══════════════════════════════════════════════════════════════════════════════════════
# Core — sessions and cancellation
# ══════════════════════════════════════════════════════════════════════════════════════

@check("C-01", "A task can continue a session", "core", f"{SPEC}/sessions.md#1-continuing-a-session")
def c01(ctx):
    first = _run_blocking(ctx)
    rid = (first.json or {}).get("id")
    sid = ((first.json or {}).get("metadata") or {}).get("session_id")
    if not rid or not sid:
        raise Skip("the first task did not return an id and session_id")
    h = _harness(ctx)
    body = {"input": "Reply with exactly: two", "previous_response_id": rid,
            "metadata": {"harness_id": h["id"]}, "stream": False}
    r = ctx.client.post("/v1/responses", body=body)
    assert r.status == 200, f"continuation returned HTTP {r.status}: {r.body[:200]!r}"
    got = ((r.json or {}).get("metadata") or {}).get("session_id")
    assert got == sid, f"continuation ran in session {got!r}, expected the original {sid!r}"
    assert (r.json or {}).get("previous_response_id") == rid, (
        "the continuation does not report the response it continued")
    ctx.state["second_response"] = r.json
    return f"session {sid} extended"


@check("C-02", "Cancelling a terminal task succeeds and changes nothing", "core",
       f"{SPEC}/sessions.md#4-cancelling")
def c02(ctx):
    rid = (_run_blocking(ctx).json or {}).get("id")
    if not rid:
        raise Skip("no response to cancel")
    before = ctx.client.get(f"/v1/responses/{rid}").json or {}
    r = ctx.client.post(f"/v1/responses/{rid}/cancel")
    assert r.status in (200, 409), (
        f"cancelling a terminal task returned HTTP {r.status}; a client retrying a cancel after a "
        "dropped connection must not be punished for having succeeded")
    after = ctx.client.get(f"/v1/responses/{rid}").json or {}
    assert after.get("status") == before.get("status"), (
        f"cancel changed a terminal status from {before.get('status')!r} to {after.get('status')!r}")


@check("C-03", "A running task can be cancelled and ends non-running", "core",
       f"{SPEC}/sessions.md#4-cancelling")
def c03(ctx):
    h = _harness(ctx)
    body = {"input": "Count slowly from 1 to 200, one number per line.",
            "metadata": {"harness_id": h["id"]}, "stream": False, "background": True}
    if ctx.model:
        body["model"] = ctx.model
    started = ctx.client.post("/v1/responses", body=body)
    rid = (started.json or {}).get("id")
    if started.status != 200 or not rid:
        raise Skip(f"could not start a cancellable task (HTTP {started.status})")
    time.sleep(2.0)
    r = ctx.client.post(f"/v1/responses/{rid}/cancel")
    assert r.status == 200, f"cancel returned HTTP {r.status}"
    deadline = time.time() + 90
    last = ""
    while time.time() < deadline:
        last = (ctx.client.get(f"/v1/responses/{rid}").json or {}).get("status", "")
        if last in {"cancelled", "completed", "failed", "incomplete"}:
            break
        time.sleep(2.0)
    assert last in {"cancelled", "completed", "failed", "incomplete"}, (
        f"the task was still {last!r} 90s after being cancelled; cancellation must reach a terminal state")
    return f"final status={last}"


# ══════════════════════════════════════════════════════════════════════════════════════
# Extended — sessions, files, artifacts
# ══════════════════════════════════════════════════════════════════════════════════════

@check("X-01", "Sessions can be listed", "extended", f"{SPEC}/sessions.md#2-listing-sessions")
def x01(ctx):
    r = ctx.client.get("/v1/sessions?limit=5")
    assert r.status == 200, f"GET /v1/sessions returned HTTP {r.status}"
    d = r.json or {}
    key = "sessions" if "sessions" in d else next((k for k, v in d.items() if isinstance(v, list)), None)
    assert key, f"no array of sessions in the response (keys: {list(d)[:6]})"
    return f"{len(d[key])} session(s)"


@check("X-02", "Session listing reports the end of pagination explicitly", "extended",
       f"{SPEC}/sessions.md#2-listing-sessions")
def x02(ctx):
    d = ctx.client.get("/v1/sessions?limit=5").json or {}
    assert any(k in d for k in ("next_cursor", "cursor", "has_more")), (
        "the listing has no pagination marker, so a client must guess the end from a short page — "
        "a heuristic that is wrong whenever a page is exactly full")


@check("X-03", "A session can be inspected", "extended", f"{SPEC}/sessions.md#3-inspecting-a-session")
def x03(ctx):
    sid = ctx.state.get("session_id")
    if not sid:
        raise Skip("no session id from an earlier task")
    r = ctx.client.get(f"/v1/sessions/{sid}")
    assert r.status == 200, f"GET /v1/sessions/{{id}} returned HTTP {r.status}"


@check("X-04", "A session's turn history is available", "extended",
       f"{SPEC}/sessions.md#3-inspecting-a-session")
def x04(ctx):
    sid = ctx.state.get("session_id")
    if not sid:
        raise Skip("no session id from an earlier task")
    r = ctx.client.get(f"/v1/sessions/{sid}/turns")
    assert r.status == 200, f"GET /v1/sessions/{{id}}/turns returned HTTP {r.status}"


@check("X-05", "A file can be sent as task input", "extended", f"{SPEC}/files.md#1-sending-files-in")
def x05(ctx):
    h = _harness(ctx)
    token = f"uhp-{uuid.uuid4().hex[:8]}"
    data = base64.b64encode(f"The secret token is {token}.".encode()).decode()
    body = {
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "Reply with only the secret token from the attached file."},
            {"type": "input_file", "filename": "token.txt",
             "file_data": f"data:text/plain;base64,{data}"}]}],
        "metadata": {"harness_id": h["id"]}, "stream": False,
    }
    if ctx.model:
        body["model"] = ctx.model
    r = ctx.client.post("/v1/responses", body=body)
    assert r.status == 200, f"a task with an inline file returned HTTP {r.status}: {r.body[:200]!r}"
    ctx.validate(r.json, "Response")
    text = json.dumps(r.json.get("output") or [])
    ctx.state["file_input_echoed"] = token in text
    return ("the harness read the file and echoed the token" if token in text
            else "accepted (the harness did not echo the token, which the protocol does not require)")


def _session_with_artifact(ctx) -> str:
    """A session that has actually produced a file, so the artifact checks test something.

    Reusing the plain text task would leave the artifact checks permanently skipped, which reads as
    "fine" in a report and verifies nothing.
    """
    if "artifact_session" in ctx.state:
        return ctx.state["artifact_session"]
    h = _harness(ctx)
    body = {"input": "Create a file named uhp-conformance.txt containing exactly: artifact-ok",
            "metadata": {"harness_id": h["id"]}, "stream": False}
    if ctx.model:
        body["model"] = ctx.model
    r = ctx.client.post("/v1/responses", body=body)
    sid = ((r.json or {}).get("metadata") or {}).get("session_id") or ctx.state.get("session_id")
    if not sid:
        raise Skip(f"could not run a task that writes a file (HTTP {r.status})")
    ctx.state["artifact_session"] = sid
    return sid


@check("X-06", "Artifacts of a session can be listed", "extended", f"{SPEC}/files.md#22-by-listing-the-session")
def x06(ctx):
    sid = _session_with_artifact(ctx)
    if not sid:
        raise Skip("no session id from an earlier task")
    r = ctx.client.get(f"/v1/sessions/{sid}/files")
    assert r.status == 200, f"GET /v1/sessions/{{id}}/files returned HTTP {r.status}"
    d = r.json or {}
    files = d.get("files") if isinstance(d.get("files"), list) else None
    assert files is not None, f"no `files` array in the response (keys: {list(d)[:6]})"
    ctx.state["artifacts"] = files
    return f"{len(files)} artifact(s)"


@check("X-07", "An artifact downloads as raw bytes with nosniff", "extended", f"{SPEC}/files.md#3-downloading")
def x07(ctx):
    arts = ctx.state.get("artifacts")
    if not arts:
        raise Skip("this session produced no artifacts to download")
    a = arts[0]
    cid, fid = a.get("container_id"), a.get("id") or a.get("file_id")
    if not cid or not fid:
        raise Skip(f"artifact has no container_id/file_id (keys: {list(a)[:6]})")
    r = ctx.client.get(f"/v1/containers/{cid}/files/{fid}/content")
    assert r.status == 200, f"artifact download returned HTTP {r.status}"
    assert r.header("x-content-type-options").lower() == "nosniff", (
        "artifact download is missing `X-Content-Type-Options: nosniff`. Artifacts are "
        "attacker-influenceable content; serving them without it is stored XSS against the client's origin.")
    return f"{len(r.body)} bytes, {r.header('content-type')}"


@check("X-08", "Artifact ids do not traverse outside their container", "extended",
       f"{SPEC}/files.md#5-retention-and-scope")
def x08(ctx):
    arts = ctx.state.get("artifacts")
    cid = (arts[0].get("container_id") if arts else None) or "cntr_uhpconformance"
    for probe in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd"):
        r = ctx.client.get(f"/v1/containers/{cid}/files/{probe}/content")
        assert r.status in (400, 403, 404), (
            f"a traversal probe returned HTTP {r.status}; expected it to be refused")
        assert b"root:" not in r.body, "a traversal probe returned /etc/passwd content"
    return "traversal probes refused"


# ══════════════════════════════════════════════════════════════════════════════════════
# Full — harness lifecycle
# ══════════════════════════════════════════════════════════════════════════════════════

@check("F-01", "A harness can be created, updated and deleted", "full",
       f"{SPEC}/harnesses.md#4-managing-harnesses")
def f01(ctx):
    # Ask the server which bases it supports rather than copying one off an existing harness: an
    # earlier run (or another client) may have left a harness whose base this server cannot run,
    # and that would make this check fail for the wrong reason.
    probe = ctx.client.post("/v1/harnesses", body={"name": "uhp-conformance-probe",
                                                  "base": "uhp-conformance-unknown-base"})
    supported = (((probe.json or {}).get("error") or {}).get("detail") or {}).get("supported") or []
    if probe.status == 200:      # the server accepted it; clean up and fall back
        ctx.client.delete(f"/v1/harnesses/{(probe.json or {}).get('id')}")
    base = (supported or [(_harness(ctx)).get("base") or "claude-code"])[0]
    created = ctx.client.post("/v1/harnesses", body={
        "name": f"uhp-conformance-{uuid.uuid4().hex[:6]}", "base": base})
    assert created.status == 200, f"create returned HTTP {created.status}: {created.body[:200]!r}"
    hid = (created.json or {}).get("id")
    assert hid, "create did not return an id"
    ctx.validate(created.json, "Harness")
    try:
        upd = ctx.client.put(f"/v1/harnesses/{hid}", body={"name": "uhp-conformance-renamed",
                                                           "base": base})
        assert upd.status == 200, f"update returned HTTP {upd.status}"
        assert (upd.json or {}).get("base") == base, "update changed the harness base, which is immutable"
    finally:
        gone = ctx.client.delete(f"/v1/harnesses/{hid}")
        assert gone.status in (200, 204), f"delete returned HTTP {gone.status}"
    after = ctx.client.get(f"/v1/harnesses/{hid}")
    assert after.status == 404, f"a deleted harness still resolves (HTTP {after.status})"
    return f"created, updated and deleted {hid}"


def _managed_harness(ctx, **cfg) -> dict:
    """Create a throwaway harness carrying `cfg`, remembered for cleanup."""
    base = _supported_base(ctx)
    body = {"name": f"uhp-conformance-{uuid.uuid4().hex[:6]}", "base": base, **cfg}
    r = ctx.client.post("/v1/harnesses", body=body)
    if r.status != 200:
        raise Skip(f"could not create a harness to configure (HTTP {r.status})")
    h = r.json or {}
    ctx.state.setdefault("_cleanup_harnesses", []).append(h.get("id"))
    return h


def _supported_base(ctx) -> str:
    if ctx.state.get("_base"):
        return ctx.state["_base"]
    probe = ctx.client.post("/v1/harnesses", body={"name": "uhp-conformance-probe",
                                                  "base": "uhp-conformance-unknown-base"})
    supported = (((probe.json or {}).get("error") or {}).get("detail") or {}).get("supported") or []
    if probe.status == 200:
        ctx.client.delete(f"/v1/harnesses/{(probe.json or {}).get('id')}")
    base = (supported or [(_harness(ctx)).get("base") or "claude-code"])[0]
    ctx.state["_base"] = base
    return base


# A folder, not a file: the point of the check is the members that are NOT SKILL.md.
_SKILL_BUNDLE = {
    "name": "uhp-conformance-skill",
    "enabled": True,
    "files": [
        {"path": "SKILL.md",
         "content": "---\nname: uhp-conformance-skill\ndescription: A conformance fixture.\n---\n\nSee references/data.md.\n"},
        {"path": "references/data.md", "content": "nested reference file\n"},
        {"path": "assets/blob.bin", "content_b64": "AAECAwQF"},
    ],
}


@check("F-03", "A skill folder round-trips through create and read", "full",
       f"{SPEC}/harnesses.md#42-skills")
def f03(ctx):
    h = _managed_harness(ctx, skills=[_SKILL_BUNDLE])
    r = ctx.client.get(f"/v1/harnesses/{h['id']}/skills/uhp-conformance-skill/files")
    assert r.status == 200, f"skill files endpoint returned HTTP {r.status}"
    body = r.json
    files = body.get("files") if isinstance(body, dict) else body
    paths = sorted(str((f or {}).get("path")) for f in (files or []))
    want = ["SKILL.md", "assets/blob.bin", "references/data.md"]
    assert paths == want, (
        f"the folder did not round-trip: got {paths}, expected {want}. Materialising or storing "
        "only SKILL.md breaks every skill that carries references, scripts or data.")
    blob = json.dumps(files)
    assert "AAECAwQF" in blob, "the binary member's content_b64 was not preserved byte-for-byte"
    return f"{len(paths)} files incl. nested + binary"


@check("F-04", "An unrelated harness edit does not destroy skill contents", "full",
       f"{SPEC}/harnesses.md#42-skills")
def f04(ctx):
    h = _managed_harness(ctx, skills=[_SKILL_BUNDLE])
    hid = h["id"]
    got = (ctx.client.get(f"/v1/harnesses/{hid}").json or {})
    # Rename only — exactly what a client does when it PUTs back what it read.
    r = ctx.client.put(f"/v1/harnesses/{hid}", body={
        "name": "uhp-conformance-renamed", "base": got.get("base"),
        "skills": got.get("skills") or [], "mcp_servers": got.get("mcpServers") or [],
        "disabled_tools": got.get("disabledTools") or []})
    assert r.status == 200, f"rename returned HTTP {r.status}"
    after = ctx.client.get(f"/v1/harnesses/{hid}/skills/uhp-conformance-skill/files")
    files = (after.json or {}).get("files") if isinstance(after.json, dict) else after.json
    paths = sorted(str((f or {}).get("path")) for f in (files or []))
    assert paths == ["SKILL.md", "assets/blob.bin", "references/data.md"], (
        f"after renaming the harness the skill folder is {paths} — the round trip lost contents, "
        "which a user cannot detect until an agent behaves oddly.")


@check("F-05", "A skill bundle without SKILL.md is refused at config time", "full",
       f"{SPEC}/harnesses.md#42-skills")
def f05(ctx):
    base = _supported_base(ctx)
    r = ctx.client.post("/v1/harnesses", body={
        "name": "uhp-conformance-badskill", "base": base,
        "skills": [{"name": "no-manifest", "enabled": True,
                    "files": [{"path": "notes.md", "content": "no manifest here"}]}]})
    if r.status == 200:
        ctx.client.delete(f"/v1/harnesses/{(r.json or {}).get('id')}")
        raise AssertionError(
            "a bundle with no SKILL.md was accepted; it would be stored and then silently ignored "
            "at run time, which is the hardest kind of failure for a user to diagnose")
    assert r.status in (400, 422), f"expected 400/422, got HTTP {r.status}"
    return f"refused with HTTP {r.status}"


@check("F-06", "MCP servers and disabled tools round-trip", "full",
       f"{SPEC}/harnesses.md#41-mcp-servers")
def f06(ctx):
    mcp = [{"name": "conformance-mcp", "url": "https://mcp.example.invalid/mcp",
            "transport": "http", "enabled": False}]
    h = _managed_harness(ctx, mcp_servers=mcp, disabled_tools=["WebSearch"])
    got = ctx.client.get(f"/v1/harnesses/{h['id']}").json or {}
    servers = got.get("mcpServers") or []
    assert servers, "mcpServers came back empty after being set"
    ctx.validate(servers[0], "McpServer")
    assert servers[0].get("enabled") is False, (
        "the server's `enabled: false` was not preserved; a client cannot tell a disabled entry "
        "from an enabled one, and the difference decides whether a third party is contacted")
    assert got.get("disabledTools") == ["WebSearch"], (
        f"disabledTools round-tripped as {got.get('disabledTools')}")
    return "mcp + disabledTools preserved"


@check("F-07", "Configured harnesses are cleaned up", "full", f"{SPEC}/harnesses.md#53-delete")
def f07(ctx):
    ids = [i for i in ctx.state.get("_cleanup_harnesses") or [] if i]
    if not ids:
        raise Skip("no harnesses were created by earlier checks")
    left = []
    for hid in ids:
        ctx.client.delete(f"/v1/harnesses/{hid}")
        if ctx.client.get(f"/v1/harnesses/{hid}").status != 404:
            left.append(hid)
    assert not left, f"these harnesses still resolve after delete: {left}"
    return f"{len(ids)} removed"


@check("F-02", "Creating a harness with an unsupported base is refused", "full",
       f"{SPEC}/harnesses.md#41-create")
def f02(ctx):
    r = ctx.client.post("/v1/harnesses", body={"name": "uhp-conformance-bad-base",
                                               "base": "definitely-not-a-real-harness"})
    assert r.status in (400, 422), (
        f"an unsupported base returned HTTP {r.status}; expected it to be refused. A server that "
        "accepts a base it cannot run fails at task time instead, after the client has committed.")
    if r.status == 200:  # defensive: clean up if the server accepted it after all
        ctx.client.delete(f"/v1/harnesses/{(r.json or {}).get('id')}")


# ══════════════════════════════════════════════════════════════════════════════════════
# Full — session sharing
# ══════════════════════════════════════════════════════════════════════════════════════
# Sessions §5 is the Full requirement this suite could not see, and it is the one where a
# happy-path check would be worse than no check at all: almost every sentence in §5 is about
# what the server REFUSES. A check that minted a link and read the conversation back would
# pass against a server that also let that link continue the task, cancel the run, or upload
# into the working directory — and an unauthenticated write path into someone's working
# directory is about as bad as a defect in this protocol gets.
#
# §5 says a server MAY publish a shared view, so every check below skips — never fails — on a
# server that does not implement sharing. What is not optional is the shape of it once it does.
#
# §5 names two endpoints and no others: it does not say where the view is served, and it does
# not name a revocation path. So these checks discover both from what the server itself
# returned, rather than assuming any one implementation's URLs. Where discovery is impossible
# the check skips and names the missing sentence, because that is a gap in the specification
# rather than a defect in the server being tested.

# Keys whose non-empty presence in a shared view would breach §5's third bullet. `headers` and
# `env` are here because that is where an MCP server's credentials live (Harnesses §4.1).
_SECRET_KEYS = {"auth", "authorization", "api_key", "apikey", "token", "access_token",
                "refresh_token", "secret", "password", "credentials", "env", "headers"}


def _walk(node, path="$"):
    """Every (json-path, key, value) pair in a document, so a finding can say where it is."""
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}"
            yield here, k, v
            yield from _walk(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def _view_path(ctx, url: str) -> str:
    """The client-relative path for a URL the server handed back.

    The share URL may be absolute or relative, and the base URL may carry a path prefix
    (`https://host/api/harness`), so neither can simply be concatenated. A view on a different
    origin is not something this suite can attest, and says so rather than guessing.
    """
    from urllib.parse import urlsplit
    base, u = urlsplit(ctx.client.base_url), urlsplit(url)
    if u.netloc and u.netloc != base.netloc:
        raise Skip(f"the shared view is served on another origin ({u.netloc}), which this suite "
                   "cannot reach or attest")
    prefix = base.path.rstrip("/")
    path = u.path if not prefix or not u.path.startswith(prefix) else u.path[len(prefix):]
    return path + (f"?{u.query}" if u.query else "")


def _shared_session_id(ctx) -> str:
    sid = ctx.state.get("session_id")
    if sid:
        return sid
    sid = ((_run_blocking(ctx).json or {}).get("metadata") or {}).get("session_id")
    if not sid:
        raise Skip("no session id from an earlier task, so there is nothing to share")
    return sid


def _mint_share(ctx, sid: str):
    """POST the share, speaking both dialects §5's silence allows.

    §5 documents POST with no body, but a server that models sharing as a toggle carries the
    target state in the body and refuses an empty one with a validation error (the reference
    implementation among them, verified live). A 4xx naming a missing body field is a dialect
    answer, not a refusal to share — while 404/405/501 stay exactly what they were: not
    implemented. ONE function, because R-07 mints its own disposable share and a second copy of
    this decision already drifted once (R-07 skipped on servers _share could drive)."""
    r = ctx.client.post(f"/v1/sessions/{sid}/share")
    if r.status in (400, 422):
        r = ctx.client.post(f"/v1/sessions/{sid}/share", body={"enabled": True})
    return r


def _share(ctx) -> dict:
    """Mint the share once and cache it, or skip with the reason it could not be minted."""
    if "share" in ctx.state:
        got = ctx.state["share"]
        if isinstance(got, str):        # a cached skip reason: do not re-POST on every check
            raise Skip(got)
        return got

    def _skip(reason):
        ctx.state["share"] = reason
        raise Skip(reason)

    caps = (ctx.state.get("discovery") or {}).get("capabilities") or {}
    if caps.get("session_sharing") is False:
        _skip("this server reports session_sharing false, and Sessions §5 is a MAY")
    sid = _shared_session_id(ctx)
    r = _mint_share(ctx, sid)
    if r.status in (404, 405, 501):
        _skip(f"POST /v1/sessions/{{id}}/share returned HTTP {r.status}: this server does not "
              "publish shared views, which Sessions §5 permits")
    if r.status != 200 or not isinstance(r.json, dict):
        _skip(f"POST /v1/sessions/{{id}}/share returned HTTP {r.status}, which is neither a share "
              f"nor a refusal this check can read: {r.body[:160]!r}")
    d = r.json
    url = next((d[k] for k in ("url", "share_url", "href", "link", "location")
                if isinstance(d.get(k), str) and d[k]), "") or r.header("location")
    if not url:
        _skip("the share carries no URL, and Sessions §5 does not say where a shared view is "
              f"served, so this check cannot locate it (keys: {sorted(d)[:8]}). The specification "
              "should name the view's endpoint, or the share object should be schema'd with a "
              "field that does.")
    share = {"id": d.get("id") or "", "url": url, "path": _view_path(ctx, url), "session_id": sid,
             "body": d}
    ctx.state["share"] = share
    return share


@check("R-01", "A shared session is published, and the link alone opens it", "full",
       f"{SPEC}/sessions.md#5-session-sharing")
def r01(ctx):
    sh = _share(ctx)
    r = ctx.client.get(sh["path"], auth=False)
    assert r.status == 200, (
        f"the URL the server published for this share returned HTTP {r.status} when opened with no "
        "credential. Sessions §5 is about publishing a view: one that only the principal who minted "
        "it can open has not been published to anyone.")
    ctx.state["share_readable"] = True
    body = r.json
    assert body is not None, f"the shared view is not JSON: {r.body[:120]!r}"
    return f"readable unauthenticated at {sh['path']}"


@check("R-02", "The share can be read back from the endpoint that minted it", "full",
       f"{SPEC}/sessions.md#5-session-sharing")
def r02(ctx):
    sh = _share(ctx)
    r = ctx.client.get(f"/v1/sessions/{sh['session_id']}/share")
    assert r.status == 200, (
        f"GET /v1/sessions/{{id}}/share returned HTTP {r.status} for a session that has a share. §5 "
        "names this endpoint, and a client that has lost the link has nowhere else to ask.")
    d = r.json or {}
    got = next((d[k] for k in ("url", "share_url", "href", "link", "location")
                if isinstance(d.get(k), str) and d[k]), "")
    assert got, f"the share read back carries no URL (keys: {sorted(d)[:8]})"
    assert _view_path(ctx, got) == sh["path"], (
        f"GET reports a different view ({_view_path(ctx, got)}) from the one POST published "
        f"({sh['path']}). A client cannot revoke, or even name, a link it is told two versions of.")
    if sh["id"] and d.get("id"):
        assert d["id"] == sh["id"], f"share id changed between POST and GET: {sh['id']} → {d['id']}"
    return "GET agrees with POST"


@check("R-03", "A share id is not a credential for the API", "full",
       f"{SPEC}/sessions.md#5-session-sharing")
def r03(ctx):
    sh = _share(ctx)
    ident = sh["id"] or sh["path"].rstrip("/").rsplit("/", 1)[-1]
    if not ident:
        raise Skip("the share exposes no id to present as a token")
    # Only endpoints this server actually serves to the real credential can say anything about a
    # wrong one: a 404 or a 405 is the router declining a path, not the guard declining a token.
    guarded = [p for p in ("/v1/sessions", "/v1/responses", "/v1/harnesses")
               if 200 <= ctx.client.get(p).status < 300]
    if not guarded:
        raise Skip("no authenticated GET endpoint answered the real credential, so nothing here "
                   "can distinguish a refused token from an absent route")
    accepted = [f"{p} → HTTP {r.status}" for p, r in
                ((p, ctx.client.get(p, headers={"authorization": f"Bearer {ident}"}))
                 for p in guarded)
                if 200 <= r.status < 300]
    assert not accepted, (
        "the share id is accepted as a bearer token: " + "; ".join(accepted) + ". §5 forbids a "
        "shared view exposing another principal's data, and a link that authenticates the API "
        "exposes all of it — every session, every response, every configured harness.")
    return f"refused on {len(guarded)} endpoint(s)"


@check("R-04", "The shared view is read-only", "full", f"{SPEC}/sessions.md#5-session-sharing")
def r04(ctx):
    sh = _share(ctx)
    if not ctx.state.get("share_readable"):
        raise Skip("the shared view did not resolve (see R-01), so what it refuses cannot be read")
    view = sh["path"].split("?")[0].rstrip("/")
    probes = [("POST", view), ("PUT", view), ("PATCH", view), ("DELETE", view),
              # The three §5 names outright, at the paths this protocol uses for them elsewhere.
              ("POST", f"{view}/cancel"), ("POST", f"{view}/responses"), ("POST", f"{view}/files")]
    accepted = []
    for method, path in probes:
        body = {} if method != "DELETE" else None
        r = ctx.client.request(method, path, body=body, auth=False)
        if 200 <= r.status < 300:
            accepted.append(f"{method} {path} → HTTP {r.status}")
    assert not accepted, (
        "the shared view accepted a write from a caller holding only the link: "
        + "; ".join(accepted) + ". §5: the view MUST NOT permit continuing, cancelling, or "
        "uploading. This is an unauthenticated write into someone else's session.")
    return f"{len(probes)} write probes refused"


@check("R-05", "The shared view exposes no credentials", "full",
       f"{SPEC}/sessions.md#5-session-sharing")
def r05(ctx):
    sh = _share(ctx)
    if not ctx.state.get("share_readable"):
        raise Skip("the shared view did not resolve (see R-01), so its contents cannot be read")
    r = ctx.client.get(sh["path"], auth=False)
    raw = r.body.decode("utf-8", "replace")
    if ctx.client.api_key:
        assert ctx.client.api_key not in raw, (
            "the shared view contains this client's API key verbatim. §5: a shared view MUST NOT "
            "expose provider credentials or tokens.")
    leaks = [p for p, k, v in _walk(r.json)
             if k.lower() in _SECRET_KEYS and v not in (None, "", {}, [], False)]
    assert not leaks, (
        f"the shared view carries credential-shaped fields with values: {leaks[:5]}. §5 forbids "
        "exposing provider credentials or tokens; Harnesses §4.1 puts an MCP server's `auth` and "
        "`headers` among them, and the holder of a link is a client that presented nothing.")
    return "no credential-shaped fields"


@check("R-06", "Revocation kills every link minted for the session", "full",
       f"{SPEC}/sessions.md#5-session-sharing")
def r06(ctx):
    sh = _share(ctx)
    if not ctx.state.get("share_readable"):
        raise Skip("the shared view never resolved (see R-01), so 'stops resolving' cannot be "
                   "distinguished from 'never resolved'")
    sid = sh["session_id"]

    # Share the session a second time before revoking. §5 does not say whether a second POST
    # returns the first link or mints another, and this check does not require either — but
    # whichever it did, revocation has to reach what it produced. A server that hands out a
    # second link and then revokes only the newest has told the operator the session is private
    # while a live link to it is still in someone's hands.
    live = [sh["path"]]
    again = ctx.client.post(f"/v1/sessions/{sid}/share")
    if again.status == 200 and isinstance(again.json, dict):
        url = next((again.json[k] for k in ("url", "share_url", "href", "link", "location")
                    if isinstance(again.json.get(k), str) and again.json[k]), "")
        if url and _view_path(ctx, url) not in live:
            live.append(_view_path(ctx, url))

    # §5 requires revocation and names no path, so the endpoint has to be searched for.
    attempts = [("DELETE", f"/v1/sessions/{sid}/share", None),
                ("POST", f"/v1/sessions/{sid}/share/revoke", None),
                ("DELETE", f"/v1/shares/{sh['id']}" if sh["id"] else "", None),
                # The toggle dialect (the reference implementation's native form). Tried LAST,
                # and believed only when the answer speaks revocation's own vocabulary: a
                # bodyless-dialect server would 200 this by MINTING — it ignores the body — and
                # a mint mistaken for a revocation would fail this check with a false message.
                ("POST", f"/v1/sessions/{sid}/share", {"enabled": False})]
    done = ""
    for method, path, payload in attempts:
        if not path:
            continue
        r = ctx.client.request(method, path, body=payload)
        if not 200 <= r.status < 300:
            continue
        if payload is not None:
            d = r.json if isinstance(r.json, dict) else {}
            if not (d.get("enabled") is False or d.get("deleted") is True):
                continue
        done = f"{method} {path}"
        break
    if not done:
        raise Skip(
            "Sessions §5 requires that a share be revocable and names no endpoint for it, so this "
            "check cannot locate one. The specification should name a path: a MUST with no "
            "endpoint is a MUST that every implementation satisfies differently, and no portable "
            "check can confirm it.")

    ctx.state["share"] = "the share minted for this run was revoked by R-06"
    ctx.state["share_readable"] = False
    alive = [(p, ctx.client.get(p, auth=False).status) for p in live]
    bad = [f"{p} → HTTP {s}" for p, s in alive if s not in (404, 410)]
    assert not bad, (
        f"a published link still resolves after {done} reported success: " + "; ".join(bad) +
        ". A revocation that answers 200 and leaves a link live is worse than none, because the "
        "operator has been told the session is no longer published.")
    return (f"revoked via {done}; {len(live)} link(s) minted, all now "
            f"{'/'.join(str(s) for _, s in alive)}")


@check("R-07", "Deleting a session takes its shared view with it", "full",
       f"{SPEC}/sessions.md#6-deleting")
def r07(ctx):
    # A session this check may destroy: deleting the one the rest of the suite shares would make
    # every later check fail for the wrong reason. That costs one extra agent run on a full pass.
    h = _harness(ctx)
    body = {"input": PROMPT, "metadata": {"harness_id": h["id"]}, "stream": False}
    if ctx.model:
        body["model"] = ctx.model
    started = ctx.client.post("/v1/responses", body=body)
    sid = ((started.json or {}).get("metadata") or {}).get("session_id")
    if started.status != 200 or not sid:
        raise Skip(f"could not start a disposable session (HTTP {started.status})")

    minted = _mint_share(ctx, sid)
    if minted.status != 200 or not isinstance(minted.json, dict):
        raise Skip(f"could not share the disposable session (HTTP {minted.status})")
    url = next((minted.json[k] for k in ("url", "share_url", "href", "link", "location")
                if isinstance(minted.json.get(k), str) and minted.json[k]), "")
    if not url:
        raise Skip("the share carries no URL, so the view cannot be located (see R-01)")
    path = _view_path(ctx, url)
    if ctx.client.get(path, auth=False).status != 200:
        raise Skip("the disposable share's view did not resolve, so its disappearance proves nothing")

    gone = ctx.client.delete(f"/v1/traces/{sid}")
    if gone.status in (404, 405, 501):
        raise Skip(f"DELETE /v1/traces/{{id}} returned HTTP {gone.status}, so a session cannot be "
                   "deleted here and this check has nothing to observe")
    assert 200 <= gone.status < 300, f"deleting the session returned HTTP {gone.status}"
    after = ctx.client.get(path, auth=False)
    assert after.status in (404, 410), (
        f"the shared link still returns HTTP {after.status} for a session that was deleted. §6 "
        "requires the session be unreadable after deletion, and a published link is the one way "
        "in that its owner is least likely to remember.")
    return f"session deleted, then HTTP {after.status}"
