"""Checks for `protocol/schema/build.py` and the generated 2026-10-19 JSON Schema (#768)."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCHEMA_DIR = _ROOT / "protocol" / "schema"
sys.path.insert(0, str(_SCHEMA_DIR))
import build  # noqa: E402 - protocol/schema/build.py


_EXPECTED_DESCRIPTIONS = {
    ("PluginSkill", "name"): "The SKILL.md frontmatter name, equal to the directory name.",
    ("HarnessCreate", "environment"): (
        "An environment id of the caller's scope, or empty. Requires the `environments` capability."
    ),
    ("Base", "statusReason"): (
        "Why the base is not ready, in words. Present only when `status` is not `ready`."
    ),
    ("BaseModel", "available"): "Computed, as on `Model`.",
    ("OutputItem", "arguments"): "JSON, as a string",
    ("Environment", "version"): "The active build, the one sessions read; null until one is ready.",
    ("EnvironmentFileList", "count"): "Files, not directories.",
    ("EnvironmentImportResult", "skipped"): (
        "Members that must not land (links, escapes) and were dropped."
    ),
    ("Session", "environment"): "The environment the session's turns read, when one did.",
}


def test_generated_schema_has_no_null_valued_keys():
    doc = build.build()
    assert build.find_null_keys(doc) == []


def test_previously_truncated_descriptions_are_complete():
    doc = json.loads(build.OUT.read_text())
    defs = doc["$defs"]
    for (defn, prop), expected in _EXPECTED_DESCRIPTIONS.items():
        props = defs[defn]["properties"][prop]
        assert props["description"] == expected
        assert not any(v is None for v in props.values()), f"{defn}.{prop} has null-valued keys: {props}"


def test_build_rejects_null_valued_keys_from_unquoted_flow_mapping(tmp_path):
    bad = tmp_path / "bad.openapi.yaml"
    bad.write_text(
        "components:\n"
        "  schemas:\n"
        "    Session:\n"
        "      type: object\n"
        "      properties:\n"
        "        environment: { type: string, description: Read at turn start, when set. }\n"
    )
    with pytest.raises(ValueError, match=r"when set\."):
        build.build(bad)

    good = tmp_path / "good.openapi.yaml"
    good.write_text(
        "components:\n"
        "  schemas:\n"
        "    Session:\n"
        "      type: object\n"
        "      properties:\n"
        '        environment: { type: string, description: "Read at turn start, when set." }\n'
    )
    doc = build.build(good)
    assert doc["$defs"]["Session"]["properties"]["environment"]["description"] == "Read at turn start, when set."


def test_build_main_exits_nonzero_on_null_key(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.openapi.yaml"
    bad.write_text(
        "components:\n"
        "  schemas:\n"
        "    Item:\n"
        "      properties:\n"
        "        note: { type: string, description: One, two. }\n"
    )
    monkeypatch.setattr(build, "SRC", bad)
    monkeypatch.setattr(build, "OUT", tmp_path / "out.schema.json")
    monkeypatch.setattr(sys, "argv", ["build.py", "--check"])
    assert build.main() == 1
    assert "two." in capsys.readouterr().err


def test_schema_matches_build_and_conformance_bundle():
    built = json.dumps(build.build(), indent=2, ensure_ascii=False) + "\n"
    assert build.OUT.read_text() == built
    bundled = _ROOT / "protocol" / "conformance" / "uhp_conformance" / build.OUT.name
    assert bundled.read_bytes() == build.OUT.read_bytes()
