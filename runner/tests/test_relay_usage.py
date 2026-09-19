"""The relay sees every provider answer, so it can count the tokens for a backend whose CLI
reports none (kimi, aider): read off the bytes as they pass, summed over the turn's calls, stamped
on a result event that arrived without usage. Same mechanism as the served model."""
import json
import pathlib
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def test_openai_usage_is_netted_to_fresh_input_like_codex_and_cline():
    u = rs._usage_fields({"prompt_tokens": 6410, "completion_tokens": 20, "total_tokens": 6430,
                          "prompt_tokens_details": {"cached_tokens": 5632}})
    assert u == {"input_tokens": 778, "output_tokens": 20, "cache_read_tokens": 5632}


def test_anthropic_usage_is_already_net_and_keeps_both_cache_counters():
    u = rs._usage_fields({"input_tokens": 12, "output_tokens": 7, "cache_read_input_tokens": 900,
                          "cache_creation_input_tokens": 300})
    assert u == {"input_tokens": 12, "output_tokens": 7, "cache_read_tokens": 900,
                 "cache_write_tokens": 300}


def test_gemini_usage_metadata_is_read_too():
    u = rs._usage_in_doc({"usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 9,
                                            "cachedContentTokenCount": 40}})
    assert u == {"input_tokens": 60, "output_tokens": 9, "cache_read_tokens": 40}
    assert rs._usage_fields({"weird": 1}) == {} and rs._usage_fields(None) == {}


def test_an_anthropic_stream_is_the_union_of_message_start_and_message_delta():
    start = b'data: {"type":"message_start","message":{"id":"m","usage":{"input_tokens":25,"output_tokens":1,"cache_read_input_tokens":0}}}'
    delta = b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":15}}'
    call: dict = {}
    for line in (start, b'event: ping', delta, b'data: [DONE]'):
        call.update(rs._usage_in_sse_line(line))
    assert call == {"input_tokens": 25, "output_tokens": 15, "cache_read_tokens": 0}


def test_an_openai_stream_reports_usage_only_on_its_last_chunk():
    lines = [b'data: {"choices":[{"delta":{"content":"hi"}}],"usage":null}',
             b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2}}',
             b'data: [DONE]']
    call: dict = {}
    for line in lines:
        call.update(rs._usage_in_sse_line(line))
    assert call == {"input_tokens": 10, "output_tokens": 2, "cache_read_tokens": 0}


def test_a_turn_is_many_calls_and_the_route_sums_them():
    flags: dict = {}
    rs._usage_add(flags, {"input_tokens": 10, "output_tokens": 2, "cache_read_tokens": 0})
    rs._usage_add(flags, {})
    rs._usage_add(flags, {"input_tokens": 3, "output_tokens": 5, "cache_read_tokens": 10})
    assert flags["usage"] == {"input_tokens": 13, "output_tokens": 7, "cache_read_tokens": 10}
    tok = "hr-relay-" + "u" * 32
    rs._HERMES_RELAY["routes"][tok] = ("https://api.example/v1", "real", flags)
    try:
        assert rs._relay_usage({"HOME": "/x", "OPENAI_API_KEY": tok}) == flags["usage"]
        assert rs._relay_usage({"OPENAI_API_KEY": "sk-direct"}) == {}
        flags.clear()
        assert rs._relay_usage({"OPENAI_API_KEY": tok}) == {}
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def _upstream(handler):
    up = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    return up


def test_usage_is_counted_off_a_json_answer_and_a_streamed_one_through_the_live_relay():
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            if body.get("stream"):
                chunks = [b'data: {"id":"c","object":"chat.completion.chunk","model":"m","choices":[{"delta":{"content":"hi"},"finish_reason":null}],"usage":null}\n\n',
                          b'data: {"id":"c","object":"chat.completion.chunk","model":"m","choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":40,"completion_tokens":4,"prompt_tokens_details":{"cached_tokens":30}}}\n\n',
                          b'data: [DONE]\n\n']
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for c in chunks:
                    self.wfile.write(c)
                    self.wfile.flush()
                return
            data = json.dumps({"id": "x", "object": "chat.completion", "model": "m",
                               "choices": [{"message": {"role": "assistant", "content": "hi"},
                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 100, "completion_tokens": 7,
                                         "prompt_tokens_details": {"cached_tokens": 60}}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    up = _upstream(Upstream)
    try:
        base, tok = rs._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        env = {"OPENAI_API_KEY": tok}
        for stream in (False, True):
            body = json.dumps({"model": "m", "stream": stream,
                               "messages": [{"role": "user", "content": "hi"}]}).encode()
            req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                         headers={"authorization": f"Bearer {tok}",
                                                  "content-type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        # 100-60 fresh + 40-30 fresh; 7 + 4 out; 60 + 30 cached
        assert rs._relay_usage(env) == {"input_tokens": 50, "output_tokens": 11, "cache_read_tokens": 90}
    finally:
        up.shutdown()
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_backend_that_reports_its_own_usage_keeps_it():
    """The stamp fills an EMPTY usage only: a CLI's own count (codex, claude, goose) is the
    record, and the relay's count would double nothing and replace nothing. Pinned on the source
    of the run loop, which needs a live process to exercise."""
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    assert src.count('if ev.get("type") == "result" and not ev.get("usage"):') == 2
