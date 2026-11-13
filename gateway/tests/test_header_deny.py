"""A setup can never pass the caller's own credential, or one of ours, to its tools. A setup declares header NAMES; a task
request's values for them reach its MCP servers and its environment through $headers.<name>.

- By name, in any letter case: Authorization, everything the relays keep for us (cookie, proxy-authorization,
  x-internal-key, the forwarding and client-address names) and every x-harness-* and x-hr-* name. A setup write that
  declares one, or references one in an MCP server (url, auth, headers) or its environment, is refused (422). A turn on a
  setup written before never reads it, and a reference to one refuses the task (400).
- By value, at the turn: a declared header carrying the request's own credential, this instance's internal key, an API
  key of ours (sk-hr-...) or a console session refuses the task (400), whatever the header is called.
- A vendor's key names (X-Api-Key, Api-Key, X-Goog-Api-Key) and a setup's own names pass.
All values here are dummies."""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

ORG = "org.hdrdeny"
SESSION = "person-credential-DUMMY-0123456789abcdef"
SAID = "can't be passed to tools"
DENIED = ["Authorization", "authorization", "AUTHORIZATION", "Cookie", "Proxy-Authorization", "X-Internal-Key",
          "X-Harness-Org", "x-harness-internal", "X-Harness-Anything", "X-HR-Anything", "X-Forwarded-For", "X-Real-IP",
          "CF-Connecting-IP", "True-Client-IP", "Forwarded"]
OWN = ["X-My-Token", "X-Authorization-Hint", "Authorization-Ext", "X-Api-Key", "api-key", "X-Goog-Api-Key"]


@pytest.fixture()
def api(monkeypatch):
    async def who(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", who)

    async def chain(org, backend, _):
        return ["c1"]
    monkeypatch.setattr(gw, "_resolve_chain", chain)

    async def no_ssrf(_url):
        return None
    monkeypatch.setattr(gw, "_ssrf_check", no_ssrf)
    return TestClient(gw.app)


def _said_right(r, name: str, code: int) -> None:
    assert r.status_code == code, r.text
    err = r.json()["error"]
    assert err["code"] == "header_not_allowed" and SAID in err["message"] and name in err["message"], err


def _create(api, **cfg):
    return api.post("/v1/harnesses", json={"name": f"hdr-{uuid.uuid4().hex[:6]}", "base": "claude-code", **cfg})


def _names(api) -> set[str]:
    return {h["name"] for h in api.get("/v1/harnesses").json().get("harnesses") or []}


def test_the_deny_rule_itself():
    for n in DENIED:
        assert gw._header_denied(n) and gw._header_denied(f"  {n} "), n
    for n in OWN + ["", None]:
        assert not gw._header_denied(n), n
    assert gw._denied_header_refs({"a": ["x $headers.Authorization y", {"b": "$headers.X-HR-Z"}], "c": "$headers.X-Ok"}) \
        == {"Authorization", "X-HR-Z"}


# ── the write ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", DENIED)
def test_a_setup_that_declares_a_denied_header_is_refused_and_not_stored(api, name):
    before = _names(api)
    r = _create(api, additional_headers=["X-Fine", name])
    _said_right(r, name, 422)
    assert r.json()["error"]["param"] == "additional_headers"
    assert _names(api) == before


@pytest.mark.parametrize("name", ["Authorization", "x-harness-internal", "Cookie", "X-HR-Bill"])
@pytest.mark.parametrize("where", ["auth", "headers", "url", "env"])
def test_a_setup_that_points_a_tool_or_its_environment_at_a_denied_header_is_refused(api, name, where):
    srv = {"name": "orders", "url": "https://mcp.example.test/mcp"}
    env = None
    if where == "auth":
        srv["auth"] = f"Bearer $headers.{name}"
    elif where == "headers":
        srv["headers"] = {"x-up": f"$headers.{name}"}
    elif where == "url":
        srv["url"] = f"https://mcp.example.test/mcp?t=$headers.{name}"
    else:
        env = {"TOKEN": f"$headers.{name}"}
    cfg = {"additional_headers": ["X-Fine"], "mcp_servers": [srv] if where != "env" else []}
    if env:
        cfg["env"] = env
    r = _create(api, **cfg)
    _said_right(r, name, 422)
    assert r.json()["error"]["param"] == ("env" if where == "env" else "mcp_servers")


def test_an_update_is_refused_the_same_way(api):
    r = _create(api, additional_headers=["X-Fine"])
    hid = r.json()["id"]
    r = api.put(f"/v1/harnesses/{hid}", json={"name": "u", "base": "claude-code", "additional_headers": ["Authorization"]})
    _said_right(r, "Authorization", 422)
    r = api.put(f"/v1/orgs/{ORG}/harnesses/{hid}", json={"name": "u", "base": "claude-code", "env": {"T": "$headers.Cookie"}})
    _said_right(r, "Cookie", 422)


def test_a_setups_own_names_pass(api):
    for name in OWN:
        r = _create(api, additional_headers=[name],
                    mcp_servers=[{"name": "own", "url": "https://mcp.example.test/mcp", "auth": f"$headers.{name}",
                                  "headers": {"x-up": f"$headers.{name}"}}],
                    env={"S": f"$headers.{name}"})
        assert r.status_code == 200, (name, r.text)


# ── the turn, on a setup written before the write refused it ───────────────────────────────────────

class _Runner:
    def __init__(self):
        self.ran: list[dict] = []

    async def __call__(self, translator, **kw):
        self.ran.append(dict(kw.get("hdr_vals") or {}))
        translator.feed({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}})
        return "completed", [], {"status": "done"}


@pytest.fixture()
def turns(api, monkeypatch):
    runner = _Runner()
    monkeypatch.setattr(gw, "_resp_execute", runner)

    def record(headers: list[str], servers: list[dict], env: dict | None = None) -> str:
        """A setup as one written before the write refused it: straight to the store."""
        hid = f"chrn_hdrdeny{time.time_ns() % 10**12}"
        asyncio.run(gw.BACKING.graph.upsert("Harness", hid, {
            "org": ORG, "member": "me@local", "workspace": "", "name": hid, "base": "claude-code", "deleted": "0",
            "created_at": str(int(time.time() * 1000)), "additional_headers": json.dumps(headers),
            "mcp_servers": json.dumps(servers), "env": json.dumps(env or {})}))
        return hid
    return {"api": api, "runner": runner, "record": record}


def _ask(t, hid: str, headers: dict):
    return t["api"].post("/v1/responses", headers=headers, json={"input": "hello", "metadata": {"harness_id": hid}})


@pytest.mark.parametrize("name", ["Authorization", "AUTHORIZATION", "X-Harness-Org", "x-harness-internal", "Cookie"])
def test_a_declared_denied_header_is_never_read_at_the_turn_and_said_once(turns, capsys, name):
    hid = turns["record"]([name, "X-My-Token"], [])
    r = _ask(turns, hid, {name: SESSION, "X-My-Token": "mine-dummy"})
    assert r.status_code == 200, r.text
    assert turns["runner"].ran == [{"x-my-token": "mine-dummy"}], turns["runner"].ran
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("[headers] WARNING")]
    assert len(lines) == 1 and gw._mcp_sha8(hid) in lines[0] and name.lower() in lines[0], lines
    assert SESSION not in out and hid not in lines[0]


@pytest.mark.parametrize("ref", ["$headers.Authorization", "Bearer $headers.authorization", "$headers.X-HR-Bill",
                                 "$headers.Cookie", "$headers.x-harness-internal"])
@pytest.mark.parametrize("where", ["auth", "headers", "url", "env"])
def test_a_setup_that_points_a_tool_or_its_environment_at_a_denied_header_refuses_the_task(turns, capsys, ref, where):
    name = ref.rsplit(".", 1)[1]
    srv = {"name": "orders", "url": "https://mcp.example.test/mcp", "enabled": True}
    env = None
    if where == "auth":
        srv["auth"] = ref
    elif where == "headers":
        srv["headers"] = {"x-up": ref}
    elif where == "url":
        srv["url"] = f"https://mcp.example.test/mcp?t={ref.split()[-1]}"
    else:
        env = {"TOKEN": ref}
    hid = turns["record"]([name], [srv] if where != "env" else [], env)
    r = _ask(turns, hid, {name: SESSION})
    _said_right(r, name, 400)
    assert turns["runner"].ran == [], "the task never starts"
    out = capsys.readouterr().out
    assert SESSION not in out and SESSION not in r.text


# ── by value, whatever the header is called ─────────────────────────────────────────────────────────

CONSOLE_SESSION = "v1.1794432583032." + "ab" * 32
OUR_KEY = "sk-hr-" + "0123456789abcdef" * 4


@pytest.mark.parametrize("value,extra", [
    (SESSION, {"Authorization": f"Bearer {SESSION}"}),              # the request's own bearer, raw
    (f"Bearer {SESSION}", {"Authorization": f"Bearer {SESSION}"}),  # or with Bearer
    (f"prefix-{OUR_KEY}-suffix", {}),                                # anyone's API key of ours
    (f"token={CONSOLE_SESSION}", {}),                                # a console session
])
def test_a_declared_header_whose_value_is_ours_refuses_the_task(turns, capsys, value, extra):
    hid = turns["record"](["X-Auth"], [{"name": "s", "url": "https://mcp.example.test/mcp", "auth": "$headers.X-Auth",
                                        "enabled": True}])
    r = _ask(turns, hid, {"X-Auth": value, **extra})
    assert r.status_code == 400 and r.json()["error"]["code"] == "header_not_allowed", r.text
    assert "x-auth" in r.json()["error"]["message"].lower() and value not in r.text
    assert turns["runner"].ran == []
    out = capsys.readouterr().out
    assert value not in out and SESSION not in out and OUR_KEY not in out


def test_the_internal_key_in_a_declared_header_refuses_the_task(turns, monkeypatch):
    monkeypatch.setattr(gw, "INTERNAL_KEY", "internal-key-DUMMY-0123456789")
    hid = turns["record"](["X-Up"], [])
    r = _ask(turns, hid, {"X-Up": "x internal-key-DUMMY-0123456789 y"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "header_not_allowed"


def test_a_vendors_key_and_short_values_pass(turns):
    hid = turns["record"](["X-Api-Key", "X-Short"], [{"name": "s", "url": "https://mcp.example.test/mcp",
                                                       "auth": "$headers.X-Api-Key", "enabled": True}])
    r = _ask(turns, hid, {"X-Api-Key": "vendor-key-dummy-123456789", "X-Short": "abc",
                          "Authorization": "Bearer abc"})                       # a credential under 16 never matches
    assert r.status_code == 200, r.text
    assert turns["runner"].ran == [{"x-api-key": "vendor-key-dummy-123456789", "x-short": "abc"}]
