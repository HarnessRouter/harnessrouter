"""A resumed Codex app-server thread takes this turn's model and settings, not only its id."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def test_a_resumed_thread_carries_this_turns_model_and_settings():
    method, params = server._codex_thread_request("thr_1", "/work", "gpt-5.3-codex")
    assert method == "thread/resume"
    assert params["threadId"] == "thr_1"
    assert params["model"] == "gpt-5.3-codex" and params["cwd"] == "/work"
    assert params["sandbox"] == server._CODEX_SANDBOX and params["approvalPolicy"] == "never"


def test_a_fresh_thread_starts_with_the_same_settings():
    method, params = server._codex_thread_request(None, "/work", "gpt-5.5")
    assert method == "thread/start" and "threadId" not in params
    _, resumed = server._codex_thread_request("thr_2", "/work", "gpt-5.5")
    assert {k: v for k, v in resumed.items() if k != "threadId"} == params
