"""opencode's baseURL ends with /v1: every ai-sdk package appends its own resource to it."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _cfg(tmp_path, **auth):
    server._opencode_config(server.Auth(**auth), "claude-opus-5", str(tmp_path), None, None, pr=auth.get("provider", ""))
    return json.load(open(tmp_path / ".harness" / "opencode.json"))["provider"]["hr"]


def test_a_direct_anthropic_key_without_the_suffix_gets_it(tmp_path):
    p = _cfg(tmp_path, provider="anthropic", base_url="https://api.anthropic.com", api_key="k")
    assert p["npm"] == "@ai-sdk/anthropic" and p["options"]["baseURL"] == "https://api.anthropic.com/v1"


def test_a_base_that_already_ends_in_v1_is_kept(tmp_path):
    p = _cfg(tmp_path, provider="tokenrouter", base_url="https://api.tokenrouter.com/v1/", api_key="k")
    assert p["options"]["baseURL"] == "https://api.tokenrouter.com/v1"


def test_a_custom_endpoint_is_the_users_exact_url(tmp_path):
    p = _cfg(tmp_path, provider="custom", base_url="https://relay.example/api/coding/v3", api_key="k", api_format="anthropic")
    assert p["options"]["baseURL"] == "https://relay.example/api/coding/v3"


def test_an_openai_shape_turn_rides_the_loopback_relay_and_a_messages_turn_does_not(tmp_path):
    # 2026-09-06: with a Google key opencode reached Google directly, so nothing replayed Gemini 3's
    # thought signatures and every artifact turn failed; through the relay pi, dsh and qwen passed.
    env = {}
    server._build_opencode("openai-api", server.Auth(provider="google", base_url="https://generativelanguage.googleapis.com/v1beta/openai", api_key="real"),
                           "gemini-3.6-flash", "hi", str(tmp_path), env)
    p = json.load(open(tmp_path / ".harness" / "opencode.json"))["provider"]["hr"]
    assert p["npm"] == "@ai-sdk/openai-compatible"
    assert p["options"]["baseURL"].startswith("http://127.0.0.1:") and p["options"]["baseURL"].endswith("/v1")
    assert env[server._OPENCODE_KEY_ENV] != "real"          # a per-turn placeholder; the key stays in this process
    env2 = {}
    server._build_opencode("anthropic", server.Auth(provider="anthropic", base_url="https://api.anthropic.com", api_key="real"),
                           "claude-opus-5", "hi", str(tmp_path), env2)
    p2 = json.load(open(tmp_path / ".harness" / "opencode.json"))["provider"]["hr"]
    assert p2["npm"] == "@ai-sdk/anthropic" and p2["options"]["baseURL"] == "https://api.anthropic.com/v1"
    assert env2[server._OPENCODE_KEY_ENV] == "real"
