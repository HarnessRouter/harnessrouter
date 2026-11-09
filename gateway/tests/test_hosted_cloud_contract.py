"""This instance against HarnessRouter Cloud as Cloud really behaves, at the HTTP boundary.

Paired instances asked Cloud's GET /v1/models for hours and were answered 401 every time, and then
paired again, often more than once (hosted logs, 2026-11-06 to 11-08). Three things on this side:

- The list was asked for WITHOUT a key whenever no HarnessRouter API connection held one: an
  instance that never connected, and one that connected only for Deploy to Cloud (that key is the
  deploy destination's, never a connection). Cloud lists models for a key's organization only, so
  that call is a 401 every time, and a failure was not remembered: every console page with a model
  picker asked again (1010 calls from one address in four days).
- With several HarnessRouter API connections, the FIRST was always the one asked. A refused key
  ahead of a good one kept the list empty, the console offered Get a key, the new key went in as a
  second connection behind the refused one, and nothing changed.
- Nothing said the key had been refused; the only way forward the console showed was another pairing.

The fake below enforces Cloud's own rules, read from the hosted gateway (backend/harness_gateway/app.py
at c009a5d0e): `_principal_resolve_caller` takes `Authorization: Bearer <API key>` and nothing else,
and answers 401 "missing or invalid API key" without one, on /v1/models as on every public route;
POST /v1/harnesses validates its body against `HarnessBody`, which refuses a field it does not have
by name (422 unknown_field) and lets the read-only fields a harness comes back with through, and
then refuses a base it does not offer (422 unsupported_base) and a default model the base does not
run (422 model_not_available). A change on this side that breaks any of those fails here."""
import asyncio
import difflib
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import AliasChoices, BaseModel, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

ORG = "local"
HOSTED = "https://api.harnessrouter.ai"
GOOD, OTHER, DEAD = "sk-hr-" + "a" * 40, "sk-hr-" + "b" * 40, "sk-hr-" + "d" * 40


# ── Cloud's harness body, as the hosted gateway declares it (HarnessBody, c009a5d0e) ──────────────
def _either(name: str, camel: str):
    return Field(default=None, validation_alias=AliasChoices(name, camel))


_READ_ONLY = frozenset({"id", "object", "notLoaded", "member", "workspace", "createdAt", "kit", "library",
                        "liveAt", "liveSite", "fromListing", "needs", "workspaceSite", "connectedAt"})


class CloudHarnessBody(BaseModel):
    name: str
    base: str
    base_label: str | None = _either("base_label", "baseLabel")
    default_model: str | None = _either("default_model", "defaultModel")
    system_prompt: str | None = _either("system_prompt", "systemPrompt")
    mcp_servers: list | None = _either("mcp_servers", "mcpServers")
    skills: list | None = None
    plugins: list | None = None
    disabled_tools: list | None = _either("disabled_tools", "disabledTools")
    max_step: int | None = _either("max_step", "maxStep")
    timeout_seconds: int | None = _either("timeout_seconds", "timeoutSeconds")
    max_cost_usd: float | None = _either("max_cost_usd", "maxCostUsd")
    reasoning_effort: str | None = _either("reasoning_effort", "reasoningEffort")
    engine_member: dict | None = _either("engine_member", "engineMember")
    additional_headers: list | None = _either("additional_headers", "additionalHeaders")
    env: dict | None = None
    source: str | None = None
    source_instance: str | None = _either("source_instance", "sourceInstance")
    environment: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _known_fields_only(cls, data):
        if not isinstance(data, dict):
            return data
        known: set[str] = set()
        for n, f in cls.model_fields.items():
            known.add(n)
            if isinstance(f.validation_alias, AliasChoices):
                known.update(c for c in f.validation_alias.choices if isinstance(c, str))
        unknown = [k for k in data if k not in known and k not in _READ_ONLY]
        if unknown:
            near = difflib.get_close_matches(str(unknown[0]), sorted(known), n=1, cutoff=0.6)
            raise PydanticCustomError("unknown_field", "unknown harness field '{field}'{hint}",
                                      {"field": unknown[0], "hint": f" (did you mean '{near[0]}'?)" if near else ""})
        return {k: v for k, v in data.items() if k not in _READ_ONLY}


def _uhp(status: int, code: str, message: str, param: str | None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"type": "invalid_request_error", "code": code, "message": message,
                                                  "param": param}, "detail": message})


class Cloud:
    """HarnessRouter Cloud, as far as this instance can see it."""
    # what the workspace is offered: hosted's /v1/models shape ({backends: {backend: {default, models}}});
    # goose without gpt-6.1-sol, as hosted offers it (open source's goose default is gpt-6.1-sol)
    OFFER = {"claude": {"default": "claude-sonnet-5.5", "models": ["claude-sonnet-5.5", "claude-haiku-5.5"]},
             "hermes": {"default": "gpt-6.1-sol", "models": ["gpt-6.1-sol", "gpt-5.4"]},
             "goose": {"default": "gpt-5.4", "models": ["gpt-5.4"]}}
    BASES = {"claude-code": "claude", "hermes": "hermes", "goose": "goose"}

    def __init__(self):
        self.keys = {GOOD: {"org": "org_e", "org_name": "Example Co", "workspace": "ws_r", "workspace_name": "Research", "member": "owner"},
                     OTHER: {"org": "org_f", "org_name": "Other Co", "workspace": "ws_o", "workspace_name": "Ops", "member": "owner"}}
        self.harnesses: dict[str, dict] = {}
        self.calls: list[tuple[str, str, bool]] = []      # (method, path, carried a bearer)
        self.pairings: dict[str, dict] = {}

    def _caller(self, req: httpx.Request) -> dict | None:
        # _principal_resolve_caller: "Bearer " (any case), then the key must be a live API key
        auth = req.headers.get("authorization", "")
        return self.keys.get(auth[7:].strip()) if auth[:7].lower() == "bearer " else None

    def handle(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        self.calls.append((req.method, p, req.headers.get("authorization", "")[:7].lower() == "bearer "))
        if p == "/v1/connect" and req.method == "POST":          # a pairing needs no account
            code = f"code{len(self.pairings) + 1}"
            self.pairings[code] = {"secret": f"s-{code}", "key": ""}
            return httpx.Response(200, json={"code": code, "secret": f"s-{code}", "expires_in": 1800,
                                             "url": f"https://app.harnessrouter.ai/get-key?code={code}"})
        if p.startswith("/v1/connect/") and req.method == "GET":
            pr = self.pairings.get(p.rsplit("/", 1)[-1])
            if not pr or pr.get("delivered"):
                return httpx.Response(410, json={"detail": "this connection code has expired or was already used"})
            if req.headers.get("x-connect-secret") != pr["secret"]:
                return httpx.Response(403, json={"detail": "wrong connection secret"})
            if not pr["key"]:
                return httpx.Response(202, json={"status": "pending"})
            pr["delivered"] = True
            return httpx.Response(200, json={"status": "ready", "api_key": pr["key"], "name": "HarnessRouter API",
                                             "endpoint": f"{HOSTED}/v1/provider", "models_url": f"{HOSTED}/v1/models",
                                             "balance_url": f"{HOSTED}/v1/balance"})
        if p == "/v1/uhp":
            return httpx.Response(200, json={"capabilities": {"plugins": True, "harness_idempotency": True}})
        if p == "/v1/harnesses" and req.method == "POST":
            # FastAPI validates the body before the route runs, so a body it refuses is 422 whoever sends it
            try:
                body = CloudHarnessBody.model_validate(json.loads(req.content))
            except ValidationError as e:
                first = e.errors()[0]
                param = ".".join(str(x) for x in first.get("loc") or []) or None
                return _uhp(422, "invalid_request", f"{param}: {first['msg']}" if param else first["msg"], param)
            me = self._caller(req)
            if not me:
                return httpx.Response(401, json={"detail": "missing or invalid API key"})
            backend = self.BASES.get(body.base.strip().lower())
            if not backend:
                return _uhp(422, "unsupported_base", f"This server cannot run the harness base '{body.base}'.", "base")
            offered = self.OFFER[backend]["models"]
            if body.default_model and body.default_model not in offered:
                return _uhp(422, "model_not_available", f"Model '{body.default_model}' is not offered on the {body.base} base. "
                                                        f"Use one of: {', '.join(offered)} (GET /v1/models lists every base's models).",
                            "default_model")
            hid = f"chrn_{len(self.harnesses) + 1:032x}"
            self.harnesses[hid] = {**body.model_dump(), "org": me["org"], "workspace": me["workspace"]}
            return httpx.Response(200, json={"id": hid, "name": body.name, "base": body.base})
        me = self._caller(req)
        if not me:
            return httpx.Response(401, json={"detail": "missing or invalid API key"})
        if p == "/v1/models":
            return httpx.Response(200, json={"backends": {b: {"default": c["default"], "models": [
                {"id": m, "available": True, "default": m == c["default"]} for m in c["models"]]} for b, c in self.OFFER.items()}})
        if p == "/v1/balance":
            return httpx.Response(200, json={"org": me["org"], "balance_usd": 12.5, "is_deficit": False, "as_of": "2026-11-08T10:00:00Z"})
        if p == "/v1/me":
            return httpx.Response(200, json=me)
        return httpx.Response(404, json={"detail": "no route"})

    def models_calls(self) -> list[bool]:
        return [bearer for m, path, bearer in self.calls if path == "/v1/models"]


@pytest.fixture()
def cloud(monkeypatch):
    c = Cloud()
    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(lambda r: c.handle(r))
            super().__init__(*a, **kw)
    monkeypatch.setattr(gw.httpx, "AsyncClient", Patched)
    monkeypatch.setattr(gw, "_checked_clients", {})
    monkeypatch.setattr(gw, "_CONNECTS", {})
    # this process's memory of Cloud, fresh per test
    monkeypatch.setattr(gw, "_HOSTED_MODELS", {"ids": [], "at": 0.0})
    monkeypatch.setattr(gw, "_HOSTED_MODELS_FAILS", {}, raising=False)    # raising=False: so the code before it fails by behaviour
    monkeypatch.setitem(gw._VENDOR_MODELS, "harnessrouter", {})
    return c


@pytest.fixture()
def api(monkeypatch):
    async def principal(request):
        return {"org": ORG, "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", principal)
    for k in (gw._INTEGRATIONS_KEY, gw._CLOUD_UPLOAD_KEY, gw._CLOUD_UPLOAD_RECORDS_KEY):
        asyncio.run(gw.BACKING.secrets.put(gw.GLOBAL_TENANT, k, "", require_encryption=True))
    return TestClient(gw.app)


def _connections(*rows: tuple[str, str]):
    """HarnessRouter API connections, in this order: (name, key)."""
    doc = [{"name": n, "provider": "harnessrouter", "models": [],
            "config": {"api_key": k, "base_url": f"{HOSTED}/v1/provider", "models_url": f"{HOSTED}/v1/models",
                       "balance_url": f"{HOSTED}/v1/balance"}} for n, k in rows]
    asyncio.run(gw.BACKING.secrets.put(gw.GLOBAL_TENANT, gw._INTEGRATIONS_KEY, json.dumps(doc), require_encryption=True))


def _rows(api) -> dict[str, dict]:
    r = api.get("/v1/admin/integrations")
    assert r.status_code == 200, r.text
    return {i["name"]: i for i in r.json()["integrations"]}


# ── the model list ────────────────────────────────────────────────────────────────────────────────
def test_with_no_key_cloud_is_never_asked_for_its_model_list(api, cloud):
    """An instance that never connected: every console page with a model picker read the connections,
    and every read asked Cloud for its list without a key, which Cloud answers 401."""
    for _ in range(5):
        assert _rows(api) == {}
    assert cloud.models_calls() == []


def test_a_pairing_for_deploy_to_cloud_alone_never_asks_for_the_model_list_without_a_key(api, cloud):
    """The instance in the hosted logs: it connected for Deploy to Cloud, used that key on /v1/me, /v1/uhp
    and POST /v1/harnesses at once, and its /v1/models calls stayed 401 before and after. That key is the
    deploy destination's and never a connection, so the list was asked for with none."""
    code = api.post("/v1/cloud-upload/connect", json={"instance": "my-box:3000"}).json()["code"]
    cloud.pairings[code]["key"] = GOOD
    assert api.get(f"/v1/cloud-upload/connect/{code}").json()["status"] == "ready"
    r = api.post("/v1/harnesses", json={"name": "Support agent", "base": "claude-code", "default_model": "claude-sonnet-5.5",
                                        "system_prompt": "Answer support questions."})
    up = api.post(f"/v1/harnesses/{r.json()['id']}/upload")
    assert up.status_code == 200, up.text
    for _ in range(3):
        _rows(api)
    assert cloud.models_calls() == []
    assert all(bearer for m, p, bearer in cloud.calls if p in ("/v1/me", "/v1/harnesses", "/v1/models", "/v1/balance"))


def test_the_connection_whose_key_cloud_takes_is_the_one_asked_and_the_refused_one_says_so(api, cloud):
    """A refused key first in the document and a good one after it (a person who connected again):
    the first one was always the one asked, so the list stayed empty however often they reconnected."""
    _connections(("HarnessRouter API", DEAD), ("HarnessRouter API 2", GOOD))
    rows = _rows(api)
    assert rows["HarnessRouter API"]["key_state"] == "refused"
    assert "key_state" not in rows["HarnessRouter API 2"]
    assert rows["HarnessRouter API 2"]["balance"]["usd"] == 12.5 and "balance" not in rows["HarnessRouter API"]
    assert {m["canonical"] for m in rows["HarnessRouter API 2"]["models"]} >= {"claude-sonnet-5.5", "gpt-6.1-sol"}
    assert cloud.models_calls() == [True, True]            # the refused key once, then the good one; never keyless
    # the refused key is asked after the good one from now on, and only when its wait is over
    _rows(api)
    assert len(cloud.models_calls()) == 2


def test_a_refused_read_is_not_asked_again_for_ten_minutes_and_is_logged_once(api, cloud, capsys):
    _connections(("HarnessRouter API", DEAD))
    for _ in range(6):
        assert _rows(api)["HarnessRouter API"]["key_state"] == "refused"
    assert cloud.models_calls() == [True]                  # one ask, not six
    assert [c for c in cloud.calls if c[1] == "/v1/balance"] == []     # nor the balance, with a key Cloud refused
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("[hosted]")]
    assert len(lines) == 1 and "HTTP 401" in lines[0] and "Cloud refused the key" in lines[0]
    assert DEAD not in lines[0] and DEAD[-8:] not in lines[0]       # the key is named by a digest, never itself
    # its wait over, it is asked once more; failing the same way, nothing more is logged
    fp = gw._hosted_key_fp(DEAD)
    gw._HOSTED_MODELS_FAILS[fp]["at"] -= gw._HOSTED_MODELS_RETRY_S + 1
    _rows(api)
    _rows(api)
    assert cloud.models_calls() == [True, True]
    assert not [x for x in capsys.readouterr().out.splitlines() if x.startswith("[hosted]")]


def test_a_failure_that_is_not_a_refusal_waits_too_and_says_nothing_to_the_console(api, cloud, capsys):
    _connections(("HarnessRouter API", GOOD))
    real = cloud.handle

    def busy(req):
        if req.url.path == "/v1/models":
            cloud.calls.append((req.method, req.url.path, True))
            return httpx.Response(503, json={"detail": "busy"})
        return real(req)
    cloud.handle = busy
    for _ in range(4):
        assert "key_state" not in _rows(api)["HarnessRouter API"]       # not refused: nothing to reconnect
    assert cloud.models_calls() == [True]
    assert len([x for x in capsys.readouterr().out.splitlines() if x.startswith("[hosted]")]) == 1


def test_reconnect_puts_the_new_key_in_the_refused_connection_and_the_list_comes_back(api, cloud):
    """Reconnect (Bring your own key) runs the key hand-off and saves the new key into the connection
    Cloud refused, under its name: the refused key is gone, not left in front."""
    _connections(("HarnessRouter API", DEAD))
    assert _rows(api)["HarnessRouter API"]["key_state"] == "refused"
    code = api.post("/v1/admin/connect", json={}).json()["code"]
    cloud.pairings[code]["key"] = GOOD
    handed = api.get(f"/v1/admin/connect/{code}").json()
    assert handed["status"] == "ready" and "claude-sonnet-5.5" in handed["models"]    # read at once with the new key
    doc = api.get("/v1/admin/integrations").json()
    row = dict(doc["integrations"][0], config={**doc["integrations"][0]["config"], "api_key": handed["api_key"]})
    assert api.put("/v1/admin/integrations", json={"integrations": [row]}).status_code == 200
    rows = _rows(api)
    assert list(rows) == ["HarnessRouter API"] and "key_state" not in rows["HarnessRouter API"]
    assert rows["HarnessRouter API"]["balance"]["usd"] == 12.5


# ── Deploy to Cloud ───────────────────────────────────────────────────────────────────────────────
def _destination(api, cloud, key=GOOD):
    code = api.post("/v1/cloud-upload/connect", json={}).json()["code"]
    cloud.pairings[code]["key"] = key
    return api.get(f"/v1/cloud-upload/connect/{code}").json()["target"]


def test_the_fake_refuses_what_cloud_refuses():
    """The fake is only worth its rules: a field Cloud does not have is refused by name, before the key is
    looked at; the read-only fields a harness comes back with are let through."""
    c = Cloud()
    post = lambda body, key=GOOD: c.handle(httpx.Request("POST", f"{HOSTED}/v1/harnesses", json=body,
                                                         headers={"authorization": f"Bearer {key}"}))
    r = post({"name": "a", "base": "hermes", "calibrates": "x"}, key="")
    assert r.status_code == 422 and "unknown harness field 'calibrates'" in r.json()["error"]["message"]
    assert post({"name": "a", "base": "hermes", "kit": None, "id": "chrn_x", "createdAt": 1}).status_code == 200
    assert post({"name": "a", "base": "hermes", "max_step": "lots"}).json()["error"]["param"] == "max_step"
    assert post({"name": "a", "base": "hermes"}, key=DEAD).status_code == 401
    assert c.handle(httpx.Request("GET", f"{HOSTED}/v1/models")).status_code == 401


def test_every_field_a_deploy_sends_is_one_cloud_takes(api, cloud):
    """A setup with something in every field the deploy sends: Cloud's own body rule takes all of it.
    Cloud refuses a field it does not have (422 unknown_field), so a field added to the deploy body
    without Cloud having it first fails here."""
    target = _destination(api, cloud)
    r = api.post("/v1/harnesses", json={
        "name": "Full", "base": "claude-code", "default_model": "claude-sonnet-5.5", "system_prompt": "Do the work.",
        "skills": [{"name": "deck", "files": [{"path": "SKILL.md", "content": "---\nname: deck\ndescription: Decks\n---\nBody"}]}],
        "max_step": 40, "timeout_seconds": 600, "reasoning_effort": "high", "additional_headers": ["X-User"],
        "disabled_tools": ["Bash"]})
    assert r.status_code == 200, r.text
    hid = r.json()["id"]
    up = api.post(f"/v1/harnesses/{hid}/upload", json={"target": target["id"]})
    assert up.status_code == 200, up.text
    sent = cloud.harnesses[up.json()["remote_id"]]
    assert sent["max_step"] == 40 and sent["timeout_seconds"] == 600 and sent["reasoning_effort"] == "high"
    assert sent["skills"][0]["files"][0]["path"] == "SKILL.md" and sent["source"] == "selfhost"


def test_a_model_cloud_does_not_offer_on_the_base_is_named_with_what_it_does(api, cloud):
    """open source's goose default (gpt-6.1-sol) is not one Cloud offers on goose: Cloud answers 422
    model_not_available on default_model, which no retry changes. Said as that, with Cloud's own list."""
    _destination(api, cloud)
    hid = api.post("/v1/harnesses", json={"name": "Goose", "base": "goose", "default_model": "gpt-6.1-sol"}).json()["id"]
    up = api.post(f"/v1/harnesses/{hid}/upload")
    assert up.status_code == 502
    said = up.json()["detail"]
    assert said.startswith("HarnessRouter Cloud did not take the model: Model 'gpt-6.1-sol' is not offered on the goose base")
    assert "gpt-5.4" in said


def test_a_deploy_key_cloud_refuses_marks_its_workspace_and_never_signs_the_person_out(api, cloud):
    """A 401 from this server signs the person out of the console. Cloud refusing the destination's key
    is said as that (400), and the workspace reads as refused so the next deploy asks to sign in again."""
    target = _destination(api, cloud)
    hid = api.post("/v1/harnesses", json={"name": "Support", "base": "claude-code"}).json()["id"]
    cloud.keys.pop(GOOD)                                    # revoked on Cloud
    up = api.post(f"/v1/harnesses/{hid}/upload", json={"target": target["id"]})
    assert up.status_code == 400 and "refused the key" in up.json()["detail"]
    assert api.get("/v1/cloud-upload/targets").json()["targets"][0]["revoked"] is True
    pasted = api.post("/v1/cloud-upload/targets", json={"api_key": DEAD, "base_url": HOSTED})
    assert pasted.status_code == 400 and "refused this key" in pasted.json()["detail"]
    # signed in again: Cloud mints a new key for the same workspace, which replaces the refused destination
    fresh = "sk-hr-" + "f" * 40
    cloud.keys[fresh] = {"org": "org_e", "org_name": "Example Co", "workspace": "ws_r", "workspace_name": "Research", "member": "owner"}
    again = _destination(api, cloud, key=fresh)
    assert again["id"] == target["id"] and again["revoked"] is False
    assert [t["revoked"] for t in api.get("/v1/cloud-upload/targets").json()["targets"]] == [False]
    assert api.post(f"/v1/harnesses/{hid}/upload", json={"target": target["id"]}).status_code == 200
