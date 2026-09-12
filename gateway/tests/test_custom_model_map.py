"""Issue #149: a custom endpoint names its models its own way, so its rows are the map."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_the_custom_rows_are_the_map_and_a_blank_wire_id_is_the_canonical():
    integ = {"name": "proxy", "provider": "custom",
             "config": {"api_format": "responses", "base_url": "https://proxy.internal/openai/v1"},
             "models": [{"canonical": "claude-opus-4.8", "provider_id": "anthropic--claude-4.8-opus"},
                        {"canonical": "gpt-5.5", "provider_id": ""},
                        {"canonical": "gpt-5.4", "provider_id": "prod-gpt-v2"}]}
    assert gw._integration_models(integ) == {"claude-opus-4.8": "anthropic--claude-4.8-opus",
                                             "gpt-5.5": "gpt-5.5", "gpt-5.4": "prod-gpt-v2"}


def test_a_custom_integration_saved_with_one_model_id_still_reads_as_that_one_row():
    integ = {"name": "old", "provider": "custom", "config": {"api_format": "openai", "model_id": "my-llm"}}
    assert gw._integration_models(integ) == {"my-llm": "my-llm"}
    # rows win over the legacy field once they exist
    integ["models"] = [{"canonical": "gpt-5.5", "provider_id": "x"}]
    assert gw._integration_models(integ) == {"gpt-5.5": "x"}


def test_the_mapped_connection_sends_the_wire_id_verbatim(monkeypatch):
    integ = {"name": "proxy", "provider": "custom",
             "config": {"api_format": "responses", "base_url": "https://proxy.internal/openai/v1", "api_key": "k"},
             "models": [{"canonical": "gpt-5.5", "provider_id": "prod-gpt-v2"}]}
    async def mm(): return {"gpt-5.5": "proxy"}
    async def docs(): return [integ]
    monkeypatch.setattr(gw, "_effective_model_map", mm)
    monkeypatch.setattr(gw, "_integrations_doc", docs)
    conn = asyncio.run(gw._mapped_integration_conn("codex", "gpt-5.5"))
    assert conn and conn["provider"] == "tokenrouter" and conn["model"] == "prod-gpt-v2" and conn["_model_resolved"]
    # a Responses endpoint drives codex and nothing else; a chat one never drives codex
    assert gw._integration_serves_backend(integ, "codex") and not gw._integration_serves_backend(integ, "hermes")
    integ["config"]["api_format"] = "openai"
    assert not gw._integration_serves_backend(integ, "codex") and gw._integration_serves_backend(integ, "hermes")


def test_the_catalog_offers_the_canonicals_to_the_custom_form_and_disabled_tools_wherever_codex_runs():
    cat = {c["id"]: c for c in gw._provider_catalog_public()}
    custom = cat["custom"]
    assert "gpt-5.5" in custom["canonicals"] and "claude-opus-4.8" in custom["canonicals"]
    assert not any(f["key"] == "model_id" for f in custom["fields"])
    for pid, c in cat.items():
        has = any(f["key"] == "disabled_tools" for f in c["fields"])
        assert has == ("codex" in c["backends"]), pid
    assert "codex" in custom["backends"]


def test_the_connections_disabled_tools_join_the_harness_list_for_the_turn():
    # the union the turn body carries: the harness's list plus the connection's comma-separated field
    conn = {"provider": "tokenrouter", "disabled_tools": "web_search, image_generation"}
    conn_off = [t.strip() for t in str(conn.get("disabled_tools") or "").split(",") if t.strip()]
    assert sorted(set(["Bash"]) | set(conn_off)) == ["Bash", "image_generation", "web_search"]
