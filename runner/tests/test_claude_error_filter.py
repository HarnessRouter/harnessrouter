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
    # The guard anchors on a leading "API Error:" — prose that happens to discuss errors must not
    # be stripped.
    ev = _asst("To handle an API error, catch the 400 status and retry.")
    assert rn._claude_passthrough(ev, {}) == [ev]


def test_a_turn_whose_only_answer_is_the_clis_error_line_fails_with_that_reason():
    """Qwen Code, hosted, claude-opus-5 (2026-09-08): Opus 5's safeguards refused the turn, the
    CLI wrote "[API Error: Model stream ended with empty response text.]" and the turn completed
    with that as its reply. Claude Code writes the same line without a status code."""
    state = {}
    ev = _asst("[API Error: Model stream ended with empty response text.]")
    assert rn._claude_passthrough(ev, state) == []
    res = {"type": "result", "subtype": "success", "result": "", "is_error": False}
    out = rn._claude_passthrough(res, state)
    assert out == [{"type": "result", "subtype": "error", "result": "API Error: Model stream ended with empty response text.", "is_error": True}]
    # batch mode: the CLI's result carries the line itself
    out = rn._claude_passthrough({"type": "result", "subtype": "success", "result": "[API Error: Model stream ended with empty response text.]", "is_error": False}, {})
    assert out[0]["is_error"] is True and out[0]["result"] == "API Error: Model stream ended with empty response text."
    # Claude Code's own account of a refusal, no code, and an error result without a message
    state = {}
    rn._claude_passthrough(_asst("API Error: Opus 5's safeguards flagged this message. Claude Code can't respond to this message with Opus 5."), state)
    out = rn._claude_passthrough({"type": "result", "subtype": "error", "result": "", "is_error": True}, state)
    assert out[0]["result"].startswith("API Error: Opus 5's safeguards flagged this message")


def test_a_real_answer_after_a_retried_error_keeps_the_answer():
    state = {"partial": True}
    rn._claude_passthrough(_asst("API Error: 429 rate limited"), state)
    delta = {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}}
    rn._claude_passthrough(delta, state)
    out = rn._claude_passthrough({"type": "result", "subtype": "success", "result": "", "is_error": False}, state)
    assert out == [{"type": "result", "subtype": "success", "result": "Hello", "is_error": False}]


def test_a_resume_the_builder_could_not_honor_is_reported_not_silent():
    """claude and opencode start fresh when the session is not in the workspace; the turn then
    opens with the resume_lost note the gateway renders (hermes already sends it, codex its own)."""
    assert rn._resume_lost("opencode", ["opencode", "run", "hello"], "ses_abc") == "ses_abc"
    assert rn._resume_lost("opencode", ["opencode", "run", "--session", "ses_abc", "hello"], "ses_abc") is None
    assert rn._resume_lost("claude", ["claude", "-p", "hi"], "s1") == "s1"
    assert rn._resume_lost("claude", ["claude", "-p", "--resume", "s1", "hi"], "s1") is None
    assert rn._resume_lost("opencode", ["opencode"], None) is None
    assert rn._resume_lost("hermes", ["hermes"], "s1") is None
