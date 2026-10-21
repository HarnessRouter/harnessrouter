"""The turns feed names, per turn, the model the turn asked for (2026-09-06): the support matrix judges a
served-model substitution on the same turn, since a switch turn asks for another model on purpose."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_the_feed_carries_the_requested_model_per_turn():
    src = Path(gw.__file__).read_text()
    body = src[src.index("async def _session_turns_data"):][:8000]
    assert '"model": rec.get("model") or None' in body
    assert '"connection": rec.get("connection")' in body


def test_the_codex_switch_check_reads_the_model_the_feed_answers():
    # The feed strips its private "_model" before it answers. The codex switch check's fallback (a
    # session with no models_seen) read "_model", so it never found a model (2026-09-05 to 10-21).
    src = Path(gw.__file__).read_text()
    body = src[src.index("if not seen and resume:"):][:400]
    assert 't.get("model")' in body and '"_model"' not in body
