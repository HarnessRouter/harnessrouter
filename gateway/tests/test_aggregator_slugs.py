"""TokenRouter keeps the plain slug; OpenRouter's dated rename stays on OpenRouter's list only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402


def test_tokenrouter_serves_the_plain_slug_and_openrouter_the_dated_one():
    assert gw._VENDOR_MODELS["tokenrouter"]["qwen3.8-max"] == "qwen/qwen3.8-max"
    assert gw._VENDOR_MODELS["openrouter"]["qwen3.8-max"] == "qwen/qwen3.8-max-0902"


def test_the_mapper_hands_each_aggregator_its_own_name():
    assert gw._map_model({"provider": "tokenrouter", "backend": "hermes"}, "qwen3.8-max") == "qwen/qwen3.8-max"
    assert gw._map_model({"provider": "openrouter", "backend": "hermes"}, "qwen3.8-max") == "qwen/qwen3.8-max-0902"
