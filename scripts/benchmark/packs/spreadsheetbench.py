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

# The suite's own framing (inference/prompt_format.py), addressed to an agent with a workspace
# instead of a code generator: the file is there, the answer is a file, and the answer goes only
# where the instruction says. VALUES rather than formulas keeps the grade about the task, not
# about whether the grading machine's spreadsheet engine evaluates a function the same way.
PROMPT = """You are working in a workspace that contains a spreadsheet file. Solve the spreadsheet manipulation task below by editing the workbook and saving the result to output_path inside the workspace. Python 3 is available; install packages with pip if you need them (openpyxl, pandas). Do not use the internet for anything other than pip: no web search, no fetching pages, no looking the task up. Write cell VALUES, not formulas, unless the instruction asks for formulas. Only modify cells inside answer_position on the answer sheet; leave everything else exactly as it is (other sheets, formatting, column widths). When the file is saved, reply with one line: done.

### instruction
{instruction}

### spreadsheet_path
{spreadsheet_path}

### instruction_type
{instruction_type}

### answer_position
{answer_sheet}!{answer_position}

### output_path
{output_path}
"""


def load(root: str) -> list[dict]:
    return json.load(open(os.path.join(root, "dataset.json"), encoding="utf-8"))


def stage(task: dict, root: str) -> dict:
    init = os.path.join(root, "spreadsheet", task["id"], f"1_{task['id']}_init.xlsx")
    with open(init, "rb") as f:
        data = f.read()
    prompt = PROMPT.format(instruction=task["instruction"], spreadsheet_path=INPUT,
                           instruction_type=task["instruction_type"], answer_sheet=task["answer_sheet"],
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


def grade(task: dict, root: str, produced: dict[str, str], workdir: str) -> dict:
    golden = os.path.join(root, "spreadsheet", task["id"], f"1_{task['id']}_golden.xlsx")
    path = produced.get(OUTPUT)
    if path is None:
        # The agent may have saved under another name; one workbook that is not the input is it.
        others = [p for n, p in produced.items() if n.endswith(".xlsx") and n != INPUT]
        path = others[0] if len(others) == 1 else None
    if path is None:
        return {"reward": 0.0, "resolved": False, "detail": "no workbook produced"}
    if root not in sys.path:
        sys.path.insert(0, root)
    from evaluation import compare_workbooks  # the suite's grader, from the suite's own tree
    recalculated = _recalculate(path, workdir)
    try:
        ok, detail = compare_workbooks(golden, path, task["instruction_type"], task["answer_position"])
    except Exception as e:  # noqa: BLE001 — a workbook the grader cannot open is a fail with its reason
        return {"reward": 0.0, "resolved": False, "detail": f"grader: {e!r}"[:300]}
    return {"reward": 1.0 if ok else 0.0, "resolved": bool(ok),
            "detail": (str(detail)[:300] if detail else "") + ("" if recalculated else " (no soffice: formulas unevaluated)")}
