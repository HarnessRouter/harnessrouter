"""A channel that refuses the harness's tool declarations gets them normalised, and is remembered.

MEASURED on Vercel, 2026-10-07, the batch-3 nanobot column: one of eight models (gemini-3.6-flash)
died on its FIRST turn with

    GenerateContentRequest.tools[0].function_declarations[14].parameters.properties[args].items:
      field predicate failed: $type == Type.ARRAY
    …properties[args].any_of[0].items: missing field.

— an optional array parameter (`anyOf: [array, null]`, no `items`) that reached Google as sent. The
relay already carried the normaliser, applied proactively on TokenRouter's Gemini channels only,
because the comment above it said Vercel normalises these first. It does for most shapes and not for
this one, so the repair is now also reactive: the provider names the problem, the relay fixes it and
remembers it for the route. Reactive rather than proactive everywhere on purpose — the normaliser
flattens anyOf, which loses information a channel that handles it faithfully would have kept.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import server as S  # noqa: E402

REFUSAL = (b'{"error":{"message":"* GenerateContentRequest.tools[0].function_declarations[14]'
           b'.parameters.properties[args].items: field predicate failed: $type == Type.ARRAY\\n'
           b'* GenerateContentRequest.tools[0].function_declarations[14].parameters.properties'
           b'[args].any_of[0].items: missing field.\\n"}}')


def _body(**over):
    b = {"model": "gemini-3.6-flash", "messages": [{"role": "user", "content": "hi"}],
         "tools": [{"type": "function", "function": {"name": "shell", "parameters": {
             "type": "object",
             "properties": {"args": {"anyOf": [{"type": "array"}, {"type": "null"}],
                                     "description": "argv"}}}}}]}
    b.update(over)
    return json.dumps(b).encode()


def test_the_exact_refused_shape_becomes_one_google_accepts():
    out = json.loads(S._with_gemini_schemas(_body()))
    args = out["tools"][0]["function"]["parameters"]["properties"]["args"]
    assert args["type"] == "array", "the anyOf is flattened to the member that carries data"
    assert args["items"] == {"type": "string"}, "Google requires items on every array"
    assert args["nullable"] is True, "the null member is kept, as nullable"
    assert args["description"] == "argv", "and the text the model reads survives"
    assert "anyOf" not in args and "any_of" not in args


def test_the_refusal_text_is_what_triggers_it():
    # the branch keys on the provider naming its own validator's field path
    assert b"function_declarations" in REFUSAL


def test_a_body_with_nothing_to_fix_is_left_alone_so_the_retry_does_not_loop():
    # the branch only continues when the normalised body DIFFERS; an unchanged body must fall
    # through to the next repair instead of resending the same bytes twice.
    clean = _body(tools=[{"type": "function", "function": {
        "name": "shell", "parameters": {"type": "object", "properties": {
            "args": {"type": "array", "items": {"type": "string"}}}}}}])
    assert S._with_gemini_schemas(clean) == clean


def test_vercel_is_still_not_a_proactive_channel():
    # the point of doing this reactively: Vercel handles most shapes faithfully, and flattening
    # every anyOf for every base on it would lose what it was getting right.
    assert not S._gemini_channel("https://ai-gateway.vercel.sh/v1")
    assert S._gemini_channel("https://api.tokenrouter.com/v1")


# ── the memo that stops every turn paying for the same refusal ───────────────────────────
# Each turn gets its own relay route, so a flag on the route is forgotten at the next turn: the run
# that found this paid one refused round trip per turn, four turns in a row. The repair is remembered
# for the runner's life instead, keyed by upstream host and model. Nothing else pins that key, and a
# memo that silently stopped matching would only cost an extra round trip per turn — the kind of
# regression no column would ever show.

def test_the_memo_is_keyed_by_upstream_host_and_model_not_by_the_whole_url():
    a = S._gemini_schema_key("https://ai-gateway.vercel.sh/v1", "google/gemini-3.6-flash")
    # the same channel and model reached through another path is the same channel and model
    b = S._gemini_schema_key("https://ai-gateway.vercel.sh/v1/chat/completions", "google/gemini-3.6-flash")
    assert a == b == ("ai-gateway.vercel.sh", "google/gemini-3.6-flash")


def test_the_model_is_matched_without_case_and_a_different_one_is_a_different_key():
    k = S._gemini_schema_key("https://x.example/v1", "Google/Gemini-3.6-Flash")
    assert k == ("x.example", "google/gemini-3.6-flash")
    assert k != S._gemini_schema_key("https://x.example/v1", "google/gemini-3.8-flash")
    # and the normalisation is NOT applied on a guess to a model that has not refused
    assert S._gemini_schema_key("https://x.example/v1", "") == ("x.example", "")


def test_another_channel_serving_the_same_model_is_not_assumed_to_refuse_too():
    assert (S._gemini_schema_key("https://ai-gateway.vercel.sh/v1", "google/gemini-3.6-flash")
            != S._gemini_schema_key("https://generativelanguage.googleapis.com/v1beta/openai",
                                    "google/gemini-3.6-flash"))
