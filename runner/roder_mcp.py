"""Expose MCP tools through Roder's externalTools; each SDK session owns its task scopes."""
import asyncio
import os
import re
from contextlib import AsyncExitStack

DETACHED = ("This tool is not available in this turn: its MCP server could not be reached, "
            "or the tool was switched off.")


def stdio_env(server):
    """A stdio server's environment: the turn's, without the runner's own HR_ names (the turn's
    relay token, and the driver's job if it were still there), then the server's declared env. The
    job carries every other server's bearer headers and env, and the relay token is the turn's
    provider credential: neither is a stdio server's to read."""
    inherited = {k: v for k, v in os.environ.items() if not k.upper().startswith("HR_")}
    return {**inherited, **{str(k): str(v) for k, v in (server.get("env") or {}).items()}}


async def serve(server, ready, queue):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamablehttp_client
    try:
        if server.get("command"):
            transport = stdio_client(StdioServerParameters(command=server["command"],
                args=server.get("args") or [], env=stdio_env(server)))
        else:
            headers = dict(server.get("headers") or {})
            transport = (sse_client(server["url"], headers=headers, timeout=90)
                if server.get("transport") == "sse" else
                streamablehttp_client(server["url"], headers=headers, timeout=90))
        async with AsyncExitStack() as stack:
            streams = await stack.enter_async_context(transport)
            session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
            await session.initialize()
            tools, cursor = [], None
            while True:
                page = await session.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.nextCursor
                if not cursor:
                    break
            ready.set_result(tools)
            while True:
                name, arguments, future = await queue.get()
                try:
                    result = await session.call_tool(name, arguments)
                    future.set_result({"output": result.model_dump_json(), "isError": bool(result.isError)})
                except Exception:
                    future.set_result({"output": "MCP tool call failed", "isError": True})
    except Exception:
        if not ready.done():
            ready.set_exception(RuntimeError("MCP discovery failed"))
        raise


class Mcp:
    def __init__(self):
        self.tasks = []
        self.tools = []
        self.calls = {}
        self.servers = {}     # wire tool name -> the MCP server it came from, by its harness name

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def connect(self, servers, disabled, emit):
        for index, server in enumerate(servers):
            name = server.get("name") or f"server{index}"
            ready = asyncio.get_running_loop().create_future()
            queue = asyncio.Queue()
            task = asyncio.create_task(serve(server, ready, queue))
            self.tasks.append(task)
            try:
                tools = await asyncio.wait_for(ready, 30)
            except Exception:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                # Exceptions may contain bearer values or URL queries; publish the name only.
                emit({"type": "system", "subtype": "mcp_unavailable", "servers": [{"name": name}]})
                continue
            for tool in tools:
                wire = "mcp__" + re.sub(r"[^a-zA-Z0-9_]", "_", name) + "__" + tool.name
                if wire in disabled:
                    continue
                if wire in self.calls:
                    raise RuntimeError("duplicate MCP tool name")
                self.tools.append({"name": wire, "description": tool.description or "",
                                   "parameters": tool.inputSchema})
                self.calls[wire] = (queue, task, tool.name)
                self.servers[wire] = name

    async def call(self, call):
        # A resumed thread keeps the external tools it started with (roder_driver.run); one that is
        # not attached this turn is answered, never left to fail the turn.
        if call.get("name") not in self.calls:
            return {"output": DETACHED, "isError": True}
        queue, task, name = self.calls[call["name"]]
        if task.done():
            return {"output": "MCP server disconnected", "isError": True}
        future = asyncio.get_running_loop().create_future()
        await queue.put((name, call.get("arguments") or {}, future))
        return await asyncio.wait_for(asyncio.shield(future), 90)
