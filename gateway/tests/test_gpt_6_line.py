"""The gpt-6 line's sol and luna tiers (OpenAI's pricing page, Azure's model catalog, and the
OpenRouter, TokenRouter, Vercel and llmtr /v1/models lists, all read 2026-09-27): every provider we
route to names them, they sit with astra ahead of the gpt-5.6 line everywhere that line is offered,
and, unlike astra, they take function tools on chat/completions (reasoning_effort "none", measured on
TokenRouter the same day), so the chat-only bases offer them too."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

LINE = ("gpt-6-sol", "gpt-6-luna")


def test_every_provider_we_route_to_names_its_own_id():
    for m in LINE:
        assert gw._vendor_models("openai")[m] == m
        assert gw._vendor_models("azure-foundry")[m] == m           # deployed on our resource 2026-09-27
        for provider in ("openrouter", "tokenrouter", "vercel", "llmtr"):
            assert gw._vendor_models(provider)[m] == f"openai/{m}", (provider, m)
        assert m not in gw._TOKENROUTER_NO_CHANNEL


def test_they_sit_with_astra_ahead_of_the_gpt_5_6_line_wherever_it_is_offered():
    for base, cat in gw._MODEL_CATALOG.items():
        models = cat["models"]
        if "gpt-5.6-sol" in models and base != "goose":               # goose: measured lists only
            i = models.index("gpt-5.6-sol")
            assert models[i - 2:i] == ["gpt-6-sol", "gpt-6-luna"], base
            if "gpt-6-astra" in models:
                assert models.index("gpt-6-astra") == i - 3, base
        else:
            assert not (set(LINE) & set(models)), base
    o = gw._MODEL_ORDER
    assert o.index("gpt-6-astra") + 1 == o.index("gpt-6-sol") and o.index("gpt-6-sol") + 1 == o.index("gpt-6-luna")
    assert o.index("gpt-6-luna") + 1 == o.index("gpt-5.6-sol")


def test_only_astra_is_responses_only():
    assert "gpt-6-astra" in gw.RESPONSES_ONLY_MODELS
    assert not (set(LINE) & gw.RESPONSES_ONLY_MODELS)
    for base in gw.CHAT_ONLY_BACKENDS:
        if "gpt-5.6-sol" in gw._MODEL_CATALOG[base]["models"] and base != "goose":
            assert set(LINE) <= set(gw._MODEL_CATALOG[base]["models"]), base


def test_they_see_images():
    for m in LINE:
        assert m in gw._VISION_CAPABLE
