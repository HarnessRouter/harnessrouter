"""The relay sees every provider answer, so it can count the tokens for a backend whose CLI
reports none (kimi, aider): read off the bytes as they pass, summed over the turn's calls, stamped
on a result event that arrived without usage. Same mechanism as the served model."""
import json
import pathlib
import sys
import threading
import urllib.request
import uuid
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


def test_a_responses_answer_is_netted_and_its_stream_is_read_inside_the_response():
    """The Responses API names its fields as Messages does and means them as chat does: input_tokens
    is gross, the cached part under input_tokens_details. A stream carries the usage only inside the
    response, on response.completed. Measured on OpenAI 2026-10-09 (4021 in, 3840 cached); before,
    a streamed Responses call counted nothing and a whole answer counted every cached token fresh."""
    usage = {"input_tokens": 4021, "input_tokens_details": {"cache_write_tokens": 0, "cached_tokens": 3840},
             "output_tokens": 5, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 4026}
    want = {"input_tokens": 181, "output_tokens": 5, "cache_read_tokens": 3840}
    assert rs._usage_in_doc({"id": "resp_1", "object": "response", "usage": usage}) == want
    call: dict = {}
    for line in (b'data: {"type":"response.created","response":{"id":"resp_1","usage":null}}',
                 b'data: {"type":"response.output_text.delta","delta":"OK"}',
                 b'data: {"type":"response.completed","response":{"id":"resp_1","usage":' + json.dumps(usage).encode() + b'}}'):
        call.update(rs._usage_in_sse_line(line))
    assert call == want


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


def _google_call(prompt, answer, thoughts=None, tool_use=None, cached=0):
    meta = {"promptTokenCount": prompt, "candidatesTokenCount": answer, "cachedContentTokenCount": cached}
    if thoughts is not None:
        meta["thoughtsTokenCount"] = thoughts
    if tool_use is not None:
        meta["toolUsePromptTokenCount"] = tool_use
    meta["totalTokenCount"] = prompt + answer + (thoughts or 0) + (tool_use or 0)
    return {"usageMetadata": meta}


def _on_route(flags, docs):
    """What the relay folds onto a route as each call's answer passes (usage and thinking count)."""
    for doc in docs:
        rs._usage_add(flags, rs._usage_in_doc(doc))
        rs._thinking_add(flags, rs._thinking_tokens_in(doc))
    tok = "hr-relay-" + uuid.uuid4().hex
    rs._HERMES_RELAY["routes"][tok] = ("https://generativelanguage.googleapis.com", "real", flags)
    return tok


def _gemini_result(stats):
    return rs._gemini_to_claude({"type": "result", "status": "success", "stats": stats}, {"final": "ok"})[0]


def test_a_gemini_turn_is_priced_off_googles_own_count_and_the_route_sums_its_calls():
    """#690: on a gemini-cli turn (a google_native route) the relay's usage replaces the CLI's stats
    whenever the relay saw the turn, summed over the turn's calls (three here, the last one without
    thinking). Without grounding the stats' fallback agrees; the grounded turn below is where they part."""
    calls = [_google_call(4000, 20, thoughts=180, cached=3000), _google_call(4300, 7, thoughts=60, cached=4000),
             _google_call(4400, 2)]
    tok = _on_route({"google_native": True}, calls)
    try:
        # the CLI's stats for the same turn: output_tokens is the answers alone
        ev = _gemini_result({"total_tokens": 12969, "input_tokens": 12700, "output_tokens": 29, "cached": 7000})
        rs._fill_relay_usage(ev, {"GEMINI_API_KEY": tok})
        assert ev["usage"] == {"input_tokens": 5700, "output_tokens": 269, "cache_read_tokens": 7000}
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_grounded_gemini_turn_prices_exactly_on_the_relay_path():
    """A turn grounded with Google Search: the tool-use prompt is prompt-side, so it is not output.
    The stats fold it into total_tokens (their fallback's known limit); the relay's count does not."""
    call = _google_call(900, 40, thoughts=120, tool_use=2500)
    assert rs._usage_fields(call["usageMetadata"]) == {"input_tokens": 900, "output_tokens": 160, "cache_read_tokens": 0}
    tok = _on_route({"google_native": True}, [call])
    try:
        ev = _gemini_result({"total_tokens": 3560, "input_tokens": 900, "output_tokens": 40})
        assert ev["usage"]["output_tokens"] == 2660            # the stats alone count the tool-use prompt
        rs._fill_relay_usage(ev, {"GEMINI_API_KEY": tok})
        assert ev["usage"] == {"input_tokens": 900, "output_tokens": 160, "cache_read_tokens": 0}
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_gemini_turn_with_thinking_off_is_unchanged():
    call = _google_call(500, 9)
    assert rs._usage_fields(call["usageMetadata"]) == {"input_tokens": 500, "output_tokens": 9, "cache_read_tokens": 0}
    tok = _on_route({"google_native": True}, [call])
    try:
        ev = _gemini_result({"total_tokens": 509, "input_tokens": 500, "output_tokens": 9})
        assert (ev["usage"]["input_tokens"], ev["usage"]["output_tokens"]) == (500, 9)
        rs._fill_relay_usage(ev, {"GEMINI_API_KEY": tok})
        assert (ev["usage"]["input_tokens"], ev["usage"]["output_tokens"]) == (500, 9)
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_route_that_is_not_googles_still_keeps_a_clis_own_split_count():
    """Only the google_native route changes: elsewhere a CLI's own count with a cache split stands."""
    tok = _on_route({}, [{"usage": {"prompt_tokens": 50, "completion_tokens": 9,
                                    "prompt_tokens_details": {"cached_tokens": 40}}}])
    try:
        ev = {"type": "result", "usage": {"input_tokens": 10, "output_tokens": 8, "cache_read_tokens": 40}}
        rs._fill_relay_usage(ev, {"OPENAI_API_KEY": tok})
        assert ev["usage"]["output_tokens"] == 8
    finally:
        rs._HERMES_RELAY["routes"].pop(tok, None)


def test_the_thinking_count_never_exceeds_the_output_in_any_shape():
    """One invariant across the shapes the relay reads: the provider's thinking count is part of the
    output that prices the turn, so reasoning_tokens <= output_tokens on the result the gateway reads
    (the gateway copies both into the Responses usage as given). Google's was the exception (#690)."""
    shapes = {
        "chat": ({"usage": {"prompt_tokens": 30, "completion_tokens": 50,
                            "completion_tokens_details": {"reasoning_tokens": 41}}}, "OPENAI_API_KEY", {}),
        "responses": ({"response": {"usage": {"input_tokens": 30, "input_tokens_details": {"cached_tokens": 0},
                                              "output_tokens": 50, "output_tokens_details": {"reasoning_tokens": 41}}}},
                      "OPENAI_API_KEY", {}),
        "google": (_google_call(30, 9, thoughts=41), "GEMINI_API_KEY", {"google_native": True}),
        "google grounded": (_google_call(30, 9, thoughts=41, tool_use=900), "GEMINI_API_KEY", {"google_native": True}),
    }
    for name, (doc, var, flags) in shapes.items():
        assert rs._thinking_tokens_in(doc) <= rs._usage_in_doc(doc)["output_tokens"], name
        tok = _on_route(dict(flags), [doc, doc])
        try:
            route = rs._HERMES_RELAY["routes"][tok][2]
            ev = {"type": "result", "usage": {}}
            rs._fill_relay_usage(ev, {var: tok})
            rs._stamp_thinking(ev, {"reasoning": {"routes": [route]}})
            assert ev["usage"]["reasoning_tokens"] == 82, name
            assert ev["usage"]["reasoning_tokens"] <= ev["usage"]["output_tokens"], name
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
    """The stamp fills an EMPTY usage, and replaces a CLI count only when the provider's carries a
    cache split the CLI's lacks (_fill_relay_usage, pinned in test_messages_route); a CLI's own
    split count (codex, claude) is the record. Pinned on the source of the run loop, which needs
    a live process to exercise: both result sites go through the one helper."""
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    # the run loop's _settle (its stream, its eof path, a budget's stop and a turn that died
    # before it said anything), the hermes and codex app-server drivers
    assert src.count("_fill_relay_usage(ev, env)") == 3
    assert src.count("_settle(ev)") == 2 and src.count("_settle(result_ev)") == 2
    assert src.count('if ev.get("type") == "result" and not ev.get("usage"):') == 0
