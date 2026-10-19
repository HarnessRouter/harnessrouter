"""A response object that leaves the gateway says what UHP says, not what the gateway calls it
internally (#480).

`lifecycle.md` §3 names five statuses. The gateway stored a background record as `running` and
answered `GET /v1/responses/{id}` and the background POST with that name, so a client written to
the spec waited for `in_progress` forever or treated the turn as an error, while streaming had
already emitted `in_progress` for the very same turn. The stored value stays `running`: the
console's turn list and the reconcile sweeps read it there, and they are not UHP response objects.
"""
import ast
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
UHP_STATUSES = {"in_progress", "completed", "failed", "incomplete", "cancelled"}

# Every status a stored response record can carry, split by how it gets there. WRITTEN is what the
# gateway's own write paths persist. READ_ONLY is what the read guards tolerate but nothing
# writes into a record today: they are mapped anyway, because a total map is what stops a future
# alias from leaking, and because a legacy record written by an older build can still carry one.
WRITTEN = {
    "running": "persist('running'), the in-flight write before the turn starts",
    "completed": "persist() with the turn's terminal status; _RESP_STATUS_MAP['done'|'completed']",
    "incomplete": "persist() with the turn's terminal status; _RESP_STATUS_MAP['max_turns'|'timeout']",
    "cancelled": "cancel_response and stop_session settle the record",
    "failed": "persist('failed') on lease refusal, hydrate failure, an unhandled exception",
}
READ_ONLY = {
    "starting": "a turn's trace record opens with it; never stored on a response record",
    "queued": "named by the cancel path's live check; nothing writes it",
    "done": "_RESP_STATUS_MAP's key for completed, translated before storage",
    "max_turns": "_RESP_STATUS_MAP's key for incomplete, translated before storage",
    "timeout": "_RESP_STATUS_MAP's key for incomplete, translated before storage",
    "error": "_RESP_STATUS_MAP's key for failed, translated before storage",
}
INTERNAL_STATUSES = {**WRITTEN, **READ_ONLY}


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_response_in_reach", lambda p, rec: asyncio.sleep(0, True))
    monkeypatch.setattr(gw, "_harness_in_reach", lambda p: asyncio.sleep(0, True))
    return TestClient(gw.app)


def _store(rid: str, status: str) -> dict:
    """Write a response record straight through `_resp_put`, the way the turn's own writes do."""
    rec = {"id": rid, "object": "response", "created_at": int(time.time()), "status": status,
           "output": [], "_session_id": "hsess1", "_org": ORG, "_member": "me@local",
           "_input": [{"role": "user", "content": "hi"}], "_backend": "dsh"}
    asyncio.run(gw._resp_put(rid, rec, ORG, "hsess1", None, status, rec["created_at"], True))
    return rec


# ── the mapping itself ─────────────────────────────────────────────────────────────────

def test_the_map_covers_every_internal_status_the_gateway_writes():
    """A new internal name cannot leak later: every status any write path can produce has to land
    in one of the five UHP statuses, and the five must pass through unchanged."""
    for status in INTERNAL_STATUSES:
        assert gw._UHP_STATUS.get(status) in UHP_STATUSES, (
            f"{status!r} ({INTERNAL_STATUSES[status]}) maps to "
            f"{gw._UHP_STATUS.get(status)!r}, which is not a UHP status")
    for status in UHP_STATUSES:
        assert gw._UHP_STATUS.get(status) == status


def _write_path_status_literals() -> set:
    """Every status literal the write and emit paths in app.py can pass.

    `_RESP_STATUS_MAP` and `_RESP_TERMINAL` are both alias tables, so walking them finds the names
    that go *through* a translation and misses the ones written straight into a record — `running`
    among them, the name this issue is about. Reading the literals out of the source is what closes
    that gap: rename `await persist("running")` to any other name and this finds it.
    """
    tree = ast.parse(pathlib.Path(gw.__file__).read_text(encoding="utf-8"))
    # A call whose function name matches, and whose argument at this index is a bare string
    # literal, is a status literal. `_resp_put` takes the status at index 4, `persist` at 0.
    want = {"persist": 0, "_resp_put": 4, "_response_obj": 0, "complete": 0}
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        idx = want.get(node.func.id)
        if idx is None or len(node.args) <= idx:
            continue
        arg = node.args[idx]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.add((node.func.id, arg.value))
    return found


def test_every_status_literal_the_write_path_uses_is_named_in_the_table():
    for func, value in sorted(_write_path_status_literals()):
        assert value in INTERNAL_STATUSES, (
            f"{func}(...) is given the status literal {value!r}, which is not named in "
            f"WRITTEN/READ_ONLY; an unmapped status reaches the client verbatim")


def test_the_every_value_the_gateway_can_store_is_named_in_the_table():
    """The tables above are the claim; this is the check. `_RESP_STATUS_MAP` is the one place
    that translates a trace or vertex status into a stored one, so both its keys and its values
    are enumerable, and every one of them must be mapped."""
    for name, mapped in gw._RESP_STATUS_MAP.items():
        assert mapped in UHP_STATUSES, f"_RESP_STATUS_MAP['{name}'] = {mapped!r} is not a UHP status"
        assert name in INTERNAL_STATUSES, (
            f"_RESP_STATUS_MAP maps {name!r}, which the enumeration test does not name")
    for name in gw._RESP_TERMINAL:
        assert name in INTERNAL_STATUSES, (
            f"_RESP_TERMINAL treats {name!r} as a stored terminal status, which the enumeration "
            "test does not name; if a record can carry it, it needs a mapping")


def test_the_formatter_drops_internal_fields_and_translates_the_status():
    rec = {"id": "resp_1", "status": "running", "output": [], "_org": ORG, "_input": [{"x": 1}]}
    out = gw._public_response(rec)
    assert out["status"] == "in_progress"
    assert out == {"id": "resp_1", "status": "in_progress", "output": []}


def test_the_formatter_leaves_the_stored_record_alone():
    """The console and the sweeps read `running` from the record itself. The formatter copies."""
    rec = {"id": "resp_1", "status": "running", "_session_id": "hsess1"}
    gw._public_response(rec)
    assert rec["status"] == "running" and rec["_session_id"] == "hsess1"


def test_a_status_with_no_mapping_is_passed_through_not_silently_rewritten():
    """Better a visible wrong value the enumeration test catches than a quiet invention."""
    assert gw._public_response({"id": "r", "status": "wat"})["status"] == "wat"


# ── one test per exit ──────────────────────────────────────────────────────────────────

def test_get_mid_turn_says_in_progress(api):
    _store("resp_get_running", "running")
    j = api.get("/v1/responses/resp_get_running").json()
    assert j["status"] == "in_progress"


def test_get_on_a_terminal_record_reports_that_terminal_status(api):
    _store("resp_get_done", "completed")
    assert api.get("/v1/responses/resp_get_done").json()["status"] == "completed"


def _seed_live_turn(rid: str, monkeypatch) -> None:
    """Make the record the live turn of a live session, so cancel takes the fast path.

    Without this, cancel cannot prove the response owns the live turn — the same-replica hint is
    only consulted when there is no control plane — so it settles the record as `cancelled`
    itself. The fixture would then assert `cancelled` and pass with the status mapping removed,
    never having reached the answer under test. Ownership is the durable `runner_turn_id` the
    cancel latch returns matching the one on the live session vertex.
    """
    async def _vget(sid):
        return {"status": "running", "turn_status": "running", "runner_turn_id": "rt1"}

    async def _mark(org, response_id, status, ttl):
        return {"runner_turn_id": "rt1"}

    async def _stop(org, sid, v, **kw):
        return None
    monkeypatch.setattr(gw, "_vertex_get", _vget)
    monkeypatch.setattr(gw, "_stop_session", _stop)
    monkeypatch.setattr(gw.control_store, "resp_mark_terminal", _mark)
    gw._session_trace["hsess1"] = {"last_response_id": rid}


@pytest.fixture()
def clean_session_trace():
    before = dict(gw._session_trace)
    yield
    gw._session_trace.clear()
    gw._session_trace.update(before)


def test_cancel_in_flight_answers_in_progress_until_the_cancel_settles(api, monkeypatch,
                                                                       clean_session_trace):
    """An accepted cancel on a turn that is still running leaves the record running: the answer is
    a response object on that path too, and it has to say `in_progress`, not the internal name."""
    _store("resp_cancel", "running")
    _seed_live_turn("resp_cancel", monkeypatch)
    j = api.post("/v1/responses/resp_cancel/cancel").json()
    assert j["status"] == "in_progress"


def test_cancel_never_leaks_internal_fields(api, monkeypatch, clean_session_trace):
    _store("resp_cancel_fields", "running")
    _seed_live_turn("resp_cancel_fields", monkeypatch)
    j = api.post("/v1/responses/resp_cancel_fields/cancel").json()
    assert not [k for k in j if k.startswith("_")]
    assert "_input" not in j


def test_the_background_post_answer_says_in_progress(api, monkeypatch):
    """The POST answer is built by the translator, not read back from the record, so the status it
    passes is the one that has to be right. This drives the real endpoint."""
    monkeypatch.setattr(gw, "_base_catalog_get", lambda h: {"id": h, "base": "dsh"}, raising=False)

    async def _chain(org, backend, model):
        return [{"backend": backend}]
    monkeypatch.setattr(gw, "_resolve_chain", _chain)

    async def _exec(tr, **kw):
        return "completed", [], {}
    monkeypatch.setattr(gw, "_resp_execute", _exec)

    r = api.post("/v1/responses", json={"input": "hi", "harness_id": "h1", "background": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"


def test_the_translator_names_the_state_in_progress_too():
    """The stream already emitted `in_progress` while the poll said `running` — the same turn, two
    names. This is the half that was already right, pinned so it stays right."""
    tr = gw._RespTranslator("resp_tr", "m", None, True, 0.0)
    assert tr.start()[1]["response"]["status"] == "in_progress"
    assert tr._response_obj("in_progress")["status"] == "in_progress"


def test_idempotent_replay_returns_the_first_record_not_a_raw_one():
    """`_idem_replay` used to answer the stored record verbatim, internal fields included, and to
    invent a `status: "unknown"` body for a missing original."""
    rec = {"id": "resp_idem", "object": "response", "status": "running", "output": [],
           "_org": ORG, "_input": [{"role": "user", "content": "secret"}]}

    async def _get(rid):
        return rec if rid == "resp_idem" else None

    orig_get, orig_sleep = gw._resp_get, asyncio.sleep

    async def _no_sleep(_):
        return None
    gw._resp_get, asyncio.sleep = _get, _no_sleep
    try:
        r = asyncio.run(gw._idem_replay("resp_idem", False))
    finally:
        gw._resp_get, asyncio.sleep = orig_get, orig_sleep

    body = json.loads(r.body)
    assert body["status"] == "in_progress"
    assert not [k for k in body if k.startswith("_")] and "_input" not in body


def test_idempotent_replay_of_a_missing_original_is_the_same_404_the_get_answers():
    async def _get(rid):
        return None

    async def _no_sleep(_):
        return None
    orig_get, orig_sleep = gw._resp_get, asyncio.sleep
    gw._resp_get, asyncio.sleep = _get, _no_sleep
    try:
        with pytest.raises(Exception) as ei:
            asyncio.run(gw._idem_replay("resp_nope", False))
    finally:
        gw._resp_get, asyncio.sleep = orig_get, orig_sleep

    detail = ei.value.detail
    assert isinstance(detail, dict) and detail["code"] == "response_not_found"
    assert ei.value.status_code == 404


def test_the_idempotent_stream_ends_on_an_event_when_the_original_is_gone():
    """The stream has already opened, so it cannot become a 404. It ends on the one event a
    client can act on, carrying the same code."""
    async def _get(rid):
        return None

    async def _no_sleep(_):
        return None
    orig_get, orig_sleep = gw._resp_get, asyncio.sleep
    gw._resp_get, asyncio.sleep = _get, _no_sleep
    try:
        resp = asyncio.run(gw._idem_replay("resp_nope", True))
        frames = asyncio.run(_frames(resp))
    finally:
        gw._resp_get, asyncio.sleep = orig_get, orig_sleep

    assert frames[-1]["type"] == "response.failed"
    assert frames[-1]["response"]["error"]["code"] == "response_not_found"
    assert frames[-1]["response"]["status"] == "failed"


async def _frames(resp) -> list:
    out: list = []
    async for chunk in resp.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


# ── the invariant the issue is really about ───────────────────────────────────────────

def test_every_exit_answers_through_the_formatter():
    """Pins the exits this file drives: GET and cancel route through the formatter, and nothing
    hands a record back through `_strip_internal` alone.

    It is not a general net. A new exit that returned the record some other way (`return rec`,
    an inline dict, `return await _resp_get(...)`) would not match either string and this test
    would stay green — the per-exit tests above are what actually cover each answer.
    """
    src = pathlib.Path(gw.__file__).read_text(encoding="utf-8")
    assert src.count("return _strip_internal(rec)") == 0, (
        "a response object is still answered without the status mapping; route it through "
        "_public_response")
    assert src.count("return _public_response(rec)") >= 2      # GET /v1/responses/{id}, cancel
    assert '_snap = tr._response_obj("in_progress")' in src    # background POST answer


def test_the_orphan_adopter_emits_a_uhp_status_not_the_trace_name():
    """`_adopt_orphan_turn` publishes its terminal event straight off `rec["status"]`, which holds
    the trace's name for the outcome (`done`, `max_turns`, `timeout`). `complete()` publishes
    whatever it is handed — deliberately, the persist path translates too — so the call site is
    the thing that has to translate, and that is what this pins."""
    src = pathlib.Path(gw.__file__).read_text(encoding="utf-8")
    assert 'translator.complete(_RESP_STATUS_MAP.get(rec["status"], "failed"), produced)' in src, (
        "the orphan adopter must translate the trace's status name before publishing it; "
        "untranslated it reached subscribers as status 'max_turns' under a response.completed "
        "event (#480)")


def test_a_synthesized_event_body_carries_every_required_response_field():
    """`Event.response` is a `$ref` to `Response`, whose `required` is id, object, created_at,
    status, output and model. A literal carrying three of the six fails schema validation even
    when everything it does carry is right."""
    required = {"id", "object", "created_at", "status", "output", "model"}
    body = gw._synth_response("resp_synth", "in_progress")
    assert required <= set(body), f"synthesized body is missing {required - set(body)}"
    assert gw._synth_response("resp_synth", "failed", {"code": "x"})["error"] == {"code": "x"}
    assert "error" not in body