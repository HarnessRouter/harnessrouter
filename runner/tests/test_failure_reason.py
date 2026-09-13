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
