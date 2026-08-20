"""Guard: codex token usage must report FRESH input (cached read netted out).

Regression this pins: codex's inputTokens INCLUDES the cached read. Billing charges input_1k on
input_tokens, so if the cached read isn't subtracted, cached tokens are billed at the full input
rate (~10x the cached rate). On a long conversation (each turn resends the whole cache-hit
transcript) that inflated cost several-fold. _norm_token_usage must net cached out so input_tokens
is fresh-only, uniform with the Anthropic contract.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402


def test_codex_input_is_netted_of_cached():
    # codex app-server shape: counts under tokenUsage.total, cached included in inputTokens
    u = {"tokenUsage": {"total": {
        "inputTokens": 13024524, "outputTokens": 264690, "cachedInputTokens": 11233792}}}
    r = rn._norm_token_usage(u)
    assert r["input_tokens"] == 13024524 - 11233792  # fresh only
    assert r["cache_read_tokens"] == 11233792
    assert r["output_tokens"] == 264690


def test_snake_case_exec_shape_netted():
    u = {"input_tokens": 1000, "output_tokens": 200, "cached_input_tokens": 900}
    r = rn._norm_token_usage(u)
    assert r["input_tokens"] == 100
    assert r["cache_read_tokens"] == 900


def test_no_cache_leaves_input_untouched():
    u = {"input_tokens": 500, "output_tokens": 50}
    r = rn._norm_token_usage(u)
    assert r["input_tokens"] == 500
    assert "cache_read_tokens" not in r


def test_never_negative_when_provider_reports_net_input():
    # defensive: a provider that already nets input (cache_read > reported input) must not go negative
    u = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 900}
    r = rn._norm_token_usage(u)
    assert r["input_tokens"] == 0
    assert r["cache_read_tokens"] == 900
