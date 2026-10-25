"""Which custom endpoint formats the four batch-4 bases take (2026-10-25)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402

F = app._CUSTOM_FORMAT_BACKENDS


def test_the_chat_bases_take_openai_chat_only_and_dcode_takes_responses():
    for b in ("vibe", "docker-agent", "fast-agent"):
        assert b in F["openai"] and b not in F["anthropic"] and b not in F["responses"], b
    assert "dcode" in F["responses"] and "dcode" not in F["openai"] and "dcode" not in F["anthropic"]


def test_a_custom_anthropic_connection_serves_none_of_them():
    # A Messages endpoint: the three post to /chat/completions, which it need not serve.
    integ = {"name": "Custom Anthropic", "provider": "custom",
             "config": {"api_key": "k", "base_url": "https://messages.example/v1", "api_format": "anthropic"}}
    for b in ("vibe", "docker-agent", "fast-agent", "dcode"):
        assert not app._integration_serves_backend(integ, b), b
    chat = {"name": "Custom OpenAI Chat", "provider": "custom",
            "config": {"api_key": "k", "base_url": "https://chat.example/v1", "api_format": "openai"}}
    for b in ("vibe", "docker-agent", "fast-agent"):
        assert app._integration_serves_backend(chat, b), b
