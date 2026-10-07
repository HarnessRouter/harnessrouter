"""Claude Haiku 5.5's thinking levels, as Vercel's and OpenRouter's chat and Messages doors answered on
2026-10-07: every level accepted, off included; high and xhigh think more. Off is the usual
`disabled`: OpenRouter refuses `between_tools` for it by name, which the larger 5.5 models need. Opus
5.5 through TokenRouter refuses every way of turning thinking off, so it has no `none` there."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reasoning  # noqa: E402
import server as rs  # noqa: E402

VERCEL = "https://ai-gateway.vercel.sh/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
TOKENROUTER = "https://api.tokenrouter.com/v1"


def _apply(shape, base, model, asked):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}]}).encode()
    out, applied = reasoning.apply(body, shape, base, asked)
    return applied, json.loads(out)


def test_haiku_5_5_has_every_level_and_its_dated_id_is_the_same_model():
    want = ("none", "low", "medium", "high", "xhigh")
    assert reasoning.levels_for("claude-haiku-5.5") == want
    assert reasoning.levels_for("anthropic/claude-haiku-5.5-20261007") == want     # OpenRouter's served id
    assert reasoning.levels_for("claude-haiku-5-5") == want


def test_off_is_disabled_for_haiku_5_5_and_between_tools_stays_for_the_larger_5_5_models():
    for base in (VERCEL, OPENROUTER):
        got, doc = _apply("messages", base, "anthropic/claude-haiku-5.5", "none")
        assert got == "none" and doc["thinking"] == {"type": "disabled"}, base
    got, doc = _apply("messages", OPENROUTER, "anthropic/claude-haiku-5.5", "xhigh")
    assert got == "xhigh" and doc["thinking"] == {"type": "adaptive"} and doc["output_config"] == {"effort": "max"}
    got, doc = _apply("chat", OPENROUTER, "anthropic/claude-haiku-5.5", "none")
    assert got == "none" and doc["reasoning_effort"] == "none"          # OpenRouter lets this one be turned off
    assert _apply("messages", VERCEL, "anthropic/claude-sonnet-5.5", "none")[1]["thinking"] == {"type": "between_tools"}


def test_opus_5_5_cannot_be_turned_off_through_tokenrouter():
    got, doc = _apply("messages", TOKENROUTER, "anthropic/claude-opus-5.5", "none")
    assert got != "none" and doc.get("thinking") != {"type": "between_tools"} and doc.get("thinking") != {"type": "disabled"}


def test_claude_code_takes_an_effort_for_haiku_5_5_not_a_budget():
    token = rs._TURN_THINKING.set({"asked": "high"})
    try:
        env = rs._claude_thinking_env("claude-haiku-5-5")
        assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "high" and "MAX_THINKING_TOKENS" not in env
    finally:
        rs._TURN_THINKING.reset(token)
    token = rs._TURN_THINKING.set({"asked": "none"})
    try:
        assert rs._claude_thinking_env("claude-haiku-5-5")["MAX_THINKING_TOKENS"] == "0"
    finally:
        rs._TURN_THINKING.reset(token)
