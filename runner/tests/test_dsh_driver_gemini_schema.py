"""Gemini tool declarations through TokenRouter's channels, normalised by the dsh relay (2026-09-06)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402


# ── Gemini function declarations through TokenRouter (2026-09-06) ─────────────────────────
def test_a_harness_tool_schema_is_normalised_to_googles_subset():
    cline_like = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
                  "properties": {"files": {"type": "array", "items": {"type": "object", "properties": {
                      "path": {"type": "string"}, "end_line": {"description": "line"},
                      "count": {"type": "integer", "exclusiveMinimum": 0},
                      "mode": {"oneOf": [{"const": "a"}, {"const": "b"}]},
                      "tag": {"type": ["string", "null"]}}, "required": ["path", "gone"]}},
                                 "opts": {"type": "object", "properties": {}}, "list": {"type": "array"}},
                  "required": ["files"]}
    out = dsh_driver._gemini_schema(cline_like)
    assert "$schema" not in out and "additionalProperties" not in out
    item = out["properties"]["files"]["items"]
    assert item["properties"]["end_line"] == {"description": "line", "type": "string"}
    assert item["properties"]["count"] == {"type": "integer", "minimum": 0}
    assert item["properties"]["mode"] == {"type": "string", "enum": ["a", "b"]}
    assert item["properties"]["tag"] == {"type": "string", "nullable": True}
    assert item["required"] == ["path"]
    assert out["properties"]["opts"] == {"type": "object"}
    assert out["properties"]["list"] == {"type": "array", "items": {"type": "string"}}


def test_only_tool_parameters_change_and_an_empty_declaration_is_dropped():
    body = json.dumps({"model": "google/gemini-3.8-flash", "messages": [{"role": "user", "content": "hi"}],
                       "tools": [{"type": "function", "function": {"name": "a", "parameters": {"$schema": "x", "type": "object", "properties": {"p": {"type": "string"}}}}},
                                 {"type": "function", "function": {"name": "b", "parameters": {"type": "object", "properties": {}}}}]}).encode()
    out = json.loads(dsh_driver._with_gemini_schemas(body))
    assert out["tools"][0]["function"]["parameters"] == {"type": "object", "properties": {"p": {"type": "string"}}}
    assert "parameters" not in out["tools"][1]["function"]
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    plain = b'{"model": "google/gemini-3.8-flash", "messages": []}'
    assert dsh_driver._with_gemini_schemas(plain) is plain


def test_a_nullable_choice_gets_a_type():
    # zod's optional integer: anyOf [integer, null] with no type; the 3.5-flash channel refuses it without one
    assert dsh_driver._gemini_schema({"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "line"}) == {"type": "integer", "nullable": True, "description": "line"}
    two = dsh_driver._gemini_schema({"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}], "description": "either"})
    assert two == {"type": "string", "nullable": True, "description": "either"}      # no anyOf leaves the relay
    assert dsh_driver._gemini_schema({"anyOf": [{"type": "null"}]}) == {"type": "string", "nullable": True}
