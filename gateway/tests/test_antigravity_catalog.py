"""The antigravity base: Google's managed Antigravity agent, an opt-in remote runtime on the instance's
Google AI Studio connection.

- Registration: the catalog's switches are the runner's tool table, its models the runner's table and
  Google's own list for the agent (a table of its own at Google, so the chat table every other base
  reads is unchanged), wired to the google provider only, native (owner trust only), never picked by
  Auto, and described in words that say where a task's files go.
- Opt-in: not in the default HR_BACKENDS; an instance that did not install it reads not_installed.
- Tools at Google: a stored MCP secret is never sent there (the 0.41.14 binding: a stored token goes
  only to the server it was saved for), nor a tool this instance hosts, nor a stdio or plain-http
  server; each is named with why. A $headers value goes, and only after the same declared-header
  checks every tool gets (_header_denied, _header_value_ours).
- A session delete hands the runner the Google connection, so the sandbox at Google goes too.
All values here are dummies."""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402
import backing  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
import antigravity_driver as drv  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
ORG = "org-antigravity"
TOKEN = "stored-token-DUMMY-0123456789"
GOOD = "https://mcp.good.example/mcp"


def run(coro):
    return asyncio.run(coro)


# ── registration ──────────────────────────────────────────────────────────────────────────────────
def test_the_base_is_registered_as_a_remote_runtime_on_the_google_connection():
    b = gw._BASE_CATALOG["antigravity"]
    assert b["backend"] == "antigravity" and b["remote"] is True and b["environments"] is False
    assert b["tool_enforcement"] == "hard" and b.get("reasoning") is False
    assert [n for n, _ in b["tools"]] == list(drv.TOOLS)
    assert gw._INTEGRATION_WIRING[("google", "antigravity")] == "google"
    assert [p for (p, back) in gw._INTEGRATION_WIRING if back == "antigravity"] == ["google"]
    assert "antigravity" in gw._NATIVE_ONLY_BACKENDS and "antigravity" in gw._SETUP_NOT_AUTO
    assert gw._backend_of_builtin("antigravity") == "antigravity"


def test_its_description_says_where_a_tasks_files_go_in_words():
    d = gw._BASE_CATALOG["antigravity"]["description"]
    for said in ("sent to Google's service", "kept there under Google's terms", "Deleting a task here deletes"):
        assert said in d, said
    # behaviour, never how this product is built
    for internal in ("HarnessRouter", "relay", "broker", "vault", "runner", "gateway", "driver", "tenant"):
        assert internal.lower() not in d.lower(), internal


def test_its_models_are_googles_list_for_the_agent_and_the_chat_table_is_unchanged():
    cat = gw._MODEL_CATALOG["antigravity"]
    assert cat["default"] == drv.DEFAULT_MODEL == "gemini-4-hydrogen"
    assert cat["models"] == list(drv.MODELS)
    assert set(gw._vendor_models("google", "antigravity")) == set(drv.MODELS)
    assert "gemini-4-hydrogen" not in gw._vendor_models("google") and "gemini-4-carbon" not in gw._vendor_models("google")
    assert "antigravity" in gw._STILL_QUALIFYING
    for m in ("gemini-4-hydrogen", "gemini-4-carbon"):
        assert gw._MODEL_ORDER.count(m) == 1, m
        assert not [b for b, c in gw._MODEL_CATALOG.items() if b != "antigravity" and m in c["models"]], m
    # the router maps and serves each id on a Google connection for this base, and only for it
    conn = {"provider": "google", "backend": "antigravity"}
    for m in drv.MODELS:
        assert gw._map_model(conn, m) == m and gw._conn_serves(conn, m, "antigravity"), m
    assert not gw._conn_serves({"provider": "google"}, "gemini-4-hydrogen", "hermes")


def test_the_google_integration_drives_the_agents_models_on_this_base():
    integ = {"name": "Google AI Studio", "provider": "google", "config": {"api_key": "AIza-DUMMY"}}
    assert gw._integration_driving([integ], "antigravity", "gemini-4-hydrogen", None) is integ
    assert gw._integration_models(integ, "antigravity")["gemini-4-carbon"] == "gemini-4-carbon"
    assert "gemini-4-carbon" not in gw._integration_models(integ)


def test_an_instance_with_only_a_google_connection_offers_and_routes_every_model_of_the_agent(monkeypatch):
    """The picker and the router read the model map, which is made from what each integration serves:
    the Antigravity agent's own models (Hydrogen and Carbon are on no chat table) are among them."""
    integ = {"name": "Google AI Studio", "provider": "google", "config": {"api_key": "AIza-DUMMY"}}

    async def integs():
        return [integ]

    async def stored():
        return {}

    async def chain(org, backend, _):
        return []
    monkeypatch.setattr(gw, "_integrations_doc", integs)
    monkeypatch.setattr(gw, "_model_map_doc", stored)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    assert run(gw._effective_model_map())["gemini-4-hydrogen"] == "Google AI Studio"
    assert set(drv.MODELS) <= run(gw._servable_models("local", "antigravity"))
    conn = run(gw._mapped_integration_conn("antigravity", "gemini-4-hydrogen"))
    assert conn["provider"] == "google" and conn["model"] == "gemini-4-hydrogen" and conn["_model_resolved"]
    # a base wired to Google that does not take the agent's models is not routed one (no fall-through)
    assert run(gw._mapped_integration_conn("hermes", "gemini-4-hydrogen")) is None
    assert run(gw._mapped_integration_conn("hermes", "gemini-4-argon"))["model"] == "gemini-4-argon"


def test_the_picker_offers_the_agents_models_and_no_gemini_chat_model(monkeypatch):
    """A Google connection serves the Gemini chat models on other bases; on this base the picker offers
    the agent's own list and nothing else (two chat models were offered here, measured 2026-11-14)."""
    integ = {"name": "Google AI Studio", "provider": "google", "config": {"api_key": "AIza-DUMMY"}}

    async def integs():
        return [integ]

    async def stored():
        return {}

    async def chain(org, backend, _):
        return []
    monkeypatch.setattr(gw, "_integrations_doc", integs)
    monkeypatch.setattr(gw, "_model_map_doc", stored)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    eff = run(gw._effective_model_map())
    chat = [m for m in eff if m not in drv.MODELS]
    assert chat, "the connection must map some Gemini chat model for this test to mean anything"
    view = run(gw._harness_models_view({}, "antigravity", run(gw._servable_models("local", "antigravity"))))
    assert [m["id"] for m in view["models"]] == list(drv.MODELS)
    gem = run(gw._harness_models_view({}, "gemini", run(gw._servable_models("local", "gemini"))))
    assert set(chat) & {m["id"] for m in gem["models"]}            # ...which a chat base still offers


def test_a_server_left_out_on_purpose_is_named_with_why_not_as_unreachable():
    """The agent's reply says which tool it ran without and why (a tool this instance serves stays here);
    "could not be reached" was the sentence before, which reads as an outage (seen live, 2026-11-14)."""
    blocks = gw._blocks_from_canonical({"type": "system", "subtype": "mcp_unavailable", "servers": [
        {"name": "memories", "reason": gw._WITHHELD_HOSTED, "withheld": True}]})
    assert blocks == [("text", '\n\n_Note: the MCP server "memories" was not given to the agent (a tool this instance '
                               'serves itself: its access stays on this instance), so this reply ran without it._\n\n')]
    mixed = gw._blocks_from_canonical({"type": "system", "subtype": "mcp_unavailable", "servers": [
        {"name": "kept-here", "reason": "r", "withheld": True}, {"name": "dead", "reason": "fetch failed"}]})
    assert [t for _, t in mixed] == ['\n\n_Note: the MCP server "kept-here" was not given to the agent (r), so this '
                                     'reply ran without it._\n\n',
                                     '\n\n_Note: the MCP server "dead" could not be reached, so this reply ran '
                                     'without those tools._\n']


def test_the_bases_document_carries_the_description_and_offers_no_thinking_level(monkeypatch):
    async def org_member(_request):
        return "local", "owner"

    async def servable(_org, _backend):
        return None
    monkeypatch.setattr(gw, "_pub_org_member", org_member)
    monkeypatch.setattr(gw, "_servable_models", servable)
    monkeypatch.delenv("HR_BACKENDS_INSTALLED", raising=False)
    bases = {b["id"]: b for b in run(gw.list_bases(None))["bases"]}
    ag = bases["antigravity"]
    assert ag["description"] == gw._BASE_CATALOG["antigravity"]["description"]
    assert ag["takesEnvironments"] is False and [t["enforcement"] for t in ag["tools"]] == ["hard"] * 3
    assert all(m["reasoning"] == [] for m in ag["models"])           # gemini-4-argon has levels elsewhere
    assert any(m["reasoning"] for m in bases["gemini"]["models"])     # ...which every other base still shows
    assert "description" not in bases["codex"]


def test_only_the_owner_trust_hands_the_runner_the_key(monkeypatch):
    conn = {"name": "integration:Google", "backend": "antigravity", "provider": "google", "api_key": "AIza-DUMMY-KEY"}
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "")
    assert gw._auth_from_conn(dict(conn), "sess1") is None           # never a broker credential sent to Google as a key
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    assert gw._auth_from_conn(dict(conn), "sess1")["api_key"] == "AIza-DUMMY-KEY"


# ── opt-in ───────────────────────────────────────────────────────────────────────────────────────
def test_the_base_is_opt_in():
    src = (ROOT / "docker" / "entrypoint.sh").read_text()
    default = re.search(r'export HR_BACKENDS="\$\{HR_BACKENDS:-([^}]*)\}"', src).group(1).split(",")
    assert "antigravity" not in default and "qoder" in default
    assert re.search(r'^\s*antigravity\) echo "\$PY" ;;', src, re.M)       # installed means the runner's interpreter


def test_an_instance_that_did_not_turn_it_on_reads_not_installed_and_refuses_a_turn(monkeypatch):
    async def org_member(_request):
        return "local", "owner"

    async def servable(_org, _backend):
        return None
    monkeypatch.setattr(gw, "_pub_org_member", org_member)
    monkeypatch.setattr(gw, "_servable_models", servable)
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "claude,codex,gemini,qoder")
    bases = {b["id"]: b for b in run(gw.list_bases(None))["bases"]}
    assert bases["antigravity"]["status"] == "not_installed"
    assert bases["antigravity"]["statusReason"].startswith("Antigravity Agent is not installed on this instance.")
    with pytest.raises(gw.HTTPException) as refused:
        gw._require_installed("antigravity")
    assert refused.value.status_code == 400 and "HR_BACKENDS" in refused.value.detail
    monkeypatch.setenv("HR_BACKENDS_INSTALLED", "claude,antigravity")
    assert {b["id"]: b for b in run(gw.list_bases(None))["bases"]}["antigravity"]["status"] == "ready"


# ── tools at Google ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setenv("HR_SECRET_KEY", "k")
    s = backing.FileSecretStore(tempfile.mkdtemp(prefix="hr-ag-"))
    monkeypatch.setattr(gw.BACKING, "secrets", s)
    monkeypatch.setattr(gw, "_org_tenant", lambda org: org or None)

    async def ok(_url):
        return ""
    monkeypatch.setattr(gw, "_ssrf_check", ok)
    return s


def _vertex(servers):
    return {"id": "chrn_ag", "org": ORG, "base": "antigravity", "workspace": "",
            "mcp_servers": json.dumps(list(servers)), "env": "{}"}


def _bind(ref: str, url: str = GOOD) -> str:
    key = f"harness-mcp-{ref}"
    run(gw._vault_put(ORG, key, TOKEN))
    run(gw._mcp_binding_add(ORG, key, uses=[gw._mcp_use_of_url(url)], workspaces=["default"]))
    return key


def test_a_stored_secret_is_never_sent_to_google_and_is_named_with_why(store):
    key = _bind("crm")
    servers = [{"name": "crm", "url": GOOD, "auth": f"vault:{key}", "enabled": True},
               {"name": "crm-header", "url": GOOD, "headers": {"X-Key": f"vault:{key}"}, "enabled": True},
               {"name": "literal", "url": GOOD, "headers": {"X-Org": "acme-literal"}, "enabled": True},
               {"name": "per-request", "url": GOOD, "auth": "$headers.X-Crm-Token",
                "headers": {"X-Tenant": "t-$headers.X-Tenant"}, "enabled": True},
               {"name": "open", "url": "https://open.example/mcp", "enabled": True},
               {"name": "plain-http", "url": "http://open.example/mcp", "enabled": True}]
    hdr = {"x-crm-token": "per-request-token-DUMMY-1", "x-tenant": "acme"}
    # the binding holds: for a base on this instance the stored token resolves for its server...
    local = run(gw._harness_plugins("chrn_ag", ORG, hdr, hv=_vertex(servers)))[0]
    assert {m["name"]: m.get("auth") for m in local}["crm"] == TOKEN
    # ...and for the agent at Google it never does
    withheld: list[dict] = []
    sent = run(gw._harness_plugins("chrn_ag", ORG, hdr, hv=_vertex(servers), withheld=withheld))[0]
    assert TOKEN not in json.dumps(sent)
    assert [m["name"] for m in sent] == ["per-request", "open"]
    per = sent[0]
    assert per["auth"] == "per-request-token-DUMMY-1" and per["headers"] == {"X-Tenant": "t-acme"}
    why = {w["name"]: w["reason"] for w in withheld}
    assert set(why) == {"crm", "crm-header", "literal", "plain-http"}
    assert why["crm"] == gw._WITHHELD_STORED and why["literal"] == gw._WITHHELD_STORED
    assert why["plain-http"] == gw._WITHHELD_ADDRESS
    assert TOKEN not in json.dumps(withheld)


def test_a_tool_this_instance_hosts_is_not_sent(store, monkeypatch):
    monkeypatch.setattr(gw, "_hosted_mcp_path", lambda url: "/v1/mcp/media" if "/v1/mcp/" in url else "")
    servers = [{"name": "media", "url": "https://this.instance/v1/mcp/media", "auth": "vault:harness-hosted-x", "enabled": True}]
    withheld: list[dict] = []
    sent = run(gw._harness_plugins("chrn_ag", ORG, {}, hv=_vertex(servers), withheld=withheld))[0]
    assert sent == [] and withheld == [{"name": "media", "reason": gw._WITHHELD_HOSTED}]


def test_per_request_values_are_only_what_the_request_brings():
    assert gw._only_per_request(["$headers.X-A", "Bearer $headers.X-B", "", None])
    for stored in (["vault:harness-mcp-x"], ["literal-token"], ["$headers.X-A", "vault:harness-mcp-y"],
                   ["prefix vault:harness-mcp-z $headers.X"]):
        assert not gw._only_per_request(stored), stored


class _Runner:
    def __init__(self):
        self.ran: list[dict] = []

    async def __call__(self, translator, **kw):
        self.ran.append({"backend": kw.get("backend"), "hdr_vals": dict(kw.get("hdr_vals") or {})})
        translator.feed({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}})
        return "completed", [], {"status": "done"}


@pytest.fixture()
def turns(monkeypatch):
    async def who(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", who)

    async def chain(org, backend, _):
        return ["c1"]
    monkeypatch.setattr(gw, "_resolve_chain", chain)

    async def no_ssrf(_url):
        return None
    monkeypatch.setattr(gw, "_ssrf_check", no_ssrf)
    monkeypatch.delenv("HR_BACKENDS_INSTALLED", raising=False)
    runner = _Runner()
    monkeypatch.setattr(gw, "_resp_execute", runner)

    def record(headers: list[str], servers: list[dict]) -> str:
        hid = f"chrn_ag{time.time_ns() % 10**12}"
        run(gw.BACKING.graph.upsert("Harness", hid, {
            "org": ORG, "member": "me@local", "workspace": "", "name": hid, "base": "antigravity", "deleted": "0",
            "created_at": str(int(time.time() * 1000)), "additional_headers": json.dumps(headers),
            "mcp_servers": json.dumps(servers), "env": "{}"}))
        return hid
    return {"api": TestClient(gw.app), "runner": runner, "record": record}


OUR_KEY = "sk-hr-" + "0123456789abcdef" * 4
SESSION = "person-credential-DUMMY-0123456789abcdef"


@pytest.mark.parametrize("value,extra", [(f"Bearer {SESSION}", {"Authorization": f"Bearer {SESSION}"}),
                                         (f"x-{OUR_KEY}", {}),
                                         ("token=v1.1794432583032." + "ab" * 32, {})])
def test_a_header_value_bound_for_google_is_held_to_the_same_value_check(turns, value, extra):
    """A $headers value goes to Google's sandbox for this base, so the checks every tool's declared
    header gets hold here too: the request's own credential, an API key of ours or a console session
    refuses the task before anything starts."""
    srv = {"name": "crm", "url": GOOD, "auth": "$headers.X-Crm", "enabled": True}
    hid = turns["record"](["X-Crm"], [srv])
    r = turns["api"].post("/v1/responses", headers={"X-Crm": value, **extra},
                          json={"input": "hello", "metadata": {"harness_id": hid}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "header_not_allowed", r.text
    assert turns["runner"].ran == [] and value not in r.text


@pytest.mark.parametrize("name", ["Authorization", "X-Harness-Org", "Cookie"])
def test_a_denied_header_name_bound_for_google_refuses_the_task(turns, name):
    srv = {"name": "crm", "url": GOOD, "auth": f"$headers.{name}", "enabled": True}
    hid = turns["record"]([name], [srv])
    r = turns["api"].post("/v1/responses", headers={name: SESSION},
                          json={"input": "hello", "metadata": {"harness_id": hid}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "header_not_allowed", r.text
    assert turns["runner"].ran == []


def test_a_header_of_the_requests_own_reaches_the_turn(turns):
    srv = {"name": "crm", "url": GOOD, "auth": "$headers.X-Crm", "enabled": True}
    hid = turns["record"](["X-Crm"], [srv])
    r = turns["api"].post("/v1/responses", headers={"X-Crm": "crm-own-token-DUMMY-1"},
                          json={"input": "hello", "metadata": {"harness_id": hid}})
    assert r.status_code == 200, r.text
    assert turns["runner"].ran[0]["backend"] == "antigravity"
    assert turns["runner"].ran[0]["hdr_vals"] == {"x-crm": "crm-own-token-DUMMY-1"}


# ── a session delete reaches Google ──────────────────────────────────────────────────────────────
def test_a_session_delete_hands_the_runner_the_google_connection(monkeypatch):
    async def integs():
        return [{"name": "Google AI Studio", "provider": "google", "config": {"api_key": "AIza-DUMMY-KEY"}},
                {"name": "OpenAI", "provider": "openai", "config": {"api_key": "sk-DUMMY"}}]
    monkeypatch.setattr(gw, "_integrations_doc", integs)
    monkeypatch.setattr(gw, "SANDBOX_TRUST", "owner")
    body = run(gw._remote_delete_body("s1", {"backend": "antigravity", "last_connection": "integration:Google AI Studio"}))
    assert body["backend"] == "antigravity" and body["auth"]["api_key"] == "AIza-DUMMY-KEY"
    u = urllib.parse.urlsplit(body["auth"]["base_url"])
    assert (u.scheme, u.hostname) == ("https", "generativelanguage.googleapis.com")
    assert run(gw._remote_delete_body("s1", {"backend": "codex"})) is None
    # a session whose connection is gone, with another of the same provider: nothing is guessed
    gone = run(gw._remote_delete_body("s1", {"backend": "antigravity", "last_connection": "integration:Old"}))
    assert gone == {"backend": "antigravity"}
