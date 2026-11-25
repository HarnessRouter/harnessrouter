"""Hermes switches toolsets, not tools (runner/server.py _HERMES_TOOLSETS_OFF). A toolset that holds one switchable tool is
withheld whenever that tool is off, so the tool is labelled hard: Settings never says "This agent can't switch it off" of
a tool the agent is not offered once it is off. A tool that shares its toolset is withheld only with the others, so it
stays "instruction". Web search can also arrive through hermes's browser toolset, so it is asked as well and stays
"instruction". The runner's table is read from its source, never imported."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gw  # noqa: E402  (environment: conftest.py)

RUNNER = Path(__file__).resolve().parents[2] / "runner" / "server.py"


def _toolsets_off() -> list[tuple[str, tuple[str, ...]]]:
    for node in ast.parse(RUNNER.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_HERMES_TOOLSETS_OFF" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("_HERMES_TOOLSETS_OFF not found in runner/server.py")


def _labels() -> dict[str, str]:
    b = gw._BASE_CATALOG["hermes"]
    return {n: gw._tool_enforcement(b, n) for n, _lbl in b["tools"]}


def test_a_tool_alone_in_its_toolset_is_labelled_hard_and_the_rest_are_asked():
    alone = {tools[0] for _ts, tools in _toolsets_off() if len(tools) == 1} - {"web_search"}
    assert alone == {"terminal"}, alone
    labels = _labels()
    assert labels["terminal"] == "hard"
    for n in ("read_file", "write_file", "patch", "search_files", "web_search", "web_extract"):
        assert labels[n] == "instruction", (n, labels[n])


def test_the_bases_document_says_so(monkeypatch):
    from fastapi.testclient import TestClient

    async def who(request):
        return {"org": "org.labels", "member": "me@local"}
    monkeypatch.setattr(gw, "_principal", who)
    rows = TestClient(gw.app).get("/v1/bases").json()
    rows = rows.get("data") or rows.get("bases") or rows
    hermes = next(x for x in rows if x.get("id") == "hermes")
    tools = {t["name"]: t["enforcement"] for t in hermes["tools"]}
    assert tools["terminal"] == "hard" and tools["read_file"] == "instruction" and tools["web_search"] == "instruction"
