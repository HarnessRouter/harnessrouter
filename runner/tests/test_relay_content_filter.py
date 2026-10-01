"""A provider that DECLINES must reach the person as a refusal, on either spelling of the field.

Measured 2026-10-01 against ai-gateway.vercel.sh: `anthropic/claude-fable-5.1` and
`anthropic/claude-opus-5` answer "Reply with exactly: M1-PROBE" with two SSE events, no content, no
reasoning and `"finish_reason":"content-filter"` — Vercel's spelling, with a hyphen, where OpenAI's
own is `content_filter`. The relay's pattern admitted only the underscore, so on that channel the
check that turns a refusal into a stated reason matched nothing and never ran: the full-catalog
matrix recorded those two ids as "Agent stopped after 5 consecutive unusable model responses to
prevent further API charges" — agentzero's own loop guard, correct in itself and about a counter
nobody outside it can see.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (_FINISH_RE, _failure_reason, _finish_reason_in,  # noqa: E402
                    _relay_last_finish, _HERMES_RELAY)


def test_vercels_hyphen_spelling_is_read():
    body = b'data: {"choices":[{"delta":{},"finish_reason":"content-filter"}]}'
    assert _finish_reason_in(body) == "content_filter"


def test_openais_underscore_spelling_still_is():
    body = b'{"choices":[{"finish_reason":"content_filter"}]}'
    assert _finish_reason_in(body) == "content_filter"


def test_an_ordinary_stop_is_unchanged():
    assert _finish_reason_in(b'{"choices":[{"finish_reason":"stop"}]}') == "stop"
    assert _finish_reason_in(b'{"choices":[{"finish_reason":"tool_calls"}]}') == "tool_calls"
    assert _finish_reason_in(b'{"no":"finish reason here"}') == ""


def test_the_pattern_takes_both_spellings_and_nothing_else():
    assert _FINISH_RE.findall(b'"finish_reason":"content-filter"') == [b"content-filter"]
    assert _FINISH_RE.findall(b'"finish_reason":"CONTENT_FILTER"') == []


def test_the_route_reports_one_spelling_to_its_callers():
    tok = "hr-relay-contentfiltertest"
    _HERMES_RELAY["routes"][tok] = ("https://up.example/v1", "sk", {"last_finish": "content-filter"})
    try:
        assert _relay_last_finish({"OPENAI_API_KEY": tok}) == "content_filter"
    finally:
        _HERMES_RELAY["routes"].pop(tok, None)


def test_a_turn_that_failed_reports_the_providers_refusal_not_the_clis_counter():
    """The slot _failure_reason already keeps for a provider's refusal: it wins over the result
    event's own message, which for agentzero is its loop guard's sentence."""
    guard = "HandledException: Agent stopped after 5 consecutive unusable model responses to prevent further API charges."
    refusal = "the provider declined the request (finish_reason content_filter)"
    assert _failure_reason(refusal, guard, "some stderr", 1) == refusal
    # and with no refusal seen, the CLI's own message is still what the person gets
    assert _failure_reason("", guard, "some stderr", 1) == guard
