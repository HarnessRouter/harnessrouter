"""A free-form object in a tool's arguments must reach the tool with its contents.

A tool author writes a list of free-form objects as `items: {"type": "object"}`. Hermes and opencode
add an empty `properties` to every object node before the provider sees it, and with that key
present some gateways let the model fill nothing in. Measured 2026-10-05, one tool call per cell, two
repetitions, the model asked to pass two specific rows:

    items shape                                            Vercel+OpenAI  Vercel/TokenRouter+kimi-k3  OpenRouter+OpenAI
    {"type":"object"}                                       intact         intact                      intact
    {"type":"object","properties":{}}                       [{}, {}]       []                          [{}, {}]
    {"type":"object","properties":{},"additionalProperties":true}   intact  intact                      [{}, {}]
    {"type":"object","additionalProperties":true}           intact         intact                      intact

The two shapes WITHOUT an empty `properties` were intact in every cell: eleven model families on two
aggregators, OpenRouter, and OpenAI, Azure and Google directly. So the relay drops an empty
`properties` from every nested object node, for every model. End to end before the repair, on
gpt-5.4 through Vercel, an MCP tool that reports what it received said "[{}, {}]" on hermes and on
opencode (scripts/support-matrix/plugins, the `rows` column).
"""
import http.client
import http.server
import json
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import _with_free_form_objects  # noqa: E402


def _tool(params: dict) -> dict:
    return {"type": "function", "function": {"name": "insert_rows", "parameters": params}}


def _params(body: bytes, i: int = 0) -> dict:
    return json.loads(body)["tools"][i]["function"]["parameters"]


def test_an_empty_properties_leaves_every_nested_object_and_nothing_else_changes():
    body = json.dumps({"model": "m", "messages": [], "tools": [_tool({
        "type": "object", "required": ["table", "rows"],
        "properties": {
            "table": {"type": "string"},
            "rows": {"type": "array", "items": {"type": "object", "properties": {}}},
            "values": {"type": "object", "properties": {}, "additionalProperties": True, "description": "Columns to set"},
            "where": {"anyOf": [{"type": "object", "properties": {}}, {"type": "null"}]},
            "point": {"type": "object", "properties": {"x": {"type": "number"},
                                                       "meta": {"type": "object", "properties": {}}}},
        }})]}).encode()
    p = _params(_with_free_form_objects(body))
    assert p["properties"]["rows"]["items"] == {"type": "object"}
    assert p["properties"]["values"] == {"type": "object", "additionalProperties": True, "description": "Columns to set"}
    assert p["properties"]["where"]["anyOf"][0] == {"type": "object"}
    assert p["properties"]["point"]["properties"]["meta"] == {"type": "object"}
    assert set(p["properties"]["point"]["properties"]) == {"x", "meta"}      # a node with real properties keeps them
    assert p["required"] == ["table", "rows"] and p["properties"]["table"] == {"type": "string"}


def test_the_root_of_a_tool_that_takes_no_arguments_keeps_its_shape():
    """`parameters: {"type": "object", "properties": {}}` is how a tool with no arguments is written,
    and several validators want `properties` on the root. Only nested nodes are touched."""
    body = json.dumps({"model": "m", "messages": [], "tools": [_tool({"type": "object", "properties": {}})]}).encode()
    assert _with_free_form_objects(body) == body


def test_a_body_without_the_shape_comes_back_byte_identical():
    for doc in ({"model": "m", "messages": [{"role": "user", "content": 'say "properties": {}'}]},
                {"model": "m", "messages": [], "tools": [_tool({"type": "object", "properties": {
                    "rows": {"type": "array", "items": {"type": "object"}}}})]},
                {"model": "m", "messages": [], "tools": "not a list"}):
        body = json.dumps(doc).encode()
        assert _with_free_form_objects(body) is body
    assert _with_free_form_objects(b"not json") == b"not json"


def test_the_relay_sends_the_repaired_schema_for_any_model():
    seen = {}

    class Up(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            out = b'{"id":"c","model":"m","choices":[{"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}'
            self.send_response(200); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = http.server.HTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    relay_base, tok = rs._hermes_relay_route(f"http://127.0.0.1:{up.server_port}/v1", "sk-real")
    conn = http.client.HTTPConnection(relay_base.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        for model in ("openai/gpt-5.4", "moonshotai/kimi-k3", "anthropic/claude-haiku-4.5"):
            conn.request("POST", "/v1/chat/completions", body=json.dumps({
                "model": model, "messages": [{"role": "user", "content": "hi"}],
                "tools": [_tool({"type": "object", "properties": {
                    "rows": {"type": "array", "items": {"type": "object", "properties": {}}}}})]}),
                headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
            resp = conn.getresponse(); resp.read()
            assert resp.status == 200
            sent = seen["body"]["tools"][0]["function"]["parameters"]
            assert sent["properties"]["rows"]["items"] == {"type": "object"}, model
    finally:
        conn.close(); up.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)


def test_hermes_on_openrouter_rides_the_relay_so_the_repair_reaches_it():
    """hermes went to OpenRouter directly, with the connection's key in its environment, and that is
    the one route where neither spelling with an empty `properties` survives an OpenAI model."""
    import tempfile
    d = tempfile.mkdtemp(); env = {"HOME": d}
    rs._hermes_prepare_env("openrouter", rs.Auth(api_key="sk-or-real", base_url="https://openrouter.ai/api/v1"), d, env,
                           model="openai/gpt-5.4")
    assert env["OPENROUTER_API_KEY"].startswith("hr-relay-") and "sk-or-real" not in json.dumps(env)
    assert env["OPENROUTER_BASE_URL"].startswith("http://127.0.0.1:") and env["OPENROUTER_BASE_URL"].endswith("/v1")
    upstream, key, _flags = rs._HERMES_RELAY["routes"][env["OPENROUTER_API_KEY"]]
    assert upstream == "https://openrouter.ai/api/v1" and key == "sk-or-real"
    rs._HERMES_RELAY["routes"].pop(env["OPENROUTER_API_KEY"], None)
    # a connection saved without a base url still gets a route, to OpenRouter's own address
    env2 = {"HOME": tempfile.mkdtemp()}
    rs._hermes_prepare_env("openrouter", rs.Auth(api_key="sk-or-real"), env2["HOME"], env2, model="openai/gpt-5.4")
    assert rs._HERMES_RELAY["routes"][env2["OPENROUTER_API_KEY"]][0] == "https://openrouter.ai/api/v1"
    rs._HERMES_RELAY["routes"].pop(env2["OPENROUTER_API_KEY"], None)
