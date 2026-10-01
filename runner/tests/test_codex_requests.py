"""Every request the codex app-server sends gets an answer in the shape codex expects, at once.

Pinned on a live reproduction (codex 0.154.0 app-server, 2026-09-30): with approvalPolicy
on-request codex asks before any MCP tool whose annotations do not say read-only, through
mcpServer/elicitation/request with _meta.codex_approval_kind = "mcp_tool_call". The runner
answered only */requestApproval, so the thread sat in waitingOnApproval for the rest of the turn
and every plug write (InsForge create_table, Vercel deploy) stalled while reads sailed through.
The elicitation below is the captured request, payload shortened, shape untouched."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import _codex_request_answer  # noqa: E402

ELICITATION = {
    "threadId": "01a0f5f2-9116-7772-8f72-29ac4a674f56", "turnId": "01a0f5f2-9152-7ae3-9a35-2a2f1d8b5c01",
    "serverName": "plugs", "mode": "form",
    "_meta": {"codex_approval_kind": "mcp_tool_call", "persist": ["session", "always"],
              "tool_description": "Create a table in the project database.",
              "tool_params": {"name": "greetings", "columns": ["id", "text"]},
              "tool_params_display": [{"name": "columns", "value": ["id", "text"], "display_name": "columns"},
                                      {"name": "name", "value": "greetings", "display_name": "name"}]},
    "message": "Allow the plugs MCP server to run tool \"create_table\"?",
    "requestedSchema": {"type": "object", "properties": {}},
}


def test_codex_asking_before_a_write_mcp_tool_is_told_yes():
    result, err = _codex_request_answer("mcpServer/elicitation/request", ELICITATION)
    assert err is None and result == {"action": "accept", "content": {}}


def test_an_mcp_servers_own_question_is_declined_because_nobody_is_attached():
    result, err = _codex_request_answer("mcpServer/elicitation/request", {
        "serverName": "crm", "mode": "form", "message": "Which account?",
        "requestedSchema": {"type": "object", "properties": {"account": {"type": "string"}}}})
    assert err is None and result == {"action": "decline"}


def test_command_and_file_approvals_are_accepted():
    for method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                   "execCommandApproval/requestApproval"):
        assert _codex_request_answer(method, {"itemId": "x"}) == ({"decision": "accept"}, None)


def test_a_permission_request_is_granted_in_its_own_shape_not_as_a_decision():
    perms = {"network": {"enabled": True}, "fileSystem": {"entries": [{"path": "/tmp", "access": "write"}]}}
    result, err = _codex_request_answer("item/permissions/requestApproval", {"itemId": "x", "permissions": perms})
    assert err is None and result == {"permissions": perms}


def test_a_user_input_request_gets_empty_answers_so_the_turn_goes_on():
    assert _codex_request_answer("item/tool/requestUserInput", {"questions": [{"id": "q1"}]}) == ({"answers": {}}, None)


def test_an_unknown_request_is_refused_aloud_rather_than_left_pending():
    result, err = _codex_request_answer("attestation/generate", {})
    assert result is None and "attestation/generate" in err
