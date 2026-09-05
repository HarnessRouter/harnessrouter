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
