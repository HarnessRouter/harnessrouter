"""A switched-off hermes tool whose whole toolset is off is withheld; the rest are asked.

Measured on 0.40.0 with every catalog tool off: terminal and the four file tools all still in the
request (the agent doc asked). hermes switches toolsets, never single tools (agent.disabled_toolsets),
so a toolset goes off only when the harness switched off everything in it that it can switch.
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402

FILE = ["read_file", "write_file", "patch", "search_files"]


def _hermes_cfg(tmp_path, **kw) -> dict:
    env = {"HOME": str(tmp_path)}
    server._hermes_prepare_env("bedrock", server.Auth(), str(tmp_path), env, model="m", **kw)
    return yaml.safe_load((tmp_path / ".hermes" / "config.yaml").read_text())


def test_terminal_off_switches_its_toolset_off():
    assert server._hermes_toolsets_off(["terminal (runs commands)"]) == ["terminal"]


def test_the_file_toolset_goes_only_with_all_four():
    assert server._hermes_toolsets_off(FILE[:3]) == []
    assert server._hermes_toolsets_off(FILE) == ["file"]


def test_web_search_alone_has_its_own_toolset_and_with_extract_both_go():
    assert server._hermes_toolsets_off(["web_search"]) == ["search"]
    assert server._hermes_toolsets_off(["web_extract"]) == []
    assert server._hermes_toolsets_off(["web_search", "web_extract"]) == ["web", "search"]


def test_every_catalog_tool_off_lands_in_config(tmp_path):
    cfg = _hermes_cfg(tmp_path, tools_disabled=["terminal", *FILE, "web_search", "web_extract"])
    assert cfg["agent"]["disabled_toolsets"] == ["file", "terminal", "web", "search"]
    assert cfg["agent"]["verify_on_stop"] is False, "the rest of the file is as it was"


def test_it_sits_beside_the_own_memory_toolsets(tmp_path):
    cfg = _hermes_cfg(tmp_path, own_memory_off=True, tools_disabled=["terminal"])
    assert cfg["agent"]["disabled_toolsets"] == ["memory", "session_search", "terminal"]


def test_nothing_off_writes_no_list(tmp_path):
    assert "disabled_toolsets" not in _hermes_cfg(tmp_path, tools_disabled=["read_file"])["agent"]


def test_hermes_still_asks_for_what_its_toolsets_cannot_withhold():
    assert "hermes" in server._TOOLS_OFF_BY_REQUEST
