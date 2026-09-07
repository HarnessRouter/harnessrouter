# Support matrix notes, self-hosted instance, 2026-09-06

The tables in [support-matrix.md](support-matrix.md) were produced by `scripts/support-matrix` against the self-hosted test instance (a single container, owner trust, the runner beside the gateway), one provider at a time, three workers with one harness each (one worker for the free-tier key), five scenarios per harness x model pair: first turn, follow-up, model switch inside the column, artifact, recycle. A row that failed was re-run once and the first try is kept in its notes; nothing was inherited from the hosted run.

## Versions

The run started on v0.13.5 and finished on v0.13.13. Every release between them came out of a finding below and was deployed on the instance behind a live-turn gate before the next column: 0.13.5 (local blob store lists by prefix), 0.13.6 (read caches, the word "refused" is not a key refusal), 0.13.7 (a Codex history kept whole under the same account, finished turns release their process handle), 0.13.8 (a Google key can be saved, qwen drops gpt-5.3-codex, a task reopened by URL keeps its model, the broker resends a Google request without the refused field, a self-hosted sandbox reaches the broker on loopback), 0.13.9 (opencode's base carries /v1), 0.13.10 (the relay's base carries its API version), 0.13.11 (the claude CLI strips it), 0.13.12 (a checkpoint that cannot be restored aborts the turn), 0.13.13 (owner trust normalises an Azure base like the broker).

## Columns

- **tokenrouter** (the instance's own TokenRouter integration, 26 models): 169 pairs, 832 of 840. opencode with gemini-3.6-flash is refused on its tool schema (`Unknown name "$schema"`); qwen with gpt-5.3-codex answers text turns and fails its tool turn (a Responses-only model on a chat/completions harness; qwen no longer lists it since 0.13.8); Codex refuses gpt-5.3-codex after another model by design.
- **vercel** (the instance's Vercel AI Gateway integration, 31 models): 174 pairs, 857 of 859. Hermes refuses kimi-k2.7-code and ling-3.0-flash on the 32k context window Vercel declares for them, below its 64k minimum.
- **azure-openai** (the instance's own Azure integration, user-interview resource, 8 deployments): 55 pairs, 267 of 271 after the gpt-5.3-codex deployment was added and the Codex same-account rule shipped in 0.13.7. Before it, Codex could not continue a thread after a model switch on Azure (a reasoning item minted by one deployment is not resolvable by another). Remaining: the Codex family rule for gpt-5.3-codex; qwen's chat/completions call to a Responses-only model.
- **openai** (the org key, 8 models): 55 pairs, 267 of 273. Remaining: the same two by-design rows, and gpt-5.6-luna answering with the second message's word instead of the first after a recycle (its history was intact).
- **anthropic** (the org key, 7 models): 49 pairs, 245 of 245 (opencode's haiku first turn answered a capabilities blurb once and the word on the next try) after three fixes the column found: opencode's Anthropic client needs the base to carry /v1 (0.13.9), the loopback relay that carries cline and qwen needs the same (0.13.10), and the claude CLI needs it stripped again (0.13.11). A base stored either way now serves every harness.
- **openrouter** (a new key, 31 models): 134 pairs, 669 of 670. qwen with gpt-5.6-luna answered without the first word after a recycle. The key reached its spend limit later that day; any OpenRouter failure after about 13:00Z is the key, not the product.
- **azure-e2** (the bundle's agentstudio-oai-e2 resource, 8 deployments): 54 pairs, 267 of 270 after the base was stored with /openai/v1. Stored as the bare portal endpoint, text turns answered and every tool turn was "Resource not found": the broker's normaliser did not run in owner trust (0.13.13). Remaining: Codex refuses gpt-5.3-codex after gpt-5.5 as well, so that model takes no switch partner from now on; gpt-5.6-luna's recycle answer miss.
- **google** (a Free-tier AI Studio key, gemini-3.6-flash): no row measured. The daily quota was spent between the hosted run and this one (429 on opencode and hermes); pi and dsh got Google's unknown-field refusal ("400, no body" as the harness reports it), which the broker resends without the field since 0.13.8 but which owner trust, where pi and dsh talk to Google directly, never sees. Open: route pi and dsh through the loopback relay or keep the fields out of their configs; re-run when the quota resets.

## What the run itself taught

- A self-hosted instance runs one runner for the container's life; the hosted pool recycles them per session. Every leak that the pool hid showed here: two pipe descriptors per turn (0.13.7), the local blob store walking all 15,628 blobs on every list (0.13.5).
- Every base normalisation the broker does must also happen where owner trust hands the sandbox its base; three columns each found one.
- The runner judges a turn by the server's own record (session detail, then the turns feed), never by the task pill or the file cards, which lag it; the message must appear in the transcript and open a new turn record before it is judged; the switch partner comes from the column's own table; a finished pair deletes its session, since 170 sessions per provider filled a 62 GB disk.
- Cold recall (a session idle past the sandbox cooldown, reopened by URL): see the section below.

## Cold recall

One session per harness on the instance's own map (TokenRouter, Azure, Vercel), a first turn with a marker word, 35 minutes idle past the sandbox cooldown, then reopened by URL and asked for the word. All eight came back with it, on the model the task ran with: claude-code (claude-opus-4.8) 8 s, codex (gpt-5.5) 10 s, hermes (gpt-5.5) 14 s, pi (gpt-5.4) 6 s, dsh (deepseek-v4-pro) 8 s, opencode (gpt-5.4) 18 s, qwen (qwen3.7-max) 16 s, cline (gpt-5.4) 8 s. The sessions were created and reopened one at a time, so this is the restore path without a burst; the hosted run's burst losses (a failed restore that did not abort the turn) are the case 0.13.12 makes visible and 0.13.13 carries.

## Totals

695 pairs over eight columns; every failing row carries the provider's own text in the table.

## TokenRouter's Gemini channels refuse JSON-schema keys (2026-09-06)

TokenRouter's Gemini channels forward a harness's JSON-schema tool declarations to Google's native
API as sent, and Google's function-declaration validator refuses what its own OpenAI-compatible
endpoint, OpenRouter and Vercel normalise away: `Unknown name "$schema"` (opencode),
`Unknown name "exclusiveMinimum"` and `schema didn't specify the schema type field` (cline). The
first turn of a task fails on the ids those channels serve natively (gemini-3.8-flash for one; the
same declaration passes on 3.7-flash, 3.5-flash and 3-flash-preview), so it is per channel, not
per model. Until TokenRouter normalises them itself, the broker and both loopback relays normalise
tool parameters to Google's Schema subset for that channel and Gemini models only (keys outside the
subset dropped, oneOf to anyOf, const to a one-value enum, exclusive bounds to bounds, a type list
to one type plus nullable, a type on every node, items on every array, required limited to existing
properties, an empty declaration dropped). The report is with TokenRouter; when their channel
normalises, this comes out of both trees.
## The gemini backend (Gemini CLI) serves every Gemini id as itself (2026-09-06)

gemini-cli speaks Google's native API with the raw key, so the backend runs in owner trust only and
on Google's own ids. On the API-key auth path the CLI's resolver rewrites every id ending in "-flash"
to gemini-3.5-flash (0.58.0, 0.59.0-preview.0 and the 2026-09-06 nightly alike), 3.1-pro-preview to
its customtools variant, and its default resolution table retargets 3-flash-preview, 3.5-flash and
2.5-flash by context. The first measurement on the instance (all five scenarios on each of the
eleven ids, org holding only the Google integration, 55 of 55 runs passed, artifact turns included on
every Gemini 3.x id) showed gemini-3.8-flash, 3.7-flash, 3.6-flash and 2.5-flash served by
gemini-3.5-flash on every turn. Richard's rule: the models are honest, no fallback. So the runner
turns on gemini-cli's `experimental.dynamicModelConfiguration`, under which `-m` resolves through the
CLI's resolution table, and writes a `modelConfigs.modelIdResolutions` entry with no contexts for
every id the backend lists and the turn's own model, pinning each to itself (the settings deep-merge
a user entry into the default one, so a plain default alone left 2.5-flash rewritten; the contexts
must be emptied). Measured on the pinned 0.58.0 with those settings, all eleven served as themselves.
And a turn the CLI ran on another model than the one asked for now fails with the reason on the
record ("the CLI ran X instead of Y"), never completes: the matrix's served-model rule, enforced for
the user. The backend lists all eleven; the instance column on 0.14.0 with the served-model rule as
judge is below. The backend's default is gemini-3.8-flash, the newest flash, since 0.14.1.

## The Gemini family, one provider at a time (2026-09-06)

The eleven Gemini ids main serves on google (gemini-3.8-flash, 3.7-flash, 3.6-flash, 3.5-flash,
3.5-flash-lite, 3.1-flash-lite, 3.1-pro-preview, 3-flash-preview, 2.5-pro, 2.5-flash,
2.5-flash-lite) were measured on every chat harness with the org holding ONE integration at a time
(plus two that serve no Gemini id), the snapshot restored after each column. Columns: google
(the sponsored Google AI Studio key), OpenRouter, Vercel, TokenRouter (its seven Gemini ids), and
the gemini backend on its own column. A pair served by a connection other than the one under test,
or as a model other than the id asked for, is a finding, never a pass; the columns run before
0.13.21 carry the session's last connection per pair (the per-turn stamp landed with #103), the
later ones the connection of every turn record.

- google, 0.13.16 then the opencode rows on 0.13.20: 65 pairs, 324 of 325 after the re-run. The
  thought-signature fix (#96) made every Gemini 3.x artifact turn pass on pi, dsh, qwen, cline and
  hermes; opencode reached Google directly until #97 routed its OpenAI-shape turns through the
  loopback relay, after which its eight 3.x ids pass every scenario. The one open miss is opencode
  on gemini-2.5-flash, which passed its retest in the family run and failed artifact and recycle on
  the single-try re-run: flaky on the smallest 2.5 flash through opencode, not a fix regression.
- OpenRouter, 0.13.16: 65 pairs, 324 of 325. hermes on gemini-2.5-flash-lite answered "DONE" (its
  last word) instead of the first message's word after a recycle, twice. Every Gemini 3.x artifact
  turn passed: the aggregator carries the thought signatures itself.
- Vercel, 0.13.16: 65 pairs, 323 of 325. dsh on gemini-2.5-flash-lite declined its own write tool
  on the artifact turn ("the available tools lack the functionality to create files"), twice;
  hermes on gemini-3.6-flash made the same recycle recall miss as on OpenRouter.
- TokenRouter, 0.13.20 then the qwen and cline rows on 0.13.22: 41 pairs, 205 of 205. Its Gemini
  channels forward tool declarations to Google's validator as sent; the three schema rules (#101,
  #102, #104) took the column from 195 to 205: `$schema` and `exclusiveMinimum` and a property
  without a type (opencode, cline), a nullable choice without a type (cline's read_files), and an
  anyOf with siblings (qwen's fork_turns), each refused by a different channel.
- gemini backend (Gemini CLI, PR #72), on 0.13.18-rc.1 built from that branch: 11 pairs, 55 of 55,
  with four served-as findings (gemini-3.8-flash, 3.7-flash, 3.6-flash, 2.5-flash served by
  gemini-3.5-flash on every turn, the CLI's own rewrite); the backend lists the seven ids served as
  themselves.

## The gemini backend through TokenRouter (2026-09-07)

TokenRouter serves Google's native API when the model carries its vendor prefix:
`POST https://api.tokenrouter.com/v1beta/models/google/gemini-3.8-flash:generateContent` (and
`:streamGenerateContent?alt=sse`) with the key in `x-goog-api-key` answers in Google's own shape;
without the prefix, and for the ids it has no channel for (gemini-3.1-flash-lite, 2.5-pro, 2.5-flash,
2.5-flash-lite), it refuses "No available channel". So the seven Gemini ids in TokenRouter's table run
on the Gemini CLI through the platform key. In owner trust the CLI reaches the provider itself, so a
TokenRouter connection points GOOGLE_GEMINI_BASE_URL at the loopback relay, which owns the vendor
prefix and the key; the CLI keeps its own model id, so the pinned resolutions and the served-model
check are unchanged. OpenRouter and Vercel expose only the OpenAI shape and cannot drive the CLI
without a translating relay. The TokenRouter column for the gemini backend follows below.

## The Gemini CLI's helper calls run on the turn's model (2026-09-07)

A long Gemini CLI turn (a deck written over five minutes on gemini-3.8-flash, on both trees) ended
failed with its own answer shown as the reason, and its record named a second model. The CLI's
housekeeping calls (model routing, plan mode, context compression, the next-speaker and loop checks)
go to a "flash" or "pro" classifier tier that defaults to gemini-3-flash-preview or
gemini-3-pro-preview, and those calls land in the turn's stats beside the answer model; the served-
model check read them as a switch. Headless gemini-cli has no fallback handler, so the fallback chains
suspected first were never the switch. Both classifier tiers now pin to the turn's own model, so every
model the CLI calls in a turn is the one asked for; the gemini backend takes the canonical id from the
gateway and the relay names it for the provider on the native path (TokenRouter's google/<id>); and a
failed turn's reason is the runner's error before its result.

## The omp backend (Oh My Pi), pi's lineage (2026-09-07)

Oh My Pi is pi's lineage: it speaks pi's `--mode json` event stream unchanged (measured on 18.1.13:
session, message_update, message_end, tool_execution_start/end, agent_end, the same fields) and
shares pi's normaliser; its OpenAI-shape turns ride the loopback relay as pi's do, so it reaches what
pi reaches and its list is pi's. Every assistant message names the model omp ran, which is the
served model on the record; a turn omp ran on another model than the one asked for fails with the
reason, never completes. The binary is pinned to 18.1.13 and verified against the release's
SHA256SUMS. Per-provider columns follow below as they are measured, one integration on the org at a
time, the served-model rule as judge.

## omp (Oh My Pi), one provider at a time (2026-09-07)

The omp harness (PR #68, omp 18.1.13, pi's lineage) was measured on the pre-release 0.14.3-rc.1 built from
its branch, one column per provider with the org holding only that provider's integration, every id the
provider serves that the omp catalog lists, all five scenarios, one retest for a failed row. 705 of 705
scenario runs passed: Google AI Studio 55/55 (11 ids; gemini-3.1-flash-lite failed its first try and passed
on retest), OpenRouter 184/184 (37), Vercel AI Gateway 184/184 (37), TokenRouter 164/164 (33), Anthropic
40/40 (8), OpenAI 39/39 (8), Azure OpenAI E2 39/39 (8). Every turn ran on the column's own integration and
no id was served as another model. The switch scenario has one run fewer per column because the switch
partner, gpt-5.6-sol, is not switched to itself.

omp reports the model it ran on every assistant message, so its columns are the first where a provider's
own name for a model reached the judge: OpenRouter, Vercel and TokenRouter serve claude-fable-5 as
anthropic/claude-fable-5, gemini-3.8-flash as google/gemini-3.8-flash, mistral-medium-3.5 as
mistralai/mistral-medium-3-5, qwen3.8-max as qwen/qwen3.8-max-0902; Anthropic serves claude-haiku-4.5 as
claude-haiku-4-5-20251001 and claude-opus-4.7 as claude-opus-4-7. The exact rule counts each as a served
model other than the id asked for. Beside it the tables now apply the same-model rule the hosted gateway
uses (scripts/support-matrix/samemodel.py, identical in both trees): a vendor prefix an aggregator adds
or drops and a dated or versioned suffix a provider appends are the provider's alias of the same model,
noted in the row and counted; a different family, number or tier under any prefix (google/gemini-3-flash-
preview for gemini-3.8-flash, gemini-2.5-flash-lite for gemini-2.5-flash) stays a finding and is not
counted. A turn that ran on several models is an alias only when every one of them is the same model.

Two things the run itself taught. A snapshot that holds an integration whose key only its owner knows
cannot be restored after a deletion-level column, because the instance masks stored keys; the restore
now restores everything it can and names the rest instead of aborting whole. And a column's isolation
deletes every other integration on the org, so nobody can test on the instance while a column runs;
the org comes back between columns and at the end.

## What the artifact row measures, and what the earlier columns were judged by (2026-09-07)

Until this date the artifact scenario asked only whether SOME rendered file card carried the expected
filename. That question cannot see a file rendered twice, and the console did render one produced file
as two identical cards until a reload, in every harness that produces files. The row now requires the
rendered cards to BE the turn's stored files, the same names and the same count, and fails with both
lists side by side otherwise; the record is read after its files are attached, which the settle does a
few seconds after the turn goes terminal.

Every column in the tables above was measured before that change and was judged by the older rule. Their
scenario counts stand as measured, and none of them is evidence either way about duplicate cards. The
duplicate itself is fixed in 0.15.1, verified on the release across gemini, cline, qwen, dsh, opencode
and omp: one stored file, one rendered card in each.
