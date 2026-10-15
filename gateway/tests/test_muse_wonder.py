"""Muse Wonder (2026-10-14), read off each vendor's own list that day and called with a tool: Meta's
own API and Vercel name it `muse-wonder-1.0`, OpenRouter `meta/muse-wonder` ($4 / $20 per million),
each answering as the id it was asked for. TokenRouter has no channel for it under either name and
llmtr does not list it. Muse Wonder Full has no API: Meta serves it only inside Muse Code."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_each_vendor_that_serves_it_names_it_as_it_does():
    assert gw._VENDOR_MODELS["openrouter"]["muse-wonder-1.0"] == "meta/muse-wonder"
    assert gw._VENDOR_MODELS["vercel"]["muse-wonder-1.0"] == "meta/muse-wonder-1.0"
    assert "muse-wonder-1.0" not in gw._VENDOR_MODELS["tokenrouter"] and "muse-wonder-1.0" in gw._TOKENROUTER_NO_CHANNEL
    assert "muse-wonder-1.0" not in gw._VENDOR_MODELS.get("llmtr", {})
    assert not any("full" in m for t in gw._VENDOR_MODELS.values() for m in t if m.startswith("muse-wonder"))


def test_every_base_that_offers_a_muse_model_offers_it_first_in_its_family():
    for b, c in gw._MODEL_CATALOG.items():
        muse = [m for m in c["models"] if m.startswith("muse")]
        if muse:
            assert muse[0] == "muse-wonder-1.0", (b, muse)
    assert gw._MODEL_ORDER.count("muse-wonder-1.0") == 1
