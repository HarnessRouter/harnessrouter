#!/usr/bin/env python3
"""What this project ships stays under licences that let anyone use it: fails on anything else.

    check-licenses.py --js       the console's production packages, from ui/package-lock.json
    check-licenses.py --python   the Python packages installed in this environment
    check-licenses.py --image    inside a built image: every Node package in what we ship, and its Python

The lockfile says what a project asked for; an image holds what the build actually copied. Only the image's
own answer can catch a package nobody asked for by name. What an operator installs at first start
(/data/agent-tools) is theirs, under its own terms (NOTICE), and isn't in what we ship.

A package under anything other than a permissive licence is used only as the separate, unmodified package it
is, and is named below with the reason. It is never a place to copy a function from: read it, learn from it,
and write your own. A licence nobody declared counts as not permissive until someone has read it.
"""
from __future__ import annotations

import argparse
import importlib.metadata as im
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERMISSIVE = re.compile(
    r"^(MIT|MIT-0|MIT-CMU|ISC|0BSD|BSD|BSD-2-Clause|BSD-3-Clause|Apache-2\.0|Apache Software License|Apache License 2\.0|"
    r"BlueOak-1\.0\.0|Unlicense|CC0-1\.0|CC-BY-3\.0|CC-BY-4\.0|OFL-1\.1|Python-2\.0|PSF-2\.0|Zlib|HPND|MIT License|"
    r"BSD License|Python Software Foundation License|The Unlicense \(Unlicense\))$", re.I)

# name -> why it may stay. Each is a package used whole and unchanged, or a licence the lockfile can't see.
ACCEPTED_JS = {
    "format": "MIT, in the older `licenses` field of its package.json, which the lockfile doesn't carry",
}
ACCEPTED_PY = {
    "certifi": "MPL-2.0. Mozilla's root certificates, unchanged",
    "pyphen": "Offered under GPL, LGPL or MPL; used under MPL, unchanged. WeasyPrint needs it",
    "pypdfium2": "BSD-3-Clause and Apache-2.0, with PDFium's permissive dependencies in its own licence files",
}


def _parts(expr: str) -> tuple[list[str], str]:
    """An SPDX expression's alternatives: one permissive alternative is enough for OR, all must be for AND."""
    e = expr.strip().strip("()").strip()
    if re.search(r"\sOR\s", e):
        return [p.strip(" ()") for p in re.split(r"\s+OR\s+", e)], "any"
    if re.search(r"\sAND\s", e):
        return [p.strip(" ()") for p in re.split(r"\s+AND\s+", e)], "all"
    if ";" in e:
        return [p.strip() for p in e.split(";")], "any"
    return [e], "any"


def permissive(expr: str) -> bool:
    if not expr:
        return False
    parts, how = _parts(expr)
    ok = [bool(PERMISSIVE.match(p)) for p in parts]
    return all(ok) if how == "all" else any(ok)


def js(lock_path: str) -> list[str]:
    with open(lock_path, encoding="utf-8") as f:
        pkgs = json.load(f)["packages"]
    bad = []
    n = 0
    for where, p in pkgs.items():
        if not where or p.get("dev") or p.get("devOptional") and not p.get("optional"):
            continue
        n += 1
        if p.get("link"):
            continue                # the entry it links to is read on its own
        name = p.get("name") or where.rsplit("node_modules/", 1)[-1]
        lic = p.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type")
        if permissive(str(lic or "")) or name in ACCEPTED_JS:
            continue
        bad.append(f"{name}@{p.get('version')}: {lic or 'no licence declared'}")
    print(f"checked {n} production packages")
    return bad


def image(roots=("/app", "/opt/harnessrouter")) -> list[str]:
    bad = []
    n = 0
    for root in roots:
        for dp, _dirs, files in os.walk(root):
            if "package.json" not in files or "/node_modules/" not in dp + "/":
                continue
            try:
                with open(os.path.join(dp, "package.json"), encoding="utf-8") as f:
                    o = json.load(f)
            except (OSError, ValueError):
                continue
            # a package.json with no name and version only marks a folder of a package as ESM or CJS
            if not isinstance(o, dict) or not o.get("name") or not o.get("version") or o.get("private"):
                continue
            n += 1
            lic = o.get("license")
            if not lic and isinstance(o.get("licenses"), list):
                lic = " OR ".join(str(x.get("type") if isinstance(x, dict) else x) for x in o["licenses"])
            if isinstance(lic, dict):
                lic = lic.get("type")
            if permissive(str(lic or "")) or o["name"] in ACCEPTED_JS:
                continue
            bad.append(f"{o['name']}@{o['version']}: {lic or 'no licence declared'} ({dp})")
    print(f"checked {n} Node packages in the image")
    return bad


def python() -> list[str]:
    bad = []
    n = 0
    for d in im.distributions():
        m = d.metadata
        name = (m.get("Name") or "").lower()
        if not name:
            continue
        n += 1
        classifiers = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]
        # a classifier that says OSI Approved and nothing more names no licence
        classifiers = [c for c in classifiers if c != "OSI Approved"]
        declared = m.get("License-Expression") or ""
        raw = (m.get("License") or "").strip()
        candidates = [declared] if declared else ([*classifiers] or ([raw] if len(raw) < 60 else []))
        if name in ACCEPTED_PY or any(permissive(c) for c in candidates):
            continue
        # a long License field is the licence's whole text: its first words say which
        head = raw[:200].lower()
        if ("permission is hereby granted, free of charge" in raw.lower() or "redistribution and use in source and binary" in raw.lower()
                or "apache license" in head):
            continue
        bad.append(f"{name}@{m.get('Version')}: {' / '.join(candidates) or raw[:60] or 'no licence declared'}")
    print(f"checked {n} installed packages")
    return bad


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--js", action="store_true")
    a.add_argument("--python", action="store_true")
    a.add_argument("--image", action="store_true")
    o = a.parse_args()
    bad = []
    if o.image:
        bad += image() + python()
    if o.js:
        bad += js(os.path.join(ROOT, "ui", "package-lock.json"))
    if o.python:
        bad += python()
    for b in sorted(set(bad)):
        print(f"not permissive and not accepted here: {b}")
    if bad:
        print("Use something under a permissive licence, or write it yourself. Never copy from one of these.")
        return 1
    print("licences hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
