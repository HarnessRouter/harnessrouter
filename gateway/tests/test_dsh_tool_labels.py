"""Settings labels each DeepSeek Harness tool for what switching it off really does.

The bases document gives every built-in tool an `enforcement`: `hard` (switched off, the agent is
never offered it) or `instruction` (switched off, the agent is only asked not to use it, and Settings
says "This agent can't switch it off"). DeepSeek Harness's switch is its runtime profile's rows: the
driver takes out the row of a tool that has one to itself, and web_fetch has its row's own switch, so
those tools are withheld. The catalog still labelled the whole base `instruction`, so Settings said
"can't switch it off" of eight tools that were in fact withheld. A tool that shares a row (read,
write and edit with read_image; glob with grep) is withheld only with the rest of its row, so on its
own it is only asked, and keeps the note.

What is withheld is read from the runner's own driver, not copied here: for each tool, switching off
that tool alone either changes what the driver composes for the runtime, or it does not. The driver is
loaded from its file and imports only the standard library at the top.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402  (environment: conftest.py)

DRIVER = pathlib.Path(__file__).resolve().parents[2] / "runner" / "dsh_driver.py"
ME = {"x-harness-internal": "test-internal-key", "x-harness-org": "org.dshlabels", "x-harness-member": "ada@example.com"}


@pytest.fixture(scope="module")
def driver():
    spec = importlib.util.spec_from_file_location("hr_dsh_driver_under_test", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _composed(driver, home: pathlib.Path, off: tuple) -> list:
    return yaml.safe_load(pathlib.Path(driver._compose_patch(home, [], tools_off=off)).read_text())


@pytest.fixture(scope="module")
def withheld_alone(driver, tmp_path_factory) -> set[str]:
    """The catalog's DeepSeek Harness tools that the driver withholds when that tool alone is off."""
    home = tmp_path_factory.mktemp("dsh-home")
    none = _composed(driver, home, ())
    tools = [n for n, _ in gw._BASE_CATALOG["dsh"]["tools"]]
    return {t for t in tools if _composed(driver, home, (t,)) != none}


@pytest.fixture(scope="module")
def labels() -> dict[str, str]:
    """Each DeepSeek Harness tool's label, as the bases document the console reads gives it."""
    with TestClient(gw.app) as c:
        r = c.get("/v1/bases", headers=ME)
    assert r.status_code == 200, r.text
    dsh = next(b for b in r.json()["bases"] if b["id"] == "dsh")
    return {t["name"]: t["enforcement"] for t in dsh["tools"]}


def test_what_the_driver_withholds_is_what_these_tests_say_it_is(withheld_alone, driver):
    """Read off the driver, so a change to its rows changes this list in the same review."""
    assert withheld_alone == {"bash", "str_replace_editor", "todo_write", "skill", "subagent", "subagent_fork",
                              "workflow", "web_fetch"}
    assert set(driver.TOOL_ROWS) <= withheld_alone


def test_a_tool_withheld_on_its_own_is_labelled_hard(labels, withheld_alone):
    assert {n for n, e in labels.items() if e == "hard"} == withheld_alone


def test_a_tool_that_shares_a_row_keeps_the_instruction_label(labels, driver, withheld_alone):
    shared = {t for tools in driver.TOOL_ROW_GROUPS.values() for t in tools} & set(labels)
    assert shared == {"read", "write", "edit", "glob", "grep"}
    for t in shared:
        assert t not in withheld_alone, t
        assert labels[t] == "instruction", t


def test_the_base_itself_stays_one_the_runner_asks():
    """The runner still writes the switched-off tools into the agent doc for DeepSeek Harness, since a
    shared-row tool can only be asked; the base's own word stays `instruction`
    (test_tool_enforcement_parity.py holds that to the runner)."""
    b = gw._BASE_CATALOG["dsh"]
    assert b["tool_enforcement"] == "instruction"
    assert set(b["hard_tools"]) <= {n for n, _ in b["tools"]}


def test_every_other_base_is_labelled_by_its_own_word():
    for bid, b in gw._BASE_CATALOG.items():
        # each held to its runner by its own test (hermes: test_hermes_tool_labels.py, agy: test_agy_catalog.py)
        if bid in ("dsh", "hermes", "agy"):
            continue
        assert "hard_tools" not in b, bid
        assert {gw._tool_enforcement(b, n) for n, _ in b["tools"]} <= {b["tool_enforcement"]}, bid
