"""The MCP server the plugin checks point a plugin at, shipped with the suite.

A streamable-HTTP MCP server with three tools. `uhp_echo` answers with a function of its input
(`fixture_answer`), so a conformance run can prove an agent called it: the answer cannot be
produced without the call. `uhp_time` says what time the fixture thinks it is, for a human at the
other end of a debugging session. `uhp_steps` answers with the step of a chain it is on and asks
for the next one, so a caller that follows it makes the chain's calls.

Run it anywhere a host under test can reach: `uhp-conformance-fixture --host 0.0.0.0 --port 8080`
serves at http://<host>:8080/mcp, and `uhp-conformance --plugin-mcp-url <that>` points a run at
it. The public copy the suite defaults to is the same code (protocol/conformance/fixture/).
"""
from __future__ import annotations

import argparse
import datetime as _dt

TOOL_NAME = "uhp_echo"
PREFIX = "UHP-FIXTURE:"
STEP_TOOL_NAME = "uhp_steps"
STEP_COUNT = 3
# How many chains a long-lived fixture remembers at once. A run cut short by a budget leaves its
# entry behind, so the dict is bounded and the oldest entries go when it grows past this.
STEP_CACHE_MAX = 1024


def fixture_answer(text: str) -> str:
    """What `uhp_echo` returns for `text`: the prefix and the text reversed."""
    return PREFIX + str(text)[::-1]


def step_answer(step: int, nonce: str, steps: int = STEP_COUNT) -> str:
    """What `uhp_steps` returns for `step`: the step it is on, and a request for the next one."""
    text = f"{PREFIX} step {step} of {steps}"
    if step < steps:
        return f"{text}; call {STEP_TOOL_NAME} again to continue"
    return f"{text}; the chain is done"


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

    # The chain is counted per nonce, so two runs against one shared fixture do not share a
    # counter. The entry is dropped when the chain COMPLETES; a run cut short by a budget leaves
    # its entry behind, so the dict is bounded and the oldest chains go when it grows too big.
    steps: dict[str, int] = {}

    @server.tool(name=STEP_TOOL_NAME, description="Count one step of a chain: the answer names the "
                                                 "step it is on and asks for the next one, so a "
                                                 "caller that follows it makes the chain's calls.")
    def uhp_steps(nonce: str) -> str:
        step = steps.get(nonce, 0) + 1
        if step >= STEP_COUNT:
            steps.pop(nonce, None)
        else:
            steps[nonce] = step
        while len(steps) > STEP_CACHE_MAX:
            steps.pop(next(iter(steps)))
        return step_answer(step, nonce)

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
