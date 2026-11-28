"""Schema validation checks for Plugin read/write shapes (#770)."""
from __future__ import annotations

from importlib import resources
import json

import jsonschema

from uhp_conformance import UHP_VERSION

SCHEMA_NAME = f"uhp-{UHP_VERSION}.schema.json"


def _validator(schema: dict, name: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator({"$defs": schema["$defs"], **schema["$defs"][name]})


def test_harness_create_allows_plugin_without_name():
    """Plugins §3: `name` is optional on write, derived from plugin.json."""
    schema = json.loads(resources.files("uhp_conformance").joinpath(SCHEMA_NAME).read_text())
    defs = schema["$defs"]
    assert defs["Harness"]["properties"]["plugins"]["items"]["$ref"] == "#/$defs/Plugin"
    assert defs["HarnessCreate"]["properties"]["plugins"]["items"]["$ref"] == "#/$defs/PluginWrite"

    create_v = _validator(schema, "HarnessCreate")
    # Write with files only (no name) — matches Plugins §3 example
    payload = {
        "name": "Contract Review Agent",
        "base": "claude-code",
        "plugins": [
            {
                "files": [
                    {
                        "path": "plugin.json",
                        "content": '{"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json","name":"contract-review"}',
                    },
                ]
            }
        ],
    }
    assert not list(create_v.iter_errors(payload))

    # Write with blob only (no name)
    assert not list(create_v.iter_errors({"base": "claude-code", "plugins": [{"blob": "plg_123"}]}))

    # Write with explicit valid name
    assert not list(
        create_v.iter_errors({"base": "claude-code", "plugins": [{"name": "contract-review", "blob": "plg_123"}]})
    )

    # Round-tripped read Plugin object is also valid on HarnessCreate
    round_trip = {
        "name": "contract-review",
        "enabled": True,
        "blob": "plg_123",
        "manifest": {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "contract-review",
        },
        "mcpServers": [],
        "skills": [],
        "skipped": [],
    }
    assert not list(create_v.iter_errors({"base": "claude-code", "plugins": [round_trip]}))

    # When name is sent on write, pattern is still enforced
    assert list(create_v.iter_errors({"base": "claude-code", "plugins": [{"name": "Bad_Name", "blob": "plg_123"}]}))


def test_harness_and_plugin_read_still_require_name():
    schema = json.loads(resources.files("uhp_conformance").joinpath(SCHEMA_NAME).read_text())
    assert "name" in schema["$defs"]["Plugin"]["required"]

    plugin_v = _validator(schema, "Plugin")
    harness_v = _validator(schema, "Harness")

    assert not list(plugin_v.iter_errors({"name": "contract-review"}))
    assert list(plugin_v.iter_errors({"files": [{"path": "plugin.json", "content": "{}"}]}))

    assert not list(
        harness_v.iter_errors(
            {"id": "chrn_123", "name": "H", "base": "claude-code", "plugins": [{"name": "contract-review"}]}
        )
    )
    assert list(
        harness_v.iter_errors(
            {"id": "chrn_123", "name": "H", "base": "claude-code", "plugins": [{"blob": "plg_123"}]}
        )
    )
