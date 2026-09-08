# Verifying a harness

A harness that answers is not a harness that works. It has to run on the connection you chose, on
the model you asked for, keep a conversation across a model switch and a sandbox recycle, and show
the reader what it actually produced. This page says what a harness must prove, how each claim is
measured, and where the rule lives in code, so a change can be checked rather than believed.

The tool is [`scripts/support-matrix`](../scripts/support-matrix/README.md); that README says how to
run it. This page is about what it decides and why.

## What is measured

For every harness and every model its menu offers, one session runs five scenarios:

| Scenario | What it proves |
|---|---|
| First turn | the harness starts, on the model asked for, and answers |
| Follow-up | the session continues rather than starting again |
| Switch | a mid-session change of model runs on the new one and keeps the thread, then switches back |
| Artifact | a file the task must produce exists in the turn record and is shown to the reader |
| Recycle | the sandbox is let go on purpose, then a follow-up still recalls the first message |

## The rules that decide a row

A scenario that "completed" is not a pass on its own. Four rules turn a run into a verdict, and each
is enforced in code rather than by eye.

**1. It ran where you said.** A turn served by a connection other than the one under test is a
finding, never a pass. Set `EXPECT_CONNECTION` for the run; every turn record's own connection stamp
is compared against it, so a pair served by two connections is visible.
Enforced in `scripts/support-matrix/run.mjs` and reported by `render.py`.

**2. It ran what you asked.** A served model other than the id asked for is a substitution and a
finding. The one exception is a provider's own name for the same model: an aggregator's vendor
prefix (`anthropic/claude-fable-5`) or a provider's dated or versioned suffix
(`claude-haiku-4-5-20251001`) is the same model, noted in the row and counted. A different family,
number or tier under any prefix (`google/gemini-3-flash-preview` for `gemini-3.8-flash`,
`gemini-2.5-flash-lite` for `gemini-2.5-flash`) is another model, and stays a finding.
Enforced in `scripts/support-matrix/samemodel.py`, pinned by `test_samemodel.py`.

**3. What the reader sees is what was stored.** The artifact row requires the rendered file cards to
BE the turn's stored files: same names, same count. Asking only whether some card carried the
expected name let a file rendered twice pass as a produced artifact for months.
Enforced in `scripts/support-matrix/run.mjs`.

**4. The catalog does not promise what the harness cannot do.** A model a provider serves only on
the Responses API is not offered on a harness that speaks chat/completions, because listing it there
is a picker row that fails on send.
Enforced by `gateway/tests/test_catalog_chat_only_backends.py`.

## The custom-harness dimension

The five scenarios measure routing. They say nothing about the configuration a person actually
builds, which is where this product's own promise lives: your own skill, carrying your own script,
and control over the tools the runtime brought with it. A harness that answers on every model and
ignores the skill you wrote is not working.

[`scripts/support-matrix/custom-harness.mjs`](../scripts/support-matrix/custom-harness.mjs) creates
a harness per base, carrying a skill bundle whose `SKILL.md` tells the agent to run a script that
ships beside it, and with one inherited tool switched off. It runs one turn, then deletes the
harness. One turn per base, not per model: this measures what the harness carries, not where the
turn routed.

A row passes only if all five hold, each read from what the server stored:

| Claim | How it is proven |
|---|---|
| The skill was stored on the harness | it comes back on a read of the harness |
| The tool policy was stored | the disabled tool comes back too |
| The bundle reached the agent | the answer carries a token that exists ONLY inside the script |
| The script actually ran | the file the script writes is among the turn's produced files |
| The tool policy took effect | no disabled tool appears among the turn's tool calls |
| The MCP server was stored, and called | it comes back on a read, and a second turn's tool calls name it. A call is named by its tool name, except omp, which dispatches MCP as a `write` to `xd://mcp__<server>_<tool>`: there the call's arguments name it |

The token is generated per run and never appears in `SKILL.md` or the prompt, so an answer carrying
it came from the bundle rather than from the model's imagination, and the written file separates a
script that ran from one that was merely read.

A harness's other kind of tool is an MCP server, and the same harness declares one. A self-contained
instance hosts only the database and media servers, one needing a database and the other costing
real money per call, so this half points at a public MCP server that needs no key and no account,
and a second turn in the same session must call it.

It is judged on the CALL, not on the answer: a public server's prose is not ours to pin, but a tool
call is a fact in the turn record. Backends name those calls differently, some recording the server
and tool (`deepwiki.read_wiki_structure`) and some only that an MCP tool was used (`mcp`), and since
the harness declares exactly one server either shape identifies it.

The third party is a dependency, so it is treated as one. The server is probed once before the run;
if it is unreachable the MCP half is skipped and the row says so, because a public service being
down is not evidence about this product. `MCP_URL=off` skips it outright, for an instance with no
egress, and any other URL overrides the default.

## Rules for the run itself

- **One provider at a time, and isolation means deletion.** A column measures what a provider can
  actually drive, so the org holds that provider's integration and nothing else while it runs. A
  model map pointed at an integration is not isolation: another integration can still serve the turn.
- **A run owns the instance.** Do not deploy the console or a new image while a column is running.
  The live-turn check passes in the gap between a worker's turns, so "no turns running" is not
  "nothing is running", and a deploy in that gap kills a worker's session and costs the column.
- **Never inherit a verified list from another instance.** Each instance reaches providers by its own
  path and its own keys.
- **Retest a bare `incomplete` before excluding a model**, and record the reproduced provider error
  text on a row that fails.
- **A finding is never counted as a pass.** The tables report findings separately and leave those
  pairs out of the scenario counts.

## Adding a harness

A new harness is registered in five places, and is not finished until it has a measured column:

1. `runner/server.py`, `BACKENDS`: its providers, default model, and the normaliser that turns its
   output into the shape the gateway stores.
2. `gateway/app.py`, `_MODEL_CATALOG`: the ids it offers, honestly (see rule 4), and
   `_INTEGRATION_WIRING`: which provider types can drive it.
3. `ui/src/lib/harness.ts`, `OOB`: the built-in harness the console lists, with its mark and models.
4. `docker/entrypoint.sh`, how the CLI is installed on first start, under its own licence, pinned.
5. `docs/support-matrix.md`, a column per provider, produced by the suite, with its notes in
   `docs/support-matrix-notes.md`.

Its models must be honest: every id the picker offers must run as itself, and a turn that ran on a
different model fails rather than quietly succeeding.

## Console changes

Any change to a console surface must survive narrow widths. `scripts/responsive-audit.mjs` sweeps
every surface at every width that matters and flags content wider than the box that holds it; its
header records the last run and its result.
