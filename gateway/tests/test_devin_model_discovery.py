"""Devin dynamic model discovery.

The live discovery path talks to Codeium's Connect-RPC endpoint, so these unit tests
use small sample payloads to exercise selection, catalog update, and fallback without
hitting the network.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _devin_select_models, _devin_update_catalog


def _sample_configs() -> list[dict]:
    return [
        {
            "modelUid": "swe-1-7",
            "label": "SWE-1.7 Max",
            "isRecommended": True,
            "modelFamilyMetadata": {"modelFamilyLabel": "SWE-1.7"},
        },
        {
            "modelUid": "swe-1-7-medium",
            "label": "SWE-1.7 Medium",
            "modelFamilyMetadata": {"modelFamilyLabel": "SWE-1.7"},
        },
        {
            "modelUid": "swe-1-7-lightning",
            "label": "SWE-1.7 Lightning Max",
            "isRecommended": True,
            "modelFamilyMetadata": {"modelFamilyLabel": "SWE-1.7 Lightning"},
        },
        {
            "modelUid": "claude-sonnet-5-medium",
            "label": "Claude Sonnet 5 Medium",
            "isRecommended": True,
            "modelFamilyMetadata": {"modelFamilyLabel": "Claude Sonnet 5"},
        },
        {
            "modelUid": "MODEL_PRIVATE_2",
            "label": "Claude Sonnet 4.5",
            "isRecommended": True,
            "modelFamilyMetadata": {"modelFamilyLabel": "Claude Sonnet 4.5"},
        },
        {
            "modelUid": "disabled-model",
            "label": "Disabled Model",
            "disabled": True,
            "isRecommended": True,
            "modelFamilyMetadata": {"modelFamilyLabel": "SWE-1.7"},
        },
    ]


def test_devin_select_models_keeps_recommended_swe_only():
    """ACP currently supports the main SWE-1.x family; we must not advertise non-SWE variants."""
    selected = _devin_select_models(_sample_configs())
    ids = [m[0] for m in selected]
    assert ids == ["swe-1-7", "devin-swe"]
    assert selected[0][1] == "SWE-1.7 Max"
    assert selected[-1][1] == "Devin SWE"


def test_devin_select_models_skips_disabled_and_internal_ids():
    """Disabled entries and internal MODEL_* ids are dropped from the picker."""
    selected = _devin_select_models(_sample_configs())
    ids = [m[0] for m in selected]
    assert "disabled-model" not in ids
    assert "MODEL_PRIVATE_2" not in ids


def test_devin_update_catalog_sets_default_to_newest_swe():
    """The catalog default should be the newest recommended SWE family."""
    selected = [("swe-1-7", "SWE-1.7 Max")]
    models = _devin_update_catalog(selected)
    assert models == {"swe-1-7"}
    import app
    assert app._MODEL_CATALOG["devin"]["default"] == "swe-1-7"
    assert app._MODEL_CATALOG["devin"]["models"] == ["swe-1-7"]
    assert app._VENDOR_MODELS["devin"]["swe-1-7"] == "swe-1-7"


def test_devin_update_catalog_falls_back_to_static_on_empty():
    """If discovery yields nothing, the existing catalog stays intact."""
    import app
    before = dict(app._MODEL_CATALOG["devin"])
    _devin_update_catalog([])
    after = app._MODEL_CATALOG["devin"]
    assert after["default"] == before["default"]
    assert after["models"] == before["models"]
