"""The console must never offer a Kimi Code CLI tool toggle the runner cannot enforce.

Kimi Code CLI's agent files match `disallowedTools` by exact, case-sensitive tool NAME, and a name
the CLI does not know "never matches anything" (its agents reference): a catalog id outside the
runner's _KIMI_TOOLS would be offered as a toggle in the console, reported as off, and change
nothing, the exact overstatement UHP section 4.3 forbids and the reason this backend is allowed to
claim `tool_enforcement: "hard"` at all. _KIMI_TOOLS is the `tools` array of a live 2.0.0 request
captured at a stub; this test holds the catalog to it, so a drift on either side fails here rather
than on a live turn. (The file keeps its first name: under the CLI's predecessor the table mapped
names to module paths.)
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import _KIMI_TOOLS  # noqa: E402


def test_every_advertised_kimi_tool_can_actually_be_withheld():
    advertised = {tid for tid, _label in A._BASE_CATALOG["kimi"]["tools"]}
    assert advertised == set(_KIMI_TOOLS), (
        "catalog ids and _KIMI_TOOLS must match exactly; "
        f"only in catalog: {advertised - set(_KIMI_TOOLS)}, only in the runner: {set(_KIMI_TOOLS) - advertised}")


def test_kimi_claims_hard_enforcement_and_earns_it():
    assert A._BASE_CATALOG["kimi"]["tool_enforcement"] == "hard"
    assert A._BASE_CATALOG["kimi"]["backend"] == "kimi"
    assert A._BASE_CATALOG["kimi"]["label"] == "Kimi Code CLI"


def test_a_tool_that_needs_a_moonshot_service_is_not_offered():
    """WebSearch is declared only with a Moonshot search service configured, which this product
    never sets, so it is not in the captured array and must not be a picker row."""
    assert "WebSearch" not in {tid for tid, _ in A._BASE_CATALOG["kimi"]["tools"]}


def test_kimi_is_chat_completions_only():
    """The runner defines its model as provider type `openai` through the relay, so a
    Responses-API-only id would fail on send."""
    assert "kimi" in A.CHAT_ONLY_BACKENDS


def test_a_server_the_cli_ran_without_becomes_a_note_in_the_reply():
    """Kimi Code CLI runs a turn without an MCP server it could not reach and says nothing; the
    runner reads the CLI's own record of it and this is the sentence a person gets."""
    one = A._blocks_from_canonical({"type": "system", "subtype": "mcp_unavailable",
                                    "servers": [{"name": "dead", "reason": "fetch failed"}]})
    assert one == [("text", '\n\n_Note: the MCP server "dead" could not be reached, so this reply ran '
                            'without those tools._\n')]
    two = A._blocks_from_canonical({"type": "system", "subtype": "mcp_unavailable",
                                    "servers": [{"name": "a"}, {"name": "b"}]})
    assert 'servers "a", "b"' in two[0][1]
    assert A._blocks_from_canonical({"type": "system", "subtype": "mcp_unavailable", "servers": []}) == []
