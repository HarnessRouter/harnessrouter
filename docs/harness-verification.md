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

Where the served model comes from is the CLI's choice, and some report none: goose reports one only
on a provider format it never uses, and cline and qwen report none either. That used to make this
rule unenforceable for those three — half the bar, on three harnesses. It no longer is. Every turn
on those backends rides the loopback relay and the provider's own answer names `model`, so the
relay reads it off the bytes as they pass and the runner stamps it on a result the CLI left
unlabelled (`_served_model_in` and `_relay_served_model` in `runner/server.py`, pinned by
`runner/tests/test_relay_served_model.py`); a CLI that reports its own keeps it. So the question to
ask of a new harness is not "does this CLI report a served model" but "does it ride the relay" — if
it does, rule 2 applies whether the CLI cooperates or not.

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

A new harness is registered in the places below, and is not finished until it has a measured
column. Every one of them fails SILENTLY when missed — the harness still builds, still answers, and
loses one capability without saying so. The single exception is the console's backend union type,
which fails the type-check, and that is the only one a compiler will find for you.

**The runner** — `runner/server.py`:

1. `BACKENDS`: its providers, default model, and the normaliser that turns its output into the
   shape the gateway stores.
2. The `turn()` dispatch branch that builds its argv.
3. `_write_skills`: where a skill bundle has to land for THAT CLI's loader to find it. Prefer a
   path under `.harness/`: the workspace root is collected as produced files, so a skills folder
   written there is handed back to the user as a deliverable on every turn.
4. `_agent_doc_path`: `AGENTS.md` or `CLAUDE.md` — whichever the CLI actually reads. Getting it
   wrong writes the file and the agent never sees it, so the workspace contract never arrives.
5. `_resume_lost`: how a turn that could not continue the conversation says so, if this CLI can
   lose one. Silence here reads as a completed turn that has forgotten everything.
6. **How this CLI reports a provider failure — check, do not assume it has an error event.**
   Several narrate it as ordinary assistant text and then end the run normally: claude injects
   `API Error: …`, goose `Ran into this error: …`. Read as written, the turn completes with the
   failure as its answer, the run counts as a pass, and the next turn in that session answers from
   a history carrying the error prose. The normaliser must recognise the CLI's prefix, fail the
   turn, and keep the sentence as the reason — `_CLAUDE_ERR_RE` and `_GOOSE_ERR_RE`. Pin the
   prefix with a test, and take it from the pinned binary (`strings`), not from the docs.
7. `CHECKPOINT_EXCLUDE` and `_git_ensure`'s ignore list: any file the CLI writes that can hold a
   credential.

**The gateway** — `gateway/app.py`:

8. `_MODEL_CATALOG`: the ids it offers, honestly (see rule 4).
9. `_BASE_CATALOG`: label, system prompt, the tool list **in the CLI's own tool names**, and
   `tool_enforcement` — `hard` only where the runtime really can withhold a tool, per UHP §4.3,
   which forbids both overstating and understating it. A tool id that matches nothing is dropped
   on the way through and disables nothing while the console reports it as off.
10. `_INTEGRATION_WIRING`: which provider types can drive it.
11. `_CUSTOM_FORMAT_BACKENDS`: which custom endpoint formats it can actually speak.

`_HID_PREFIX_RE`, `_backend_of_builtin` and `_backend_of_harness` are DERIVED from `_BASE_CATALOG`
and need no edit — they were hand-written lists once, and each silently missed a base.

**The console** — and note only the first of these is caught by the type-check:

12. `ui/src/lib/harness.ts`: the `backend` union type, and `OOB`, the built-in harness the console
    lists with its mark and models.
13. `ui/src/components/HarnessLogo.tsx`: its brand mark, if there is one. A mapping to a file that
    does not exist renders a broken image — worse than the generic glyph it falls back to.
14. `ui/src/components/HarnessSettings.tsx`: the instruction-file label, which must agree with
    `_agent_doc_path` or the settings page names a file the runner does not write.

**Install and measurement:**

15. `docker/entrypoint.sh`: `HR_BACKENDS`, `backend_bin`, an installer, and its call in
    `install_backends` — the CLI installed on first start, under its own licence, pinned exactly
    and VERIFIED. A pinned tag is not verification: a tag can be moved and a release asset
    re-uploaded. Where upstream publishes checksums, fetch and compare them (`install_omp`); where
    it does not, compute the digests yourself and pin them beside the version (`install_goose`).
    An override that skips the check must say so in the log rather than skip it quietly.
16. `scripts/support-matrix/custom-harness.mjs`, `BASES`: otherwise the custom-harness dimension
    never measures this harness at all.
17. `docs/support-matrix.md`, a column per provider, produced by the suite, with its notes in
    `docs/support-matrix-notes.md`.

Its models must be honest: every id the picker offers must run as itself, and a turn that ran on a
different model fails rather than quietly succeeding.

## Console changes

Any change to a console surface must survive narrow widths. `scripts/responsive-audit.mjs` sweeps
every surface at every width that matters and flags content wider than the box that holds it; its
header records the last run and its result.
