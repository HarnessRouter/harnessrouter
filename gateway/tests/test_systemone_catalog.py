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


def test_the_base_is_in_the_catalog_with_hard_enforcement_and_no_built_in_tools():
    b = gw._BASE_CATALOG["systemone"]
    assert b["backend"] == "systemone" and b["status"] == "ready" and b["label"] == "System One"
    assert b["tool_enforcement"] == "hard"
    assert b["tools"] == []     # the actions are the environment's; nothing is built into the base


def test_an_openrouter_integration_drives_the_base_and_no_other_provider_claims_to():
    assert gw._INTEGRATION_WIRING[("openrouter", "systemone")] == "openrouter"
    others = [k for k in gw._INTEGRATION_WIRING if k[1] == "systemone" and k[0] != "openrouter"]
    assert others == []
    assert gw._integration_serves_backend({"provider": "openrouter"}, "systemone")
    assert not gw._integration_serves_backend({"provider": "tokenrouter"}, "systemone")


def test_an_incomplete_turn_status_is_a_response_status_of_its_own():
    assert gw._RESP_STATUS_MAP["incomplete"] == "incomplete"


def test_a_custom_endpoints_models_never_appear_on_the_systemone_list(monkeypatch):
    """Measured on hr-test 2026-09-19: a System One harness's picker showed claude-sonnet-4.6,
    gpt-5.5 and four more as "(no provider)". They were the rows of custom-endpoint integrations,
    appended to every backend as unavailable. No custom format can drive systemone, so nothing of
    theirs belongs on its list; a chat backend keeps the greyed row as its explanation."""
    import asyncio
    integ = [{"name": "my-openai", "provider": "custom", "config": {"api_format": "openai", "base_url": "https://x/v1"}}]

    async def _integrations():
        return integ

    async def _map():
        return {"gpt-5.5": "my-openai", "jev-1.13": "openrouter"}

    monkeypatch.setattr(gw, "_integrations_doc", _integrations)
    monkeypatch.setattr(gw, "_effective_model_map", _map)
    assert not gw._custom_can_drive("systemone") and gw._custom_can_drive("claude") and gw._custom_can_drive("hermes")
    view = asyncio.run(gw._harness_models_view(None, "systemone", {"jev-1.13", "jev-latest"}))
    assert [m["id"] for m in view["models"]] == ["jev-1.13", "jev-latest"]
    assert all(m["available"] for m in view["models"])
    # a chat backend the custom format cannot drive still shows the row, greyed, as the explanation
    view = asyncio.run(gw._harness_models_view(None, "claude", set()))
    row = next(m for m in view["models"] if m["id"] == "gpt-5.5")
    assert row["available"] is False


def test_the_base_takes_no_skills_and_none_are_mounted_for_a_turn(monkeypatch):
    """The built-in skills are prose an agent reads and scripts it runs from a shell, each needing
    free text; a System One model chooses among offered actions and writes nothing. So the base
    declares it takes no skills, the bases endpoint offers none, and a turn mounts none, for the
    built-in harness and for a harness forked from it alike."""
    import asyncio
    assert gw._BASE_CATALOG["systemone"]["skills"] is False
    assert not gw._base_takes_skills("systemone") and gw._base_takes_skills("codex") and gw._base_takes_skills("")
    monkeypatch.setattr(gw, "_builtin_skills", lambda: {"pdf": {"title": "PDF", "description": "", "default_enabled": True,
                                                                  "origin": "image", "files": [{"path": "SKILL.md", "content": "x"}]}})
    _, skills, _, _, _ = asyncio.run(gw._harness_plugins("systemone", "local", None, hv=None))
    assert skills == []
    _, skills, _, _, _ = asyncio.run(gw._harness_plugins("codex", "local", None, hv=None))
    assert [s["name"] for s in skills] == ["pdf"]
