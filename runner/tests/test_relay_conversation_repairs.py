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
from server import (_image_in_tool_result_refused, _repair_tool_call_ids,  # noqa: E402
                    _tool_images_as_text, _IMAGE_PLACEHOLDER, _EMPTY_CALL_ID)


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
