"""A 401 from the runner's own MCP relay is not the provider refusing the model key (#714).

OpenHands' follow-ups failed with the relay's 401 ("unknown relay token") on an address under
/hr-mcp-, and the turn said "Your vercel key was refused", which sent people to a key that was fine.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)


def test_a_401_on_the_relay_address_is_not_a_key_refusal():
    err = ("agent-server said: HTTPStatusError: Client error '401 Unauthorized' for url "
           "'http://127.0.0.1:33931/hr-mcp-7e334b2c0d1e4f5a6b7c8d9e0f1a2b3c/mcp'")
    assert gw._provider_refused(err) is False


def test_a_provider_401_is_still_a_key_refusal():
    assert gw._provider_refused("Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}") is True
