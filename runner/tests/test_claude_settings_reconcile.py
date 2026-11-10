"""Claude Code's settings.json is reconciled with the harness on every turn.

Disabled tools are a permissions.deny list in $HOME/.claude/settings.json, and HOME is checkpointed. The list
was written only when something was off, so a tool switched back on stayed denied by the file an earlier
turn left: the harness said it was on and the agent did not have it.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server  # noqa: E402


def _turn(tmp_path, **kw) -> dict | None:
    env = {"HOME": str(tmp_path)}
    server._build_claude("anthropic", server.Auth(provider="anthropic", api_key="k", base_url="https://api.anthropic.com/v1"),
                         "claude-haiku-4.5", "hi", 1, str(tmp_path), env, **kw)
    p = tmp_path / ".claude" / "settings.json"
    return json.loads(p.read_text()) if p.exists() else None


def test_a_tool_switched_back_on_is_no_longer_denied(tmp_path):
    assert _turn(tmp_path, disallowed_tools=["Bash", "WebFetch (fetch)"])["permissions"]["deny"] == ["Bash", "WebFetch"]
    assert _turn(tmp_path, disallowed_tools=["WebFetch"])["permissions"]["deny"] == ["WebFetch"]
    assert "permissions" not in _turn(tmp_path, disallowed_tools=[])


def test_the_subagent_id_harnesses_store_is_denied_by_the_tools_name_now(tmp_path):
    """"Task" is the catalog's id for the subagent tool, which Claude Code 2.1.280 names Agent: the deny
    list carries Agent, once, whichever of the two a harness holds."""
    assert _turn(tmp_path, disallowed_tools=["Bash", "Task"])["permissions"]["deny"] == ["Bash", "Agent"]
    assert _turn(tmp_path, disallowed_tools=["Task", "Agent"])["permissions"]["deny"] == ["Agent"]


def test_nothing_off_on_a_fresh_session_writes_no_file(tmp_path):
    assert _turn(tmp_path) is None


def test_the_rest_of_the_file_stays(tmp_path):
    _turn(tmp_path, disallowed_tools=["Bash"])
    p = tmp_path / ".claude" / "settings.json"
    p.write_text(json.dumps({**json.loads(p.read_text()), "theme": "dark",
                             "permissions": {"deny": ["Bash"], "allow": ["Read"]}}))
    cfg = _turn(tmp_path)
    assert cfg == {"theme": "dark", "permissions": {"allow": ["Read"]}}


def test_auto_memory_follows_the_platform_memory_turn_by_turn(tmp_path):
    assert _turn(tmp_path, own_memory_off=True) == {"autoMemoryEnabled": False}
    assert _turn(tmp_path, own_memory_off=True, disallowed_tools=["Bash"]) == \
        {"autoMemoryEnabled": False, "permissions": {"deny": ["Bash"]}}
    assert _turn(tmp_path) == {}, "a turn without the platform's memory gives Claude Code its own back"
