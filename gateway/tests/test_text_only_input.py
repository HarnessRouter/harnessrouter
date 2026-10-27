"""The models whose channels take no image input (_TEXT_ONLY_INPUT): the runner's `vision` flag is false for them, so
pi, dsh, omp and fast-agent keep images out of what they send (fast-agent's overlay declares text only, its stored
history is stripped), as the relay's image fit does. Each entry was measured refusing an image."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402


def test_the_measured_text_only_models():
    # nemotron-3-super (2026-10-27): Vercel 400 "This model doesn't support the image content block", OpenRouter
    # 404 "No endpoints found that support image input"; the same request without the image answered on both
    assert gw._TEXT_ONLY_INPUT == {"qwen3.7-max", "glm-5.3", "nemotron-3.5-lightning", "nemotron-3-super"}
    assert "glm-5.3-flash" not in gw._TEXT_ONLY_INPUT          # took the same image task and completed
