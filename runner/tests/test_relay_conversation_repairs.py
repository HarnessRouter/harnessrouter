"""What a conversation inherits from one model must not end it for the next.

The family tour hands ONE conversation from family to family, and on hr-test (2026-10-03, the four
bases of 0.29.0) three things an earlier model left in the history each ended the conversation for
every stricter provider after it: an image in a tool result, a tool call with an empty id, and two
parallel tool calls with one id. These pin the relay's repair of each.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from server import (_conversation_order_refused, _drop_empty_messages,  # noqa: E402
                    _empty_message_refused, _image_in_tool_result_refused,
                    _repair_tool_call_ids, _tool_images_as_text, _trailing_system_as_user,
                    _IMAGE_PLACEHOLDER, _EMPTY_CALL_ID)


def _body(messages):
    return json.dumps({"model": "m", "messages": messages}).encode()


def test_an_image_in_a_tool_result_becomes_a_sentence_and_text_only_results_are_untouched():
    plain = _body([{"role": "tool", "tool_call_id": "a", "content": [{"type": "text", "text": "ok"}]},
                   {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:x"}}]}])
    assert _tool_images_as_text(plain) == plain      # a user's own image is theirs to send
    body = _body([{"role": "tool", "tool_call_id": "a", "content": [
        {"type": "text", "text": "slide1.png"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}])
    out = json.loads(_tool_images_as_text(body))["messages"][0]
    assert out["content"] == "slide1.png\n" + _IMAGE_PLACEHOLDER and out["tool_call_id"] == "a"
    assert b"AAAA" not in _tool_images_as_text(body)


def test_the_refusals_measured_on_the_tour_are_each_recognised():
    for code, text in (
            (400, b"tool_result.content.1: Input tag 'image_url' found using 'type' does not match"),
            (400, b"did not match any variant of untagged enum ChatCompletionRequestToolMessageContent"),
            (404, b"No endpoints found that support image input")):
        assert _image_in_tool_result_refused(code, text), text
    assert not _image_in_tool_result_refused(401, b"image")
    assert not _image_in_tool_result_refused(400, b"max_tokens is too large")


def test_an_empty_tool_call_id_is_filled_and_its_answer_follows_it():
    body = _body([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "", "type": "function", "function": {"name": "run", "arguments": "{}"}},
            {"id": "call_ok", "type": "function", "function": {"name": "run", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "", "content": "one"},
        {"role": "tool", "tool_call_id": "call_ok", "content": "two"}])
    assert _EMPTY_CALL_ID.search(body)
    m = json.loads(_repair_tool_call_ids(body))["messages"]
    new = m[0]["tool_calls"][0]["id"]
    assert new and new != "call_ok" and m[1]["tool_call_id"] == new
    assert m[0]["tool_calls"][1]["id"] == "call_ok" and m[2]["tool_call_id"] == "call_ok"
    assert not _EMPTY_CALL_ID.search(_repair_tool_call_ids(body))


def test_duplicate_ids_in_one_message_are_told_apart_only_when_asked_and_in_call_order():
    body = _body([
        {"role": "assistant", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "call_1", "type": "function", "function": {"name": "b", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "from a"},
        {"role": "tool", "tool_call_id": "call_1", "content": "from b"}])
    assert _repair_tool_call_ids(body) == body
    m = json.loads(_repair_tool_call_ids(body, dedupe=True))["messages"]
    ids = [c["id"] for c in m[0]["tool_calls"]]
    assert ids[0] == "call_1" and ids[1] != "call_1"
    assert [m[1]["tool_call_id"], m[2]["tool_call_id"]] == ids
    clean = _body([{"role": "assistant", "tool_calls": [{"id": "x", "type": "function",
                                                         "function": {"name": "a", "arguments": "{}"}}]},
                   {"role": "tool", "tool_call_id": "x", "content": "r"}])
    assert _repair_tool_call_ids(clean, dedupe=True) == clean


# ── what a CLIENT's own request shape can do to a stricter provider (VT Code, 2026-10-16) ──────

def test_a_conversation_that_ends_in_a_system_message_is_sent_with_it_as_the_users_turn():
    body = _body([{"role": "system", "content": "you are vt"},
                  {"role": "user", "content": "hi"},
                  {"role": "assistant", "content": "VT-FIRST"},
                  {"role": "system", "content": "## Environment\n- Date: today"}])
    out = json.loads(_trailing_system_as_user(body))["messages"]
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user"]
    assert out[-1]["content"] == "## Environment\n- Date: today", "the text is kept verbatim"
    # the leading system message is the one place a system message belongs, and is left alone
    one = _body([{"role": "system", "content": "you are vt"}])
    assert _trailing_system_as_user(one) == one
    ok = _body([{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}])
    assert _trailing_system_as_user(ok) == ok


def test_the_two_refusals_measured_for_that_shape_are_recognised():
    # anthropic/claude-haiku-5.5 through the Vercel gateway, on a turn that had already answered
    assert _conversation_order_refused(400, b'{"error":{"message":"This model does not support '
                                             b'assistant message prefill. The conversation must '
                                             b'end with a user message."}}')
    assert not _conversation_order_refused(401, b"must end with a user message")
    assert not _conversation_order_refused(400, b"max_tokens is too large")


def test_an_empty_turn_is_dropped_and_everything_that_carries_something_is_kept():
    # google/gemini-3-flash: 400 "user message must have content", param messages.5.content
    body = _body([{"role": "system", "content": "s"},
                  {"role": "user", "content": "hi"},
                  {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "type": "function",
                                                                       "function": {"name": "x", "arguments": "{}"}}]},
                  {"role": "tool", "tool_call_id": "a", "content": "done"},
                  {"role": "user", "content": ""},
                  {"role": "user", "content": "carry on"}])
    out = json.loads(_drop_empty_messages(body))["messages"]
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "user"]
    assert out[-1]["content"] == "carry on"
    # an assistant turn with tool_calls is not empty, and neither is a tool result
    assert any(m.get("tool_calls") for m in out)
    # nothing to drop: the body is returned untouched, bytes for bytes
    clean = _body([{"role": "user", "content": "hi"}])
    assert _drop_empty_messages(clean) == clean


def test_an_empty_structured_content_array_counts_as_empty():
    """The shape VT Code actually sends. The first version of this repair read any list as
    "structured content, leave it alone", so it never fired on the body it was written for and the
    provider's 400 stood — which is how a repair can pass its own tests and change nothing."""
    body = _body([{"role": "user", "content": "hi"},
                  {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
                  {"role": "user", "content": []},
                  {"role": "user", "content": [{"type": "text", "text": "   "}]},
                  {"role": "user", "content": [{"type": "text", "text": "carry on"}]}])
    out = json.loads(_drop_empty_messages(body))["messages"]
    assert len(out) == 3
    assert out[1]["content"] == [{"type": "text", "text": "done"}], "real content is untouched"
    assert out[-1]["content"] == [{"type": "text", "text": "carry on"}]


def test_that_refusal_is_recognised_and_an_unrelated_400_is_not():
    assert _empty_message_refused(400, b'{"error":{"message":"user message must have content",'
                                       b'"param":"messages.5.content"}}')
    assert not _empty_message_refused(400, b"Assistant message must have either content or tool_calls")
    assert not _empty_message_refused(500, b"user message must have content")
