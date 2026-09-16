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


def test_pi_adapter_gets_a_stdio_command_entry(tmp_path):
    """pi-mcp-adapter spawns a stdio server itself (`command`, mutually exclusive with `url`), so
    a plugin's server reaches pi as the launcher the runner wrote, beside the URL servers. Before
    this the writer skipped anything without a url and the gateway refused the package for pi."""
    home = tmp_path / "home"
    servers = [{"name": "probe", "command": "/ws/.harness/plugin-data/hr_probe/.launch-probe.sh",
                "args": ["--data", "/ws/.harness/plugin-data/hr_probe"], "plugin": "hr-probe"},
               {"name": "remote", "url": "https://mcp.example.invalid/mcp", "headers": {"X-Team": "t"}}]
    assert rn._pi_write_mcp(home, servers) is True
    cfg = json.loads((home / ".pi" / "agent" / "mcp.json").read_text())["mcpServers"]
    assert cfg["probe"] == {"command": "/ws/.harness/plugin-data/hr_probe/.launch-probe.sh",
                            "args": ["--data", "/ws/.harness/plugin-data/hr_probe"]}
    assert cfg["remote"] == {"url": "https://mcp.example.invalid/mcp", "headers": {"X-Team": "t"}}


def test_dsh_client_gets_a_stdio_row(tmp_path):
    """dsh-mcp-client has a stdio transport of its own (StdioClientTransport on command/args), so a
    plugin's server is one more inserted client row, discriminated on transport."""
    import yaml
    import dsh_driver
    home = tmp_path / "home"
    servers = [{"name": "probe", "command": "/ws/.harness/plugin-data/hr_probe/.launch-probe.sh",
                "args": ["--data", "/ws/.harness/plugin-data/hr_probe"], "plugin": "hr-probe"},
               {"name": "remote", "url": "https://mcp.example.invalid/mcp"}]
    out = pathlib.Path(dsh_driver._compose_patch(home, servers, relay_port=9999, model="m", cwd=str(tmp_path / "ws")))
    rows = [r for e in yaml.safe_load(out.read_text()) if isinstance(e, dict) for r in (e.get("insert") or [])
            if r.get("name") == "@deepseek-ai/dsh-mcp-client"]
    by = {r["config"]["serverName"]: r["config"] for r in rows}
    assert by["probe"] == {"transport": "stdio", "serverName": "probe", "cwd": str(tmp_path / "ws"),
                           "command": "/ws/.harness/plugin-data/hr_probe/.launch-probe.sh",
                           "args": ["--data", "/ws/.harness/plugin-data/hr_probe"]}
    assert by["remote"]["transport"] == "streamable-http" and by["remote"]["url"] == "https://mcp.example.invalid/mcp"


def test_an_sse_server_reaches_each_client_in_its_own_spelling(tmp_path):
    """gemini and qwen name the transport by the key (`url` is SSE, `httpUrl` streamable HTTP);
    cline and omp by a type. Every writer used to emit the streamable form for any url, so an sse
    server was configured but never loaded (hosted, 2026-09-15: SSE=MISSING on all four)."""
    sse = {"name": "probe_sse", "url": "https://probe.example.invalid/sse", "transport": "sse"}
    http = {"name": "probe_http", "url": "https://probe.example.invalid/mcp", "transport": "http"}
    rn._gemini_settings(tmp_path / "g", [sse, http], "gemini-3.8-flash")
    g = json.loads((tmp_path / "g" / ".gemini" / "settings.json").read_text())["mcpServers"]
    assert g["probe_sse"] == {"url": sse["url"]} and g["probe_http"] == {"httpUrl": http["url"]}
    rn._qwen_settings(tmp_path / "q", [sse, http])
    q = json.loads((tmp_path / "q" / ".qwen" / "settings.json").read_text())["mcpServers"]
    assert q["probe_sse"] == {"url": sse["url"]} and q["probe_http"] == {"httpUrl": http["url"]}
    omp_dir = tmp_path / "omp"
    assert rn._omp_write_mcp(omp_dir, [sse, http]) is True
    o = json.loads((omp_dir / "mcp.json").read_text())["mcpServers"]
    assert o["probe_sse"]["type"] == "sse" and o["probe_http"]["type"] == "http"


def test_a_client_without_sse_gets_the_server_through_the_stdio_bridge(tmp_path):
    """goose 1.50.0's ExtensionConfig has no sse variant, dsh-mcp-client's config is a union of
    stdio and streamable-http, codex's client takes streamable HTTP and stdio. Each launches a
    stdio server, so an SSE server reaches them as the bridge: url and headers in the launcher's
    environment, never on its command line; other servers and other backends pass untouched."""
    sse = {"name": "probe_sse", "url": "https://probe.example.invalid/sse", "transport": "sse",
           "auth": "secret-token", "headers": {"X-Team": "t"}, "plugin": "hr-probe"}
    http = {"name": "probe_http", "url": "https://probe.example.invalid/mcp", "transport": "http"}
    for backend in ("goose", "dsh", "codex"):
        out = rn._sse_bridges(str(tmp_path), [sse, http], backend)
        assert out[1] == http
        b = out[0]
        assert b["name"] == "probe_sse" and b["plugin"] == "hr-probe" and b["args"] == [] and "url" not in b and "auth" not in b
        text = pathlib.Path(b["command"]).read_text()
        assert "HR_MCP_URL=https://probe.example.invalid/sse" in text and "HR_MCP_TRANSPORT=sse" in text
        assert '"Authorization": "Bearer secret-token"' in text and '"X-Team": "t"' in text
        assert text.rstrip().endswith("mcp_bridge.py") and os.access(b["command"], os.X_OK)
    assert rn._sse_bridges(str(tmp_path), [sse, http], "claude") == [sse, http]
    # the writers then see a stdio entry, as for any plugin server
    ext = rn._goose_extensions(rn._sse_bridges(str(tmp_path), [sse, http], "goose"), None)
    assert ext["probe_sse"]["type"] == "stdio" and ext["probe_http"]["type"] == "streamable_http"

def test_dsh_job_keeps_a_stdio_server(tmp_path):
    """_build_dsh hands the driver a job whose server list kept only urls, from before plugins:
    the stdio row the driver knows how to write never saw the server (hosted, 2026-09-15, the
    compose patch held the http row alone)."""
    env = {"HOME": str(tmp_path)}
    servers = [{"name": "probe", "command": "/ws/.launch-probe.sh", "args": ["--data", "/d"], "plugin": "hr-probe"},
               {"name": "remote", "url": "https://mcp.example.invalid/mcp"}]
    cmd = rn._build_dsh("deepseek", rn.Auth(api_key="k", base_url="https://api.deepseek.com"), "deepseek-v4-pro", "x", str(tmp_path), env, mcp_servers=servers)
    job = json.loads(cmd[2])
    assert [s["name"] for s in job["mcp_servers"]] == ["probe", "remote"]
