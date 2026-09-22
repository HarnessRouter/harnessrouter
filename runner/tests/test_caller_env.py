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
    assert got == {"API_KEY": "sk-x", "R2_URL": "https://r2/x", "PATH": "/evil"}
    monkeypatch.setenv("PATH", "/usr/bin")
    env = {**server._caller_env({"PATH": "/evil", "API_KEY": "sk-x"}), **server._child_env()}
    assert env["PATH"] == os.environ["PATH"] and env["API_KEY"] == "sk-x"


def test_turn_request_accepts_the_env_map():
    req = server.TurnReq(prompt="hi", env={"A": "1"})
    assert req.env == {"A": "1"}
