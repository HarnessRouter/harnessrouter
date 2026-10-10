"""Claude on goose, hermes and OpenHands reaches an Anthropic Messages endpoint natively, through the
relay, with prompt caching: the OpenAI-compatible surface of an Anthropic endpoint cannot cache at
all (its own docs say so), and a customer benchmark paid $15.80 on goose and $12.28 on OpenHands for
an audit task Claude Code did for $2.08 on the same model (2026-09-30). The relay reads the key
under x-api-key, sends it the way Anthropic takes it, adds cache breakpoints when the client set
none, and the provider's own cache split replaces a CLI count that has none."""
import json
import pathlib
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from server import (Auth, _HERMES_RELAY, _build_goose, _build_openhands, _claude_model_used,  # noqa: E402
                    _fill_relay_usage, _hermes_prepare_env, _hermes_relay_route, _with_anthropic_cache)


def _cache(obj):
    return json.loads(_with_anthropic_cache(json.dumps(obj).encode()))


def test_cache_breakpoints_land_on_the_system_and_the_last_user_block():
    out = _cache({"model": "claude-sonnet-5", "system": "be brief",
                  "messages": [{"role": "user", "content": "hi"}]})
    assert out["system"] == [{"type": "text", "text": "be brief", "cache_control": {"type": "ephemeral"}}]
    assert out["messages"][-1]["content"] == [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]
    out = _cache({"model": "claude-sonnet-5", "system": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
                  "messages": [{"role": "assistant", "content": "x"},
                               {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}]})
    assert "cache_control" not in out["system"][0] and out["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert out["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_a_request_with_its_own_breakpoints_or_another_model_goes_through_untouched():
    own = json.dumps({"model": "claude-sonnet-5", "system": [{"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}}],
                      "messages": [{"role": "user", "content": "hi"}]}).encode()
    assert _with_anthropic_cache(own) == own
    other = json.dumps({"model": "gpt-5.4", "messages": [{"role": "user", "content": "claude?"}]}).encode()
    assert _with_anthropic_cache(other) == other
    prefill = json.dumps({"model": "claude-sonnet-5", "messages": [{"role": "assistant", "content": "The"}]}).encode()
    assert _with_anthropic_cache(prefill) == prefill
    assert _with_anthropic_cache(b"not json claude") == b"not json claude"


def test_the_relay_reads_x_api_key_and_sends_a_cached_messages_request_with_both_headers():
    seen = {}

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen["auth"] = self.headers.get("authorization")
            seen["x-api-key"] = self.headers.get("x-api-key")
            seen["path"] = self.path
            data = b'{"type":"message","model":"claude-sonnet-5","usage":{"input_tokens":5,"output_tokens":1,"cache_read_input_tokens":900,"cache_creation_input_tokens":10},"content":[]}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    try:
        base, tok = _hermes_relay_route(f"http://127.0.0.1:{up.server_address[1]}/v1", "sk-real")
        body = json.dumps({"model": "claude-sonnet-5", "system": "s", "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(base + "/messages", data=body, method="POST",
                                     headers={"x-api-key": tok, "anthropic-version": "2023-06-01",
                                              "content-type": "application/json"})
        assert json.loads(urllib.request.urlopen(req, timeout=10).read())["type"] == "message"
        assert seen["path"] == "/v1/messages"
        assert seen["x-api-key"] == "sk-real" and seen["auth"] == "Bearer sk-real"   # a non-Anthropic host takes either
        assert seen["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert seen["body"]["messages"][-1]["content"][0]["cache_control"] == {"type": "ephemeral"}
        # the provider's own usage, cache split included, is what the route recorded
        assert _HERMES_RELAY["routes"][tok][2]["usage"] == {"input_tokens": 5, "output_tokens": 1,
                                                            "cache_read_tokens": 900, "cache_write_tokens": 10}
        assert _HERMES_RELAY["routes"][tok][2]["served_model"] == "claude-sonnet-5"
    finally:
        up.shutdown()


def test_anthropic_itself_takes_the_key_in_x_api_key_only():
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    assert 'if (urllib.parse.urlsplit(base).hostname or "").lower() == "api.anthropic.com":' in src
    assert 'headers.pop("authorization", None)' in src


def test_goose_on_an_anthropic_endpoint_uses_its_own_anthropic_provider_through_the_relay():
    d = tempfile.mkdtemp(); env: dict = {}
    _build_goose("anthropic", Auth(api_key="sk-real", base_url="https://api.anthropic.com/v1"),
                 "claude-sonnet-5", "do it", d, env)
    assert env["ANTHROPIC_API_KEY"].startswith("hr-relay-") and "sk-real" not in json.dumps(env)
    assert env["ANTHROPIC_HOST"].startswith("http://127.0.0.1:") and not env["ANTHROPIC_HOST"].endswith("/v1")
    assert "OPENAI_HOST" not in env and "OPENAI_API_KEY" not in env
    cfg = yaml.safe_load((pathlib.Path(env["GOOSE_PATH_ROOT"]) / "config" / "config.yaml").read_text())
    assert cfg["GOOSE_PROVIDER"] == "anthropic" and cfg["GOOSE_MODEL"] == "claude-sonnet-5"
    # a custom endpoint declared in the Messages format is the same route
    env2: dict = {}
    _build_goose("openai-api", Auth(api_key="sk-real", base_url="https://proxy.example/anthropic/v1", api_format="anthropic"),
                 "claude-sonnet-5", "do it", tempfile.mkdtemp(), env2)
    assert "ANTHROPIC_HOST" in env2 and "OPENAI_HOST" not in env2
    # and an OpenAI endpoint keeps goose's OpenAI provider
    env3: dict = {}
    _build_goose("openai-api", Auth(api_key="sk-real", base_url="https://up.example/v1"), "gpt-5.4", "x", tempfile.mkdtemp(), env3)
    assert env3["OPENAI_HOST"].startswith("http://127.0.0.1:") and "ANTHROPIC_HOST" not in env3


def test_openhands_on_an_anthropic_endpoint_takes_litellms_anthropic_route_at_the_relays_messages_url():
    d = tempfile.mkdtemp(); env: dict = {}
    cmd = _build_openhands("anthropic", Auth(api_key="sk-real", base_url="https://api.anthropic.com/v1"),
                           "claude-sonnet-5", "hi", d, env)
    job = json.loads(cmd[-1])
    assert job["model"] == "anthropic/claude-sonnet-5"
    pe = job["provider_env"]
    assert pe["ANTHROPIC_API_KEY"].startswith("hr-relay-") and env["ANTHROPIC_API_KEY"] == pe["ANTHROPIC_API_KEY"]
    # litellm 1.94.3 posts to ANTHROPIC_API_BASE as given, so the base names the relay's /v1/messages
    assert pe["ANTHROPIC_API_BASE"].startswith("http://127.0.0.1:") and pe["ANTHROPIC_API_BASE"].endswith("/v1/messages")
    assert "LITELLM_PROXY_API_KEY" not in env and "sk-real" not in json.dumps(env) and "sk-real" not in cmd[-1]
    # the OpenAI route is unchanged
    env2: dict = {}
    job2 = json.loads(_build_openhands("openai-api", Auth(api_key="sk-real", base_url="https://up.example/v1"), "gpt-5.4", "hi", tempfile.mkdtemp(), env2)[-1])
    assert job2["model"] == "litellm_proxy/gpt-5.4" and job2["provider_env"]["LITELLM_PROXY_API_BASE"] == job2["base_url"]
    assert env2["LITELLM_PROXY_API_KEY"] == job2["api_key"]


def test_the_driver_sets_the_routes_own_pair():
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("openhands_driver.py").read_text()
    assert 'for k, v in (job.get("provider_env") or {}).items():' in src
    assert 'env["LITELLM_PROXY_API_KEY"] = str(job["api_key"])' not in src


def test_hermes_on_anthropic_rides_the_relay_too():
    d = tempfile.mkdtemp(); env = {"HOME": d}
    _hermes_prepare_env("anthropic", Auth(api_key="sk-real", base_url="https://api.anthropic.com/v1"), d, env,
                        model="claude-sonnet-5")
    assert env["ANTHROPIC_API_KEY"].startswith("hr-relay-") and "sk-real" not in json.dumps(env)
    assert env["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:") and not env["ANTHROPIC_BASE_URL"].endswith("/v1")
    # a custom Messages endpoint is hermes's anthropic provider
    env2 = {"HOME": tempfile.mkdtemp()}
    _hermes_prepare_env("openai-api", Auth(api_key="sk-real", base_url="https://proxy.example/v1", api_format="anthropic"),
                        env2["HOME"], env2, model="claude-sonnet-5")
    cfg = yaml.safe_load((pathlib.Path(env2["HERMES_HOME"]) / "config.yaml").read_text())
    assert cfg["model"]["provider"] == "anthropic" and "ANTHROPIC_BASE_URL" in env2


def test_the_providers_cache_split_replaces_a_cli_count_without_one():
    _, tok = _hermes_relay_route("http://127.0.0.1:9/v1", "sk-x")
    _HERMES_RELAY["routes"][tok][2]["usage"] = {"input_tokens": 50, "output_tokens": 7, "cache_read_tokens": 900}
    env = {"ANTHROPIC_API_KEY": tok}
    ev = {"type": "result", "usage": {"input_tokens": 950, "output_tokens": 7}}
    _fill_relay_usage(ev, env)
    assert ev["usage"] == {"input_tokens": 50, "output_tokens": 7, "cache_read_tokens": 900}
    own = {"type": "result", "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 3}}
    _fill_relay_usage(own, env)
    assert own["usage"] == {"input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 3}     # the CLI's split stands
    empty = {"type": "result"}
    _fill_relay_usage(empty, env)
    assert empty["usage"]["cache_read_tokens"] == 900
    _HERMES_RELAY["routes"][tok][2]["usage"] = {"input_tokens": 50, "output_tokens": 7}
    plain = {"type": "result", "usage": {"input_tokens": 60, "output_tokens": 7}}
    _fill_relay_usage(plain, env)
    assert plain["usage"] == {"input_tokens": 60, "output_tokens": 7}                           # nothing better known


def test_the_claude_result_names_the_model_from_its_usage_by_model():
    res = {"type": "result", "modelUsage": {"claude-haiku-4-5": {"outputTokens": 40},
                                            "claude-sonnet-4-6": {"outputTokens": 1200}}}
    assert _claude_model_used(res) == "claude-sonnet-4-6"
    assert _claude_model_used({"type": "result"}) == ""
    out = server._claude_passthrough(dict(res), {})
    assert out[0]["model"] == "claude-sonnet-4-6"
    named = server._claude_passthrough({"type": "result", "model": "x", "modelUsage": res["modelUsage"]}, {})
    assert named[0]["model"] == "x"


def test_the_hermes_result_carries_the_relays_served_model_and_cache_split():
    """hermes builds its own result from its session counters, which carry no cache figures and no
    model; through the relay the provider's statement is at hand and is what prices the turn."""
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    body = src[src.index("def _run_hermes_bg("):src.index("# ── HTTP surface")]
    assert "served = _relay_served_model(env)" in body and "_fill_relay_usage(ev, env)" in body
    assert body.index("_fill_relay_usage(ev, env)") < body.rindex("append(ev)")   # stamped before the result is appended


def test_a_hermes_turn_is_launched_on_the_provider_its_config_names(monkeypatch, tmp_path):
    """The --provider flag wins over config.yaml, so the two must name one provider. A custom
    endpoint in the Messages format arrives as openai-api; it was configured as anthropic and
    launched as openai-api, and hermes refused it for want of an OPENAI_API_KEY (#374)."""
    launched = []
    monkeypatch.setattr(server, "_run_hermes_bg", lambda *args: launched.append(args))
    wirings = [("openai-api", "anthropic", "anthropic", "ANTHROPIC_BASE_URL"),   # custom, Messages format
               ("openai-api", "openai", "openai-api", "OPENAI_BASE_URL"),        # custom, Chat Completions
               ("anthropic", None, "anthropic", "ANTHROPIC_BASE_URL"),
               ("openrouter", None, "openrouter", "OPENROUTER_BASE_URL")]
    for i, (provider, fmt, want, base_env) in enumerate(wirings):
        cwd = tmp_path / str(i)
        cwd.mkdir()
        server.turn(server.TurnReq(backend="hermes", provider=provider, model="claude-haiku-4.5", prompt="hi",
                                   auth=Auth(api_key="sk-test", base_url="https://proxy.example/v1", api_format=fmt),
                                   cwd=str(cwd)))
        env, flag = launched[-1][2], launched[-1][4]
        cfg = yaml.safe_load((pathlib.Path(env["HERMES_HOME"]) / "config.yaml").read_text())
        assert flag == cfg["model"]["provider"] == want and base_env in env, (provider, fmt)
