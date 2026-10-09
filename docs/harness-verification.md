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

One base is not a coding agent. `systemone` runs a decision loop over a typed action space rather
than a CLI over a workspace, so the artifact scenario's prompt does not apply to it; it is verified by
its own loop (its package's tests, its UHP conformance and its benchmark) and by the first-turn,
follow-up, switch and recycle scenarios here. See docs/support-matrix-notes.md, "systemone".

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

## The family tour

One conversation, one deliverable, every model family in turn. The first turn builds a small
deliverable (a one-page `.pptx`); each following turn switches the composer's model to the next
family (OpenAI, Anthropic, Google, xAI, Meta, DeepSeek, Moonshot, Qwen, Zhipu, Mistral, StepFun,
Tencent, NVIDIA, one model each) and asks for one more change to the same deck. A turn passes when
it completes and the deck is produced again; the tour passes when every family the instance
serves passes. Nothing about the harness is allowed to depend on which model answered the turn
before: the session file, the resume, the verdict on how the turn ended.

It exists because the matrix's five scenarios did not catch what a person found in five turns
on 2026-09-27: a CheetahClaws turn on muse-spark-1.1 that answered in full was reported as a
failure, because the model's smaller context made the CLI compact its history mid-turn and the
driver judged the turn by a position in that history. Every base runs the tour before its column
is published, and a base that changes how it reads its own history runs it again.

`scripts/support-matrix/family-tour.mjs` drives it through the console (`HARNESS=<base>`; `SID=`
continues an existing conversation, which is how a person's own failing session is retested) and
writes one record per family: model, served model, status, seconds, the files the turn produced,
and the failure text when there is one. The notes name the instance, the connections and the
result per family.

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
   A harness can also report a failure NOWHERE. openhands' agent-server publishes an error event
   only for an exception that is not a `ConversationRunError`, on the assumption that the run
   already emitted its own — and an exception raised out of the run's error handling is exactly
   the case where nobody did: the status flips to error and the wire carries no reason at all.
   Where a backend writes a log, read its tail as the fallback, and take the EXCEPTION lines out
   of it rather than the last lines — a turn that dies in seconds and is then retried to
   exhaustion ends with `SIGTERM … Shutting down`, and putting that in the record is worse than
   silence, because it reads like a reason.
   A successful turn can also lose a configured MCP server. Goose 1.50.0 logs `Failed to start
   extension 'name' ..., continuing without it` on stderr, then emits a successful stream-json
   result. The runner must preserve this as `system/mcp_unavailable` so the gateway can tell the
   user which tools were absent. Do not copy the extension's raw stderr into that event; it may
   contain credentials.
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

### Remote runtimes

A remote runtime is a harness whose agent loop runs somewhere this runner does not spawn it: a
hosted session reached over an API, with the turn process here an HTTP client to it. Qoder Cloud
Agent (`qoder`, `runner/qoder_driver.py`) is the first. The registry entry declares it —
`BACKENDS[...]["remote"] = True` — and that flag is what the runner keys the differences below on,
so the second one follows the same shape instead of rediscovering it. The per-turn contract does
not change: one process per turn, `__hr_init`, one `{"m","p"}` line per event, `__hr_result`, and
`server.py` unaware of the wire. What changes is that three things every local backend gets for
free have to be built, and several of the registration points above have no object.

**Not applicable, and the base says so rather than skipping it:**

- *15, the installer.* There is no binary. `docker/entrypoint.sh` installs nothing for it, and the
  catalog entry's notes say the runtime is remote.
- *3 and 4, `_write_skills` and `_agent_doc_path` as places a loader looks.* Nothing on this box
  loads anything. Skills are staged under `.harness/skills/` for the DRIVER to publish (qoder:
  as Skill resources bound on the session's Agent, reused by content hash); the harness's
  instructions travel in the job and become the remote Agent's system prompt
  (`_write_agent_doc` writes nothing, the systemone precedent).
- *A plugin's stdio MCP servers.* They are processes on this box; a remote runtime cannot dial
  them. The driver reports each one as `system/mcp_unavailable` and the base lists no tool for
  them. URL servers are configured on the remote Agent, and their bearer travels to the vendor
  (qoder: a Vault credential, created per session and deleted with it); the base's description
  says so, because the harness owner's token then lives at the vendor.
- *Environments* (`runner/environments.py`). The layer is mounted read-only in THIS sandbox; the
  remote session sees only what the driver uploads. A turn that names one is refused before any
  process starts (`turn()`, 400), rather than run without it.
- *7, `CHECKPOINT_EXCLUDE` for credentials.* The driver writes none: it holds the relay's
  placeholder. What it does write is `.harness/<backend>/state.json`, the ids of everything it
  created remotely, and that file MUST travel in the checkpoint (continuation and deletion on
  another sandbox depend on it).

**Must be answered instead, each in the PR description and each with a test:**

- *Input files.* `_write_input_files` lands them in a workspace the runtime cannot see. The driver
  uploads what was staged and tells the model where it is mounted; what the vendor will not take
  (qoder: anything but a text-type file, 5 MB) fails the turn before anything is created, naming
  the file, and the base's description states the limit.
- *Artifacts.* Nothing under `.harness/` is a produced file (`_PRODUCED_EXCLUDE_PREFIX`). A
  delivered artifact is written to the workspace ROOT and rides the checkpoint, diff and download
  path unchanged. The driver keeps the list the stream declared and verifies every one landed with
  its declared size; one missing, expired or refused ends the turn `incomplete` naming it, even
  when the remote run reports success. **Artifact names are input**: only a plain file name is
  written — no path separator, no `..`, nothing opening a dot directory, no control characters —
  an existing file is never overwritten (the new one lands as `name (2).ext` and the record says
  so) and a symlink is never followed. `../x` and `.harness/x` are pinned refused.
- *Cancellation.* `_kill_proc_tree` is SIGSTOP then SIGKILL; neither runs a handler, and a killed
  client leaves the remote turn running and billing. For a `remote` backend `_stop_proc` sends
  SIGTERM first and waits `_REMOTE_STOP_GRACE_S` while the reader loop keeps draining stdout, so
  the driver's own line — "cancel accepted", or "cancel failed, session <id> may still be running"
  — reaches the record before the kill. The same path serves the wall-clock cap. A driver that
  dies without its result ends the turn with "the session may still be running" (`_qoder_eof`).
- *Continuation.* `_SESSION_PRESENT` has no probe for it: the driver itself asks the vendor
  whether the session the caller named is there and takes a message, emits `resume_lost` when it
  is not, and starts a new one. A session still running an earlier turn is a conflict and fails
  the turn; it is never retried blindly. `hard` has to hold across turns too: a session that
  pins its Agent's configuration at creation gets its tools replaced before every message
  (qoder: `POST /sessions/{id}` with `agent.tools`), pinned by a test that disables a tool
  between two turns.
- *Recovery.* The runner replays nothing. A dropped stream is the driver's to resume from its
  last event id inside the turn; the message is NEVER sent twice — when its acknowledgement is
  lost the session's history decides whether it arrived. A stream that ends without a terminal
  event asks the session's status before deciding.
- *Served model, usage, charge.* Rule 2 and the token columns read what the relay saw; on a
  pass-through route the relay sees nothing it may use, and the vendor reports what it reports.
  qoder's public API exposes neither token counts nor the model that served, so its rows read
  "served model unreported", the token cells are empty, and the result carries no `usage` and no
  `model`. What it does expose goes on the result as `charge: {amount, unit, basis}` — a shape
  that names no vendor, so the next runtime uses the same field — never folded into the token
  columns, and with `basis: "snapshot"` when the figure can lag the turn (qoder's sandbox charges
  settle after idle). Every `stop_reason` other than the vendor's normal end is `incomplete` with
  the raw reason, and a typed error event with no retry left is `failed` with the vendor's
  sentence.
- *Deletion.* Since 0.32.0 a delete removes data for real, and for this backend the conversation,
  the input files, the artifacts and every Agent, Skill, Vault and Environment the driver created
  live at the vendor. `DELETE /workspace` takes the connection in its body (`WorkspaceDelete`) and
  runs the driver in purge mode before removing the folder (`_remote_purge`); each remote delete
  that fails is reported with its id in the answer and the log, never swallowed. The lifecycle is
  one of everything per session — created on the first turn, updated when the harness changed,
  deleted with the session — so nothing outlives it and the per-turn runner keeps no state at
  harness level.
- *The relay is still the credential boundary.* The vendor's API is HTTPS with a bearer, which is
  exactly what the loopback relay fronts: the base is registered as a PASS-THROUGH route
  (`_qoder_relay_route`, `_HermesRelayHandler._passthrough`) — no body rewrite, no retry ladder,
  and NONE of the taps, because a session object through the model-call taps would record the
  CONFIGURED model as the served one and the matrix would score a check the backend cannot make.
  A stalled pass-through stream is closed, not narrated with an error event the driver would read
  as the API's own. DELETE is forwarded. On the hosted service a sandbox never holds a vendor
  credential, so this is not optional there.

## What the matrix did not see, and what changed (2026-09-30)

A customer ran twelve of their production tasks across seven bases and nine models on a 2026-09-30
image and handed back twelve defects. Every scenario of this matrix had passed on the same code.
The matrix was not wrong about what it measured; these failures lived where it did not look.

**One route.** Every column ran through one aggregator. The customer brought the vendor's own key.
On that route Claude Code reported no served model (the CLI names none on its result; the relay,
which stamps one for the aggregator route, was not in the path), so a request for an unlisted
model ran on the harness default and nothing said so. goose and OpenHands reached the vendor over
its OpenAI-compatible surface, which cannot cache a prompt, and paid 6 to 8 times the Claude Code
price per task; hermes crashed on a fresh volume's SDK. None of this exists on the aggregator route.
*Changed:* a turn with no served model is a finding, never a pass (`unlabelled`, run.mjs and
render.py); a Claude pair that read no prompt cache across its turns is a finding (`tokens`); the
three bases take a Messages endpoint natively; hermes installs the SDK its own extra pins; and a
release's matrix runs the Claude pairs on the vendor's own route as well as the aggregator's.

**Short turns.** The longest scenario ends in a few minutes. The console's proxy cut every
synchronous turn at 800 s, and the customer's parsing tasks ran 13 to 15 minutes. *Changed:* the
proxy allows the gateway's hour and logs a dropped upstream with its elapsed time; a release check
holds one synchronous turn past 800 s through the console's port (`sleep 850`, then a word).

**Working, not priced.** The scenarios asked whether a turn completed, never what it cost. A pair
that completes at 7 times the price of another is a pass here and a defect to a customer paying for
it. *Changed:* the matrix records each pair's input tokens and cache reads and prints the cache
share; `scripts/benchmark` prices the same work across pairs.

**Nothing went wrong on purpose.** No scenario drops a provider stream, asks the exec policy about
a command, exceeds a Skill's description cap or omits a field a write requires. Each of those is a
unit test now (`runner/tests/test_codex_reconnect.py`, `gateway/tests/test_model_refusal.py`); a
matrix cannot produce a provider's 502 at will, and should not pretend to.

**The fresh volume.** The release check brought a fresh volume up and asked whether it answered,
not what it installed. *Changed:* the check reads the Hermes venv's SDK versions against the pins.

The rule behind all five: a scenario proves the path it takes, and only that path. A route, a
duration, a price, a failure mode or an installer that no scenario takes is unverified, whatever
the table says.

## Beyond working: the benchmark dimension

The matrix asks whether a harness works. `scripts/benchmark` asks how well a harness × model
does the same work, on public task suites whose grading is deterministic, one task per session,
every number read from the turn record. Its rules are the matrix's rules 1 and 2 plus three of
its own (a run that reached the network or searched the machine for the task is a finding, tokens
on one convention, no judge), stated and pinned in [scripts/benchmark/README.md](../scripts/benchmark/README.md).

## Console changes

Any change to a console surface must survive narrow widths. `scripts/responsive-audit.mjs` sweeps
every surface at every width that matters and flags content wider than the box that holds it; its
header records the last run and its result.
