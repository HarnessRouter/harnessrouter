# Benchmark suite

The support matrix proves a harness *works*. This suite measures how well a harness × model
configuration does the same work: public task suites with deterministic grading, run through the
instance's own API, one task per session, every number read from the turn record the runner
already stores. The rules below decide a row; `test_run.py` pins them.

## What is measured

For every harness and model named, each task of a pack runs in a fresh session: the pack stages
the task's files and instruction as the first turn, the turn runs, the files it produced come back
from the session, and the suite's own grader decides. A record carries the verdict (`resolved`,
`reward` in [0, 1], the grader's reason), wall time, tool calls and tool names, how many of those
calls failed (the CLI flagged the result, or a shell exited non-zero or raised — read from the
stored trace), fresh / cached / output tokens, the connection and the served model the turn record
stamps, and the files. The table sums wall time and tool calls per row and gives the failed calls
as a rate.

Packs live in `packs/`, one module each, and never re-implement a grader: the suite's data and
grader stay outside this repository, at `PACK_ROOT`, under the suite's own licence.

| Pack | Suite | Grading | Needs on the grading machine |
|---|---|---|---|
| `spreadsheetbench` | [SpreadsheetBench Verified](https://github.com/RUCKBReasoning/SpreadsheetBench) (400 real spreadsheet-manipulation questions, NeurIPS 2024 D&B) | the suite's `evaluation.py`, cell by cell over the answer range | `openpyxl`; LibreOffice (`soffice`) so a workbook saved with formulas has values to compare |

## The rules that decide a row

**1. It ran where you said.** Set `EXPECT_CONNECTION` to the connection under test; a run whose turn
record names another connection is a finding, never a score. The matrix's rule 1, unchanged.

**2. It ran what you asked.** A served model other than the id asked for is a finding, judged by
`samemodel.py` exactly as the matrix judges it: an aggregator's prefix or a provider's version
suffix is the same model, another family, number or tier is not. A harness whose turn record
carries no served model is scored, and the row says on how many runs rule 2 could not be checked.

**3. It did the task, not a lookup.** The sandbox has internet. The first pilot's third task
fetched its own ground truth from the suite's public data, because the task id was in a filename.
So a pack names nothing — the workbook is `input.xlsx`, the answer `output.xlsx`, the prompt
carries no id — and a run whose tool calls made a request (a web tool; `curl`, `wget`, `git clone`,
`urllib.request`, `requests`, `httpx`, `aiohttp` in a shell or script) is a finding, never a
score. Package installs are the sandbox's normal traffic and do not count; a URL merely spelled
in code (an xlsx's XML namespaces) does not either. Disable the harness's web tools as well, on
the harness or the connection: the rule catches what the switch missed.

**4. Tokens on one convention.** Fresh input, cached input and output are reported apart and
never summed: a cached read is the same prompt read again, not new input. The runner's contract
is `input_tokens` = fresh input (codex, gemini and, since #209, cline are netted to it); an
instance older than #209 reports cline's input gross, and its rows say so in their notes.

**5. No judge.** A suite whose grading needs a model's opinion is not a pack. Findings and
runner errors are listed under the table, not scored.

## Running it

```
export BASE=http://127.0.0.1:3000/api/harness HR_API_KEY=... PROVIDER=deepseek EXPECT_CONNECTION=integration:deepseek
export PACK=spreadsheetbench PACK_ROOT=/data/spreadsheetbench_verified_400   # dataset.json + spreadsheet/ + the suite's evaluation.py, open_spreadsheet.py
HARNESSES=opencode=chrn_...,pi=chrn_...,cline=chrn_...,dsh=chrn_... MODELS=deepseek-v4.1-flash TASKS=first:50 \
  RESULTS=results-deepseek.json LOG=log-deepseek.txt WORKERS=2 python3 run.py
python3 render.py results-deepseek.json > ../../docs/benchmark.md
```

`HARNESSES` is `label=id`: a custom harness with its web tools off is its `chrn_` id, a built-in
its backend name. `TASKS` is `first:N` or a comma list of ids; the default is the whole pack.
Resumable: a task already recorded for a harness × model × pack is skipped, a record carrying
`error` (this runner's own failure) is re-run. Sessions are deleted once graded, as the matrix
does; `KEEP=1` leaves them. An instance whose console proxy cut a synchronous turn at five minutes
(before #214) still ran it: the runner finds the session it opened and grades from the record.

## The first slice

Five tasks of SpreadsheetBench Verified, four harnesses with web tools off, `deepseek-v4.1-flash`
through one custom connection, self-hosted CE 0.18.x, 2026-09-17. Twenty runs, under one US
dollar of inference. The instance predated #209, so cline's row is netted by hand from the
per-request records; every other row is as the turn record stored it.

| Harness | Resolved | Wall (sum) | Tool calls | Fresh in | Cached in | Output |
|---|---|---|---|---|---|---|
| opencode | 4/5 | 563 s | 62 | 73k | 1.40M | 11k |
| pi | 4/5 | 767 s | 80 | 74k | 2.33M | 143k |
| dsh | 4/5 | 874 s | 95 | 89k | 2.37M | 143k |
| cline | 4/5 | 998 s | 100 | 152k | 2.27M | 156k |

All four resolve the same four tasks and fail the same one, so on this slice the harness shows in
efficiency, not correctness: 1.8× in wall time, 1.6× in prompt volume, 14× in output tokens.
Two things this slice found are now fixed upstream: cline's cached reads were counted as input
(#209), and the console proxy cut synchronous turns at five minutes (#214). Two remain open:
through a custom OpenAI-format connection, cline's and dsh's turn records carry no served model,
so rule 2 cannot be checked on them; and one task in the first, un-anonymised run was answered by
fetching the suite's ground truth, which is why rule 3 exists.
