"""Which backends a streamed task asks for token-level deltas (HARNESS_STREAM_PARTIAL=1 or
metadata.stream_partial), and that the default stays batch.

grok is in the gate because Grok Build 1.0.41 with `--include-partial-messages` emits Claude Code's
`stream_event` content_block_delta lines in its streaming-messages-json (measured at a local stub:
a three-chunk answer came back as three text_delta lines), and _grok_to_claude hands them to the
claude passthrough, which turns each into its own response.output_text.delta.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import _want_partial  # noqa: E402


def test_default_is_batch_for_every_backend(monkeypatch):
    monkeypatch.delenv("HARNESS_STREAM_PARTIAL", raising=False)
    for backend in ("claude", "codex", "grok", "hermes"):
        assert _want_partial(backend, {}) is False


def test_env_switch_streams_grok(monkeypatch):
    monkeypatch.setenv("HARNESS_STREAM_PARTIAL", "1")
    assert _want_partial("grok", {}) is True
    assert _want_partial("claude", {}) is True
    assert _want_partial("codex", {}) is True


def test_metadata_switch_streams_grok(monkeypatch):
    monkeypatch.delenv("HARNESS_STREAM_PARTIAL", raising=False)
    assert _want_partial("grok", {"stream_partial": True}) is True


def test_a_backend_without_deltas_stays_batch(monkeypatch):
    monkeypatch.setenv("HARNESS_STREAM_PARTIAL", "1")
    assert _want_partial("hermes", {}) is False
