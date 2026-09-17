"""kimi's "hard" tool enforcement is only real while the catalog and the path table agree.

kimi matches `exclude_tools` on tool PATHS (`kimi_cli.tools.shell:Shell`), not on the tool NAMES the
model sees. Measured on 1.50.0: excluding the bare name "Shell" is a SILENT no-op — the tool stays
in the array sent to the provider — while excluding the path removes it. So a catalog id with no
row in runner/server.py's _KIMI_TOOL_PATHS would be offered as a toggle in the console, reported as
off, and change nothing: the exact overstatement UHP §4.3 forbids and the reason this backend is
allowed to claim `tool_enforcement: "hard"` at all.

This test is named in both comments that make the claim (the catalog entry and the path table), so
that a drift on either side fails here rather than on a live turn.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import _KIMI_TOOL_PATHS  # noqa: E402


def test_every_advertised_kimi_tool_can_actually_be_withheld():
    advertised = {tid for tid, _label in A._BASE_CATALOG["kimi"]["tools"]}
    assert advertised == set(_KIMI_TOOL_PATHS), (
        "catalog ids and _KIMI_TOOL_PATHS keys must match exactly; "
        f"only in catalog: {advertised - set(_KIMI_TOOL_PATHS)}, "
        f"only in table: {set(_KIMI_TOOL_PATHS) - advertised}")


def test_kimi_claims_hard_enforcement_and_earns_it():
    assert A._BASE_CATALOG["kimi"]["tool_enforcement"] == "hard"
    assert A._BASE_CATALOG["kimi"]["backend"] == "kimi"


def test_tools_gated_behind_a_key_or_a_vision_model_are_not_offered():
    """SearchWeb and ReadMediaFile are in kimi's shipped default agent but raise SkipThisTool
    unless a Moonshot search key / a vision-capable model is configured, so neither is ever
    constructed here. Listing one would be a picker row for a tool that does not exist."""
    advertised = {tid for tid, _ in A._BASE_CATALOG["kimi"]["tools"]}
    assert "SearchWeb" not in advertised
    assert "ReadMediaFile" not in advertised


def test_kimi_is_chat_completions_only():
    """Its provider type is openai_legacy, so a Responses-API-only id would fail on send."""
    assert "kimi" in A.CHAT_ONLY_BACKENDS
