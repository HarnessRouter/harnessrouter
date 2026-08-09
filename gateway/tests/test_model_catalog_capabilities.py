"""Every catalog model must be drivable by the agent loop.

A harness runs a conversation with tools: it sends text, reads text back, and calls functions.
A model that generates images or video, or that cannot call tools, is not a candidate however
impressive it is — selecting one produces a task that fails at the first tool call, or returns
something the transcript cannot render.

Nothing enforced this when the catalog was written by hand; models were picked by vendor family
and happened to be chat models. This checks it instead of hoping.

Capabilities are read from OpenRouter's live catalog, which publishes input/output modalities and
supported parameters for the same models. The test SKIPS when the network is unavailable, so it
never turns an offline checkout red — it is a correctness gate, not a liveness probe.
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
_OPENROUTER = "https://openrouter.ai/api/v1/models"


def _vendor_models() -> dict[str, dict[str, str]]:
    """The vendor table, read from source without importing the app (which wants env + network)."""
    src = open(_SRC).read()
    m = re.search(r"_VENDOR_MODELS: dict\[str, dict\[str, str\]\] = (\{.*?\n\})\n", src, re.S)
    assert m, "_VENDOR_MODELS not found in app.py"
    return eval(m.group(1), {"__builtins__": {}}, {})  # noqa: S307 — our own literal


def _catalog() -> dict[str, dict]:
    src = open(_SRC).read()
    m = re.search(r"^_MODEL_CATALOG: dict\[str, dict\] = (\{.*?^\})", src, re.S | re.M)
    assert m, "_MODEL_CATALOG not found in app.py"
    return eval(m.group(1), {"__builtins__": {}}, {})  # noqa: S307


@pytest.fixture(scope="module")
def openrouter() -> dict[str, dict]:
    try:
        with urllib.request.urlopen(_OPENROUTER, timeout=30) as r:
            return {m["id"]: m for m in json.load(r)["data"]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        pytest.skip(f"OpenRouter catalog unreachable ({e}) — capability check skipped")


def test_every_catalog_model_is_a_chat_llm(openrouter):
    """Text in, text out, and able to call tools. Anything else cannot drive an agent turn."""
    slugs = _vendor_models()["openrouter"]
    unusable = []
    for canonical, slug in slugs.items():
        meta = openrouter.get(slug)
        if meta is None:
            continue                      # covered by the slug test below
        arch = meta.get("architecture") or {}
        inputs = arch.get("input_modalities") or []
        outputs = arch.get("output_modalities") or []
        params = meta.get("supported_parameters") or []
        why = []
        if "text" not in inputs:
            why.append(f"input={inputs}")
        if "text" not in outputs:
            why.append(f"output={outputs}")
        if "tools" not in params:
            why.append("no tool calling")
        if why:
            unusable.append(f"{canonical} ({slug}): {', '.join(why)}")
    assert not unusable, (
        "these catalog models cannot drive an agent turn:\n  " + "\n  ".join(unusable))


def test_every_aggregator_slug_exists(openrouter):
    """A slug we cannot address is worse than an absent model: it is offered and then rejected."""
    missing = [f"{c} -> {s}" for c, s in _vendor_models()["openrouter"].items()
               if s not in openrouter]
    assert not missing, "aggregator slugs not present on OpenRouter:\n  " + "\n  ".join(missing)


def test_catalog_and_vendor_tables_agree():
    """Every model a backend offers must be servable by at least one vendor — offline check."""
    vendors = _vendor_models()
    servable = set().union(*(set(t) for t in vendors.values()))
    orphans = sorted({m for c in _catalog().values() for m in c["models"]} - servable)
    assert not orphans, f"catalog models no vendor serves: {orphans}"
