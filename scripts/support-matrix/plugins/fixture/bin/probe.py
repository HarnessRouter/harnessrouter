#!/usr/bin/env python3
"""A minimal MCP stdio server with two tools: plugin_probe(note) -> "PLUGIN_MCP_OK", and
probe_rows(rows), which answers "PLUGIN_ROWS_OK" only when the rows it was handed are the two the
matrix asks for.

Speaks the protocol by hand (JSON-RPC 2.0, one message per line) so it depends on nothing
but python3, whatever SDK version the client brings."""
import json
import sys

TOOL = {"name": "plugin_probe", "description": "The support matrix's probe tool. Returns a fixed token.",
        "inputSchema": {"type": "object", "properties": {"note": {"type": "string"}}}}
# A list of FREE-FORM objects, declared the way a tool author writes one: `items: {"type": "object"}`
# and nothing more. Several clients add an empty `properties` to such a node before the provider
# sees it, and some providers then let the model fill nothing in: the rows arrived as [{}, {}] or
# [] (measured 2026-10-05). The tool says what it received, so a lost argument cannot read as a pass.
ROWS = [{"label": "first", "score": 1}, {"label": "second", "score": 2}]
ROWS_TOOL = {"name": "probe_rows", "description": "The support matrix's probe for a list of objects. Says whether the rows arrived whole.",
             "inputSchema": {"type": "object", "required": ["rows"],
                             "properties": {"rows": {"type": "array", "description": "Row objects", "items": {"type": "object"}}}}}


def rows_answer(args) -> str:
    got = (args or {}).get("rows")
    if got == ROWS:
        return "PLUGIN_ROWS_OK first=1 second=2"
    return "PLUGIN_ROWS_LOST the tool received " + json.dumps(got)[:300]


def reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    m, i = msg.get("method"), msg.get("id")
    if m == "initialize":
        reply(i, {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "probe", "version": "1.0.0"}})
    elif m == "tools/list":
        reply(i, {"tools": [TOOL, ROWS_TOOL]})
    elif m == "tools/call":
        params = msg.get("params") or {}
        text = rows_answer(params.get("arguments")) if params.get("name") == "probe_rows" else "PLUGIN_MCP_OK"
        reply(i, {"content": [{"type": "text", "text": text}], "isError": False})
    elif m == "ping":
        reply(i, {})
    elif i is not None:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i,
                                     "error": {"code": -32601, "message": f"unknown method {m}"}}) + "\n")
        sys.stdout.flush()
