"""The relay sees every provider answer, so it can say what was served for a backend whose CLI
never reports it (goose, cline, qwen): read off the bytes, stamped on the result event."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def test_the_model_is_read_off_json_and_sse_bytes():
    assert rs._served_model_in(b'{"id":"x","object":"chat.completion","model":"gpt-5.4-2026-08-01","choices":[]}') == "gpt-5.4-2026-08-01"
    assert rs._served_model_in(b'data: {"id":"c","object":"chat.completion.chunk","model":"openai/gpt-5.4","choices":[{"delta":{}}]}\n\n') == "openai/gpt-5.4"
    assert rs._served_model_in(b'{"type":"message_start","message":{"id":"m","model":"claude-sonnet-4-6"}}') == "claude-sonnet-4-6"
    assert rs._served_model_in(b'data: [DONE]\n') == ""


def test_the_turns_route_is_found_by_its_placeholder_bearer_and_answers_the_served_model():
    tok = "hr-relay-" + "a" * 32
    rs._HERMES_RELAY["routes"][tok] = ("https://api.example/v1", "real", {"served_model": "openai/gpt-5.4"})
    try:
        assert rs._relay_served_model({"HOME": "/x", "OPENAI_API_KEY": tok}) == "openai/gpt-5.4"
        assert rs._relay_served_model({"OPENAI_API_KEY": "sk-direct"}) == ""     # not on the relay
        rs._HERMES_RELAY["routes"][tok][2].clear()
        assert rs._relay_served_model({"OPENAI_API_KEY": tok}) == ""             # nothing answered yet
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)
