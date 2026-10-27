"""fast-agent is told what the turn's model reads where its own table says otherwise (_fast_agent_overlay).

MEASURED on fast-agent 0.10.47 (2026-10-27): an id its table does not have is text only to it, so
attach_media is not offered and images are filtered out of the messages; claude-opus-5.5 was one of 65
such ids. A model overlay named `generic.<id>` in the home's model-overlays/ is what `--model
generic.<id>` resolves to, with the id sent upstream unchanged. Every turn's overlay also carries
fast-agent's stream wait (its own 150 s cut a long gemini-4-argon turn, hosted 2026-10-27). These tests pin
the decision and what reaches the relay; fast-agent's own view is stubbed (its python is not on a test
machine)."""
import json
import pathlib
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402
from server import Auth, FAST_AGENT_DRIVER, _build_fast_agent, _fast_agent_home  # noqa: E402

UP = "https://up.example/v1"
GPT = ["text/plain", "image/jpeg", "image/png", "image/webp", "application/pdf"]


def _ws() -> str:
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / ".harness" / "home").mkdir(parents=True)
    return d


@pytest.fixture
def view(monkeypatch):
    """fast-agent's own answer per id: a dict (known), None (unknown) or False (could not be asked)."""
    answers: dict = {}
    monkeypatch.setattr(server, "_fast_agent_known", lambda m: answers.get(m, None))
    return answers


def _turn(model: str, vision: bool, ws: str | None = None):
    ws = ws or _ws()
    env: dict = {}
    cmd = _build_fast_agent("openai-api", Auth(base_url=UP, api_key="k"), model, "hi", ws, env, vision=vision)
    assert cmd[1] == FAST_AGENT_DRIVER
    argv = json.loads(cmd[2])["argv"]
    route = server._HERMES_RELAY["routes"][env["GENERIC_API_KEY"]]
    path = _fast_agent_home(ws) / "model-overlays" / server._FA_OVERLAY_FILE
    doc = json.loads(path.read_text()) if path.exists() else None
    return argv, route[2], doc, ws


def test_an_id_it_does_not_know_reads_images_when_its_channel_does(view):
    argv, flags, doc, _ = _turn("claude-opus-5.5", vision=True)
    assert argv[argv.index("--model") + 1] == "generic.claude-opus-5.5"     # the id it sends is unchanged
    assert doc["name"] == "generic.claude-opus-5.5" and doc["provider"] == "generic" and doc["model"] == "claude-opus-5.5"
    assert doc["metadata"]["tokenizes"] == ["text/plain", *server._FA_IMAGES]
    # its overlay needs limits, and the cap it would send as max_tokens never went before: the route drops it
    assert doc["metadata"]["context_window"] and doc["metadata"]["max_output_tokens"]
    assert {"max_tokens", "max_completion_tokens"} <= set(flags["drop_fields"])


def test_an_id_it_knows_with_images_is_left_to_its_own_table(view):
    view["gpt-5.4"] = {"tokenizes": GPT}
    _, flags, doc, _ = _turn("gpt-5.4", vision=True)
    assert "metadata" not in doc and "max_tokens" not in flags["drop_fields"]


def test_every_turn_waits_for_its_stream_as_long_as_the_relay_does(view):
    view["gpt-5.4"] = {"tokenizes": GPT}
    for model, vision in (("gpt-5.4", True), ("claude-opus-5.5", True), ("qwen3.7-max", False)):
        _, _, doc, _ = _turn(model, vision=vision)
        assert doc["name"] == f"generic.{model}"
        assert doc["defaults"] == {"streaming_timeout": server._FA_STREAM_WAIT_S}
    assert server._FA_STREAM_WAIT_S > server.HR_RELAY_UPSTREAM_TIMEOUT_S > 150


def test_a_text_only_channel_reads_text_alone_whatever_the_table_says(view):
    view["glm-5.3-flash"] = {"tokenizes": GPT}
    _, flags, doc, _ = _turn("glm-5.3-flash", vision=False)
    # its own limits stay: no made-up ones, nothing dropped
    assert doc["metadata"] == {"tokenizes": ["text/plain"]} and "max_tokens" not in flags["drop_fields"]
    # an id it does not know is already text only to it: nothing to declare
    _, _, doc, _ = _turn("qwen3.7-max", vision=False)
    assert "metadata" not in doc


def test_a_known_text_only_id_whose_channel_takes_images_gets_them(view):
    view["some-model"] = {"tokenizes": ["text/plain", "application/pdf"]}
    _, flags, doc, _ = _turn("some-model", vision=True)
    assert doc["metadata"] == {"tokenizes": ["text/plain", "application/pdf", *server._FA_IMAGES]}
    assert "max_tokens" not in flags["drop_fields"]


def test_the_file_is_this_turns_and_says_nothing_of_reading_when_none_is_needed(view):
    view["gpt-5.4"] = {"tokenizes": GPT}
    _, _, doc, ws = _turn("claude-sonnet-5.5", vision=True)
    assert doc["model"] == "claude-sonnet-5.5"
    _, _, doc, _ = _turn("gpt-5.4", vision=True, ws=ws)       # a switch to a model its table knows
    assert doc["model"] == "gpt-5.4" and "metadata" not in doc


def test_when_it_cannot_be_asked_the_turn_is_as_before(view):
    view["claude-opus-5.5"] = False
    _, flags, doc, _ = _turn("claude-opus-5.5", vision=True)
    assert "metadata" not in doc and "max_tokens" not in flags["drop_fields"]


def test_its_view_is_asked_once_per_id(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[-1])
        out = json.dumps(None if cmd[-1] == "claude-opus-5.5" else {"tokenizes": GPT})
        return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")
    monkeypatch.setattr(server, "_FA_KNOWN", {})
    monkeypatch.setattr(server.subprocess, "run", run)
    assert server._fast_agent_known("claude-opus-5.5") is None
    assert server._fast_agent_known("gpt-5.4") == {"tokenizes": GPT}
    assert server._fast_agent_known("claude-opus-5.5") is None
    assert calls == ["claude-opus-5.5", "gpt-5.4"]
    # a probe that fails is not remembered: the next turn asks again
    monkeypatch.setattr(server.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    assert server._fast_agent_known("kimi-k3") is False and "kimi-k3" not in server._FA_KNOWN
