"""Every catalog model on Opper must be drivable by the agent loop.

Capabilities are read from Opper's live catalog (GET https://api.opper.ai/v3/models), which
publishes input/output modalities and capabilities (including tools) for all served models.
The test SKIPS when the network is unavailable, matching test_model_catalog_capabilities.py.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
_OPPER_MODELS = "https://api.opper.ai/v3/models"


def _vendor_models() -> dict[str, dict[str, str]]:
    """The vendor table, read from source without importing the app (which wants env + network)."""
    src = open(_SRC, encoding="utf-8").read()
    m = re.search(r"_VENDOR_MODELS:\s*dict\[str,\s*dict\[str,\s*str\]\]\s*=\s*(\{.*?\n\})\n", src, re.S)
    assert m, "_VENDOR_MODELS not found in app.py"
    tables = eval(m.group(1), {"__builtins__": {}}, {})
    return tables


def _catalog() -> dict[str, dict]:
    src = open(_SRC, encoding="utf-8").read()
    m = re.search(r"^\s*_MODEL_CATALOG:\s*dict\[str,\s*dict\]\s*=\s*(\{.*?^\})", src, re.S | re.M)
    assert m, "_MODEL_CATALOG not found in app.py"
    return eval(m.group(1), {"__builtins__": {}}, {})


@pytest.fixture(scope="module")
def opper_catalog() -> dict[str, list[dict]]:
    """Fetch Opper's public models catalogue, grouped by pooled model name."""
    try:
        models_by_slug: dict[str, list[dict]] = {}
        offset = 0
        limit = 500
        while True:
            url = f"{_OPPER_MODELS}?limit={limit}&offset={offset}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            batch = data.get("models", [])
            for m in batch:
                mod = m.get("model")
                if mod:
                    models_by_slug.setdefault(mod, []).append(m)
            if not data.get("has_more") or not batch:
                break
            offset = data.get("next_offset", offset + len(batch))
        return models_by_slug
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        pytest.skip(f"Opper catalog unreachable ({e}) — capability check skipped")


def test_opper_table_exists():
    """_VENDOR_MODELS must contain an entry for opper."""
    vendors = _vendor_models()
    assert "opper" in vendors, "opper missing from _VENDOR_MODELS"
    assert len(vendors["opper"]) > 0, "opper table in _VENDOR_MODELS is empty"


def test_every_opper_canonical_in_model_catalog():
    """All models in _VENDOR_MODELS['opper'] must be known in _MODEL_CATALOG."""
    catalog = _catalog()
    all_catalog_models = {m for c in catalog.values() for m in c.get("models", [])}
    opper_models = _vendor_models()["opper"]
    unknown = [m for m in opper_models if m not in all_catalog_models]
    assert not unknown, f"opper models not in _MODEL_CATALOG: {unknown}"


def test_every_opper_model_exists_and_supports_tools(opper_catalog):
    """Every model in _VENDOR_MODELS['opper'] must exist on Opper and support tools."""
    slugs = _vendor_models()["opper"]
    unusable = []
    missing = []
    for canonical, slug in slugs.items():
        routes = opper_catalog.get(slug)
        if not routes:
            missing.append(f"{canonical} -> {slug}")
            continue
        
        # Check if at least one route supports tools and text
        has_tools = False
        why_list = []
        for r in routes:
            caps = r.get("capabilities") or []
            in_mod = r.get("input_modalities") or []
            out_mod = r.get("output_modalities") or []
            if "tools" in caps and "text" in in_mod and "text" in out_mod:
                has_tools = True
                break
            why_list.append(f"caps={caps}")

        if not has_tools:
            unusable.append(f"{canonical} ({slug}): no route with tools support ({', '.join(why_list[:2])})")

    assert not missing, f"opper slugs not found on Opper /v3/models: {missing}"
    assert not unusable, f"opper models lacking tool support: {unusable}"
