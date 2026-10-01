"""A customer benchmark, 2026-09-30: a model the base could not serve was replaced by the harness
default and the run billed as another model; a row adding a model newer than the release was
accepted and ignored; a write without model_map answered 422; a skill the server set aside was
visible only in the console."""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_a_model_the_base_cannot_serve_is_refused_not_replaced(monkeypatch):
    async def no(*a, **k):
        return False
    monkeypatch.setattr(gw, "_model_authorized_async", no)
    with pytest.raises(HTTPException) as e:
        asyncio.run(gw._resolve_model_policy("claude-sonnet-9", {"default_model": "claude-sonnet-5"}, "claude", "org"))
    assert e.value.status_code == 400
    assert e.value.detail["code"] == "model_not_available" and e.value.detail["param"] == "model"
    assert "claude-sonnet-9" in e.value.detail["message"] and "claude" in e.value.detail["message"]
    # no request, or a bare family name, is the harness default and not a refusal
    assert asyncio.run(gw._resolve_model_policy("", {"default_model": "claude-sonnet-5"}, "claude", "org")) == "claude-sonnet-5"
    async def yes(*a, **k):
        return True
    monkeypatch.setattr(gw, "_model_authorized_async", yes)
    assert asyncio.run(gw._resolve_model_policy("claude-sonnet-5.5", {}, "claude", "org")) == "claude-sonnet-5.5"


def test_the_response_never_claims_a_fallback():
    src = Path(gw.__file__).read_text()
    assert "model_fallback" not in src and "requested_model" not in src


def test_a_row_for_a_model_the_table_does_not_list_adds_it_on_a_current_document():
    table = gw._vendor_models("anthropic")
    assert "claude-sonnet-5" in table
    integ = {"name": "Anthropic", "provider": "anthropic", "config": {}, "rows_v": 2,
             "models": [{"canonical": "claude-sonnet-9", "provider_id": "claude-sonnet-9-20270101"},
                        {"canonical": "claude-sonnet-5", "provider_id": "claude-sonnet-5-custom"}]}
    models = gw._integration_models(integ)
    assert models["claude-sonnet-9"] == "claude-sonnet-9-20270101"          # added
    assert models["claude-sonnet-5"] == "claude-sonnet-5-custom"            # overridden, as before
    assert set(table) - {"claude-sonnet-5"} <= set(models)                  # the table's own stay
    stale = {**integ}; stale.pop("rows_v")
    assert "claude-sonnet-9" not in gw._integration_models(stale)           # an old snapshot adds nothing
    # the picker lists the added model for a base the integration drives
    async def mm():
        return {"claude-sonnet-9": "Anthropic"}
    async def docs():
        return [integ]
    view = asyncio.run(_with(mm, docs, lambda: gw._harness_models_view({}, "claude", servable={"claude-sonnet-9"})))
    row = next(m for m in view["models"] if m["id"] == "claude-sonnet-9")
    assert row["available"] and row["backend"] == "claude"
    view = asyncio.run(_with(mm, docs, lambda: gw._harness_models_view({}, "codex", servable=set())))
    assert not any(m["id"] == "claude-sonnet-9" for m in view["models"])  # anthropic drives no codex


async def _with(mm, docs, call):
    saved = gw._effective_model_map, gw._integrations_doc
    gw._effective_model_map, gw._integrations_doc = mm, docs
    try:
        return await call()
    finally:
        gw._effective_model_map, gw._integrations_doc = saved


def test_a_write_may_leave_the_model_map_alone():
    body = gw.IntegrationsBody(integrations=[])
    assert body.model_map is None
    assert gw.IntegrationsBody(integrations=[], model_map={}).model_map == {}


def test_the_record_says_what_a_package_did_not_load():
    v = {"id": "h1", "name": "n", "base": "claude-code",
         "plugins": json.dumps([{"name": "reg-parsing", "enabled": True,
                                 "skipped": [{"path": "skills/reg-parsing-v3",
                                              "reason": "SKILL.md needs a description of at most 1024 characters"}]},
                                {"name": "clean", "enabled": True}])}
    out = gw._harness_out(v)
    assert out["notLoaded"] == [{"plugin": "reg-parsing", "path": "skills/reg-parsing-v3",
                                 "reason": "SKILL.md needs a description of at most 1024 characters"}]


def test_the_api_describes_the_three_list_fields():
    schema = gw.HarnessBody.model_json_schema()
    props = schema["properties"]
    assert props["mcp_servers"]["items"]["properties"]["transport"]["enum"] == ["http", "sse", "stdio"]
    assert "1024" in props["skills"]["description"]
    assert "agent-plugins.org/schemas/1.0.0/plugin.schema.json" in props["plugins"]["description"]
    assert props["plugins"]["items"]["properties"]["files"]["items"]["required"] == ["path"]


def test_a_custom_messages_endpoint_drives_the_three_bases_that_now_speak_it():
    for b in ("goose", "hermes", "openhands"):
        assert b in gw._CUSTOM_FORMAT_BACKENDS["anthropic"]
    assert "codex" not in gw._CUSTOM_FORMAT_BACKENDS["anthropic"]


def test_every_picker_reads_the_one_view():
    """/v1/models and /v1/bases feed the base pickers; a second copy of the harness route's logic
    listed custom endpoints only, so a model added to a vendor integration ran but never showed."""
    src = Path(gw.__file__).read_text()
    models_route = src[src.index('@app.get("/v1/models")'):src.index('@app.get("/v1/harnesses/{hid}/models")')]
    bases_route = src[src.index('@app.get("/v1/bases")'):src.index('"builtinSkillsEnumerable": False')]
    assert "await _harness_models_view({}, b, await _servable_models(org, b))" in models_route
    assert "await _harness_models_view({}, backend, await _servable_models(org, backend))" in bases_route
    assert 'provider") or "").lower() != "custom"' not in models_route
