"""Codex app-server: a provider stream the server is reconnecting is not a failed turn, and a
command its exec policy asks about is approved, since the sandbox is the trust boundary.
GPT-5.6 on Azure dropped the stream after 7 to 12 tool calls and every such turn died on
"Reconnecting... 1/5"; `rm -f` inside the agent's own workspace was rejected by the default rules
under approvalPolicy never (a customer benchmark, 2026-09-30)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def test_a_retried_stream_is_transient_and_keeps_the_underlying_reason():
    line, transient = server._codex_error_line({"willRetry": True, "error": {
        "message": "Reconnecting... 1/5", "additionalDetails": "stream disconnected before completion: 502 Bad Gateway"}})
    assert transient and line == "Reconnecting... 1/5 (stream disconnected before completion: 502 Bad Gateway)"
    line, transient = server._codex_error_line({"error": {"message": "Reconnecting... 3/5"}})
    assert transient and line == "Reconnecting... 3/5"


def test_a_final_error_ends_the_turn():
    line, transient = server._codex_error_line({"willRetry": False, "error": {"message": "exceeded retry limit, last status: 502 Bad Gateway"}})
    assert not transient and line.startswith("exceeded retry limit")
    assert server._codex_error_line({}) == ("codex error", False)


def test_the_loop_continues_on_a_transient_error_and_answers_approval_requests():
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("server.py").read_text()
    loop = src[src.index('elif method == "error":'):src.index('elif method == "turn/failed":')]
    assert "if transient:" in loop and "continue" in loop
    assert server._CODEX_APPROVAL == "on-request"
    assert 'if method.endswith("/requestApproval"):' in src and 'reply(mid, {"decision": "accept"})' in src
