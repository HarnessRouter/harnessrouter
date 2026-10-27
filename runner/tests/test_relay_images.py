"""A conversation's images, fitted to what the model takes (2026-10-27). A deck agent renders and looks at its slides
every turn, and a switch to a model that reads text only, or that takes at most N images, failed every turn after:
on Deep Agents Code on the hosted service, qwen3.7-max ("Unexpected item type in content"), nemotron-3-super ("This
model doesn't support the image content block that you provided") and mistral-medium-3.5 ("Total number of images
exceeds the maximum allowed of 8"), all on Vercel's route. The three provider answers below are the ones those turns
received; the hosted broker carries the same rung."""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

QWEN_SAYS = ("<400> InternalError.Algo.InvalidParameter: The provided messages input is invalid. "
             "The error info is [Unexpected item type in content.].")
NEMOTRON_SAYS = "This model doesn't support the image content block that you provided. Update the content block and try again."
MISTRAL_SAYS = "Total number of images exceeds the maximum allowed of 8."
PNG = "data:image/png;base64,iVBORw0KGgo="


def _responses(n: int, model: str) -> dict:
    """dcode's shape: a Responses request whose history holds n looks at an image (tool results), then the new ask."""
    items = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "make the deck"}]}]
    for i in range(n):
        items += [{"type": "function_call", "call_id": f"c{i}", "name": "read_file", "arguments": json.dumps({"path": f"s{i}.png"})},
                  {"type": "function_call_output", "call_id": f"c{i}",
                   "output": [{"type": "input_image", "image_url": PNG}, {"type": "input_text", "text": f"s{i}.png"}]}]
    items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "change to brown"}]})
    return {"model": model, "input": items}


def _chat(n: int, model: str) -> dict:
    content = [{"type": "text", "text": "look"}] + [{"type": "image_url", "image_url": {"url": PNG}} for _ in range(n)]
    return {"model": model, "messages": [{"role": "user", "content": content}]}


def _messages(n: int) -> dict:
    blocks = [{"type": "tool_result", "tool_use_id": f"t{i}",
               "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBO"}}]}
              for i in range(n)]
    return {"model": "claude-sonnet-5.5", "messages": [{"role": "user", "content": blocks}]}


def _err(msg: str) -> bytes:
    return json.dumps({"error": {"message": msg, "type": "invalid_request_error"}}).encode()


def test_each_wording_is_read_and_nothing_else_is():
    assert server._images_refused(_err(QWEN_SAYS)) == 0
    assert server._images_refused(_err(NEMOTRON_SAYS)) == 0
    assert server._images_refused(_err(MISTRAL_SAYS)) == 8
    assert server._images_refused(_err("max_tokens: 100000 > 64000, which is the maximum allowed")) is None
    assert server._images_refused(_err("invalid temperature: only 1 is allowed")) is None
    assert server._images_refused(b"") is None


def test_the_known_limits_by_model_and_the_learned_ones_by_route(monkeypatch):
    monkeypatch.setattr(server, "_IMAGES_CAP_SEEN", {})
    route = ("ai-gateway.vercel.sh", "alibaba/qwen3.8-max")
    assert server._image_cap("alibaba/qwen3.7-max", route) == 0
    assert server._image_cap("nvidia/nemotron-3-super", route) == 0
    assert server._image_cap("mistral/mistral-medium-3.5", route) == 8
    assert server._image_cap("openai/gpt-6.1-sol", route) is None
    server._IMAGES_CAP_SEEN[route] = 4
    assert server._image_cap("alibaba/qwen3.8-max", route) == 4


def test_the_most_recent_images_are_kept_and_each_earlier_one_is_said_in_every_shape():
    out = json.loads(server._fit_images(json.dumps(_responses(10, "m")).encode(), 8))
    outs = [i["output"] for i in out["input"] if i.get("type") == "function_call_output"]
    assert [o[0]["type"] for o in outs] == ["input_text"] * 2 + ["input_image"] * 8      # the two oldest go
    assert outs[0][0]["text"] == server._IMAGE_NOT_SENT and outs[0][1] == {"type": "input_text", "text": "s0.png"}
    chat = json.loads(server._fit_images(json.dumps(_chat(3, "m")).encode(), 0))
    assert [p["type"] for p in chat["messages"][0]["content"]] == ["text"] * 4
    assert chat["messages"][0]["content"][1]["text"] == server._IMAGE_TEXT_ONLY
    msgs = json.loads(server._fit_images(json.dumps(_messages(2)).encode(), 1))
    assert [b["content"][0]["type"] for b in msgs["messages"][0]["content"]] == ["text", "image"]


def test_a_body_within_the_limit_goes_byte_for_byte():
    raw = json.dumps(_responses(3, "m")).encode()
    assert server._fit_images(raw, 8) is raw and server._fit_images(b"not json image", 0) == b"not json image"
    assert server._image_count(raw) == 3 and server._image_count(b"not json image") == 0


# ── through the relay, against an upstream that refuses as Vercel's routes did ──────────────────────────────

def _vercel_like(doc: dict) -> bytes | None:
    """The refusal Vercel's route gave for this request on 10-27, or None when it answers."""
    n, m = server._image_count(json.dumps(doc).encode()), str(doc.get("model"))
    if "qwen3.7-max" in m and n:
        return _err(QWEN_SAYS)
    if "nemotron" in m and n:
        return _err(NEMOTRON_SAYS)
    if "mistral" in m and n > 8:
        return _err(MISTRAL_SAYS)
    if "qwen3.8-max" in m and n > 4:
        return _err("Too many images: at most 4 images per request")
    if "llama" in m:
        return _err("max_tokens: 100000 > 64000, which is the maximum allowed")
    return None


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setattr(server, "_IMAGES_CAP_SEEN", {})
    got: list[bytes] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["content-length"]))
            got.append(raw)
            doc = json.loads(raw)
            refused = _vercel_like(doc)
            if refused is not None:
                code, out = 400, refused
            elif self.path.endswith("/responses"):
                code, out = 200, json.dumps({"id": "resp_1", "object": "response", "status": "completed", "model": doc["model"],
                                             "output": [{"type": "message", "role": "assistant", "content": [
                                                 {"type": "output_text", "text": "DONE"}]}],
                                             "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}).encode()
            else:
                code, out = 200, json.dumps({"object": "chat.completion", "model": doc["model"], "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "DONE"}}]}).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key")

    def post(path: str, body: dict) -> int:
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=10).status
        except urllib.error.HTTPError as e:
            return e.code
    yield post, got
    up.shutdown()


def test_a_text_only_model_mid_conversation_is_sent_no_image_and_answers(upstream):
    post, got = upstream
    for model in ("alibaba/qwen3.7-max", "nvidia/nemotron-3-super"):
        assert post("/responses", _responses(5, model)) == 200, model
        assert server._image_count(got[-1]) == 0
    assert len(got) == 2                        # known: fitted before the first call, nothing refused
    assert post("/chat/completions", _chat(3, "alibaba/qwen3.7-max")) == 200 and server._image_count(got[-1]) == 0


def test_mistral_takes_its_eight_most_recent_and_answers(upstream):
    post, got = upstream
    assert post("/responses", _responses(12, "mistral/mistral-medium-3.5")) == 200
    assert len(got) == 1 and server._image_count(got[0]) == 8


def test_an_unknown_limit_is_learned_from_the_refusal_and_kept_for_the_route(upstream):
    post, got = upstream
    assert post("/responses", _responses(6, "alibaba/qwen3.8-max")) == 200 and len(got) == 2
    assert server._image_count(got[0]) == 6 and server._image_count(got[1]) == 4      # as written, then fitted
    assert post("/responses", _responses(6, "alibaba/qwen3.8-max")) == 200
    assert len(got) == 3 and server._image_count(got[2]) == 4                          # learned: fitted at once


def test_a_model_that_takes_images_is_sent_all_of_them_and_other_refusals_pass_through(upstream):
    post, got = upstream
    raw = _responses(12, "openai/gpt-6.1-sol")
    assert post("/responses", raw) == 200 and server._image_count(got[0]) == 12
    assert json.loads(got[0])["input"] == raw["input"]                                   # untouched
    assert post("/responses", _responses(2, "meta/llama-4-maverick")) == 400
    # not about images: no fitted resend (the relay's other repairs may still try their own)
    assert all(server._image_count(b) == 2 for b in got[1:])
