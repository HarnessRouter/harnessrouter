"""What a claude turn with `input_requests` is built with (#476): the ask server in the MCP config
the CLI is pointed at, and the CLI's own AskUserQuestion in the deny list, so a question goes
through the tool that ends the turn rather than one that waits on a terminal nobody is at."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def test_the_mcp_config_carries_the_ask_server_as_stdio(tmp_path):
    path = rs._write_mcp_config_claude(str(tmp_path), [{"name": "plugs", "url": "https://gw/v1/mcp/plugs"},
                                                        rs._ask_user_server()])
    cfg = json.loads(pathlib.Path(path).read_text())["mcpServers"]
    assert cfg["harnessrouter"] == {"type": "stdio", "command": sys.executable,
                                    "args": [str(pathlib.Path(rs.__file__).with_name("ask_user_mcp.py"))]}
    assert cfg["plugs"]["type"] == "http"          # the harness's own servers ride beside it


def test_the_clis_own_question_tool_is_denied(tmp_path):
    env = {"HOME": str(tmp_path / "home")}
    cmd = rs._build_claude("anthropic", rs.Auth(), "claude-sonnet-4.6", "go", 10, str(tmp_path), env,
                           mcp_config=str(tmp_path / "mcp.json"),
                           disallowed_tools=["Bash", "AskUserQuestion"])
    assert cmd[:2] == ["claude", "-p"] and "--mcp-config" in cmd
    settings = json.loads((tmp_path / "home" / ".claude" / "settings.json").read_text())
    assert settings["permissions"]["deny"] == ["Bash", "AskUserQuestion"]
    assert "--disallowedTools" not in cmd          # the deny list is the enforcement, not the flag
