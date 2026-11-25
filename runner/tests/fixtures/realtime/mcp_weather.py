"""A tool server for the realtime driver's tests: a deterministic `weather` tool, a `step` tool that
always asks to be called again, and a `delete_account` tool a harness disables.

    python mcp_weather.py <port>      serves Streamable HTTP at http://127.0.0.1:<port>/mcp
"""
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("realtime-driver-fixture")


@server.tool()
def weather(city: str) -> dict:
    """The current weather in a city."""
    return {"city": city, "sky": "clear", "celsius": 18}


@server.tool()
def step(n: int) -> str:
    """One link of a chain. Call it again with n + 1."""
    return f"link {n} done, call step again with n={n + 1}"


@server.tool()
def delete_account(user: str) -> str:
    """Deletes a user's account."""
    return "deleted"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(server.streamable_http_app(), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
