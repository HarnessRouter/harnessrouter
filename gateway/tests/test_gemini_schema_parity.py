"""The Gemini tool-schema repair and the thought-signature reader exist twice: in the runner's
relay (runner/server.py) and on the gateway's API front (gateway/app.py). The DeepSeek Harness
driver had a third copy in a relay of its own until its model calls rode the runner's (#382).
Until there is one implementation, one corpus goes through both and the answers must agree, so a
repair made in one copy fails here until it is made in the other.

It already had: the nullable-enum repair ({"type": ["string", "null"], "enum": [..., null]}, refused
whole by Google's validator, 2026-09-27) was in the runner's copy only, so a dsh turn or a gateway
tool declaration carrying grok's todo_write status still sent the null member to Google.
"""
import copy
import json
import os
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "gateway"))
sys.path.insert(0, str(_ROOT / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app  # noqa: E402
import server  # noqa: E402

COPIES = {"runner relay": server, "gateway": app}

SCHEMAS = [
    # the shapes each repair in _gemini_schema exists for
    {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "additionalProperties": False,
     "properties": {"p": {"type": "string"}}, "required": ["p", "gone"]},
    {"type": "object", "properties": {"mode": {"oneOf": [{"const": "a"}, {"const": "b"}]}}},
    {"type": "object", "properties": {"n": {"type": "integer", "exclusiveMinimum": 0, "exclusiveMaximum": 9}}},
    {"type": "object", "properties": {"tag": {"type": ["string", "null"]}}},
    {"anyOf": [{"type": "integer"}, {"type": "null"}], "description": "line"},
    {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}], "description": "either"},
    {"anyOf": [{"type": "string", "enum": ["x"]}, {"type": "string", "enum": ["y"]}]},
    {"anyOf": [{"type": "null"}]},
    {"type": ["string", "null"], "enum": ["pending", "in_progress", "completed", None]},   # grok's todo_write status
    {"enum": [None]},
    {"type": "object", "properties": {}},
    {"type": "array"},
    {"type": "array", "items": [{"type": "integer"}]},
    {"type": "array", "items": []},
    {"description": "no type at all"},
    {"properties": {"a": {"items": {"type": "string"}}}},
    {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["y"]},
]


def _answers(fn, *args):
    out = {}
    for name, mod in COPIES.items():
        out[name] = getattr(mod, fn)(*copy.deepcopy(args))
    return out


@pytest.mark.parametrize("schema", SCHEMAS, ids=[str(i) for i in range(len(SCHEMAS))])
def test_every_copy_normalises_a_schema_the_same_way(schema):
    got = _answers("_gemini_schema", schema)
    assert got["gateway"] == got["runner relay"], got


def test_every_copy_rewrites_a_request_body_the_same_way():
    tools = [{"type": "function", "function": {"name": f"t{i}", "parameters": s}} for i, s in enumerate(SCHEMAS)]
    body = json.dumps({"model": "google/gemini-3.8-flash", "messages": [{"role": "user", "content": "hi"}],
                       "tools": tools}).encode()
    got = {k: json.loads(v) for k, v in _answers("_with_gemini_schemas", body).items()}
    assert got["gateway"] == got["runner relay"]
    plain = b'{"model": "google/gemini-3.8-flash", "messages": []}'
    for name, mod in COPIES.items():
        assert mod._with_gemini_schemas(plain) == plain, name


SIGNATURE_DOCS = [
    {"choices": [{"delta": {"tool_calls": [{"id": "call_1", "extra_content": {"google": {"thought_signature": "sigA"}}}]}}]},
    {"choices": [{"message": {"tool_calls": [{"id": "call_2", "extra_content": {"google": {"thought_signature": "sigB"}}},
                                             {"id": "call_3"}]}}]},
    {"choices": [{"delta": {"tool_calls": [{"id": "", "extra_content": {"google": {"thought_signature": "s"}}},
                                           {"id": "call_4", "extra_content": {"google": {"thought_signature": ""}}},
                                           {"id": "call_5", "extra_content": "not a dict"}, "not a call"]}}]},
    {"choices": ["not a choice", {"delta": "not a dict"}]},
    {},
]


@pytest.mark.parametrize("doc", SIGNATURE_DOCS, ids=[str(i) for i in range(len(SIGNATURE_DOCS))])
def test_every_copy_reads_the_same_thought_signatures(doc):
    got = _answers("_google_signatures_in", doc)
    assert got["gateway"] == got["runner relay"], got


def test_a_nullable_enum_loses_its_null_member_in_every_copy():
    for name, mod in COPIES.items():
        out = mod._gemini_schema({"type": ["string", "null"], "enum": ["a", None]})
        assert out == {"type": "string", "enum": ["a"], "nullable": True}, (name, out)
