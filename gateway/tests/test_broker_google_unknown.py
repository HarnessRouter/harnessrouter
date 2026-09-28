"""Google's OpenAI-compatible endpoint names the request field it does not know; the relay drops
that top-level field and sends again (pi and dsh on gemini-3.6-flash, 2026-09-06: store, seed)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import _effort_shape_refused, _google_unknown_field, _without_field  # noqa: E402

STORE = json.dumps([{"error": {"code": 400, "message": 'Invalid JSON payload received. Unknown name "store": Cannot find field.', "status": "INVALID_ARGUMENT"}}]).encode()
SEED = json.dumps({"error": {"code": 400, "message": 'Invalid JSON payload received. Unknown name "seed": Cannot find field.'}}).encode()
NESTED = json.dumps({"error": {"code": 400, "message": 'Invalid JSON payload received. Unknown name "strict" at \'tools[0].function\': Cannot find field.'}}).encode()
QUOTA = json.dumps({"error": {"code": 429, "message": "You exceeded your current quota"}}).encode()


def test_names_the_refused_top_level_field():
    assert _google_unknown_field(STORE) == "store"
    assert _google_unknown_field(SEED) == "seed"


def test_nested_or_unrelated_refusals_are_not_retried():
    assert _google_unknown_field(NESTED) == ""
    assert _google_unknown_field(QUOTA) == ""
    assert _google_unknown_field(b"<html>bad gateway</html>") == ""


def test_without_field_drops_only_that_field():
    body = json.dumps({"model": "gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}], "store": False, "seed": 7}).encode()
    out = json.loads(_without_field(body, "store"))
    assert "store" not in out and out["seed"] == 7 and out["messages"]
    assert _without_field(body, "absent") == body
    assert _without_field(b"not json", "store") == b"not json"


def test_anthropics_refusal_of_the_effort_thinking_shape_is_recognised():
    """TokenRouter's chat-completions translation of `reasoning_effort` for Claude 5 came back as
    Anthropic's '"thinking.type: enabled" is not supported for this model. Use "thinking.type:
    adaptive" and "output_config.effort"' (hr-test 0.25.12, 2026-09-28); the broker sends the
    request again without the effort. Any other 400 is handed back as it came."""
    refusal = (b'{"error":{"message":"\\"thinking.type: enabled\\" is not supported for this model. Use '
               b'\\"thinking.type: adaptive\\" and \\"output_config.effort\\" to control reasoning.","type":"invalid_request_error"}}')
    assert _effort_shape_refused(refusal)
    assert not _effort_shape_refused(b'{"error":{"message":"Function tools with reasoning_effort are not supported"}}')
    assert not _effort_shape_refused(b"")
    body = json.dumps({"model": "claude-opus-5", "reasoning_effort": "high", "messages": []}).encode()
    assert json.loads(_without_field(body, "reasoning_effort")) == {"model": "claude-opus-5", "messages": []}
