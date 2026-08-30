"""Follow-up continuity for a backend whose CLI cannot resume.

cline 3.0.60's `--json --id` refuses a prompt in every form (verified live, each form
individually), so the gateway hands the conversation back in the runner prompt. These pin the
transcript builder: bounded, newest-turns-win, in-order emission, and a fresh turn untouched.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import os
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402


def test_a_fresh_turn_is_untouched():
    assert A._history_prompt([], "do it") == "do it"


def test_history_is_prefixed_in_order_and_the_new_prompt_survives_verbatim():
    turns = [{"user": "Remember the codeword AZURE-PEACH.", "assistant": "OK"},
             {"user": "And the number 7.", "assistant": "Noted."}]
    out = A._history_prompt(turns, "What was the codeword?")
    assert out.endswith("What was the codeword?")
    assert out.index("AZURE-PEACH") < out.index("the number 7"), "history must read in order"
    assert "<conversation_so_far>" in out and "</conversation_so_far>" in out


def test_newest_turns_win_the_byte_budget():
    turns = [{"user": f"turn {i}", "assistant": "x" * A._HISTORY_CLIP} for i in range(40)]
    out = A._history_prompt(turns, "go")
    assert "turn 39" in out, "the newest turn must always survive"
    assert "turn 0" not in out, "the oldest turns fall off first"
    assert len(out) < A._HISTORY_MAX_BYTES + A._HISTORY_CLIP + 500


def test_only_cline_is_a_no_resume_backend():
    """Every other CLI resumes natively; adding one here is a decision with a live probe behind
    it, not a convenience."""
    assert A._NO_RESUME_BACKENDS == {"cline"}
