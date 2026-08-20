"""Claude Code injects transient provider errors into its stream AS assistant text
("API Error: 400 ..."), then retries. That diagnostic is CLI UX, not model output — rendering it
as the reply made a working opus-4.7/4.8 turn look failed. _claude_passthrough must drop those
error-only assistant messages and strip the error block from mixed ones, without touching real
replies, results, or other event types."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402


def _asst(*texts):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": t} for t in texts]}}


def test_pure_api_error_message_is_dropped():
    for code in ("400", "429", "500", "529"):
        ev = _asst(f'API Error: {code} "..enabled" is not supported for this model.')
        assert rn._claude_passthrough(ev, {}) == [], f"{code} error should render nothing"


def test_error_stripped_but_real_text_kept():
    ev = _asst("API Error: 429 rate limited", "Hello! How can I help?")
    out = rn._claude_passthrough(ev, {})
    assert len(out) == 1
    kept = out[0]["message"]["content"]
    assert kept == [{"type": "text", "text": "Hello! How can I help?"}]


def test_normal_reply_untouched():
    ev = _asst("Here is your answer.")
    assert rn._claude_passthrough(ev, {}) == [ev]


def test_tool_use_block_preserved_even_with_error_text():
    ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "API Error: 400 bad thinking param"},
        {"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "ls"}}]}}
    out = rn._claude_passthrough(ev, {})
    assert out and any(c.get("type") == "tool_use" for c in out[0]["message"]["content"])
    assert all(not (c.get("type") == "text") for c in out[0]["message"]["content"])


def test_result_and_other_events_pass_through():
    res = {"type": "result", "subtype": "success", "result": "done", "is_error": False}
    assert rn._claude_passthrough(res, {}) == [res]
    init = {"type": "system", "subtype": "init", "session_id": "s1"}
    assert rn._claude_passthrough(init, {}) == [init]


def test_non_error_text_that_merely_mentions_api_error_is_kept():
    # The guard anchors on a leading "API Error: <3-digit code>" — prose that happens to discuss
    # errors must not be stripped.
    ev = _asst("To handle an API error, catch the 400 status and retry.")
    assert rn._claude_passthrough(ev, {}) == [ev]
