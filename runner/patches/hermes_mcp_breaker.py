"""Hermes counts a tool's own error answer as its MCP server failing.

hermes-agent 0.19.0 (tools/mcp_tool.py) bumps the per-server circuit breaker whenever a call's
answer is an error, including an answer a live server gave on purpose (a tool result marked
isError: "no such item"). Three in a row open the breaker, and for 60 s every tool of that server
is refused with "MCP server ... is unreachable": an agent that had read three wrong document ids
could then not comment on a task, and told its person the service was down (seen on the hosted
service, 2026-10-06, and fixed there the same way).

This marks the error answers that came back from the server's own tool result, and lets the
breaker count only failures to reach the server (no session, a transport error, a timeout), which
it already counts where they happen. The text the model reads is unchanged.

Hermes is not in this image (see the Dockerfile's licence note): it is installed on first start,
so the entrypoint applies this to the installed copy on every start, which also repairs a volume
installed before this existed. A source that is not the bytes this was written against is left
alone and said so; nothing is written unless the result compiles.

Usage: python hermes_mcp_breaker.py <path of tools/mcp_tool.py>
Exit: 0 applied or already applied, 3 the source is not the one this was written for, 4 the result
does not compile under the Python it was run with. Nothing is written on 3 or 4.
"""
import sys

MARK = "_hr_tool_error"

TOOL_ERROR = '''                return json.dumps({
                    "error": _sanitize_error(
                        error_text or "MCP tool returned an error"
                    )
                }, ensure_ascii=False)
'''
TOOL_ERROR_NEW = '''                return json.dumps({
                    "error": _sanitize_error(
                        error_text or "MCP tool returned an error"
                    ),
                    "''' + MARK + '''": True,
                }, ensure_ascii=False)
'''

AFTER_CALL = '''            # Check if the MCP tool itself returned an error
            try:
                parsed = json.loads(result)
                if "error" in parsed:
                    _bump_server_error(server_name)
                else:
                    _reset_server_error(server_name)  # success — reset
            except (json.JSONDecodeError, TypeError):
                _reset_server_error(server_name)  # non-JSON = success
            return result
'''
AFTER_CALL_NEW = '''            # Check if the MCP tool itself returned an error
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and parsed.pop("''' + MARK + '''", False):
                    # the server answered: its tool refused this call, the server is not failing
                    _reset_server_error(server_name)
                    return json.dumps(parsed, ensure_ascii=False)
                if "error" in parsed:
                    _bump_server_error(server_name)
                else:
                    _reset_server_error(server_name)  # success — reset
            except (json.JSONDecodeError, TypeError):
                _reset_server_error(server_name)  # non-JSON = success
            return result
'''


class Moved(Exception):
    """The installed source is not the one this patch was written for."""


def patch(src: str) -> str:
    for old in (TOOL_ERROR, AFTER_CALL):
        if src.count(old) != 1:
            raise Moved(f"{src.count(old)} matches of:\n{old}")
    return src.replace(TOOL_ERROR, TOOL_ERROR_NEW).replace(AFTER_CALL, AFTER_CALL_NEW)


def apply(path: str) -> str:
    """'applied', 'already applied', or raises Moved. Nothing is written unless the result compiles."""
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        return "already applied"
    out = patch(src)
    compile(out, path, "exec")
    open(path, "w", encoding="utf-8").write(out)
    return "applied"


if __name__ == "__main__":
    try:
        print("hermes mcp breaker patch:", apply(sys.argv[1]))
    except Moved as e:
        print(f"hermes mcp breaker patch: NOT applied, the installed source is not the one it was written for ({str(e).splitlines()[0]})")
        sys.exit(3)
    except SyntaxError as e:
        # run with the interpreter Hermes itself runs on: its source needs Python 3.10 or later
        print(f"hermes mcp breaker patch: NOT applied, the result does not compile under this Python (line {e.lineno}: {e.msg})")
        sys.exit(4)
