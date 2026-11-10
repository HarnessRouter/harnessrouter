"""What every runner test shares."""
import os
import sys

import pytest


@pytest.fixture(autouse=True)
def _prompt_argv_library(monkeypatch, tmp_path_factory):
    """jcode's builder refuses to start without the library that hands jcode its prompt (server.PROMPT_ARGV_SO),
    which the image builds from runner/prompt_argv.c and a checkout does not hold. A test that builds a jcode turn
    gets a stand-in file at that path; the refusal and the real library are tested in test_prompt_off_argv.py.
    The server module is the one the test imported (several set their environment before importing it)."""
    server = sys.modules.get("server")
    if server is None or os.path.isfile(getattr(server, "PROMPT_ARGV_SO", "") or ""):
        return
    stand_in = tmp_path_factory.getbasetemp() / "prompt_argv.so"
    stand_in.touch()
    monkeypatch.setattr(server, "PROMPT_ARGV_SO", str(stand_in))
