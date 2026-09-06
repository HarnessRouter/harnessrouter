"""A model served on the Responses API alone is not offered on a harness that speaks chat/completions only."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

RESPONSES_ONLY = {"gpt-5.3-codex"}
CHAT_ONLY_BACKENDS = ("qwen", "cline")


def test_responses_only_models_stay_off_chat_only_harnesses():
    for backend in CHAT_ONLY_BACKENDS:
        listed = set(gw._MODEL_CATALOG[backend]["models"])
        assert not (listed & RESPONSES_ONLY), f"{backend} lists {listed & RESPONSES_ONLY}"


def test_the_harnesses_that_speak_responses_keep_it():
    for backend in ("codex", "hermes", "pi", "dsh", "opencode"):
        assert "gpt-5.3-codex" in gw._MODEL_CATALOG[backend]["models"]
