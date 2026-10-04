"""The kilo base (Kilo CLI 7.8.1): its registration in the gateway."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

# runner/tests/test_kilo_backend.py checks every one of these is a key _kilo_denies turns into a
# deny rule; this side checks the catalog offers exactly these.
KILO_CATALOG_TOOLS = ["bash", "read", "edit", "glob", "grep", "webfetch", "task", "todowrite", "skill",
                      "background_process", "kilo_local_recall", "board_post", "board_read", "link_pr",
                      "agent_manager_models"]


def test_catalog_tools_are_the_ones_the_runner_can_withhold():
    assert [t for t, _ in gw._BASE_CATALOG["kilo"]["tools"]] == KILO_CATALOG_TOOLS
    assert gw._BASE_CATALOG["kilo"]["tool_enforcement"] == "hard"


def test_no_switch_that_would_disable_nothing():
    """Kilo gates write and apply_patch on the `edit` key; a separate switch would be a no-op, and
    the scheduling tools are denied by the runner on every turn, so offering them would be a lie."""
    ids = {t for t, _ in gw._BASE_CATALOG["kilo"]["tools"]}
    assert not ids & {"write", "apply_patch", "schedule_wakeup", "cron_create", "goal", "websearch"}


def test_kilo_is_wired_where_opencode_is():
    """Same provider layer, built by the same package choice: every opencode row has a kilo twin
    mapping to the same runner provider, and nothing more."""
    oc = {p: v for (p, b), v in gw._INTEGRATION_WIRING.items() if b == "opencode"}
    kl = {p: v for (p, b), v in gw._INTEGRATION_WIRING.items() if b == "kilo"}
    assert kl == oc
    assert "kilo" in gw._CUSTOM_FORMAT_BACKENDS["openai"] and "kilo" in gw._CUSTOM_FORMAT_BACKENDS["anthropic"]


def test_catalog_is_opencodes_less_what_kilo_s_own_column_failed_and_defaults_like_it():
    assert gw._MODEL_CATALOG["kilo"]["default"] == "gpt-5.4"
    gone = gw._NOT_OFFERED["kilo"]
    assert gone == {"llama-3.3-70b"}      # failed twice on kilo's full-catalog column (2026-10-03)
    assert gw._MODEL_CATALOG["kilo"]["models"] == [m for m in gw._MODEL_CATALOG["opencode"]["models"]
                                                   if m not in gone]
    assert gw._backend_of_builtin("kilo") == "kilo"
