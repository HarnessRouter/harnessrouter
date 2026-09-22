# Harness benchmark

How a row is measured, and the rules that decide it, are in [scripts/benchmark/README.md](../scripts/benchmark/README.md). One task is one session; the pack's own grader decides; every number is read from the turn record.

## Provider: deepseek, pack: spreadsheetbench

| Harness | Model | Tasks | Resolved | Reward | Wall (sum) | Median wall | Tool calls | Calls failed | Fresh in | Cached in | Output | Served by | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cline | deepseek-v4.1-flash | 47 | 36 (77%) | 0.77 | 6882 s | 108 s | 736 | 121 (16%) | 1.20M | 19.74M | 1.21M | deepseek | 2 runs the pack could not grade (the task fails its own grader), left out ; served model unreported on 50 of 50 runs (rule 2 unverifiable there) ; 1 run is a finding, not counted |
| dsh | deepseek-v4.1-flash | 46 | 36 (78%) | 0.78 | 6506 s | 100 s | 721 | 113 (16%) | 761k | 12.32M | 752k | deepseek | 2 runs the pack could not grade (the task fails its own grader), left out ; served model unreported on 50 of 50 runs (rule 2 unverifiable there) ; 2 runs are findings, not counted |
| opencode | deepseek-v4.1-flash | 48 | 39 (81%) | 0.81 | 5515 s | 75 s | 563 | 67 (12%) | 666k | 11.64M | 709k | deepseek | 2 runs the pack could not grade (the task fails its own grader), left out ; served model unreported on 1 of 50 runs (rule 2 unverifiable there) |
| pi | deepseek-v4.1-flash | 47 | 40 (85%) | 0.85 | 3605 s | 48 s | 526 | 89 (17%) | 484k | 7.53M | 546k | deepseek | 2 runs the pack could not grade (the task fails its own grader), left out ; served model unreported on 1 of 50 runs (rule 2 unverifiable there) ; 1 run is a finding, not counted |

Findings, runs served by another connection, as another model, or that reached the network or looked for the task outside the workspace: listed, not scored.

- cline x deepseek-v4.1-flash 290-1: reached the network: fetch_web_content; fetch_web_content
- dsh x deepseek-v4.1-flash 79-7: looked for the task outside the workspace: bash: grep -rl "Where the answer goes" /opt/harnessrouter /data/agent-tools 2>/dev/null | head -20
- dsh x deepseek-v4.1-flash 73-45: looked for the task outside the workspace: bash: ls /data/agent-tools/dsh-venv/lib/python3.12/site-packages/deepseek_harness_runtime/ 2>/dev/null; echo "---"; find
- pi x deepseek-v4.1-flash 73-45: looked for the task outside the workspace: bash: cd /data/workspaces/hsesscb99ac8612e64459b6aa2b6b071fe991 && find / -name '*.xlsx' 2>/dev/null | grep -v site-pack

## Run notes

- SpreadsheetBench Verified, the first fifty tasks of dataset.json; deepseek-v4.1-flash through one custom OpenAI-format connection, web tools disabled on every harness (a hard switch on opencode and pi, an instruction on cline and dsh); WORKERS=2, TASK_CAP_S=900.
- Self-hosted CE: pi and dsh on 0.18.0 (2026-09-18); cline on 0.18.4 (2026-09-19), a release with #209, so that its input tokens are fresh input; opencode on 0.18.4 with #216 applied (2026-09-19), so that its output tokens include its reasoning. Two earlier columns are set aside: cline on 0.18.0 (36 of 50, input reported gross at 18.87M) and opencode before #216 (37 of 48, output reported as 81k of visible text).
- The console proxy of both versions cut synchronous turns at five minutes (#214 open at the time); 20 runs went past it, were found in the session list and graded from the record.
- Tasks 130-9 and 283-32 fail their own grader (a sheet name with commas; a whole-column range) and are left out of every row.

