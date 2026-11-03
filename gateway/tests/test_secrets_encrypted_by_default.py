"""Stored credentials are encrypted at rest on every install (#624).

The file secret store sealed records only under HR_SECRET_KEY, and nothing set it: an install
that followed the README kept its provider keys and MCP tokens in the clear under /data/secrets.
Now the entrypoint gives an install with no key one at its first start; a credential — a provider
connection, the integrations document, an MCP token, a plug's secret — is stored only where it
can be sealed, and refused with 501 secrets_not_configured where it cannot, as a database
connection already was; and what was stored before the key existed is sealed at the gateway's
start, once, in place.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)
import backing  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
INTERNAL = {"x-harness-internal": os.environ["HARNESS_INTERNAL_KEY"]}


def _store(monkeypatch, key: str | None) -> backing.FileSecretStore:
    if key:
        monkeypatch.setenv("HR_SECRET_KEY", key)
    else:
        monkeypatch.delenv("HR_SECRET_KEY", raising=False)
    store = backing.FileSecretStore(tempfile.mkdtemp(prefix="hr-secrets-"))
    monkeypatch.setattr(gw.BACKING, "secrets", store)
    return store


def _raw(store: backing.FileSecretStore, tenant: str, name: str) -> str:
    return store._p(tenant, name).read_text()


# ── the store ─────────────────────────────────────────────────────────────────────────────────

def test_records_written_before_the_key_existed_are_sealed_at_start(monkeypatch):
    plain = _store(monkeypatch, None)
    asyncio.run(plain.put("org-a", "harness-conn-anthropic", json.dumps({"api_key": "sk-plain"})))
    asyncio.run(plain.put("org-a", "harness-policy-claude", '{"chain":["anthropic"]}'))
    assert _raw(plain, "org-a", "harness-conn-anthropic").startswith("{")      # the clear text, as before
    assert asyncio.run(plain.reencrypt_plaintext()) == 0                       # nothing to seal with

    monkeypatch.setenv("HR_SECRET_KEY", "first-boot-key")      # the next start has a key
    keyed = backing.FileSecretStore(str(plain._root))
    assert asyncio.run(keyed.reencrypt_plaintext()) == 2
    assert _raw(keyed, "org-a", "harness-conn-anthropic").startswith("hrenc1:")
    assert asyncio.run(keyed.get("org-a", "harness-conn-anthropic")) == json.dumps({"api_key": "sk-plain"})
    assert asyncio.run(keyed.reencrypt_plaintext()) == 0                       # once: sealed records are left alone
    assert oct(store_mode := (keyed._p("org-a", "harness-conn-anthropic").stat().st_mode & 0o777)) == oct(0o600), store_mode


def test_a_keyed_store_seals_every_write(monkeypatch):
    store = _store(monkeypatch, "k")
    asyncio.run(store.put("global", "harness-integrations", '{"items":[]}'))
    assert _raw(store, "global", "harness-integrations").startswith("hrenc1:")


def test_the_gateway_runs_the_migration_at_start(monkeypatch):
    src = (ROOT / "gateway" / "app.py").read_text()
    i = src.index("async def _start_secrets_at_rest")
    assert '@app.on_event("startup")' in src[i - 60:i] and "reencrypt_plaintext" in src[i:i + 600]


# ── the credential callers ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def api(monkeypatch):
    async def who(request):
        return {"org": "org-a", "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", who)
    return TestClient(gw.app)


def test_a_provider_connection_is_refused_where_it_cannot_be_sealed(api, monkeypatch):
    store = _store(monkeypatch, None)
    r = api.put("/v1/orgs/org-a/connections/anthropic", headers=INTERNAL,
                json={"backend": "claude", "provider": "anthropic", "api_key": "sk-ant-x"})
    assert r.status_code == 501, r.text
    err = r.json()["error"]
    assert err["code"] == "secrets_not_configured" and "HR_SECRET_KEY" in err["message"]
    assert not store._p("org-a", "harness-conn-anthropic").exists()           # nothing in the clear


def test_a_provider_connection_is_sealed_where_it_can_be(api, monkeypatch):
    store = _store(monkeypatch, "k")
    r = api.put("/v1/orgs/org-a/connections/anthropic", headers=INTERNAL,
                json={"backend": "claude", "provider": "anthropic", "api_key": "sk-ant-x"})
    assert r.status_code == 200, r.text
    raw = _raw(store, "org-a", "harness-conn-anthropic")
    assert raw.startswith("hrenc1:") and "sk-ant-x" not in raw
    assert json.loads(asyncio.run(store.get("org-a", "harness-conn-anthropic")))["api_key"] == "sk-ant-x"


def test_every_credential_writer_requires_encryption():
    """The writers of a provider key, the integrations document, an MCP token and a plug's
    secret go through _vault_put_credential; a model map or a policy chain is not a secret and
    stays on _vault_put."""
    src = (ROOT / "gateway" / "app.py").read_text()
    for name in ("harness-conn-", "_INTEGRATIONS_KEY, json.dumps(out)", "_INTEGRATIONS_PREV_KEY, prior",
                 "(tenant, key, token", "(org, ref, value.strip()", "(org, ref, rt)"):
        line = next(ln for ln in src.splitlines() if name in ln and "_vault_put" in ln)
        assert "_vault_put_credential(" in line, line
    for name in ("_MODEL_MAP_KEY, json.dumps(mm)", "harness-policy-"):
        line = next(ln for ln in src.splitlines() if name in ln and "_vault_put" in ln)
        assert "_vault_put(" in line and "_vault_put_credential" not in line, line


def test_health_says_whether_secrets_are_encrypted(api, monkeypatch):
    _store(monkeypatch, None)
    assert api.get("/healthz").json()["secrets_encrypted"] is False
    _store(monkeypatch, "k")
    assert api.get("/healthz").json()["secrets_encrypted"] is True


# ── the entrypoint ────────────────────────────────────────────────────────────────────────────

def test_the_entrypoint_gives_an_install_with_no_key_one_at_first_start():
    ep = (ROOT / "docker" / "entrypoint.sh").read_text()
    block = ep[ep.index('HR_SECRET_KEY_FILE="$DATA_DIR/secret-key"'):]
    block = block[:block.index("\nfi\n") + 4]
    assert re.search(r'if \[ -z "\$\{HR_SECRET_KEY:-\}" \]', block), "an operator's key must win"
    assert "umask 077" in block and "token_urlsafe(32)" in block and 'chmod 600 "$HR_SECRET_KEY_FILE"' in block
    assert "export HR_SECRET_KEY" in block
    # root reads and writes the file only once it is root's own regular file (0.37.17): a link or a
    # file the product left at that name on an older volume is removed, not followed
    assert block.index('root_file "$HR_SECRET_KEY_FILE"') < block.index('[ ! -s "$HR_SECRET_KEY_FILE" ]')
    # root's python is isolated: neither the current directory nor the environment adds a module
    assert '"$PY" -I -c' in block and '"$PY" -c' not in block
    # before the gateway starts, and after the entrypoint's own HOME and data-dir setup
    assert ep.index('HR_SECRET_KEY_FILE="$DATA_DIR/secret-key"') < ep.index("uvicorn app:app")
    # the runner never gets it: it is the product's, not the agents' (unchanged)
    assert "-u HR_SECRET_KEY" in ep
