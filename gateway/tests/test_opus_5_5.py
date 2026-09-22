"""Claude Opus 5.5 (Anthropic's models overview and pricing page, 2026-09-22; OpenRouter's and
Vercel's /v1/models the same day): every provider that serves it names it under its own id, the
one that does not list it yet is left out, and every backend that offers Opus 5 offers it beside."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_every_provider_that_serves_opus_5_5_names_its_own_id():
    assert gw._VENDOR_MODELS["anthropic"]["claude-opus-5.5"] == "claude-opus-5-5"
    assert gw._VENDOR_MODELS["bedrock"]["claude-opus-5.5"] == "us.anthropic.claude-opus-5-5"
    assert gw._VENDOR_MODELS["openrouter"]["claude-opus-5.5"] == "anthropic/claude-opus-5.5"
    assert gw._VENDOR_MODELS["vercel"]["claude-opus-5.5"] == "anthropic/claude-opus-5.5"
    assert gw._ANTHROPIC_CLAUDE["opus-5.5"] == "claude-opus-5-5" and gw._BEDROCK_CLAUDE["opus-5.5"] == "us.anthropic.claude-opus-5-5"


def test_aggregators_that_do_not_list_it_do_not_promise_it():
    assert "claude-opus-5.5" not in gw._VENDOR_MODELS["tokenrouter"]      # TokenRouter's list, 2026-09-22
    assert "claude-opus-5.5" not in gw._VENDOR_MODELS["llmtr"]            # llmtr's list, 2026-09-22


def test_it_sits_beside_opus_5_in_every_catalog_that_offers_opus_5():
    for base, cat in gw._MODEL_CATALOG.items():
        models = cat["models"]
        if "claude-opus-5" in models:
            assert models.index("claude-opus-5.5") == models.index("claude-opus-5") - 1, base
        else:
            assert "claude-opus-5.5" not in models, base
    assert gw._MODEL_ORDER.index("claude-opus-5.5") == gw._MODEL_ORDER.index("claude-opus-5") - 1
    assert "claude-opus-5.5" in gw._VISION_CAPABLE
