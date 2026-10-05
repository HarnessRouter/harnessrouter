"""How much a model thinks on a turn (runner/reasoning.py and where the runner applies it).

Every expectation here is a cell of the measurement of 2026-10-05 (docs/support-matrix-notes.md, "How
much a model thinks"): one question at every level through each route, judged by the provider's own
reasoning-token count. The traps are the tests: a level a model lacks is REFUSED by the provider, and
the field that works is not the same on every route.
"""
import http.client
import http.server
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reasoning  # noqa: E402
import server as rs  # noqa: E402

VERCEL = "https://ai-gateway.vercel.sh/v1"
TOKENROUTER = "https://api.tokenrouter.com/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
GOOGLE = "https://generativelanguage.googleapis.com/v1beta/openai"
OPENAI = "https://api.openai.com/v1"


def _apply(shape, base, model, asked, **extra):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}], **extra}).encode()
    out, applied = reasoning.apply(body, shape, base, asked)
    doc = json.loads(out)
    return applied, doc, out is body


@pytest.mark.parametrize("shape,base,model,asked,applied,sent", [
    # OpenAI: `minimal` is refused by gpt-5.4 ("Unsupported value") and by every route's Responses API
    ("chat", VERCEL, "openai/gpt-5.4", "minimal", "low", {"reasoning_effort": "low"}),
    ("chat", OPENAI, "gpt-5.4-2026-03-05", "none", "none", {"reasoning_effort": "none"}),
    ("responses", OPENAI, "gpt-5.4", "xhigh", "xhigh", {"reasoning": {"effort": "xhigh"}}),
    # gpt-6.1-sol and gpt-6-astra cannot be turned off: "does not support 'none' with this model"
    ("chat", TOKENROUTER, "openai/gpt-6.1-sol", "none", "low", {"reasoning_effort": "low"}),
    ("responses", OPENROUTER, "openai/gpt-6-astra", "none", "low", {"reasoning": {"effort": "low"}}),
    # Gemini through Vercel takes `reasoning_effort: none` as "think more"; Google's own setting works
    ("chat", VERCEL, "google/gemini-3.5-flash", "none", "none",
     {"providerOptions": {"google": {"thinkingConfig": {"thinkingBudget": 0}}}}),
    ("chat", VERCEL, "google/gemini-3-flash", "minimal", "minimal",
     {"providerOptions": {"google": {"thinkingConfig": {"thinkingLevel": "minimal"}}}}),
    # ...and the 3.8 flash model refuses both a zero budget and `minimal`: its lowest level is low
    ("chat", VERCEL, "google/gemini-3.8-flash", "none", "low",
     {"providerOptions": {"google": {"thinkingConfig": {"thinkingLevel": "low"}}}}),
    # through TokenRouter the field is ignored and the setting rides `extra_body`
    ("chat", TOKENROUTER, "google/gemini-3.5-flash", "high", "high",
     {"extra_body": {"google": {"thinking_config": {"thinking_level": "high"}}}}),
    # OpenRouter honours the field and refuses `none` for every Gemini; `minimal` is its zero
    ("chat", OPENROUTER, "google/gemini-3.5-flash", "none", "minimal", {"reasoning_effort": "minimal"}),
    ("chat", GOOGLE, "gemini-3.1-pro-preview", "none", "low", {"reasoning_effort": "low"}),
    # Claude over Chat Completions; the 5.5 line cannot be turned off through OpenRouter
    ("chat", VERCEL, "anthropic/claude-haiku-4.5", "medium", "medium", {"reasoning_effort": "medium"}),
    ("chat", OPENROUTER, "anthropic/claude-sonnet-5.5", "none", "low", {"reasoning_effort": "low"}),
    # a model that cannot be turned off gets its lowest level for `none`
    ("chat", TOKENROUTER, "x-ai/grok-4.6", "none", "minimal", {"reasoning_effort": "minimal"}),
    ("chat", TOKENROUTER, "deepseek/deepseek-v4-pro", "none", "low", {"reasoning_effort": "low"}),
    # on or off only: any level that asks for thinking is "on"; Mistral through Vercel refuses `low`
    ("chat", VERCEL, "alibaba/qwen3.7-max", "low", "high", {"reasoning_effort": "high"}),
    ("chat", VERCEL, "mistral/mistral-medium-3.5", "low", "high", {"reasoning_effort": "high"}),
])
def test_a_level_is_written_the_way_the_route_and_the_model_take_it(shape, base, model, asked, applied, sent):
    got, doc, same = _apply(shape, base, model, asked)
    assert got == applied and not same
    for key, value in sent.items():
        assert doc[key] == value
    if "providerOptions" in sent or "extra_body" in sent:
        assert "reasoning_effort" not in doc


@pytest.mark.parametrize("shape,base,model", [
    ("chat", VERCEL, "zai/glm-5.3"),                       # no setting changed what it did
    ("chat", "https://llm.example/v1", "gpt-5.4"),         # a route that was not measured
    ("chat", TOKENROUTER, "google/gemini-3.8-flash"),      # answered to nothing through this door
    ("responses", VERCEL, "anthropic/claude-haiku-4.5"),   # that shape has no setting for the family
    ("chat", OPENROUTER, "meta-llama/llama-3.3-70b-instruct"),
])
def test_an_unmeasured_model_or_route_gets_nothing_and_the_same_bytes(shape, base, model):
    body = json.dumps({"model": model, "messages": []}).encode()
    out, applied = reasoning.apply(body, shape, base, "high")
    assert out is body and applied == ""


def test_a_model_that_does_not_think_unless_asked_is_left_alone_for_none():
    """Google refuses `none` for the flash-lite models ("invalid argument") and they do not think by
    default, so nothing is sent and the turn still reads none."""
    got, doc, _ = _apply("chat", GOOGLE, "gemini-3.5-flash-lite", "none")
    assert got == "none" and "reasoning_effort" not in doc


def test_anthropic_messages_take_a_budget_or_an_effort_by_model():
    # the older model: a budget, out of max_tokens with half left to answer; an effort is refused
    got, doc, _ = _apply("messages", TOKENROUTER, "anthropic/claude-haiku-4.5", "high", max_tokens=8000)
    assert got == "high" and doc["thinking"] == {"type": "enabled", "budget_tokens": 4000}
    got, doc, same = _apply("messages", TOKENROUTER, "anthropic/claude-haiku-4.5", "low", max_tokens=1500)
    assert got == "" and same                                   # below the API's floor of 1024
    # the newer ones: adaptive with an effort ("...enabled is not supported for this model")
    got, doc, _ = _apply("messages", "https://api.anthropic.com", "claude-sonnet-4-6", "xhigh",
                         output_config={"format": "x"})
    assert doc["thinking"] == {"type": "adaptive"} and doc["output_config"] == {"format": "x", "effort": "max"}
    # off: `disabled`, except the 5.5 line, whose API names its own word; fable has no off at all
    assert _apply("messages", TOKENROUTER, "anthropic/claude-opus-5", "none")[1]["thinking"] == {"type": "disabled"}
    assert _apply("messages", TOKENROUTER, "anthropic/claude-sonnet-5.5", "none")[1]["thinking"] == {"type": "between_tools"}
    got, doc, _ = _apply("messages", TOKENROUTER, "anthropic/claude-fable-5.1", "none")
    assert got == "low" and doc["output_config"] == {"effort": "low"}


def test_googles_own_body_takes_a_level_or_a_zero_budget_never_both():
    body = json.dumps({"contents": [], "generationConfig": {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": -1}}}).encode()
    out, applied = reasoning.apply(body, "google", GOOGLE, "low", model="gemini-3.5-flash")
    assert applied == "low"
    assert json.loads(out)["generationConfig"]["thinkingConfig"] == {"includeThoughts": True, "thinkingLevel": "low"}
    out, applied = reasoning.apply(body, "google", GOOGLE, "none", model="gemini-3.5-flash")
    assert json.loads(out)["generationConfig"]["thinkingConfig"] == {"includeThoughts": True, "thinkingBudget": 0}


def test_nearest_never_turns_thinking_off_for_a_turn_that_asked_for_some():
    assert reasoning.nearest("low", ("none", "high")) == "high"
    assert reasoning.nearest("none", ("low", "high")) == "low"
    assert reasoning.nearest("medium", ("low", "high")) == "low"          # a tie goes down
    assert reasoning.nearest("xhigh", ("none", "low", "medium")) == "medium"
    assert reasoning.nearest("low", ("none",)) == "" and reasoning.nearest("bogus", ("low",)) == ""


def test_levels_are_named_only_for_models_that_were_measured():
    assert reasoning.levels_for("openai/gpt-5.4-mini") == ("none", "low", "medium", "high", "xhigh")
    assert reasoning.levels_for("claude-haiku-4-5-20251001") == ("none", "low", "medium", "high", "xhigh")
    assert "none" not in reasoning.levels_for("gpt-6.1-sol") and "none" not in reasoning.levels_for("grok-4.6")
    assert reasoning.levels_for("gemini-3.8-flash") == ("low", "medium", "high")
    for unmeasured in ("llama-3.3-70b", "glm-5.3", "grok-4.20", "qwen3.8-max", "nemotron-3-super", "jev-1.13", ""):
        assert reasoning.levels_for(unmeasured) == ()
    for model, levels in ((m, reasoning.levels_for(m)) for m in ("gpt-5.4", "grok-4.5", "kimi-k3", "hy3")):
        assert levels and all(lv in reasoning.LEVELS for lv in levels), model


# ── the relay ────────────────────────────────────────────────────────────────────────────────

class _Upstream:
    """A provider that records what it is sent and refuses whatever `refuse` says to."""

    def __init__(self, refuse=lambda doc: False):
        seen = self.seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers["content-length"]))
                seen.append(raw)
                if refuse(json.loads(raw)):
                    out, code = b'{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled."}}', 400
                else:
                    out, code = (b'{"id":"c","model":"m","choices":[{"message":{"role":"assistant","content":"ok"},'
                                 b'"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":9,'
                                 b'"completion_tokens_details":{"reasoning_tokens":7}}}'), 200
                self.send_response(code); self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def route(self, asked, monkeypatch):
        """A route to this provider for a turn that asked for `asked`, measured as OpenRouter is."""
        monkeypatch.setattr(reasoning, "route_of", lambda base: "openrouter")
        token = rs._TURN_THINKING.set({"asked": asked, "applied": "", "routes": []})
        try:
            relay, tok = rs._hermes_relay_route(f"http://127.0.0.1:{self.srv.server_port}/v1", "sk-real")
        finally:
            rs._TURN_THINKING.reset(token)
        return relay.removeprefix("http://").removesuffix("/v1"), tok


def _post(host, tok, doc):
    conn = http.client.HTTPConnection(host, timeout=10)
    try:
        raw = json.dumps(doc).encode()
        conn.request("POST", "/v1/chat/completions", body=raw,
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        return resp.status, resp.read(), raw
    finally:
        conn.close()


def test_a_turn_that_asked_for_no_level_sends_what_the_client_wrote(monkeypatch):
    up = _Upstream()
    host, tok = up.route("", monkeypatch)
    try:
        assert "effort" not in rs._HERMES_RELAY["routes"][tok][2]
        status, _, raw = _post(host, tok, {"model": "openai/gpt-5.4", "messages": [{"role": "user", "content": "hi"}]})
        assert status == 200 and up.seen == [raw]
    finally:
        up.srv.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)


def test_the_relay_writes_the_level_and_remembers_what_it_applied(monkeypatch):
    up = _Upstream()
    host, tok = up.route("minimal", monkeypatch)
    try:
        status, _, _ = _post(host, tok, {"model": "openai/gpt-5.4", "messages": [{"role": "user", "content": "hi"}]})
        assert status == 200 and json.loads(up.seen[0])["reasoning_effort"] == "low"
        flags = rs._HERMES_RELAY["routes"][tok][2]
        assert flags["effort_applied"] == {"openai/gpt-5.4": "low"}
        # a helper model on the same route that has no measured level is left alone, and said to be
        _post(host, tok, {"model": "meta-llama/llama-3.3-70b-instruct", "messages": []})
        assert "reasoning_effort" not in json.loads(up.seen[1])
        assert flags["effort_applied"]["meta-llama/llama-3.3-70b-instruct"] == ""
        assert flags["reasoning_tokens"] == 14                   # the provider's own count, both calls
        assert "reasoning_tokens" not in flags["usage"]          # the usage that prices a turn is untouched
    finally:
        up.srv.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_refused_level_never_fails_the_call_and_is_not_offered_again(monkeypatch):
    up = _Upstream(refuse=lambda doc: "reasoning_effort" in doc)
    host, tok = up.route("high", monkeypatch)
    try:
        doc = {"model": "openai/gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
        status, _, raw = _post(host, tok, doc)
        assert status == 200
        assert "reasoning_effort" in json.loads(up.seen[0]) and up.seen[1] == raw      # then as the client wrote it
        flags = rs._HERMES_RELAY["routes"][tok][2]
        assert flags["effort_applied"] == {"openai/gpt-5.4": ""} and flags["effort_refused:openai/gpt-5.4"]
        _post(host, tok, doc)
        assert len(up.seen) == 3 and up.seen[2] == raw                                 # one call, no level
    finally:
        up.srv.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_refusal_that_is_not_about_the_level_is_the_clients_to_see_and_blames_nothing(monkeypatch):
    up = _Upstream(refuse=lambda doc: True)
    host, tok = up.route("high", monkeypatch)
    try:
        status, _, raw = _post(host, tok, {"model": "openai/gpt-5.4", "messages": []})
        assert status == 400 and up.seen[1] == raw
        flags = rs._HERMES_RELAY["routes"][tok][2]
        assert "effort_refused:openai/gpt-5.4" not in flags and flags["effort_applied"] == {"openai/gpt-5.4": "high"}
    finally:
        up.srv.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)


# ── the turn's record, and the backends whose calls never pass the relay ──────────────────────

def _thinking(asked):
    return rs._TURN_THINKING.set({"asked": asked, "applied": "", "routes": []})


def test_the_result_says_what_was_asked_and_what_was_applied():
    """Read off the routes the turn registered, wherever the backend keeps its placeholder: pi and
    omp write theirs into a file, and a lookup through the turn's environment recorded "default"
    for a level that had been applied (the thinking column on a candidate, 2026-10-05)."""
    flags = {"effort": "minimal", "effort_applied": {"aux/model": "", "openai/gpt-5.4": "low"},
             "usage": {"input_tokens": 1, "output_tokens": 9}, "reasoning_tokens": 7}
    rec = {"model": "openai/gpt-5.4", "reasoning": {"asked": "minimal", "applied": "", "routes": [flags]}}
    ev = {"type": "result", "usage": {"input_tokens": 1, "output_tokens": 9}}
    rs._stamp_thinking(ev, rec)
    assert ev["reasoning"] == {"effort": "minimal", "applied": "low"} and ev["usage"]["reasoning_tokens"] == 7
    # nothing was applied (an unmeasured model, or a refusal): the record says so
    flags["effort_applied"] = {"openai/gpt-5.4": ""}
    ev = {"type": "result"}
    rs._stamp_thinking(ev, rec)
    assert ev["reasoning"] == {"effort": "minimal", "applied": "default"}
    # a backend that set its own CLI, with no route at all
    ev = {"type": "result"}
    rs._stamp_thinking(ev, {"model": "claude-haiku-4-5", "reasoning": {"asked": "high", "applied": "high", "routes": []}})
    assert ev == {"type": "result", "reasoning": {"effort": "high", "applied": "high"}}
    # a turn that asked for no level says nothing about one, and still carries the provider's count
    ev = {"type": "result"}
    rs._stamp_thinking(ev, {"model": "openai/gpt-5.4", "reasoning": {"asked": "", "applied": "", "routes": [flags]}})
    assert ev == {"type": "result", "usage": {"reasoning_tokens": 7}}


def test_a_turns_routes_are_remembered_without_its_environment():
    token = _thinking("low")
    tok = aux = ""
    try:
        _, tok = rs._hermes_relay_route("https://ai-gateway.vercel.sh/v1", "sk-real")
        _, aux = rs._hermes_relay_route("https://ai-gateway.vercel.sh/v1", "sk-real", aux=True)
        routes = rs._TURN_THINKING.get()["routes"]
        assert len(routes) == 1 and routes[0] is rs._HERMES_RELAY["routes"][tok][2] and routes[0]["effort"] == "low"
        assert "effort" not in rs._HERMES_RELAY["routes"][aux][2]          # a helper model's route
    finally:
        rs._TURN_THINKING.reset(token)
        rs._HERMES_RELAY["routes"].pop(tok, None); rs._HERMES_RELAY["routes"].pop(aux, None)


def test_claude_code_gets_its_own_switch_by_model():
    token = _thinking("high")
    try:
        assert rs._claude_thinking_env("claude-sonnet-5-5")["CLAUDE_CODE_EFFORT_LEVEL"] == "high"
        env = rs._claude_thinking_env("claude-haiku-4-5-20251001")      # refuses an effort; takes a budget
        assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "auto" and env["MAX_THINKING_TOKENS"] == "16384"
        assert rs._TURN_THINKING.get()["applied"] == "high"
    finally:
        rs._TURN_THINKING.reset(token)
    token = _thinking("none")
    try:
        assert rs._claude_thinking_env("claude-sonnet-5-5")["MAX_THINKING_TOKENS"] == "0"
    finally:
        rs._TURN_THINKING.reset(token)
    token = _thinking("")
    try:                                                                # no level asked: as before
        assert rs._claude_thinking_env("claude-sonnet-5-5") == {"CLAUDE_CODE_EFFORT_LEVEL": "auto"}
        assert rs._claude_thinking_env("claude-opus-4-8") == {"CLAUDE_CODE_EFFORT_LEVEL": "auto", "MAX_THINKING_TOKENS": "0"}
    finally:
        rs._TURN_THINKING.reset(token)


def test_codex_writes_the_level_into_its_own_config(tmp_path):
    def cfg(model, asked):
        token = rs._TURN_THINKING.set({"asked": asked, "applied": "", "routes": []})
        try:
            home = tmp_path / f"{model}-{asked or 'unset'}"
            home.mkdir()
            d = rs._codex_prepare_env("openai", rs.Auth(api_key="k", base_url="https://api.openai.com/v1"),
                                      model, str(home), {"HOME": str(home)})
            return (d / "config.toml").read_text(), (rs._TURN_THINKING.get() or {}).get("applied")
        finally:
            rs._TURN_THINKING.reset(token)

    assert f'model_reasoning_effort = "{rs.CODEX_REASONING_EFFORT}"' in cfg("gpt-5.4", "")[0]
    text, applied = cfg("gpt-5.4", "minimal")                 # refused by the model; its nearest is low
    assert 'model_reasoning_effort = "low"' in text and applied == "low"
    text, applied = cfg("gpt-6.1-sol", "none")                # cannot be turned off
    assert 'model_reasoning_effort = "low"' in text and applied == "low"


def test_the_providers_count_of_thinking_tokens_is_read_in_every_shape_and_apart_from_pricing():
    chat = {"usage": {"prompt_tokens": 5, "completion_tokens": 9, "completion_tokens_details": {"reasoning_tokens": 7}}}
    responses = {"usage": {"input_tokens": 5, "output_tokens": 9, "output_tokens_details": {"reasoning_tokens": 4}}}
    stream_end = {"type": "response.completed", "response": responses}      # the Responses API's stream
    google = {"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 9, "thoughtsTokenCount": 3}}
    assert [rs._thinking_tokens_in(d) for d in (chat, responses, stream_end, google)] == [7, 4, 4, 3]
    assert rs._thinking_tokens_in({"usage": {"input_tokens": 5, "output_tokens": 9}}) is None    # Anthropic gives none
    assert rs._thinking_in_sse_line(b"data: " + json.dumps(stream_end).encode()) == 4
    assert rs._thinking_in_sse_line(b"data: [DONE]") is None
    # the usage that prices a turn carries what it carried before
    assert rs._usage_fields(chat["usage"]) == {"input_tokens": 5, "output_tokens": 9, "cache_read_tokens": 0}
    assert rs._usage_fields(google["usageMetadata"]) == {"input_tokens": 5, "output_tokens": 9, "cache_read_tokens": 0}


def test_a_streamed_calls_usage_is_on_the_route_before_the_client_has_the_bytes():
    """The provider's last events pass long before it closes the stream. A client that is done at
    `[DONE]` (CheetahClaws's in-process driver) read the route's totals before its own call was on
    them, and its turn came back with no usage."""
    release = threading.Event()

    class Up(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
            for chunk in (b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
                          b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":9,'
                          b'"completion_tokens_details":{"reasoning_tokens":7}}}\n\n', b'data: [DONE]\n\n'):
                self.wfile.write(chunk); self.wfile.flush()
            release.wait(10)                                   # the provider has not closed the stream yet

        def log_message(self, *a):
            pass

    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    relay, tok = rs._hermes_relay_route(f"http://127.0.0.1:{up.server_port}/v1", "sk-real")
    conn = http.client.HTTPConnection(relay.removeprefix("http://").removesuffix("/v1"), timeout=10)
    try:
        conn.request("POST", "/v1/chat/completions", body=json.dumps({"model": "m", "stream": True, "messages": []}),
                     headers={"authorization": f"Bearer {tok}", "content-type": "application/json"})
        resp = conn.getresponse()
        seen = b""
        while b"[DONE]" not in seen:
            seen += resp.read1(65536)
        flags = rs._HERMES_RELAY["routes"][tok][2]             # what a client done at [DONE] reads
        assert flags["usage"] == {"input_tokens": 5, "output_tokens": 9, "cache_read_tokens": 0}
        assert flags["reasoning_tokens"] == 7
        release.set()
        resp.read()
        assert flags["usage"]["output_tokens"] == 9 and flags["reasoning_tokens"] == 7     # counted once
    finally:
        release.set(); conn.close(); up.shutdown(); rs._HERMES_RELAY["routes"].pop(tok, None)


def test_a_route_the_gateway_names_wins_over_the_base(monkeypatch):
    """Behind a broker every base is the broker's, so the base says nothing about the provider. The
    gateway, which knows the connection, names the route on the turn."""
    body = json.dumps({"model": "google/gemini-3.5-flash", "messages": []}).encode()
    broker = "https://hr.example/v1/llm"
    assert reasoning.apply(body, "chat", broker, "none") == (body, "")
    out, applied = reasoning.apply(body, "chat", broker, "none", route="vercel")
    assert applied == "none" and json.loads(out)["providerOptions"]["google"]["thinkingConfig"] == {"thinkingBudget": 0}
    assert reasoning.apply(body, "chat", broker, "none", route="not-a-route") == (body, "")
    # the turn carries it to its routes, in the relay's memory and nowhere the agent can read
    token = rs._TURN_THINKING.set({"asked": "low", "applied": "", "routes": [], "route": "openrouter"})
    tok = ""
    try:
        _, tok = rs._hermes_relay_route(broker, "per-turn-credential")
        flags = rs._HERMES_RELAY["routes"][tok][2]
        assert flags["effort"] == "low" and flags["effort_route"] == "openrouter"
    finally:
        rs._TURN_THINKING.reset(token); rs._HERMES_RELAY["routes"].pop(tok, None)
    # a turn with no named route reads the base, as before
    token = rs._TURN_THINKING.set({"asked": "low", "applied": "", "routes": [], "route": ""})
    try:
        _, tok = rs._hermes_relay_route(VERCEL, "k")
        assert "effort_route" not in rs._HERMES_RELAY["routes"][tok][2]
    finally:
        rs._TURN_THINKING.reset(token); rs._HERMES_RELAY["routes"].pop(tok, None)
