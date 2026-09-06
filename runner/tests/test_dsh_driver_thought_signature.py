"""Gemini 3 thought signatures through the dsh relay (2026-09-06)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402


def test_dsh_relay_reads_signatures_and_replays_them_or_the_sentinel():
    tc = {"id": "call_7", "type": "function", "function": {"name": "f", "arguments": "{}"},
          "extra_content": {"google": {"thought_signature": "sig7"}}}
    line = b"data: " + json.dumps({"choices": [{"delta": {"tool_calls": [tc]}}]}).encode()
    assert dsh_driver._google_signatures_in_line(line) == [("call_7", "sig7")]
    assert dsh_driver._google_signatures_in_line(b"data: [DONE]") == []
    body = json.dumps({"messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_7", "type": "function", "function": {"name": "f", "arguments": "{}"}},
        {"id": "call_new", "type": "function", "function": {"name": "f", "arguments": "{}"}}]}]}).encode()
    out = json.loads(dsh_driver._google_with_signatures(body, {"call_7": "sig7"}))
    calls = out["messages"][0]["tool_calls"]
    assert calls[0]["extra_content"]["google"]["thought_signature"] == "sig7"
    assert calls[1]["extra_content"]["google"]["thought_signature"] == dsh_driver._GOOGLE_SIG_SKIP
    plain = b'{"messages": [{"role": "user", "content": "hi"}]}'
    assert dsh_driver._google_with_signatures(plain, {}) is plain
