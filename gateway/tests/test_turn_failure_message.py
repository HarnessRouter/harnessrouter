"""A failed turn names the org's own key's refusal when that is why it stopped."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_own_key_refusal_is_said_in_words():
    rec = {"tried": [{"connection": "openai", "status": "failed", "error": "OpenAI API error (401): invalid api key"}],
           "error_message": "Your openai key was refused: OpenAI API error (401): invalid api key"}
    assert gw._turn_failure_message(rec) == "Your openai key was refused: OpenAI API error (401): invalid api key"


def test_an_exhausted_chain_lists_what_was_tried():
    rec = {"tried": [{"connection": "a", "error": "not found"}, {"connection": "b", "status": "failed", "error": "boom"}]}
    m = gw._turn_failure_message(rec)
    assert '"a"' in m and "boom" in m


def test_nothing_tried_still_says_something():
    assert gw._turn_failure_message({}) == "turn failed"


def test_only_a_refusal_reads_as_a_refused_key():
    assert gw._PROVIDER_REFUSAL_RE.search("OpenAI API error (401): invalid api key")
    assert not gw._PROVIDER_REFUSAL_RE.search("no rollout found for thread id 01a06ea9")


def test_refusal_is_judged_on_the_providers_first_line_only():
    compact = ("ERROR codex_core::session::turn: Failed to run pre-sampling compact\n"
               "Error running remote compact task: { \"error\": { \"message\": \"X-OpenAI-Internal-Codex-Responses-Lite "
               "requires `reasoning.context` to be `all_turns`.\", \"type\": \"invalid_request_error\" } }\n"
               "Reconnecting... 1/5 (rate limit? no: quota)")
    assert not gw._provider_refused(compact)
    assert gw._provider_refused("OpenAI API error (401): Incorrect API key provided")
    assert gw._provider_refused("Error: 429 insufficient_quota\nReconnecting... 1/5")


def test_a_models_content_refusal_is_not_a_key_refusal():
    # pi, glm-5.3-flash switching to claude-opus-5 on the OSS matrix (2026-09-06): the provider's
    # first line was "The model refused to complete the request", and the word alone read as a
    # refused key. A key refusal is an auth or quota line, never the word.
    assert not gw._provider_refused("The model refused to complete the request")
    assert not gw._provider_refused("Your tokenrouter key was refused: The model refused to complete the request")
    assert gw._provider_refused("403 Forbidden: key disabled")
