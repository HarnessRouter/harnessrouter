"""Which OpenAI ids the runner drives over the Responses API rather than chat/completions.

Called with function tools, the modern line answers on /v1/responses and is refused on
/v1/chat/completions ("Function tools with reasoning_effort are not supported for <id> in
/v1/chat/completions"). The family test therefore reads the major version rather than a literal 5,
so a new id in the line routes instead of 400-ing on its first turn (gpt-6-astra, 2026-09-07).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import _HERMES_RESPONSES_API_MODEL as RESPONSES  # noqa: E402


def test_the_family_test_covers_gpt_6_and_whatever_comes_after():
    for model in ("gpt-6-astra", "openai/gpt-6-astra", "gpt-5.6-sol", "gpt-5.3-codex", "o3",
                  "gpt-7-x", "gpt-10-x"):
        assert RESPONSES.search(model), model


def test_the_older_line_and_other_vendors_keep_chat_completions():
    for model in ("gpt-4.1", "gpt-4o", "gpt-image-1", "claude-opus-5", "qwen3.8-max",
                  "deepseek-v4-pro", "gemini-3.8-flash"):
        assert not RESPONSES.search(model), model
