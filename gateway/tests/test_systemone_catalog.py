"""The systemone base: what the catalog promises is what the router can run.

Jev is a decision model served by TypeSafe's own API and by OpenRouter, each under its own ids,
so those ids live in the two vendor tables and no other's, and only the systemone base lists them.
A turn on the base is served through one of the two wirings, and a run that stops for a reason of
its own reports that reason rather than a failure or a step cap.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

JEV_OPENROUTER = {"jev-1.13": "typesafe/jev-1.13", "jev-latest": "~typesafe/jev-latest"}
JEV_TYPESAFE = {"jev-latest": "jev-latest", "jev-preview": "jev-preview"}     # measured 2026-09-20
JEV = set(JEV_OPENROUTER) | set(JEV_TYPESAFE)


def test_jev_is_on_its_two_providers_under_their_own_ids_and_nowhere_else():
    assert {c: gw._VENDOR_MODELS["openrouter"][c] for c in JEV_OPENROUTER} == JEV_OPENROUTER
    assert gw._VENDOR_MODELS["typesafe"] == JEV_TYPESAFE
    assert "jev-1.13" not in gw._VENDOR_MODELS["typesafe"]        # "Unknown model" on TypeSafe's API
    assert "jev-preview" not in gw._VENDOR_MODELS["openrouter"]   # OpenRouter does not serve the preview
    for vendor in ("tokenrouter", "vercel", "llmtr", "openai", "anthropic", "google"):
        table = gw._VENDOR_MODELS.get(vendor) or {}
        assert not (JEV & set(table)), f"{vendor} lists a Jev id it cannot serve"


def test_only_the_systemone_base_offers_jev_and_it_offers_nothing_else():
    # the default is the one id both providers serve, so a harness made on either connection runs
    assert gw._MODEL_CATALOG["systemone"] == {"default": "jev-latest", "models": ["jev-latest", "jev-preview", "jev-1.13"]}
    assert gw._MODEL_CATALOG["systemone"]["default"] in gw._VENDOR_MODELS["typesafe"]
    assert gw._MODEL_CATALOG["systemone"]["default"] in gw._VENDOR_MODELS["openrouter"]
    for backend, cat in gw._MODEL_CATALOG.items():
        if backend == "systemone":
            continue
        assert not (JEV & set(cat.get("models", []))), f"{backend} offers a Jev id it cannot answer"


def test_the_base_is_in_the_catalog_with_hard_enforcement_and_no_built_in_tools():
    b = gw._BASE_CATALOG["systemone"]
    assert b["backend"] == "systemone" and b["status"] == "ready" and b["label"] == "System One"
    assert b["tool_enforcement"] == "hard"
    assert b["tools"] == []     # the actions are the environment's; nothing is built into the base


def test_a_typesafe_or_openrouter_integration_drives_the_base_and_no_other_provider_claims_to():
    assert gw._INTEGRATION_WIRING[("openrouter", "systemone")] == "openrouter"
    assert gw._INTEGRATION_WIRING[("typesafe", "systemone")] == "typesafe"
    others = [k for k in gw._INTEGRATION_WIRING if k[1] == "systemone" and k[0] not in ("openrouter", "typesafe")]
    assert others == []
    assert gw._integration_serves_backend({"provider": "openrouter"}, "systemone")
    assert gw._integration_serves_backend({"provider": "typesafe"}, "systemone")
    assert not gw._integration_serves_backend({"provider": "tokenrouter"}, "systemone")
    # the provider is a plain bearer HTTP API with a fixed base, checked at /v1/models, and it
    # serves no chat model: only the systemone base can use a TypeSafe connection
    ts = gw._PROVIDER_CATALOG["typesafe"]
    assert ts["label"] == "TypeSafe AI" and ts["base_url"] == "https://api.typesafe.ai/v1" and ts["secret"] == "api_key"
    assert "typesafe" in gw._BROKERABLE_PROVIDERS
    assert [b for b in gw._MODEL_CATALOG if gw._integration_serves_backend({"provider": "typesafe"}, b)] == ["systemone"]


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
    view = asyncio.run(gw._harness_models_view(None, "systemone", {"jev-1.13", "jev-latest", "jev-preview"}))
    assert [m["id"] for m in view["models"]] == ["jev-latest", "jev-preview", "jev-1.13"]
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
