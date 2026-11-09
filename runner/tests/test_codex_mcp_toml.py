"""codex's MCP block is tables only.

It opened with `experimental_use_rmcp_client = true`, an opt-in older Codex releases needed for an HTTP
server that 0.154 neither reads nor names (the string is not in its binary). Appended after the config's
last table, the key landed inside that table: [sandbox_workspace_write], a resumed session's provider
alias, or the turn's own [features] (where codex expects only feature names).
"""
import pathlib
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402

SERVERS = [{"name": "graph", "url": "https://mcp.example/mcp", "auth": "t"},
           {"name": "local", "command": "/usr/bin/python3", "args": ["-m", "srv"]}]


def test_the_block_is_tables_only():
    mcp = rs._codex_mcp_toml(SERVERS)
    first = next(line for line in mcp.splitlines() if line.strip())
    assert first.startswith("[mcp_servers."), first
    assert "experimental_use_rmcp_client" not in mcp


def test_no_table_takes_a_key_that_is_not_its_own(tmp_path):
    env = {"HOME": str(tmp_path)}
    d = rs._codex_prepare_env("openai", rs.Auth(api_key="k"), "gpt-5.5", str(tmp_path), env,
                              mcp_toml=rs._codex_mcp_toml(SERVERS))
    doc = tomllib.loads((d / "config.toml").read_text())
    assert set(doc["sandbox_workspace_write"]) == {"network_access", "exclude_slash_tmp"}
    assert doc["mcp_servers"]["graph"]["url"] == "https://mcp.example/mcp"
    assert doc["mcp_servers"]["local"]["command"] == "/usr/bin/python3"
    assert "experimental_use_rmcp_client" not in (d / "config.toml").read_text()
