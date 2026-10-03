"""The console's placeholder lists are copies of the gateway's catalog. ui/src/lib/harness.ts carries a
models list and a defaultModel per base for the second or two before the catalog read lands, and
those must be the catalog's own: on 2026-09-27 the placeholder defaults were older than the gateway's
(codex and hermes on gpt-5.5, claude-code on claude-opus-4.8) while the helper read the placeholder
first, and on hosted three entries with no default opened a fresh page on the first entry of a list
that leads with gpt-6-astra. Regenerate the lists from _MODEL_CATALOG when a catalog changes; this
test fails the suite when they drift."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402

HARNESS_TS = Path(__file__).resolve().parents[2] / "ui" / "src" / "lib" / "harness.ts"
ENTRY = re.compile(r"\n  \{ id: '([a-z0-9-]+)', name: '[^']*', version: '[^']*', backend: '([a-z-]+)'(.*?)\n    tools: \[", re.S)


def _entries() -> list[tuple[str, str, list[str], str]]:
    if not HARNESS_TS.exists():
        pytest.skip("the console tree is not beside the gateway here")
    src = HARNESS_TS.read_text()
    body = src[src.index("export const OOB: OobHarness[] = ["):]
    body = body[: body.index("\n];\n")]
    out = []
    for cid, backend, rest in ENTRY.findall(body):
        models = re.search(r"models: \[(.*?)\]", rest, re.S)
        default = re.search(r"defaultModel: '([^']*)'", rest)
        out.append((cid, backend, re.findall(r"'([^']+)'", models.group(1)) if models else [], default.group(1) if default else ""))
    return out


def test_every_base_of_the_catalog_has_one_console_entry():
    entries = _entries()
    assert sorted(b for _, b, _, _ in entries) == sorted(gw._MODEL_CATALOG)


def test_each_placeholder_list_and_default_is_the_catalog_s():
    for cid, backend, models, default in _entries():
        cat = gw._MODEL_CATALOG[backend]
        assert models == cat["models"], cid
        assert default == cat["default"], cid
        assert default in models, cid


def test_the_console_default_helper_reads_the_server_first():
    """`fromServer || o.defaultModel || ''`: the placeholder stands in only until the catalog lands,
    and a list's first entry is never a default."""
    src = HARNESS_TS.read_text()
    assert "return fromServer || o.defaultModel || '';" in src
    assert "oobModels(o)[0]" not in src
