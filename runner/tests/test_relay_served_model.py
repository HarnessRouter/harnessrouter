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


def test_a_field_split_across_two_reads_is_still_seen():
    """The relay reads the stream in 4096-byte chunks and a boundary can fall inside
    "model":"…". The miss would be SILENT — served_model stays empty and the turn is simply not
    substitution-checked — so the loop carries the previous chunk's tail; this pins that the
    carry is long enough for the longest id the reader accepts."""
    body = b'data: {"id":"c","object":"chat.completion.chunk","model":"openai/gpt-5.4","choices":[]}\n\n'
    cut = body.index(b'"model"') + 4        # split INSIDE the field name
    head, tail = body[:cut], body[cut:]
    assert rs._served_model_in(head) == "" and rs._served_model_in(tail) == "", "the split must be real"
    carry = head[-256:]
    assert rs._served_model_in(carry + tail) == "openai/gpt-5.4"


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
