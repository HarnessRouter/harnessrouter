"""A connection that passes chat/completions straight through to OpenAI does not serve gpt-6.1-sol to a base
that drives chat completions with function tools (2026-10-25): OpenAI refuses the pair, and this id refuses
reasoning_effort 'none' too. The picker and the turn must both pass such a connection by, and an aggregator
that translates to the Responses API still serves it."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

TOKENROUTER = {"name": "My TokenRouter", "provider": "tokenrouter", "config": {"api_key": "t", "base_url": "https://api.tokenrouter.com/v1"}}
VERCEL = {"name": "Vercel AI Gateway", "provider": "vercel", "config": {"api_key": "v", "base_url": "https://ai-gateway.vercel.sh/v1"}}
CHAT_BASES = ("vibe", "docker-agent", "fast-agent")


def test_the_refusal_is_the_measured_one_and_no_wider():
    for b in CHAT_BASES:
        for p in ("tokenrouter", "openai", "azure-foundry", "harnessrouter", "openai-api", "azure"):
            assert gw._channel_refuses(p, b, "gpt-6.1-sol"), (p, b)
        for p in ("vercel", "openrouter"):                 # they translate to the Responses API upstream
            assert not gw._channel_refuses(p, b, "gpt-6.1-sol"), (p, b)
        assert not gw._channel_refuses("tokenrouter", b, "gpt-6-sol")   # takes reasoning_effort 'none'
        assert not gw._channel_refuses("tokenrouter", b, "gpt-5.4")
    assert not gw._channel_refuses("tokenrouter", "dcode", "gpt-6.1-sol")   # drives the Responses API
    assert gw._channel_refuses("TokenRouter", "vibe", " gpt-6.1-sol ")


def test_a_mapping_to_a_refusing_connection_falls_through_to_one_that_serves():
    assert gw._integration_driving([TOKENROUTER, VERCEL], "vibe", "gpt-6.1-sol", "My TokenRouter") is VERCEL
    assert gw._integration_driving([TOKENROUTER], "vibe", "gpt-6.1-sol", "My TokenRouter") is None
    assert gw._integration_driving([TOKENROUTER], "vibe", "gpt-5.4", "My TokenRouter") is TOKENROUTER
    assert gw._integration_driving([TOKENROUTER], "dcode", "gpt-6.1-sol", "My TokenRouter") is TOKENROUTER


def test_the_picker_greys_it_on_that_connection_and_offers_it_where_it_runs(monkeypatch):
    async def mm(): return {}
    async def chain(org, backend, _): return ["only"]
    monkeypatch.setattr(gw, "_effective_model_map", mm)
    monkeypatch.setattr(gw, "_resolve_chain", chain)

    def holding(conn):
        async def docs(): return []
        async def get(org, name): return conn, None
        monkeypatch.setattr(gw, "_integrations_doc", docs)
        monkeypatch.setattr(gw, "_get_connection", get)

    holding({"provider": "tokenrouter"})
    vibe = asyncio.run(gw._servable_models("org1", "vibe"))
    assert "gpt-6.1-sol" not in vibe and "gpt-6-sol" in vibe and "gpt-5.4" in vibe
    assert "gpt-6.1-sol" in asyncio.run(gw._servable_models("org1", "dcode"))
    holding({"provider": "vercel"})
    assert "gpt-6.1-sol" in asyncio.run(gw._servable_models("org1", "vibe"))


def test_tokenrouter_does_not_offer_claude_fable_5_1_to_docker_agent_alone():
    assert gw._channel_refuses("tokenrouter", "docker-agent", "claude-fable-5-1")
    assert not gw._channel_refuses("tokenrouter", "vibe", "claude-fable-5-1")
    assert not gw._channel_refuses("openrouter", "docker-agent", "claude-fable-5-1")
    assert not gw._channel_refuses("tokenrouter", "docker-agent", "claude-fable-5")
    assert gw._channel_refuses("tokenrouter", "docker-agent", "gpt-6.1-sol")       # the earlier rule still holds


def test_tokenrouter_s_responses_endpoint_does_not_serve_dcode_claude_or_these_geminis():
    for m in ("claude-fable-5-1", "claude-sonnet-5.5", "claude-haiku-4.5", "gemini-3.5-flash"):
        assert gw._channel_refuses("tokenrouter", "dcode", m), m
    assert gw._channel_refuses("tokenrouter", "dcode", "glm-5.3-flash")
    for m in ("gpt-6.1-sol", "gemini-3.1-pro-preview", "grok-4.6", "deepseek-v4-pro", "qwen3.8-max", "glm-5.3"):
        assert not gw._channel_refuses("tokenrouter", "dcode", m), m
    assert not gw._channel_refuses("openrouter", "dcode", "claude-fable-5-1")
    assert not gw._channel_refuses("tokenrouter", "vibe", "claude-sonnet-5.5")


def test_tokenrouter_lists_neither_model_it_cannot_serve_as_itself():
    for m in ("deepseek-v4-flash", "kimi-k3"):
        assert m in gw._TOKENROUTER_NO_CHANNEL and m not in gw._vendor_models("tokenrouter"), m
    assert "deepseek-v4.1-flash" in gw._vendor_models("tokenrouter")


def test_the_older_chat_bases_are_not_offered_gpt_6_1_sol_where_it_refuses_their_tools():
    for p in ("tokenrouter", "openai", "azure-foundry"):
        for b in ("kimi", "qwen", "cline"):
            assert gw._channel_refuses(p, b, "gpt-6.1-sol"), (p, b)
    for b in ("openhands", "cheetahclaws"):
        assert gw._channel_refuses("tokenrouter", b, "gpt-6.1-sol"), b
    assert not gw._channel_refuses("openai", "openhands", "gpt-6.1-sol")         # litellm's Responses path
    assert not gw._channel_refuses("openrouter", "kimi", "gpt-6.1-sol")         # the aggregator translates
    assert not gw._channel_refuses("tokenrouter", "codex", "gpt-6.1-sol")


def test_on_the_harnessrouter_api_the_four_that_fail_are_not_offered_it_and_openhands_is():
    for b in ("kimi", "qwen", "cline", "cheetahclaws"):
        assert gw._channel_refuses("harnessrouter", b, "gpt-6.1-sol"), b
    assert not gw._channel_refuses("harnessrouter", "openhands", "gpt-6.1-sol")   # completed with a Shell call
    assert not gw._channel_refuses("harnessrouter", "kimi", "gpt-6-sol")
