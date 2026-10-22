"""A connection's model rows on save (PUT /v1/admin/integrations).

A row is {canonical, provider_id}, and a blank wire id is the canonical. A list of bare ids is the same
rows with blank wire ids; it used to fail the whole save with a 500 ('str' object has no attribute
'get'). Any other shape is refused by name, with a 400, never a crash.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def _save(monkeypatch, integrations):
    written = {}

    async def allow(request):
        return None

    async def doc():
        return []

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


CUSTOM = {"name": "Mine", "provider": "custom",
          "config": {"base_url": "http://127.0.0.1:9/v1", "api_key": "k-for-a-test", "api_format": "openai"}}


def test_bare_ids_are_rows_whose_wire_id_is_their_own(monkeypatch):
    saved = _save(monkeypatch, [{**CUSTOM, "models": ["m-one", {"canonical": "m-two", "provider_id": "wire-two"}]}])
    assert saved["Mine"]["models"] == [{"canonical": "m-one", "provider_id": "m-one"},
                                       {"canonical": "m-two", "provider_id": "wire-two"}]


@pytest.mark.parametrize("bad", [7, ["m"], None])
def test_any_other_shape_is_refused_by_name(monkeypatch, bad):
    with pytest.raises(HTTPException) as e:
        _save(monkeypatch, [{**CUSTOM, "models": ["ok", bad]}])
    assert e.value.status_code == 400
    assert "Mine" in str(e.value.detail)


@pytest.mark.parametrize("models", ["m-one", {"m-one": "w"}, 7])
def test_models_that_are_not_a_list_are_refused_and_nothing_is_written(monkeypatch, models):
    # a string used to be read letter by letter, each letter a model
    with pytest.raises(HTTPException) as e:
        _save(monkeypatch, [{**CUSTOM, "models": models}])
    assert e.value.status_code == 400 and "Mine" in str(e.value.detail)
