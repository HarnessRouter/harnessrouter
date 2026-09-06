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
