"""Prompt cache breakpoints on a Claude chat request (2026-10-25). vibe, docker-agent and fast-agent drive Claude
through OpenAI chat only and set no cache_control, so no Claude pair of the 0.37.0 matrix read a cached token on
any connection: every call of an agent loop paid for its whole prompt. On their routes the relay sets the two
breakpoints it sets on a Messages request."""
import json
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

MARK = {"type": "ephemeral"}
LOOP = {"model": "anthropic/claude-sonnet-4.6", "stream": True, "tools": [{"type": "function", "function": {
    "name": "write_file", "parameters": {"type": "object", "properties": {}}}}], "messages": [
    {"role": "system", "content": "You are a helpful agent."},
    {"role": "user", "content": "Create hello.txt"},
    {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "write_file", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "written"}]}


def _marks(doc: dict) -> list[tuple[int, str]]:
    return [(i, m["role"]) for i, m in enumerate(doc["messages"]) if isinstance(m.get("content"), list)
            and any(p.get("cache_control") == MARK for p in m["content"])]


def test_the_system_message_and_the_last_message_carry_a_breakpoint():
    doc = json.loads(server._with_chat_cache(json.dumps(LOOP).encode()))
    assert _marks(doc) == [(0, "system"), (3, "tool")]
    assert doc["messages"][0]["content"] == [{"type": "text", "text": "You are a helpful agent.", "cache_control": MARK}]
    assert doc["messages"][3]["content"][0]["text"] == "written"
    assert doc["messages"][2] == LOOP["messages"][2] and doc["tools"] == LOOP["tools"]


def test_text_parts_take_it_on_their_last_part():
    body = dict(LOOP, messages=[{"role": "system", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
                                {"role": "user", "content": [{"type": "text", "text": "hi"}]}])
    doc = json.loads(server._with_chat_cache(json.dumps(body).encode()))
    assert doc["messages"][0]["content"] == [{"type": "text", "text": "a"}, {"type": "text", "text": "b", "cache_control": MARK}]
    assert doc["messages"][1]["content"] == [{"type": "text", "text": "hi", "cache_control": MARK}]


def test_left_as_it_came():
    own = json.dumps(dict(LOOP, messages=[{"role": "system", "content": [
        {"type": "text", "text": "x", "cache_control": MARK}]}, {"role": "user", "content": "hi"}])).encode()
    assert server._with_chat_cache(own) is own                               # the client's own policy
    other = json.dumps(dict(LOOP, model="openai/gpt-5.4")).encode()
    assert server._with_chat_cache(other) is other                           # not Claude
    image = json.dumps(dict(LOOP, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}])).encode()
    assert server._with_chat_cache(image) is image                           # nothing to mark
    assert server._with_chat_cache(b"not json claude") == b"not json claude"
    ended = dict(LOOP, messages=LOOP["messages"][:3])                        # ends on the model's own message
    assert _marks(json.loads(server._with_chat_cache(json.dumps(ended).encode()))) == [(0, "system")]


def _upstream(refuse_marks: bool = False):
    got: list[bytes] = []

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["content-length"]))
            got.append(raw)
            if refuse_marks and b"cache_control" in raw:
                err = (b'{"error": {"message": "Unrecognized request argument supplied: '
                       b'messages[0].content[0].cache_control", "type": "invalid_request_error"}}')
                self.send_response(400)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
                return
            ok = json.dumps({"object": "chat.completion", "model": json.loads(raw)["model"], "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "DONE"}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(ok)))
            self.end_headers()
            self.wfile.write(ok)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    return up, got


def _post(base: str, tok: str, body: dict) -> dict:
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
        headers={"authorization": f"Bearer {tok}", "content-type": "application/json"}), timeout=10).read())


def _forwarded(body: dict = None, **route) -> bytes:
    up, got = _upstream()
    try:
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key", **route)
        _post(base, tok, body or dict(LOOP, stream=False))
    finally:
        up.shutdown()
    return got[0]


def test_only_the_upstreams_measured_to_read_them_back_are_sent_them():
    assert server._chat_cache_reads("https://openrouter.ai/api/v1")
    assert server._chat_cache_reads("https://ai-gateway.vercel.sh/v1")
    for base in ("https://api.anthropic.com/v1", "https://api.tokenrouter.com/v1", "https://api.openai.com/v1",
                 "https://proxy.internal/openai/v1", "http://127.0.0.1:9/v1", ""):
        assert not server._chat_cache_reads(base), base


def test_on_a_route_that_asks_the_provider_gets_the_breakpoints(monkeypatch):
    monkeypatch.setattr(server, "_CHAT_CACHE_HOSTS", frozenset({"127.0.0.1"}))   # the test upstream reads them
    assert _marks(json.loads(_forwarded(chat_cache=True))) == [(0, "system"), (3, "tool")]
    assert _marks(json.loads(_forwarded())) == []                            # every other route as before


def test_an_upstream_that_does_not_read_them_gets_the_clients_own_body():
    # Anthropic's OpenAI-compatible endpoint cached nothing and TokenRouter wrote entries no call read
    body = dict(LOOP, stream=False)
    assert _forwarded(body, chat_cache=True) == _forwarded(body)


def test_a_model_that_is_not_claude_leaves_byte_for_byte_as_it_would_without_the_flag(monkeypatch):
    monkeypatch.setattr(server, "_CHAT_CACHE_HOSTS", frozenset({"127.0.0.1"}))
    for model in ("openai/gpt-5.4", "gemini-3.5-flash", "deepseek-v4.1-flash"):
        body = dict(LOOP, model=model, stream=False)
        assert _forwarded(body, chat_cache=True) == _forwarded(body), model


def test_a_server_that_refuses_the_field_is_sent_none_for_that_model_from_then_on(monkeypatch):
    monkeypatch.setattr(server, "_CHAT_CACHE_HOSTS", frozenset({"127.0.0.1"}))
    up, got = _upstream(refuse_marks=True)
    try:
        base, tok = server._hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-key",
                                               chat_cache=True)
        assert _post(base, tok, dict(LOOP, stream=False))["choices"][0]["message"]["content"] == "DONE"
        assert [b"cache_control" in b for b in got] == [True, False]          # refused, then sent without
        bare = json.loads(got[1])
        assert bare["messages"] == LOOP["messages"]                            # exactly the client's own
        _post(base, tok, dict(LOOP, stream=False))
        assert b"cache_control" not in got[2]                                  # learned for this model
        _post(base, tok, dict(LOOP, model="anthropic/claude-opus-4.8", stream=False))
        assert b"cache_control" in got[3]                                      # another model is still asked
    finally:
        up.shutdown()


def test_the_three_chat_bases_routes_ask():
    auth = server.Auth(base_url="https://up.example/v1", api_key="k")
    for build in (server._build_vibe, server._build_docker_agent, server._build_fast_agent):
        env: dict = {}
        cwd = tempfile.mkdtemp(prefix="chat-cache-")
        build("openai-api", auth, "claude-sonnet-4.6", "hi", cwd, env)
        toks = [v for v in env.values() if isinstance(v, str) and v.startswith("hr-relay-")]
        toks += [t for t in server._HERMES_RELAY["routes"] if any(t in p.read_text(errors="ignore")
                 for p in Path(cwd).rglob("*") if p.is_file())]
        routes = [server._HERMES_RELAY["routes"].get(t) for t in toks]
        assert routes and all(r is not None and r[2].get("chat_cache") is True for r in routes), build.__name__
