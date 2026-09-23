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


def test_harness_env_resolves_header_vault_and_literal_and_names_the_secrets(monkeypatch):
    async def _vault(org, auth):
        assert org == "org.a" and auth == "vault:harness-mcp-deploy-key"
        return "from-the-vault"
    monkeypatch.setattr(gw, "_resolve_mcp_auth", _vault)
    hv = {"env": json.dumps({"TOKEN": "$headers.X-App-Token", "DEPLOY": "vault:harness-mcp-deploy-key",
                             "REGION": "us-east-1", "MISSING": "$headers.X-Absent"})}
    out, secret = asyncio.run(gw._harness_env(hv, "org.a", {"x-app-token": SECRET}))
    assert out == {"TOKEN": SECRET, "DEPLOY": "from-the-vault", "REGION": "us-east-1"}   # the absent header is left unset
    assert secret == ["TOKEN", "DEPLOY"]                                                  # the literal is not a secret


def test_a_vault_reference_reads_only_the_orgs_own_mcp_secrets(monkeypatch):
    """The platform pool is never consulted, and only the MCP-secrets namespace resolves: a
    customer's reference is resolved into that customer's sandbox."""
    asked = []

    async def _vault_get(tenant, key):
        asked.append((tenant, key))
        return f"<{tenant}>:{key}"
    monkeypatch.setattr(gw, "_vault_get", _vault_get)
    mine = gw._org_tenant("org.attacker.example")
    assert asyncio.run(gw._resolve_mcp_auth("org.attacker.example", "vault:harness-mcp-github")) == f"<{mine}>:harness-mcp-github"
    for ref in ("vault:harness-conn-OpenRouter", "vault:harness-integrations", "vault:harness-media-access",
                "vault:harness-policy-x", "vault:" + gw._HOSTED_SECRET_PREFIX + "x", "vault:anything"):
        assert asyncio.run(gw._resolve_mcp_auth("org.attacker.example", ref)) == "", ref
    assert all(t == mine for t, _ in asked) and gw.GLOBAL_TENANT not in {t for t, _ in asked}
    assert asyncio.run(gw._resolve_mcp_auth("", "vault:harness-mcp-github")) == ""      # no org, nothing resolves
    assert asyncio.run(gw._resolve_mcp_auth("org.a", "literal-bearer")) == "literal-bearer"


def test_an_mcp_secret_is_stored_in_the_orgs_own_tenant(monkeypatch):
    put = []

    async def _vault_put(tenant, key, value):
        put.append((tenant, key, value))
    monkeypatch.setattr(gw, "_vault_put", _vault_put)
    out = asyncio.run(gw._mcp_secret_store("org.songrenchu.example.com", "GitHub token", "ghp_x"))
    assert put == [(gw._org_tenant("org.songrenchu.example.com"), "harness-mcp-github-token", "ghp_x")]
    assert out["ref"] == "vault:harness-mcp-github-token" and out["tenant"] != gw.GLOBAL_TENANT
    with pytest.raises(gw.HTTPException):
        asyncio.run(gw._mcp_secret_store("", "x", "y"))


def test_env_clean_refuses_the_loader_the_import_paths_the_trust_roots_and_the_proxies():
    for name in ("LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "PYTHONPATH", "NODE_OPTIONS", "SSL_CERT_FILE", "HTTPS_PROXY", "no_proxy"):
        with pytest.raises(gw.HTTPException):
            gw._env_clean({name: "x"})


def test_the_runner_is_told_which_values_are_secret():
    """The turn body names the secret variables; the runner redacts them where the gateway reads
    the turn, so the gateway has no scrub of its own (one mechanism, every sink)."""
    src = open(Path(gw.__file__)).read()
    assert '"env_secret": turn_secret,' in src
    assert "_scrub_secrets" not in src


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
    # console-owned routes under a public prefix stay out (#245, reported by trifonnt): the cloud
    # upload handlers and the kits' server state, vendor and media handlers
    assert not [p for p in paths if p.startswith(("/v1/harnesses/upload", "/v1/harnesses/{hid}/upload", "/v1/harnesses/{hid}/servers"))], sorted(paths)
    for p in ("/v1/harnesses/{harness_id}/events", "/v1/harnesses/{hid}/plugin", "/v1/harnesses/{hid}/plugins/{name}/files"):
        assert p in paths, p
    assert "env" in doc["components"]["schemas"]["HarnessBody"]["properties"]
    assert asyncio.run(gw.openapi_public()) is doc                       # built once per process
    html = asyncio.run(gw.openapi_docs())
    assert html.status_code == 200 and b"/v1/openapi.json" in html.body
