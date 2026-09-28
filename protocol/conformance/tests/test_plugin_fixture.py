"""The plugin fixture and the address that reaches it.

The fixture's answer is a function of its input, which is what lets P-11 tell a tool call from a
guess; the plugin checks take the server's address from the context, so a run can be pointed at a
copy the host under test can reach; and P-11 must fail a reply that does not carry the answer.
"""
from __future__ import annotations

from uhp_conformance import DEFAULT_PLUGIN_MCP_URL
from uhp_conformance import checks  # noqa: F401 — importing populates the registry
from uhp_conformance.context import Context
from uhp_conformance.fixture import PREFIX, TOOL_NAME, fixture_answer
from uhp_conformance.registry import REGISTRY


def test_the_answer_is_a_function_of_the_input_and_names_the_fixture():
    assert fixture_answer("abc123") == PREFIX + "321cba"
    assert fixture_answer("") == PREFIX
    assert TOOL_NAME == "uhp_echo"


def test_the_context_carries_the_address_and_defaults_to_the_public_copy():
    ctx = Context(client=None)
    assert ctx.plugin_mcp_url == DEFAULT_PLUGIN_MCP_URL
    assert DEFAULT_PLUGIN_MCP_URL.startswith("https://") and DEFAULT_PLUGIN_MCP_URL.endswith("/mcp")
    own = Context(client=None, plugin_mcp_url="http://10.0.0.5:8080/mcp")
    mcp = checks._plugin_mcp(own)
    assert mcp["mcpServers"]["conformance-http"]["url"] == "http://10.0.0.5:8080/mcp"
    assert "example.invalid" not in str(checks._plugin_files_of(own))


def test_p11_is_a_full_class_check_that_runs_a_task():
    p11 = next(c for c in REGISTRY if c.id == "P-11")
    assert p11.cls == "full"
    assert "tool call" in p11.title


class _Resp:
    def __init__(self, status, json, body=b""):
        self.status, self.json, self.body, self.elapsed_s = status, json, body, 0.1


class _Client:
    """A server that derives the plugin and then answers the task without calling the tool."""
    def __init__(self, reply: str):
        self.reply = reply
    def get(self, path, **kw):
        if path == "/v1/harnesses":
            return _Resp(200, {"harnesses": [{"id": "h1", "base": "claude-code", "defaultModel": "m"}]})
        if path == "/v1/discovery":
            return _Resp(200, {"capabilities": {"plugins": True}})
        return _Resp(200, {"id": "h2", "plugins": [{"name": "uhp-conformance-plugin",
                                                     "mcpServers": [{"name": "conformance-http"}], "skipped": []}]})
    def post(self, path, **kw):
        if path == "/v1/harnesses":
            return _Resp(200, {"id": "h2"})
        return _Resp(200, {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": self.reply}]}]})
    def delete(self, path, **kw):
        return _Resp(200, {})


def _run_p11(reply: str):
    ctx = Context(client=_Client(reply)); ctx.state["discovery"] = {"capabilities": {"plugins": True}}
    p11 = next(c for c in REGISTRY if c.id == "P-11")
    return p11.run(ctx)


def test_p11_fails_a_reply_without_the_fixture_answer_and_passes_one_with_it():
    from uhp_conformance.registry import Outcome
    bad = _run_p11("I called the tool and it said hello")
    assert bad.outcome == Outcome.FAIL and "never reached the plugin's server" in (bad.detail or "")
    # the passing reply must carry the answer for the nonce the check chose, which the fake
    # server cannot know: so pass through whatever text the check sent, reversed, as the fixture would
    import uhp_conformance.checks as ck
    real_post = _Client.post
    def echo_post(self, path, **kw):
        if path == "/v1/responses":
            text = kw["body"]["input"]; nonce = text.split(" with the text ")[1].split(" ")[0]
            return _Resp(200, {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": fixture_answer(nonce)}]}]})
        return real_post(self, path, **kw)
    _Client.post = echo_post
    try:
        good = _run_p11("")
    finally:
        _Client.post = real_post
    assert good.outcome == Outcome.PASS, good.detail
