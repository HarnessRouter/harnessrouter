import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import _failure_reason  # noqa: E402

PANIC = "thread 'tokio-rt-worker' panicked at crates/goose/src/agents/platform_extensions/mod.rs:178:90:\ncalled `Result::unwrap()` on an `Err` value: Permission denied (os error 13) at path \"/tmp/.tmpAb12\"\nError: Extension loading task failed"


def test_the_clis_last_lines_outrank_a_normalisers_no_diagnostic_sentence():
    assert _failure_reason("", "goose exited 1 without reporting an error", PANIC, 1) == PANIC
    assert _failure_reason("", "opencode exited 2 without reporting an error", "boom", 2) == "boom"


def test_a_real_result_message_and_a_refusal_still_come_first():
    assert _failure_reason("", "the provider declined the request (finish_reason content_filter)", PANIC, 1).startswith("the provider declined")
    assert _failure_reason("HTTP 401: bad key", "goose exited 1 without reporting an error", PANIC, 1) == "HTTP 401: bad key"


def test_without_any_lines_the_sentence_and_then_the_exit_code_remain():
    assert _failure_reason("", "goose exited 1 without reporting an error", "", 1) == "goose exited 1 without reporting an error"
    assert _failure_reason("", "", "", 3) == "exit_code=3, no diagnostic output"


# ── a rich-rendered traceback is frames, not a reason ───────────────────────────────────────
# MEASURED by the browser column (2026-10-21): fast-agent writes a rich traceback to stderr when an
# MCP server fails to start. A tail is read from the END, so the reason came out as the gutter line
# `│   579 │   try:` and the turn's answer as `│  1585 │   │   │   exc` — while the CLI had said
# what happened three lines above the box.
_RICH_TAIL = """
MCP Server Startup Error:
MCP Server: 'plugs': Failed to initialize - see details. Check the server's
fast-agent.yaml configuration.

Details:
MCPError: Not Found

╭───────────────────── Traceback (most recent call last) ──────────────────────╮
│ /path/mcp_connection_manager.py:465 in _run_server_lifecycle                 │
│                                                                              │
│    462 │   │   connection = server_conn._client_connection_factory()         │
│ ❱  465 │   │   │   async with connection:                                    │
│    579 │   try:                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
"""


def test_the_clis_own_sentence_wins_over_its_traceback_frames():
    got = _failure_reason("", "", _RICH_TAIL, 1)
    assert got.startswith("MCP Server Startup Error:")
    assert "MCPError: Not Found" in got
    assert "│" not in got and "╭" not in got and "❱" not in got
    assert "try:" not in got, "a source line from a frame is not the reason"


def test_a_tail_of_nothing_but_frames_falls_through_to_the_exit_code():
    only_frames = "╭── Traceback ──╮\n│   579 │   try:   │\n╰───────────────╯"
    assert _failure_reason("", "", only_frames, 1) == "exit_code=1, no diagnostic output"


def test_an_ordinary_tail_is_untouched_by_the_frame_filter():
    tail = "Permission denied (os error 13) at path /tmp/x\nthread 'tokio-runtime-worker' panicked"
    got = _failure_reason("", "", tail, 1)
    assert got == tail, "nothing here is a frame, so nothing is dropped"


# ── a gutter line number is not an HTTP status ───────────────────────────────────────────────
# MEASURED end to end (2026-10-21, the browser column): every failed fast-agent turn reported the
# single line `│   579 │   try:` as its reason. _PROVIDER_REFUSAL's `\b5\d\d\b` arm — there for
# "HTTP 503", "Error code: 429" and the rest — read 579, a SOURCE LINE NUMBER in rich's gutter, as
# a 5xx; and a refusal wins over every other candidate. The CLI's own sentence was two lines below.
def test_a_line_number_in_a_traceback_frame_is_not_a_provider_refusal():
    from server import _PROVIDER_REFUSAL, _without_traceback_frames
    frame = "│   579 │   try:                                     │"
    assert _PROVIDER_REFUSAL.search(frame), "the matcher does fire on it; that is the trap"
    kept = _without_traceback_frames("\n".join([frame, "RuntimeError: Core not initialized"]))
    assert not any(_PROVIDER_REFUSAL.search(ln) for ln in kept.splitlines())
    assert kept == "RuntimeError: Core not initialized"


def test_a_real_refusal_in_prose_still_wins():
    from server import _PROVIDER_REFUSAL, _without_traceback_frames
    # the arm is left as it is: these are the phrasings it carries, and none is a frame
    for line in ("HTTP 503 Service Unavailable", "Error code: 429 - rate limit exceeded",
                 "401 Unauthorized", "insufficient_quota: your quota is exhausted"):
        kept = _without_traceback_frames(line)
        assert any(_PROVIDER_REFUSAL.search(ln) for ln in kept.splitlines()), line
