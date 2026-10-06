"""A calibration credential touches only what belongs to the harness it drives, and is refused
before anything is read back or written.

The route list (test_dual_loop.py) says which doors the credential may knock on. These are the
rooms behind them. Reported privately, twice: the kit launch moved a kit between two harnesses and
THEN answered 403; reading and cancelling a response checked the organization alone; and starting a
run checked the harness named in the request but not whose conversation it continued.
"""
import asyncio
import inspect
import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

ORG = "org-a"
INNER = "chrn_" + "a" * 32
OTHER = "chrn_" + "b" * 32
CAL = {"org": ORG, "member": "calibrator:hsess_outer", "calibration": {"inner": INNER, "org": ORG, "sid": "hsess_outer"}}
MEMBER = {"org": ORG, "member": "ana@example.com", "workspace": "", "workspace_default": False}

SESSIONS = {
    "hsess_inner": {"tenant": ORG, "harness_id": INNER, "status": "idle"},
    "hsess_other": {"tenant": ORG, "harness_id": OTHER, "status": "idle"},
    "hsess_blank": {"tenant": ORG, "harness_id": "", "status": "idle"},
}
RESPONSES = {
    "resp_inner": {"id": "resp_inner", "_org": ORG, "_session_id": "hsess_inner", "status": "completed"},
    "resp_other": {"id": "resp_other", "_org": ORG, "_session_id": "hsess_other", "status": "completed"},
    "resp_blank": {"id": "resp_blank", "_org": ORG, "_session_id": "hsess_blank", "status": "completed"},
}


class _Req:
    def __init__(self, headers=None, path="/v1/responses", method="POST"):
        self.headers = headers or {}
        self.method = method
        self.url = type("U", (), {"path": path})()


def _refused(coro) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        asyncio.run(coro)
    return e.value


@pytest.fixture
def world(monkeypatch):
    """The graph a handler reads, and a record of everything it writes or reaches out to."""
    did = {"writes": [], "db_checks": [], "idem": [], "sessions_resolved": [], "cancelled": []}
    harnesses = {
        INNER: {"id": INNER, "org": ORG, "workspace": "", "kit": "", "deleted": "0"},
        OTHER: {"id": OTHER, "org": ORG, "workspace": "space.b", "kit": "", "deleted": "0"},
    }

    async def vertex_get(vid):
        return dict(SESSIONS[vid]) if vid in SESSIONS else (dict(harnesses[vid]) if vid in harnesses else None)

    async def resp_get(rid):
        return dict(RESPONSES[rid]) if rid in RESPONSES else None

    async def list_by_org(label, org):
        return [dict(h) for h in harnesses.values()]

    async def upsert(label, vid, props, **kw):
        did["writes"].append((label, vid, dict(props)))
        harnesses.setdefault(vid, {"id": vid, "org": ORG}).update(props)

    async def db_validate(engine, conn):
        did["db_checks"].append(conn)
        return {"ok": True}

    monkeypatch.setattr(gw, "_vertex_get", vertex_get)
    monkeypatch.setattr(gw, "_resp_get", resp_get)
    monkeypatch.setattr(gw, "_vg_list_by_org", list_by_org)
    monkeypatch.setattr(gw, "_vg_upsert", upsert)
    monkeypatch.setattr(gw, "_db_validate", db_validate)
    monkeypatch.setattr(gw, "_kits", lambda: {"mario": {"id": "mario", "title": "Mario", "harness": {}, "app": {"route": "/kits/mario"}}})
    monkeypatch.setattr(gw, "_kit_launch_database", lambda kit: {"name": "database", "id": "mcp.database"})
    monkeypatch.setattr(gw, "_kit_launch_media", lambda kit: None)
    did["harnesses"] = harnesses
    return did


def _as(monkeypatch, principal):
    async def who(request):
        return principal
    monkeypatch.setattr(gw, "_principal", who)


def _launch(body=None):
    return gw.launch_kit("mario", _Req(path="/v1/kits/mario/launch"), gw.KitLaunchBody(**body) if body else None)


# ── the kit launch: refused before anything happens ────────────────────────────────────────────

@pytest.mark.parametrize("kit_on, names", [
    (INNER, OTHER),      # the reported case: move the kit off its own harness onto another one
    (OTHER, INNER),      # take a kit away from a harness it does not drive
    (OTHER, ""),         # relaunch a kit that runs somewhere else
    (OTHER, OTHER),
    ("", ""),            # nothing runs the kit: it does not get to create a harness either
    ("", OTHER),
], ids=["onto-another", "take-from-another", "another-s-kit", "another-s-kit-named", "no-harness", "no-harness-named"])
def test_a_refused_launch_changes_nothing_and_reaches_nowhere(world, monkeypatch, kit_on, names):
    if kit_on:
        world["harnesses"][kit_on]["kit"] = "mario"
    before = {k: dict(v) for k, v in world["harnesses"].items()}
    _as(monkeypatch, CAL)
    body = {"database": {"engine": "postgres", "connection_string": "postgres://10.0.0.5:5432/x"}}
    if names:
        body["harness"] = names
    e = _refused(_launch(body))
    assert e.status_code == 403
    assert world["writes"] == [] and world["harnesses"] == before          # the 403 means nothing happened
    assert world["db_checks"] == []                                        # and no socket was opened for it


def test_the_credential_relaunches_the_kit_where_it_already_runs(world, monkeypatch):
    world["harnesses"][INNER]["kit"] = "mario"
    _as(monkeypatch, CAL)
    monkeypatch.setattr(gw, "_kit_launch_database", lambda kit: None)
    monkeypatch.setattr(gw, "_kit_plugin", lambda kit: None)

    async def no_plugs(org, hid):
        return False
    monkeypatch.setattr(gw, "_plugs_ensure_required", no_plugs)
    monkeypatch.setattr(gw, "_harness_out", lambda v: {"id": v.get("id")})
    for body in (None, {"harness": INNER}):
        out = asyncio.run(_launch(body))
        assert out["harnessId"] == INNER and out["created"] is False
    assert world["writes"] == []                                           # a relaunch of an unchanged kit rewrites nothing


def test_a_member_still_moves_a_kit_between_two_of_their_harnesses(world, monkeypatch):
    world["harnesses"][INNER]["kit"] = "mario"
    _as(monkeypatch, MEMBER)
    monkeypatch.setattr(gw, "_kit_launch_database", lambda kit: None)
    monkeypatch.setattr(gw, "_kit_plugin", lambda kit: None)

    async def no_plugs(org, hid):
        return False
    monkeypatch.setattr(gw, "_plugs_ensure_required", no_plugs)
    monkeypatch.setattr(gw, "_harness_out", lambda v: {"id": v.get("id")})
    out = asyncio.run(_launch({"harness": OTHER}))
    assert out["harnessId"] == OTHER
    assert [(v, p.get("kit")) for _, v, p in world["writes"]] == [(INNER, ""), (OTHER, "mario")]


def test_in_the_handler_the_credential_is_judged_before_the_first_side_effect():
    src = inspect.getsource(gw.launch_kit)
    gate = src.index("_inner = _calibration_inner(p)")
    assert gate < src.index("_db_validate(") and gate < src.index("_vg_upsert(")
    assert src.count('p.get("calibration")') == 0                         # one gate, not a second one further down


# ── a response: read and cancelled only when it is its harness's ───────────────────────────────

@pytest.mark.parametrize("rid", ["resp_other", "resp_blank"])
def test_another_harness_s_response_is_not_found_to_read_or_to_cancel(world, monkeypatch, rid):
    _as(monkeypatch, CAL)

    def must_not(*a, **k):
        raise AssertionError("the response was touched after it should have been refused")
    monkeypatch.setattr(gw, "_reconcile_response", must_not)
    monkeypatch.setattr(gw.control_store, "enabled", must_not)
    e = _refused(gw.get_response(rid, _Req(path=f"/v1/responses/{rid}", method="GET")))
    assert e.status_code == 404 and "No response with that id." in str(e.detail)
    e = _refused(gw.cancel_response(rid, _Req(path=f"/v1/responses/{rid}/cancel")))
    assert e.status_code == 404


def test_its_own_harness_s_response_is_read(world, monkeypatch):
    _as(monkeypatch, CAL)

    async def settle(rid, rec):
        return rec
    monkeypatch.setattr(gw, "_reconcile_response", settle)
    assert asyncio.run(gw.get_response("resp_inner", _Req(path="/v1/responses/resp_inner", method="GET")))["id"] == "resp_inner"


def test_a_member_reads_any_response_of_the_organization_as_before(world, monkeypatch):
    _as(monkeypatch, MEMBER)

    async def settle(rid, rec):
        return rec
    monkeypatch.setattr(gw, "_reconcile_response", settle)
    assert asyncio.run(gw.get_response("resp_other", _Req(path="/v1/responses/resp_other", method="GET")))["id"] == "resp_other"


# ── a run: on its harness, and in a conversation that is already its harness's ─────────────────

def _start(world, monkeypatch, **body):
    """create_response as the credential, with every later stage rigged to shout if it is reached."""
    _as(monkeypatch, CAL)

    async def idem_get(org, sha):
        world["idem"].append(sha)
        return {"resp_id": "resp_other", "req_hash": ""}

    async def resolve(*a, **k):
        world["sessions_resolved"].append((a, k))
        raise AssertionError("a session was resolved for a run that should have been refused")
    monkeypatch.setattr(gw.control_store, "enabled", lambda: True)
    monkeypatch.setattr(gw.control_store, "idem_get", idem_get)
    monkeypatch.setattr(gw, "_resp_resolve_session", resolve)
    return gw.create_response(gw.CreateResponseBody(input="hello", **body), _Req(headers={"Idempotency-Key": "k-1"}))


@pytest.mark.parametrize("body, status", [
    ({"metadata": {"harness_id": OTHER}}, 403),                                             # another harness
    ({"metadata": {"harness_id": INNER}, "previous_response_id": "resp_other"}, 404),       # its harness, another's conversation
    ({"metadata": {"harness_id": INNER}, "previous_response_id": "resp_blank"}, 404),       # a conversation that names no harness
    ({"metadata": {"harness_id": INNER}, "previous_response_id": "resp_missing"}, 404),
    ({"metadata": {"harness_id": INNER, "session_id": "hsess_other"}}, 404),
    ({"metadata": {"harness_id": INNER, "session_id": "hsess_blank"}}, 404),
], ids=["another-harness", "another-s-response", "unnamed-response", "missing-response", "another-s-session", "unnamed-session"])
def test_a_run_outside_its_harness_is_refused_before_a_stored_answer_is_replayed(world, monkeypatch, body, status):
    e = _refused(_start(world, monkeypatch, **body))
    assert e.status_code == status
    assert world["idem"] == []                    # refused before the idempotency replay could hand a response back
    assert world["sessions_resolved"] == [] and world["writes"] == []


def test_a_run_on_its_harness_in_its_own_conversation_gets_past_the_gate(world, monkeypatch):
    # past the gate the next thing asked is the idempotency store: reaching it is the proof
    coro = _start(world, monkeypatch, metadata={"harness_id": INNER, "session_id": "hsess_inner"},
                  previous_response_id="resp_inner")

    async def replay(resp_id, stream):
        return {"replayed": resp_id}
    monkeypatch.setattr(gw, "_idem_replay", replay)
    assert asyncio.run(coro) == {"replayed": "resp_other"} and len(world["idem"]) == 1


def test_what_belongs_to_the_harness_it_drives(world):
    holds = lambda sid: asyncio.run(gw._calibration_holds_session(INNER, sid))   # noqa: E731
    assert holds("hsess_inner")
    assert not holds("hsess_other") and not holds("hsess_blank") and not holds("hsess_nope") and not holds("")
    assert not asyncio.run(gw._calibration_holds_session("", "hsess_blank"))    # no harness named: nothing is held
    assert asyncio.run(gw._calibration_holds_response(INNER, RESPONSES["resp_inner"]))
    assert not asyncio.run(gw._calibration_holds_response(INNER, None))
    assert gw._calibration_inner(CAL) == INNER and gw._calibration_inner(MEMBER) == ""
