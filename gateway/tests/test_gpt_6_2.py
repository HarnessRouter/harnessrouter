"""gpt-6.2-astra and gpt-6.2-sol (released 2026-11-17; OpenAI's pricing page, Vercel's changelog and
OpenRouter's model pages, read the same day): every provider we route to that carries the gpt-6 line
names them, and each is a candidate placed exactly where its predecessor is, to be measured. 6.2-sol
goes wherever gpt-6.1-sol is offered, with the same channel refusals and exclusions; 6.2-astra wherever
gpt-6-astra is, Responses-only as it is. Newest first in the OpenAI family; no default changed."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

ASTRA, SOL = "gpt-6.2-astra", "gpt-6.2-sol"
PRED = {ASTRA: "gpt-6-astra", SOL: "gpt-6.1-sol"}
APP_PY = Path(__file__).resolve().parents[1] / "app.py"

# The defaults as they stood before the 6.2 line arrived: adding a candidate changes none of them.
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


def test_every_provider_that_carries_the_line_names_its_own_id():
    for m in (ASTRA, SOL):
        assert gw._vendor_models("openai")[m] == m
        assert gw._vendor_models("azure-foundry")[m] == m
        for provider in ("openrouter", "tokenrouter", "vercel", "llmtr"):
            assert gw._vendor_models(provider)[m] == f"openai/{m}", (provider, m)
        assert m not in gw._TOKENROUTER_NO_CHANNEL and m not in gw._VERCEL_NO_CHANNEL
    # every aggregator table that carries gpt-6.1-sol carries both, and no other vendor table does
    for provider, table in gw._VENDOR_MODELS.items():
        if provider == "harnessrouter":
            continue   # the hosted list, read at run time
        assert (ASTRA in table) == (SOL in table) == ("gpt-6.1-sol" in table), provider
    # the -fast / Ultrafast variants are not offered anywhere
    for table in gw._VENDOR_MODELS.values():
        assert not any(re.match(r"(openai/)?gpt-6\.2-.*fast", str(v)) for v in table.values())


def test_the_prices_read_on_release_day_are_written_beside_the_catalog():
    """There is no price table in this tree (billing reads the engine's); the list prices live in the
    catalog's comment, as every line's do. Changing them here has to be a decision made there too."""
    src = re.sub(r"\s*\n\s*#\s*", " ", APP_PY.read_text())
    assert ("gpt-6.2-astra $8 in / $40 out, cached $0.40, cache write $10, and above 272k prompt tokens "
            "$16 / $60, cached $0.80, cache write $20") in src
    assert ("gpt-6.2-sol $2 in / $10 out, cached $0.10, cache write $2.50, and above 272k prompt tokens "
            "$4 / $15, cached $0.20, cache write $5, as gpt-6.1-sol") in src
    assert "doubled above 272k" not in src.split("gpt-6.2-astra $8", 1)[1][:400]   # 1.5x on output, not 2x


def test_the_line_leads_the_openai_family_newest_first():
    o = gw._MODEL_ORDER
    assert list(o[:4]) == [ASTRA, SOL, "gpt-6.1-sol", "gpt-6-astra"]


def test_each_is_offered_exactly_where_its_predecessor_is():
    for base, cat in gw._MODEL_CATALOG.items():
        models = cat["models"]
        if base in gw._STILL_QUALIFYING:
            # offers only what it has run so far (roder: gpt-6.1-sol alone); the line is not offered
            assert not ({ASTRA, SOL} & set(models)), base
            continue
        for m, pred in PRED.items():
            assert (m in models) == (pred in models), (base, m)
        # placed directly before the predecessor's line entries, astra ahead of sol
        if SOL in models:
            assert models.index(SOL) + 1 == models.index("gpt-6.1-sol"), base
        if ASTRA in models:
            assert models.index(ASTRA) + 1 == models.index(SOL), base
            assert models.index("gpt-6.1-sol") + 1 == models.index("gpt-6-astra"), base
    # and the same exclusions: a base that does not offer the predecessor excludes the successor too
    for base, gone in gw._NOT_OFFERED.items():
        for m, pred in PRED.items():
            assert (m in gone) == (pred in gone), (base, m)


def test_the_bases_that_offer_them():
    measured = {b: c for b, c in gw._MODEL_CATALOG.items() if b not in gw._STILL_QUALIFYING}
    sol = {b for b, c in measured.items() if SOL in c["models"]}
    astra = {b for b, c in measured.items() if ASTRA in c["models"]}
    assert sol == {b for b, c in measured.items() if "gpt-6.1-sol" in c["models"]}
    assert astra == {b for b, c in measured.items() if "gpt-6-astra" in c["models"]}
    assert astra < sol
    assert not (astra & set(gw.CHAT_ONLY_BACKENDS))
    # roder qualifies on its one model and is left as it is
    assert gw._MODEL_CATALOG["roder"]["models"] == ["gpt-6.1-sol"]


def test_astra_is_responses_only_and_sol_is_not():
    assert ASTRA in gw.RESPONSES_ONLY_MODELS and "gpt-6-astra" in gw.RESPONSES_ONLY_MODELS
    assert SOL not in gw.RESPONSES_ONLY_MODELS and "gpt-6.1-sol" not in gw.RESPONSES_ONLY_MODELS


def test_vision_follows_the_predecessor():
    assert SOL in gw._VISION_CAPABLE and "gpt-6.1-sol" in gw._VISION_CAPABLE
    assert ASTRA not in gw._VISION_CAPABLE and "gpt-6-astra" not in gw._VISION_CAPABLE


def test_a_connection_that_refuses_6_1_sol_for_a_base_refuses_6_2_sol_too():
    pairs = [k for k, refused in gw._CHANNEL_REFUSES.items() if "gpt-6.1-sol" in refused]
    assert len(pairs) >= 20
    for k, refused in gw._CHANNEL_REFUSES.items():
        assert ("gpt-6.1-sol" in refused) == (SOL in refused), k
        assert ("gpt-6-astra" in refused) == (ASTRA in refused), k
    assert gw._channel_refuses("tokenrouter", "vibe", SOL) and gw._channel_refuses("openai", "kimi", SOL)
    assert not gw._channel_refuses("openrouter", "kimi", SOL)              # the aggregator translates
    assert not gw._channel_refuses("openai", "openhands", SOL)             # litellm's Responses path


def test_no_default_changed():
    assert {b: c["default"] for b, c in gw._MODEL_CATALOG.items()} == DEFAULTS
    assert not any(c["default"] in (ASTRA, SOL) for c in gw._MODEL_CATALOG.values())
