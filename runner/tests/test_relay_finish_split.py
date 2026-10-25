"""An answer's last words in the chunk that carries the finish reason reach docker-agent (2026-10-25).

docker-agent 1.152.0 returns on a stop finish before it reads the same chunk's text, and TokenRouter puts
an answer's last words in that chunk: deepseek-v4.1-flash streamed "M1-deepseek-v4.1-flash" whole and the
recorded answers were "M1-deepseek-v4.1", "M1-deepseek-v", "M1-deepseek-v4" and "M1-deepseek-v4.". On
docker-agent's route the relay sends such a chunk as two events, the text and then the finish."""
import json
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _chunk(content=None, finish=None, usage=None, tool_calls=None):
    delta = {"role": "assistant"}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    doc = {"id": "c1", "object": "chat.completion.chunk", "model": "deepseek-v4-1-flash-260910",
           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        doc["usage"] = usage
    return b"data: " + json.dumps(doc).encode()


USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def _events(blob: bytes) -> list[dict]:
    return [json.loads(l[5:]) for l in blob.split(b"\n") if l.startswith(b"data:") and l.strip() != b"data: [DONE]"]


def test_a_finish_that_carries_text_becomes_the_text_then_the_finish():
    out = _events(server._split_finish_content_line(_chunk(".1-flash", "stop", USAGE)))
    assert len(out) == 2
    text, finish = out
    assert text["choices"][0]["delta"]["content"] == ".1-flash" and text["choices"][0]["finish_reason"] is None
    assert "usage" not in text
    assert finish["choices"][0]["finish_reason"] == "stop" and "content" not in finish["choices"][0]["delta"]
    assert finish["usage"] == USAGE and finish["id"] == text["id"] == "c1"


def test_everything_else_is_left_as_it_came():
    for line in (_chunk("M"),                                              # text, no finish
                 _chunk("", "stop", USAGE),                                # a finish with no text
                 _chunk(None, "tool_calls"),
                 _chunk("x", "stop", tool_calls=[{"index": 0, "id": "t1", "type": "function",
                                                   "function": {"name": "f", "arguments": "{}"}}]),
                 b"data: [DONE]", b": keep-alive", b"data: not json finish_reason"):
        assert server._split_finish_content_line(line) is line


def _read_like_docker_agent(sse: bytes) -> str:
    """docker-agent's reading: a stop finish ends the answer before that chunk's text is taken."""
    text = ""
    for ev in _events(sse):
        ch = (ev.get("choices") or [{}])[0]
        if ch.get("finish_reason") in ("stop", "length"):
            break
        text += (ch.get("delta") or {}).get("content") or ""
    return text


def _route(**flags):
    sse = b"\n\n".join([_chunk("M"), _chunk("1-deepseek-v4"), _chunk(".1-flash", "stop", USAGE), b"data: [DONE]"]) + b"\n\n"

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(sse)))
            self.end_headers()
            self.wfile.write(sse)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key", **flags)
    body = json.dumps({"model": "deepseek/deepseek-v4.1-flash", "stream": True,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    got = urllib.request.urlopen(urllib.request.Request(
        base + "/chat/completions", data=body, method="POST",
        headers={"authorization": f"Bearer {tok}", "content-type": "application/json"}), timeout=10).read()
    up.shutdown()
    return got


def test_on_a_route_that_asks_the_whole_answer_reaches_a_reader_that_stops_at_the_finish():
    assert _read_like_docker_agent(_route(split_finish_content=True)) == "M1-deepseek-v4.1-flash"
    assert _read_like_docker_agent(_route()) == "M1-deepseek-v4"          # what docker-agent kept before


def test_docker_agent_s_route_asks():
    env: dict = {}
    server._build_docker_agent("openai-api", server.Auth(base_url="https://up.example/v1", api_key="k"),
                               "gpt-5.4", "hi", tempfile.mkdtemp(prefix="da-route-"), env)
    tok = next((v for v in env.values() if isinstance(v, str) and v.startswith("hr-relay-")), "")
    route = server._HERMES_RELAY["routes"].get(tok)
    assert route is not None and route[2].get("split_finish_content") is True
