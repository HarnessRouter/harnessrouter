"""Gemini 3 thought signatures through the loopback relay (2026-09-06)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _delta(cid, sig=None):
    tc = {"id": cid, "type": "function", "function": {"name": "write_file", "arguments": "{}"}}
    if sig:
        tc["extra_content"] = {"google": {"thought_signature": sig}}
    return {"object": "chat.completion.chunk", "choices": [{"delta": {"tool_calls": [tc]}}]}


def _replay():
    return json.dumps({"model": "gemini-3.6-flash", "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            {"id": "call_x", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            {"id": "call_k", "type": "function", "function": {"name": "f", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "kept"}}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"}]}).encode()


def test_signatures_are_read_off_a_chunk_a_whole_message_and_an_sse_line():
    assert server._google_signatures_in(_delta("call_1", "sigA")) == [("call_1", "sigA")]
    assert server._google_signatures_in(_delta("call_1")) == []
    whole = {"object": "chat.completion", "choices": [{"message": {"tool_calls": [
        {"id": "call_2", "type": "function", "function": {"name": "f", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "sigB"}}}]}}]}
    assert server._google_signatures_in(whole) == [("call_2", "sigB")]
    line = b"data: " + json.dumps(_delta("call_9", "sigZ")).encode()
    assert server._google_signatures_in_line(line) == [("call_9", "sigZ")]
    assert server._google_signatures_in_line(b"data: [DONE]") == []
    assert server._google_signatures_in_line(b'data: {"choices": [{"delta": {"content": "thought_signature"}}]}') == []


def test_the_replay_carries_the_seen_signature_or_the_sentinel():
    sigs = {"call_1": "sigA"}
    out = json.loads(server._google_with_signatures(_replay(), sigs))
    calls = out["messages"][1]["tool_calls"]
    assert calls[0]["extra_content"] == {"google": {"thought_signature": "sigA"}}
    assert calls[1]["extra_content"] == {"google": {"thought_signature": server._GOOGLE_SIG_SKIP}}
    assert calls[2]["extra_content"] == {"google": {"thought_signature": "kept"}}
    assert out["messages"][2] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    untouched = b'{"model": "gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}]}'
    assert server._google_with_signatures(untouched, sigs) is untouched
    assert server._google_with_signatures(b"not json tool_calls", sigs) == b"not json tool_calls"
