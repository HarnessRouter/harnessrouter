# Support matrix suite

Drives the console as one user and, for every harness and every model its menu offers, runs four
scenarios in one session: a first turn, a follow-up, a switch to another model of the harness (then
back), and an artifact (a file the task must produce, checked on the transcript's file cards).
Results are one JSON record per harness x model with the outcome, seconds and reason of each
scenario; `fill-connection.py` stamps each record with the connection its session actually ran on;
`render.py` turns the records into `docs/support-matrix.md`.

```
export BASE=https://your-instance HR_USER=harnessrouter HR_PASS=... PROVIDER=tokenrouter
HARNESSES=claude-code,codex,opencode,pi RESULTS=results-A.json LOG=log-A.txt node run.mjs
HARNESSES=hermes,dsh,qwen,cline       RESULTS=results-B.json LOG=log-B.txt node run.mjs
HR_API_KEY=... python3 fill-connection.py results-A.json results-B.json
python3 render.py <(jq -s add results-A.json results-B.json) > ../../docs/support-matrix.md
```

Needs `playwright` (`npm i playwright` next to `run.mjs`, then `npx playwright install chromium`).
Resumable: a pair already recorded is skipped, so a killed worker is relaunched and continues; a
pair whose record carries `error` (the runner's own failure) is re-run. To re-run failed pairs,
delete their records and relaunch. `PROVIDER` is a label for the column: run once per key you
want a column for, with that key wired in Integrations first. `MODELS` (comma list) limits a run
to some models, which is how a single failing pair is reproduced with tracing on. Set
`IGNORE_TLS=1` for an instance on a self-signed certificate.

Rows that fail must carry the reproduced provider error text; a verified list is never inherited
from another instance, since each reaches providers by its own path. Retest a bare `incomplete`
before excluding a model.
