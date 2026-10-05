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

SPEC = "protocol/versions/2026-10-04"


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
        # Never a silent fallback: a named harness that is not there is the caller's mistake
        # (a name given for an id, a typo), and two runs against different --harness-id values
        # once produced byte-identical reports because both fell back to the first harness
        # listed (#203). The CLI resolves the id before the first task; this is the guard for a
        # harness that disappears mid-run.
        items = [h for h in items if h.get("id") == ctx.harness_id]
        if not items:
            raise RuntimeError(f"no harness with id {ctx.harness_id!r} on this server")
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


@check("X-04", "A session's turn history is available, in the specified shape", "extended",
       f"{SPEC}/sessions.md#3-inspecting-a-session")
def x04(ctx):
    sid = ctx.state.get("session_id")
    if not sid:
        raise Skip("no session id from an earlier task")
    r = ctx.client.get(f"/v1/sessions/{sid}/turns")
    assert r.status == 200, f"GET /v1/sessions/{{id}}/turns returned HTTP {r.status}"
    # Sessions §3 now states the item shape (id + status at least), so this asserts it instead of
    # stopping at the status code — the check that could previously only "check for a 200".
    turns = (r.json or {}).get("turns")
    assert isinstance(turns, list), f"the body carries no `turns` array (keys: {sorted(r.json or {})})"
    if not turns:
        raise Skip("the session reports no turns to inspect, so the item shape cannot be observed")
    for i, t in enumerate(turns):
        ctx.validate(t, "TurnItem")
        assert t.get("id") and isinstance(t.get("id"), str), f"turns[{i}] has no response id"
        assert t.get("status"), f"turns[{i}] has no status"


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

@check("X-09", "A file uploaded through POST /v1/files is accepted and can be sent as task input",
       "extended", f"{SPEC}/files.md#12-by-upload")
def x09(ctx):
    """Files §1.2 is the other half of "a server MUST accept both forms". X-05 sends its file inline,
    so it never reaches `POST /v1/files`: HarnessRouter CE 0.17.3 answered every upload with 500 and
    passed the files chapter (#198). This check uploads, holds the file object to the schema, and
    then references the id from a task the way a client would."""
    d = ctx.state.get("discovery") or ctx.client.get("/v1/uhp", auth=False).json or {}
    ctx.state["discovery"] = d
    if (d.get("capabilities") or {}).get("files_input") is False:
        raise Skip("this server reports files_input false, so Files §1 does not apply to it")
    h = _harness(ctx)
    token = f"uhp-{uuid.uuid4().hex[:8]}"
    content = f"The secret token is {token}.\n".encode()
    boundary = f"uhp{uuid.uuid4().hex}"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nuser_data\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"token.txt\"\r\n"
            f"Content-Type: text/plain\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    r = ctx.client.post("/v1/files", raw=body, content_type=f"multipart/form-data; boundary={boundary}")
    assert r.status == 200, (f"POST /v1/files returned HTTP {r.status}: {r.body[:200]!r} "
                             f"(X-05 sends its file inline and never reaches this endpoint)")
    f = r.json if isinstance(r.json, dict) else {}
    ctx.validate(f, "File")
    assert f.get("object") == "file", f"the upload answered object={f.get('object')!r}, not 'file'"
    if "bytes" in f:   # optional in the schema; when reported it must be the whole file — a short
        assert f["bytes"] == len(content), (   # count is the silent truncation §1.2 forbids
            f"the upload reports {f['bytes']!r} bytes for a {len(content)}-byte file")
    task = {"input": [{"role": "user", "content": [
                {"type": "input_text", "text": "Reply with only the secret token from the attached file."},
                {"type": "input_file", "file_id": f["id"]}]}],
            "metadata": {"harness_id": h["id"]}, "stream": False}
    if ctx.model:
        task["model"] = ctx.model
    r2 = ctx.client.post("/v1/responses", body=task)
    assert r2.status == 200, (f"a task referencing the uploaded file returned HTTP {r2.status}: "
                              f"{r2.body[:200]!r}")
    ctx.validate(r2.json, "Response")
    text = json.dumps(r2.json.get("output") or [])
    return ("uploaded, referenced by id, and the harness echoed the token" if token in text
            else "uploaded and accepted by id (the harness did not echo the token, which the protocol "
                 "does not require)")


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
    mcp = [{"name": "conformance-mcp", "url": ctx.plugin_mcp_url,
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


# ══════════════════════════════════════════════════════════════════════════════════════
# Full — plugins (capability `plugins`, Plugins chapter)
# ══════════════════════════════════════════════════════════════════════════════════════
# Every P- check creates its harnesses through _managed_harness, so F-07 below removes them.

_AP_MANIFEST_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
_AP_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"


def _plugins_supported(ctx) -> None:
    """Skip, with the reason, unless discovery reports the capability. Plugins are a MAY."""
    d = ctx.state.get("discovery") or ctx.client.get("/v1/uhp", auth=False).json or {}
    ctx.state["discovery"] = d
    if not (d.get("capabilities") or {}).get("plugins"):
        raise Skip("this server reports the plugins capability false or absent, and the Plugins "
                   "chapter is optional at every class")


def _package(name: str = "uhp-conformance-plugin", *, manifest: dict | None = None,
             mcp: dict | None = None, skill: bool = True, extra: list | None = None) -> list[dict]:
    """An Agent Plugins package as UHP files: manifest, mcp.json, one skill folder with a nested
    reference and a binary member. `manifest=None` omits plugin.json; `mcp=None` omits mcp.json."""
    files = []
    if manifest is not None:
        files.append({"path": "plugin.json", "content": json.dumps(manifest)})
    if mcp is not None:
        files.append({"path": "mcp.json", "content": json.dumps(mcp)})
    if skill:
        files += [
            {"path": "skills/conformance-skill/SKILL.md",
             "content": "---\nname: conformance-skill\ndescription: A conformance fixture.\n---\n\n"
                        "See references/data.md.\n"},
            {"path": "skills/conformance-skill/references/data.md", "content": "nested reference\n"},
            {"path": "bin/tool.bin", "content_b64": "AAECAwQF"},
        ]
    return files + (extra or [])


_PLUGIN_MANIFEST = {"$schema": _AP_MANIFEST_SCHEMA, "name": "uhp-conformance-plugin",
                    "version": "1.0.0", "description": "A conformance fixture."}


def _plugin_mcp(ctx) -> dict:
    """The fixture plugin's mcp.json. Its HTTP server is the one the run was pointed at
    (`--plugin-mcp-url`), which resolves and answers: a host may refuse a server it cannot reach at
    configuration time and record that in `skipped`, and with an unresolvable placeholder these
    checks measured that refusal instead of the plugin (the hosted HarnessRouter, 2026-09-27)."""
    return {"$schema": _AP_MCP_SCHEMA, "mcpServers": {
        "conformance-http": {"type": "streamable-http", "url": ctx.plugin_mcp_url},
        "conformance-stdio": {"type": "stdio", "command": "./bin/tool.bin",
                              "args": ["--data", "${PLUGIN_DATA}"]},
    }}


def _plugin_files_of(ctx) -> list[dict]:
    return _package(manifest=_PLUGIN_MANIFEST, mcp=_plugin_mcp(ctx))


_PLUGIN_PATHS = sorted(f["path"] for f in _package(manifest=_PLUGIN_MANIFEST, mcp={"mcpServers": {}}))


def _error_code(r) -> str:
    return str((((r.json or {}) if isinstance(r.json, dict) else {}).get("error") or {}).get("code") or "")


def _plugin_files(ctx, hid: str, name: str) -> list[str]:
    r = ctx.client.get(f"/v1/harnesses/{hid}/plugins/{name}/files")
    assert r.status == 200, f"plugin files endpoint returned HTTP {r.status}"
    body = r.json
    files = body.get("files") if isinstance(body, dict) else body
    ctx.state["_last_plugin_files"] = files or []
    return sorted(str((f or {}).get("path")) for f in (files or []))


@check("P-01", "The plugins capability names the manifest schemas it installs", "full",
       f"{SPEC}/plugins.md#7-discovery")
def p01(ctx):
    _plugins_supported(ctx)
    schemas = (ctx.state.get("discovery") or {}).get("plugin_schemas")
    assert isinstance(schemas, list) and schemas and all(isinstance(s, str) and s for s in schemas), (
        f"capabilities.plugins is true but plugin_schemas is {schemas!r}. A client cannot tell which "
        "packages this server will install, so it cannot offer any.")
    return f"plugin_schemas={schemas}"


@check("P-02", "A plugin package round-trips, and is derived rather than copied", "full",
       f"{SPEC}/plugins.md#2-the-plugin-object")
def p02(ctx):
    _plugins_supported(ctx)
    h = _managed_harness(ctx, plugins=[{"files": _plugin_files_of(ctx)}])
    got = ctx.client.get(f"/v1/harnesses/{h['id']}").json or {}
    plugins = got.get("plugins") or []
    assert len(plugins) == 1, f"installed one plugin, read back {len(plugins)}"
    pl = plugins[0]
    ctx.validate(pl, "Plugin")
    assert pl.get("name") == "uhp-conformance-plugin", (
        f"the plugin's name is {pl.get('name')!r}; it must be the manifest's name")
    assert (pl.get("manifest") or {}).get("name") == "uhp-conformance-plugin", (
        "manifest was not derived from plugin.json")
    servers = {s.get("name"): s for s in (pl.get("mcpServers") or [])}
    assert set(servers) == {"conformance-http", "conformance-stdio"}, (
        f"mcpServers derived from mcp.json are {sorted(servers)}, expected both entries")
    assert servers["conformance-http"].get("transport") == "http", "streamable-http did not map to http"
    st = servers["conformance-stdio"]
    assert st.get("transport") == "stdio" and st.get("command") == "./bin/tool.bin", (
        f"the stdio entry came back as {st}")
    assert "${PLUGIN_DATA}" in json.dumps(st.get("args")), (
        "the placeholder was expanded in what the client sees; a sandbox path is not the client's "
        "business and changes from turn to turn")
    assert [s.get("name") for s in pl.get("skills") or []] == ["conformance-skill"], (
        f"skills derived from skills/ are {pl.get('skills')}, expected conformance-skill")
    assert isinstance(pl.get("skipped"), list) and not pl["skipped"], (
        f"skipped must be present and empty for a clean package, got {pl.get('skipped')!r}")
    # The compatibility rule: the direct fields report what was written to them, and nothing was.
    assert not got.get("mcpServers") and not got.get("skills"), (
        f"the harness's own mcpServers/skills absorbed the plugin's ({got.get('mcpServers')}, "
        f"{got.get('skills')}). A client that PUTs back what it read would then install them twice, "
        "and uninstalling the plugin would leave them behind.")
    paths = _plugin_files(ctx, h["id"], "uhp-conformance-plugin")
    assert paths == _PLUGIN_PATHS, (
        f"the package did not round-trip: got {paths}, expected {_PLUGIN_PATHS}. A plugin's skills "
        "carry references and its stdio servers carry executables; a partial package breaks both.")
    assert "AAECAwQF" in json.dumps(ctx.state.get("_last_plugin_files")), (
        "the binary member's content_b64 was not preserved byte-for-byte")
    return f"{len(paths)} files, 2 servers, 1 skill derived"


@check("P-03", "A package without plugin.json is refused at configuration time", "full",
       f"{SPEC}/plugins.md#21-files")
def p03(ctx):
    _plugins_supported(ctx)
    base = _supported_base(ctx)
    r = ctx.client.post("/v1/harnesses", body={
        "name": "uhp-conformance-nomanifest", "base": base,
        "plugins": [{"files": _package(manifest=None, mcp=_plugin_mcp(ctx))}]})
    if r.status == 200:
        ctx.client.delete(f"/v1/harnesses/{(r.json or {}).get('id')}")
        raise AssertionError(
            "a package with no plugin.json was accepted; there is no plugin without a manifest, and "
            "storing one means it is silently ignored at run time")
    assert r.status in (400, 422), f"expected 400/422, got HTTP {r.status}"
    assert _error_code(r) == "plugin_invalid", (
        f"refused with code {_error_code(r)!r}, expected plugin_invalid")
    return f"refused with HTTP {r.status} plugin_invalid"


@check("P-04", "A component name collision across the harness and a plugin is refused", "full",
       f"{SPEC}/plugins.md#42-one-namespace-checked-at-configuration-time")
def p04(ctx):
    _plugins_supported(ctx)
    base = _supported_base(ctx)
    direct = [{"name": "conformance-http", "url": ctx.plugin_mcp_url, "transport": "http"}]
    r = ctx.client.post("/v1/harnesses", body={
        "name": "uhp-conformance-collision", "base": base,
        "mcp_servers": direct, "plugins": [{"files": _plugin_files_of(ctx)}]})
    if r.status == 200:
        ctx.client.delete(f"/v1/harnesses/{(r.json or {}).get('id')}")
        raise AssertionError(
            "a plugin whose MCP server shares a name with the harness's own was accepted. The agent "
            "sees one flat namespace, so one of the two is silently lost at run time.")
    assert r.status == 409, f"expected 409, got HTTP {r.status}"
    assert _error_code(r) == "plugin_conflict", (
        f"refused with code {_error_code(r)!r}, expected plugin_conflict")
    detail = (((r.json or {}).get("error") or {}).get("detail") or {})
    assert detail.get("component") == "mcp_server" and detail.get("name") == "conformance-http", (
        f"detail does not say which component collided: {detail}")
    return "refused with 409 plugin_conflict"


@check("P-05", "An unrelated harness edit does not destroy plugin contents", "full",
       f"{SPEC}/plugins.md#3-installing-a-plugin")
def p05(ctx):
    _plugins_supported(ctx)
    h = _managed_harness(ctx, plugins=[{"files": _plugin_files_of(ctx)}])
    hid = h["id"]
    got = ctx.client.get(f"/v1/harnesses/{hid}").json or {}
    if got.get("mcpServers") or got.get("skills"):
        raise Skip("the harness's own mcpServers/skills carry the plugin's components, which P-02 "
                   "reports; a round trip on top of that cannot be measured separately")
    if _plugin_files(ctx, hid, "uhp-conformance-plugin") != _PLUGIN_PATHS:
        raise Skip("the package is already incomplete before any edit, which P-02 reports")
    # Rename only, sending back exactly what was read: the case the round-trip rule exists for.
    r = ctx.client.put(f"/v1/harnesses/{hid}", body={
        "name": "uhp-conformance-renamed", "base": got.get("base"),
        "plugins": got.get("plugins") or [], "skills": got.get("skills") or [],
        "mcp_servers": got.get("mcpServers") or [], "disabled_tools": got.get("disabledTools") or []})
    assert r.status == 200, f"rename returned HTTP {r.status}: {r.body[:160]!r}"
    paths = _plugin_files(ctx, hid, "uhp-conformance-plugin")
    assert paths == _PLUGIN_PATHS, (
        f"after renaming the harness the package is {paths} — the round trip lost contents, which a "
        "user cannot detect until an agent behaves oddly.")
    after = ctx.client.get(f"/v1/harnesses/{hid}").json or {}
    assert [p.get("name") for p in after.get("plugins") or []] == ["uhp-conformance-plugin"], (
        f"after the rename the plugin list is {after.get('plugins')}")


@check("P-06", "A harness exports as a package that installs, without its credentials", "full",
       f"{SPEC}/plugins.md#5-exporting-a-harness-as-a-plugin")
def p06(ctx):
    _plugins_supported(ctx)
    direct = [{"name": "conformance-direct", "url": ctx.plugin_mcp_url,
               "transport": "http", "headers": {"X-Team": "conformance"}, "auth": "secret-token"}]
    h = _managed_harness(ctx, mcp_servers=direct, skills=[_SKILL_BUNDLE])
    r = ctx.client.get(f"/v1/harnesses/{h['id']}/plugin")
    assert r.status == 200, f"export returned HTTP {r.status}"
    pl = r.json if isinstance(r.json, dict) else {}
    ctx.validate(pl, "Plugin")
    files = {str((f or {}).get("path")): (f or {}) for f in pl.get("files") or []}
    assert "plugin.json" in files, f"the export has no plugin.json; files: {sorted(files)}"
    manifest = json.loads(files["plugin.json"].get("content") or "{}")
    ctx.validate(manifest, "PluginManifest")
    assert manifest.get("name") == pl.get("name"), "the export's name and its manifest's disagree"
    assert "mcp.json" in files, f"the enabled MCP server was not exported; files: {sorted(files)}"
    mcp = json.loads(files["mcp.json"].get("content") or "{}")
    entry = (mcp.get("mcpServers") or {}).get("conformance-direct") or {}
    assert entry.get("type") == "streamable-http" and entry.get("url"), (
        f"the http server exported as {entry}, expected type streamable-http with its url")
    assert "headers" not in entry and "auth" not in entry, (
        f"the export carries the operator's credentials: {sorted(entry)}. An export is meant to leave.")
    assert json.dumps(entry).find("secret-token") < 0, "the bearer token leaked into the export"
    skipped = json.dumps(pl.get("skipped") or [])
    assert "conformance-direct" in skipped, (
        "the omitted credentials are not recorded in skipped, so whoever imports the package cannot "
        "know what to re-enter")
    want = {"skills/uhp-conformance-skill/SKILL.md", "skills/uhp-conformance-skill/references/data.md",
            "skills/uhp-conformance-skill/assets/blob.bin"}
    assert want <= set(files), f"the skill folder was not exported whole: {sorted(files)}"
    # The promise is that the result installs unchanged.
    h2 = _managed_harness(ctx, plugins=[{"files": list(files.values())}])
    got = (ctx.client.get(f"/v1/harnesses/{h2['id']}").json or {}).get("plugins") or []
    assert len(got) == 1 and got[0].get("name") == pl.get("name"), (
        f"the exported package did not install into a fresh harness: {got}")
    assert [s.get("name") for s in got[0].get("mcpServers") or []] == ["conformance-direct"], (
        f"the reinstalled plugin's servers are {got[0].get('mcpServers')}")
    assert [s.get("name") for s in got[0].get("skills") or []] == ["uhp-conformance-skill"], (
        f"the reinstalled plugin's skills are {got[0].get('skills')}")
    return f"exported {len(files)} files as {pl.get('name')!r}, reinstalled"


@check("P-07", "A component that fails to load is recorded, not silently dropped", "full",
       f"{SPEC}/plugins.md#22-what-the-server-derives")
def p07(ctx):
    _plugins_supported(ctx)
    mcp = {"$schema": _AP_MCP_SCHEMA, "mcpServers": {
        "conformance-http": {"type": "streamable-http", "url": ctx.plugin_mcp_url},
        "conformance-broken": {"type": "carrier-pigeon", "url": ctx.plugin_mcp_url}}}
    h = _managed_harness(ctx, plugins=[{"files": _package(manifest=_PLUGIN_MANIFEST, mcp=mcp)}])
    pl = ((ctx.client.get(f"/v1/harnesses/{h['id']}").json or {}).get("plugins") or [{}])[0]
    names = [s.get("name") for s in pl.get("mcpServers") or []]
    assert names == ["conformance-http"], (
        f"derived servers are {names}: the invalid entry must be skipped and the valid one kept")
    skipped = pl.get("skipped") or []
    hit = [s for s in skipped if "conformance-broken" in str(s.get("path"))]
    assert hit, (
        f"the invalid server was dropped without a skipped entry (skipped={skipped}). Ignoring is "
        "allowed; silent ignoring is not.")
    assert hit[0].get("reason"), "the skipped entry carries no reason"
    return f"skipped: {hit[0].get('path')}"


@check("P-08", "A disabled plugin stays installed, and stays disabled", "full",
       f"{SPEC}/plugins.md#3-installing-a-plugin")
def p08(ctx):
    _plugins_supported(ctx)
    h = _managed_harness(ctx, plugins=[{"files": _plugin_files_of(ctx), "enabled": False}])
    pl = ((ctx.client.get(f"/v1/harnesses/{h['id']}").json or {}).get("plugins") or [{}])[0]
    assert pl.get("name") == "uhp-conformance-plugin", f"the disabled plugin was not kept: {pl}"
    assert pl.get("enabled") is False, (
        "enabled: false was not preserved; a client cannot tell an inert plugin from an active one, "
        "and the difference decides whether a third party's server is launched")


@check("P-09", "An unsupported manifest schema is refused, naming the supported ones", "full",
       f"{SPEC}/plugins.md#22-what-the-server-derives")
def p09(ctx):
    _plugins_supported(ctx)
    base = _supported_base(ctx)
    manifest = {**_PLUGIN_MANIFEST,
                "$schema": "https://agent-plugins.org/schemas/0.0.1/plugin.schema.json"}
    r = ctx.client.post("/v1/harnesses", body={
        "name": "uhp-conformance-oldschema", "base": base,
        "plugins": [{"files": _package(manifest=manifest, mcp=None)}]})
    if r.status == 200:
        ctx.client.delete(f"/v1/harnesses/{(r.json or {}).get('id')}")
        raise AssertionError(
            "a manifest targeting an Agent Plugins version this server never claimed to support was "
            "accepted; its rules were not applied, so whatever it declares was interpreted by guess")
    assert r.status == 422, f"expected 422, got HTTP {r.status}"
    assert _error_code(r) == "unsupported_plugin_schema", (
        f"refused with code {_error_code(r)!r}, expected unsupported_plugin_schema")
    supported = ((((r.json or {}).get("error") or {}).get("detail") or {}).get("supported"))
    assert isinstance(supported, list) and supported, (
        f"detail.supported is {supported!r}; the refusal must say what would have been accepted")
    return f"refused; supported={supported}"


@check("P-11", "A plugin's MCP server answers the agent's tool call", "full",
       f"{SPEC}/plugins.md#4-binding-at-run-time")
def p11(ctx):
    """The one plugin check that runs a task. P-02 to P-10 read what the server derived and
    refused; none of them shows that an agent can reach the plugin's server. This one installs a
    plugin whose only server is the fixture the run was pointed at, asks the agent to call the
    fixture's tool with a nonce, and expects the fixture's answer back: the tool's output is a
    function of the nonce that the agent cannot produce without calling it."""
    _plugins_supported(ctx)
    from .fixture import fixture_answer, TOOL_NAME
    base_h = _harness(ctx)
    nonce = uuid.uuid4().hex[:10]
    mcp = {"$schema": _AP_MCP_SCHEMA, "mcpServers": {
        "conformance-http": {"type": "streamable-http", "url": ctx.plugin_mcp_url}}}
    body = {"name": f"uhp-conformance-p11-{nonce[:4]}", "base": base_h.get("base") or _supported_base(ctx),
            "plugins": [{"files": _package(manifest=_PLUGIN_MANIFEST, mcp=mcp, skill=False)}]}
    model = ctx.model or str(base_h.get("defaultModel") or "").strip()
    if model:
        body["default_model"] = model
    r = ctx.client.post("/v1/harnesses", body=body)
    if r.status != 200:
        raise Skip(f"could not create a harness carrying the plugin (HTTP {r.status}: {r.body[:160]!r})")
    h = r.json or {}
    ctx.state.setdefault("_cleanup_harnesses", []).append(h.get("id"))
    pl = ((ctx.client.get(f"/v1/harnesses/{h['id']}").json or {}).get("plugins") or [{}])[0]
    names = [s.get("name") for s in pl.get("mcpServers") or []]
    assert names == ["conformance-http"], (
        f"the plugin's server was not derived (servers={names}, skipped={pl.get('skipped')}); the "
        f"fixture at {ctx.plugin_mcp_url} must be reachable from this server")
    task = {"input": (f"Call the tool {TOOL_NAME} with the text {nonce} and reply with exactly what it "
                      "returns, nothing else."),
            "metadata": {"harness_id": h["id"]}, "stream": False}
    if model:
        task["model"] = model
    resp = ctx.client.post("/v1/responses", body=task)
    assert resp.status == 200, f"POST /v1/responses returned HTTP {resp.status}: {resp.body[:200]!r}"
    text = json.dumps((resp.json or {}).get("output") or [])
    want = fixture_answer(nonce)
    assert want in text, (
        f"the reply does not carry the fixture's answer {want!r} (status={(resp.json or {}).get('status')}, "
        f"output={text[:240]!r}). The agent never reached the plugin's server: either the host did "
        f"not bind it at run time or the sandbox cannot reach {ctx.plugin_mcp_url}.")
    return f"the fixture answered through the plugin in {resp.elapsed_s:.1f}s"


@check("P-10", "Two plugins with the same name are refused", "full",
       f"{SPEC}/plugins.md#3-installing-a-plugin")
def p10(ctx):
    _plugins_supported(ctx)
    base = _supported_base(ctx)
    twin = _package(manifest=_PLUGIN_MANIFEST, mcp=None, skill=False)
    r = ctx.client.post("/v1/harnesses", body={
        "name": "uhp-conformance-twins", "base": base,
        "plugins": [{"files": _plugin_files_of(ctx)}, {"files": twin}]})
    if r.status == 200:
        ctx.client.delete(f"/v1/harnesses/{(r.json or {}).get('id')}")
        raise AssertionError("two plugins named uhp-conformance-plugin were installed side by side; "
                             "the name is the address of the files endpoint, so one is unreachable")
    assert r.status == 409, f"expected 409, got HTTP {r.status}"
    assert _error_code(r) == "plugin_conflict", (
        f"refused with code {_error_code(r)!r}, expected plugin_conflict")
    return "refused with 409 plugin_conflict"


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


@check("F-08", "A session can be deleted at the protocol path", "full", f"{SPEC}/sessions.md#6-deleting")
def f08(ctx):
    # Its own session, never the cached one: later checks still read the shared session, and a
    # check that deletes what its neighbours depend on would fail them for the wrong reason.
    h = _harness(ctx)
    body = {"input": PROMPT, "metadata": {"harness_id": h["id"]}, "stream": False}
    if ctx.model:
        body["model"] = ctx.model
    r = ctx.client.post("/v1/responses", body=body)
    assert r.status == 200, f"the task to be deleted returned HTTP {r.status}: {r.body[:200]!r}"
    sid = ((r.json or {}).get("metadata") or {}).get("session_id")
    if not sid:
        raise Skip("the task did not return a session_id, so there is no session to delete")
    # §6 names the endpoint. The older /v1/traces/{id} MAY be kept, but the named path must work —
    # that is what lets a client delete a session on any server without per-implementation lore.
    gone = ctx.client.delete(f"/v1/sessions/{sid}")
    assert 200 <= gone.status < 300, (
        f"DELETE /v1/sessions/{{id}} returned HTTP {gone.status}. §6 names this path for session "
        "deletion; a server may keep /v1/traces/{id} besides, but the named one must work.")
    after = ctx.client.get(f"/v1/sessions/{sid}")
    assert after.status == 404, (
        f"a deleted session still resolves (GET returned HTTP {after.status}); §6 requires 404 "
        "afterwards, otherwise the client cannot tell 'deleted' from 'failed to delete'.")
    return f"deleted {sid}, now 404"


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
# Core — reserved request fields
# ══════════════════════════════════════════════════════════════════════════════════════
# `tools` and `include` are reserved and ignored (Tasks §1.4), which is two requirements and
# not one. A server must accept a request carrying them, and it must say that it ignored them.
# Both directions are currently unmeasured: no other check sends either field, so a server that
# rejected them outright and a server that silently honoured them would both pass the suite.
#
# The second direction is the one with teeth. §1.1 requires ignoring to be observable for the
# same reason §1.3 requires model substitution to be reported: a client that cannot tell a
# dropped field from an honoured one has to assume the worst about every field it sends.

def _run_with_reserved(ctx) -> dict:
    """One task carrying both reserved fields, run once and cached."""
    if "reserved" in ctx.state:
        return ctx.state["reserved"]
    h = _harness(ctx)
    body = {"input": PROMPT, "metadata": {"harness_id": h["id"]}, "stream": False,
            # Deliberately plausible under both readings of `tools` that implementers have
            # reached for, so a server that quietly acts on either is exercised rather than
            # merely handed something it can dismiss as malformed.
            "tools": [{"type": "function", "name": "uhp_conformance_probe",
                       "description": "Must never be offered to the agent.",
                       "parameters": {"type": "object", "properties": {}}},
                      {"name": "uhp-conformance-mcp", "url": ctx.plugin_mcp_url,
                       "transport": "http"}],
            "include": ["uhp.conformance.not_a_real_value"]}
    if ctx.model:
        body["model"] = ctx.model
    r = ctx.client.post("/v1/responses", body=body)
    ctx.state["reserved"] = r
    return r


@check("T-08", "A request carrying reserved fields is accepted, not rejected", "core",
       f"{SPEC}/tasks.md#11-request-fields")
def t08(ctx):
    r = _run_with_reserved(ctx)
    assert r.status == 200, (
        f"a task sending `tools` and `include` returned HTTP {r.status}: {r.body[:200]!r}. §1.1 "
        "requires a server to ignore rather than reject, and §1.4 makes both fields reserved — a "
        "client that sends them for wire compatibility with another API must not be refused.")
    d = r.json or {}
    assert d.get("status") in {"completed", "incomplete"}, (
        f"the task carrying reserved fields ended {d.get('status')!r}; accepting a request means "
        "running it, not failing it later for the same reason")
    return "accepted and ran"


@check("T-09", "Reserved fields are reported in metadata.ignored_fields", "core",
       f"{SPEC}/tasks.md#14-reserved-fields-tools-and-include")
def t09(ctx):
    r = _run_with_reserved(ctx)
    if r.status != 200:
        raise Skip("the request carrying reserved fields was not accepted (see T-08)")
    meta = ((r.json or {}).get("metadata") or {})
    got = meta.get("ignored_fields")
    assert got is not None, (
        "the response has no `metadata.ignored_fields` for a request that sent `tools` and "
        "`include`. §1.1 requires ignoring to be observable: silently dropping a field is "
        "indistinguishable from acting on it, and the client cannot tell which happened.")
    assert isinstance(got, list) and all(isinstance(x, str) for x in got), (
        f"metadata.ignored_fields is {type(got).__name__}, expected an array of field names")
    missing = [f for f in ("tools", "include") if f not in got]
    assert not missing, (
        f"the request sent `tools` and `include`, and ignored_fields names {got} — missing "
        f"{missing}. §1.4 makes both reserved, so both must be reported whenever they are sent.")
    return f"ignored_fields={got}"


@check("T-10", "A task that sends no reserved field is not told one was ignored", "core",
       f"{SPEC}/tasks.md#11-request-fields")
def t10(ctx):
    """The other half of T-09. A server that hardcodes the list reports fields the client never
    sent, which is a different lie in the same place: it tells a client its request was altered
    when it was not."""
    d = (_run_blocking(ctx).json or {})
    got = ((d.get("metadata") or {}).get("ignored_fields")) or []
    over = [f for f in ("tools", "include") if f in got]
    assert not over, (
        f"the response names {over} in ignored_fields for a request that sent neither. "
        "ignored_fields reports what this request carried and the server dropped, not a "
        "catalogue of what the server would drop.")

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
    assert url, (
        f"the share object carries no `url` (keys: {sorted(d)[:8]}). Sessions §5 requires the "
        "share to say where its view is served; without it a client cannot open, audit, or "
        "revoke what it just published.")
    try:
        ctx.validate(d, "SessionShare")
    except Skip:
        # Validator unavailable (no jsonschema, or the schema file is not alongside an installed
        # wheel). The structural asserts above already ran; degrading here is the difference
        # between one weaker check and the ENTIRE R-series cascade-skipping through this cached
        # mint. A real schema VIOLATION is an AssertionError and still fails.
        pass
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

    # §5 names the endpoint: DELETE on the share endpoint revokes. What used to be a search
    # over guessed paths, ending in a skip that blamed the specification, is now an assertion.
    r = ctx.client.delete(f"/v1/sessions/{sid}/share")
    assert 200 <= r.status < 300, (
        f"DELETE /v1/sessions/{{id}}/share returned HTTP {r.status}. §5 names this endpoint for "
        "revocation; a server may keep other forms besides, but the named one must work — that "
        "is what makes revocation portable instead of per-implementation folklore.")
    done = f"DELETE /v1/sessions/{sid}/share"

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


@check("R-08", "A bodyless POST publishes, as §5 says it does", "full",
       f"{SPEC}/sessions.md#5-session-sharing")
def r08(ctx):
    """§5: "a body is OPTIONAL; no body means publish."

    Named in harnessrouter#53 as the one sentence of the chapter nothing enforced. The R-series
    mints through a helper that retries a 400/422 with {"enabled": true}, because a server
    speaking only the toggle dialect would otherwise skip all seven checks — so the retry is what
    makes the series portable, and it is also what hides this sentence. A toggle-only server
    passes R-01 through R-07 on the strength of a request §5 does not require anyone to accept,
    while refusing the one it does.

    That is worth a check rather than a note because the two servers this suite is measured
    against both happen to publish on a bodyless POST today, so nothing in either tree would
    notice if one stopped. A sentence enforced by coincidence is enforced until the coincidence
    ends.

    Deliberately NOT using _mint_share: the retry is the thing under test. And deliberately not
    gated on _share either — that helper caches "revoked by R-06" once R-06 has run, so gating on
    it would make this check skip on every conformant server, which is the failure mode it exists
    to catch. The two skip conditions are restated here instead, from discovery and from the
    status code, so the answer does not depend on what ran before."""
    caps = (ctx.state.get("discovery") or {}).get("capabilities") or {}
    if caps.get("session_sharing") is False:
        raise Skip("this server reports session_sharing false, and Sessions §5 is a MAY")
    sid = _shared_session_id(ctx)

    r = ctx.client.post(f"/v1/sessions/{sid}/share")
    if r.status in (404, 405, 501):
        # Not-implemented answers, exactly as _share reads them. A server refusing only the
        # *body* answers 400/422 — a method-level refusal cannot be the toggle dialect — so
        # this is not an escape hatch for the mistake below.
        raise Skip(f"POST /v1/sessions/{{id}}/share returned HTTP {r.status}: this server does "
                   "not publish shared views, which Sessions §5 permits")
    assert 200 <= r.status < 300, (
        f"POST /v1/sessions/{{id}}/share with no body returned HTTP {r.status}: {r.body[:160]!r}. "
        "§5 makes the body OPTIONAL and says no body means publish. A server that accepts only "
        "{\"enabled\": true} has made a field mandatory that the specification made optional, so "
        "a conformant client written against §5 cannot publish here at all.")
    d = r.json if isinstance(r.json, dict) else {}
    assert d.get("id") and d.get("url"), (
        f"the bodyless POST answered HTTP {r.status} but not a share object (keys: "
        f"{sorted(d)[:8]}). Accepting the request and returning something else is the same "
        "failure one step later: the caller still cannot open what it just published.")

    # Best-effort tidy-up, unasserted. This check publishes a link on a real server and R-06 has
    # already proved DELETE revokes, so leaving one live would be a surprise for whoever ran the
    # suite — but a failure here is R-06's finding to report, not this one's, and asserting it
    # would diagnose one bug twice.
    ctx.client.delete(f"/v1/sessions/{sid}/share")
    return "published with no body"


# ══════════════════════════════════════════════════════════════════════════════════════
# Environments (2026-09-28) — optional capability; a project's files and installed dependencies,
# built once and read by every session that names it. Checks EN-01 to EN-06 need no model: they
# drive the object, its files, a build and the reference. EN-07 runs one task on it.
# ══════════════════════════════════════════════════════════════════════════════════════
def _environments_supported(ctx) -> None:
    d = ctx.state.get("discovery") or ctx.client.get("/v1/uhp", auth=False).json or {}
    ctx.state["discovery"] = d
    if not (d.get("capabilities") or {}).get("environments"):
        raise Skip("this server reports the environments capability false or absent, and the "
                   "Environments chapter is optional at every class")


def _managed_environment(ctx) -> dict:
    """One environment for the whole series, created once with a file and an empty requirements
    manifest (a build that needs no network), remembered for cleanup."""
    if ctx.state.get("environment"):
        return ctx.state["environment"]
    r = ctx.client.post("/v1/environments", body={"name": f"uhp-conformance-{uuid.uuid4().hex[:6]}",
                                                  "description": "the conformance suite's environment",
                                                  "entry": "python3 run.py"})
    assert r.status == 200, f"POST /v1/environments returned HTTP {r.status}: {r.text[:200]}"
    e = r.json or {}
    ctx.validate(e, "Environment")
    ctx.state["environment"] = e
    ctx.state.setdefault("_cleanup_environments", []).append(e.get("id"))
    return e


def _built_environment(ctx) -> dict:
    """The environment with a finished build, waited for once."""
    e = _managed_environment(ctx)
    if ctx.state.get("environment_built"):
        return ctx.state["environment_built"]
    eid = e["id"]
    for path, body in (("run.py", b"import sys\nprint(sys.prefix)\n"), ("requirements.txt", b""),
                       ("data/hello.txt", b"hello from the environment\n")):
        r = ctx.client.put(f"/v1/environments/{eid}/files/{path}", raw=body, content_type="application/octet-stream")
        assert r.status == 200, f"PUT files/{path} returned HTTP {r.status}: {r.text[:200]}"
    r = ctx.client.post(f"/v1/environments/{eid}/build")
    assert r.status == 200, f"POST build returned HTTP {r.status}: {r.text[:200]}"
    n = int((r.json or {}).get("version") or 0)
    assert n >= 1, f"the build did not name a version: {r.json}"
    deadline = time.time() + ctx.task_timeout
    rec = {}
    while time.time() < deadline:
        rec = ctx.client.get(f"/v1/environments/{eid}/builds/{n}").json or {}
        if rec.get("status") in ("ready", "failed"):
            break
        time.sleep(2)
    assert rec.get("status") == "ready", f"the build did not become ready: {rec.get('status')!r} {str(rec.get('error') or '')[:200]}"
    e = ctx.client.get(f"/v1/environments/{eid}").json or {}
    ctx.state["environment_built"] = e
    return e


@check("EN-01", "An environment is created with a fixed mount path and reads back", "full",
       f"{SPEC}/environments.md#2-the-environment-object")
def en01(ctx):
    _environments_supported(ctx)
    e = _managed_environment(ctx)
    assert str(e.get("id") or "").startswith("henv_"), f"id {e.get('id')!r} does not carry the henv_ prefix"
    assert e.get("status") == "empty" and e.get("version") is None, (
        f"a new environment must be empty with no version; got status={e.get('status')!r} version={e.get('version')!r}")
    assert str(e.get("mount") or "").startswith("/") and e["mount"].endswith("/" + e["slug"]), (
        f"mount {e.get('mount')!r} must be an absolute path ending in the slug {e.get('slug')!r}")
    got = ctx.client.get(f"/v1/environments/{e['id']}").json or {}
    ctx.validate(got, "Environment")
    assert got.get("slug") == e["slug"] and got.get("mount") == e["mount"], "the slug and mount must be stable across reads"
    return f"{e['id']} at {e['mount']}"


@check("EN-02", "Files go in by path and come back byte for byte; escapes are refused", "full",
       f"{SPEC}/environments.md#3-files")
def en02(ctx):
    _environments_supported(ctx)
    e = _managed_environment(ctx)
    eid = e["id"]
    body = b"nested\x00bytes\n"
    r = ctx.client.put(f"/v1/environments/{eid}/files/probe/nested/blob.bin", raw=body, content_type="application/octet-stream")
    assert r.status == 200, f"PUT returned HTTP {r.status}"
    r = ctx.client.get(f"/v1/environments/{eid}/files/probe/nested/blob.bin")
    assert r.status == 200 and r.body == body, "the bytes must come back exactly as sent"
    tree = ctx.client.get(f"/v1/environments/{eid}/files").json or {}
    ctx.validate(tree, "EnvironmentFileList")
    paths = {x.get("path") for x in tree.get("entries") or []}
    assert "probe/nested/blob.bin" in paths and "probe/nested" in paths, f"the tree must list the file and its directories: {sorted(paths)[:10]}"
    r = ctx.client.put(f"/v1/environments/{eid}/files/..%2Fescape.txt", raw=b"no", content_type="application/octet-stream")
    assert r.status in (400, 404, 422), f"a path that escapes the root must be refused, got HTTP {r.status}"
    assert ctx.client.delete(f"/v1/environments/{eid}/files/probe").status == 200, "a directory tree is removable"
    paths = {x.get("path") for x in (ctx.client.get(f"/v1/environments/{eid}/files").json or {}).get("entries") or []}
    assert "probe" not in paths, "the removed tree must be gone"
    return "round trip, tree, escape refused, removal"


@check("EN-03", "A build snapshots the source and becomes the active version", "full",
       f"{SPEC}/environments.md#4-builds-and-versions")
def en03(ctx):
    _environments_supported(ctx)
    e = _built_environment(ctx)
    assert e.get("status") == "ready" and e.get("version") == 1, f"after the first build: status={e.get('status')!r} version={e.get('version')!r}"
    vers = ctx.client.get(f"/v1/environments/{e['id']}/versions").json or {}
    assert vers.get("active") == 1 and [v.get("version") for v in vers.get("versions") or []] == [1], f"versions: {vers}"
    b = ctx.client.get(f"/v1/environments/{e['id']}/builds/1").json or {}
    ctx.validate(b, "EnvironmentBuild")
    assert b.get("status") == "ready" and isinstance(b.get("packages"), list), "a ready build lists its packages"
    return f"version 1 ready, {len(b.get('packages') or [])} packages"


@check("EN-04", "Editing the source changes nothing until the next build; rollback is a pointer", "full",
       f"{SPEC}/environments.md#4-builds-and-versions")
def en04(ctx):
    _environments_supported(ctx)
    e = _built_environment(ctx)
    eid = e["id"]
    ctx.client.put(f"/v1/environments/{eid}/files/data/hello.txt", raw=b"changed\n", content_type="application/octet-stream")
    assert (ctx.client.get(f"/v1/environments/{eid}").json or {}).get("version") == 1, "an edit must not change the active version"
    r = ctx.client.post(f"/v1/environments/{eid}/build")
    assert r.status == 200 and (r.json or {}).get("version") == 2, f"the second build must be version 2: HTTP {r.status} {r.json}"
    deadline = time.time() + ctx.task_timeout
    rec = {}
    while time.time() < deadline:
        rec = ctx.client.get(f"/v1/environments/{eid}/builds/2").json or {}
        if rec.get("status") in ("ready", "failed"):
            break
        time.sleep(2)
    assert rec.get("status") == "ready", f"build 2: {rec.get('status')!r} {str(rec.get('error') or '')[:200]}"
    assert (ctx.client.get(f"/v1/environments/{eid}").json or {}).get("version") == 2, "a finished build becomes the active version"
    r = ctx.client.post(f"/v1/environments/{eid}/versions/1/activate")
    assert r.status == 200 and (r.json or {}).get("version") == 1, f"activating version 1 must make it active: HTTP {r.status} {r.json}"
    r = ctx.client.post(f"/v1/environments/{eid}/versions/99/activate")
    assert r.status in (404, 409), f"activating a version that was never built must be refused, got HTTP {r.status}"
    assert _error_code(r) in ("environment_not_ready", "not_found", ""), f"unexpected code {_error_code(r)!r}"
    return "edit invisible, build 2 active, rollback to 1"


@check("EN-05", "A harness names an environment; a task on an unbuilt one is refused before it starts", "full",
       f"{SPEC}/environments.md#5-attaching-an-environment")
def en05(ctx):
    _environments_supported(ctx)
    e = _built_environment(ctx)
    h = _managed_harness(ctx, environment=e["id"])
    got = ctx.client.get(f"/v1/harnesses/{h['id']}").json or {}
    assert got.get("environment") == e["id"], f"the harness must report the environment it names: {got.get('environment')!r}"
    r = ctx.client.post("/v1/harnesses", body={"name": "uhp-conformance-bad-env", "base": _supported_base(ctx),
                                               "environment": "henv_00000000000000000000000000000000"})
    assert r.status == 404 and _error_code(r) == "environment_not_found", (
        f"a harness naming an environment that is not there must be refused with environment_not_found: HTTP {r.status} {_error_code(r)!r}")
    if r.status == 200:
        ctx.client.delete(f"/v1/harnesses/{(r.json or {}).get('id')}")
    empty = ctx.client.post("/v1/environments", body={"name": f"uhp-conformance-empty-{uuid.uuid4().hex[:6]}"}).json or {}
    ctx.state.setdefault("_cleanup_environments", []).append(empty.get("id"))
    r = ctx.client.post("/v1/responses", body={"input": PROMPT, "stream": False,
                                               "metadata": {"harness_id": h["id"], "environment": empty.get("id")}})
    assert r.status == 409 and _error_code(r) == "environment_not_ready", (
        f"a task on an environment with nothing built must be refused with environment_not_ready before it starts: HTTP {r.status} {_error_code(r)!r}")
    return "harness reference reads back; unknown refused; unbuilt refused"


@check("EN-06", "The environment's harness list names the harness that reads it", "full",
       f"{SPEC}/environments.md#5-attaching-an-environment")
def en06(ctx):
    _environments_supported(ctx)
    e = _built_environment(ctx)
    h = _managed_harness(ctx, environment=e["id"])
    ids = {x.get("id") for x in (ctx.client.get(f"/v1/environments/{e['id']}/harnesses").json or {}).get("harnesses") or []}
    assert h["id"] in ids, "the harness that names the environment must be listed"
    return f"{len(ids)} harness(es) read it"


@check("EN-07", "A task reads the environment at its mount path, read-only, and its session names it", "full",
       f"{SPEC}/environments.md#6-what-a-session-sees")
def en07(ctx):
    _environments_supported(ctx)
    e = _built_environment(ctx)
    h = _managed_harness(ctx, environment=e["id"])
    mount = e["mount"]
    body = {"input": (f"Run this shell command and reply with its output only, nothing else: "
                      f"cat {mount}/data/hello.txt; touch {mount}/write-probe 2>&1 | tail -1; echo WRITE_RC=$?"),
            "metadata": {"harness_id": h["id"]}, "stream": False}
    if ctx.model:
        body["model"] = ctx.model
    r = ctx.client.post("/v1/responses", body=body)
    assert r.status == 200, f"the task did not start: HTTP {r.status} {r.text[:200]}"
    resp = r.json or {}
    text = " ".join(str(c.get("text") or "") for it in resp.get("output") or [] for c in it.get("content") or [] if isinstance(c, dict))
    assert "hello from the environment" in text, f"the agent could not read the file at {mount}: {text[-300:]!r}"
    assert "WRITE_RC=0" not in text or "denied" in text.lower() or "read-only" in text.lower(), (
        f"a write under {mount} must fail (the layer is read-only): {text[-300:]!r}")
    meta = resp.get("metadata") or {}
    assert meta.get("environment") == e["id"], f"the response must name the environment the task read in metadata.environment: {meta.get('environment')!r}"
    sid = str(meta.get("session_id") or "")
    if sid:
        s = ctx.client.get(f"/v1/sessions/{sid}").json or {}
        assert s.get("environment") == e["id"], f"the session must name the environment its turn read: {s.get('environment')!r}"
    return f"read {mount}/data/hello.txt; write refused; metadata.environment reported"


@check("EN-09", "A package check answers for a known name and reports one that is not there", "full",
       f"{SPEC}/environments.md#4-builds-and-versions")
def en09(ctx):
    _environments_supported(ctx)
    r = ctx.client.get("/v1/environments/packages/check?manager=pip&spec=pip")
    if r.status == 404:
        raise Skip("the server offers no package check (optional in Environments §4)")
    assert r.status == 200, f"the check answered HTTP {r.status}: {r.text[:200]}"
    j = r.json or {}
    ctx.validate(j, "EnvironmentPackageCheck")
    assert j.get("exists") is True and j.get("latest"), f"pip must be known to PyPI with a latest version: {j}"
    r = ctx.client.get(f"/v1/environments/packages/check?manager=pip&spec=uhp-conformance-no-such-package-{uuid.uuid4().hex[:10]}")
    assert r.status == 200 and (r.json or {}).get("exists") is False, (
        f"a name that is not on the registry must be reported as not there, not refused: HTTP {r.status} {r.text[:160]}")
    r = ctx.client.get("/v1/environments/packages/check?manager=cargo&spec=serde")
    assert r.status == 400 and _error_code(r) == "environment_invalid", f"a manager the server does not build with must be refused with environment_invalid: HTTP {r.status}"
    return f"pip {j.get('latest')} known; an unknown name reported; an unknown manager refused"


@check("EN-08", "Configured environments are cleaned up", "full", f"{SPEC}/environments.md#2-the-environment-object")
def en08(ctx):
    ids = [i for i in ctx.state.get("_cleanup_environments") or [] if i]
    if not ids:
        raise Skip("no environments were created by earlier checks")
    # the harnesses that named them go first (F-07 ran before this series existed; its list is spent)
    for hid in [i for i in ctx.state.get("_cleanup_harnesses") or [] if i]:
        ctx.client.delete(f"/v1/harnesses/{hid}")
    left = []
    for eid in ids:
        r = ctx.client.delete(f"/v1/environments/{eid}")
        if r.status == 409:   # a build still running: wait for it, then delete
            for _ in range(60):
                time.sleep(2)
                if ctx.client.delete(f"/v1/environments/{eid}").status == 200:
                    break
        if ctx.client.get(f"/v1/environments/{eid}").status != 404:
            left.append(eid)
    assert not left, f"these environments still resolve after delete: {left}"
    return f"{len(ids)} removed"


# ══════════════════════════════════════════════════════════════════════════════════════
# Memories (2026-10-04) — optional capability; memory that outlasts a session, as a tree of
# memories with records kept by a provider the server is connected to. No model is needed: the
# checks drive the tree and the records through the public surface, on the first provider the
# server lists, and read that provider's capability document to know what it may be held to.
# One credential runs the suite, so what one principal may not read of another's is not checked here.
# ══════════════════════════════════════════════════════════════════════════════════════
def _memories_supported(ctx) -> dict:
    d = ctx.state.get("discovery") or ctx.client.get("/v1/uhp", auth=False).json or {}
    ctx.state["discovery"] = d
    if not (d.get("capabilities") or {}).get("memories"):
        raise Skip("this server reports the memories capability false or absent, and the "
                   "Memories chapter is optional at every class")
    if "memory_provider" not in ctx.state:
        rows = (ctx.client.get("/v1/memories/providers").json or {}).get("data") or []
        ctx.state["memory_provider"] = None
        for p in rows:      # the first provider this caller can actually create a memory with
            r = ctx.client.post("/v1/memories", body={"name": f"uhp-conformance-{uuid.uuid4().hex[:6]}",
                                                      "description": "the conformance suite's memory",
                                                      "provider": p.get("id")})
            if r.status == 200:
                ctx.state["memory_provider"], ctx.state["memory_root"] = p, r.json or {}
                ctx.state.setdefault("_cleanup_memories", []).append((r.json or {}).get("id"))
                break
    if not ctx.state["memory_provider"]:
        raise Skip("the server implements memories and no provider is connected for this caller: "
                   "a server keeps no memory of its own")
    return ctx.state["memory_provider"]


def _memory_child(ctx) -> dict:
    if ctx.state.get("memory_child"):
        return ctx.state["memory_child"]
    root = ctx.state["memory_root"]
    r = ctx.client.post("/v1/memories", body={"name": "accounts", "description": "what is known about each account",
                                              "parent_id": root["id"]})
    assert r.status == 200, f"POST /v1/memories with a parent returned HTTP {r.status}: {r.text[:200]}"
    ctx.state["memory_child"] = r.json or {}
    return ctx.state["memory_child"]


def _memory_fact(ctx) -> dict:
    """One stated record in the child memory, written once for the series."""
    if ctx.state.get("memory_fact"):
        return ctx.state["memory_fact"]
    child = _memory_child(ctx)
    r = ctx.client.post(f"/v1/memories/{child['id']}/records", body={
        "type": "fact", "content": "Quillon Freight renews its contract every March.",
        "attributes": {"account": "quillon"}, "written_by": {"kind": "member", "id": "someone-else"}})
    assert r.status == 200, f"POST records returned HTTP {r.status}: {r.text[:200]}"
    ctx.state["memory_fact"] = r.json or {}
    return ctx.state["memory_fact"]


def _recall_until(ctx, mid: str, body: dict, want_id: str, seconds: float = 40.0) -> dict:
    """A recall, repeated while a provider that indexes after it stores catches up."""
    deadline, res = time.time() + seconds, {}
    while True:
        r = ctx.client.post(f"/v1/memories/{mid}/recall", body=body)
        assert r.status == 200, f"POST recall returned HTTP {r.status}: {r.text[:200]}"
        res = r.json or {}
        if any(((x.get("record") or {}).get("id")) == want_id for x in res.get("results") or []) or time.time() > deadline:
            return res
        time.sleep(2)


@check("ME-01", "A memory is a node in a tree: it reads back with its parent, its ancestors and the caller's privileges", "full",
       f"{SPEC}/memories.md#2-the-memory-object")
def me01(ctx):
    _memories_supported(ctx)
    root, child = ctx.state["memory_root"], _memory_child(ctx)
    ctx.validate(root, "Memory")
    ctx.validate(child, "Memory")
    assert str(root.get("id") or "").strip(), "a memory must carry an id"
    assert child.get("parent_id") == root["id"] and child.get("ancestors") == [root["id"]], (
        f"the child must name its parent and its ancestors root first; got parent_id={child.get('parent_id')!r} ancestors={child.get('ancestors')!r}")
    assert child.get("provider") == root.get("provider"), "a child created without a provider must take its parent's"
    assert set(root.get("privileges") or []) == {"read", "write", "create", "delete"}, (
        f"whoever creates a memory holds all four privileges on it; got {root.get('privileges')!r}")
    kids = (ctx.client.get(f"/v1/memories?parent={root['id']}").json or {}).get("data") or []
    assert [k.get("id") for k in kids] == [child["id"]], f"the listing of a parent is its direct children; got {[k.get('id') for k in kids]}"
    r = ctx.client.get("/v1/memories/" + "uhp-conformance-no-such-memory-" + uuid.uuid4().hex)
    assert r.status == 404 and ((r.json or {}).get("error") or {}).get("code") == "memory_not_found", (
        f"an unknown memory must answer 404 memory_not_found; got HTTP {r.status}")
    return f"{root['id']} > {child['id']} on provider {root.get('provider')!r}"


@check("ME-02", "A stated record is kept as stated, marked untrusted, and its writer is the server's stamp", "full",
       f"{SPEC}/memories.md#4-records")
def me02(ctx):
    _memories_supported(ctx)
    rec = _memory_fact(ctx)
    ctx.validate(rec, "MemoryRecord")
    assert rec.get("content") == [{"type": "text", "text": "Quillon Freight renews its contract every March."}], (
        f"a string written as content must read back as one text part, in a list; got {rec.get('content')!r}")
    assert rec.get("trust") == "untrusted", "a record read back must be marked untrusted"
    assert rec.get("memory_id") == ctx.state["memory_child"]["id"], "the record must name the memory it is in"
    assert (rec.get("written_by") or {}).get("id") != "someone-else", (
        "written_by is stamped by the server from the authenticated caller; the client's own value was kept")
    assert (rec.get("attributes") or {}).get("account") == "quillon", f"attributes did not round-trip: {rec.get('attributes')!r}"
    got = ctx.client.get(f"/v1/memories/{rec['memory_id']}/records/{rec['id']}").json or {}
    assert got.get("id") == rec["id"] and got.get("content") == rec["content"], "the record does not read back by its id"
    w = rec.get("written_by") or {}
    assert w.get("kind") == "member" or str(w.get("kind") or "").startswith("x."), (
        f"a stated record's writer is a member (a person or an agent) or an x.-prefixed kind of the server's own; got {w.get('kind')!r}")
    assert w.get("type") in (None, "human", "agent"), f"a member's type is human or agent; got {w.get('type')!r}"
    assert w.get("id"), "written_by carries the id of who wrote the record"
    return f"{rec['id']} written by {rec.get('written_by')}"


@check("ME-03", "A question covers the memory and what is below it, names where each answer is, and never looks above", "full",
       f"{SPEC}/memories.md#61-search-finds-the-place-then-the-agent-walks")
def me03(ctx):
    prov = _memories_supported(ctx)
    rec, root, child = _memory_fact(ctx), ctx.state["memory_root"], ctx.state["memory_child"]
    signals = (prov.get("recall") or {}).get("signals") or []
    body = {"query": "when does Quillon Freight renew?"} if "query" in signals else {"text": "Quillon"}
    hit = lambda res: next((x for x in res.get("results") or [] if (x.get("record") or {}).get("id") == rec["id"]), None)  # noqa: E731
    res = _recall_until(ctx, child["id"], body, rec["id"])
    ctx.validate(res, "MemoryRecall")
    assert hit(res), f"the record was not recalled from its own memory with {body}"
    assert (res.get("parent") or {}).get("id") == root["id"], "a recall must name the parent the caller may read"
    # asked of the parent, the record below is found, and the result says which memory holds it
    up = _recall_until(ctx, root["id"], body, rec["id"])
    ctx.validate(up, "MemoryRecall")
    found = hit(up)
    assert found, "a question asked of the parent did not find the record in its child: recall covers the subtree"
    assert (found.get("memory") or {}).get("id") == child["id"], (
        f"the result names memory {(found.get('memory') or {}).get('id')!r}, the record is in {child['id']!r}")
    kid = next((c for c in up.get("children") or [] if c.get("id") == child["id"]), None)
    assert kid and kid.get("description") == "what is known about each account", (
        "a recall must name the children the caller may read, each with its description")
    # depth 0 is the memory alone
    alone = ctx.client.post(f"/v1/memories/{root['id']}/recall", body={**body, "depth": 0}).json or {}
    assert not hit(alone), "depth 0 returned a record of a child"
    # and nothing looks above: a record stated in the parent is not found from the child
    marker = "Vellacourt" + uuid.uuid4().hex[:6]
    top = ctx.client.post(f"/v1/memories/{root['id']}/records", body={"type": "fact", "content": f"{marker} is the parent's own fact."})
    assert top.status == 200, f"POST records on the parent answered {top.status}"
    probe = {"query": f"what is {marker}?"} if "query" in signals else {"text": marker}
    _recall_until(ctx, root["id"], {**probe, "depth": 0}, top.json["id"])
    below = ctx.client.post(f"/v1/memories/{child['id']}/recall", body=probe).json or {}
    assert not any((x.get("record") or {}).get("id") == top.json["id"] for x in below.get("results") or []), (
        "a recall on the child returned a record of its parent: a question never looks above")
    return f"found from {root['id']} in {child['id']}; depth 0 and the upward direction hold"


@check("ME-04", "What a provider does not do is said, never ignored", "full", f"{SPEC}/memories.md#63-the-response")
def me04(ctx):
    prov = _memories_supported(ctx)
    child = _memory_child(ctx)
    signals = (prov.get("recall") or {}).get("signals") or []
    notes = []
    for sig, body in (("query", {"query": "renewal"}), ("text", {"text": "March"}),
                      ("filters", {"filters": {"field": "attributes.account", "op": "eq", "value": "quillon"}})):
        r = ctx.client.post(f"/v1/memories/{child['id']}/recall", body=body)
        assert r.status == 200, f"recall with {sig} returned HTTP {r.status}: {r.text[:160]}"
        said = f"{sig}:not_supported" in ((r.json or {}).get("degraded") or [])
        assert said == (sig not in signals), (
            f"the provider declares signals {signals}; a recall by {sig} answered degraded={((r.json or {}).get('degraded'))}")
        notes.append(f"{sig}={'declared' if sig in signals else 'degraded'}")
    r = ctx.client.post(f"/v1/memories/{child['id']}/recall", body={})
    assert r.status == 422, f"a recall with no query, text or filters must be refused; got HTTP {r.status}"
    return ", ".join(notes)


@check("ME-05", "A revision appends a version and the earlier one stays in the history", "full",
       f"{SPEC}/memories.md#53-nothing-is-overwritten")
def me05(ctx):
    prov = _memories_supported(ctx)
    rec = _memory_fact(ctx)
    base = f"/v1/memories/{rec['memory_id']}/records/{rec['id']}"
    r = ctx.client.request("PATCH", base, body={"content": "Quillon Freight renews its contract every April."})
    if r.status == 422 and ((r.json or {}).get("error") or {}).get("code") == "memory_unsupported":
        raise Skip("this provider does not revise a record, and says so")
    assert r.status == 200, f"PATCH returned HTTP {r.status}: {r.text[:200]}"
    v2 = r.json or {}
    assert v2.get("id") == rec["id"] and "April" in str(v2.get("content")), "the revision must keep the record's id and carry the new content"
    assert int(v2.get("version") or 0) == int(rec.get("version") or 1) + 1, f"the version did not advance: {rec.get('version')} -> {v2.get('version')}"
    if (prov.get("history") or {}).get("content") != "versions":
        return "revised; this provider declares no version history"
    h = ctx.client.get(base + "/history")
    assert h.status == 200, f"GET history returned HTTP {h.status}"
    hist = (h.json or {}).get("data") or []
    assert len(hist) >= 2 and "March" in str(hist[0].get("content")) and "April" in str(hist[-1].get("content")), (
        f"the history must hold the earlier content first and the current last; got {[str(x.get('content'))[:40] for x in hist]}")
    assert hist[0].get("status") == "superseded" and hist[-1].get("status") == "active", (
        f"an earlier version is superseded and the last is active; got {[x.get('status') for x in hist]}")
    return f"{len(hist)} versions, the first superseded"


@check("ME-06", "A record of one memory is not found through another", "full", f"{SPEC}/memories.md#33-enforcement")
def me06(ctx):
    _memories_supported(ctx)
    rec, root = _memory_fact(ctx), ctx.state["memory_root"]
    for method, path, body in (("GET", f"/v1/memories/{root['id']}/records/{rec['id']}", None),
                               ("PATCH", f"/v1/memories/{root['id']}/records/{rec['id']}", {"content": "x"}),
                               ("DELETE", f"/v1/memories/{root['id']}/records/{rec['id']}", None)):
        r = ctx.client.request(method, path, body=body)
        assert r.status == 404, (
            f"{method} of a record through a memory it is not in must answer 404; got HTTP {r.status}: a record's id must "
            "not reach across memories")
    still = ctx.client.get(f"/v1/memories/{rec['memory_id']}/records/{rec['id']}")
    assert still.status == 200 and (still.json or {}).get("status") == "active", "the record must be untouched in its own memory"
    return "refused by id through the parent, intact in its own memory"


@check("ME-07", "Forget closes a record and keeps its trace; erase reports what could not be reached", "full",
       f"{SPEC}/memories.md#52-two-ways-to-remove")
def me07(ctx):
    _memories_supported(ctx)
    child = _memory_child(ctx)
    r = ctx.client.post(f"/v1/memories/{child['id']}/records", body={"type": "fact", "content": "Harlow Mills pays net sixty."})
    assert r.status == 200, f"POST records returned HTTP {r.status}"
    rid = (r.json or {})["id"]
    base = f"/v1/memories/{child['id']}/records/{rid}"
    f = ctx.client.delete(base)
    assert f.status == 200 and (f.json or {}).get("status") == "forgotten", f"DELETE must answer the closed record; got HTTP {f.status} {(f.json or {}).get('status')!r}"
    got = ctx.client.get(base)
    assert got.status == 200 and (got.json or {}).get("status") == "forgotten", (
        "a forgotten record keeps its place: it must still read back by id, as forgotten")
    listed = [x.get("id") for x in (ctx.client.get(f"/v1/memories/{child['id']}/records").json or {}).get("data") or []]
    assert rid not in listed, "a forgotten record must leave a listing that does not ask for history"
    e = ctx.client.post(f"/v1/memories/{child['id']}/erase", body={"record_ids": [rid]})
    if e.status == 422 and ((e.json or {}).get("error") or {}).get("code") == "memory_unsupported":
        return "forgotten and kept; this provider does not erase, and says so"
    assert e.status == 200, f"POST erase returned HTTP {e.status}: {e.text[:200]}"
    ctx.validate(e.json or {}, "MemoryErasure")
    assert (e.json or {}).get("erased") == [rid], f"erase must name what it erased; got {(e.json or {}).get('erased')}"
    assert ctx.client.get(base).status == 404, "an erased record must not read back"
    return f"forgotten, then erased with unreachable={len((e.json or {}).get('unreachable') or [])}"


@check("ME-09", "Content is an ordered list of text and file parts, and a provider keeps what it says it keeps", "full",
       f"{SPEC}/memories.md#43-content")
def me09(ctx):
    prov = _memories_supported(ctx)
    child = _memory_child(ctx)
    base = f"/v1/memories/{child['id']}/records"
    two = ctx.client.post(base, body={"type": "note", "content": [{"type": "text", "text": "First line."},
                                                                 {"type": "text", "text": "Second line."}]})
    assert two.status == 200, f"a list of text parts was refused: HTTP {two.status} {two.text[:160]}"
    parts = (two.json or {}).get("content")
    assert isinstance(parts, list) and parts and all(p.get("type") == "text" for p in parts), (
        f"content must read back as a list of parts; got {parts!r}")
    said = " ".join(str(p.get("text")) for p in parts)
    assert "First line." in said and said.index("First line.") < said.index("Second line."), (
        f"the parts' words must survive in order; got {said!r}")
    for bad, why in (([{"type": "image", "url": "x"}], "a part that is neither text, file nor x.-prefixed"),
                     ([{"type": "text"}], "a text part with no text"),
                     ([{"type": "file", "file": {}}], "a file part that names no file"),
                     ([{"type": "text", "text": "x", "role": "narrator"}], "a role that is not one of the four")):
        r = ctx.client.post(base, body={"content": bad})
        assert r.status == 422, f"{why} must be refused with 422; got HTTP {r.status}"
    # a file part: uploaded as Files says, named by id, completed by the server, kept or refused as declared
    media = ((prov.get("content") or {}).get("media")) or ["text/*"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    boundary = "uhpconformance" + uuid.uuid4().hex
    form = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nuser_data\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"dot.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + png + f"\r\n--{boundary}--\r\n".encode()
    up = ctx.client.post("/v1/files", raw=form, content_type=f"multipart/form-data; boundary={boundary}")
    if up.status != 200:
        return f"text parts in order; file parts not exercised (POST /v1/files answered HTTP {up.status})"
    fid = (up.json or {}).get("id")
    r = ctx.client.post(base, body={"type": "note", "content": [
        {"type": "text", "text": "A dot."},
        {"type": "file", "file": {"id": fid, "name": "forged.bin", "media_type": "application/x-forged", "bytes": 1},
         "text": "A single black dot on white."}]})
    import fnmatch
    keeps = any(fnmatch.fnmatch("image/png", pat) for pat in media)
    if not keeps:
        assert r.status == 422 and ((r.json or {}).get("error") or {}).get("code") == "memory_unsupported", (
            f"this provider declares content.media={media}; a png must be refused with memory_unsupported, not stored "
            f"without its file. Got HTTP {r.status}: {r.text[:160]}")
        return f"text parts in order; image/png refused as declared (content.media={media})"
    assert r.status == 200, f"this provider declares it keeps image/png, and refused it: HTTP {r.status} {r.text[:160]}"
    rec = r.json or {}
    ctx.validate(rec, "MemoryRecord")
    fp = next((p for p in rec.get("content") or [] if p.get("type") == "file"), None)
    assert fp and (fp.get("file") or {}).get("media_type") == "image/png" and (fp["file"].get("name") == "dot.png"), (
        f"the server completes a file part from its own file store, not from the caller: {fp!r}")
    assert fp.get("text") == "A single black dot on white.", "the words that stand for a file must be kept with it"
    idx = (rec.get("content") or []).index(fp)
    b = ctx.client.get(f"{base}/{rec['id']}/content/{idx}")
    assert b.status == 200 and b.body == png, f"the part's bytes must read back at its own address; got HTTP {b.status}"
    return "text parts in order; a png kept with its description and read back byte for byte"


@check("ME-10", "Entities and relationships are records and references, read as one graph", "full",
       f"{SPEC}/memories.md#66-the-graph")
def me10(ctx):
    prov = _memories_supported(ctx)
    child = _memory_child(ctx)
    if ((prov.get("graph") or {}).get("entities") or "none") == "none":
        raise Skip("this provider keeps no record of type entity (graph.entities is none)")
    base = f"/v1/memories/{child['id']}"

    def mk(**body):
        r = ctx.client.post(base + "/records", body=body)
        assert r.status == 200, f"POST records ({body.get('type')}) returned HTTP {r.status}: {r.text[:200]}"
        return r.json or {}
    tag = uuid.uuid4().hex[:6]
    a = mk(type="entity", content=f"Ines Varga {tag}")
    b = mk(type="entity", content=f"Harlow Mills {tag}")
    assert a.get("type") == "entity", f"an entity is a core record type; it read back as {a.get('type')!r}"
    f = mk(type="fact", content=f"Ines Varga {tag} runs purchasing at Harlow Mills {tag}.", attributes={"predicate": "works_at"},
           references=[{"rel": "subject", "record_id": a["id"]}, {"rel": "object", "record_id": b["id"]}])
    deadline, g = time.time() + 40, {}
    while True:
        r = ctx.client.post(base + "/graph", body={"around": a["id"], "hops": 2})
        assert r.status == 200, f"POST graph returned HTTP {r.status}: {r.text[:200]}"
        g = r.json or {}
        if {a["id"], b["id"], f["id"]} <= {(n.get("record") or {}).get("id") for n in g.get("nodes") or []} or time.time() > deadline:
            break
        time.sleep(2)
    ctx.validate(g, "MemoryGraph")
    ids = {(n.get("record") or {}).get("id"): n for n in g.get("nodes") or []}
    assert {a["id"], b["id"], f["id"]} <= set(ids), "two hops from an entity must reach the fact about it and the entity at its other end"
    assert (ids[b["id"]].get("memory") or {}).get("id") == child["id"], "a node names the memory its record is in"

    def edge(rel, to):
        return any(e.get("rel") == rel and (e.get("from") or {}).get("record_id") == f["id"]
                   and (e.get("to") or {}).get("record_id") == to and e.get("available") is True for e in g.get("edges") or [])
    assert edge("subject", a["id"]) and edge("object", b["id"]), (
        "the fact's references must be edges from the fact to its subject and to its object")
    one = ctx.client.post(base + "/graph", body={"around": a["id"], "hops": 1}).json or {}
    assert b["id"] not in {(n.get("record") or {}).get("id") for n in one.get("nodes") or []}, (
        "one hop from the subject reached the object: the fact between them is a node, one hop away")
    return f"{len(g.get('nodes') or [])} nodes, {len(g.get('edges') or [])} edges around {a['id']} on entities={prov['graph']['entities']}"


@check("ME-08", "A memory moves with its subtree, and deleting it takes the subtree", "full",
       f"{SPEC}/memories.md#2-the-memory-object")
def me08(ctx):
    _memories_supported(ctx)
    root, child = ctx.state["memory_root"], _memory_child(ctx)
    r = ctx.client.put(f"/v1/memories/{root['id']}", body={"parent_id": child["id"]})
    assert r.status == 422, f"moving a memory under its own child must be refused; got HTTP {r.status}"
    ids = [i for i in ctx.state.get("_cleanup_memories") or [] if i]
    for mid in ids:
        d = ctx.client.delete(f"/v1/memories/{mid}")
        assert d.status == 200, f"DELETE /v1/memories/{mid} returned HTTP {d.status}"
    assert ctx.client.get(f"/v1/memories/{child['id']}").status == 404, "deleting a memory must take its descendants"
    return f"{len(ids)} tree(s) removed"
