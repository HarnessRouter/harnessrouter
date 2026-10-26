"""Batch 4 on the releases it ships with: mistral-vibe 3.0.2, docker-agent v1.152.0, fast-agent-mcp
0.10.47 and deepagents-code 0.2.1, and the merge of this batch with the failure detail of #504.

Each test pins one thing those releases changed, or one hole their review found:
- vibe 3.0 streams a draft it then discarded, sends max_tokens on every request, and declares `wait`;
- vibe reads VIBE_<key> as config and fetches organization settings when a Mistral key is visible;
- fast-agent reads a .env in the directory it runs in, which could turn its OTEL on or move its
  model endpoint off the relay;
- fast-agent's and docker-agent's per-turn configs can carry an MCP server's Authorization header;
- a failed turn's reason is read with traceback frames taken out, and its error_detail with them in.
"""
import json
import os
import pathlib
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402
from server import (ALL_VIBE_TOOLS, Auth, CHECKPOINT_EXCLUDE, _build_fast_agent,  # noqa: E402
                    _build_vibe, _caller_env, _fast_agent_home, _vibe_to_claude, _turns,
                    _run_turn_bg, _claude_passthrough)

UP = "https://up.example/v1"


def _ws() -> str:
    d = tempfile.mkdtemp()
    (pathlib.Path(d) / ".harness" / "home").mkdir(parents=True)
    return d


def _entry(eid: str, text: str, outcome: dict | None) -> dict:
    e = {"id": eid, "sessionId": "s1", "generationStatus": "completed", "type": "message",
         "role": "assistant", "content": [{"type": "text", "text": text}]}
    if outcome is not None:
        e["outcome"] = outcome
    return e


# ── vibe 3.0.2 ────────────────────────────────────────────────────────────────────────────────

def test_a_draft_vibe_discarded_is_neither_shown_nor_the_answer():
    """3.0 asks again when an answer is cut off at the output limit, and streams the cut-off draft
    first, marked discarded (measured: "CUT OFF", then the committed answer)."""
    state: dict = {"model": "m", "final": ""}
    out = []
    for e in (_entry("a1", "CUT OFF", {"type": "discarded", "cause": "retry"}),
              _entry("a2", "the whole answer", {"type": "committed"})):
        out += _vibe_to_claude(e, state)
    texts = [b["text"] for ev in out if ev.get("type") == "assistant"
             for b in ev["message"]["content"] if b.get("type") == "text"]
    assert texts == ["the whole answer"]
    assert state["final"] == "the whole answer"


def test_an_entry_without_an_outcome_is_still_the_answer():
    """2.26.1's journal carries no outcome at all, and a resumed session's old entries are read so."""
    state: dict = {"model": "m", "final": ""}
    _vibe_to_claude(_entry("a1", "an answer", None), state)
    assert state["final"] == "an answer"


def test_vibes_route_drops_the_output_cap_it_now_sends():
    """3.0.1 sends max_tokens = the declared context window minus the input minus 4096 (about
    187,000 here); 2.26.1 sent none. The relay takes it off, as it does for kimi and openhands."""
    env: dict = {}
    _build_vibe("openai-api", Auth(base_url=UP, api_key="k"), "gpt-5.4", "hi", _ws(), env)
    tok = env["HR_VIBE_RELAY_KEY"]
    flags = rs._HERMES_RELAY["routes"][tok][2]
    assert "max_tokens" in flags["drop_fields"]


def test_vibes_tools_include_wait():
    assert "wait" in ALL_VIBE_TOOLS


def test_a_harness_variable_cannot_reconfigure_vibe_or_hand_it_a_mistral_key():
    """VIBE_<key> overrides vibe's config (enable_telemetry among them), and a visible
    MISTRAL_API_KEY makes it fetch the organization's settings from Mistral with no switch."""
    got = _caller_env({"VIBE_ENABLE_TELEMETRY": "true", "MISTRAL_API_KEY": "sk-x",
                       "vibe_home": "/tmp/x", "MY_SETTING": "ok"})
    assert got == {"MY_SETTING": "ok"}


# ── fast-agent 0.10.47 ────────────────────────────────────────────────────────────────────────

def test_fast_agents_config_states_what_a_workspace_env_file_could_change():
    """A .env in the workspace was read: OTEL__ENABLED there sent traces out, and
    GENERIC__BASE_URL there sent the model call around the relay. The per-turn config says both."""
    ws, env = _ws(), {}
    _build_fast_agent("openai-api", Auth(base_url=UP, api_key="real-key"), "gpt-5.4", "hi", ws, env)
    cfg = (_fast_agent_home(ws) / "fastagent.config.yaml").read_text()
    assert "otel:\n  enabled: false" in cfg
    relay = env["GENERIC_BASE_URL"]
    assert relay.startswith("http://127.0.0.1:") and f'generic:\n  base_url: "{relay}"' in cfg
    assert UP not in cfg and "real-key" not in cfg


# ── checkpoints ───────────────────────────────────────────────────────────────────────────────

def test_the_per_turn_configs_that_carry_mcp_headers_never_travel_in_a_checkpoint():
    for path in ("./.harness/fast-agent/fastagent.config.yaml", "./.harness/docker-agent/agent.yaml"):
        assert path in CHECKPOINT_EXCLUDE, path
    # their session stores DO travel, or resume dies on every recycle
    assert "./.harness/fast-agent" not in CHECKPOINT_EXCLUDE
    assert "./.harness/docker-agent" not in CHECKPOINT_EXCLUDE
    assert "./.harness/docker-agent/sessions.db" not in CHECKPOINT_EXCLUDE


# ── the merge: the reason without the frames, error_detail with them ─────────────────────────

_RICH_TRACEBACK = ("MCP Server: 'plugs': Failed to initialize. Details: MCPError: Not Found\n"
                   "╭──── Traceback (most recent call last) ────╮\n"
                   "│   579 │   try:                                          │\n"
                   "│  1585 │   │   │   exc                                 │\n"
                   "╰──────────────╯\n")


def _failed_turn(tmp_path: pathlib.Path) -> dict:
    """A CLI that prints the CLI's own sentence, then a rich traceback, and exits 1."""
    path = tmp_path / "cli.py"
    path.write_text("import sys\nsys.stderr.write(" + json.dumps(_RICH_TRACEBACK) + ")\nsys.exit(1)\n")
    turn_id = "b4-latest-" + uuid.uuid4().hex
    _turns[turn_id] = {"status": "running", "events": [], "result": "", "done": False,
                       "started": time.time(), "backend": "fast-agent", "model": "m"}
    try:
        _run_turn_bg(turn_id, [sys.executable, str(path)], os.environ.copy(), str(tmp_path),
                     _claude_passthrough, "m", timeout_seconds=30)
        return _turns[turn_id]
    finally:
        _turns.pop(turn_id, None)


def test_the_reason_is_the_clis_own_sentence_not_a_traceback_frame(tmp_path):
    """This branch's half: the frames were the last lines of stderr, so the reason read
    `│   579 │   try:` (and 579 looked like an HTTP 5xx). With them out, it is what the CLI said."""
    rec = _failed_turn(tmp_path)
    assert "Failed to initialize" in rec["error"]
    assert not any(ch in rec["error"] for ch in "│╭╰")


def test_error_detail_keeps_the_frames_the_reason_leaves_out(tmp_path):
    """#504's half: the harness's own account of a failure is kept whole, frames and all. Merged
    naively, error_detail read the filtered tail and lost them; it reads the raw one."""
    rec = _failed_turn(tmp_path)
    exc = rec["error_detail"]["exception"]
    assert "Failed to initialize" in exc
    assert "│   579 │   try:" in exc and "Traceback (most recent call last)" in exc
