"""A harness's environment: variables every turn's shell and tools start with.

Resolved on the gateway the way MCP auth already is (a `$headers.X` reference takes the request's
declared header, `vault:ref` the stored secret, anything else the literal), handed to the runner as
values, and scrubbed from everything the turn records. The public OpenAPI document is pinned here
too: it must describe the customer surface and nothing behind the internal key."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

SECRET = "sk-live-0123456789abcdef"


def test_env_clean_keeps_shell_safe_names_and_refuses_the_runtimes_own():
    assert gw._env_clean({"API_KEY": "$headers.X-Api-Key", "n": 1, "gone": None}) == {"API_KEY": "$headers.X-Api-Key", "n": "1"}
    for bad in ("1ABC", "A-B", "", "A B"):
        with pytest.raises(gw.HTTPException) as e:
            gw._env_clean({bad: "x"})
        assert e.value.status_code == 400
    for reserved in ("HR_TOKEN", "OPENAI_API_KEY", "anthropic_api_key", "PATH", "home"):
        with pytest.raises(gw.HTTPException) as e:
            gw._env_clean({reserved: "x"})
        assert e.value.status_code == 400 and "reserved_env_name" in json.dumps(e.value.detail)
    with pytest.raises(gw.HTTPException):
        gw._env_clean({f"V{i}": "x" for i in range(gw._ENV_MAX + 1)})


def test_harness_env_resolves_header_vault_and_literal(monkeypatch):
    async def _vault(org, auth):
        assert org == "org.a" and auth == "vault:deploy-key"
        return "from-the-vault"
    monkeypatch.setattr(gw, "_resolve_mcp_auth", _vault)
    hv = {"env": json.dumps({"TOKEN": "$headers.X-App-Token", "DEPLOY": "vault:deploy-key",
                             "REGION": "us-east-1", "MISSING": "$headers.X-Absent"})}
    out, secrets = asyncio.run(gw._harness_env(hv, "org.a", {"x-app-token": SECRET}))
    assert out == {"TOKEN": SECRET, "DEPLOY": "from-the-vault", "REGION": "us-east-1"}   # the absent header is left unset
    assert secrets == [SECRET, "from-the-vault"]                                          # the literal is not a secret


def test_scrub_replaces_values_wherever_they_appear():
    assert gw._scrub_secrets(f"echo {SECRET}; export T={SECRET}", [SECRET]) == "echo [redacted]; export T=[redacted]"
    assert gw._scrub_secrets("region us-east-1 stays", ["us"]) == "region us-east-1 stays"   # short values are not scrubbed


def test_stored_response_and_live_events_are_scrubbed(monkeypatch):
    sid = "sess_scrub"
    monkeypatch.setitem(gw._session_trace, sid, {"secrets": [SECRET]})
    put: dict = {}

    async def _blob_put(key, data, **kw):
        put[key] = data
    async def _vg_upsert(*a, **kw):
        pass
    monkeypatch.setattr(gw, "_blob_put", _blob_put)
    monkeypatch.setattr(gw, "_vg_upsert", _vg_upsert)
    asyncio.run(gw._resp_put("resp_1", {"output": [{"text": f"the token is {SECRET}"}]}, "org.a", sid, None, "completed", 0.0, True))
    assert SECRET not in put["responses/resp_1.json"].decode() and "[redacted]" in put["responses/resp_1.json"].decode()

    seen = []
    monkeypatch.setattr(gw, "_redis_out", None)
    monkeypatch.setattr(gw, "_bus_deliver", lambda *a: seen.append(a[-1]))
    gw._bus_publish("org.a", "chrn_x", "m", sid, "resp_1", {"type": "response.output_text.delta", "delta": SECRET})
    assert seen == [{"type": "response.output_text.delta", "delta": "[redacted]"}]


def test_harness_body_stores_env_and_reads_it_back():
    body = gw.HarnessBody(name="n", base="codex", env={"TOKEN": "$headers.X-App-Token"})
    props = gw._harness_props(body)
    assert json.loads(props["env"]) == {"TOKEN": "$headers.X-App-Token"}
    assert gw._harness_out(dict(props, id="chrn_" + "a" * 32))["env"] == {"TOKEN": "$headers.X-App-Token"}


def test_openapi_describes_the_customer_surface_only():
    doc = gw._openapi_public()
    paths = set(doc["paths"])
    for p in ("/v1/responses", "/v1/files", "/v1/harnesses", "/v1/harnesses/{hid}", "/v1/sessions/{sid}/turns", "/v1/models"):
        assert p in paths, p
    assert not [p for p in paths if p.startswith(("/v1/admin", "/v1/orgs", "/v1/mcp/", "/v1/kits", "/v1/cloud-upload", "/v1/hr", "/internal", "/share"))]
    assert "env" in doc["components"]["schemas"]["HarnessBody"]["properties"]
    assert asyncio.run(gw.openapi_public()) is doc                       # built once per process
    html = asyncio.run(gw.openapi_docs())
    assert html.status_code == 200 and b"/v1/openapi.json" in html.body
