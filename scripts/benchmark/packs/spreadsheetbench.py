"""SpreadsheetBench Verified (400) — RUCKBReasoning/SpreadsheetBench, NeurIPS 2024 D&B spotlight.

Real spreadsheet-manipulation questions from Excel forums; each instruction carries an input
workbook, a golden workbook and the cell range the answer must land in, and the suite's
`evaluation.py` compares that range cell by cell (OJ-style). Sheet-level rows must match the whole
range; cell-level rows the named cells.

`root` is the extracted `spreadsheetbench_verified_400/` directory with the suite's
`evaluation.py` and `open_spreadsheet.py` copied beside `dataset.json` — the grader is the suite's,
imported from there, never a copy in this repository. Grading needs LibreOffice (`soffice`) on the
grading machine, not in the sandbox: a workbook the agent saved with formulas has no cached values
until a spreadsheet engine opens it, and openpyxl reads cached values only.
"""
import json
import os
import shutil
import subprocess
import sys

NAME = "spreadsheetbench"

INPUT = "input.xlsx"
OUTPUT = "output.xlsx"

# The suite's framing (inference/prompt_format.py) in plain words, addressed to an agent with a
# workspace: the file is there, the answer is a file, and the answer goes only where the task
# says. None of the suite's own field names appear: a turn that saw "instruction_type:
# Sheet-Level Manipulation" recognised the suite and spent twenty minutes grepping the whole
# filesystem for its data and trying to `pip download` it (measured 2026-09-18) — the vocabulary
# was the search key. VALUES rather than formulas keeps the grade about the task, not about
# whether the grading machine's spreadsheet engine evaluates a function the same way.
PROMPT = """You are working in a workspace that contains a spreadsheet, {spreadsheet_path}. Do the task below by editing that workbook and saving the result as {output_path} in the workspace.

The task: {instruction}

Where the answer goes: sheet "{answer_sheet}", cells {answer_position}. {scope}

Python 3 is available; install packages with pip if you need them (openpyxl, pandas). Do not use the internet, and do not look for this task or its answer anywhere else on this machine: everything you need is in the workspace. Write cell values, not formulas, unless the task asks for formulas. Leave everything outside the answer cells exactly as it is (other sheets, formatting, column widths). When {output_path} is saved, reply with one line: done.
"""
SCOPE = {"Cell-Level Manipulation": "Only those cells change.",
         "Sheet-Level Manipulation": "Everything the task asks for lands inside that range, and nothing outside it changes."}


def load(root: str) -> list[dict]:
    return json.load(open(os.path.join(root, "dataset.json"), encoding="utf-8"))


def stage(task: dict, root: str) -> dict:
    init = os.path.join(root, "spreadsheet", task["id"], f"1_{task['id']}_init.xlsx")
    with open(init, "rb") as f:
        data = f.read()
    prompt = PROMPT.format(instruction=task["instruction"].strip(), spreadsheet_path=INPUT,
                           scope=SCOPE.get(task["instruction_type"], ""), answer_sheet=task["answer_sheet"],
                           answer_position=task["answer_position"], output_path=OUTPUT)
    return {"prompt": prompt, "files": [(INPUT, data)]}


def _recalculate(path: str, workdir: str) -> bool:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    tmp = os.path.join(workdir, "_recalc")
    os.makedirs(tmp, exist_ok=True)
    subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", tmp, path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    converted = os.path.join(tmp, os.path.basename(path))
    if not os.path.exists(converted):
        return False
    shutil.move(converted, path)
    return True


_GRADABLE: dict[str, str] = {}


def _ungradable(task: dict, golden: str, compare_workbooks) -> str:
    """Why the suite's grader cannot decide this task, or "": the golden workbook is graded
    against itself first, and a task whose own answer does not pass is nobody's failure. Two of
    the first fifty were such (measured 2026-09-18): a sheet name with commas in it, which the
    grader splits the answer range on, and a whole-column range, A:G, it reads a row number from.
    Every harness "failed" both until this told them apart."""
    if task["id"] not in _GRADABLE:
        try:
            ok, detail = compare_workbooks(golden, golden, task["instruction_type"], task["answer_position"])
            _GRADABLE[task["id"]] = "" if ok else f"the golden workbook fails its own grader: {detail}"
        except Exception as e:  # noqa: BLE001
            _GRADABLE[task["id"]] = f"the grader raises on the golden workbook: {e!r}"
    return _GRADABLE[task["id"]]


def grade(task: dict, root: str, produced: dict[str, str], workdir: str) -> dict:
    golden = os.path.join(root, "spreadsheet", task["id"], f"1_{task['id']}_golden.xlsx")
    if root not in sys.path:
        sys.path.insert(0, root)
    from evaluation import compare_workbooks  # the suite's grader, from the suite's own tree
    why = _ungradable(task, golden, compare_workbooks)
    if why:
        return {"reward": None, "resolved": None, "detail": ("ungradable: " + why)[:300]}
    path = produced.get(OUTPUT)
    if path is None:
        # The agent may have saved under another name; one workbook that is not the input is it.
        others = [p for n, p in produced.items() if n.endswith(".xlsx") and n != INPUT]
        path = others[0] if len(others) == 1 else None
    if path is None:
        return {"reward": 0.0, "resolved": False, "detail": "no workbook produced"}
    recalculated = _recalculate(path, workdir)
    try:
        ok, detail = compare_workbooks(golden, path, task["instruction_type"], task["answer_position"])
    except Exception as e:  # noqa: BLE001 — a workbook the grader cannot open is a fail with its reason
        return {"reward": 0.0, "resolved": False, "detail": f"grader: {e!r}"[:300]}
    return {"reward": 1.0 if ok else 0.0, "resolved": bool(ok),
            "detail": (str(detail)[:300] if detail else "") + ("" if recalculated else " (no soffice: formulas unevaluated)")}
