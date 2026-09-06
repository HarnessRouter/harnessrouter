"""The turns feed names, per turn, the model asked for beside the one the CLI reported it ran."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_the_feed_carries_both_models_per_turn():
    src = Path(gw.__file__).read_text()
    i = src.index("async def _session_turns_data")
    body = src[i:i + 6000]
    assert '"model": rec.get("model") or None' in body
    assert '"served_model": rec.get("served_model") or None' in body
