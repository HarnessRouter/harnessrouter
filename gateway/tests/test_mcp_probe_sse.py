"""The MCP connection probe reads a JSON-RPC response from a complete SSE event."""
import json
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


RESPONSE = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "search"}]}}


def _sse(message, newline="\n", space=" "):
    lines = [": heartbeat", "event: message", "id: probe"]
    lines += [f"data:{space}{line}" for line in json.dumps(message, indent=2).split("\n")]
    return newline.join(lines) + newline * 2


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("space", [" ", ""])
def test_multiline_sse_is_one_jsonrpc_object(newline, space):
    assert app._parse_jsonrpc(_sse(RESPONSE, newline, space)) == RESPONSE


@pytest.mark.parametrize("text", [json.dumps(RESPONSE), "data: " + json.dumps(RESPONSE),
                                 "data:" + json.dumps(RESPONSE) + "\n\n"])
def test_plain_json_and_single_line_sse_still_parse(text):
    assert app._parse_jsonrpc(text) == RESPONSE


def test_skips_invalid_events_and_keeps_the_first_object():
    notification = {"jsonrpc": "2.0", "method": "notifications/progress"}
    prefix = ": heartbeat\n\nevent: ping\n\ndata: [DONE]\n\ndata: {broken\n\n"
    assert app._parse_jsonrpc(prefix + _sse(notification) + _sse(RESPONSE)) == notification


def test_data_lines_are_joined_before_parsing():
    # Two individually valid objects in one event are not two events.
    invalid = 'data: {"result": "wrong"}\ndata: {"result": "also wrong"}\n\n'
    assert app._parse_jsonrpc(invalid + _sse(RESPONSE)) == RESPONSE


@pytest.mark.parametrize("text", ["", ": heartbeat\n\n", "data: []\n\n", "data: {broken\n\n"])
def test_no_jsonrpc_object_returns_empty_dict(text):
    assert app._parse_jsonrpc(text) == {}


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
async def test_connection_probe_retains_server_and_tools_from_multiline_sse(monkeypatch, newline):
    url = "https://mcp.example.invalid/mcp"
    requests = []

    def respond(request):
        requests.append(request)
        message = json.loads(request.content)
        if message["method"] == "initialize":
            result = {"serverInfo": {"name": "fixture"}, "capabilities": {"tools": {}}}
            return httpx.Response(200, text=_sse({"jsonrpc": "2.0", "id": 1, "result": result}, newline),
                                  headers={"content-type": "text/event-stream", "mcp-session-id": "session-1"})
        if message["method"] == "notifications/initialized":
            return httpx.Response(202)
        assert message["method"] == "tools/list"
        return httpx.Response(200, text=_sse(RESPONSE, newline), headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(app, "_pool_is_local", lambda: True)
        monkeypatch.setattr(app, "_checked_http", lambda: client)
        result = await app._mcp_list_tools(url, "test-token")

    assert result == {"ok": True, "server": "fixture", "tools": [{"name": "search", "description": ""}]}
    assert [json.loads(r.content)["method"] for r in requests] == [
        "initialize", "notifications/initialized", "tools/list"]
    assert all(str(r.url) == url and r.headers["authorization"] == "Bearer test-token" for r in requests)
    assert all(r.headers["mcp-session-id"] == "session-1" for r in requests[1:])
