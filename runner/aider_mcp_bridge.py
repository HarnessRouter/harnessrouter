"""aider's MCP client, built on the official Model Context Protocol Python SDK.

aider ships no MCP client of any kind — `grep -rniE "\\bmcp\\b"` over the whole 0.86.2 tree returns
nothing. Rather than record the capability as missing, the harness brings one and lets the model
reach it through the ONE tool surface aider has: a shell command it proposes in a fenced block.

WHY NOT f/mcptools, which was the first choice: it is a Go program that publishes NO binaries on any
release (checked every release through v0.7.1 — all have zero assets), so installing it would mean
adding a Go toolchain to a python:3.12-slim image for one command. The official `mcp` SDK is MIT,
pip-installable, and goes straight into the venv aider already needs. It is also the more defensible
"well-known open source component": the protocol's own reference implementation rather than a third
party's wrapper around it.

Invoked as `hr-mcp`, a shim the turn builder writes into the workspace and puts on PATH:

    hr-mcp tools <server>
    hr-mcp call <server> <tool> --params '{"key": "value"}'

Servers are named, not URL'd, so the model cannot invent an endpoint: the names and their targets
come from the harness's own configuration, written beside this file as aider-mcp.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys


def _load(config: str) -> dict:
    try:
        data = json.loads(pathlib.Path(config).read_text())
    except Exception as exc:  # noqa: BLE001
        print(f"hr-mcp: cannot read its server list ({exc})", file=sys.stderr)
        raise SystemExit(2)
    return data.get("mcpServers") or {}


def _target(servers: dict, name: str):
    entry = servers.get(name)
    if entry is None:
        known = ", ".join(sorted(servers)) or "none are configured"
        print(f"hr-mcp: no MCP server named {name!r} (known: {known})", file=sys.stderr)
        raise SystemExit(2)
    url = (entry.get("url") or "").strip()
    if url:
        return url
    cmd = entry.get("command")
    if cmd:
        from mcp import StdioServerParameters
        return StdioServerParameters(command=cmd, args=[str(a) for a in (entry.get("args") or [])],
                                     env=entry.get("env") or None)
    print(f"hr-mcp: server {name!r} has neither a url nor a command", file=sys.stderr)
    raise SystemExit(2)


def _render(result) -> str:
    """A CallToolResult as text the agent can read. Structured content wins when present, because a
    tool that returns data should not be flattened into prose."""
    # FIELD NAMES ARE snake_case IN THE 2.2.0 SDK — structured_content, is_error, input_schema —
    # not the camelCase of older releases. Read off mcp.types.Tool/CallToolResult.model_fields
    # against the pinned version, after the camelCase guess silently produced an AttributeError
    # inside a TaskGroup and came out as an unreadable ExceptionGroup.
    structured = getattr(result, "structured_content", None)
    if structured:
        return json.dumps(structured, indent=2, default=str)
    parts = []
    for block in (getattr(result, "content", None) or []):
        text = getattr(block, "text", None)
        parts.append(text if text is not None else json.dumps(
            getattr(block, "model_dump", lambda: str(block))(), default=str))
    return "\n".join(p for p in parts if p)


async def _run(args) -> int:
    # The SDK's high-level Client takes a URL string or StdioServerParameters and picks the
    # transport itself (mode="auto"), so streamable HTTP needs no special casing here.
    from mcp.client.client import Client

    servers = _load(args.config)
    target = _target(servers, args.server)
    async with Client(target, raise_exceptions=False) as client:
        if args.command == "tools":
            listed = await client.list_tools()
            for tool in listed.tools:
                desc = (tool.description or "").strip().splitlines()
                print(f"{tool.name}: {desc[0] if desc else ''}")
                print(f"    params: {json.dumps(tool.input_schema or {}, default=str)}")
            return 0
        result = await client.call_tool(args.tool, args.parsed_params)
        print(_render(result))
        # A tool that reports failure must exit non-zero, so the agent sees a failed command rather
        # than an answer-shaped one.
        return 1 if getattr(result, "is_error", False) else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hr-mcp", description="Call MCP tools from the shell.")
    p.add_argument("--config", default=".harness/aider-mcp.json")
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tools", help="list a server's tools")
    t.add_argument("server")
    c = sub.add_parser("call", help="call one tool")
    c.add_argument("server")
    c.add_argument("tool")
    c.add_argument("--params", default="")
    args = p.parse_args(argv)
    # Validate BEFORE anything is imported or connected: a malformed --params is the agent's
    # mistake, and it should be told that in one line rather than shown whatever the import or the
    # network failed with first.
    args.parsed_params = {}
    if args.command == "call":
        try:
            args.parsed_params = json.loads(args.params) if args.params else {}
        except json.JSONDecodeError as exc:
            print(f"hr-mcp: --params is not valid JSON ({exc})", file=sys.stderr)
            return 2
        if not isinstance(args.parsed_params, dict):
            print("hr-mcp: --params must be a JSON object", file=sys.stderr)
            return 2
    try:
        return asyncio.run(_run(args))
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — the agent reads stderr; a traceback helps nobody
        # anyio runs the transport in a TaskGroup, so a failure arrives wrapped in an ExceptionGroup
        # whose own str() says only "unhandled errors in a TaskGroup (1 sub-exception)". Unwrap it,
        # or every MCP failure reaches the agent as that same useless sentence.
        for inner in getattr(exc, "exceptions", None) or [exc]:
            print(f"hr-mcp: {type(inner).__name__}: {inner}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
