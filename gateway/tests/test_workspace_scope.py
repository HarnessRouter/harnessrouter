"""A key held to a workspace reaches that workspace and nothing else of the organization.

The lists always held to this. The routes that take an id checked the organization and stopped, so a
workspace's key that knew an id read, changed and deleted another workspace's harnesses, sessions
and responses, and could mint itself a key with no workspace at all (reported privately three times).
The rule is one function, `_scope_keeps`; the last test reads every route to see that it is asked.

Who is held: an API key of a workspace other than the Default Workspace. Who is not (Richard,
2026-10-06, the same on the hosted service): a person in the console, a key for the whole
organization, and a Default Workspace key, which is what a key was before workspaces existed.
"""
import ast
import asyncio
import pathlib
import re
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

ORG = "org-a"
KEY_A = {"org": ORG, "member": "svc-a", "workspace": "space.a", "workspace_default": False, "via": "api_key"}
KEY_DEFAULT = {"org": ORG, "member": "svc-d", "workspace": "default", "workspace_default": True, "via": "api_key"}
KEY_ORG = {"org": ORG, "member": "svc-o", "workspace": "", "workspace_default": False, "via": "api_key"}
CONSOLE_A = {"org": ORG, "member": "ana@example.com", "workspace": "space.a", "workspace_default": False}

GRAPH = {
    "chrn_a": {"id": "chrn_a", "org": ORG, "workspace": "space.a", "deleted": "0"},
    "chrn_b": {"id": "chrn_b", "org": ORG, "workspace": "space.b", "deleted": "0"},
    "chrn_old": {"id": "chrn_old", "org": ORG, "workspace": "", "deleted": "0"},
    "chrn_gone": {"id": "chrn_gone", "org": ORG, "workspace": "space.a", "deleted": "1"},
    "chrn_x": {"id": "chrn_x", "org": "org-x", "workspace": "space.a", "deleted": "0"},
    "hsess_a": {"tenant": ORG, "workspace": "space.a", "status": "idle", "harness_id": "chrn_a"},
    "hsess_b": {"tenant": ORG, "workspace": "space.b", "status": "idle", "harness_id": "chrn_b"},
    "hsess_old": {"tenant": ORG, "workspace": "", "status": "idle", "harness_id": "chrn_old"},
    "key_a": {"org": ORG, "workspace": "space.a"},
    "key_b": {"org": ORG, "workspace": "space.b"},
}
RESP = {r: {"id": r, "_org": ORG, "_session_id": s} for r, s in (("resp_a", "hsess_a"), ("resp_b", "hsess_b"), ("resp_old", "hsess_old"))}


class _Req:
    def __init__(self, headers=None, path="/", method="GET"):
        self.headers, self.method = headers or {}, method
        self.url = type("U", (), {"path": path})()


@pytest.fixture
def world(monkeypatch):
    writes = []

    async def vertex_get(vid):
        return dict(GRAPH[vid]) if vid in GRAPH else None

    async def resp_get(rid):
        return dict(RESP[rid]) if rid in RESP else None

    async def upsert(label, vid, props, **kw):
        writes.append((label, vid, dict(props)))
    monkeypatch.setattr(gw, "_vertex_get", vertex_get)
    monkeypatch.setattr(gw, "_resp_get", resp_get)
    monkeypatch.setattr(gw, "_vg_upsert", upsert)
    monkeypatch.setattr(gw.control_store, "enabled", lambda: False)
    return writes


def _as(monkeypatch, principal):
    async def who(request):
        return dict(principal)
    monkeypatch.setattr(gw, "_principal", who)


def _status(coro) -> int:
    with pytest.raises(HTTPException) as e:
        asyncio.run(coro)
    return e.value.status_code


# ── the rule ───────────────────────────────────────────────────────────────────────────────────

def test_the_rule():
    keeps, held = gw._scope_keeps, gw._key_scope
    assert held(KEY_A) == "space.a"
    assert keeps(KEY_A, "space.a") and not keeps(KEY_A, "space.b")
    assert not keeps(KEY_A, "") and not keeps(KEY_A, None)            # made before workspaces: the Default Workspace's
    # not held: a Default Workspace key, a key for the whole organization, a person in the console
    for p in (KEY_DEFAULT, KEY_ORG, CONSOLE_A, {"org": ORG, "workspace": "org-a__hr_default", "via": "api_key"}):
        assert held(p) == "" and all(keeps(p, ws) for ws in ("space.a", "space.b", "default", "", None)), p
    assert held({"org": ORG, "workspace": "other__hr_default", "via": "api_key"}) == "other__hr_default"   # another organization's default is not this one's


# ── harnesses ──────────────────────────────────────────────────────────────────────────────────

def test_a_harness_is_found_only_inside_a_held_keys_workspace(world):
    reach = lambda p, hid, **k: asyncio.run(gw._harness_in_reach(p, hid, **k))   # noqa: E731
    assert reach(KEY_A, "chrn_a")["id"] == "chrn_a"
    for hid in ("chrn_b", "chrn_old", "chrn_gone", "chrn_x", "chrn_nope"):
        assert _status(gw._harness_in_reach(KEY_A, hid)) == 404, hid
    for p in (KEY_DEFAULT, KEY_ORG, CONSOLE_A):                                  # organization reach
        assert [reach(p, h)["id"] for h in ("chrn_a", "chrn_b", "chrn_old")] == ["chrn_a", "chrn_b", "chrn_old"]
        assert _status(gw._harness_in_reach(p, "chrn_x")) == 404                 # ...of its own organization
    assert reach(KEY_A, "chrn_gone", deleted_ok=True)["id"] == "chrn_gone"       # deleting again is allowed, in its own workspace
    assert _status(gw._harness_in_reach({"org": "", "workspace": ""}, "chrn_a")) == 404


@pytest.mark.parametrize("call", [
    lambda: gw.get_harness_public("chrn_b", _Req()),
    lambda: gw.update_harness_public("chrn_b", gw.HarnessBody(name="HIJACKED", base="pi"), _Req()),
    lambda: gw.delete_harness_public("chrn_b", _Req()),
    lambda: gw.get_harness(ORG, "chrn_b", _Req()),
    lambda: gw.update_harness(ORG, "chrn_b", gw.HarnessBody(name="HIJACKED", base="pi"), _Req()),
    lambda: gw.delete_harness(ORG, "chrn_b", _Req()),
    lambda: gw.get_harness_models_public("chrn_b", _Req()),
    lambda: gw.export_harness_plugin_public("chrn_b", _Req()),
    lambda: gw.cloud_upload_status("chrn_b", _Req()),
    lambda: gw.harness_events("chrn_b", _Req()),
    lambda: gw.detach_plugs("chrn_b", _Req()),
], ids=["read", "overwrite", "delete", "read-org-path", "overwrite-org-path", "delete-org-path", "models", "package",
        "upload-status", "events", "detach-plugs"])
def test_another_workspaces_harness_is_not_found_on_any_route_and_nothing_is_written(world, monkeypatch, call):
    _as(monkeypatch, KEY_A)
    assert _status(call()) == 404
    assert world == []


# ── sessions and responses ─────────────────────────────────────────────────────────────────────

def test_a_session_is_found_only_inside_a_held_keys_workspace(world, monkeypatch):
    _as(monkeypatch, KEY_A)
    assert asyncio.run(gw._owned_session(_Req(), "hsess_a"))[1]["harness_id"] == "chrn_a"
    assert _status(gw._owned_session(_Req(), "hsess_b")) == 404 and _status(gw._owned_session(_Req(), "hsess_old")) == 404
    for p in (KEY_DEFAULT, KEY_ORG, CONSOLE_A):
        _as(monkeypatch, p)
        assert [asyncio.run(gw._owned_session(_Req(), s))[0] for s in ("hsess_a", "hsess_b", "hsess_old")] == [ORG] * 3


@pytest.mark.parametrize("call", [
    lambda: gw.delete_trace("hsess_b", _Req()),
    lambda: gw.artifact_by_path("hsess_b", "report.pdf", _Req()),
    lambda: gw.set_session_share("hsess_b", _Req()),
    lambda: gw.revoke_session_share("hsess_b", _Req()),
    lambda: gw.get_session_share("hsess_b", _Req()),
    lambda: gw.get_response("resp_b", _Req()),
    lambda: gw.delete_response("resp_b", _Req()),
    lambda: gw.list_input_items("resp_b", _Req()),
    lambda: gw.cancel_response("resp_b", _Req()),
], ids=["delete", "artifact", "publish", "unpublish", "share-state", "read-response", "delete-response", "input-items", "cancel"])
def test_another_workspaces_session_and_its_responses_are_not_found(world, monkeypatch, call):
    _as(monkeypatch, KEY_A)
    assert _status(call()) == 404
    assert world == []


def test_a_response_is_reached_through_its_session(world):
    reach = lambda p, r: asyncio.run(gw._response_in_reach(p, RESP.get(r)))   # noqa: E731
    assert reach(KEY_A, "resp_a") and not reach(KEY_A, "resp_b") and not reach(KEY_A, "resp_old")
    assert all(reach(p, r) for p in (KEY_DEFAULT, KEY_ORG, CONSOLE_A) for r in ("resp_a", "resp_b", "resp_old"))
    assert not asyncio.run(gw._response_in_reach(KEY_A, {"id": "resp_orphan", "_org": ORG}))    # no session: not a narrowed caller's
    assert asyncio.run(gw._response_in_reach(KEY_ORG, {"id": "resp_orphan", "_org": ORG}))


def test_a_conversation_of_another_workspace_is_not_continued(world):
    for prev, hint in (("resp_b", ""), ("", "hsess_b"), ("", "hsess_old")):
        assert _status(gw._resp_resolve_session(ORG, "svc-a", prev or None, "pi", session_hint=hint,
                                                workspace="space.a", caller=KEY_A)) == 404
    assert world == []


def test_a_caller_with_organization_reach_continues_any_conversation_of_it(world, monkeypatch):
    seen = []

    async def trace_cursor(tr):
        seen.append(tr)
    monkeypatch.setattr(gw, "_recover_trace_cursor", trace_cursor)
    monkeypatch.setattr(gw, "_prefix_from_vertex", lambda sid, v: f"{ORG}/x_{sid}")

    async def vupsert(sid, props):
        pass
    monkeypatch.setattr(gw, "_vertex_upsert", vupsert)
    for p in (KEY_DEFAULT, KEY_ORG, CONSOLE_A):
        sid, _resume = asyncio.run(gw._resp_resolve_session(ORG, "m", None, "pi", session_hint="hsess_b", workspace="", caller=p))
        assert sid == "hsess_b"


# ── keys ───────────────────────────────────────────────────────────────────────────────────────

def _mint(monkeypatch, caller, **body):
    _as(monkeypatch, caller)
    return asyncio.run(gw.mint_key(ORG, gw.KeyBody(**body), _Req()))


def test_a_held_key_mints_keys_for_its_own_workspace_under_its_own_name(world, monkeypatch):
    out = _mint(monkeypatch, KEY_A, member_id="attacker@evil", workspace="")
    stored = world[-1][2]
    assert out["workspace"] == "space.a" and stored["workspace"] == "space.a" and stored["member"] == "svc-a"
    assert stored["workspace_default"] == ""
    assert _status(gw.mint_key(ORG, gw.KeyBody(workspace="space.b"), _Req())) == 403


def test_a_person_and_a_key_with_organization_reach_choose_what_they_mint(world, monkeypatch):
    # a person in the console makes an organization key on purpose: the body says so, no header trick
    _mint(monkeypatch, CONSOLE_A, workspace="", member_id="ana@example.com")
    assert world[-1][2]["workspace"] == "" and world[-1][2]["member"] == "ana@example.com"
    _mint(monkeypatch, CONSOLE_A, workspace="space.b", member_id="ana@example.com")
    assert world[-1][2]["workspace"] == "space.b"
    # a Default Workspace key mints a workspace's key for it, and may name whose it is
    _mint(monkeypatch, KEY_DEFAULT, workspace="space.b", member_id="company-b")
    assert world[-1][2]["workspace"] == "space.b" and world[-1][2]["member"] == "company-b"
    _mint(monkeypatch, KEY_ORG, workspace="", member_id="x")
    assert world[-1][2]["workspace"] == ""


def test_a_held_key_revokes_and_lists_its_own_workspaces_keys(world, monkeypatch):
    _as(monkeypatch, KEY_A)
    assert _status(gw.revoke_key(ORG, "key_b", _Req())) == 404 and world == []
    assert asyncio.run(gw.revoke_key(ORG, "key_a", _Req()))["revoked"] is True

    class _Graph:
        async def find(self, label, where):
            return [{"id": "key_a", "workspace": "space.a"}, {"id": "key_b", "workspace": "space.b"}, {"id": "key_o", "workspace": ""}]
    monkeypatch.setattr(gw.BACKING, "graph", _Graph())
    assert [k["id"] for k in asyncio.run(gw.list_keys(ORG, _Req()))["keys"]] == ["key_a"]
    for p in (KEY_ORG, KEY_DEFAULT, CONSOLE_A):
        _as(monkeypatch, p)
        assert len(asyncio.run(gw.list_keys(ORG, _Req()))["keys"]) == 3
        assert asyncio.run(gw.revoke_key(ORG, "key_b", _Req()))["revoked"] is True      # a company's key, retired by the organization's


def test_a_held_key_does_not_make_or_rename_workspaces(world, monkeypatch):
    _as(monkeypatch, KEY_A)
    assert _status(gw.workspaces_create(gw.WorkspaceBody(name="mine"), _Req())) == 403
    assert _status(gw.workspaces_update("space.b", gw.WorkspaceBody(name="theirs"), _Req())) == 403


def test_a_held_keys_plug_routes_are_about_its_own_workspace_whatever_header_it_sends():
    named_b = _Req(headers={"x-harness-workspace": "space.b"})
    assert gw._plug_workspace(named_b, KEY_A) == "space.a"
    assert gw._plug_workspace(named_b, CONSOLE_A) == "space.b" and gw._plug_workspace(named_b, KEY_DEFAULT) == "space.b"
    assert gw._plug_workspace(_Req(), KEY_ORG) == "default"


# ── every route that takes an id asks ──────────────────────────────────────────────────────────

IDS = {"hid", "harness_id", "sid", "response_id", "container_id", "kid", "env_id", "wid"}
ASKS = {"_owned_session", "_owned_environment", "_harness_in_reach", "_harness_for_route", "_media_route",
        "_response_in_reach", "_scope_keeps"}
# A route that takes an id and is not held to a workspace, with the reason it is not.
EXEMPT = {
    "recycle_session_sandbox": "behind the internal key: the platform's own call, no caller to narrow",
    "workspace_by_path": "the public artifact address: one unguessable link, its own check, no caller at all",
    "workspaces_update": "the id IS a workspace: refuses a workspace's key that names another one",
}


def test_every_route_that_takes_an_id_asks_whether_it_is_in_the_callers_workspace():
    tree = ast.parse(pathlib.Path(gw.__file__).read_text())
    missing, seen = [], 0
    for fn in [n for n in tree.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))]:
        for d in fn.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "app"
                    and d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)):
                continue
            if not set(re.findall(r"\{(\w+)", d.args[0].value)) & IDS:
                continue
            seen += 1
            called = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            if not called & ASKS and fn.name not in EXEMPT:
                missing.append(f"{d.func.attr.upper()} {d.args[0].value} ({fn.name})")
    assert seen > 60, "the scan found too few routes, which means it stopped working"
    assert not missing, "routes that take an id and never ask about the workspace:\n  " + "\n  ".join(sorted(set(missing)))
    assert set(EXEMPT) <= {n.name for n in tree.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
