import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402


def test_a_listing_naming_the_window_context_window_also_carries_context_length():
    """Vercel: hermes reads a loopback relay as a local server and takes max_model_len, context_length
    or max_tokens from the per-model body, so without this it took the output cap as the window."""
    body = json.dumps({"id": "deepseek/deepseek-v4.1-flash", "context_window": 1048576, "max_tokens": 32768}).encode()
    out = json.loads(server._model_metadata_with_context_length(body))
    assert out["context_length"] == 1048576 and out["max_tokens"] == 32768
    listing = json.dumps({"object": "list", "data": [{"id": "a", "context_window": 1000000}, {"id": "b", "context_length": 5, "context_window": 9}]}).encode()
    out = json.loads(server._model_metadata_with_context_length(listing))
    assert [e["context_length"] for e in out["data"]] == [1000000, 5]


def test_other_bodies_go_back_unchanged():
    for body in (b"not json", json.dumps({"id": "x", "context_length": 128000}).encode(),
                 json.dumps({"object": "list", "data": [{"id": "x"}]}).encode(), json.dumps({"choices": []}).encode()):
        assert server._model_metadata_with_context_length(body) == body
