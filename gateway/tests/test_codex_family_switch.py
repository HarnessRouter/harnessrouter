"""gpt-5.3-codex cannot run in a Codex task another model family has used: refused in words."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_families():
    assert gw._codex_family("gpt-5.3-codex") == "codex"
    assert gw._codex_family("gpt-5.5") == "gpt" and gw._codex_family("gpt-5.6-sol") == "gpt"


def test_codex_model_after_another_family_is_refused_in_words():
    why = gw._codex_switch_refusal(["gpt-5.5"], "gpt-5.3-codex")
    assert "already used gpt-5.5" in why and "Start a new task for gpt-5.3-codex." in why
    assert gw._codex_switch_refusal(["gpt-5.3-codex", "gpt-5.6-sol"], "gpt-5.3-codex"), "a switch away and back"


def test_the_other_models_run_anywhere_and_codex_stays_within_its_own():
    assert gw._codex_switch_refusal(["gpt-5.3-codex"], "gpt-5.5") == "", "measured: gpt-5.5 acts in a gpt-5.3-codex thread"
    assert gw._codex_switch_refusal(["gpt-5.5"], "gpt-5.4") == ""
    assert gw._codex_switch_refusal(["gpt-5.3-codex"], "gpt-5.3-codex") == ""
    assert gw._codex_switch_refusal([], "gpt-5.3-codex") == ""
