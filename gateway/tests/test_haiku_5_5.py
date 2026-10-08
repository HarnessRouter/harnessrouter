"""Claude Haiku 5.5 (Anthropic's models overview and pricing page, OpenRouter's, Vercel's, TokenRouter's
and llmtr's /v1/models, all read 2026-10-07): Anthropic, Bedrock, OpenRouter and Vercel serve it under
their own ids; TokenRouter and llmtr do not list it yet. Every backend that offers Haiku 4.5 offers it
beside. The same reading found Opus 5.5 on TokenRouter's list, so it is no longer marked missing there."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_every_provider_that_serves_haiku_5_5_names_its_own_id():
    assert gw._VENDOR_MODELS["anthropic"]["claude-haiku-5.5"] == "claude-haiku-5-5"
    assert gw._VENDOR_MODELS["bedrock"]["claude-haiku-5.5"] == "us.anthropic.claude-haiku-5-5"
    for agg in ("openrouter", "vercel"):
        assert gw._VENDOR_MODELS[agg]["claude-haiku-5.5"] == "anthropic/claude-haiku-5.5", agg
    assert "claude-haiku-5.5" not in gw._VENDOR_MODELS["tokenrouter"] and "claude-haiku-5.5" not in gw._VENDOR_MODELS["llmtr"]
    assert "claude-haiku-5.5" in gw._TOKENROUTER_NO_CHANNEL
    assert gw._ANTHROPIC_CLAUDE["haiku-5.5"] == "claude-haiku-5-5" and gw._BEDROCK_CLAUDE["haiku-5.5"] == "us.anthropic.claude-haiku-5-5"


def test_opus_5_5_is_served_by_tokenrouter_now():
    assert "claude-opus-5.5" not in gw._TOKENROUTER_NO_CHANNEL
    assert gw._VENDOR_MODELS["tokenrouter"]["claude-opus-5.5"] == "anthropic/claude-opus-5.5"


def test_it_sits_beside_haiku_4_5_in_every_catalog_that_offers_haiku_4_5_but_aiders():
    """aider failed the recycle scenario on it in two of three runs (2026-10-07), so it is left out there."""
    assert "claude-haiku-5.5" not in gw._MODEL_CATALOG["aider"]["models"] and "claude-haiku-4.5" in gw._MODEL_CATALOG["aider"]["models"]
    for base, cat in gw._MODEL_CATALOG.items():
        models = cat["models"]
        if base == "aider":
            continue
        if "claude-haiku-4.5" in models:
            assert models.index("claude-haiku-5.5") == models.index("claude-haiku-4.5") - 1, base
        else:
            assert "claude-haiku-5.5" not in models, base
    assert gw._MODEL_ORDER.index("claude-haiku-5.5") == gw._MODEL_ORDER.index("claude-haiku-4.5") - 1
    assert "claude-haiku-5.5" in gw._VISION_CAPABLE


def test_the_console_offers_it_wherever_it_offers_haiku_4_5():
    ts = (Path(__file__).resolve().parents[2] / "ui" / "src" / "lib" / "harness.ts").read_text()
    assert ts.count("'claude-haiku-4.5'") - 1 == ts.count("'claude-haiku-5.5', 'claude-haiku-4.5'") > 0   # all but aider
