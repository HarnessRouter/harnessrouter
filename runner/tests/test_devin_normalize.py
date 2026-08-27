import json
import pathlib

import pytest

FIXTURE = pathlib.Path(__file__).with_suffix("").parent / "fixtures" / "devin_acp_updates.jsonl"


@pytest.fixture
def update_lines():
    return [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]


def _make_state():
    return {"model": "devin-swe", "final": ""}


def test_devin_text_chunk():
    from server import _devin_to_claude
    evs = _devin_to_claude(
        {"jsonrpc": "2.0", "method": "session/update",
         "params": {"sessionId": "s1", "type": "agent_message_chunk",
                    "content": [{"type": "text", "text": "hello"}]}},
        _make_state(),
    )
    assert evs[0]["type"] == "assistant"
    assert evs[0]["message"]["content"][0]["text"] == "hello"


def test_devin_tool_call():
    from server import _devin_to_claude
    evs = _devin_to_claude(
        {"jsonrpc": "2.0", "method": "session/update",
         "params": {"sessionId": "s1", "type": "tool_call",
                    "toolCall": {"id": "tc1", "name": "bash", "input": {"command": "ls"}}}},
        _make_state(),
    )
    assert evs[0]["type"] == "assistant"
    assert evs[0]["message"]["content"][0]["type"] == "tool_use"
    assert evs[0]["message"]["content"][0]["name"] == "bash"


def test_devin_final_result():
    from server import _devin_to_claude
    evs = _devin_to_claude(
        {"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}},
        _make_state(),
    )
    assert any(e["type"] == "result" for e in evs)
