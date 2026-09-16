"""Everything the runner imports at module level must be something the image installs.

`mcp_bridge.py` imported the MCP SDK and no requirements file pinned it. The image installs those
files and nothing else into the one environment gateway and runner share, so the bridge would die
the moment a client tried to start it, and the only symptom would be an MCP server that never
connected. The bridge landed after v0.17.2, so the next release would have been the first to carry
it; verified against a real image built from this branch's requirements before and after.

The check is derived rather than typed: every module-level third-party import in every runner
module has to be pinned in `runner/requirements.txt` or `gateway/requirements.txt`. Module level is
the line that matters: that import decides whether the file loads at all. An import inside a
function is the code saying "only on this path", which is how the backend runtimes that install
themselves (the DeepSeek harness in its own environment) are reached, and those are not pinned
here on purpose.
"""
import ast
import pathlib
import re
import sys

RUNNER = pathlib.Path(__file__).resolve().parents[1]
GATEWAY = RUNNER.parent / "gateway"
# Module name -> the distribution that provides it, where the two differ.
DISTRIBUTION = {"yaml": "pyyaml"}


def _module_level_imports(path: pathlib.Path) -> set[str]:
    mods: set[str] = set()
    for node in ast.parse(path.read_text()).body:      # body, not walk: top level only
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    local = {p.stem for p in RUNNER.glob("*.py")}
    return {m for m in mods
            if m not in sys.stdlib_module_names and m not in local and not m.startswith("_")}


def _pinned() -> set[str]:
    out: set[str] = set()
    for f in (RUNNER / "requirements.txt", GATEWAY / "requirements.txt"):
        for line in f.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                out.add(re.split(r"[=<>\[]", line, 1)[0].strip().lower())
    return out


def test_every_module_level_runner_import_is_pinned():
    pinned, missing = _pinned(), {}
    for f in sorted(RUNNER.glob("*.py")):
        for mod in _module_level_imports(f):
            if DISTRIBUTION.get(mod, mod).lower() not in pinned:
                missing.setdefault(f.name, set()).add(mod)
    assert not missing, (
        f"these runner modules import something no requirements file pins: {missing}. "
        "The image installs those files and nothing else, so the import fails at run time.")


def test_the_bridge_names_the_sdk_it_needs():
    """The specific regression: the bridge's SDK, pinned to the version the hosted image bakes."""
    assert "mcp" in _module_level_imports(RUNNER / "mcp_bridge.py")
    assert re.search(r"^mcp==", (RUNNER / "requirements.txt").read_text(), re.M), \
        "mcp_bridge.py cannot start without the MCP SDK"
