"""A failed turn names the org's own key's refusal when that is why it stopped."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_own_key_refusal_is_said_in_words():
    rec = {"tried": [{"connection": "openai", "status": "failed", "error": "OpenAI API error (401): invalid api key"}],
           "error_message": "Your openai key was refused: OpenAI API error (401): invalid api key"}
    assert gw._turn_failure_message(rec) == "Your openai key was refused: OpenAI API error (401): invalid api key"


def test_an_exhausted_chain_says_the_last_reason_and_no_connection_name():
    rec = {"tried": [{"connection": "a", "error": "not found"}, {"connection": "b", "status": "failed", "error": "boom"}]}
    m = gw._turn_failure_message(rec)
    assert m == "The turn failed on every connection it tried. The last one said: boom"
    assert '"a"' not in m and "[" not in m


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


def test_the_reason_is_the_last_connection_that_ran_not_a_skipped_one():
    """hermes on hosted, claude-opus-5, 2026-09-08: TokenRouter ran the turn and Opus 5's
    safeguards refused it; the chain's next connection could not be brokered and its note was
    shown as the reason."""
    rec = {"tried": [{"connection": "integration:global:TokenRouter Sponsorship", "status": "failed",
                      "error": "The model refused to complete the request"},
                     {"connection": "integration:global:hermes-bedrock", "error": "credential cannot be brokered; refused"}]}
    assert gw._turn_failure_message(rec) == \
        "The turn failed on every connection it tried. The last one said: The model refused to complete the request"
    only_skips = {"tried": [{"connection": "a", "error": "not found"}, {"connection": "b", "error": "credential cannot be brokered; refused"}]}
    assert gw._turn_failure_message(only_skips) == \
        "The turn failed on every connection it tried. The last one said: credential cannot be brokered; refused"


def test_a_provider_refusing_the_tasks_earlier_reasoning_is_said_in_words():
    """TokenRouter's gpt-5.4 route: a gpt-5.4 thread switched into gpt-6-astra fails with the
    provider's JSON (the open source column, 2026-09-10); a same-model cold restore failed the same
    way on hosted on 2026-09-08. The person reads what to do, never the JSON."""
    raw = ('{"error":{"message":"The encrypted content for item rs_0f75 could not be verified. Reason: '
           'Encrypted content could not be decrypted or parsed.","type":"invalid_request_error"}}')
    rec = {"model_req": "gpt-6-astra", "models_before": ["gpt-5.4"],
           "tried": [{"connection": "integration:My TokenRouter", "status": "failed", "error": "The turn failed: " + raw}]}
    m = gw._turn_failure_message(rec)
    assert m == ("gpt-6-astra cannot continue this task's earlier reasoning through this provider (it was "
                 "produced under another route). Start a new task for gpt-6-astra, or keep this task on gpt-5.4.")
    same = {"model_req": "gpt-5.4", "models_before": [], "tried": [{"connection": "c", "status": "failed", "error": raw}]}
    assert gw._turn_failure_message(same).endswith("Start a new task for gpt-5.4.")
    assert "invalid_request_error" not in gw._turn_failure_message(rec)
    plain = {"tried": [{"connection": "c", "status": "failed", "error": "boom"}]}
    assert gw._turn_failure_message(plain) == "The turn failed: boom"
