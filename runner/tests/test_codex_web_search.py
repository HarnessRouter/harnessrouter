"""Issue #150: codex's built-in web_search has one switch, the top-level config key."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def test_naming_web_search_in_the_disabled_list_turns_the_tool_off_in_config(tmp_path):
    env = {"HOME": str(tmp_path)}
    cfg_dir = rs._codex_prepare_env("openai", rs.Auth(api_key="k"), "gpt-5.5", str(tmp_path), env,
                                    tools_disabled=["Bash", "web_search (search the web)"])
    cfg = (cfg_dir / "config.toml").read_text()
    import tomllib
    doc = tomllib.loads(cfg)
    # At the TOP level: a line appended after the last [table] header belongs to that table and
    # switches nothing (rc.1 shipped exactly that; the tool stayed in the request).
    assert doc["web_search"] == "disabled" and "web_search" not in doc["sandbox_workspace_write"]
    assert doc["model"] == "gpt-5.5" and doc["model_providers"]      # the rest of the file is intact
    assert "Bash" not in cfg                      # the others stay a standing instruction, not config


def test_the_switch_stays_out_of_config_unless_named(tmp_path):
    env = {"HOME": str(tmp_path)}
    cfg_dir = rs._codex_prepare_env("openai", rs.Auth(api_key="k"), "gpt-5.5", str(tmp_path), env, tools_disabled=["Bash"])
    assert "web_search" not in (cfg_dir / "config.toml").read_text()
    import tomllib
    tomllib.loads((cfg_dir / "config.toml").read_text())
    assert rs._codex_web_search_off(["WebSearch"]) and rs._codex_web_search_off(["web-search"]) \
        and not rs._codex_web_search_off(None) and not rs._codex_web_search_off(["web"])


def test_custom_responses_defaults_to_function_tools_only(tmp_path):
    env = {"HOME": str(tmp_path)}
    auth = rs.Auth(api_key="k", base_url="https://example.invalid/v1", api_format="responses")
    cfg_dir = rs._codex_prepare_env("openai", auth, "gpt-5.5", str(tmp_path), env)
    import tomllib
    doc = tomllib.loads((cfg_dir / "config.toml").read_text())
    assert doc["agents"]["enabled"] is False
    assert doc["web_search"] == "disabled"


def test_native_responses_keep_codex_tools_default(tmp_path):
    env = {"HOME": str(tmp_path)}
    auth = rs.Auth(api_key="k", base_url="https://example.invalid/v1")
    cfg_dir = rs._codex_prepare_env("openai", auth, "gpt-5.5", str(tmp_path), env)
    import tomllib
    doc = tomllib.loads((cfg_dir / "config.toml").read_text())
    assert "agents" not in doc and "web_search" not in doc


def test_custom_responses_can_opt_into_codex_tools(tmp_path):
    env = {"HOME": str(tmp_path)}
    auth = rs.Auth(api_key="k", base_url="https://example.invalid/v1", api_format="responses",
                   namespace_tools="1", web_search="1")
    cfg_dir = rs._codex_prepare_env("openai", auth, "gpt-5.5", str(tmp_path), env)
    import tomllib
    doc = tomllib.loads((cfg_dir / "config.toml").read_text())
    assert "agents" not in doc and "web_search" not in doc


def test_explicit_disabled_tools_still_override_custom_opt_in(tmp_path):
    env = {"HOME": str(tmp_path)}
    auth = rs.Auth(api_key="k", base_url="https://example.invalid/v1", api_format="responses",
                   web_search="1")
    cfg_dir = rs._codex_prepare_env("openai", auth, "gpt-5.5", str(tmp_path), env,
                                    tools_disabled=["web_search"])
    import tomllib
    doc = tomllib.loads((cfg_dir / "config.toml").read_text())
    assert doc["web_search"] == "disabled"
