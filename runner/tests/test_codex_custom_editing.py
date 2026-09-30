"""Issue #202 (lab1207's PR #332 started this): a model Codex does not know, on a custom Responses
endpoint, called a tool named apply_patch and looped on "unsupported call". Codex 0.154 registers
that tool only inside its own multi-environment executors and never on a custom provider here, so
the turn tells the model how files are edited instead of offering a switch that registers nothing."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def test_a_codex_turn_on_a_custom_responses_endpoint_is_told_how_to_edit():
    custom = rs.Auth(api_key="k", base_url="https://bridge.internal/v1", api_format="responses")
    note = rs._codex_custom_editing_note("codex", custom)
    assert note.startswith("## Editing files on this connection")
    assert "no `apply_patch` tool" in note and "unsupported call" in note and "shell tool" in note
    # the same connection on another base, a Codex turn on a first-party provider, and no auth at all: nothing added
    assert rs._codex_custom_editing_note("hermes", custom) == ""
    assert rs._codex_custom_editing_note("codex", rs.Auth(api_key="k", base_url="https://api.openai.com/v1")) == ""
    assert rs._codex_custom_editing_note("codex", rs.Auth(api_key="k", api_format="openai")) == ""
    assert rs._codex_custom_editing_note("codex", None) == ""
