"""New setup's builder (setup_builder), the hosted service's flow on this server: a built-in harness,
running on one of this instance's own models (the best one it can run, by the default order), reads
the person's current workspace (its connected plugins and the media tools, the skills and MCP servers
its setups have, its environments, the harnesses and models this instance runs) and writes the setup's
configuration through configure_harness; the server saves it into that workspace. The console starts a
build with a key and reads its record by that key, a read that waits for the next change. Asserted:
the builder sees that one workspace and no other, every answer is settled against what it was offered,
a workspace skill and server are copied onto the new setup, a plugin not connected is asked for and
bound, one key is one build, the hourly budget, the model order and how each model is reached, a model
that refuses the call gives way to the next, no model at all is refused before anything starts, and a
builder that cannot answer saves nothing."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as gw  # noqa: E402
import setup_builder as sb  # noqa: E402

KEY = "sk-own-key-test-not-real"
ORG_A, WS_A = "org.build.acme", "ws_acme"
ORG_B, WS_B = "org.build.other", "ws_other"
INT = {"x-harness-internal": "test-internal-key"}
ADA = {"org": ORG_A, "member": "ada@acme.example", "workspace": WS_A, "workspace_default": False}
BOB = {"org": ORG_B, "member": "bob@other.example", "workspace": WS_B, "workspace_default": False}

JOB = ("Build an agent that answers our support emails: look up the customer's order in our CRM and draft a "
       "reply in our tone.")
INSTR = ("You draft replies to support emails for a small online shop. Each request is one customer email, "
         "pasted as it arrived. Find the order it is about in the CRM server by the order number or the "
         "customer's email address, read its status, then draft a short reply in the shop's tone: warm, plain "
         "and specific. Follow the reply-tone skill for wording. Return the draft only, with a subject line. If "
         "the email names no order and the CRM finds none for the sender, ask for the order number. Never "
         "promise a refund or a date the order does not show.")
EXAMPLE = "Hi, my order 4821 still says processing after a week. When will it ship?"
TONE_MD = "---\nname: reply-tone\ndescription: How the shop writes to customers.\n---\nWarm, plain, no exclamation marks."

BASES = {
    "hermes": {"name": "Hermes", "default": "gpt-5.4", "models": ["gpt-5.4", "deepseek-v4-pro"], "skills": True, "auto": True},
    "dsh": {"name": "DeepSeek Harness", "default": "deepseek-v4-pro", "models": ["deepseek-v4-pro", "deepseek-v4-flash"], "skills": True, "auto": True},
    "systemone": {"name": "System One", "default": "jev-latest", "models": ["jev-latest"], "skills": False, "auto": False},
}
PLUGS = {(ORG_A, WS_A): {"github": "connected", "vercel": "missing", "browser": "missing", "insforge": "missing",
                         "microsoft365": "missing"},
         (ORG_B, WS_B): {"vercel": "connected"}}
ENVS = {ORG_A: [{"id": "henv_a", "org": ORG_A, "workspace": WS_A, "name": "Data tools", "slug": "data",
                 "description": "Python with pandas.", "active_version": "1", "packages": json.dumps(["pandas"])},
                {"id": "henv_a2", "org": ORG_A, "workspace": WS_A, "name": "Not built", "slug": "nb", "active_version": ""}],
        ORG_B: [{"id": "henv_b", "org": ORG_B, "workspace": WS_B, "name": "Other env", "slug": "other", "active_version": "1"}]}
WIRE = {"url": "https://router.test/v1/chat/completions", "headers": {"authorization": f"Bearer {KEY}"},
        "model": "openai/gpt-5.4", "canonical": "gpt-5.4", "route": "openrouter"}


def configure(**over) -> dict:
    args = {"name": "Support replies", "instructions": INSTR, "example_task": EXAMPLE, "base": "dsh",
            "model": "deepseek-v4-pro", "plugins": [], "skills": ["skill:reply-tone"], "mcp_servers": [],
            "environment": "", "connections_needed": []}
    args.update(over)
    return args


def call(name: str, args: dict | str, cid: str = "call_1", reasoning: str = "") -> dict:
    a = args if isinstance(args, str) else json.dumps(args)
    msg = {"role": "assistant", "content": None,
           "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": a}}]}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"message": msg}]}


class FakeChat:
    """The provider's chat completions endpoint: answers in turn what the test queues, then `answer`."""

    def __init__(self):
        self.calls: list[dict] = []
        self.queue: list = []
        self.answer = (200, call(sb.TOOL, configure()))
        self.delay = 0.0
        self.by_url: dict = {}

    async def post(self, url, **kw):
        self.calls.append({"url": url, **json.loads(json.dumps(kw))})
        if self.delay:
            await asyncio.sleep(self.delay)
        status, answer = self.by_url[url] if url in self.by_url else (self.queue.pop(0) if self.queue else self.answer)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(status, json=answer, request=httpx.Request("POST", url))


def _setup_rows():
    """The workspace's setups, as the store keeps them: one with a skill of its own and a server with
    a stored token, one with only a switch on a built-in, and another workspace's."""
    return [
        {"id": "chrn_mine1", "org": ORG_A, "workspace": WS_A, "member": ADA["member"], "deleted": "0", "name": "Support desk",
         "base": "hermes", "updated_at": "2", "created_at": "1",
         "skills": json.dumps([{"name": "reply-tone", "enabled": True, "files": [{"path": "SKILL.md", "content": TONE_MD}]},
                               {"name": "imagegen", "enabled": False}]),
         "mcp_servers": json.dumps([{"id": "mcp.crm00001", "name": "crm", "url": "https://crm.acme.example/mcp",
                                     "transport": "http", "auth": "vault:harness-mcp-mcp-crm00001", "enabled": True},
                                    {"id": "mcp.plugs", "name": "plugs", "url": "https://gateway.example/v1/mcp/plugs",
                                     "transport": "http", "auth": "vault:x"}])},
        {"id": "chrn_mine2", "org": ORG_A, "workspace": WS_A, "member": ADA["member"], "deleted": "0", "name": "Images",
         "base": "hermes", "updated_at": "1", "created_at": "1", "skills": json.dumps([{"name": "imagegen", "enabled": False}])},
        {"id": "chrn_theirs", "org": ORG_B, "workspace": WS_B, "member": BOB["member"], "deleted": "0", "name": "Other",
         "base": "hermes", "updated_at": "1", "created_at": "1",
         "skills": json.dumps([{"name": "other-secret", "enabled": True, "files": [{"path": "SKILL.md", "content": "Not Acme's."}]}]),
         "mcp_servers": json.dumps([{"id": "mcp.zz", "name": "theirs", "url": "https://other.example/mcp", "transport": "http"}])},
    ]


@pytest.fixture
def env(monkeypatch):
    who = {"p": dict(ADA)}
    chat = FakeChat()
    store: dict[str, dict] = {r["id"]: dict(r) for r in _setup_rows()}
    vault: dict[tuple[str, str], str] = {(gw._org_tenant(ORG_A), "harness-mcp-mcp-crm00001"): "crm-token-not-real"}
    rec: dict[str, list] = {"plugs_attach": [], "media": [], "offered": [], "lookups": [], "wires": []}

    async def principal(_request):
        return dict(who["p"])

    async def bases(org):
        return json.loads(json.dumps(BASES))

    async def builtin(org):
        return {"pdf": {"name": "PDF", "about": "Read and write PDF files."}}

    async def lookup(org, ws, t):
        rec["lookups"].append((org, ws))
        status = PLUGS.get((org, ws), {}).get(t, "missing")
        return status, ({"config": {}} if status == "connected" else None)

    async def list_by_org(label, org):
        if label == "Environment":
            return [dict(x) for x in ENVS.get(org, [])]
        return [dict(v) for v in store.values() if v.get("org") == org and v.get("_label", "Harness") == label]

    async def vertex_get(vid):
        return dict(store[vid]) if vid in store else None

    async def upsert(label, vid, props, raise_on_fail=False):
        store[vid] = {**store.get(vid, {}), "id": vid, "_label": label, **props}

    async def offered(org, base, model, previous=""):
        rec["offered"].append((org, base, model))

    async def env_ref(org, env_id):
        if env_id and env_id not in {e["id"] for e in ENVS.get(org, [])}:
            raise gw.uhp_error(404, "environment_not_found", "No environment with that id.", "environment")

    async def media_attach(org, hid, v, decl):
        rec["media"].append((org, hid, decl["id"]))

    async def plugs_attach(org, hid, v, plugs, tools):
        rec["plugs_attach"].append({"org": org, "hid": hid, "workspace": v.get("workspace"), "plugs": plugs})

    async def media_providers():
        return {"fal": {}}

    async def wires(org):
        rec["wires"].append(org)
        return [dict(WIRE)]

    async def vault_get(tenant, key):
        return vault.get((tenant, key))

    async def vault_put(tenant, key, value):
        vault[(tenant, key)] = value

    monkeypatch.setattr(gw, "_principal", principal)
    monkeypatch.setattr(gw, "_client", lambda: chat)
    monkeypatch.setattr(gw, "_setup_bases", bases)
    monkeypatch.setattr(gw, "_setup_builtin_skills", builtin)
    monkeypatch.setattr(gw, "_builtin_skills", lambda: {"pdf": {"files": [{"path": "SKILL.md", "content": "PDF skill body."}]}})
    monkeypatch.setattr(gw, "_plug_lookup", lookup)
    monkeypatch.setattr(gw, "_vg_list_by_org", list_by_org)
    monkeypatch.setattr(gw, "_vertex_get", vertex_get)
    monkeypatch.setattr(gw, "_vg_upsert", upsert)
    monkeypatch.setattr(gw, "_require_offered_model", offered)
    monkeypatch.setattr(gw, "_environment_check_ref", env_ref)
    monkeypatch.setattr(gw, "_hosted_media_attach", media_attach)
    monkeypatch.setattr(gw, "_plugs_attach", plugs_attach)
    monkeypatch.setattr(gw, "_media_providers", media_providers)
    monkeypatch.setattr(gw, "_setup_build_wires", wires)
    monkeypatch.setattr(gw, "_vault_get", vault_get)
    monkeypatch.setattr(gw, "_vault_put", vault_put)
    monkeypatch.setattr(sb, "RECORDS", sb._Records())
    with TestClient(gw.app) as c:
        yield {"c": c, "who": who, "chat": chat, "store": store, "vault": vault, **rec}


def start(env, key="b1test0001", job=JOB, base="auto", model="auto", workspace=""):
    return env["c"].post("/v1/harnesses/builds", json={"job": job, "base": base, "model": model, "workspace": workspace,
                                                       "key": key}, headers=INT)


def settled(env, key="b1test0001") -> dict:
    for _ in range(400):
        r = env["c"].get(f"/v1/harnesses/builds/{key}", headers=INT)
        assert r.status_code == 200, r.text
        if r.json()["status"] != "building":
            return r.json()
        time.sleep(0.01)
    raise AssertionError("the build never settled")


def first_message(call: dict) -> dict:
    """What the builder was given: the documents block of its system message (the user message is the task)."""
    text = call["json"]["messages"][0]["content"]
    assert call["json"]["messages"][1] == {"role": "user", "content": sb.TASK}
    return json.loads(text.split("<documents>\n", 1)[1].split("\n</documents>", 1)[0])


def built(env) -> list[dict]:
    return [v for k, v in env["store"].items() if v.get("_label") == "Harness" and k.startswith("chrn_") and k not in
            {"chrn_mine1", "chrn_mine2", "chrn_theirs"}]


def mcp_id(url: str) -> str:
    return gw._setup_build_mcp_id(url)


CRM = mcp_id("https://crm.acme.example/mcp")


# ── the builder, and what it reads ───────────────────────────────────────────────────────────────
def test_the_builder_runs_on_the_instances_own_model_reading_this_workspace_only(env):
    r = start(env)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "building" and r.json()["step"] == "reading" and r.json()["key"] == "b1test0001"
    out = settled(env)
    assert out["status"] == "saved", out
    call0 = env["chat"].calls[0]
    assert call0["url"] == WIRE["url"] and call0["headers"]["authorization"] == f"Bearer {KEY}"
    assert call0["json"]["model"] == "openai/gpt-5.4" and "reasoning_effort" not in call0["json"]
    assert env["wires"] == [ORG_A]
    names = [t["function"]["name"] for t in call0["json"]["tools"]]
    assert names == ["read_items", "configure_harness"] and call0["json"]["tool_choice"] == "auto"   # no apps catalog here
    sys_text = call0["json"]["messages"][0]["content"]
    assert "configuration, not a task" in sys_text and "never the team's sentence repeated" in sys_text
    assert "find_apps" not in sys_text and "apps_needed" not in sys_text
    assert "The team wrote in English. Write the name, the instructions and the example in English." in sys_text
    given = first_message(call0)
    assert given["what_it_should_do_for_users"] == JOB
    ws = given["workspace"]
    assert [x["id"] for x in ws["plugins"]] == ["github", "media"] and ws["plugins"][0]["about"].startswith("Tools: ")
    assert {x["id"] for x in ws["skills"]} == {"pdf", "skill:reply-tone"}
    assert next(x for x in ws["skills"] if x["id"] == "skill:reply-tone")["about"] == "How the shop writes to customers."
    assert [x["id"] for x in ws["mcp_servers"]] == [CRM] and "crm.acme.example" in ws["mcp_servers"][0]["about"]
    assert [x["id"] for x in ws["environments"]] == ["henv_a"]                   # the one with a built version
    assert [x["id"] for x in ws["not_connected"]] == ["browser", "insforge", "vercel"]   # never Microsoft 365
    assert "apps" not in ws
    flat = json.dumps(call0["json"])
    for theirs in ("other-secret", "other.example", "henv_b", "crm-token-not-real", "mcp.plugs"):
        assert theirs not in flat
    assert set(env["lookups"]) == {(ORG_A, WS_A)}
    props = call0["json"]["tools"][1]["function"]["parameters"]["properties"]
    assert props["base"]["enum"] == ["hermes", "dsh"]                            # never one Auto may not pick
    assert props["connections_needed"]["items"]["enum"] == ["browser", "insforge", "vercel"]
    assert "apps" not in props and "apps_needed" not in props


def test_a_job_is_saved_into_the_workspace_with_its_own_copies_of_the_skill_and_server(env):
    env["chat"].answer = (200, call(sb.TOOL, configure(mcp_servers=[CRM])))
    start(env)
    out = settled(env)
    hid = sb.setup_id(ORG_A, ADA["member"], "b1test0001")
    assert out["setupId"] == hid
    cfg = out["config"]
    assert cfg["name"] == "Support replies" and cfg["instructions"] == INSTR and cfg["exampleTask"] == EXAMPLE
    assert cfg["base"] == "dsh" and cfg["baseName"] == "DeepSeek Harness" and cfg["model"] == "deepseek-v4-pro"
    assert cfg["skills"] == [{"id": "skill:reply-tone", "name": "reply-tone"}]
    assert cfg["mcpServers"] == [{"id": CRM, "name": "crm"}] and cfg["connectionsNeeded"] == [] and cfg["apps"] == []
    [h] = built(env)
    assert h["id"] == hid and h["org"] == ORG_A and h["workspace"] == WS_A and h["member"] == ADA["member"]
    assert h["system_prompt"] == INSTR and h["base"] == "dsh" and h["default_model"] == "deepseek-v4-pro"
    assert JOB not in json.dumps(h)                                              # never the person's sentence
    assert env["offered"] == [(ORG_A, "dsh", "deepseek-v4-pro")]
    [sk] = json.loads(h["skills"])
    assert sk["name"] == "reply-tone" and sk["enabled"] is True and sk["files"][0]["content"] == TONE_MD
    [srv] = json.loads(h["mcp_servers"])
    assert srv["url"] == "https://crm.acme.example/mcp" and srv["id"].startswith("mcp.") and srv["id"] != "mcp.crm00001"
    # its own copy of the token, under its own id; the original's stays as it was
    new_key = srv["auth"][len("vault:"):]
    assert new_key != "harness-mcp-mcp-crm00001" and env["vault"][(gw._org_tenant(ORG_A), new_key)] == "crm-token-not-real"
    assert env["vault"][(gw._org_tenant(ORG_A), "harness-mcp-mcp-crm00001")] == "crm-token-not-real"
    assert out["attached"] == {"skill:reply-tone": "on", CRM: "on"}
    assert env["plugs_attach"] == [] and env["media"] == []


def test_a_plugin_the_workspace_has_not_connected_is_asked_for_and_bound(env):
    env["chat"].answer = (200, call(sb.TOOL, configure(plugins=["media", "github"], connections_needed=["vercel"])))
    start(env)
    out = settled(env)
    assert out["status"] == "saved", out
    assert out["config"]["connectionsNeeded"] == [{"id": "vercel", "name": "Vercel", "kind": "plugin"}]
    hid = out["setupId"]
    # bound now, it works once connected; the media tools by their own route
    assert env["plugs_attach"] == [{"org": ORG_A, "hid": hid, "workspace": WS_A, "plugs": ["github", "vercel"]}]
    assert env["media"] == [(ORG_A, hid, "mcp.media")]
    assert out["attached"] == {"skill:reply-tone": "on", "media": "on", "github": "on"}


def test_every_answer_is_settled_against_what_was_offered(env):
    env["chat"].answer = (200, call(sb.TOOL, configure(
        name="The Support Agent Bot!", base="aider", model="gpt-9", plugins=["vercel", "github", "github"],
        skills=["skill:other-secret", "pdf"], mcp_servers=[mcp_id("https://other.example/mcp")],
        environment="henv_b", connections_needed=["github", "microsoft365"])))
    start(env)
    cfg = settled(env)["config"]
    assert cfg["name"] == "The Support"
    assert cfg["base"] == "hermes" and cfg["model"] == "gpt-5.4"               # Auto's default, on its own default
    assert cfg["plugins"] == [{"id": "github", "name": "GitHub"}]
    assert cfg["skills"] == [{"id": "pdf", "name": "PDF"}] and cfg["mcpServers"] == [] and cfg["environment"] is None
    assert cfg["connectionsNeeded"] == []   # GitHub is connected, Microsoft 365 comes with its own sign-in


def test_a_chosen_harness_and_model_are_kept_and_an_environment_from_the_workspace_is_saved(env):
    env["chat"].answer = (200, call(sb.TOOL, configure(base="dsh", model="gpt-5.4", environment="henv_a")))
    start(env, base="hermes", model="deepseek-v4-pro")
    out = settled(env)
    props = env["chat"].calls[0]["json"]["tools"][1]["function"]["parameters"]["properties"]
    assert "base" not in props and "model" not in props
    assert out["config"]["base"] == "hermes" and out["config"]["model"] == "deepseek-v4-pro"
    assert out["config"]["environment"] == {"id": "henv_a", "name": "Data tools"}
    assert built(env)[0]["environment"] == "henv_a"


def test_a_choice_this_server_does_not_offer_is_refused_before_anything_starts(env):
    assert start(env, base="aider").status_code == 400
    assert start(env, base="hermes", model="gpt-9").status_code == 400
    assert start(env, key="b1test0002", model="jev-9").status_code == 400
    assert env["chat"].calls == [] and env["c"].get("/v1/harnesses/builds/b1test0001", headers=INT).status_code == 404


def test_reading_a_workspace_skill_gives_the_builder_its_instructions(env):
    env["chat"].queue = [(200, call("read_items", {"ids": ["skill:reply-tone", "github", "skill:other-secret"]},
                                    reasoning="Let me look."))]
    start(env)
    assert settled(env)["status"] == "saved"
    second = env["chat"].calls[1]["json"]["messages"]
    assert second[2]["role"] == "assistant" and second[2]["reasoning_content"] == "Let me look."
    items = {x["id"]: x for x in json.loads(second[3]["content"])["items"]}
    assert "no exclamation marks" in items["skill:reply-tone"]["instructions"]
    assert items["github"]["kind"] == "plugin" and items["github"]["tools"]
    assert items["skill:other-secret"] == {"id": "skill:other-secret", "error": "No such item in this workspace."}


def test_instructions_that_only_repeat_the_sentence_are_asked_for_again(env):
    env["chat"].queue = [(200, call(sb.TOOL, configure(instructions=JOB)))]
    start(env)
    out = settled(env)
    assert out["status"] == "saved" and out["config"]["instructions"] == INSTR
    told = env["chat"].calls[1]["json"]["messages"][-1]
    assert told["role"] == "tool" and "repeat the team's sentence" in told["content"]


def test_the_last_call_offers_configure_harness_alone_and_requires_it(env):
    env["chat"].queue = [(200, call("read_items", {"ids": ["github"]}, cid=f"c{n}")) for n in range(3)]
    start(env)
    assert settled(env)["status"] == "saved"
    last = env["chat"].calls[-1]["json"]
    assert len(env["chat"].calls) == sb.STEPS
    assert [t["function"]["name"] for t in last["tools"]] == ["configure_harness"] and last["tool_choice"] == "required"


def test_a_refused_shape_is_asked_once_more_in_the_plainest_one(env, monkeypatch):
    monkeypatch.setattr(sb, "STEPS", 1)
    env["chat"].queue = [(400, {"error": {"message": "tool_choice required is not supported"}})]
    start(env)
    assert settled(env)["status"] == "saved"
    a, b = (c["json"] for c in env["chat"].calls)
    assert a["tool_choice"] == "required" and b["tool_choice"] == "auto"


# ── the builder's model: the best this instance runs, the next when one refuses ──────────────────
def test_a_model_that_refuses_the_call_gives_way_to_the_next(env, monkeypatch):
    other = {**WIRE, "url": "https://api.deepseek.test/v1/chat/completions", "model": "deepseek-v4-pro",
             "canonical": "deepseek-v4-pro", "route": "deepseek"}

    async def two(org):
        return [dict(WIRE), dict(other)]
    monkeypatch.setattr(gw, "_setup_build_wires", two)
    env["chat"].by_url[WIRE["url"]] = (400, {"error": {"message": "Function tools are not supported here"}})
    start(env)
    out = settled(env)
    assert out["status"] == "saved", out
    urls = [c["url"] for c in env["chat"].calls]
    assert urls == [WIRE["url"], WIRE["url"], other["url"]]        # asked plainly once, then the next model
    assert env["chat"].calls[-1]["json"]["model"] == "deepseek-v4-pro"


def test_a_model_whose_answer_comes_back_short_does_not_move_on(env, monkeypatch):
    other = {**WIRE, "url": "https://api.deepseek.test/v1/chat/completions"}

    async def two(org):
        return [dict(WIRE), dict(other)]
    monkeypatch.setattr(gw, "_setup_build_wires", two)
    env["chat"].answer = (200, call(sb.TOOL, configure(example_task="")))
    start(env)
    out = settled(env)
    assert out["status"] == "failed" and out["reason"] == sb.R_UNAVAILABLE
    assert {c["url"] for c in env["chat"].calls} == {WIRE["url"]}


def test_a_model_that_takes_tools_only_with_reasoning_off_is_asked_that_way(env, monkeypatch):
    async def luna(org):
        return [{**WIRE, "model": "openai/gpt-6-sol", "canonical": "gpt-6-sol"}]
    monkeypatch.setattr(gw, "_setup_build_wires", luna)
    start(env)
    assert settled(env)["status"] == "saved"
    assert env["chat"].calls[0]["json"]["reasoning_effort"] == "none"


def test_no_model_this_instance_runs_is_refused_with_the_key_sentence(env, monkeypatch):
    async def none(org):
        return []
    monkeypatch.setattr(gw, "_setup_build_wires", none)
    r = start(env)
    assert r.status_code == 400 and r.json()["detail"] == "Connect a model key first. Your setup is built with one of your models."
    assert env["chat"].calls == [] and env["c"].get("/v1/harnesses/builds/b1test0001", headers=INT).status_code == 404


def test_builder_models_order(monkeypatch):
    known = {"gpt-6.1-sol", "gpt-5.4", "deepseek-v4-pro", "claude-sonnet-4.6", "gpt-6-sol", "kimi-k3"}
    runs = ["gpt-6.1-sol", "gpt-6-sol", "gpt-5.4", "kimi-k3", "deepseek-v4-pro"]
    assert sb.builder_models("gpt-6.1-sol", runs, known) == ["gpt-6.1-sol", "gpt-5.4", "deepseek-v4-pro", "gpt-6-sol", "kimi-k3"]
    # the harness's default first, whatever it is; a model it does not run now is never offered
    assert sb.builder_models("kimi-k3", ["kimi-k3", "deepseek-v4-pro"], known) == ["kimi-k3", "deepseek-v4-pro"]
    assert sb.builder_models("gpt-6.1-sol", [], known) == []
    monkeypatch.setattr(sb, "MODELS_SET", ("deepseek-v4-pro", "nope", "gpt-5.4"))
    assert sb.builder_models("gpt-6.1-sol", runs, known) == ["deepseek-v4-pro", "gpt-5.4"]


def test_each_model_is_reached_the_way_a_hermes_turn_reaches_it(monkeypatch):
    integrations = [
        {"name": "openai", "provider": "openai", "config": {"api_key": "sk-openai-not-real"}},
        {"name": "azure", "provider": "azure-foundry", "config": {"api_key": "az-not-real", "base_url": "https://res.openai.azure.com/"}},
        {"name": "anthropic", "provider": "anthropic", "config": {"api_key": "ak-not-real"}},
        {"name": "custom", "provider": "custom", "config": {"api_key": "c-not-real", "base_url": "https://llm.example/v3",
                                                           "api_format": "openai"}},
    ]
    mm = {"gpt-5.4": "openai", "gpt-6-sol": "azure", "claude-sonnet-4.6": "anthropic"}

    async def doc():
        return integrations

    async def model_map():
        return mm

    async def chain(org, backend, explicit):
        return []
    monkeypatch.setattr(gw, "_integrations_doc", doc)
    monkeypatch.setattr(gw, "_effective_model_map", model_map)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    w = asyncio.run(gw._setup_build_model_wire(ORG_A, "gpt-5.4"))
    assert w["url"] == "https://api.openai.com/v1/chat/completions" and w["headers"] == {"authorization": "Bearer sk-openai-not-real"}
    assert w["model"] == gw._integration_models(integrations[0]).get("gpt-5.4") and w["canonical"] == "gpt-5.4"
    w = asyncio.run(gw._setup_build_model_wire(ORG_A, "gpt-6-sol"))
    assert w["url"] == "https://res.openai.azure.com/openai/v1/chat/completions" and w["headers"] == {"api-key": "az-not-real"}
    # Anthropic's own API is not chat completions: the builder skips it, as the hosted builder does
    assert asyncio.run(gw._setup_build_model_wire(ORG_A, "claude-sonnet-4.6")) is None
    assert gw._setup_build_wire("custom", integrations[3]["config"], "m1", "m1")["url"] == "https://llm.example/v3/chat/completions"
    assert gw._setup_build_wire("custom", {**integrations[3]["config"], "full_url": "1"}, "m1", "m1")["url"] == "https://llm.example/v3"
    assert gw._setup_build_wire("custom", {**integrations[3]["config"], "api_format": "anthropic"}, "m1", "m1") is None
    assert gw._setup_build_wire("openai", {}, "gpt-5.4", "gpt-5.4") is None                  # no key, no wire
    assert gw._setup_build_wire("azure-foundry", {"api_key": "k", "auth": "entra", "base_url": "https://r.openai.azure.com"},
                                "m", "m") is None                                            # federated sign in


def test_a_chain_connection_serves_the_builder_when_no_integration_does(monkeypatch):
    async def doc():
        return []

    async def model_map():
        return {}

    async def chain(org, backend, explicit):
        assert backend == "hermes"
        return ["mine"]

    async def get_conn(org, name):
        return {"provider": "openai", "api_key": "sk-chain-not-real"}, "t"
    monkeypatch.setattr(gw, "_integrations_doc", doc)
    monkeypatch.setattr(gw, "_effective_model_map", model_map)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    monkeypatch.setattr(gw, "_get_connection", get_conn)
    w = asyncio.run(gw._setup_build_model_wire(ORG_A, "gpt-5.4"))
    assert w["url"] == "https://api.openai.com/v1/chat/completions" and w["headers"]["authorization"] == "Bearer sk-chain-not-real"


# ── one key, one build; each person their own; a read that waits for the next change ─────────────
def test_the_same_key_never_makes_two_setups(env):
    first = start(env).json()
    again = start(env).json()
    assert again["key"] == first["key"] and again["startedAt"] == first["startedAt"]
    out = settled(env)
    assert start(env, job="Something else entirely, said again with the same key.").json() == out
    assert len(built(env)) == 1 and len(env["chat"].calls) == 1


def test_a_page_load_reads_the_build_by_its_key(env):
    env["chat"].delay = 0.2
    start(env)
    mid = env["c"].get("/v1/harnesses/builds/b1test0001", headers=INT).json()
    assert mid["status"] == "building" and mid["step"] in ("reading", "writing")
    assert settled(env)["status"] == "saved"


def test_a_read_after_a_step_waits_for_the_next_change(env, monkeypatch):
    env["chat"].delay = 0.3
    start(env)
    seen, marks = "", []
    t0 = time.monotonic()
    for _ in range(10):
        r = env["c"].get("/v1/harnesses/builds/b1test0001", params={"after": seen}, headers=INT).json()
        seen = sb.mark(r)
        marks.append(seen)
        if r["status"] != "building":
            break
    assert marks[-1] == "saved." and "building.writing" in marks
    assert len(marks) == len(set(marks))              # each answer is a change, never the same step again
    assert time.monotonic() - t0 < 5
    # a build that does not change: the read answers as it is once the wait is over
    monkeypatch.setattr(sb, "WAIT_S", 0.2)
    t1 = time.monotonic()
    r = env["c"].get("/v1/harnesses/builds/b1test0001", params={"after": "saved."}, headers=INT).json()
    assert r["status"] == "saved" and 0.15 < time.monotonic() - t1 < 3


def test_another_organization_reads_and_builds_only_its_own(env):
    start(env)
    settled(env)
    env["who"]["p"] = dict(BOB)
    assert env["c"].get("/v1/harnesses/builds/b1test0001", headers=INT).status_code == 404     # Ada's build is not Bob's
    env["chat"].answer = (200, call(sb.TOOL, configure(skills=["skill:other-secret"])))
    start(env)                                                                      # the same key, his own build
    out = settled(env)
    assert out["setupId"] == sb.setup_id(ORG_B, BOB["member"], "b1test0001") != sb.setup_id(ORG_A, ADA["member"], "b1test0001")
    ws = first_message(env["chat"].calls[-1])["workspace"]
    assert [x["id"] for x in ws["plugins"]] == ["media", "vercel"]
    flat = json.dumps(env["chat"].calls[-1]["json"])
    for ada_s in ("reply-tone", "crm.acme.example", "henv_a", "Support desk"):
        assert ada_s not in flat
    assert "github" in [x["id"] for x in ws["not_connected"]]       # connected in Ada's workspace, not in his
    mine = [h for h in built(env) if h["org"] == ORG_B]
    assert len(mine) == 1 and mine[0]["workspace"] == WS_B
    assert out["config"]["skills"] == [{"id": "skill:other-secret", "name": "other-secret"}]


def test_a_workspace_named_in_the_body_must_be_the_pages_own(env):
    assert start(env, workspace="ws_elsewhere").status_code == 409
    assert start(env, workspace=WS_A).status_code == 200                # the same as the header
    assert start(env, key="b1test0003", workspace="").status_code == 200   # empty: the header's


def test_a_key_an_api_key_and_an_empty_or_long_job_are_refused(env):
    assert start(env, key="short").status_code == 400
    assert start(env, key="has spaces in it").status_code == 400
    assert start(env, job="   ").status_code == 400
    assert start(env, job="x" * (sb.JOB_MAX + 1)).status_code == 413
    env["who"]["p"] = {**ADA, "via": "api_key"}
    assert start(env, key="b1test0004").status_code == 403
    env["who"]["p"] = {**ADA, "member": ""}
    assert start(env, key="b1test0005").status_code == 401
    assert env["chat"].calls == []


# ── bounded and honest ───────────────────────────────────────────────────────────────────────────
def test_the_hourly_budget_then_failed_without_asking(env, monkeypatch):
    monkeypatch.setattr(sb, "BUILDS_PER_HOUR", 2)
    for n in range(2):
        start(env, key=f"b1budget00{n}")
        assert settled(env, f"b1budget00{n}")["status"] == "saved"
    calls = len(env["chat"].calls)
    r = start(env, key="b1budget002").json()
    assert r["status"] == "failed" and r["reason"] == sb.R_BUDGET
    assert len(env["chat"].calls) == calls and len(built(env)) == 2


@pytest.mark.parametrize("trouble", ["busy", "refused", "transport", "no_call", "not_json", "short"])
def test_a_builder_that_cannot_answer_saves_nothing(env, trouble):
    chat = env["chat"]
    if trouble == "busy":
        chat.answer = (503, {"error": {}})
    elif trouble == "refused":
        chat.answer = (401, {"error": {}})
    elif trouble == "transport":
        chat.answer = (200, httpx.ConnectError("down"))
    elif trouble == "no_call":
        chat.answer = (200, {"choices": [{"message": {"role": "assistant", "content": "Here is a plan."}}]})
    elif trouble == "not_json":
        chat.answer = (200, call(sb.TOOL, "{not json"))
    else:
        chat.answer = (200, call(sb.TOOL, configure(example_task="")))
    start(env)
    out = settled(env)
    assert out["status"] == "failed" and out["reason"] == sb.R_UNAVAILABLE and "setupId" not in out
    assert built(env) == [] and env["plugs_attach"] == []
    assert len(chat.calls) <= sb.STEPS + 1


def test_a_builder_past_its_bound_saves_nothing_and_says_it_took_too_long(env, monkeypatch):
    monkeypatch.setattr(sb, "TIMEOUT_S", 0.2)
    env["chat"].delay = 1.0
    start(env)
    out = settled(env)
    assert out["status"] == "failed" and out["reason"] == sb.R_TIMEOUT and built(env) == []


def test_a_setup_that_could_not_be_made_is_a_failed_build(env, monkeypatch):
    async def refuse(org, base, model, previous=""):
        raise gw.uhp_error(400, "model_not_offered", "No.", "model")
    monkeypatch.setattr(gw, "_require_offered_model", refuse)
    start(env)
    out = settled(env)
    assert out["status"] == "failed" and out["reason"] == sb.R_SAVE and built(env) == []


def test_an_attach_that_fails_leaves_the_setup_saved_with_that_part_off(env, monkeypatch):
    async def down(org, hid, v, plugs, tools):
        raise gw.uhp_error(503, "plugs_unavailable", "Not now.", "plugs")
    monkeypatch.setattr(gw, "_plugs_attach", down)
    env["chat"].answer = (200, call(sb.TOOL, configure(plugins=["github"])))
    start(env)
    out = settled(env)
    assert out["status"] == "saved" and len(built(env)) == 1
    assert out["attached"] == {"skill:reply-tone": "on", "github": "off"}


def test_a_server_whose_token_cannot_be_read_is_left_off_and_the_setup_saved(env):
    env["vault"].clear()
    env["chat"].answer = (200, call(sb.TOOL, configure(mcp_servers=[CRM])))
    start(env)
    out = settled(env)
    assert out["status"] == "saved" and out["attached"][CRM] == "off"
    assert json.loads(built(env)[0].get("mcp_servers") or "[]") == []


def test_a_build_that_stopped_reads_failed_or_saved_by_whether_its_setup_exists(env):
    member = ADA["member"]
    old = int(time.time() * 1000) - int(sb.STALE_S * 1000) - 5000
    sb.RECORDS.set(sb.record_key(ORG_A, member, "b1stale001"), {"v": 1, "key": "b1stale001", "status": "building",
                                                              "step": "writing", "startedAt": old})
    out = env["c"].get("/v1/harnesses/builds/b1stale001", headers=INT).json()
    assert out["status"] == "failed" and out["reason"] == sb.R_STOPPED
    hid = sb.setup_id(ORG_A, member, "b1stale002")
    env["store"][hid] = {"id": hid, "org": ORG_A, "workspace": WS_A, "deleted": "0", "_label": "Harness"}
    sb.RECORDS.set(sb.record_key(ORG_A, member, "b1stale002"), {"v": 1, "key": "b1stale002", "status": "building",
                                                              "step": "saving", "startedAt": old,
                                                              "config": {"name": "Support replies"}})
    out = env["c"].get("/v1/harnesses/builds/b1stale002", headers=INT).json()
    assert out["status"] == "saved" and out["setupId"] == hid


def test_nothing_of_the_job_or_the_answer_is_logged(env, capsys):
    start(env)
    settled(env)
    text = capsys.readouterr().out
    line = next(x for x in text.splitlines() if x.startswith("[setup-build]") and "status=saved" in x)
    assert f"chars={len(JOB)}" in line and "lang=en" in line and "calls=1" in line and "skills=1" in line
    assert "route=openrouter builder=gpt-5.4" in line
    for words in ("support emails", "order 4821", "Support replies", "b1test0001", KEY):
        assert words not in text


def test_a_chinese_job_is_built_in_chinese(env):
    job = "帮我做一个智能体：读取客户的支持邮件，在 CRM 里查订单，然后用我们的语气起草回复。"
    zh = ("你为一家网店起草客服邮件回复。每个请求是一封客户邮件，原样粘贴。先用 CRM 服务按订单号或客户邮箱找到相关订单，读取它的状态，"
          "然后按店铺的语气写一封简短的回复：亲切、平实、具体。措辞遵循 reply-tone 技能。只返回草稿，并附上主题行。"
          "如果邮件没写订单号，CRM 里也查不到发件人的订单，就请对方提供订单号。不要承诺订单上没有的退款或日期。")
    env["chat"].answer = (200, call(sb.TOOL, configure(name="客服回复", instructions=zh, example_task="你好，我的订单 4821 一周了还在处理中，什么时候发货？")))
    start(env, job=job)
    out = settled(env)
    assert out["status"] == "saved" and out["config"]["name"] == "客服回复"
    assert "Write the name, the instructions and the example in Simplified Chinese." in env["chat"].calls[0]["json"]["messages"][0]["content"]


def test_settle_and_uniq_name_alone():
    inv = {"bases": BASES, "default_base": "hermes", "skills": {}, "plugins": {}, "apps": {}, "mcp": {}, "environments": {},
           "connect": {"vercel": {"name": "Vercel"}}, "unread": ["plugins"]}
    cfg = sb.settle(configure(skills=[], connections_needed=["vercel"]), inv, "auto", "auto", {}, JOB)
    assert cfg["connectionsNeeded"] == []          # the plugins could not be read: nothing is asked to be connected
    with pytest.raises(sb.BadAnswer):
        sb.settle(configure(instructions=JOB + " Thanks."), inv, "auto", "auto", {}, JOB)
    assert sb.uniq_name("Support replies", ["support  Replies", "Support replies 2"]) == "Support replies 3"


def test_the_wires_follow_the_order_and_skip_a_model_with_no_connection(monkeypatch):
    integ = {"name": "openai", "provider": "openai", "config": {"api_key": "sk-openai-not-real"}}

    async def servable(org, backend):
        return {"gpt-6.1-sol", "gpt-5.4", "deepseek-v4-pro"}

    async def doc():
        return [integ]

    async def model_map():
        return {"gpt-6.1-sol": "openai", "gpt-5.4": "openai"}

    async def chain(org, backend, explicit):
        return []
    monkeypatch.setattr(gw, "_servable_models", servable)
    monkeypatch.setattr(gw, "_integrations_doc", doc)
    monkeypatch.setattr(gw, "_effective_model_map", model_map)
    monkeypatch.setattr(gw, "_resolve_chain", chain)
    wires = asyncio.run(gw._setup_build_wires(ORG_A))
    assert gw._MODEL_CATALOG["hermes"]["default"] == "gpt-6.1-sol"
    assert [w["canonical"] for w in wires] == ["gpt-6.1-sol", "gpt-5.4"]       # deepseek-v4-pro runs, but has no connection here
    assert all(w["url"] == "https://api.openai.com/v1/chat/completions" for w in wires)
