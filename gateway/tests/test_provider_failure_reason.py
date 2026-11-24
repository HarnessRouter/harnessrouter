"""When the provider turns down the org's own connection, the turn says which way, and its error.detail says
why and whether a retry can succeed.

_PROVIDER_REFUSAL_RE matched 429, "rate limit" and "quota" the same as 401 and an invalid key, so every one of
them read "Your <provider> key was refused". A rate limit partway through a task, an account with no credit
left, and a model the provider would not serve for the key all sent people to check a key that worked, and
nothing machine-readable told a client with automatic retries which of them could pass on a retry.

The rule still decides that the turn stops on this connection rather than move on (_provider_refused, as
before). What it says is now told apart, and error.detail carries
{"reason": provider_key_refused | provider_model_refused | provider_quota_exhausted | provider_rate_limited,
 "retryable": true for a rate limit only, "retry_after_seconds": when the provider named a wait}
beside the base and tool it already carried. The code stays turn_failed."""
from __future__ import annotations

import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

CONN = {"provider": "tokenrouter", "_vendor": "tokenrouter"}


@pytest.mark.parametrize("err,kind", [
    ("OpenAI API error (401): Incorrect API key provided", "refused"),
    ("Error code: 403 - {'error': 'forbidden'}", "refused"),
    ("403 Forbidden: permission denied", "refused"),
    ("Error code: 429 - {'error': {'message': 'Rate limit reached for gpt-5.4', 'type': 'rate_limit_error'}}", "rate_limit"),
    ("tokenrouter: 429 Too Many Requests", "rate_limit"),
    ("APIError: rate_limit_exceeded, please retry after 20s", "rate_limit"),
    ("Error code: 429 - {'error': {'code': 'insufficient_quota', 'message': 'You exceeded your current quota'}}", "quota"),
    ("Error code: 403 - {'error': {'message': 'Project proj_x does not have access to model gpt-5.4-pro', 'code': 'model_not_found'}}", "model"),
    ("tokenrouter 403: your key is not allowed to use model claude-opus-5", "model"),
    ("403 Forbidden: model 'gemini-4-argon' is not available to this API key", "model"),
    ("no rollout found for thread id 01a06ea9", ""),
    ("Failed to run pre-sampling compact\nReconnecting... 1/5 (429 rate limit)", ""),          # first line only
    ("Client error '401 Unauthorized' for url 'http://127.0.0.1:1/hr-mcp-ab/mcp'", ""),          # the relay (#714)
    ('Error code: 401 - {"error": "unknown relay token"}', ""),                                  # the provider relay
    ("401 Unauthorized from http://127.0.0.1:41234/v1/chat/completions: unknown relay token", ""),
    ("hr API error (502): Microsoft Entra did not sign this connection in: AADSTS90055: Too many requests.", ""),
])
def test_each_answer_is_told_apart_and_all_four_still_stop_the_turn(err, kind):
    assert gw._provider_failure_kind(err) == kind
    assert gw._provider_refused(err) is bool(kind)


@pytest.mark.parametrize("err,kind,wait", [
    # Gemini's per-minute limit says "quota" and names a wait: it passes in 41 seconds, so it is a rate limit.
    ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, please check your "
     "plan and billing details. Quota exceeded for metric: generate_content_free_tier_requests, limit: 10. "
     "Please retry in 41.24s.', 'status': 'RESOURCE_EXHAUSTED'}}", "rate_limit", 41.24),
    ("[API Error: 429 Resource has been exhausted (e.g. check quota).]", "rate_limit", None),
    # OpenAI's empty account without its code: the plan's quota, no wait named.
    ("429 You exceeded your current quota, please check your plan and billing details.", "quota", None),
    # an empty account named by its code or its sentence stays one even when it names a wait
    ("tokenrouter 403: insufficient_user_quota", "quota", None),
    ("Error code: 429 - insufficient_quota, retry after 60s", "quota", None),
    ("429: Your credit balance is too low to access the API", "quota", None),
])
def test_a_quota_that_passes_with_a_wait_is_a_rate_limit_and_an_empty_account_is_not(err, kind, wait):
    assert gw._provider_failure_kind(err) == kind
    detail = gw._provider_failure_detail(err)
    assert detail["retryable"] is (kind == "rate_limit")
    assert detail.get("retry_after_seconds") == wait


def test_a_rate_limit_says_the_key_was_not_refused_and_to_wait():
    err = "tokenrouter: 429 Too Many Requests"
    said = gw._refusal_message(CONN, err)
    assert said.startswith("tokenrouter rate-limited this task (too many requests for now; your key was not refused).")
    assert "Wait a minute and try again." in said and said.endswith(err)


@pytest.mark.parametrize("err,wait", [
    ("429: rate limit, retry after 20s", "It asked to wait 20 s"),
    ("429 Too Many Requests; Retry-After: 7", "It asked to wait 7 s"),
    ("Rate limit reached for gpt-5.4. Please try again in 1.5s.", "It asked to wait 1.5 s"),
    ("Rate limit reached. Please try again in 120ms.", "It asked to wait 0.12 s"),
    ("429 rate limit: try again in 5 minutes", "It asked to wait 5 min"),
])
def test_the_wait_the_provider_names_is_passed_on(err, wait):
    assert wait in gw._refusal_message(CONN, err)


def test_an_empty_account_and_a_refused_model_say_what_to_do():
    quota = gw._refusal_message(CONN, "Error code: 429 - {'error': {'code': 'insufficient_quota'}}")
    assert quota.startswith("Your tokenrouter account has no quota or credit left for this key; add credit with tokenrouter")
    model = gw._refusal_message(CONN, "tokenrouter 403: your key is not allowed to use model claude-opus-5")
    assert model.startswith("tokenrouter refused this model for your key (the key itself was accepted). Choose another model")
    for said in (quota, model):
        assert "was refused:" not in said


def test_a_custom_endpoint_is_called_by_the_connections_name():
    """Read back on the 0.41.26 candidate: a custom connection said "custom rate-limited this task" and "add credit
    with custom"."""
    custom = {"name": "integration:My DeepSeek", "_vendor": "custom", "provider": "tokenrouter"}
    said = gw._refusal_message(custom, "429: Rate limit reached. Please try again in 2s.")
    assert said.startswith("My DeepSeek rate-limited this task (too many requests for now; your key was not refused).")
    said = gw._refusal_message(custom, "Error code: 429 - insufficient_quota")
    assert said.startswith("Your My DeepSeek account has no quota or credit left for this key; add credit with My DeepSeek")
    assert gw._refusal_message({"_vendor": "custom"}, "401 invalid api key").startswith("Your custom endpoint key was refused")
    assert gw._refusal_message({**CONN, "name": "integration:My TR"}, "401 invalid api key").startswith("Your tokenrouter key was refused")


def test_a_refused_key_reads_as_before_and_an_entra_connection_is_never_a_key():
    assert gw._refusal_message(CONN, "OpenAI API error (401): invalid api key") == \
        "Your tokenrouter key was refused: OpenAI API error (401): invalid api key"
    entra = {"provider": "azure", "auth": "entra"}
    for err in ("hr API error (401): x", "429 rate limit", "429 insufficient_quota", "403: not allowed to use model gpt-5.4"):
        assert "key" not in gw._refusal_message(entra, err).replace(err, "")


@pytest.mark.parametrize("err,extra", [
    ("OpenAI API error (401): Incorrect API key provided", {"reason": "provider_key_refused", "retryable": False}),
    ("tokenrouter 403: your key is not allowed to use model claude-opus-5", {"reason": "provider_model_refused", "retryable": False}),
    ("Error code: 429 - {'error': {'code': 'insufficient_quota'}}", {"reason": "provider_quota_exhausted", "retryable": False}),
    ("tokenrouter: 429 Too Many Requests", {"reason": "provider_rate_limited", "retryable": True}),
    ("Rate limit reached. Please try again in 1.5s.", {"reason": "provider_rate_limited", "retryable": True, "retry_after_seconds": 1.5}),
])
def test_the_failed_response_says_why_and_whether_a_retry_can_succeed(err, extra):
    rec = {"backend": "hermes", "tried": [{"connection": "c", "status": "failed", "error": err}],
           "error_message": gw._refusal_message(CONN, err), "provider_failure": gw._provider_failure_detail(err)}
    tr = gw._RespTranslator("resp_reason", "m", None, True, time.time())
    gw._fail_events(tr, rec)
    assert tr.error["code"] == "turn_failed" and tr.error["message"] == rec["error_message"]
    assert tr.error["detail"] == {"base": "hermes", **extra}


def test_the_detail_carries_none_of_the_providers_text_and_other_failures_add_nothing():
    err = "429 rate limit for messages[0].content=\"my secret plan\" via integration:org.acme:openai"
    assert gw._provider_failure_detail(err) == {"reason": "provider_rate_limited", "retryable": True}
    assert gw._provider_failure_detail("runner: exit_code=1, no diagnostic output") == {}
    rec = {"backend": "hermes", "tried": [{"connection": "c", "status": "failed", "error": "upstream 502"}]}
    tr = gw._RespTranslator("resp_other", "m", None, True, time.time())
    gw._fail_events(tr, rec)
    assert tr.error["detail"] == {"base": "hermes"}


def test_the_refusal_branch_sets_the_message_and_the_detail_together():
    src = (pathlib.Path(__file__).resolve().parents[1] / "app.py").read_text()
    i = src.index('rec["error_message"] = _refusal_message(conn, _last_err)')
    assert 'rec["provider_failure"] = _provider_failure_detail(_last_err)' in src[i:i + 200]
