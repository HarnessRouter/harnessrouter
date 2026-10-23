"""The settings page must name the file the runner actually writes.

Registration point 14 of docs/harness-verification.md: "the instruction-file label, which must agree
with `_agent_doc_path` or the settings page names a file the runner does not write". Nothing checked
it, and it had drifted — the page labelled the box "AGENTS.md" for qwen and gemini while the runner
wrote QWEN.md and GEMINI.md, so a person editing those instructions was editing a box named for a
file their agent never read. (The text still reached the agent; the NAME on the box was a lie, which
on this repo's own terms is a defect rather than a nit.)

The console now derives the label from one map, `instructionFileLabel` in ui/src/lib/harness.ts,
and this test holds that map to `_agent_doc_path` for every base the console lists.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "runner"))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402
from server import _agent_doc_path  # noqa: E402

UI = pathlib.Path(__file__).resolve().parents[2] / "ui" / "src"
HARNESS_TS = UI / "lib" / "harness.ts"
# The settings page names the box through settingsModel.mdName, which is instructionFileLabel; the page
# itself (SetupSettings.tsx) carries no file name of its own.
SETTINGS = [UI / "components" / "hrui" / "setup" / "settingsModel.ts", UI / "components" / "hrui" / "setup" / "SetupSettings.tsx"]

# The bases that read no workspace file: systemone's instructions travel in the job, qoder's with the
# hosted session it drives, so there is no file to name and the page says so instead of inventing one.
NO_FILE = {"systemone", "qoder"}


def _label_map() -> dict:
    src = HARNESS_TS.read_text()
    special = dict(re.findall(r"^\s*([A-Za-z0-9_-]+):\s*'([^']+)',",
                              re.search(r"INSTRUCTION_FILE: Record<string, string> = \{(.*?)\n\};",
                                        src, re.S).group(1), re.M))
    agents = re.findall(r"'([a-z0-9-]+)'",
                        re.search(r"const AGENTS_MD_BASES = \[(.*?)\n\];", src, re.S).group(1))
    out = {}
    for base in A._BASE_CATALOG:
        out[base] = special.get(base) or ("AGENTS.md" if base in agents else "CLAUDE.md")
    return out


def test_every_label_is_the_file_the_runner_writes():
    for base, label in _label_map().items():
        if base in NO_FILE:
            assert label == "Instructions", base
            continue
        backend = A._BASE_CATALOG[base]["backend"]
        want = _agent_doc_path("/w", backend).name
        assert label == want, (
            f"{base}: the settings page calls the box {label!r} and the runner writes {want!r}")


def test_the_page_does_not_carry_a_second_copy_of_the_list():
    # Two lists meant two places to edit and only one of them got edited, which is how this drifted.
    model, page = (p.read_text() for p in SETTINGS)
    assert "instructionFileLabel(" in model
    assert "mdName(" in page
    for src in (model, page):
        assert "AGENTS.md" not in src and "CLAUDE.md" not in src


def test_the_bases_this_batch_added_are_covered():
    labels = _label_map()
    for base in ("mimo", "jcode", "opensquilla", "nanobot"):
        assert labels[base] == "AGENTS.md", base


def test_the_two_that_were_mislabelled_now_say_their_own_name():
    labels = _label_map()
    assert labels["qwen"] == "QWEN.md"
    assert labels["gemini"] == "GEMINI.md"
