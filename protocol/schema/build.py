#!/usr/bin/env python3
"""Derive the JSON Schema document from the OpenAPI document.

The two files describe the same objects. Maintaining both by hand guarantees they drift, and a
client generated from one would then disagree with a validator built on the other — the kind of
inconsistency a standard exists to prevent. So the OpenAPI document is the source, and this script
produces the JSON Schema from it.

    python protocol/schema/build.py            # write the JSON Schema
    python protocol/schema/build.py --check    # fail if it is out of date (for CI)

`components.schemas` maps to `$defs`, and internal references are rewritten from OpenAPI's
`#/components/schemas/X` to JSON Schema's `#/$defs/X`. Nothing else is transformed: the subset of
OpenAPI 3.1 used here is JSON Schema 2020-12 by construction, which is why 3.1 was chosen.
"""
from __future__ import annotations

import json
import pathlib
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - environment guidance, not logic
    sys.exit("PyYAML is required: pip install pyyaml")

HERE = pathlib.Path(__file__).parent
VERSION = "2026-08-11"
SRC = HERE / f"uhp-{VERSION}.openapi.yaml"
OUT = HERE / f"uhp-{VERSION}.schema.json"


def rewrite_refs(node):
    """`#/components/schemas/X` (OpenAPI) -> `#/$defs/X` (JSON Schema)."""
    if isinstance(node, dict):
        return {
            k: (v.replace("#/components/schemas/", "#/$defs/")
                if k == "$ref" and isinstance(v, str) else rewrite_refs(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [rewrite_refs(v) for v in node]
    return node


def build() -> dict:
    spec = yaml.safe_load(SRC.read_text())
    defs = rewrite_refs(spec["components"]["schemas"])
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://unifiedharnessprotocol.io/schema/uhp-{VERSION}.schema.json",
        "title": "Unified Harness Protocol",
        "description": (
            f"Object definitions for UHP {VERSION}. Generated from "
            f"uhp-{VERSION}.openapi.yaml by build.py — do not edit by hand."
        ),
        "$defs": defs,
    }


def main() -> int:
    doc = build()
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.name} is out of date — run: python protocol/schema/build.py")
            return 1
        print(f"{OUT.name} is up to date ({len(doc['$defs'])} definitions)")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.name} ({len(doc['$defs'])} definitions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
