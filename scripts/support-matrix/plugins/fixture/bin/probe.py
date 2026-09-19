#!/usr/bin/env python3
"""A minimal MCP stdio server with one tool, plugin_probe(note) -> "PLUGIN_MCP_OK".

Speaks the protocol by hand (JSON-RPC 2.0, one message per line) so it depends on nothing
but python3, whatever SDK version the client brings."""
import json
import sys

TOOL = {"name": "plugin_probe", "description": "The support matrix's probe tool. Returns a fixed token.",
        "inputSchema": {"type": "object", "properties": {"note": {"type": "string"}}}}


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
        reply(i, {"tools": [TOOL]})
    elif m == "tools/call":
        reply(i, {"content": [{"type": "text", "text": "PLUGIN_MCP_OK"}], "isError": False})
    elif m == "ping":
        reply(i, {})
    elif i is not None:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i,
                                     "error": {"code": -32601, "message": f"unknown method {m}"}}) + "\n")
        sys.stdout.flush()
