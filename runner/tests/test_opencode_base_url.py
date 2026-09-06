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
