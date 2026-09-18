"""The openhands backend (OpenHands V1 through openhands-agent-server 1.49.2, MIT).

Every test below pins something measured against a real agent-server on the pinned version, not a
reading of its docs. The four that decided the design:

  the agent is FROZEN at the conversation's first creation — a second create carrying `tools: []`
      left the persisted agent holding ['terminal', 'file_editor'] and the turn wrote its file
  the credential is NEVER persisted — base_state.json holds the whole LLM spec with `api_key: None`,
      so a resumed turn had no key and litellm's backoff hid that for two minutes
  the turn's answer can arrive as a FinishAction rather than a trailing assistant message
  disabling a tool is enforced by OMISSION — with Shell and Edit both withheld the same request
      that wrote a file under the full tool list produced no file and no tool call at all
"""
import json
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import openhands_driver as drv  # noqa: E402


# ── the conversation identity carries the tool policy ──
def test_the_same_policy_is_the_same_conversation():
    assert drv._conversation_id(["terminal", "file_editor"]) == \
        drv._conversation_id(["terminal", "file_editor"])


def test_a_changed_policy_is_a_different_conversation():
    """MEASURED: the agent is frozen at first creation and no endpoint updates it, so a policy that
    only reached a create call the server ignored would run with tools the operator disabled.
    Keying the id on the policy makes the new policy arrive the one way it can — a new
    conversation. Verified live: with Shell and Edit withheld the id changed, the file was not
    written, and restoring the full policy resumed the ORIGINAL conversation with its history."""
    full = drv._conversation_id(["terminal", "file_editor", "task_tracker"])
    none = drv._conversation_id([])
    assert full != none
    # and going back is going back: the id is a pure function of the policy
    assert drv._conversation_id(["terminal", "file_editor", "task_tracker"]) == full


def test_the_id_is_a_uuid_because_the_field_is_typed_one():
    import uuid
    uuid.UUID(drv._conversation_id(["terminal"]))


# ── the tool list, and what disabling means ──
def test_the_browser_set_is_not_offered():
    """It is in upstream's default preset and needs a Chromium this image does not carry; the
    server's own log says `Error preloading … Exception: Chromium is …`. A tool that cannot run is
    not offered."""
    assert "browser_tool_set" not in drv._TOOLS
    assert set(drv._tools({})) == set(drv._TOOLS)


def test_a_disabled_tool_is_withheld_by_its_console_name():
    assert "terminal" not in drv._tools({"tools_disabled": ["Shell"]})
    assert "file_editor" not in drv._tools({"tools_disabled": ["Edit"]})


def test_a_disabled_tool_is_withheld_by_its_own_name_too():
    assert "terminal" not in drv._tools({"tools_disabled": ["terminal"]})


def test_disabling_one_tool_leaves_the_others():
    left = drv._tools({"tools_disabled": ["Shell"]})
    assert "file_editor" in left and "task_tracker" in left


# ── the credential never rides in the conversation ──
def test_the_agent_spec_carries_no_key():
    """MEASURED: base_state.json persists model, base_url, retries and timeouts, and `api_key:
    None`. A key passed here reaches the first turn and nothing after it."""
    spec = drv._agent_spec({"model": "openai/gpt-5.4", "base_url": "http://relay/v1",
                            "api_key": "sk-secret"})
    assert "sk-secret" not in json.dumps(spec)
    assert spec["llm"]["base_url"] == "http://relay/v1"


def test_the_agent_spec_carries_the_tools():
    spec = drv._agent_spec({"model": "m", "tools_disabled": ["Shell"]})
    names = [t["name"] for t in spec["tools"]]
    assert "terminal" not in names and "file_editor" in names


# ── the server's own config, written per turn ──
def test_every_path_is_under_the_harness_dir_and_vscode_is_off(tmp_path):
    """VSCode defaults ON and binds 8001; one server process per turn would collide on it at once.
    The stores go under .harness/ so they travel in the checkpoint and are not produced files."""
    cfg = json.loads(drv._write_config(tmp_path, "key").read_text())
    assert cfg["enable_vscode"] is False
    assert cfg["session_api_keys"] == ["key"]
    for field in ("conversations_path", "workspace_path", "bash_events_dir"):
        assert str(tmp_path) in cfg[field], field


# ── events ──
def _collect(ev, state=None):
    out, state = [], state if state is not None else {}
    real, drv._emit = drv._emit, lambda m, p: out.append((m, p))
    try:
        drv._on_event(ev, state)
    finally:
        drv._emit = real
    return out, state


def test_an_assistant_message_is_the_answer():
    out, state = _collect({"kind": "MessageEvent",
                           "llm_message": {"role": "assistant",
                                           "content": [{"type": "text", "text": "OH-PROBE-1"}]}})
    assert out == [("text", {"text": "OH-PROBE-1"})]
    assert state["final"] == "OH-PROBE-1"


def test_a_user_message_is_not():
    out, _ = _collect({"kind": "MessageEvent",
                       "llm_message": {"role": "user",
                                       "content": [{"type": "text", "text": "do it"}]}})
    assert out == []


def test_a_finish_action_is_the_answer_and_not_a_tool_call():
    """MEASURED: a turn that uses tools ends with its answer on the finish action, while a turn
    that only talks emits a MessageEvent and no finish. Rendering finish as a tool call showed the
    user a `finish` step and left the turn with no answer."""
    out, state = _collect({"kind": "ActionEvent", "tool_call_id": "c1",
                           "action": {"kind": "FinishAction", "message": "DONE"}})
    assert out == [("text", {"text": "DONE"})]
    assert state["final"] == "DONE"


def test_the_finish_observation_is_not_an_orphan_result():
    """Its action is suppressed above, so rendering this would leave a tool result under a call id
    the transcript never showed. Seen in a real artifact turn."""
    out, _ = _collect({"kind": "ObservationEvent", "tool_call_id": "c1",
                       "observation": {"kind": "FinishObservation"}})
    assert out == []


def test_a_real_tool_call_and_its_result_are_a_pair():
    state = {}
    call, _ = _collect({"kind": "ActionEvent", "tool_call_id": "c9", "tool_name": "terminal",
                        "action": {"kind": "TerminalAction", "command": "echo hi"}}, state)
    res, _ = _collect({"kind": "ObservationEvent", "tool_call_id": "c9",
                       "observation": {"kind": "TerminalObservation", "exit_code": 0}}, state)
    assert call[0][0] == "tool_call" and call[0][1]["name"] == "terminal"
    assert res[0][0] == "tool_result" and res[0][1]["id"] == call[0][1]["id"] == "c9"


def test_only_the_execution_status_update_sets_the_status():
    """The event is a generic key/value pair and `last_user_message_id` rides the same shape.
    Reading `value` alone once set the status to a message uuid."""
    _, state = _collect({"kind": "ConversationStateUpdateEvent",
                         "key": "last_user_message_id", "value": "b0d94974-206c-4317-8274-45b"})
    assert "status" not in state
    _, state = _collect({"kind": "ConversationStateUpdateEvent",
                         "key": "execution_status", "value": "running"})
    assert state["status"] == "running"


def test_an_error_event_is_recorded_not_rendered():
    """LLMServiceUnavailableError is the turn's reason, not part of its answer."""
    out, _ = _collect({"kind": "ConversationErrorEvent", "code": "LLMServiceUnavailableError",
                       "detail": "Missing credentials"})
    assert [m for m, _ in out] == ["error"]


def test_a_streaming_delta_is_not_rendered_twice():
    """The final MessageEvent carries the same text whole."""
    out, _ = _collect({"kind": "StreamingDeltaEvent", "delta": "OH-"})
    assert out == []
