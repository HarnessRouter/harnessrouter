"""A switched-off dsh tool whose profile row registers nothing else is withheld; the rest are asked.

Measured on 0.40.0 with every catalog tool off: all thirteen still in the request (the agent doc
asked). dsh has no per-tool switch, but its sdk profile is rows, and the runner's patch overlay can
switch a row off: the rows below each register one tool (the runtime's own packages, 0.1.2rc1).
A row that registers more than one is switched off only when every tool on it is off.
"""
import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dsh_driver  # noqa: E402
from server import Auth, _TOOLS_OFF_BY_REQUEST, _build_dsh  # noqa: E402

CATALOG = ["bash", "read", "write", "edit", "str_replace_editor", "glob", "grep", "web_fetch",
           "todo_write", "skill", "subagent", "subagent_fork", "workflow"]


def _entries(tmp_path, off):
    return yaml.safe_load(pathlib.Path(dsh_driver._compose_patch(tmp_path / "home", [], cwd=str(tmp_path),
                                                                 tools_off=off)).read_text())


def test_a_single_tool_row_is_switched_off():
    assert dsh_driver._rows_off(["bash", "skill", "subagent_fork"]) == ["tool-bash", "tool-skill", "tool-subagent-fork"]


def test_a_shared_row_goes_only_with_every_tool_on_it():
    assert dsh_driver._rows_off(["glob"]) == []
    assert dsh_driver._rows_off(["glob", "grep"]) == ["tool-fs-search"]
    # read, write and edit share their row with read_image, which is not a switch a harness has
    assert dsh_driver._rows_off(["read", "write", "edit"]) == []


def test_every_catalog_tool_off_switches_off_every_row_it_can(tmp_path):
    entries = _entries(tmp_path, CATALOG)
    off = {e["id"] for e in entries if e.get("disabled") is True}
    assert {"tool-bash", "tool-str-replace-editor", "tool-todo", "tool-skill", "tool-subagent",
            "tool-subagent-fork", "tool-workflow", "tool-fs-search"} <= off
    assert "tool-fs" not in off
    assert {"id": "tool-web", "config": {"search": False, "fetch": False}} in entries


def test_nothing_off_changes_nothing(tmp_path):
    entries = _entries(tmp_path, [])
    assert {"id": "tool-web", "config": {"search": False}} in entries
    assert not [e for e in entries if e.get("id", "").startswith("tool-") and e.get("disabled")]


def test_the_builder_hands_the_names_to_the_driver(tmp_path):
    env: dict = {}
    _build_dsh("deepseek", Auth(api_key="k", base_url="https://tr.example/v1"), "deepseek-v4-pro", "x",
               str(tmp_path), env, tools_disabled=["bash (runs commands)", "glob", "glob"])
    assert json.loads(env["HR_DRIVER_JOB"])["tools_off"] == ["bash", "glob"]


def test_dsh_still_asks_for_what_its_rows_cannot_withhold():
    assert "dsh" in _TOOLS_OFF_BY_REQUEST
