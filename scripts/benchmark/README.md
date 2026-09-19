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

**3. It did the task, not a lookup.** The sandbox has internet and a filesystem. The first
pilot's third task fetched its own ground truth from the suite's public data, because the task id
was in a filename; two later turns recognised the suite from its field names in the prompt and
spent half an hour grepping the whole filesystem for its data and trying to `pip download` it.
So a pack names nothing — the workbook is `input.xlsx`, the answer `output.xlsx`, the prompt is
plain words with none of the suite's vocabulary — and a run whose tool calls made a request (a
web tool; `curl`, `wget`, `git clone`, `urllib.request`, `requests`, `httpx`, `aiohttp` in a
shell or script) or searched the machine for the task (a recursive `grep`, `rg` or `find`
rooted outside the workspace; a package fetched under a suite's name) is a finding, never a
score. Package installs are the sandbox's normal traffic and do not count; a URL merely spelled
in code (an xlsx's XML namespaces) does not either; the workspace is the agent's to search.
Disable the harness's web tools as well, on the harness or the connection: the rule catches what
the switch missed — and on a harness whose switch is an instruction to the model (cline, dsh)
it did, once in two hundred runs, fifteen minutes into a task the run did not finish. A
finding's session is left on the instance; its trace is the evidence.

**4. Tokens on one convention.** Fresh input, cached input and output are reported apart and
never summed: a cached read is the same prompt read again, not new input. The runner's contract
is `input_tokens` = fresh input (codex, gemini and, since #209, cline are netted to it); an
instance older than #209 reports cline's input gross, and a cline column from one belongs in the
run's notes, not in the table.

**5. No judge.** A suite whose grading needs a model's opinion is not a pack. Findings and
runner errors are listed under the table, not scored. A task the suite's own grader cannot
decide — its golden answer fails it — is left out of the row and counted in its notes, not held
against every harness: two of the first fifty were such, a sheet name with commas in it, which
the grader splits the answer range on, and a whole-column range it reads a row number from.

Every task has a time cap, `TASK_CAP_S` (900 s by default): a turn still running at the cap is
cancelled through the API and graded as it stands, a failure, not a finding — the cap is part of
the task. The row says how many runs hit it.

A turn the provider refused before the agent did anything (a 401/402/429/5xx, a dry balance, a
rate limit) measures the account, not the harness: it is recorded as this runner's error, re-run
on the next launch, and three in a row halt the run rather than fill the table with the same line.

## Running it

```
export BASE=http://127.0.0.1:3000/api/harness HR_API_KEY=... PROVIDER=deepseek EXPECT_CONNECTION=integration:deepseek
export PACK=spreadsheetbench PACK_ROOT=/data/spreadsheetbench_verified_400   # dataset.json + spreadsheet/ + the suite's evaluation.py, open_spreadsheet.py
HARNESSES=opencode=chrn_...,pi=chrn_...,cline=chrn_...,dsh=chrn_... MODELS=deepseek-v4.1-flash TASKS=first:50 \
  RESULTS=results-deepseek.json LOG=log-deepseek.txt WORKERS=2 python3 run.py
python3 render.py results-deepseek.json --note "self-hosted CE 0.18.4, 2026-09-19" > ../../docs/benchmark.md
```

`HARNESSES` is `label=id`: a custom harness with its web tools off is its `chrn_` id, a built-in
its backend name. `TASKS` is `first:N` or a comma list of ids; the default is the whole pack.
Resumable: a task already recorded for a harness × model × pack is skipped, a record carrying
`error` (this runner's own failure) is re-run. Sessions are deleted once graded, as the matrix
does, except a finding's, which stays for its trace to be read; `KEEP=1` leaves them all. An
instance whose console proxy cut a synchronous turn at five minutes (before #214) still ran it:
the runner finds the session it opened and grades from the record.

## The first column

Fifty tasks of SpreadsheetBench Verified (the first fifty of `dataset.json`), four harnesses with
their web tools off, `deepseek-v4.1-flash` through one custom OpenAI-format connection, on a
self-hosted CE: opencode, pi and dsh on 0.18.0 (2026-09-18), cline on 0.18.4 (2026-09-19) so that
its usage is on the convention. Two hundred runs, two workers; the generated table with its
findings is [docs/benchmark.md](../../docs/benchmark.md), the records
[docs/benchmark-results.json](../../docs/benchmark-results.json). Two tasks fail their own grader
and are left out; three lookups and one network fetch are findings, not scores.

| Harness | Resolved | Wall (sum) | Median wall | Tool calls | Calls failed | Fresh in | Cached in | Output |
|---|---|---|---|---|---|---|---|---|
| pi | 40/47 (85%) | 3605 s | 48 s | 526 | 89 (17%) | 484k | 7.53M | 546k |
| opencode | 37/48 (77%) | 6738 s | 98 s | 520 | 64 (12%) | 601k | 8.00M | 81k |
| dsh | 36/46 (78%) | 6506 s | 100 s | 721 | 113 (16%) | 761k | 12.32M | 752k |
| cline | 36/47 (77%) | 6882 s | 108 s | 736 | 121 (16%) | 1.20M | 19.74M | 1.21M |

Of the 48 gradable tasks, 31 are resolved by all four harnesses and 7 by none; the other 10 split,
and no harness resolves a task the others all fail. pi's seven failures are exactly the seven
nobody resolves, in half the wall time of the rest; the other three lose three or four more,
mostly different ones. The spread is in cost, on the same tasks and the same model: 2.5× in
fresh input and 2.6× in cached between pi and cline, 15× in output between opencode and cline.
Where a run fails it mostly fails outright: no workbook saved (15 runs), or the answer cells
wrong (24); the one run that hit the time cap is also the one that reached the network.

Rule 2 could not be checked on cline or dsh: through a custom OpenAI-format connection their
turn records carry no served model (opencode's do, pi's do). The instance's console proxy still
cut synchronous turns at five minutes (#214 is open); 20 runs went past it and were recovered
from the session list and graded from the record. An earlier cline column, on 0.18.0 before
#209, resolved 36 of 50 with its input reported gross (18.87M) and is set aside; the rerun above
is the one that counts.
