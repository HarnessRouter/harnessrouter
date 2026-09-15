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
    remote = sse_client(url, headers=headers or None) if transport == "sse" else streamablehttp_client(url, headers=headers or None)
    async with remote as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            init = await session.initialize()
            caps = init.capabilities
            server = Server(init.serverInfo.name if init.serverInfo else "bridge")

            @server.list_tools()
            async def list_tools() -> list[types.Tool]:
                return (await session.list_tools()).tools

            @server.call_tool()
            async def call_tool(name: str, arguments: dict | None) -> types.CallToolResult:
                # The remote result travels whole: a tool that declares an output schema answers
                # with structured content too, and the SDK on this side checks for it.
                result = await session.call_tool(name, arguments or {})
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
