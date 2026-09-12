"""A model served on the Responses API alone is not offered on a harness that speaks chat/completions only."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

# Measured against OpenAI directly: called with function tools these answer on /v1/responses and are
# refused on /v1/chat/completions. gpt-6-astra joined them on 2026-09-07 with the same sentence,
# "Function tools with reasoning_effort are not supported for gpt-6-astra in /v1/chat/completions".
RESPONSES_ONLY = {"gpt-5.3-codex", "gpt-6-astra"}
# goose speaks chat/completions and nothing else: its provider takes OPENAI_HOST plus an
# OPENAI_BASE_PATH the runner fixes at "…/chat/completions", so a Responses-only id listed for it
# would be a picker row that fails on send, exactly as for qwen and cline.
CHAT_ONLY_BACKENDS = ("qwen", "cline", "goose")
RESPONSES_BACKENDS = ("codex", "hermes", "pi", "dsh", "opencode", "omp")


def test_responses_only_models_stay_off_chat_only_harnesses():
    for backend in CHAT_ONLY_BACKENDS:
        listed = set(gw._MODEL_CATALOG[backend]["models"])
        assert not (listed & RESPONSES_ONLY), f"{backend} lists {listed & RESPONSES_ONLY}"


def test_the_harnesses_that_speak_responses_keep_it():
    for backend in RESPONSES_BACKENDS:
        for model in RESPONSES_ONLY:
            assert model in gw._MODEL_CATALOG[backend]["models"], f"{backend} is missing {model}"


def test_gpt_6_astra_is_served_by_every_provider_we_route_to():
    """Each id read from that provider's own model list on the day it was added (2026-09-07):
    OpenAI and our Azure resource serve it bare, the aggregators under OpenAI's vendor prefix."""
    assert gw._vendor_models("openai")["gpt-6-astra"] == "gpt-6-astra"
    assert gw._vendor_models("azure-foundry")["gpt-6-astra"] == "gpt-6-astra"
    for provider in ("openrouter", "tokenrouter", "vercel", "llmtr"):
        assert gw._vendor_models(provider)["gpt-6-astra"] == "openai/gpt-6-astra", provider
    assert "gpt-6-astra" not in gw._TOKENROUTER_NO_CHANNEL
