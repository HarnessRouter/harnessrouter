"""A stored key goes only where it was typed for.

The console never sees a stored secret: an unchanged edit sends a placeholder back and the stored value is
carried through. Carried through a CHANGED address, it sent the key on to wherever the new address pointed, and
whoever runs that address could spend it without ever having seen it. The hosted service refuses that save;
so does this one. An unchanged edit, the catalog's own address filled in or not, still saves.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

KEY = "sk-stored-key-0123456789"


def _save(monkeypatch, integrations, stored=()):
    written = {}

    async def allow(request):
        return None

    async def doc():
        return list(stored)

    async def vget(tenant, key):
        return None

    async def vput(tenant, key, value):
        written[key] = value
        return True
    monkeypatch.setattr(gw, "_require_integrations_admin", allow)
    monkeypatch.setattr(gw, "_integrations_doc", doc)
    monkeypatch.setattr(gw, "_vault_get", vget)
    monkeypatch.setattr(gw, "_vault_put", vput)
    asyncio.run(gw.admin_integrations_put(gw.IntegrationsBody(integrations=list(integrations)), None))
    return {i["name"]: i for i in json.loads(written[gw._INTEGRATIONS_KEY])}


CUSTOM = {"name": "Mine", "provider": "custom", "config": {"api_key": KEY, "base_url": "https://llm.example.com/v1",
                                                            "api_format": "openai"}}


def test_a_kept_key_cannot_follow_a_new_address(monkeypatch):
    stored = _save(monkeypatch, [CUSTOM])["Mine"]
    moved = {**CUSTOM, "config": {**CUSTOM["config"], "api_key": gw._SECRET_SENTINEL,
                                  "base_url": "https://attacker.example/v1"}}
    with pytest.raises(HTTPException) as e:
        _save(monkeypatch, [moved], stored=[stored])
    assert e.value.status_code == 400 and "type its key again" in str(e.value.detail)


def test_a_kept_key_cannot_follow_a_new_provider(monkeypatch):
    stored = _save(monkeypatch, [CUSTOM])["Mine"]
    swapped = {"name": "Mine", "provider": "openrouter", "config": {"api_key": gw._SECRET_SENTINEL}}
    with pytest.raises(HTTPException):
        _save(monkeypatch, [swapped], stored=[stored])


def test_an_unchanged_edit_keeps_its_key(monkeypatch):
    stored = _save(monkeypatch, [CUSTOM])["Mine"]
    again = _save(monkeypatch, [{**CUSTOM, "config": {**CUSTOM["config"], "api_key": gw._SECRET_SENTINEL}}], stored=[stored])
    assert again["Mine"]["config"]["api_key"] == KEY


def test_a_catalog_provider_saved_without_its_address_keeps_its_key(monkeypatch):
    """The form sends no base_url for a provider whose endpoint the catalog knows; the effective address is
    the catalog's on both sides, so the edit is unchanged."""
    first = {"name": "OpenAI", "provider": "openai", "config": {"api_key": KEY}}
    stored = _save(monkeypatch, [first])["OpenAI"]
    again = _save(monkeypatch, [{"name": "OpenAI", "provider": "openai", "config": {"api_key": gw._SECRET_SENTINEL}}],
                  stored=[stored])
    assert again["OpenAI"]["config"]["api_key"] == KEY


def test_a_new_address_with_its_key_typed_again_saves(monkeypatch):
    stored = _save(monkeypatch, [CUSTOM])["Mine"]
    moved = {**CUSTOM, "config": {**CUSTOM["config"], "api_key": "sk-typed-again-0123456789",
                                  "base_url": "https://other.example.com/v1"}}
    out = _save(monkeypatch, [moved], stored=[stored])
    assert out["Mine"]["config"]["base_url"] == "https://other.example.com/v1"
