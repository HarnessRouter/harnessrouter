"""The systemone base: what the catalog promises is what the router can run.

Jev is a decision model served by OpenRouter alone, so its ids live in OpenRouter's vendor table
and no other aggregator's, and only the systemone base lists them. A turn on the base is served
through the one wiring, an OpenRouter integration, and a run that stops for a reason of its own
reports that reason rather than a failure or a step cap.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

JEV = {"jev-1.13": "typesafe/jev-1.13", "jev-latest": "~typesafe/jev-latest"}


def test_jev_is_on_openrouter_and_nowhere_else():
    for canonical, slug in JEV.items():
        assert gw._VENDOR_MODELS["openrouter"][canonical] == slug
    for vendor in ("tokenrouter", "vercel", "llmtr", "openai", "anthropic", "google"):
        table = gw._VENDOR_MODELS.get(vendor) or {}
        assert not (set(JEV) & set(table)), f"{vendor} lists a Jev id it cannot serve"


def test_only_the_systemone_base_offers_jev_and_it_offers_nothing_else():
    assert gw._MODEL_CATALOG["systemone"] == {"default": "jev-1.13", "models": ["jev-1.13", "jev-latest"]}
    for backend, cat in gw._MODEL_CATALOG.items():
        if backend == "systemone":
            continue
        assert not (set(JEV) & set(cat.get("models", []))), f"{backend} offers a Jev id it cannot answer"


def test_the_base_is_in_the_catalog_with_hard_enforcement_and_the_desk_actions():
    b = gw._BASE_CATALOG["systemone"]
    assert b["backend"] == "systemone" and b["status"] == "ready" and b["label"] == "System One"
    assert b["tool_enforcement"] == "hard"
    assert [n for n, _ in b["tools"]] == ["pick_item", "pack", "choose_carrier", "ship", "cancel_order", "add_note"]


def test_an_openrouter_integration_drives_the_base_and_no_other_provider_claims_to():
    assert gw._INTEGRATION_WIRING[("openrouter", "systemone")] == "openrouter"
    others = [k for k in gw._INTEGRATION_WIRING if k[1] == "systemone" and k[0] != "openrouter"]
    assert others == []
    assert gw._integration_serves_backend({"provider": "openrouter"}, "systemone")
    assert not gw._integration_serves_backend({"provider": "tokenrouter"}, "systemone")


def test_an_incomplete_turn_status_is_a_response_status_of_its_own():
    assert gw._RESP_STATUS_MAP["incomplete"] == "incomplete"
