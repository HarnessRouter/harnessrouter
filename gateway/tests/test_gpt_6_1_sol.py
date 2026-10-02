"""gpt-6.1-sol (OpenAI's pricing page, and the OpenRouter, TokenRouter, Vercel and llmtr /v1/models
lists, all read 2026-10-02): every provider we route to names it, it leads the gpt-6 family wherever
that family is offered, and like gpt-6-sol it takes function tools on chat/completions
(reasoning_effort "none"), so the chat-only bases offer it too. goose is measured-only: it gains the
id once its own pairs pass, as it did for gpt-6-sol."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

M = "gpt-6.1-sol"


def test_every_provider_we_route_to_names_its_own_id():
    assert gw._vendor_models("openai")[M] == M
    assert gw._vendor_models("azure-foundry")[M] == M          # Azure's catalog, model version 2026-09-29
    for provider in ("openrouter", "tokenrouter", "vercel", "llmtr"):
        assert gw._vendor_models(provider)[M] == f"openai/{M}", provider
    assert M not in gw._TOKENROUTER_NO_CHANNEL


def test_it_leads_the_gpt_6_family_wherever_that_family_is_offered():
    for base, cat in gw._MODEL_CATALOG.items():
        models = cat["models"]
        if base == "goose":
            assert M not in models                                  # measured-only, see the docstring
            continue
        if "gpt-6-sol" in models:
            assert models.index(M) == models.index("gpt-6-sol") - (2 if "gpt-6-astra" in models else 1), base
            if "gpt-6-astra" in models:
                assert models.index(M) + 1 == models.index("gpt-6-astra"), base
        else:
            assert M not in models, base
    o = gw._MODEL_ORDER
    assert o.index(M) + 1 == o.index("gpt-6-astra")


def test_it_is_not_responses_only_and_the_chat_only_bases_offer_it():
    assert M not in gw.RESPONSES_ONLY_MODELS
    for base in gw.CHAT_ONLY_BACKENDS:
        if base != "goose" and "gpt-6-sol" in gw._MODEL_CATALOG[base]["models"]:
            assert M in gw._MODEL_CATALOG[base]["models"], base


def test_it_sees_images():
    assert M in gw._VISION_CAPABLE
