"""What the broker strips, by request shape and by key.

Anthropic-shape requests lose the extended-thinking controls on every provider and every key
(measured model-version 400s: opus-4.7/4.8 reject `thinking.enabled`, haiku-4.5 rejects
`output_config.effort` and `thinking.adaptive`). OpenAI-shape requests keep `reasoning` and
`reasoning_effort` on every provider: TokenRouter and OpenRouter take them as written (probed
2026-09-06), and Codex's compaction needs `reasoning.context`. Priced-tier selectors go only on
the platform's key. Anything that is not JSON passes untouched.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import _strip_unsupported  # noqa: E402


def _anth(**kw) -> bytes:
    return json.dumps({"model": "claude-haiku-4.5", "max_tokens": 64,
                       "messages": [{"role": "user", "content": "hi"}], **kw}).encode()


def _resp(**kw) -> bytes:
    return json.dumps({"model": "gpt-5.5", "input": "hi", **kw}).encode()


def test_anthropic_shape_loses_thinking_controls_on_every_key():
    for byok in (False, True):
        for provider in ("anthropic", "tokenrouter", "vercel", "bedrock"):
            out = json.loads(_strip_unsupported(_anth(thinking={"type": "enabled", "budget_tokens": 1024},
                                                      context_management={"edits": []},
                                                      output_config={"effort": "high", "format": {"type": "json"}}),
                                                provider=provider, byok=byok, path="messages"))
            assert "thinking" not in out and "context_management" not in out, (provider, byok)
            assert out["output_config"] == {"format": {"type": "json"}}
            assert out["messages"] and out["max_tokens"] == 64


def test_anthropic_shape_empty_output_config_goes_with_effort():
    out = json.loads(_strip_unsupported(_anth(output_config={"effort": "low"}), provider="anthropic", byok=True, path="messages"))
    assert "output_config" not in out


def test_openai_shape_keeps_reasoning_on_every_provider():
    body = _resp(reasoning={"effort": "high", "summary": "auto"})
    for provider in ("openai", "azure", "azure-foundry", "tokenrouter", "openrouter", "vercel", "google"):
        for byok in (False, True):
            out = json.loads(_strip_unsupported(body, provider=provider, byok=byok, path="responses"))
            assert out["reasoning"] == {"effort": "high", "summary": "auto"}, (provider, byok)
    chat = json.dumps({"model": "gpt-5.4", "messages": [{"role": "user", "content": "hi"}], "reasoning_effort": "low"}).encode()
    for provider in ("openai", "tokenrouter", "openrouter"):
        assert json.loads(_strip_unsupported(chat, provider=provider, byok=False, path="chat/completions"))["reasoning_effort"] == "low"


def test_codex_compaction_keeps_reasoning_context():
    body = _resp(reasoning={"context": "all_turns"}, previous_response_id="resp_1")
    out = _strip_unsupported(body, provider="openai", byok=True, path="responses/compact")
    assert out == body                        # byte-identical: nothing to strip, nothing rewritten


def test_tier_selectors_stripped_on_the_platform_key_only():
    for path, body in (("responses", _resp(service_tier="priority")),
                       ("messages", _anth(speed="fast")),
                       ("chat/completions", json.dumps({"model": "m", "messages": [], "provider": {"order": ["openai"]}}).encode())):
        platform = json.loads(_strip_unsupported(body, provider="openrouter", byok=False, path=path))
        own = json.loads(_strip_unsupported(body, provider="openrouter", byok=True, path=path))
        assert not ({"service_tier", "speed", "provider"} & set(platform)), path
        assert {"service_tier", "speed", "provider"} & set(own), path


def test_non_json_passes_untouched():
    raw = b"not json at all"
    assert _strip_unsupported(raw, provider="tokenrouter", byok=False, path="messages") is raw
    assert _strip_unsupported(b"", provider="openai") == b""
    arr = b"[1, 2]"
    assert _strip_unsupported(arr, provider="openai", path="responses") is arr
