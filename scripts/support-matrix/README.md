# Support matrix suite

What a harness must prove, and the rules that decide a row, are in
[docs/harness-verification.md](../../docs/harness-verification.md). This file is how to run it.

Drives the console as one user and, for every harness and every model its menu offers, runs five
scenarios in one session: a first turn, a follow-up, a switch to another model of the harness (then
back), an artifact (a file the task must produce, checked on the transcript's file cards), and a
recycle (the session's sandbox is let go on purpose through the internal recycle route, then a
follow-up must recall the first message: the history survived the checkpoint round trip).
Results are one JSON record per harness x model with the outcome, seconds and reason of each
scenario; `fill-connection.py` stamps each record with the connection its session actually ran on;
`render.py` turns the records into `docs/support-matrix.md` (the Browser section at its end comes from docs/browser-column.json).

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
delete their records and relaunch. `PROVIDER` is a label for the table: run once per provider, with the model map pointing every
model that provider serves at its integration (one provider at a time, since a model has one
integration). `MODELS` (comma list) limits a run
to some models, which is how a single failing pair is reproduced with tracing on. Set
`IGNORE_TLS=1` for an instance on a self-signed certificate.

Rows that fail must carry the reproduced provider error text; a verified list is never inherited
from another instance, since each reaches providers by its own path. Retest a bare `incomplete`
before excluding a model.

## The family tour

One conversation, every model family in turn, on one deliverable (see "The family tour" in
docs/harness-verification.md). Through the console, like `run.mjs`:

```
export BASE=https://your-instance HR_USER=harnessrouter HR_PASS=...
HARNESS=cheetahclaws RESULTS=tour-cheetahclaws.json node family-tour.mjs
SID=hsess... HARNESS=cheetahclaws node family-tour.mjs     # retest a person's own conversation
```

`FAMILIES` (comma list of model ids, one per family) overrides the default list; a model the
instance does not serve is skipped and recorded as not offered. Exit 0 when every family passed.

## The plugin matrix

`plugins/run-matrix.py` proves the plugin path on every base, one base at a time: a harness is
created with ONE Agent Plugins package (`plugins/fixture/`: a manifest, a skill whose token the
model must repeat, a stdio MCP server that speaks the protocol by hand) and nothing on its
direct lists, one real task runs per column (skill, stdio MCP, a stdio tool that takes a list of
free-form objects, SSE MCP, streamable-HTTP MCP, the remote two against a public probe), and the
answer is judged on the probe token alone. The `rows` column's token comes from the tool itself:
it answers only when the rows it was handed carry their fields, and names what it received
otherwise, so an agent's own account of its call is never the judge.

    python3 plugins/run-matrix.py --base-url https://your-instance/api/harness --api-key "$KEY" \
        --bases aider --out plugin-results.json

Kept in the repository since 2026-09-18 after the copy in a scratch folder was emptied mid-review.

## The browser column

`plugs/browser.py` runs the browser plugin on every base but System One, through the API, on one
task in plain words (open example.com, follow its link, report where you landed), and judges each
base on the trace: the browser navigated and clicked, the answer names the page it reached, the
browser session was stopped and billed. A failed base is retested once. The prompt names no tool;
the harness's Browser section in the agent's instructions file is what the agent goes on.

    python3 plugs/browser.py --base-url https://<instance>/api/harness --api-key "$KEY" \
        --out browser.json --md browser.md            # every ready base except systemone
    python3 plugs/browser.py ... --bases codex,pi     # a few bases
    python3 plugs/browser.py ... --model gpt-5.4      # one model on every base

The table (`--md`) is the Browser section of docs/support-matrix.md; the run's findings go to
docs/support-matrix-notes.md like every other column's.

## Environments column

`python3 environments/column.py --base-url ... --api-key ... --environment henv_...` runs three tasks per base (pip, npm, apt) on one built environment and judges each by the trace (no install), the answer (the package's path under the environment) and the session record. See docs/support-matrix-notes.md.
