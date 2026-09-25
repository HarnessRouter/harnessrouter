"""The muse base (Meta's Muse Code): what the catalog promises is what the router can run.

Muse Code speaks Meta's Model API and nothing else — its provider enum is `echo|meta`, it fetches
Meta's own catalog (GET /muse-code/models) before every turn and calls the Responses API — so one
provider drives it, and only it. Meta serves that catalog at the HOST ROOT, not under /v1 (measured
2026-09-25: /muse-code/models 200, /v1/muse-code/models 404), so the broker must place it beside
the version segment or a brokered turn cannot start.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

MUSE = ["muse-spark-1.3", "muse-spark-1.3-contributor", "muse-spark-1.2", "muse-spark-1.2-contributor"]


def test_the_meta_provider_is_metas_model_api_and_brokerable():
    p = gw._PROVIDER_CATALOG["meta"]
    assert p["base_url"] == "https://api.meta.ai/v1" and p["secret"] == "api_key"
    assert "meta" in gw._BROKERABLE_PROVIDERS
    assert "muse" not in gw._NATIVE_ONLY_BACKENDS


def test_only_the_meta_connection_drives_muse():
    wired = {integ for (integ, backend) in gw._INTEGRATION_WIRING if backend == "muse"}
    assert wired == {"meta"}, "no aggregator serves Meta's /muse-code/models, so none can run the CLI"
    assert gw._INTEGRATION_WIRING[("meta", "muse")] == "meta"
    assert not gw._custom_can_drive("muse"), "a custom endpoint has no Muse Code catalog either"


def test_the_catalog_defaults_to_the_standard_id_and_offers_the_discount_beside_it():
    """-contributor is about a twelfth of the price and lets Meta use the content for product
    improvement. A harness sends the person's own code, so the discount is theirs to pick."""
    cat = gw._MODEL_CATALOG["muse"]
    assert cat["default"] == "muse-spark-1.3"
    assert cat["models"] == MUSE, "each discounted id sits right after the model it discounts"
    assert set(cat["models"]) <= set(gw._VENDOR_MODELS["meta"])
    assert all(gw._VENDOR_MODELS["meta"][m] == m for m in MUSE), "Meta names them by the canonical ids"


def test_no_other_base_offers_a_contributor_id():
    for backend, cat in gw._MODEL_CATALOG.items():
        if backend != "muse":
            assert not any(m.endswith("-contributor") for m in cat.get("models") or []), backend


def test_the_base_is_listed_with_the_clis_own_tool_names_and_an_honest_enforcement_tier():
    b = gw._BASE_CATALOG["muse"]
    assert b["backend"] == "muse" and b["status"] == "ready"
    names = [t for t, _ in b["tools"]]
    assert {"bash", "read_file", "write_file", "edit_file", "search", "web_search"} <= set(names)
    assert len(names) == len(set(names)) == 31
    assert b["tool_enforcement"] == "instruction"
    assert "muse" in gw._SUPPORTED_BASES


def test_the_broker_carries_the_catalog_and_puts_it_beside_the_version_segment():
    assert gw._broker_path_allowed("muse-code/models")
    assert not gw._broker_path_allowed("muse-code/feedback"), "the allowlist names the one listing"
    assert gw._broker_upstream_url("https://api.meta.ai/v1", "muse-code/models") == \
        "https://api.meta.ai/muse-code/models"
    assert gw._broker_upstream_url("https://api.meta.ai/v1/", "responses") == "https://api.meta.ai/v1/responses"
    # every other provider's join is unchanged
    assert gw._broker_upstream_url("https://openrouter.ai/api/v1", "chat/completions") == \
        "https://openrouter.ai/api/v1/chat/completions"
    assert gw._broker_upstream_url("https://api.example/v1", "") == "https://api.example/v1"


def test_the_broker_endpoint_builds_its_url_with_that_rule():
    src = pathlib.Path(gw.__file__).read_text()
    assert "url = _broker_upstream_url(base, suffix)" in src
