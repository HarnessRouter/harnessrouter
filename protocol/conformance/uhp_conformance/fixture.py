"""The MCP server the plugin checks point a plugin at, shipped with the suite.

A streamable-HTTP MCP server with two tools. `uhp_echo` answers with a function of its input
(`fixture_answer`), so a conformance run can prove an agent called it: the answer cannot be
produced without the call. `uhp_time` says what time the fixture thinks it is, for a human at the
other end of a debugging session.

Run it anywhere a host under test can reach: `uhp-conformance-fixture --host 0.0.0.0 --port 8080`
serves at http://<host>:8080/mcp, and `uhp-conformance --plugin-mcp-url <that>` points a run at
it. The public copy the suite defaults to is the same code (protocol/conformance/fixture/).
"""
from __future__ import annotations

import argparse
import datetime as _dt

TOOL_NAME = "uhp_echo"
PREFIX = "UHP-FIXTURE:"


def fixture_answer(text: str) -> str:
    """What `uhp_echo` returns for `text`: the prefix and the text reversed."""
    return PREFIX + str(text)[::-1]


def build_server(host: str, port: int):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover - the extra is named in the error
        raise SystemExit("the fixture needs the MCP SDK: pip install 'uhp-conformance[fixture]'") from e
    server = FastMCP("uhp-conformance-fixture", host=host, port=port, stateless_http=True)

    @server.tool(name=TOOL_NAME, description="Echo back the text, transformed the way only this "
                                              "fixture does, so a caller can prove the call happened.")
    def uhp_echo(text: str) -> str:
        return fixture_answer(text)

    @server.tool(name="uhp_time", description="The fixture's current UTC time.")
    def uhp_time() -> str:
        return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    return server


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="uhp-conformance-fixture",
                                description="The MCP server the UHP conformance plugin checks point a plugin at.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    a = p.parse_args(argv)
    build_server(a.host, a.port).run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
