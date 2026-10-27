"""A base's default model is one it offers, and the three places that name it agree.

The default is what a task runs when nobody picks a model: the gateway's catalog says it, the runner
falls back to its own copy (<BACKEND>_DEFAULT_MODEL), and the console preselects a third
(ui/src/lib/harness.ts). gpt-6.1-sol replaced gpt-5.4 as the default (2026-10-22) wherever it ran
every scenario on the common connections; a copy left behind would run the old model with nothing saying so.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as gw  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _runner_defaults() -> dict:
    src = (_ROOT / "runner" / "server.py").read_text()
    return {m.group(1).lower(): m.group(2) for m in re.finditer(
        r'^([A-Z]+)_DEFAULT_MODEL = os\.environ\.get\("\1_DEFAULT_MODEL", "([^"]+)"\)', src, re.M)}


def _console_defaults() -> dict:
    src = (_ROOT / "ui" / "src" / "lib" / "harness.ts").read_text()
    out = {}
    for block in re.split(r"\n  \{", src):
        i, d = re.search(r"id: '([a-z0-9-]+)'", block), re.search(r"defaultModel: '([^']+)'", block)
        if i and d:
            out[{"claude-code": "claude"}.get(i.group(1), i.group(1))] = d.group(1)
    return out


def test_every_default_is_offered_on_its_base():
    for backend, entry in gw._MODEL_CATALOG.items():
        models = entry.get("models") or []
        if not models:
            continue          # a base that takes the list of another, filled below its entry
        gone = gw._NOT_OFFERED.get(backend, frozenset())
        assert entry["default"] in models and entry["default"] not in gone, backend


def test_the_runner_falls_back_to_the_catalogs_default():
    runner = _runner_defaults()
    # systemone's model id reaches its provider verbatim (`typesafe/jev-1.13`, runner/server.py),
    # where the catalog names the alias both of its providers serve.
    checked = [b for b in gw._MODEL_CATALOG if b in runner and b != "systemone"]
    assert len(checked) >= 20
    for backend in checked:
        assert runner[backend] == gw._MODEL_CATALOG[backend]["default"], backend


def test_the_console_preselects_the_catalogs_default():
    console = _console_defaults()
    checked = [b for b in gw._MODEL_CATALOG if b in console]
    assert len(checked) >= 20
    for backend in checked:
        assert console[backend] == gw._MODEL_CATALOG[backend]["default"], backend


def test_gpt_6_1_sol_is_the_default_where_gpt_5_4_was_and_it_runs():
    sol = sorted(b for b, e in gw._MODEL_CATALOG.items() if e["default"] == "gpt-6.1-sol")
    # where it ran all five matrix scenarios through OpenAI, Azure and TokenRouter (2026-10-22; dcode 2026-10-27)
    assert sol == sorted(["codex", "hermes", "pi", "opencode", "kilo", "omp", "goose", "aider", "agentzero", "mimo",
                          "dcode"])
    # refused it on a common connection (chat/completions with function tools, at any effort), or not offered it
    for b in ("cline", "cheetahclaws", "jcode", "nanobot", "zeroclaw", "openhands", "opensquilla",
              "vibe", "docker-agent", "fast-agent"):
        assert gw._MODEL_CATALOG[b]["default"] == "gpt-5.4", b
