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


# ── the relay repair this column found ──
def test_an_assistant_messages_block_list_flattens_to_a_string():
    """MEASURED against the live endpoint (2026-09-18): the identical chat/completions request
    answers 200 with `content: "M1"` on the assistant turn and 400 with
    `content: [{"type": "text", "text": "M1"}]`, and the 400 reads `Assistant message must have
    either content or tool_calls, but not none.` about a message whose content is right there.
    The OpenHands SDK sends the array form for every replayed assistant turn, so a first turn
    passes and every one after it fails: four of five scenarios on
    vercel|openhands|mistral-medium-3.5."""
    from server import _stringify_assistant_content
    body = json.dumps({"model": "m", "messages": [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "M1"}]},
        {"role": "tool", "content": [{"type": "text", "text": "out"}]},
    ]}).encode()
    out = json.loads(_stringify_assistant_content(body))
    assert out["messages"][1]["content"] == "M1"
    # the other roles are left exactly as they were: user arrays are accepted everywhere, and the
    # tool role has its own repair with its own trigger
    assert out["messages"][0]["content"] == [{"type": "text", "text": "hi"}]
    assert out["messages"][2]["content"] == [{"type": "text", "text": "out"}]


def test_a_body_with_nothing_to_flatten_is_returned_untouched():
    """Byte-identical, so the retry loop can tell 'no repair applies' from 'repaired'."""
    from server import _stringify_assistant_content
    body = json.dumps({"model": "m", "messages": [
        {"role": "assistant", "content": "already a string"}]}).encode()
    assert _stringify_assistant_content(body) == body


def test_an_unparseable_body_is_never_altered():
    from server import _stringify_assistant_content
    assert _stringify_assistant_content(b"not json") == b"not json"


# ── MCP: declared servers reach the agent ──
def test_a_url_server_carries_the_transport_the_harness_declared():
    """The rule #191's review set for kimi, one backend over: the harness says what a server
    speaks and the url's spelling decides nothing."""
    from server import _openhands_mcp_config
    cfg = _openhands_mcp_config([
        {"name": "events", "transport": "sse", "url": "https://example.test/events"},
        {"name": "api", "transport": "http", "url": "https://example.test/mcp"},
    ])
    assert cfg["events"] == {"url": "https://example.test/events", "transport": "sse"}
    assert cfg["api"] == {"url": "https://example.test/mcp", "transport": "http"}


def test_a_transport_the_sdk_does_not_know_is_dropped_rather_than_guessed():
    """Its own values are stdio/http/streamable-http/sse. A config the SDK rejects fails the whole
    turn, not the one server, so an unknown word is left out and the SDK decides."""
    from server import _openhands_mcp_config
    cfg = _openhands_mcp_config([{"name": "x", "transport": "carrier-pigeon",
                                  "url": "https://example.test/mcp"}])
    assert cfg["x"] == {"url": "https://example.test/mcp"}


def test_a_stdio_server_reaches_the_agent_as_command_and_args():
    from server import _openhands_mcp_config
    cfg = _openhands_mcp_config([{"name": "local", "command": ["node", "srv.js"],
                                  "args": ["--flag"], "env": {"K": "v"}}])
    assert cfg["local"]["transport"] == "stdio"
    assert cfg["local"]["command"] == "node"
    assert cfg["local"]["args"] == ["srv.js", "--flag"]
    assert cfg["local"]["env"] == {"K": "v"}


def test_declared_headers_travel():
    from server import _openhands_mcp_config
    cfg = _openhands_mcp_config([{"name": "api", "url": "https://example.test/mcp",
                                  "headers": {"X-K": "v"}}])
    assert cfg["api"]["headers"] == {"X-K": "v"}


def test_the_config_actually_reaches_the_agent():
    """The defect aider's bridge taught this repo: a block generated by a function nobody called.
    Pinned end to end rather than at the seam."""
    spec = drv._agent_spec({"model": "m", "mcp_config": {"deepwiki": {"url": "https://x/mcp"}}})
    assert spec["mcp_config"] == {"deepwiki": {"url": "https://x/mcp"}}
    assert "mcp_config" not in drv._agent_spec({"model": "m"})


def test_declaring_a_server_is_a_different_agent():
    """The agent is frozen at creation, so a server added later cannot reach the one already made;
    the identity carries the servers for the same reason it carries the tool policy."""
    bare = drv._conversation_id(["terminal"], {})
    with_mcp = drv._conversation_id(["terminal"], {"deepwiki": {"url": "https://x/mcp"}})
    assert bare != with_mcp
    assert drv._conversation_id(["terminal"], {}) == bare
