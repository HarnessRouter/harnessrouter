"""qwen4-max (Alibaba, released 2026-11-16; Model Studio's model and pricing pages and the aggregators' own
/v1/models, read 2026-11-22). OpenRouter, Vercel and llmtr name it; TokenRouter answered 404 model_not_found and
does not. It is placed exactly where qwen3.8-max is and measured there: 25 of 25 bases pass all five matrix
scenarios on Vercel and on OpenRouter. Newest first in the Alibaba family; no default changed. fast-agent offers
it although it does not offer qwen3.8-max: that exclusion is for qwen3.8-max's own measured answer there, not
for the family."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

NEW, PRED = "qwen4-max", "qwen3.8-max"
APP_PY = Path(__file__).resolve().parents[1] / "app.py"

# The defaults as they stood before qwen4-max arrived: adding a candidate changes none of them.
DEFAULTS = {
    "codex": "gpt-6.1-sol", "claude": "claude-sonnet-5.5", "hermes": "gpt-6.1-sol", "dsh": "deepseek-v4-pro",
    "opencode": "gpt-6.1-sol", "aider": "gpt-6.1-sol", "kimi": "kimi-k3", "minimax": "minimax-m3",
    "grok": "grok-4.6", "openhands": "gpt-5.4", "cheetahclaws": "gpt-5.4", "agentzero": "gpt-6.1-sol",
    "qwen": "qwen3.7-max", "cline": "gpt-5.4", "pi": "gpt-6.1-sol", "gemini": "gemini-3.8-flash",
    "omp": "gpt-6.1-sol", "goose": "gpt-6.1-sol", "kilo": "gpt-6.1-sol", "mimo": "gpt-6.1-sol",
    "jcode": "gpt-5.4", "opensquilla": "gpt-5.4", "nanobot": "gpt-5.4", "zeroclaw": "gpt-5.4",
    "vibe": "gpt-5.4", "docker-agent": "gpt-5.4", "fast-agent": "gpt-5.4", "dcode": "gpt-6.1-sol",
    "roder": "gpt-6.1-sol", "systemone": "jev-latest", "qoder": "ultimate",
}


def test_every_aggregator_that_carries_the_qwen_line_names_its_own_id():
    for provider in ("openrouter", "llmtr"):
        assert gw._vendor_models(provider)[NEW] == "qwen/qwen4-max", provider
    assert gw._vendor_models("vercel")[NEW] == "alibaba/qwen4-max"
    assert NEW not in gw._VERCEL_NO_CHANNEL
    assert NEW not in gw._OPENROUTER_RESLUG   # OpenRouter serves it under the plain name, no dated alias
    # TokenRouter answered 404 model_not_found on three bases (2026-11-22): off its list, not out of the catalog
    assert NEW in gw._TOKENROUTER_NO_CHANNEL and NEW not in gw._vendor_models("tokenrouter")
    assert PRED in gw._vendor_models("tokenrouter")
    # every other vendor table that carries qwen3.8-max carries qwen4-max, and no other one does
    for provider, table in gw._VENDOR_MODELS.items():
        if provider in ("harnessrouter", "tokenrouter"):
            continue   # the hosted list, read at run time; TokenRouter above
        assert (NEW in table) == (PRED in table), provider
    # Model Studio lists no preview, snapshot or -latest alias beside it, so none is offered anywhere
    for table in gw._VENDOR_MODELS.values():
        assert not any(re.search(r"qwen4-max-", str(v)) for v in table.values())


def test_the_facts_read_on_the_day_are_written_beside_the_catalog():
    """There is no price table in this tree (billing reads the engine's); the list price lives in the
    catalog's comment, as every line's does. Changing it here has to be a decision made there too."""
    src = re.sub(r"\s*\n\s*#\s*", " ", APP_PY.read_text())
    assert ("qwen4-max $1.50 in / $4.50 out, cached $0.075, cache write $1.875 (5 min)") in src
    assert "Thinking is on by default there (effort high), and thinking tokens bill as output" in src
    assert ("MEASURED (2026-11-22, the test instance, the matrix's five scenarios on every base that offers it): "
            "25 of 25 bases pass on Vercel and 25 of 25 on OpenRouter") in src


def test_it_leads_the_alibaba_family_newest_first():
    o = list(gw._MODEL_ORDER)
    assert o.index(NEW) + 1 == o.index(PRED)
    assert o[o.index(NEW) - 1] == "kimi-k2.7-code"   # the family before Alibaba's ends there


def test_it_is_offered_where_qwen3_8_max_is_and_on_fast_agent():
    pred_bases = {b for b, c in gw._MODEL_CATALOG.items() if PRED in c["models"]}
    new_bases = {b for b, c in gw._MODEL_CATALOG.items() if NEW in c["models"]}
    assert new_bases == pred_bases | {"fast-agent"}
    assert "fast-agent" not in pred_bases and PRED in gw._NOT_OFFERED["fast-agent"]
    assert not any(NEW in gone for gone in gw._NOT_OFFERED.values())
    for base in pred_bases:
        models = gw._MODEL_CATALOG[base]["models"]
        assert models.index(NEW) + 1 == models.index(PRED), base   # directly before its predecessor
    assert len(new_bases) == 25
    # still-qualifying bases and the vendor-locked ones are left alone
    for base in ("roder", "codex", "claude", "gemini", "systemone", "qoder"):
        assert NEW not in gw._MODEL_CATALOG[base]["models"], base


def test_it_is_a_chat_model_not_a_responses_only_one_and_vision_waits_for_a_measurement():
    assert NEW not in gw.RESPONSES_ONLY_MODELS
    assert NEW not in gw._VISION_CAPABLE and PRED not in gw._VISION_CAPABLE
    assert not any(NEW in refused for refused in gw._CHANNEL_REFUSES.values())


def test_the_provider_slug_reaches_the_wire():
    assert gw._map_model({"provider": "openrouter", "backend": "hermes"}, NEW) == "qwen/qwen4-max"
    assert gw._map_model({"provider": "vercel", "backend": "qwen"}, NEW) == "alibaba/qwen4-max"
    assert gw._map_model({"provider": "llmtr", "backend": "opencode"}, NEW) == "qwen/qwen4-max"


def test_no_default_changed():
    assert {b: c["default"] for b, c in gw._MODEL_CATALOG.items()} == DEFAULTS
    assert not any(c["default"] == NEW for c in gw._MODEL_CATALOG.values())
