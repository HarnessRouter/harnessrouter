"""Guard: a Claude Code plugin's own scripts must be executable once materialized, and its
stdio-transport MCP servers must not be silently dropped.

The first regression this pins was found live: `_write_plugins` wrote a plugin's
`hooks/*.sh` and `bin/*` files with the default (non-executable) mode, so every hook
invocation failed with "Permission denied" and the plugin's own MCP server (itself a
shell script under `bin/`) never started — invisible until a real `--plugin-dir` turn
actually tried to run one. Verified against a real Claude Code plugin end to end
(`claude -p --plugin-dir ... --include-hook-events`): before the fix, hooks errored
with exit_code 126 and the MCP server connection status was "failed"; after, hooks ran
clean and the server connected.

The second regression `_write_mcp_config_claude` used to have: it only ever emitted
http/sse entries, silently skipping any server dict with no `url` — but `stdio` is the
CLI's own default MCP transport (`claude mcp add` defaults to it), so a stdio server
config (`{"command": ..., "args": [...]}`) was dropped with no error at all.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402


def test_bin_files_are_written_executable(tmp_path):
    plugin = {
        "name": "demo",
        "files": [
            {"path": ".claude-plugin/plugin.json", "content": "{}"},
            {"path": "bin/demo-run", "content": "#!/bin/sh\necho hi\n"},
        ],
    }
    dirs = rn._write_plugins(str(tmp_path), [plugin])
    assert len(dirs) == 1
    entry = Path(dirs[0]) / "bin" / "demo-run"
    assert entry.is_file()
    assert entry.stat().st_mode & 0o111, "bin/demo-run was not written executable"


def test_hook_scripts_are_written_executable(tmp_path):
    plugin = {
        "name": "demo",
        "files": [
            {"path": ".claude-plugin/plugin.json", "content": "{}"},
            {"path": "hooks/notice.sh", "content": "#!/bin/sh\nexit 0\n"},
        ],
    }
    dirs = rn._write_plugins(str(tmp_path), [plugin])
    entry = Path(dirs[0]) / "hooks" / "notice.sh"
    assert entry.stat().st_mode & 0o111, "hooks/notice.sh was not written executable"


def test_ordinary_files_are_not_made_executable(tmp_path):
    plugin = {
        "name": "demo",
        "files": [
            {"path": ".claude-plugin/plugin.json", "content": "{}"},
            {"path": "vesta/graph.py", "content": "x = 1\n"},
        ],
    }
    dirs = rn._write_plugins(str(tmp_path), [plugin])
    entry = Path(dirs[0]) / "vesta" / "graph.py"
    assert not (entry.stat().st_mode & 0o111), "a plain source file was made executable"


def test_a_declared_executable_flag_is_honoured_outside_the_known_paths(tmp_path):
    plugin = {
        "name": "demo",
        "files": [
            {"path": ".claude-plugin/plugin.json", "content": "{}"},
            {"path": "scripts/setup", "content": "#!/bin/sh\n", "executable": True},
        ],
    }
    dirs = rn._write_plugins(str(tmp_path), [plugin])
    entry = Path(dirs[0]) / "scripts" / "setup"
    assert entry.stat().st_mode & 0o111


def test_multiple_plugins_land_in_their_own_directories(tmp_path):
    plugins = [
        {"name": "a", "files": [{"path": ".claude-plugin/plugin.json", "content": "{}"}]},
        {"name": "b", "files": [{"path": ".claude-plugin/plugin.json", "content": "{}"}]},
    ]
    dirs = rn._write_plugins(str(tmp_path), plugins)
    assert len(dirs) == 2
    assert {Path(d).name for d in dirs} == {"a", "b"}


def test_a_plugin_with_no_files_is_skipped(tmp_path):
    dirs = rn._write_plugins(str(tmp_path), [{"name": "empty", "files": []}])
    assert dirs == []


def test_build_claude_appends_one_plugin_dir_flag_per_plugin():
    cmd = rn._build_claude(
        provider="anthropic", auth=rn.Auth(), model="claude-sonnet-5",
        prompt="hi", max_turns=5, cwd="/tmp/ws", env={"HOME": "/tmp/ws/.harness/home"},
        plugin_dirs=["/tmp/ws/.harness/plugins/a", "/tmp/ws/.harness/plugins/b"],
    )
    assert cmd.count("--plugin-dir") == 2
    ia = cmd.index("--plugin-dir")
    assert cmd[ia + 1] == "/tmp/ws/.harness/plugins/a"
    ib = cmd.index("--plugin-dir", ia + 1)
    assert cmd[ib + 1] == "/tmp/ws/.harness/plugins/b"


def test_build_claude_with_no_plugins_appends_no_flag():
    cmd = rn._build_claude(
        provider="anthropic", auth=rn.Auth(), model="claude-sonnet-5",
        prompt="hi", max_turns=5, cwd="/tmp/ws", env={"HOME": "/tmp/ws/.harness/home"},
    )
    assert "--plugin-dir" not in cmd


def test_mcp_config_writes_a_stdio_entry(tmp_path):
    path = rn._write_mcp_config_claude(
        str(tmp_path), [{"name": "vesta", "command": "/plugin/bin/vesta-sidecar"}],
    )
    assert path is not None
    import json
    cfg = json.loads(Path(path).read_text())
    entry = cfg["mcpServers"]["vesta"]
    assert entry == {"type": "stdio", "command": "/plugin/bin/vesta-sidecar", "args": []}


def test_mcp_config_stdio_entry_carries_args_and_env(tmp_path):
    path = rn._write_mcp_config_claude(
        str(tmp_path),
        [{"name": "demo", "command": "npx", "args": ["my-mcp-server"], "env": {"KEY": "x"}}],
    )
    cfg_json = Path(path).read_text()
    import json
    entry = json.loads(cfg_json)["mcpServers"]["demo"]
    assert entry["args"] == ["my-mcp-server"]
    assert entry["env"] == {"KEY": "x"}


def test_mcp_config_still_writes_http_entries_unchanged(tmp_path):
    path = rn._write_mcp_config_claude(
        str(tmp_path), [{"name": "remote", "url": "https://example.invalid/mcp"}],
    )
    import json
    entry = json.loads(Path(path).read_text())["mcpServers"]["remote"]
    assert entry == {"type": "http", "url": "https://example.invalid/mcp"}


def test_mcp_config_with_neither_url_nor_command_is_skipped(tmp_path):
    path = rn._write_mcp_config_claude(str(tmp_path), [{"name": "broken"}])
    assert path is None
