"""The loopback relay joins the client's resource onto a base that carries its API version."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def test_a_bare_anthropic_base_gets_v1():
    assert server._relay_base_with_version("https://api.anthropic.com") == "https://api.anthropic.com/v1"


def test_a_versioned_base_is_kept():
    assert server._relay_base_with_version("https://api.tokenrouter.com/v1/") == "https://api.tokenrouter.com/v1"
    assert server._relay_base_with_version("https://generativelanguage.googleapis.com/v1beta/openai") == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_an_aws_host_keeps_its_own_path():
    assert server._relay_base_with_version("https://bedrock-runtime.us-east-1.amazonaws.com") == "https://bedrock-runtime.us-east-1.amazonaws.com"


def test_the_route_stores_the_versioned_base():
    base, tok = server._hermes_relay_route("https://api.anthropic.com", "k")
    assert server._HERMES_RELAY["routes"][tok][0] == "https://api.anthropic.com/v1" and base.endswith("/v1")
