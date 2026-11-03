"""The claude CLI appends /v1/messages itself. A keyed connection rides the loopback relay (#615): the CLI gets the
relay's origin and a placeholder, and the request it makes must reach exactly the URL it reached when it was
handed the connection's base, whatever /v1 that base was stored with. A base handed over without a key still
loses its trailing /v1."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _messages_url(env, token_var):
    """Where the CLI's POST /v1/messages ends up: the relay strips /v1 and joins /messages onto the route's base."""
    assert env["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:"), env["ANTHROPIC_BASE_URL"]
    base, key, _ = server._HERMES_RELAY["routes"][env[token_var]]
    assert key == "sk-real-claude-key-123" and "sk-real-claude-key-123" not in repr(env)
    return base.rstrip("/") + "/messages"


def _direct(tmp_path, url):
    env = {"HOME": str(tmp_path)}
    server._build_claude("anthropic", server.Auth(provider="anthropic", api_key="sk-real-claude-key-123", base_url=url),
                         "claude-haiku-4.5", "hi", 1, str(tmp_path), env)
    return _messages_url(env, "ANTHROPIC_API_KEY")


def test_a_direct_anthropic_base_with_v1_reaches_anthropics_messages(tmp_path):
    assert _direct(tmp_path, "https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"


def test_a_bare_direct_anthropic_base_reaches_the_same(tmp_path):
    assert _direct(tmp_path, "https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"


def test_a_direct_key_with_no_base_reaches_anthropic_itself(tmp_path):
    assert _direct(tmp_path, None) == "https://api.anthropic.com/v1/messages"


def test_a_router_base_reaches_its_messages_as_before(tmp_path):
    env = {"HOME": str(tmp_path)}
    server._build_claude("tokenrouter", server.Auth(provider="tokenrouter", api_key="sk-real-claude-key-123",
                                                    base_url="https://api.tokenrouter.com/v1"),
                         "claude-haiku-4.5", "hi", 1, str(tmp_path), env)
    assert _messages_url(env, "ANTHROPIC_AUTH_TOKEN") == "https://api.tokenrouter.com/v1/messages"


def test_a_base_without_a_key_is_stripped_as_before(tmp_path):
    env = {"HOME": str(tmp_path)}
    server._build_claude("anthropic", server.Auth(provider="anthropic", base_url="https://api.anthropic.com/v1"),
                         "claude-haiku-4.5", "hi", 1, str(tmp_path), env)
    assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
