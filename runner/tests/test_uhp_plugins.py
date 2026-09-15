"""UHP Plugins §6 in the runner: a package lands whole at its root with a data directory, and a
stdio server a plugin declares runs through a launcher that sets PLUGIN_ROOT and PLUGIN_DATA,
expands the two placeholders once, resolves a ./ command against the root, and honours cwd. The
launcher is real: one test runs it and reads what the child process saw."""
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rn  # noqa: E402

PKG = {"name": "demo-plugin", "files": [
    {"path": "plugin.json", "content": "{}"},
    {"path": "bin/probe.sh", "content": "#!/bin/sh\nprintf '%s|%s|%s|%s|' \"$PLUGIN_ROOT\" \"$PLUGIN_DATA\" \"$MODE\" \"$(pwd)\"; printf '%s|' \"$@\"\n"},
]}


def _server(**over):
    return {"name": "probe", "plugin": "demo-plugin", "command": "./bin/probe.sh",
            "args": ["--data", "${PLUGIN_DATA}/x", "${PLUGIN_ROOT}"], "env": {"MODE": "t-${PLUGIN_DATA}"}, **over}


def test_a_package_lands_at_its_root_with_a_data_directory(tmp_path):
    roots = rn._write_plugins(str(tmp_path), [PKG])
    assert roots == [str(tmp_path / ".harness/plugins/demo_plugin")]
    assert (tmp_path / ".harness/plugins/demo_plugin/bin/probe.sh").is_file()
    assert (tmp_path / ".harness/plugin-data/demo_plugin").is_dir()


def test_the_launcher_runs_the_command_with_root_data_env_cwd_and_args(tmp_path):
    rn._write_plugins(str(tmp_path), [PKG])
    (out,) = rn._plugin_launchers(str(tmp_path), [_server()])
    assert out["name"] == "probe" and out["command"].endswith("/.launch-probe.sh") and "env" not in out
    root = str(tmp_path / ".harness/plugins/demo_plugin")
    data = str(tmp_path / ".harness/plugin-data/demo_plugin")
    assert out["args"] == ["--data", f"{data}/x", root], "placeholders expand in args"
    seen = subprocess.run([out["command"], *out["args"], "extra"], capture_output=True, text=True, timeout=10)
    assert seen.returncode == 0, seen.stderr
    got = seen.stdout.split("|")
    assert got[0] == root and got[1] == data, "PLUGIN_ROOT and PLUGIN_DATA reach the process"
    assert got[2] == f"t-{data}", "the env overlay is expanded and exported"
    assert os.path.realpath(got[3]) == os.path.realpath(root), "cwd defaults to the plugin root"
    assert got[4:8] == ["--data", f"{data}/x", root, "extra"], "args are passed as argv, unparsed"


def test_cwd_may_sit_in_the_root_or_the_data_directory_and_nowhere_else(tmp_path):
    rn._write_plugins(str(tmp_path), [PKG])
    (a,) = rn._plugin_launchers(str(tmp_path), [_server(cwd="${PLUGIN_DATA}/work")])
    seen = subprocess.run([a["command"]], capture_output=True, text=True, timeout=10).stdout.split("|")
    assert seen[3].endswith("/.harness/plugin-data/demo_plugin/work"), "a data-rooted cwd is created and used"
    (b,) = rn._plugin_launchers(str(tmp_path), [_server(cwd="./sub")])
    seen = subprocess.run([b["command"]], capture_output=True, text=True, timeout=10).stdout.split("|")
    assert seen[3].endswith("/.harness/plugins/demo_plugin/sub")
    assert rn._plugin_launchers(str(tmp_path), [_server(cwd="/etc")]) == []
    assert rn._plugin_launchers(str(tmp_path), [_server(cwd="${PLUGIN_ROOT}/../../escape")]) == []


def test_an_escaping_command_is_dropped_and_a_bare_one_kept(tmp_path):
    rn._write_plugins(str(tmp_path), [PKG])
    assert rn._plugin_launchers(str(tmp_path), [_server(command="./../../bin/sh")]) == []
    (bare,) = rn._plugin_launchers(str(tmp_path), [_server(command="sh", args=["-c", "echo hi"])])
    assert subprocess.run([bare["command"], *bare["args"]], capture_output=True, text=True, timeout=10).stdout.strip() == "hi"


def test_the_reserved_names_cannot_be_overridden_from_env(tmp_path):
    rn._write_plugins(str(tmp_path), [PKG])
    (out,) = rn._plugin_launchers(str(tmp_path), [_server(env={"PLUGIN_ROOT": "/tmp/evil", "plugin_data": "/x", "MODE": "ok"})])
    text = pathlib.Path(out["command"]).read_text()
    assert "/tmp/evil" not in text and "plugin_data" not in text and "export MODE=ok" in text
    assert text.count("export PLUGIN_ROOT=") == 1 and text.count("export PLUGIN_DATA=") == 1


def test_servers_that_are_not_a_plugins_pass_through(tmp_path):
    direct = {"name": "vault", "url": "https://mcp.example.invalid/mcp"}
    assert rn._plugin_launchers(str(tmp_path), [direct]) == [direct]


def test_a_plugin_without_a_root_in_this_workspace_is_skipped(tmp_path):
    assert rn._plugin_launchers(str(tmp_path), [_server()]) == []


def test_every_url_only_writer_now_carries_a_stdio_entry(tmp_path):
    srv = [{"name": "probe", "command": "/ws/.harness/plugin-data/demo/.launch-probe.sh", "args": ["--x", "1"]},
           {"name": "vault", "url": "https://mcp.example.invalid/mcp"}]
    toml = rn._codex_mcp_toml(srv)
    assert '[mcp_servers.probe]\ncommand = "/ws/.harness/plugin-data/demo/.launch-probe.sh"\nargs = ["--x", "1"]' in toml
    assert "[mcp_servers.vault]" in toml
    hermes = rn._hermes_mcp_section(srv)
    assert hermes["probe"] == {"command": "/ws/.harness/plugin-data/demo/.launch-probe.sh", "args": ["--x", "1"]}
    assert hermes["vault"]["url"].startswith("https://")
    home = tmp_path / "home"
    rn._cline_settings(home, "https://relay", "k", "m", srv)
    cline = json.loads((home / ".cline/data/settings/cline_mcp_settings.json").read_text())["mcpServers"]
    assert cline["probe"]["transport"] == {"type": "stdio", "command": "/ws/.harness/plugin-data/demo/.launch-probe.sh", "args": ["--x", "1"]}
    agent = tmp_path / "omp"
    assert rn._omp_write_mcp(agent, srv)
    omp = json.loads((agent / "mcp.json").read_text())["mcpServers"]
    assert omp["probe"] == {"type": "stdio", "command": "/ws/.harness/plugin-data/demo/.launch-probe.sh", "args": ["--x", "1"]}
    assert omp["vault"]["type"] == "http"


def test_a_dot_command_is_made_runnable_and_control_chars_are_escaped_for_codex(tmp_path):
    pkg = {"name": "demo-plugin", "files": [{"path": "plugin.json", "content": "{}"},
                                             {"path": "server.sh", "content": "#!/bin/sh\necho started\n"}]}
    rn._write_plugins(str(tmp_path), [pkg])
    (out,) = rn._plugin_launchers(str(tmp_path), [_server(command="./server.sh", args=["a\nb"])])
    assert subprocess.run([out["command"]], capture_output=True, text=True, timeout=10).stdout.strip() == "started"
    toml = rn._codex_mcp_toml([out])
    assert "\\n" in toml and "\n\n" not in toml.split("args = ")[1].split("]")[0]


def test_stale_plugin_roots_and_skills_are_removed_on_the_next_turn(tmp_path):
    rn._write_plugins(str(tmp_path), [PKG, {"name": "other", "files": [{"path": "plugin.json", "content": "{}"}]}])
    assert (tmp_path / ".harness/plugins/other").is_dir()
    rn._write_plugins(str(tmp_path), [PKG])
    assert not (tmp_path / ".harness/plugins/other").exists() and (tmp_path / ".harness/plugins/demo_plugin").is_dir()
    skill = {"name": "risk", "files": [{"path": "SKILL.md", "content": "---\nname: risk\ndescription: x\n---\n"}]}
    rn._write_skills(str(tmp_path), [skill], "claude")
    assert (tmp_path / ".harness/home/.claude/skills/risk/SKILL.md").is_file()
    rn._write_skills(str(tmp_path), [], "claude")
    assert not (tmp_path / ".harness/home/.claude/skills/risk").exists()


def test_a_symlinked_data_directory_is_not_followed(tmp_path):
    rn._write_plugins(str(tmp_path), [PKG])
    outside = tmp_path / "outside"; outside.mkdir()
    data = tmp_path / ".harness/plugin-data/demo_plugin"
    import shutil as _sh; _sh.rmtree(data); data.symlink_to(outside)
    (out,) = rn._plugin_launchers(str(tmp_path), [_server()])
    assert not data.is_symlink() and data.is_dir(), "the planted link is replaced by a real directory"
    assert pathlib.Path(out["command"]).parent.resolve() == data.resolve()
    assert not list(outside.iterdir()), "nothing was written through the link"
