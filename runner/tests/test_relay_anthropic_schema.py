"""The relay repairs a tool schema Anthropic refuses, for every backend that rides it.

Anthropic accepts no combinator at an input_schema's ROOT. Measured 2026-09-29 against
ai-gateway.vercel.sh: a grok turn on any claude id died before inference with
`tools.14.custom.input_schema: input_schema does not support oneOf, allOf, or anyOf at the top
level` — grok's `use_tool` declares a root `oneOf` over its three call forms. The catalog offered
nine claude ids that could not run at all (harness-verification rule 4).

These pin the repair itself rather than any one backend: it is in the shared relay, so a root
combinator from ANY base is flattened, and a schema without one comes back byte-identical.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (_anthropic_family, _anthropic_tool_schema,  # noqa: E402
                    _with_anthropic_schemas)


USE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {"description": "Discovered MCP target name", "type": "string"},
        "tool_input": {"description": "Inline remote arguments", "type": "object",
                       "additionalProperties": True},
        "tool_input_file": {"description": "UTF-8 JSON file", "type": "string", "minLength": 1},
        "file": {"description": "UTF-8 JSON document", "type": "string", "minLength": 1},
    },
    "oneOf": [
        {"type": "object", "properties": {"tool_name": {"type": "string"}, "tool_input": {"type": "object"}},
         "required": ["tool_name", "tool_input"],
         "not": {"anyOf": [{"required": ["tool_input_file"]}, {"required": ["file"]}]}},
        {"type": "object", "properties": {"tool_name": {"type": "string"}, "tool_input_file": {"type": "string"}},
         "required": ["tool_name", "tool_input_file"],
         "not": {"anyOf": [{"required": ["tool_input"]}, {"required": ["file"]}]}},
        {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"],
         "not": {"anyOf": [{"required": ["tool_name"]}, {"required": ["tool_input"]}]}},
    ],
}


def _has_root_combinator(schema: dict) -> bool:
    return any(k in schema for k in ("oneOf", "anyOf", "allOf"))


def test_the_root_combinator_is_flattened_and_the_call_the_model_makes_stays_declared():
    from server import _anthropic_tool_schema
    assert _has_root_combinator(USE_TOOL_SCHEMA)          # the defect, constructed
    flat = _anthropic_tool_schema(USE_TOOL_SCHEMA)
    assert not _has_root_combinator(flat) and "not" not in flat
    assert flat["type"] == "object"
    # every property a caller may send is still declared, with the root's own description kept
    assert set(flat["properties"]) == {"tool_name", "tool_input", "tool_input_file", "file"}
    assert flat["properties"]["tool_name"]["description"] == "Discovered MCP target name"
    # `required` is what EVERY branch requires — here nothing, because two forms take no tool_name.
    # Demanding one branch's key would refuse the other two forms outright.
    assert "required" not in flat
    assert _has_root_combinator(USE_TOOL_SCHEMA)          # the caller's schema is not mutated


def test_a_required_key_every_branch_shares_survives_the_flattening():
    from server import _anthropic_tool_schema
    schema = {"type": "object", "properties": {"id": {"type": "string"}},
              "anyOf": [{"required": ["id", "a"]}, {"required": ["id", "b"]}]}
    assert _anthropic_tool_schema(schema)["required"] == ["id"]


def test_what_every_call_needs_stays_required_whatever_the_branches_say():
    """The root's own list applies to every shape, every allOf branch applies at once, and of
    alternatives only what all of them demand. A flattening that kept the alternatives' common keys
    alone dropped `path` from a write tool whose content could come two ways."""
    flat = _anthropic_tool_schema({"type": "object", "required": ["path"],
                                   "anyOf": [{"required": ["content"]}, {"required": ["patch"]}]})
    assert flat["required"] == ["path"]
    flat = _anthropic_tool_schema({"allOf": [{"required": ["a"]}, {"required": ["b"]}]})
    assert flat["required"] == ["a", "b"]
    flat = _anthropic_tool_schema({"required": ["id"], "allOf": [{"required": ["a"]}],
                                   "oneOf": [{"required": ["x", "k"]}, {"required": ["y", "k"]}]})
    assert flat["required"] == ["id", "a", "k"]
    flat = _anthropic_tool_schema({"anyOf": [{"required": ["x"]}, {"properties": {"y": {}}}]})
    assert "required" not in flat


def test_a_nested_combinator_is_left_alone_because_anthropic_accepts_it():
    from server import _anthropic_tool_schema
    schema = {"type": "object", "properties": {"n": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}}
    assert _anthropic_tool_schema(schema) == schema


def test_both_wire_shapes_are_repaired_and_an_untouched_body_is_byte_identical():
    import json as _json
    from server import _with_anthropic_schemas
    openai = _json.dumps({"model": "anthropic/claude-haiku-4.5", "messages": [],
                          "tools": [{"type": "function", "function": {"name": "use_tool",
                                                                     "parameters": USE_TOOL_SCHEMA}}]}).encode()
    got = _json.loads(_with_anthropic_schemas(openai))
    assert not _has_root_combinator(got["tools"][0]["function"]["parameters"])
    native = _json.dumps({"model": "claude-haiku-4.5", "messages": [],
                          "tools": [{"name": "use_tool", "input_schema": USE_TOOL_SCHEMA}]}).encode()
    got = _json.loads(_with_anthropic_schemas(native))
    assert not _has_root_combinator(got["tools"][0]["input_schema"])
    clean = _json.dumps({"model": "claude-haiku-4.5", "messages": [],
                         "tools": [{"name": "grep", "input_schema": {"type": "object",
                                                                    "properties": {"q": {"type": "string"}}}}]}).encode()
    assert _with_anthropic_schemas(clean) == clean
    assert _with_anthropic_schemas(b'{"messages": []}') == b'{"messages": []}'


def test_the_family_test_reads_the_vendor_prefixed_id_and_the_bare_one():
    from server import _anthropic_family
    for m in ("claude-haiku-4.5", "anthropic/claude-sonnet-4.6", "CLAUDE-OPUS-5"):
        assert _anthropic_family(m)
    for m in ("", "gemini-3.5-flash", "spacexai/grok-4.6", "gpt-5.4"):
        assert not _anthropic_family(m)


def test_the_repair_is_idempotent_so_the_relays_retry_terminates():
    """The relay repairs on the provider's complaint and sends again; if the second body still
    carried the combinator the loop would burn all three attempts and fail anyway. MEASURED against
    a stub that refuses the shape exactly as Anthropic does: call 1 the session title (1 tool, no
    combinator), call 2 the answer (20 tools, root combinator at index 14) refused, call 3 the same
    request repaired and answered — one extra request, not a ladder."""
    import json as _json
    from server import _with_anthropic_schemas
    body = _json.dumps({"model": "vendor/opus-x", "messages": [],
                        "tools": [{"type": "function", "function": {"name": "use_tool",
                                                                   "parameters": USE_TOOL_SCHEMA}}]}).encode()
    once = _with_anthropic_schemas(body)
    assert once != body
    assert _with_anthropic_schemas(once) == once



def test_the_relay_flattens_a_root_combinator_for_every_model_not_only_claude():
    """OpenAI refuses the same shape Anthropic does. Measured 2026-10-03: grok on gpt-6.1-sol through
    an aggregator that passes the schema on, `Invalid schema for function 'use_tool': schema must
    have type 'object' and not have 'oneOf'/'anyOf'/'allOf'/… at the top level`, on every turn."""
    import http.client, http.server, threading
    import server as rs
    seen = {}

    class Up(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            out = b'{"id":"c","model":"gpt-6.1-sol","choices":[{"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}'
            self.send_response(200); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = http.server.HTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    relay_base, tok = rs._hermes_relay_route(f"http://127.0.0.1:{up.server_port}/v1", "sk-real")
    conn = http.client.HTTPConnection(relay_base.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        conn.request("POST", "/v1/chat/completions", body=json.dumps({
            "model": "openai/gpt-6.1-sol", "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": "use_tool", "parameters": USE_TOOL_SCHEMA}}]}),
            headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        assert conn.getresponse().status == 200
    finally:
        conn.close(); up.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)
    sent = seen["body"]["tools"][0]["function"]["parameters"]
    assert not _has_root_combinator(sent) and sent["type"] == "object"
    assert set(sent["properties"]) == {"tool_name", "tool_input", "tool_input_file", "file"}
