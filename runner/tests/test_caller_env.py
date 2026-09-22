"""A harness's environment reaches the agent's processes under the runner's own: a caller names
variables, never one the runner sets, and never with a name a shell would refuse."""
from __future__ import annotations
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def test_caller_env_is_filtered_and_the_runner_wins(monkeypatch):
    got = server._caller_env({"API_KEY": "sk-x", "R2_URL": "https://r2/x", "HR_TURN_ID": "no", "OPENAI_API_KEY": "no",
                              "PATH": "/evil", "bad-name": "no", "EMPTY": None})
    assert got == {"API_KEY": "sk-x", "R2_URL": "https://r2/x"}       # PATH is the runner's, refused by name
    monkeypatch.setenv("PATH", "/usr/bin")
    env = {**server._caller_env({"PATH": "/evil", "API_KEY": "sk-x"}), **server._child_env()}
    assert env["PATH"] == os.environ["PATH"] and env["API_KEY"] == "sk-x"


def test_turn_request_accepts_the_env_map():
    req = server.TurnReq(prompt="hi", env={"A": "1"})
    assert req.env == {"A": "1"}


def test_the_runtimes_own_names_are_refused():
    out = server._caller_env({"LD_PRELOAD": "/x.so", "PYTHONPATH": "/p", "HTTPS_PROXY": "http://x", "NODE_OPTIONS": "-r x",
                              "SSL_CERT_FILE": "/c", "ld_library_path": "/l", "DEPLOY_TOKEN": "abc"})
    assert out == {"DEPLOY_TOKEN": "abc"}


def test_a_turn_is_read_back_without_its_secret_values(monkeypatch):
    env = {"TOKEN": "tok_0123456789abcdef", "REGION": "us-east-1", "SHORT": "abc"}
    secrets = server._turn_secrets(env, ["TOKEN", "REGION", "SHORT", "MISSING"])
    assert secrets == ["tok_0123456789abcdef", "us-east-1"]           # a short value is left alone
    monkeypatch.setitem(server._turns, "turn_x", {
        "status": "completed", "done": True, "backend": "claude", "model": "m", "started": 0.0,
        "result": "the token is tok_0123456789abcdef in us-east-1", "error": "bad tok_0123456789abcdef",
        "events": [{"type": "assistant", "message": {"content": [{"type": "text", "text": "echo tok_0123456789abcdef"}]}}],
        "secrets": secrets})
    out = server.get_turn("turn_x")
    dumped = __import__("json").dumps(out)
    assert "tok_0123456789abcdef" not in dumped and "us-east-1" not in dumped
    assert out["result"] == "the token is [redacted] in [redacted]" and out["error"] == "bad [redacted]"
    assert out["events"][0]["message"]["content"][0]["text"] == "echo [redacted]"
