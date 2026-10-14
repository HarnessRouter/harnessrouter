#!/usr/bin/env python3
"""A remote MCP server, spoken to over stdio.

Every agent CLI in the image launches a stdio MCP server; not every one speaks the remote
transports (goose 1.50 and dsh's client have no SSE transport, codex takes streamable HTTP only).
Rather than leave such a server out for that client, the runner hands it this bridge as a stdio
server: the bridge connects to the remote end with the transport it names and forwards the tools,
resources and prompts unchanged. One process per server per turn, started by the client, gone
with it.

    HR_MCP_URL        the remote endpoint
    HR_MCP_TRANSPORT  sse (default) or http (streamable HTTP)
    HR_MCP_HEADERS    JSON object of request headers (Authorization and the rest)
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


def declared_only(schema: dict | None, arguments: dict) -> dict:
    """The arguments a CLOSED tool schema declares, and nothing a model added beside them.

    jcode's own tools all take an `intent` argument, and a model working in jcode writes one into
    remote tools' calls too. The browser's tools are closed (additionalProperties false), so this
    bridge's own input check refused them ("Input validation error: Additional properties are not
    allowed ('intent' was unexpected)"): three refused browser calls in one jcode turn on gpt-5.4
    before the model looked the schema up and left it out (review instance, 2026-10-14), and on
    hosted the agent answered without the browser (gpt-5.4 and claude-sonnet-5). An argument the
    tool never declared carries nothing it reads, so it is left out; whether the rest is right is
    the remote server's call, not this bridge's."""
    if (not isinstance(schema, dict) or schema.get("additionalProperties") is not False
            or not isinstance(schema.get("properties"), dict)):
        return arguments
    return {k: v for k, v in arguments.items() if k in schema["properties"]}


async def main() -> int:
    url = os.environ.get("HR_MCP_URL", "")
    if not url:
        print("HR_MCP_URL is not set", file=sys.stderr)
        return 2
    transport = (os.environ.get("HR_MCP_TRANSPORT") or "sse").lower()
    try:
        headers = json.loads(os.environ.get("HR_MCP_HEADERS") or "{}")
    except json.JSONDecodeError:
        headers = {}
    # 90 s per request and 600 s on the event stream, not the SDK's 5 s and 30 s: the plugs plane
    # caps a call at 60 s and a takeover holds one 45 s; under load a browser call and even the
    # tool listing timed out (hosted, omp and aider, 2026-09-28).
    remote = (sse_client(url, headers=headers or None, timeout=90, sse_read_timeout=600) if transport == "sse"
              else streamablehttp_client(url, headers=headers or None, timeout=90, sse_read_timeout=600))
    async with remote as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            init = await session.initialize()
            caps = init.capabilities
            server = Server(init.serverInfo.name if init.serverInfo else "bridge")
            schemas: dict[str, dict] = {}

            @server.list_tools()
            async def list_tools() -> list[types.Tool]:
                tools = (await session.list_tools()).tools
                schemas.update({t.name: t.inputSchema or {} for t in tools})
                return tools

            # The remote server judges a call's arguments; this bridge only leaves out what a closed
            # schema never declared (declared_only), so its own check is off.
            @server.call_tool(validate_input=False)
            async def call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
                # The remote result travels whole: a tool that declares an output schema answers
                # with structured content too, and the SDK on this side checks for it.
                if name not in schemas:      # a client that calls before it lists: learn the schemas once
                    schemas.update({t.name: t.inputSchema or {} for t in (await session.list_tools()).tools})
                result = await session.call_tool(name, declared_only(schemas.get(name), arguments or {}))
                return types.CallToolResult(content=result.content, structuredContent=result.structuredContent,
                                            isError=bool(result.isError))

            if caps.resources:
                @server.list_resources()
                async def list_resources() -> list[types.Resource]:
                    return (await session.list_resources()).resources

                @server.read_resource()
                async def read_resource(uri):
                    got = await session.read_resource(uri)
                    return [types.ReadResourceContents(content=c.text if isinstance(c, types.TextResourceContents) else c.blob,
                                                       mime_type=c.mimeType) for c in got.contents]

            if caps.prompts:
                @server.list_prompts()
                async def list_prompts() -> list[types.Prompt]:
                    return (await session.list_prompts()).prompts

                @server.get_prompt()
                async def get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
                    return await session.get_prompt(name, arguments or {})

            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
