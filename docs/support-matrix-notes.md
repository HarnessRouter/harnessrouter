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
## The gemini backend (Gemini CLI) lists the ids it serves as itself (2026-09-06)

gemini-cli speaks Google's native API with the raw key, so the backend runs in owner trust only and
on Google's own ids. Measured on the OSS instance with the org holding only the Google integration,
all five scenarios on each of the eleven ids the google provider serves, 55 of 55 runs passed, artifact
turns included on every Gemini 3.x id (the CLI carries the thought signatures itself). The result
event's stats are keyed by the model the CLI actually called, and that is where the catalog's rule
bites: on the API-key auth path gemini-cli 0.58.0 (and 0.59.0-preview.0 and the 2026-09-06 nightly)
treats "3.5 Flash GA" as launched and its resolver rewrites every id ending in "-flash" to
gemini-3.5-flash, with no setting to turn it off. gemini-3.8-flash, 3.7-flash, 3.6-flash and 2.5-flash
were served by gemini-3.5-flash on every turn and are listed as served-as findings, not passes; the
backend lists the seven ids served as themselves: gemini-3.5-flash, 3.5-flash-lite, 3.1-flash-lite,
3.1-pro-preview, 3-flash-preview, 2.5-pro, 2.5-flash-lite. The four stay reachable on the same key
through the OpenAI-shape harnesses, where Google serves each id as requested on both API surfaces.

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

