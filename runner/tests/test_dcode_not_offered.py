"""deepagents-code is implemented in the runner and NOT offered by the gateway, for a reason its
own source states.

`dcode -n "<task>"` cannot continue a conversation. From main.py in 0.1.84, about `--rubric`:

    `--rubric` cannot reach that state: it requires `-n`, and `run_non_interactive` takes no resume
    or thread-id argument, so it always starts a fresh thread with no checkpointed goal. … Add the
    combined check here if the non-interactive path ever gains thread resumption.

MEASURED against that (2026-10-16), because a comment is a claim too: three turns in one workspace,
each passing `-r <thread_id>` for a thread whose row and 22 checkpoints were in the store. Every
turn created a NEW thread (five rows in `dcode_thread_workspaces` for five turns) and every recall
answered "this thread has no earlier message". A fourth turn with `-r` placed before `-n` instead of
after it did the same.

The first reading of this was WRONG and is worth keeping: an earlier probe "resumed" and recalled
the right word, which looked like continuity and was not — the question was "what word did I ask you
to put in the file", and the file was in the workspace for the agent to read. The control that
settled it asks for something only the conversation could carry, and the memory file that could
have carried it (`$HOME/.deepagents/agent/AGENTS.md`) was empty on both sides.

So a base on this path would pass `first turn` and fail `follow-up`, `switch` and `recycle` — three
of the matrix's five scenarios — and the honest thing is not to offer it until it rides a surface
that keeps a conversation. That surface exists: `dcode --acp` runs an ACP server whose sessions ARE
LangGraph threads and whose server is constructed with `load_sessions=True` (main.py:3703), so
`session/load` can continue one across processes, and ACP carries tool calls as well. This file
pins the current state so a half-registration cannot pass unnoticed.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "gateway"))
os.environ.setdefault("HR_BACKING", "local")
from server import BACKENDS, _build_dcode, _dcode_session_present, _dcode_state_db  # noqa: E402


def test_the_runner_can_execute_it():
    assert "dcode" in BACKENDS
    assert BACKENDS["dcode"]["providers"]


def test_the_gateway_neither_lists_it_nor_routes_it():
    import app as A
    assert "dcode" not in A._MODEL_CATALOG
    assert "dcode" not in A._BASE_CATALOG
    assert "dcode" not in A._SUPPORTED_BASES
    assert not [1 for (_p, b) in A._INTEGRATION_WIRING if b == "dcode"]
    for fmt in A._CUSTOM_FORMAT_BACKENDS.values():
        assert "dcode" not in fmt


def test_it_is_not_installed_or_measured_either():
    root = pathlib.Path(__file__).resolve().parents[2]
    entry = (root / "docker" / "entrypoint.sh").read_text()
    assert "install_dcode" not in entry
    assert "dcode" not in entry.split("HR_BACKENDS:-", 1)[1].split("}", 1)[0]
    dim = (root / "scripts" / "support-matrix" / "custom-harness.mjs").read_text()
    bases = dim.split("process.env.BASES || '", 1)[1].split("'", 1)[0]
    assert "dcode" not in bases.split(",")
    ts = (root / "ui" / "src" / "lib" / "harness.ts").read_text()
    assert "'dcode'" not in ts


def test_the_pieces_that_do_exist_still_work():
    # the builder, the store reader and the driver are real: the ACP work starts from them
    ws = pathlib.Path(__file__).resolve().parent / "fixtures"      # any directory
    cmd = _build_dcode("openai-api", __import__("server").Auth(base_url="https://up.example/v1",
                                                               api_key="k"),
                       "gpt-5.4", "hi", str(ws), {})
    assert cmd[1].endswith("dcode_driver.py")
    assert _dcode_session_present(str(ws), [], "nope") is False
    assert str(_dcode_state_db(str(ws))).endswith(".deepagents/.state/sessions.db")
    assert (pathlib.Path(__file__).resolve().parents[1] / "dcode_driver.py").is_file()
