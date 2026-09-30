"""Claude Sonnet 5.5 (Anthropic's models overview and pricing page, OpenRouter's, Vercel's,
TokenRouter's and llmtr's /v1/models, all read 2026-09-30): every provider names it under its own
id, every aggregator lists it (unlike Opus 5.5 on the day it was added), and every backend that
offers Sonnet 5 offers it beside."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_every_provider_that_serves_sonnet_5_5_names_its_own_id():
    assert gw._VENDOR_MODELS["anthropic"]["claude-sonnet-5.5"] == "claude-sonnet-5-5"
    assert gw._VENDOR_MODELS["bedrock"]["claude-sonnet-5.5"] == "us.anthropic.claude-sonnet-5-5"
    for agg in ("openrouter", "vercel", "tokenrouter", "llmtr"):
        assert gw._VENDOR_MODELS[agg]["claude-sonnet-5.5"] == "anthropic/claude-sonnet-5.5", agg
    assert gw._ANTHROPIC_CLAUDE["sonnet-5.5"] == "claude-sonnet-5-5" and gw._BEDROCK_CLAUDE["sonnet-5.5"] == "us.anthropic.claude-sonnet-5-5"
    assert "claude-sonnet-5.5" not in gw._TOKENROUTER_NO_CHANNEL


def test_it_sits_beside_sonnet_5_in_every_catalog_that_offers_sonnet_5():
    for base, cat in gw._MODEL_CATALOG.items():
        models = cat["models"]
        if "claude-sonnet-5" in models:
            assert models.index("claude-sonnet-5.5") == models.index("claude-sonnet-5") - 1, base
        else:
            assert "claude-sonnet-5.5" not in models, base
    assert gw._MODEL_ORDER.index("claude-sonnet-5.5") == gw._MODEL_ORDER.index("claude-sonnet-5") - 1
    assert "claude-sonnet-5.5" in gw._VISION_CAPABLE
