"""vtcode is implemented and deliberately NOT offered — this pins that state at every surface.

VT Code 0.177.0 works as a runner path: it has a measured support-matrix column (vercel,
2026-10-19 — 56 of the catalog's 58 ids ran and 55 passed all five scenarios), and the runner still
carries `_build_vtcode`, `_vtcode_to_claude`, `_vtcode_eof`, their tests and their captured
fixtures. What stops it is half of what a harness IS here:

  **A harness's MCP servers cannot reach the model in `vtcode exec`.** Measured on 0.177.0 and
  again on 0.180.0 (2026-10-19/20) with a stdio MCP server written for the probe, which appends a
  line the moment it is started and then answers the protocol by hand: the log holds exactly
  `spawned <ts>` and NOT ONE `initialize`. The CLI launches the server its own config names and
  never speaks to it, so no tool is ever registered. `search_tools` — the only other door, and the
  one this runtime defers everything else behind — answers `[Execution failed] session tool catalog
  is not available`, because `attach_session_model_tools` is called by the INTERACTIVE runloop
  alone ("Headless paths may never call this", its own doc comment) and `execute_search_tools`
  errors instead of degrading as that comment requires.

  Ruled out, each by measurement rather than by reading: the tool profile (`advanced_vtcode` adds
  its own tools and no MCP tool), the surface gate (`SessionSurface::AgentRunner => true` allows
  every tool), the MCP allow-list (`default_allowlist_enforced() == false`), the config shape
  (`[[mcp.providers]]` is what `McpClientConfig.providers` declares, and exec does read it — that
  is how the server gets spawned), bridging the server as stdio (the bridge produces a stdio
  server, which is exactly what is ignored), and `vtcode mcp list` (it reads its own registry, not
  the workspace config, so there is no warm-up that would populate a cache before a turn).

A base that answers every turn and silently drops the MCP servers a person declared is the
overstatement this product refuses, so it waits for upstream. A half-restore is the risk this file
exists for — listed but not routable, or routable but not installed, fails on a user's first turn
with nothing to read — so the rule is all or nothing, and today it is none.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_gateway_neither_lists_nor_routes_it():
    assert "vtcode" not in A._BASE_CATALOG
    assert "vtcode" not in A._MODEL_CATALOG
    assert "vtcode" not in A._SUPPORTED_BASES
    assert not A._HID_PREFIX_RE.match("/vtcode/v1/responses")
    assert not any(b == "vtcode" for _p, b in A._INTEGRATION_WIRING)
    assert not any("vtcode" in bs for bs in A._CUSTOM_FORMAT_BACKENDS.values())
    assert "vtcode" not in A.CHAT_ONLY_BACKENDS


def test_the_console_does_not_offer_it():
    ts = (ROOT / "ui" / "src" / "lib" / "harness.ts").read_text()
    assert "id: 'vtcode'" not in ts
    assert "'vtcode'" not in ts          # the backend union and the instruction-file list too
    logo = (ROOT / "ui" / "src" / "components" / "HarnessLogo.tsx").read_text()
    assert "vtcode: '" not in logo
    # and the mark is gone from the tree rather than left to rot
    assert not (ROOT / "ui" / "public" / "logos" / "vtcode.png").exists()


def test_nothing_installs_it_by_default():
    sh = (ROOT / "docker" / "entrypoint.sh").read_text()
    default = re.search(r'HR_BACKENDS="\$\{HR_BACKENDS:-([^}]+)\}"', sh).group(1)
    assert "vtcode" not in default.split(",")
    # the installer stays for an operator who names it, with the reason beside it
    assert "install_vtcode()" in sh
    assert "NOT INSTALLED TODAY" in sh.split("install_vtcode()", 1)[0][-700:]


def test_no_measurement_dimension_claims_to_cover_it():
    mjs = (ROOT / "scripts" / "support-matrix" / "custom-harness.mjs").read_text()
    assert "vtcode" not in mjs.split("process.env.BASES", 1)[1].split("\n", 1)[0]
    plugins = (ROOT / "scripts" / "support-matrix" / "plugins" / "run-matrix.py").read_text()
    start = plugins.index("BASES = [")
    depth, end = 0, start
    for i, ch in enumerate(plugins[start:], start):
        depth += (ch == "[") - (ch == "]")
        if depth == 0:
            end = i + 1
            break
    assert '"vtcode"' not in plugins[start:end]


def test_the_runner_implementation_is_still_there_and_still_works():
    # Kept on purpose: the base runs, and what blocks it is upstream's headless MCP path. If
    # someone deletes this code, this test is where they are asked to mean it.
    from server import (ALL_VTCODE_TOOLS, _build_vtcode, _vtcode_eof,  # noqa: F401
                        _vtcode_to_claude)
    assert set(ALL_VTCODE_TOOLS) == {"exec_command", "write_stdin", "apply_patch", "search_tools",
                                     "record_decision"}
    assert (ROOT / "runner" / "tests" / "fixtures" / "batch4" / "vtcode-first-turn.ndjson").is_file()


def test_the_reason_is_written_down_where_someone_would_look():
    gw = (ROOT / "gateway" / "app.py").read_text()
    assert "vtcode (VT Code) is implemented and NOT OFFERED" in gw
    assert "session tool catalog is not available" in gw
    notes = (ROOT / "docs" / "support-matrix-notes.md").read_text()
    assert "spawned <ts>" in notes or "not one `initialize`" in notes
    assert "implemented, NOT offered" in notes
