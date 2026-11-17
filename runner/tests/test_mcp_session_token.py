"""OpenHands keeps one MCP relay address for the whole session (#714).

OpenHands freezes its agent, MCP addresses included, when the conversation is first created, so the
address the relay gave it on turn 1 is the one every later turn calls. A token minted per turn was
forgotten when turn 1 ended, and every follow-up failed with the relay's 401. A base in
_MCP_STABLE_FOR now gets a token that is the same for the session and the server on every turn; it
is still registered by each turn and forgotten when the turn ends, and no other session can make it.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402

SRV = [{"name": "memories", "url": "https://gw.example/v1/mcp/memories", "headers": {"Authorization": "Bearer t"}}]


def _turn(stable_for=None):
    """One turn's relay registration, the way the turn handler makes it: the routes the turn held."""
    held: list = []
    tok = server._TURN_ROUTE_TOKENS.set(held)
    try:
        out = server._mcp_through_relay(SRV, stable_for=stable_for)
    finally:
        server._TURN_ROUTE_TOKENS.reset(tok)
    return out[0]["url"], held


def _token(url):
    return re.search(r"/(hr-mcp-[0-9a-f]{32})/", url).group(1)


def test_openhands_gets_the_same_address_on_every_turn_of_its_session():
    a1, held1 = _turn("/data/workspaces/hsessA")
    server._relay_forget(held1)                                   # turn 1 ends
    a2, held2 = _turn("/data/workspaces/hsessA")
    assert a1 == a2, "the frozen agent's address must still route on turn 2"
    assert _token(a2) in server._MCP_RELAY["routes"]              # registered again by turn 2
    server._relay_forget(held2)


def test_between_turns_the_address_opens_nothing():
    a, held = _turn("/data/workspaces/hsessB")
    server._relay_forget(held)
    assert _token(a) not in server._MCP_RELAY["routes"]


def test_another_session_gets_another_address():
    a, ha = _turn("/data/workspaces/hsessC")
    b, hb = _turn("/data/workspaces/hsessD")
    assert a != b
    server._relay_forget(ha + hb)


def test_every_other_base_still_gets_a_token_per_turn():
    a, ha = _turn(None)
    b, hb = _turn(None)
    assert a != b
    server._relay_forget(ha + hb)


def test_the_token_is_the_relays_shape_and_names_nothing():
    t = server._mcp_session_token("/data/workspaces/hsessE", "memories", SRV[0]["url"])
    assert re.fullmatch(r"hr-mcp-[0-9a-f]{32}", t)
    assert "hsessE" not in t and "memories" not in t


def test_only_openhands_asks_for_it():
    assert server._MCP_STABLE_FOR == frozenset({"openhands"})
    src = pathlib.Path(server.__file__).read_text()
    assert "stable_for=os.path.realpath(cwd) if backend in _MCP_STABLE_FOR else None" in src
