"""codex's shell has a switch of its own: `[features] shell_tool = false` (codex 0.154's feature table).

Measured on 0.40.0 with every catalog tool off: codex still offered exec_command and write_stdin, its
shell under unified exec, and only the agent doc asked. The catalog's other names (apply_patch,
read_file, write_file, git) are not tools 0.154 offers on these connections, so they stay asked.
"""
import pathlib
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def _cfg(tmp_path, off, mcp_toml=""):
    env = {"HOME": str(tmp_path)}
    d = rs._codex_prepare_env("openai", rs.Auth(api_key="k"), "gpt-5.5", str(tmp_path), env,
                              mcp_toml=mcp_toml, tools_disabled=off)
    return tomllib.loads((d / "config.toml").read_text())


def test_shell_off_turns_the_feature_off(tmp_path):
    doc = _cfg(tmp_path, ["shell (runs commands)", "read_file"])
    assert doc["features"] == {"shell_tool": False}
    assert doc["model"] == "gpt-5.5" and doc["model_providers"], "the rest of the file is intact"


def test_the_name_codex_sends_works_too():
    assert rs._codex_shell_off(["exec_command"]) and rs._codex_shell_off(["Shell"])
    assert not rs._codex_shell_off(None) and not rs._codex_shell_off(["read_file"])


def test_shell_on_leaves_the_features_alone(tmp_path):
    assert "features" not in _cfg(tmp_path, ["read_file"])


def test_the_feature_table_and_the_mcp_block_keep_to_their_own_keys(tmp_path):
    """Every table holds only its own keys: a key written after a table lands inside it (the MCP
    block used to open with one, and codex refuses a feature it does not know)."""
    mcp = rs._codex_mcp_toml([{"name": "graph", "url": "https://mcp.example/mcp", "auth": "t"}])
    doc = _cfg(tmp_path, ["shell"], mcp_toml=mcp)
    assert doc["features"] == {"shell_tool": False} and "graph" in doc["mcp_servers"]
    assert set(doc["sandbox_workspace_write"]) == {"network_access", "exclude_slash_tmp"}
