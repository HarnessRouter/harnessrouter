"""Issue #202.1: expose apply_patch_tool_type so Codex registers apply_patch for unknown models."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server as rs  # noqa: E402


def test_apply_patch_tool_type_registers_the_tool_at_top_level(tmp_path):
    env = {"HOME": str(tmp_path)}
    auth = rs.Auth(api_key="k", base_url="https://example.invalid/v1", api_format="responses",
                   apply_patch_tool_type="function")
    cfg_dir = rs._codex_prepare_env("openai", auth, "gpt-5.5", str(tmp_path), env)
    import tomllib
    doc = tomllib.loads((cfg_dir / "config.toml").read_text())
    # Top level like web_search: appended after the last [table] header it would
    # belong to that table and register nothing.
    assert doc["apply_patch_tool_type"] == "function"
    assert "apply_patch_tool_type" not in doc["sandbox_workspace_write"]


def test_apply_patch_tool_type_stays_out_unless_set(tmp_path):
    env = {"HOME": str(tmp_path)}
    auth = rs.Auth(api_key="k", base_url="https://example.invalid/v1", api_format="responses")
    cfg_dir = rs._codex_prepare_env("openai", auth, "gpt-5.5", str(tmp_path), env)
    import tomllib
    doc = tomllib.loads((cfg_dir / "config.toml").read_text())
    assert "apply_patch_tool_type" not in doc


def test_apply_patch_tool_type_rejects_unknown_values():
    with pytest.raises(Exception, match="apply_patch_tool_type"):
        rs._codex_apply_patch_tool_type(rs.Auth(apply_patch_tool_type="freeform-ish"))
    assert rs._codex_apply_patch_tool_type(rs.Auth(apply_patch_tool_type=" Function ")) == "function"
    assert rs._codex_apply_patch_tool_type(rs.Auth()) is None
