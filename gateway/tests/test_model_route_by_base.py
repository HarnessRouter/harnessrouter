"""A mapped model runs on an integration that can drive the base. The map names the integration
that serves a model with no base in mind; when that one has no wiring for the base, another
integration that lists the model and drives the base takes the turn (claude-opus-5.5 on Claude
Code, hosted 2026-09-27: mapped to OpenRouter, which has no Anthropic-shaped endpoint, while
Vercel AI Gateway serves it and drives Claude Code). On this tree `_integration_driving` has
made that choice since 2026-09-06; this pins it for the case hosted hit, with hosted's turn
failure sentences for a turn that ran on no connection. The example model is now claude-haiku-5.5,
which stands where Opus 5.5 stood then: TokenRouter lists Opus 5.5 since 2026-10-07 and does not list
Haiku 5.5, which OpenRouter and Vercel serve."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def _async(v):
    async def _f(*a, **k):
        return v
    return _f()


DOC = [{"name": "TokenRouter Sponsorship", "provider": "tokenrouter", "config": {"api_key": "sk-t", "base_url": "https://tr.example/v1"}},
       {"name": "OpenRouter", "provider": "openrouter", "config": {"api_key": "sk-o", "base_url": "https://openrouter.ai/api/v1"}},
       {"name": "Vercel AI Gateway", "provider": "vercel", "config": {"api_key": "sk-v", "base_url": "https://ai-gateway.vercel.sh/v1"}}]


def _world(monkeypatch, doc=DOC, route="OpenRouter"):
    monkeypatch.setattr(gw, "_effective_model_map", lambda: _async({"claude-haiku-5.5": route}))
    monkeypatch.setattr(gw, "_integrations_doc", lambda: _async([dict(i) for i in doc]))


def test_the_vendor_tables_know_who_serves_haiku_5_5():
    assert "claude-haiku-5.5" in gw._integration_models(DOC[1]) and "claude-haiku-5.5" in gw._integration_models(DOC[2])
    assert "claude-haiku-5.5" not in gw._integration_models(DOC[0])
    assert ("openrouter", "claude") not in gw._INTEGRATION_WIRING and ("vercel", "claude") in gw._INTEGRATION_WIRING


def test_a_base_the_mapped_integration_cannot_drive_runs_on_another_that_serves_the_model(monkeypatch):
    _world(monkeypatch)
    conn = asyncio.run(gw._mapped_integration_conn("claude", "claude-haiku-5.5"))
    assert conn and conn["name"] == "integration:Vercel AI Gateway"
    assert conn["provider"] == gw._INTEGRATION_WIRING[("vercel", "claude")] and conn["model"] == "anthropic/claude-haiku-5.5"
    # a base the mapped integration drives keeps the map's choice
    conn = asyncio.run(gw._mapped_integration_conn("hermes", "claude-haiku-5.5"))
    assert conn and conn["name"] == "integration:OpenRouter"


def test_an_integration_without_the_model_is_passed_over(monkeypatch):
    _world(monkeypatch, doc=DOC[:2])
    assert asyncio.run(gw._mapped_integration_conn("claude", "claude-haiku-5.5")) is None


def test_a_turn_that_ran_on_no_connection_says_so_in_words():
    rec = {"model": "claude-haiku-5.5", "tried": [{"connection": "tr", "error": "provider does not serve 'claude-haiku-5.5'"},
                                               {"connection": "br", "error": "credential cannot be brokered; refused"}]}
    m = gw._turn_failure_message(rec)
    assert m.startswith("claude-haiku-5.5 is served here only by a connection this harness's base cannot use.") and "Bring Your Own Key" in m
    assert "brokered" not in m and "tr" not in m.split()
    rec = {"model": "gpt-9", "tried": [{"connection": "tr", "error": "provider does not serve 'gpt-9'"}, {"connection": "v", "error": "not found"}]}
    assert gw._turn_failure_message(rec).startswith("No connection on this account serves gpt-9.")
