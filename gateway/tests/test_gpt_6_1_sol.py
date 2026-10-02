"""gpt-6.1-sol (OpenAI's pricing page, and the OpenRouter, TokenRouter, Vercel and llmtr /v1/models
lists, all read 2026-10-02): every provider we route to names it, and it leads the gpt-6 family
wherever gpt-6-sol is offered. It refuses reasoning_effort "none", so a connection that passes
chat/completions through (TokenRouter, OpenAI direct) refuses function tools on the chat-only bases,
while OpenRouter and Vercel translate to the Responses API and serve them (measured 2026-10-02); as
with the gpt-5.6 line, a row measured working on a path stays listed. Not Responses-only: aider
(chat completions, no function tools) runs it everywhere; goose on its own measured pairs."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

M = "gpt-6.1-sol"
REFUSED_EVERYWHERE = []


def test_every_provider_we_route_to_names_its_own_id():
    assert gw._vendor_models("openai")[M] == M
    assert gw._vendor_models("azure-foundry")[M] == M          # Azure's catalog, model version 2026-09-29
    for provider in ("openrouter", "tokenrouter", "vercel", "llmtr"):
        assert gw._vendor_models(provider)[M] == f"openai/{M}", provider
    assert M not in gw._TOKENROUTER_NO_CHANNEL


def test_it_leads_the_gpt_6_family_wherever_that_family_is_offered():
    for base, cat in gw._MODEL_CATALOG.items():
        models = cat["models"]
        if base in REFUSED_EVERYWHERE:
            assert M not in models, base
        elif "gpt-6-sol" in models:
            assert models.index(M) == models.index("gpt-6-sol") - (2 if "gpt-6-astra" in models else 1), base
            if "gpt-6-astra" in models:
                assert models.index(M) + 1 == models.index("gpt-6-astra"), base
        else:
            assert M not in models, base
    o = gw._MODEL_ORDER
    assert o.index(M) + 1 == o.index("gpt-6-astra")


def test_it_is_not_responses_only():
    assert M not in gw.RESPONSES_ONLY_MODELS            # aider runs it: chat completions, no function tools


def test_it_sees_images():
    assert M in gw._VISION_CAPABLE
