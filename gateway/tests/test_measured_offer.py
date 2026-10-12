"""A base offers only the models it was measured to run reliably (2026-10-12).

mimo, jcode, opensquilla and nanobot start from the list of the base whose wire reach they share,
and each loses every model that failed on it in the full measurement. These pin both halves: none
of the measured failures comes back with a list refresh (opencode's or kimi's list growing, a
reorder), and nothing else was dropped along the way."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

# What each model did is in the comment above _NOT_OFFERED; the ids are repeated here on purpose,
# so removing one there has to be a decision made here too.
FAILED = {
    "mimo": {"claude-opus-4.7", "llama-3.3-70b", "llama-4-maverick", "qwen3.8-flash", "gpt-5.6-luna",
             "hunyuan-4-preview"},
    "jcode": {"grok-build-0.1", "hunyuan-4-preview", "kimi-k3", "gemini-3-flash-preview"},
    "opensquilla": {"claude-opus-4.7", "grok-4.20", "llama-3.3-70b", "hunyuan-4-preview"},
    "nanobot": {"grok-build-0.1", "kimi-k3", "llama-3.3-70b", "grok-4.5"},
}
REACH = {"mimo": "opencode", "jcode": "kimi", "opensquilla": "kimi", "nanobot": "kimi"}


def test_a_model_that_failed_on_a_base_is_not_offered_there():
    for base, failed in FAILED.items():
        offered = set(gw._MODEL_CATALOG[base]["models"])
        assert not (offered & failed), (base, sorted(offered & failed))
        assert gw._NOT_OFFERED[base] == frozenset(failed), base


def test_the_offer_is_the_reach_less_the_measured_failures_and_nothing_else():
    for base, failed in FAILED.items():
        src = REACH[base]
        reach = set(gw._MODEL_CATALOG[src]["models"]) | gw._NOT_OFFERED.get(src, frozenset())
        if base != "mimo":   # the chat-only bases never had the Responses-only ids
            reach -= gw.RESPONSES_ONLY_MODELS
        assert set(gw._MODEL_CATALOG[base]["models"]) == reach - failed, base


def test_every_default_is_one_the_base_still_offers():
    for base in FAILED:
        cat = gw._MODEL_CATALOG[base]
        assert cat["default"] in cat["models"], base
