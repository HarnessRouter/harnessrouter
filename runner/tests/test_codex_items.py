"""codex names its items two ways: snake_case on `codex exec --json`, camelCase on the app-server.
The record must read both the same, and a message is never a tool (2026-09-10)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import _codex_item_kind, _codex_tool_item  # noqa: E402


def test_item_kinds_read_the_same_in_both_spellings():
    assert _codex_item_kind({"type": "mcpToolCall"}) == "mcp_tool_call"
    assert _codex_item_kind({"type": "mcp_tool_call"}) == "mcp_tool_call"
    assert _codex_item_kind({"type": "commandExecution"}) == "command_execution"
    assert _codex_item_kind({"type": "agentMessage"}) == "agent_message"


def test_an_mcp_call_is_named_by_its_server_and_tool_in_both_spellings():
    for it in ({"type": "mcpToolCall", "id": "m1", "server": "deepwiki", "tool": "read_wiki_structure", "arguments": {"repoName": "x"}},
               {"type": "mcp_tool_call", "id": "m1", "server": "deepwiki", "tool": "read_wiki_structure", "arguments": {"repoName": "x"}}):
        evs = _codex_tool_item(it)
        use = evs[0]["message"]["content"][0]
        assert use["type"] == "tool_use" and use["name"] == "deepwiki.read_wiki_structure" and use["input"] == {"repoName": "x"}


def test_messages_and_reasoning_are_not_tools():
    for kind in ("userMessage", "agentMessage", "reasoning", "agent_message"):
        assert _codex_tool_item({"type": kind, "id": "x", "text": "hello"}) == []


def test_a_command_reads_its_camel_case_fields():
    evs = _codex_tool_item({"type": "commandExecution", "id": "c1", "command": "ls", "aggregatedOutput": "a\n", "exitCode": 0})
    use, res = evs[0]["message"]["content"][0], evs[1]["message"]["content"][0]
    assert use["name"] == "Bash" and use["input"] == {"command": "ls"}
    assert res["type"] == "tool_result" and res["is_error"] is False and res["content"] == "a\n"
