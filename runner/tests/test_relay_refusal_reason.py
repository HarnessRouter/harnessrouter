"""A failed turn's reason is the provider's refusal as the relay read it, when the CLI could not read
it (#612).

Qwen Code 0.26.3 reads a refusal's reason only under an `error` key. vLLM up to 0.10.0 puts `message`
at the top level, so a turn vLLM refused for a window too small read "API Error: 400 status code (no
body)" while the relay held vLLM's sentence on the route. Measured with the real CLI at a stub
through the relay, and on a real vLLM v0.8.5.post1 in #578.

Each test runs a turn through _run_turn_bg, the generic path whose reason the gateway shows ("The
turn failed: <reason>"), with a fake CLI that makes its calls through the route _build_qwen
registers, prints the stream-json events Qwen Code 0.26.3 printed on such a refusal (captured
2026-10-29), and exits 1 as it did.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import Auth, _build_qwen, _claude_passthrough, _relay_refusal_unsaid, _run_turn_bg, _turns  # noqa: E402

VLLM_SAID = ("This model's maximum context length is 8192 tokens. However, you requested 49350 tokens "
             "(16582 in the messages, 32768 in the completion). Please reduce the length of the messages "
             "or completion.")
# vLLM <=0.10.0's ErrorResponse, as the #578 capture proxy recorded it, and OpenAI's shape (vLLM >=0.10.1)
FLAT = json.dumps({"object": "error", "message": VLLM_SAID, "type": "BadRequestError", "param": None, "code": 400}).encode()
NESTED = json.dumps({"error": {"message": VLLM_SAID, "type": "BadRequestError", "param": None, "code": 400}}).encode()

# The fake CLI: each body in FAKE_CALLS goes to the route as a chat-completions call, then the events
# Qwen Code printed for a failed run, with FAKE_SAYS as its message, and exit 1.
_CLI = r'''
import json, os, sys, urllib.error, urllib.request
for body in json.loads(os.environ["FAKE_CALLS"]):
    req = urllib.request.Request(os.environ["OPENAI_BASE_URL"] + "/chat/completions", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                          "content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError as e:
        e.read()
says, sid = os.environ["FAKE_SAYS"], "9c87656f-c69b-48cb-8b6d-b0eecd6b670f"
for ev in ({"type": "system", "subtype": "init", "session_id": sid, "model": "qwen3-4b"},
           {"type": "assistant", "session_id": sid, "parent_tool_use_id": None,
            "message": {"type": "message", "role": "assistant", "model": "qwen3-4b",
                        "content": [{"type": "text", "text": says}], "stop_reason": None}},
           {"type": "result", "subtype": "error_during_execution", "session_id": sid, "is_error": True,
            "num_turns": 1, "usage": {"input_tokens": 0, "output_tokens": 0}, "error": {"message": says}}):
    print(json.dumps(ev), flush=True)
sys.exit(1)
'''


def _call(stream_options: bool) -> dict:
    body = {"model": "qwen3-4b", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    if stream_options:
        body["stream_options"] = {"include_usage": True}
    return body


class _Provider(BaseHTTPRequestHandler):
    """Refuses with `refusal` every call it is told to refuse; answers a one-word stream otherwise."""
    refusal = FLAT
    refuse = staticmethod(lambda body: True)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if type(self).refuse(body):
            out, code, ctype = type(self).refusal, 400, "application/json"
        else:
            chunk = {"id": "c1", "object": "chat.completion.chunk", "model": "qwen3-4b",
                     "choices": [{"index": 0, "delta": {"content": "DONE"}, "finish_reason": "stop"}]}
            out, code, ctype = b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n", 200, "text/event-stream"
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def _turn(tmp_path, refusal: bytes, refuse, calls: list[dict], says: str) -> dict:
    handler = type("Provider", (_Provider,), {"refusal": refusal, "refuse": staticmethod(refuse)})
    up = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    cli = tmp_path / "fake_qwen.py"
    cli.write_text(_CLI)
    env = {**os.environ, "FAKE_CALLS": json.dumps(calls), "FAKE_SAYS": says}
    _build_qwen("openai-api", Auth(api_key="sk-local", base_url=f"http://127.0.0.1:{up.server_address[1]}/v1"),
                "qwen3-4b", "hi", str(tmp_path), env)
    tid = f"t-{time.time()}"
    _turns[tid] = {"status": "running", "events": [], "result": "", "done": False,
                   "started": time.time(), "backend": "qwen", "model": "qwen3-4b"}
    try:
        _run_turn_bg(tid, [sys.executable, str(cli)], env, str(tmp_path), _claude_passthrough, "qwen3-4b",
                     timeout_seconds=30)
        return _turns[tid]
    finally:
        _turns.pop(tid, None)
        up.shutdown()


def test_a_refusal_the_cli_could_not_read_is_the_turns_reason(tmp_path):
    """The bug: the reason was Qwen Code's "API Error: 400 status code (no body)"."""
    rec = _turn(tmp_path, FLAT, lambda b: True, [_call(True)], "[API Error: 400 status code (no body)]")
    assert rec["status"] == "failed"
    assert rec["error"] == f"The model provider refused the request (400: {VLLM_SAID})"


def test_a_cli_that_read_the_refusal_keeps_its_own_sentence(tmp_path):
    """OpenAI's shape (vLLM >=0.10.1): Qwen Code says the reason itself, and its sentence stands
    as it did before #612."""
    says = f"[API Error: 400 {VLLM_SAID}]"
    rec = _turn(tmp_path, NESTED, lambda b: True, [_call(True)], says)
    assert rec["status"] == "failed"
    assert VLLM_SAID in rec["error"] and "The model provider refused" not in rec["error"]


def test_a_refusal_the_relay_repaired_is_not_the_reason_for_a_later_failure(tmp_path):
    """The provider refuses the call with stream_options and answers it without (the relay's own
    one-time retry repairs it); the CLI then fails for a reason of its own. The repaired refusal was
    left on the route before #612, and is not what this turn failed of."""
    says = "Error: the tool registry failed to load"
    rec = _turn(tmp_path, FLAT, lambda b: "stream_options" in b, [_call(True)], says)
    assert rec["status"] == "failed"
    assert "Please reduce the length" not in rec["error"]
    assert "tool registry failed to load" in rec["error"]


def test_a_later_refusal_after_an_answer_is_still_the_reason(tmp_path):
    """Clearing on an answer forgets only what came before it: the turn's last call refused is
    still read, after an answered one on the same route."""
    calls = [_call(False), {**_call(False), "messages": [{"role": "user", "content": "too long"}]}]
    rec = _turn(tmp_path, FLAT, lambda b: "too long" in json.dumps(b), calls,
                "[API Error: 400 status code (no body)]")
    assert rec["error"] == f"The model provider refused the request (400: {VLLM_SAID})"


def test_no_route_or_no_words_leaves_the_reason_to_the_cli():
    assert _relay_refusal_unsaid({}, "anything") == ""                    # the turn did not ride the relay
    assert _relay_refusal_unsaid({"X": "not-a-relay-token"}, "") == ""
