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

## dsh on the 0.1.2rc1 runtime (2026-09-08)

The pin moved from 0.1.0rc7 to 0.1.2rc1 because rc7's runtime does not carry the MCP client at all
(zero `dsh-mcp-client` strings in its binary), which is why the custom-harness dimension found dsh never
calling a configured server. The new runtime composes an `sdk` profile that the driver overlays with a
`--patch` file: the stock JSON-RPC server row disabled and the resume-or-create server inserted (a patch
cannot rename a row), one `dsh-mcp-client` row per server, and the pi-ai route merged into the stock
`llm-pi-ai` row. Measured locally through the real driver against TokenRouter with
`deepseek/deepseek-v4-flash`: `mcp__deepwiki__read_wiki_structure` called and answered in 10 s, a second
process resumed a session and recalled its codeword, and a bash call carried its name through the relay.
The sdk profile also offers more tools than rc7 did (glob, grep, str_replace_editor, web_search,
web_fetch, skill, subagent_fork, workflow); the catalog lists them. Every dsh column before this date
was judged on rc7.

### dsh columns on 0.15.6-rc.3 (2026-09-08)

The full dsh column on the 0.1.2rc1 runtime with the final composition (no sandboxing executor):
Vercel 189/189 (two one-off misses passed on retest), TokenRouter 169/169, Anthropic 40/40, OpenAI 44/44,
Azure OpenAI E2 44/44, Google 55/55. OpenRouter ran as a partial that morning (the shared account was empty:
four cheap pairs measured, gpt-6-astra refused 402 before anything ran) and was rerun in full on 0.15.7 after the
top-up, 2026-09-10: 189/189, nothing retested, no substitution. Two earlier candidates on the same runtime were rejected by their own columns: rc.1's profile sandbox
refused every bash command on the container (no bubblewrap, no Landlock), and rc.2's still-mounted sandboxing
executor advertised `sandbox_permissions` and `justification` on every file tool, which GPT models filled on
every write and the runtime then refused (five artifact misses on the Vercel column). The custom-harness
dimension on the same candidate: ten of ten bases, MCP called on each.

## codex through its app-server (0.15.9, 2026-09-10)

Hosted runs codex through its app-server and the open source image ran `codex exec`, the same code on a
flag the image never set; 0.15.9 sets it on, so every codex column before this date was measured on
`codex exec`. The column rerun on the app-server path, per provider: Vercel 43/44, TokenRouter 43/44,
OpenAI 44/44, Azure OpenAI E2 44/44, OpenRouter 43/44. The misses: gpt-5.6-luna's recycle recall on
Vercel and OpenRouter, the same wrong word ("DONE", the end of its artifact turn) it gave on `codex exec`
on 2026-09-06, a model wobble that survives a retest; and one deterministic refusal on TokenRouter, a
gpt-5.4 thread switched into gpt-6-astra, "The encrypted content for item rs_... could not be verified",
while six other gpt-5.x threads made the same switch on the same key and passed and the same switch
passed on Vercel: TokenRouter serves gpt-5.4 from more than one upstream account, and OpenAI's encrypted
reasoning items are opened only by the account that produced them (hosted saw the same refusal on a
same-model cold restore of gpt-5.4 on 2026-09-08). 0.15.10 says that refusal in words instead of the
provider's JSON. The custom-harness dimension's codex row on the app-server path: skill script ran, tool
policy held, `deepwiki.read_wiki_structure` called by name (the item-spelling fix of 0.15.8).

### The results file (2026-09-10)

`docs/support-matrix-results.json` is the merged record the table is rendered from (`python3
scripts/support-matrix/render.py docs/support-matrix-results.json`), committed beside it from this date so a
render is reproducible. The provider-wide `tokenrouter` and `vercel` columns of 2026-09-06 are not in it:
their result files were lost with the scratchpad, and their sections in the table are carried from the
render of that date until the columns are measured again.

## goose columns (2026-09-12/13, candidate 0.17.0-rc.3, goose 1.50.0, codex 0.154)

Seven columns for the goose harness (PR #164), five scenarios per model, two workers per column,
the served model read by the relay (goose's CLI never reports one): TokenRouter 154/155, Vercel
199/200, OpenRouter 200/200, OpenAI 35/35, Azure OpenAI e2 35/35, Anthropic 35/35, and the hosted
HarnessRouter door 155/155 through the official key ($2.35 for its 155 checks). Zero substitutions.
The two misses: gpt-5.6-luna's recall after recycle on TokenRouter (the codex column's class), and
qwen3.7-max's artifact turn on Vercel, which now reads FAILED with Vercel's own "Upstream stream
ended before terminal chunk" (a provider error goose renders as prose; the runner fails the turn). Five ids only Vercel and OpenRouter serve (hunyuan-3, ling-3.0-flash,
minimax-m3, nemotron-3-ultra, qwen3.7-flash) were measured on those two after the first pass
(all five scenarios each), so goose's list is 40. claude-opus-5 was measured on the first pass and left off goose's list: once a session holds a turn by
another model (the switch scenario), Anthropic answers every further opus-5 request from goose with
an empty stream and finish_reason content_filter (reproduced through the relay against Anthropic
directly); the same session without the switch completes the tool task. The relay now records that
finish and the turn fails with the provider's reason. gemini-3.5-flash-lite answered one recall with a tool call on Vercel only.
The custom-harness dimension for goose needs `MCP_URL=https://mcp.context7.com/mcp` (deepwiki cannot
handshake with goose, reproduced through goose's own extension flag); on Vercel all six claims pass.

## The seven ids of the 2026-09 model sweep (2026-09-13, candidate 0.17.0-rc.5, hermes on Vercel re-run on rc.9)

deepseek-v4.1-flash, qwen3.8-flash, qwen3.8-27b, qwen3.7-plus, hunyuan-4-preview, nemotron-3.5-lightning
and nemotron-3-super, on every provider that serves them, across hermes, dsh, opencode, pi, omp, qwen,
cline and goose (the harnesses whose catalogs carry them), five scenarios each. qwen3.8-27b has no
TokenRouter channel and is not run there.

- TokenRouter: 48 pairs, 240/240. Vercel: 56 pairs, 280/280. OpenRouter: 56 pairs, 280/280. Zero foreign
  connections. Served names are the providers' own ids for the model (tencent/hy4-preview,
  nvidia/nemotron-3-super-120b-a12b, nvidia/nemotron-3.5-lightning, qwen/qwen3.7-plus, qwen/qwen3.8-flash)
  and DeepSeek's own name for v4.1-flash, "deepseek-flash", measured with one request per id through
  TokenRouter (v4-flash answers "deepseek-v4-flash", v4-pro "deepseek-v4-pro"); the judge knows it.
- hermes on Vercel failed the first turn for deepseek-v4.1-flash and nemotron-3-super on rc.5 ("has a
  context window of 32,768 tokens, which is below the minimum 64,000 required by Hermes Agent"). Root
  cause, read in the image: hermes treats the loopback relay as a local server and takes the window from
  GET /v1/models/<id> as max_model_len, context_length or max_tokens; Vercel names the window
  context_window, so hermes took the output cap. The relay now carries the window as context_length on
  model listings (runner cf85581). Re-run on rc.9: both pairs 5/5, and the two catalog ids the same
  misread had blocked on Vercel, kimi-k2.7-code and ling-3.0-flash, 5/5 each (their rows are in the
  vercel column as the proof). One hermes qwen3.8-27b recycle missed the recall on rc.5 and passed on its
  single re-run.
- The 0.17.0 no-regression sample (two models per harness on TokenRouter, rc.3) is folded under the
  tokenrouter and per-harness tokenrouter labels.

## xAI and Meta (2026-09-13, candidates 0.17.0-rc.10 and rc.11)

Thirteen ids went in after one tool-bearing chat request per id on each aggregator that lists it:
grok-4.6, grok-4.5, grok-4.3, grok-4.20, grok-4.1-fast, grok-build-0.1, muse-spark-1.3, muse-spark-1.2,
muse-spark-1.1, muse-glimmer-30b, llama-4-maverick, llama-4-scout, llama-3.3-70b. The list that ships is
what measured across hermes, dsh, opencode, pi, omp, qwen, cline and goose, five scenarios each, every miss
re-run once.

- TokenRouter serves the five Grok ids (grok-4.1-fast is listed but answered by grok-4.3, a substitution,
  so it is off that table; no Meta id is listed): 40 pairs, 199/200. The miss: qwen on grok-4.20 replies
  DONE without writing the file, twice.
- Vercel: 104 pairs. Grok 240/240 plus grok-4.1-fast 25/28 (qwen, omp and cline end the first turn with
  "Stream error occurred", twice; the other five harnesses pass). Muse Spark 1.3, 1.2, 1.1 and Muse
  Glimmer 30B 160/160. Llama 4 Maverick and Llama 3.3 70B 0/16: Vercel's Llama route refuses tools in
  streaming mode (HTTP 405 "Tool calling is not supported for model: meta-llama/Llama-4-Maverick-17B-128E-
  Instruct-FP8", HTTP 400 "This model doesn't support tool use in streaming mode") and caps output at
  8192, so no harness can drive a turn there; both ids are off Vercel's table. Llama 4 Scout 28/40: seven
  of eight harnesses failed the artifact or the recall scenario twice; it is not in the catalog.
- OpenRouter serves the five Grok ids, Muse Glimmer 30B, Llama 4 Maverick and Llama 3.3 70B (grok-4.1-fast
  is not listed; llama-4-scout has no endpoint; the three Muse Spark ids answer HTTP 403 until the
  account confirms 18+ on openrouter.ai): 64 pairs, 315/320. Misses, each twice: llama-4-maverick under
  qwen writes the tool call as prose; llama-3.3-70b fails the recall under goose, writes output.txt
  instead of the asked file under pi, and under hermes failed the artifact and recall once and a switch
  on the re-run.
- A pair that failed twice on the one aggregator serving the id is not offered on that harness
  (gateway _NOT_OFFERED): grok-4.1-fast on qwen, omp and cline; llama-4-maverick on qwen; llama-3.3-70b
  on goose, hermes and pi. Zero foreign connections; every served name is the aggregator's own id for
  the model (spacexai/ on Vercel, x-ai/grok-4.20-beta on TokenRouter).
- Found on the way: Vercel's table was derived from OpenRouter's already-edited copy, so an id OpenRouter
  lacks vanished from Vercel too (rc.11 derives every aggregator from the shared slugs).
- Addendum (2026-09-13): grok-4.1-fast is not offered after all. xAI retired grok-4-1-fast-reasoning on
  2026-05-15 and serves the slug with grok-4.3 at grok-4.3's price (docs.x.ai, May 15 retirement
  notice); TokenRouter's answers named grok-4.3, Vercel's echoed the asked id. A retired id answered by
  another model is a substitution whatever the aggregator reports, so its Vercel passes are not a
  measurement of grok-4.1-fast. Eleven ids ship.
- Addendum (2026-09-13, rc.14): Muse Spark on OpenRouter after the account's 18+ attestation
  (settings/preferences; the gate is on the account, not the key): 24 pairs, 118/120 first pass. Two
  recall misses on muse-spark-1.1; hermes passed its re-run, opencode missed twice. muse-spark-1.1 stays
  on opencode because the same pair passes on Vercel; the miss is recorded. OpenRouter's no-channel set
  is empty.

## The kimi backend: Kimi Code CLI 2.0.0 (2026-09-17)

0.18.0 wired this base to MoonshotAI/kimi-cli 1.50.0. That is the predecessor: its own README opens
with "Kimi CLI is evolving into Kimi Code CLI", and the product, the one kimi.ai/code points at, is
the TypeScript rewrite in MoonshotAI/kimi-code. The base now runs the product itself. Everything
below was measured on the 2.0.0 binary, first on the test VM host and then through the product on a
candidate image; the section after this one is the predecessor's record and no longer describes what
the base runs.

**The surface, as measured.**

- Headless is `kimi -p <prompt> --output-format stream-json`, one JSON message per line: a version
  line, assistant text (`content` a string), assistant tool calls (no `content` key, `arguments` a JSON
  string), tool results, and LAST a `session.resume_hint` line, the only place the session id appears.
  No usage and no result event: usage is the relay's, the process exiting ends the turn.
- The model is defined from the environment alone (`KIMI_MODEL_NAME` and its family): a provider
  synthesised in memory, no config file, no key at rest. After a full session the data home
  (`KIMI_CODE_HOME`, under the workspace so a resume survives a recycle) held no trace of the key.
  Telemetry and the self-update preflight are switched off by environment.
- Resume is `-r <id>`. An id the store does not hold is a hard failure, exit 1 with `Session "<id>"
  not found`, where the predecessor silently started over; the builder asks the store first and a lost
  conversation is reported through the resume-lost note instead of failing the turn.
- Failures are exit 1 and one stderr line, `error: failed to run prompt: <class>: <reason>`
  (`provider.auth_error: 401 …`, `loop.max_steps_exceeded: …`), followed by a `See log: <path>` note
  that is trimmed from the reason. The step budget is `KIMI_LOOP_MAX_STEPS_PER_TURN`; unset is unlimited.
- Tool policy is an agent file (Markdown) whose `disallowedTools` match by exact NAME and are enforced
  again before execution. The 26 names are the `tools` array of a live request captured at a stub.
  The agent is bound when the session is created, so a policy change reaches the next conversation,
  not the open one.
- MCP is `$KIMI_CODE_HOME/mcp.json`: a `command` entry is stdio (args, env, cwd honoured), a `url` is
  streamable HTTP, and a legacy server says `transport: "sse"` explicitly. Tools are named
  `mcp__<server>__<tool>`. Skills come from `--skills-dir`; AGENTS.md is honoured.

**Two things the product run found, both fixed before merge.**

- With only Bash disallowed, kimi-k3 said it had no shell of its own "but I can dispatch a subagent
  that does", and did: a built-in subagent carries its own tool list. The agent file now empties the
  subagent allowlist whenever a tool is withheld; the same prompt then calls nothing and says it has
  no shell.
- An MCP server that cannot be reached is skipped in SILENCE: no stream line, nothing on stderr,
  exit 0, where the predecessor failed the turn. The only trace is one line in the CLI's log. The
  runner reads this turn's lines and the reply now ends with a note naming the server.

**Measured through the product** on the candidate image (hr-test, 2026-09-17): a volume first started
by 0.18.0 was upgraded from the old binary in place (`kimi, version 1.50.0` to `2.0.0`, digest
checked); first turn, a follow-up that remembered, an artifact; a person's own skill with its script
plus an MCP tool in ONE round, twice in one session (`Skill`, `Bash`, `mcp__probe__probe_http`), the
script's value one that can only come from running it; the four plugin columns (skill, stdio, SSE,
streamable HTTP).

**Every id on the five console scenarios, through a real browser** (first turn, follow-up, switch to
another model and back, an artifact checked on the file cards, a recycle that must recall the first
message after the sandbox is let go): 50 ids across six connections (TokenRouter 38, Vercel 6,
Anthropic 2, a custom OpenAI endpoint 2, Azure OpenAI 1, OpenRouter 1), **248 of 250**, taking the
latest run of each id. The first full pass was 217 of 250, and all but two of its misses were one
cause with two faces:

- **The CLI sends request fields nobody configured**, captured at a stub across ten model families:
  `max_tokens: 131072` on every request (as `max_completion_tokens` for a gpt or o name), an output
  budget sized for a Kimi window, and `reasoning_effort: "high"` whenever the model NAME looks like a
  reasoning model. OpenAI, Anthropic and Google refuse the first outright, each naming its limit
  ("supports at most 128000 completion tokens", "131072 > 128000", "range is from 1 to 65537
  (exclusive)"); on llama-3.3-70b the budget alone overflows the 131k window ("requested about
  154972 tokens ... 131072 in the output"); TokenRouter turns the second into `thinking.type.enabled`,
  which claude-fable-5-1, claude-fable-5, claude-opus-4.8, claude-opus-4.7 and claude-sonnet-5 refuse
  ("Use thinking.type.adaptive"). The relay route this base registers is born dropping all three, so
  the provider's defaults apply as on every other base. `prompt_cache_key`, the one other extra,
  is harmless and stays. The CLI also retries a failing step ten times, a flat 400 included (143 to
  178 s to surface a refusal); the base sets three attempts.
- **claude-opus-5, artifact and recycle, three runs of three:** "Provider safety policy blocked the
  response". Isolated through the API: the scenario's own words trip it. After the switch turn has
  gpt-5.6-sol answer `M3-gpt-5.6-sol`, the next claude-opus-5 turn is blocked; the same shape with
  neutral words (a text turn, a switch turn answering `SW-1`, then the file) passes every time, as
  does the artifact prompt on a fresh session. It is the provider's policy meeting the test's
  vocabulary, not the wiring, and the id stays listed.


## The kimi backend's first wiring: Kimi CLI 1.50.0, the predecessor (superseded, kept as the record) — behaviour measured, columns NOT yet run

No column has run for this harness. Everything below was measured against the pinned 1.50.0
artifact — its source, its bytes on the wire, and two live turns through Vercel — and none of it is
a substitute for a column. `docs/support-matrix.md` is rendered from
`docs/support-matrix-results.json` and is deliberately untouched by this change.

**Verified by running the real image, not only by reading the CLI.** `docker build` of this tree,
then a container with `HR_BACKENDS=kimi`: `install_kimi` downloaded the pinned archive, the digest
check passed, and the container reported `backends available: kimi` with
`/data/agent-tools/bin/kimi --version` answering `kimi, version 1.50.0`. The two pinned digests were
also compared against upstream's own published `.sha256` files and match character for character.

**One real turn was run end to end in that image**, against Vercel, with the argv and the
`config.toml` the runner generates — not a hand-written approximation. It is an A/B that settles the
`reasoning_effort` question: the same command sent straight to Vercel answers
`Error code: 400 - {… 'param': 'reasoning_effort' …}`, on ONE stdout line (so the `COLUMNS=400`
mitigation for rich's 80-column wrapping works); sent through `_normalize_openai_chat_body`, the turn
completes and prints `{"role":"assistant","content":"PROBE-OK"}` with exit 0. That line is also the
shape `_kimi_to_claude` expects — `content` a plain STRING, not a list of blocks.

Two more things that turn settled, from the state it left behind rather than from the notes:

- `Connection error.` really does exit **75**, observed when the relay was not yet listening.
- The `_resume_lost` probe matches kimi's own store: `md5("/tmp/ws")` is `59fa73ff…`, which is
  exactly the directory kimi created, and `context.jsonl` is in it — so the probe reports the
  session PRESENT for the id that ran and LOST for one that never existed.

**A failed turn reads as failed, by exit code rather than by prose.** kimi classifies provider
failures itself (`Print._classify_provider_error`): 75 (EX_TEMPFAIL) for connection, timeout and
empty-response errors and for HTTP 429/500/502/503/504; 1 for every other status error and for the
catch-all. The reason arrives as a bare non-JSON line on stdout (`Error code: 401 - {…}`,
`Connection error.`), which the runner already collects and `_failure_reason` already prefers. This
is the first backend here that needs no error-prose regex at all — contrast claude's `API Error: …`
and goose's `Ran into this error: …`, both of which are narrated as assistant text.

**The CLI reports no served model anywhere**, so every kimi row is substitution-checked from the
relay (`_relay_served_model`), the same path goose, cline and qwen use. Measured: a live turn's
upstream SSE carried `"model":"openai/gpt-5.4-nano"`, which `_served_model_in` matches. Separately,
kimi does not rewrite the id it is given — the value reaches the provider verbatim, and its only
alias machinery raises `KeyError` on a miss rather than substituting, so the gemini `resolveModel`
class of silent substitution is absent.

**`reasoning_effort: null` is on every kimi request and Vercel's AI Gateway answers it with HTTP
400** ("Invalid option: expected one of \"none\"|\"minimal\"|…", reproduced twice in one live turn).
Without the relay dropping that key, every kimi turn on Vercel fails before it begins. The drop is
in `_normalize_openai_chat_body`, so it applies to any backend that sends the same shape.

**An unreachable MCP server KILLS the turn on this backend** — `Unknown error: Failed to connect
MCP servers: {…}` and exit 1, verified live against a dead server — it does not degrade. That is
the opposite of goose (warns on stderr, continues) and of hermes (disables HTTP MCP with a log
line), and it means the visibility UHP §4.1 asks for is satisfied loudly here, at the cost of a
flaky third-party server taking every turn with it. The matrix probes the server once before a run
and skips the MCP half when it is unreachable, so the custom-harness dimension is unaffected; a
user-configured server that dies mid-session is the real exposure.

**A resumed session that is gone is silent.** `--session <unknown-id>` does not error: kimi mints a
session with that id and answers from an empty history, with no stdout line and no change of exit
code. `_resume_lost`'s kimi arm therefore asks the store — `sessions/<md5(work_dir)>/<id>/context.jsonl`,
kimi's own predicate — rather than reading argv, where the id is present either way.

**Tool policy is real but path-keyed.** `exclude_tools` matches tool PATHS
(`kimi_cli.tools.shell:Shell`), not the names the model sees; a bare name is a silent no-op.
Measured in one probe: excluding `kimi_cli.tools.web:FetchURL` removed it from the tools array,
while excluding `Shell` did not. `tool_enforcement: "hard"` is honest only because
`runner/server.py`'s `_KIMI_TOOL_PATHS` translates, and a gateway test pins the catalog's ids equal
to that table's keys.

**`SearchWeb` and `ReadMediaFile` are not offered.** Both ship in kimi's default agent and both
raise `SkipThisTool` unless a Moonshot search key / a vision-capable model is configured, so
neither is ever constructed on this deployment.

**Token usage is absent from the stream**, not merely named differently: `JsonPrinter` drops every
`StatusUpdate`. kimi's result events carry `usage: {}` until `_relay_usage` lands, which is the
agreed division of work — no harness PR builds its own usage pipeline.

**The Vercel column, measured 2026-09-16 (candidate built from this branch, kimi 1.50.0).**
46 ids, five scenarios each: **229 of 230 scenarios passed**, every turn served by the connection
under test — no foreign connection on any pair.

The single failure is `gemini-2.5-flash-lite`'s artifact turn, with the provider's own words: "The
API returned an empty response". It is **deterministic through this product** (three independent
runs on two different builds, same id, same scenario, same sentence) and takes ~175s, which is kimi
retrying the empty response until `max_retries_per_step` is exhausted rather than one slow call.

What it is NOT, each eliminated by measurement rather than reasoning:
- not the request shape — the same conversation replayed by hand against the same provider answers
  correctly, non-streaming and streaming, with one tool and with the full fifteen, and with a
  system prompt padded to the size kimi sends;
- not the `reasoning_effort` repair, which is applied identically on every other id here;
- not a transient — `qwen3.7-max` failed the same scenario in the previous run with "Upstream stream
  ended before terminal chunk" and PASSED here, so that one was the flake this is not.

What could not be reproduced outside the product: replaying the exact four-step sequence
(first, follow-up, switch to the partner model, artifact) through the real kimi binary against the
same provider, with the workspace contract in AGENTS.md, completes all four turns and writes the
file. So the remaining variable is something the gateway path adds that a CLI replay does not.

**The Google column then said what one column could not.** Same harness, same scenarios, 11 ids,
**53 of 55 scenarios passed**, no foreign connection. The two failures are
`gemini-2.5-flash`'s artifact turn — *the same sentence*, "The API returned an empty response" — and
the recycle that followed it with nothing to recall. And `gemini-2.5-flash-lite`, which fails
deterministically on Vercel, **passes all five here**:

| id | Vercel | Google |
|---|---|---|
| `gemini-2.5-flash-lite` | artifact fails, empty response | 5/5 |
| `gemini-2.5-flash` | 5/5 | artifact fails, empty response |

So it is NOT the channel — both show it — and NOT one id, since each channel's healthy member is the
other's casualty. What survives is the shape: **a gemini-2.5-class model returns an empty response on
the artifact turn**, the one that follows a model switch and asks for a file, and which member of the
family trips differs by provider (most likely the actual build behind the same name on each). One
column alone would have supported the wrong conclusion — the Vercel notes above nearly recorded it as
a property of that id on that channel.

Recorded as rows that fail with the provider's reproduced text, which is what the rules ask for.

Vercel's answers carry the aggregator's vendor prefix (`openai/gpt-5.4`, `anthropic/claude-opus-5`,
`alibaba/qwen3.7-max`), which rule 2 counts as the same model.

**Five ids Vercel does not serve at all**, so this column never ran them: `claude-fable-5-1`,
`gemini-3-flash-preview`, `grok-4.20`, `hunyuan-4-preview`, `nemotron-3-super`. They remain in the
catalog because other providers serve them; they are unmeasured HERE, not rejected.

**The four slow ids: the cause was found, and it was ours.** kimi's own default is **1000 steps per
turn** (`config.py` `max_steps_per_turn`, raised from 500 upstream), and `_build_kimi` never passed
the operator's step budget — the gateway's `max_step` reaches the runner as `max_turns` and every
other backend forwards it (claude and goose as `--max-turns`), but this builder dropped it. On a
fast model the default is invisible; on a slow reasoning one, 1000 steps at 10-30s each is three to
eight hours, which is exactly the range that was measured. Now forwarded as
`--max-steps-per-turn`. Reaching the cap is visible on this CLI rather than silent — it raises
`MaxStepsReached`, which arrives as its own stdout line with a non-zero exit — so a truncated turn
reads as truncated, unlike goose, which reports nothing at its cap.

Two hypotheses were tested and rejected before that one: the relay's repair loop is bounded
(`attempt < 2`), and the `reasoning_effort` shape is not the trigger — measured directly against
Vercel with function tools on `gpt-5.6-sol`, `reasoning_effort: null` is a 400 in 0s while both the
key deleted (what the relay does for kimi) and `reasoning_effort: "none"` answer 200 in 1-2s.

**What was measured of those four before the fix**, with the budget still unbounded: What was measured of them, before the exclusion:
`gpt-5.6-sol` and `gpt-5.6-terra` passed all five scenarios but took HOURS each; `gpt-5.6-luna`'s
switch hung 8,754s and then failed; `gpt-5.5`'s switch hung 2,200s and its artifact 7,418s. The
mechanism is not established. The cline and qwen catalog entries already record that the gpt-5.6
line answers 400 through aggregator chat/completions when the request carries function tools, which
`_set_reasoning_effort_none` repairs per (route, model) — but on those backends that is a FAST
error, and here it is an hours-long wait, which is not the same shape. Whether this is kimi's or the
channel's is an open question: aider and openhands have no data on those four ids at all.

**The custom-harness dimension passes, and deepwiki works here.** All claims on the kimi row:
the skill and the tool policy were stored and came back on a read, the bundle reached the agent (the
answer carried the token that exists only inside the script), the script ran (`stamp.txt` among the
turn's produced files), and the declared MCP server was stored and called — `read_wiki_structure`,
against `https://mcp.deepwiki.com/mcp`, which needed no override. Worth recording because goose
cannot handshake with deepwiki and its row needs `MCP_URL=https://mcp.context7.com/mcp`; kimi's does
not.

**But `disabled_tool_unused` passes VACUOUSLY on this row, as it does on aider, qwen, gemini and
cline.** The dimension switches off the fixed id `WebSearch`, and kimi's catalog does not list it —
deliberately, because it is never constructed without a Moonshot search key. Nothing named the tool
because nothing could, so that claim proves the policy was STORED and nothing about whether it TOOK
EFFECT.

**Measured separately, so the `hard` claim is not left resting on that.** A one-off experiment — the
dimension run once with the disabled tool changed to `Shell`, a tool kimi has and this task needs;
the shared script was NOT changed, and this is a recommendation rather than a diff:

| | tools the turn used |
|---|---|
| Shell allowed | `ReadFile`, `Shell` |
| Shell disabled | `ReadFile`, `ReadFile`, `WriteFile` |

Shell is absent, and the agent reached the same result another way. The policy really withholds, so
`tool_enforcement: "hard"` on this base is measured rather than asserted.

**That experiment also exposed something about claim 4 that is the dimension's, not kimi's.** With
Shell disabled the agent could execute nothing, yet `script_ran` still passed and `stamp.txt` still
appeared: the agent read SKILL.md, read the script, and wrote the file itself. "The script actually
ran" is judged by the file being among the produced files, and an agent that can read the script can
produce that file without running it. Same shape as the vacuous pass above — a gap between the
judge and the thing it means to prove — and harder to notice, since nothing about the row looks
wrong. Two suggestions, both the maintainer's call: let the dimension name the tool it disables
(a base that has no `WebSearch` could disable one it has), and make the script write something the
agent cannot predict from reading it.

**Known open question: `max_context_size`.** kimi requires one per model and plans compaction
against it; the catalog carries no per-id window, so `KIMI_CONTEXT_WINDOW` holds one value for all
ids, exactly as `CODEX_CONTEXT_WINDOW` does for codex. Being wrong changes WHEN the agent compacts,
never whether it answers: too large lets a thread overflow the real window (the provider then
errors), too small compacts early and wastes tokens.

## The aider backend (Aider 0.86.2) — behaviour measured before any column ran

Everything in THIS section was measured against the pinned 0.86.2 — its source, and a stub that
answers as a provider would, at no API cost — before a single paid turn. The google column has since
run; its results and what they overturned are a section of their own below.
`docs/support-matrix.md` is rendered from the results file and is untouched.

**aider is driven IN PROCESS, and that is a correctness requirement rather than a preference.** It
has no machine-readable output mode, and its stdout carries the model's prose and aider's own
diagnostics on one channel. A stub was made to return model prose whose second line began
`litellm.AuthenticationError:`; on stdout it was byte-identical to a real 401 on the same stream,
same exit code 0, no colour under `--no-pretty`. No anchored regex separates those, so a
text-parsing normaliser would report ordinary answers as provider failures. In process they are
never mixed: failures reach `io.tool_error`, prose reaches `io.assistant_output`, and
`coder.usage_report` is None exactly when no completion came back. `runner/aider_driver.py` uses
aider's own entry point, `main(..., return_coder=True)` — the one its GUI uses (`gui.py:71`) and its
tests cover. Upstream supports NO python API: its scripting page says the python scripting API "is
not officially supported or documented, and could change in future releases without providing
backwards compatibility". Hence the exact pin and the install-time symbol checks.

**Upstream refuses shell commands under `--yes-always` by design, and HarnessRouter approves them
through a policy gate.** State this plainly to anyone who knows aider, because they will assume the
opposite. `confirm_ask` returns `"n"` for the one call site that sets `explicit_yes_required`
(`handle_shell_commands`) — so out of the box a skill's bundled script can be read but never run.
The driver wraps that single gate: it receives the exact command the model proposed, refuses it if
the harness disabled the matching tool (with the policy as the reason, which is what the reader
sees), and otherwise approves it to run in the workspace under the session's uid. The model chooses
the command; the harness never injects one. Measured both ways: with `Shell` disabled the proposed
command is refused and the file it would have written does not appear; with it enabled the script
runs and its output is reported.

**MCP reaches aider through a bridge, because aider has no MCP client at all** — zero source hits
for MCP across the whole tree. The bridge (`runner/aider_mcp_bridge.py`) is built on the official MCP
Python SDK (`mcp`, MIT), installed into aider's own venv, and exposed to the model as `hr-mcp`: the
declared servers are listed by NAME in the context aider reads — so the model cannot invent an
endpoint — and the gate recognises `hr-mcp call <server> <tool>` and records it under the MCP tool's
own name. `mcp_called` is therefore measured from a command that actually ran.

f/mcptools was the first choice and is not usable here: it is a Go program that publishes **no
binaries on any release** (checked every release through v0.7.1 — all have zero assets), so it would
have meant adding a Go toolchain to a `python:3.12-slim` image for one command. The official SDK is
also the more defensible component — the protocol's own reference implementation rather than a third
party's wrapper around it.

Measured live against public servers, at no cost: `hr-mcp tools context7` lists both of its tools
with their schemas (exit 0); a correct `call` returns the server's content (exit 0); a call with the
wrong parameters relays the server's own validation error and **exits 1**, so the agent sees a failed
command rather than an answer-shaped one; an unknown server name exits 2 and names the ones that
exist. **deepwiki works through this bridge** — worth recording because goose cannot handshake with
it, so aider's custom-harness row needs no `MCP_URL` override.

Two field-name traps were found by running it rather than reading about it: the 2.2.0 SDK is
snake_case (`input_schema`, `structured_content`, `is_error`), not the camelCase of older releases,
and a wrong name raised inside anyio's TaskGroup and surfaced as the useless sentence "unhandled
errors in a TaskGroup (1 sub-exception)". The bridge unwraps ExceptionGroups so an MCP failure
reaches the agent as a real message.

**The edit format is pinned to `diff`, and it is load-bearing.** Shell commands are extracted in
`editblock_coder.get_edits()`; `wholefile`, `udiff` and `patch` never populate `shell_commands`, so
a ```bash block is inert on those formats and a skill's script could not run at all.

**Shell output is fed back through aider's own reflection path, and this is the measured
experiment the backend was asked to run.** Stock aider stashes the output in `cur_messages` for the
NEXT user message and sets no reflection (`base_coder.py:1609-1614`), unlike its lint and test
paths — so within one turn the model never sees what its command printed, and cannot report a token
the script produced. Setting `reflected_message` gives aider the same in-turn loop every other
backend has. Measured against the stub: reflection on, two provider round trips and the answer
carries the script's output; reflection off, one round trip and the answer is the ```bash block
itself. One hazard found and fixed while measuring it: `init_before_message()` empties
`shell_commands` once per TURN, not per reflection, so the first version re-ran every executed
command on each pass — one command ran four times, four round trips instead of two, side effects
repeated. The driver now clears the list after running it, pinned by a test.

The cost ceiling is aider's own: `Coder.max_reflections` is 3, so a model that keeps proposing the
same command after seeing its output costs at most three extra round trips and three executions,
not an unbounded loop. Observed with a stub that answers identically every time.

**Model ids are sent with an `openai/` prefix.** A bare id is resolved against aider's own
`MODEL_ALIASES` (`models.py:87-111`), which rewrites 21 of them including `gemini-2.5-pro`, an id
this catalog also serves. The prefix skips that table, so the id the picker offered is the id the
provider is asked for. The same class of silent substitution that pruned the gemini catalog.

**Streaming is off (`--no-stream`), and that is about billing honesty.** With streaming, aider
reports `usage_present: false` and substitutes a **tiktoken estimate** through the same field names
(587 against a true 595, measured live) because it never sends `stream_options`. Its own numbers are
not used either way: result events carry `usage: {}` and `_relay_usage` will supply them.

**Nothing of aider's lands in the workspace root.** Its chat and input histories are relocated under
`.harness/aider/`, and the repo-map tags cache — `Path(root)/".aider.tags.cache.v4"`, with no CLI
flag — is moved there by setting `RepoMap.TAGS_CACHE_DIR` in the driver, which only an in-process
driver can do. Verified after a full turn: the workspace root held `.git`, `.harness` and the task's
own files, nothing else. Auto-commits are off so aider never interleaves commits with the
checkpoint repo's, and `--no-gitignore` stops it appending to the `.gitignore` the runner owns.

**The install path is verified in a real image.** `docker build` of this tree,
then a container with `HR_BACKENDS=aider`: the install completed, the container reported
`backends available: aider`, and `aider.__version__` inside it is 0.86.2 with the MCP SDK importable
beside it. **681 MB measured there** (`du -sh /data/agent-tools/aider-venv`) — a first estimate of
735 MB came from a macOS venv — and the MCP bridge was run from inside the image against deepwiki,
listing its tools with exit 0. The PR proposed keeping aider out of the default `HR_BACKENDS` for its size; the review put it in (2026-09-18), because the console offers every base the catalogue lists and a listed base that is not installed fails on its first task. Note the Python floor: 0.86.2
declares `Requires-Python <3.13,>=3.10`, and on an interpreter outside that range pip does not fail
— it silently offers an older aider (0.82.3 on 3.9) with none of the behaviour above. The installer
asserts the imported version to turn that into a hard failure. Installing the MCP SDK into the same
venv bumps `idna` past aider's own `idna==3.11` pin; aider was re-verified running end to end
afterwards, so that pin is advisory here — but it is why the SDK goes in aider's venv and not the
runner's, where the same class of bump breaks FastAPI outright.

**Known limitation: no tool loop, so the custom-harness dimension's disabled tool is not aider's.**
The request body's keys are exactly `['messages','model','temperature']` — no `tools`, no
`functions`. aider's withholdable surface is the shell command and the URL scrape, which the gate
really does refuse; but `custom-harness.mjs` disables the fixed id `WebSearch`, which matches
nothing on this harness — so `disabled_tool_unused` would pass VACUOUSLY, as it already does for
qwen, gemini and cline, whose catalogs carry no `WebSearch` either. The enforcement here is real and
demonstrable; what is missing is a dimension that disables a tool the base under test actually
lists.


## aider × Google, the first paid column (2026-09-16)

11 pairs, **51 ok / 4 FAIL**, every pair served by `integration:google` on every turn and every
`served_model` matching the id the pair asked for. The two questions the column was run to answer
both came back:

**`--timeout` holds.** `gemini-2.5-flash-lite` had burned 27,360s in a single vercel scenario before
the flag was pinned. Here the whole pair ran green, its slowest scenario 25.69s. No scenario in the
column waited without a bound.

**The artifact failure is not a gpt-5 phenomenon.** One turned up here too — but for a different
reason than the gpt-5 family's, so the earlier `diff`-edit-format hypothesis explains neither.

### Three symptoms, one cause: the reminder is glued to the user's message

`base_coder.py:1322`. When `main_model.reminder == "user"` — the default (`models.py:125`), and what
every id in this catalog resolves to — aider appends its whole `system_reminder` to the FINAL user
message rather than sending it as its own turn. Reproduced against the real package: the matrix's
39-character `Reply with exactly: M2-<id>` becomes a **3,080-character** user message whose last
3,041 characters are SEARCH/REPLACE rules and shell-command examples. The instruction is 1.3% of
what the model is handed, and it is at the top.

Three of the four failures are that message, failing in three different ways:

  * **FOLLOWUP, `gemini-3.5-flash` and `gemini-3-flash-preview`** — the model continues the tail
    instead of obeying the head. The answer ends `...suggest the command to install them. Etc.`,
    byte-identical to the end of the appended block. 31.8s and 37.9s against 7.6s for a healthy
    followup, because it is reciting 3 KB.
  * **ARTIFACT, `gemini-3.5-flash-lite`** — "Please add hello-aider.txt to the chat so I can propose
    the edit", about a file that does not exist yet. The system prompt says `You can create new
    files without asking!` and then, in the next sentence, that edits to files not in the chat
    `*MUST*` be refused until the user adds them. The weaker model took the second sentence.
  * **An unhandled crash, `gemini-3-flash-preview`** — `The turn failed: list index out of range`,
    seen once in six re-runs. Asked to echo one word, the model emitted a headerless SEARCH/REPLACE
    block whose only content was that same word. Fed to the real parser, aider reads the word as the
    FILENAME: `[('M1-gemini-3-flash-preview', '', 'M1-gemini-3-flash-preview\n')]`. Then
    `strip_quoted_wrapping` (`editblock_coder.py:349-354`) drops the one line because it endswith
    the filename and immediately indexes `res[0]` on the now-empty list. **An upstream defect in
    0.86.2**, reproducible in three lines with no model and no network; this product only supplies
    the conditions.

`--no-suggest-shell-commands` would remove the shell half of that block, and is NOT taken: shell
commands are how a skill's script runs at all, which is the custom-harness dimension.

### The fourth failure was not repaired, and the A/B says so

`RECYCLE gemini-3-flash-preview FAIL 399.14s`, reported as
`Input tokens: ~45,356 of 0 -- possibly exhausted context window!`. The `0` is real and is a defect
of ours — see `_write_model_metadata` — but it is a defect of REPORTING. Six re-runs of that one
pair, three with the metadata file and three on the committed driver, put every recycle in the same
band regardless: **19.9s / 209.0s with it, 210.8s / 222.8s / 229.2s without**, all passing. The
399.1s failure is the tail of that distribution, not something the metadata fix cured. Recorded here
because the first re-run passed at 19.9s and reading that one sample as a fix would have been wrong.

`gemini-3-flash-preview` is the unstable id on this harness: across six full runs it produced one
upstream crash, four followup failures, and recycles ranging over an order of magnitude.

### aider's custom-harness row: the capability is real, the row never passed (2026-09-18)

Measured on the vercel integration, nine runs of `custom-harness.mjs` with `BASES=aider`:

```
skill_reached  9/9      script_ran  2/9      mcp_called  2/9      row ok  0/9
```

The harness itself is stored correctly every time — `skill_stored`, `tool_disabled_stored` and
`mcp_stored` are all true — and the MCP capability demonstrably WORKS. A harness declaring only the
deepwiki server, asked to read a wiki structure, produced this record:

```
tools: ["Shell", "deepwiki.read_wiki_structure"]
assistant:
  ```bash
  hr-mcp tools deepwiki
  ```
  ```bash
  hr-mcp call deepwiki read_wiki_structure --params '{"repoName":"modelcontextprotocol/servers"}'
  ```
```

The model listed the server's tools and then called one, against the real public server, through
`runner/aider_mcp_bridge.py`. The block that tells it how is in the workspace's AGENTS.md on every
turn, verified on disk under `## MCP servers` with the declared server named.

**What fails is not the wiring but the choice, and both halves of this row turn on the same choice.**
Every other backend gives a skill's script and an MCP tool their own call channel: the model emits a
tool call and the runtime executes it. aider has no such channel at all — a "tool call" here is the
model writing a ```bash block into its prose, which `editblock_coder.get_edits()` then extracts. So
`script_ran` and `mcp_called` are not two independent measurements; they are one question asked
twice: did the model choose to emit a fenced bash block this turn. Against a prompt built to make it
emit SEARCH/REPLACE blocks — and with 3,041 characters of those rules appended to the user's own
message (see the reminder finding above) — it chose to twice out of nine, and never twice in the
same run.

The first turn shows the pull plainly: asked for the skill's build stamp, the model usually reads the
token out of `stamp.py` and answers with it instead of running the script. That answer is correct,
and it is not what the row measures.

Recorded as measured: the row is **FAIL**, and the reason is aider's, not the bridge's. Anyone
re-running it should expect a different mix of the same two flips rather than a stable result.

## aider × Vercel, the full column (2026-09-18)

52 pairs, **235 ok / 21 FAIL**. Every pair `connection=integration:vercel` on every turn, no
foreign connection anywhere. The log flags `SUBSTITUTED=` on 51 of 52 pairs and NONE of them is
one: `run.mjs:177` compares the served id to the asked id as raw strings, and this channel stamps a
vendor prefix (`openai/gpt-5.6-sol`, `nvidia/nemotron-3-super-120b-a12b`). Judged by the comparator
that owns the question, `scripts/support-matrix/samemodel.py`, **0 of the 51 is a real
substitution**. The google column flagged none because that channel stamps the bare id. Read the
flag as raw pre-canonicalisation data, not as a finding.

```
first     ok=51  FAIL=1
followup  ok=49  FAIL=2
switch    ok=51  FAIL=0
artifact  ok=47  FAIL=4
recycle   ok=37  FAIL=14      <- two thirds of every failure in the column
```

### The `--timeout` pin holds on the channel that produced the hangs

The 3,621s / 6,040s / 16,071s / 27,360s scenarios were all measured HERE. The slowest scenario in
this column is 477s (`gemini-3-flash-preview`'s recycle) and nothing waited without a bound.

### The artifact failure is a small-model behaviour, not a gpt-5 one

Four artifact failures: `gpt-5.4-mini`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`,
`grok-4.20`. Three of the four are the mini/lite variant of a family whose full-size sibling passed,
across three vendors and (with the google column's `gemini-3.5-flash-lite`) two providers. The gpt-5
family passed 5 of 6. **The earlier hypothesis -- that this was the gpt-5 family meeting the `diff`
edit format -- is dead.** What these models do is obey the system prompt's `*MUST* tell the user
their full path names and ask them to *add the files to the chat*` for a file that does not exist
yet, ignoring the sentence above it that says new files need no permission.

### Recycle, by family

```
claude   8/8    deepseek 3/3   kimi 2/2   glm 2/2   step 1/1
gemini  10/11   grok     4/5   qwen  4/5
muse     2/4
gpt-5    1/6
nemotron 0/2    mistral  0/1   hunyuan 0/1
```

### aider puts a user message the user never sent at the head of every conversation

`editblock_prompts.py:31`. aider teaches the SEARCH/REPLACE format by example, and with
`examples_as_sys_msg` false -- the default (`models.py:126`), and what every id in this catalog
resolves to, because aider's per-model overrides match legacy substrings (`gpt-4.1`, `3.5-sonnet`,
`deepseek`+`v3`, `qwq`+`32b`) that no 2026 id contains -- those examples are injected as REAL
`user`/`assistant` turns. The first user message in the model's context is therefore
`Change get_factorial() to use math.factorial`.

The recycle scenario asks what word was requested `in my very first message of this task`. In the
column five models answered out of that synthetic turn: `math.factorial` (gpt-5.6-terra, gpt-5.6-luna),
`Change` (gpt-5.4, muse-glimmer-30b), and qwen3.8-max quoting it back as a sentence. They are not
wrong about what they were shown. This is not only a test artefact: any feature that asks a model
about its own history inherits a turn attributed to a user who never wrote it.

### Setting `examples_as_sys_msg` closes that trap and changes nothing (2026-09-18)

aider supports the fix: `--model-settings-file` (`main.py:757`) with `examples_as_sys_msg: true`
folds the examples into the system prompt under `# Example conversations:` instead of sending them
as turns. Measured on the six ids that had failed recycle, one variable changed and every other
ModelSettings field left at the default already in effect, against a CONTROL of the same six pairs
on the same image in the same hour:

```
              control (as shipped)      with examples_as_sys_msg
              ok=25  FAIL=5             ok=25  FAIL=5
```

Identical. The mechanism is real -- under the setting NO answer cites the example text, while the
control still produced `math.factorial` -- but closing it does not buy a single scenario: the models
that stopped answering `math.factorial` answered `HELLO`, or `Ok`, or "the first message of this
task did not ask me to reply with any specific word" instead. **Not taken.** Fitting the harness's
prompt to this matrix without a measurement that supports it is the trade this repo does not make.

### The column's recycle number is a single sample, and it is not stable

The same six pairs re-run on the same image failed recycle three times, where the column failed them
five times and voided a sixth. `gpt-5.2`'s `FIRST FAIL 171.62s -- The LLM did not conform to the
edit format`, which voided its whole pair in the column, did not reproduce at all: both arms ran it
4/5. Quote `recycle ok=37/51` as what this run measured, never as aider's rate.

### The model's reasoning was being rendered as its answer (fixed)

`grok-4.20` is the only id in the column whose provider returns a separate reasoning field, and its
cards carried the chain of thought: `...(wait, no, that is not how it works) The instruction is to
tell which files need changes and stop. So my response should be:... ► ANSWER hello-aider.txt`. That
`► ANSWER` is aider's own terminal banner (`reasoning_tags.py:11`), reaching a browser transcript.
The driver hooked `io.assistant_output`, which `base_coder.py:1882-1890` feeds the DISPLAY string --
reasoning prepended to the answer -- rather than `partial_response_content`, which carries the answer
alone. Fixed in `_install`; re-measured on a rebuilt image, the same cards now read
`AIDER No files in the repo need to be changed for this request.` with no banner. **Both verdicts
stayed FAIL**: the artifact row is judged on the file card, and the recall answer never contained
the word either way. The leak reached the transcript only -- aider writes `partial_response_content`
to the chat history (`base_coder.py:1828`), so no later turn was fed the reasoning.

## aider, the review of PR #211 on hr-test (2026-09-18)

Reviewed on a derived image of the PR branch merged with main, on the 0.18.4 base, with every
built-in skill installed as a fresh volume installs them. What the review changed, each with the
measurement that made it a defect, and then what the columns say on the image that carries the
changes.

**Every turn carried the whole skill library.** The PR passed every file of every installed
skill bundle through `--read` on every turn: on hr-test that is 27 files and 264 KB for the three
built-in bundles, two licences and a PNG among them, and `Reply with exactly: AIDER-SMOKE-OK` cost
**45,030 input tokens**. The same turn on the review image costs 3,039. The agent doc alone
reaches the model; a skill is read when a task calls for it, as on every base without a loader.

**The agent doc is the system message.** `--read` delivered it as a USER message ("Here are some
READ ONLY files, provided for your reference") ahead of the conversation, and aider's few-shot
examples for the edit format went in as user/assistant turns ahead of that. So the first user
message the model saw was never the user's: asked what the first message of the task asked for,
the gpt-5 family answered `Change` (aider's `Change get_factorial()` example) and, once the
examples were folded away, `reference` (the read-only preamble). The doc now rides aider's own
`Model.system_prompt_prefix` hook, ahead of the system message aider composes, and the examples
fold into that message through aider's own `examples_as_sys_msg`, set on the object because a
settings-file entry replaces every other setting of the model with class defaults. The PR's A/B
of that switch (above) was run with the history cap still in place, which is why it could not
move a verdict: the first message was being summarised away regardless.

**The conversation was summarised away after four short turns.** aider keeps at most
`min(max(window/16, 1k), 8k)` tokens of chat history, and 1k for an id litellm has no record of,
which is most of this catalog; past that it summarises the history with a model call on every
turn. Measured in the console matrix: after first, follow-up, switch and artifact, the recycle
question could not be answered on ids that had answered the follow-up one turn earlier. The
driver passes `--max-chat-history-tokens` as half the window when the record says it, else
96,000, which fits the catalog's smallest windows; the other bases keep the whole transcript the
same way.

**The model was never told how this workspace works.** aider's prompt tells it the USER adds
files and may run the commands it suggests. Here the driver does both, and a model that was not
told behaved as aider's prompt says: asked to use a skill it guessed the token instead of reading
SKILL.md; asked for an MCP tool it wrote "I'm constrained here to only return SEARCH/REPLACE
blocks"; asked for a streamable-HTTP tool it invented the result. The doc now carries a block
that says what happens between messages, names each installed SKILL.md as a `cat` the model can
run on any turn (aider's own file-mention route adds only files git already tracks, and on a
session's first turn the skill files are not committed yet, measured), and forbids reporting
output that was never received. Plugin matrix before: 1 of 4 columns (skills guessed, stdio
refused, http invented). After, run twice: **4 of 4 both times**. `custom-harness.mjs`, which the
PR ran nine times without a pass: **3 of 3**, `skill_reached`, `script_ran`, `mcp_called` all
true each time.

**The operator's step budget never reached the driver.** The builder accepted `max_turns` and
`turn()` did not pass it; the test that claimed to pin the dispatch pinned the builder. Fixed and
pinned on the dispatch.

**Usage was empty on every kimi and aider turn.** Both normalisers wrote `usage: {}` on the
promise that "the relay stamps it", and nothing in this tree did: the console showed no tokens for
either base. The relay now reads the provider's usage off the bytes as they pass, the way it
already reads the served model (OpenAI `prompt_tokens` netted to fresh input by the cached part,
Anthropic's counters as they are, Gemini's `usageMetadata`, streamed or not), sums it over the
turn's calls and stamps it on a result event that arrived empty. Measured after: aider
`input 3,039 / output 9`, then `input 2,710 / cache_read 2,176` on the follow-up; kimi
`input 7,487 / cache_read 13,312`.

**`temperature` refused by a provider.** aider sends `temperature: 0` for every id its settings do
not know; `claude-fable-5-1` on TokenRouter answered "`temperature` is deprecated for this model"
and the turn died after 171 s of retries. No other base sets one; aider's own `use_temperature`
switch leaves it out.

**Edit markup rendered as the answer.** A file-writing task's reply card read
`hello.py ```python <<<<<<< SEARCH ======= print("aider") >>>>>>> REPLACE ``` `. That is aider's
wire format for an edit; the driver strips it from the text (the text event AND the result event,
since the gateway stores the latter as the answer) and reports each edited file as an `Edit` card,
as file edits render on every other base.

**Two claims removed.** The catalog listed `Web Fetch` as a withholdable tool while the runner
always ran aider with `--no-detect-urls`, so the switch withheld something that never happened;
the web is reached through a shell command like everything else, under the one gate. And the
install was opt-in "per the 300 MB line", but the console offers every base the gateway's
catalogue lists, so on a default install Aider was a base that failed on its first task; it is in
the default `HR_BACKENDS` (fresh volume: healthy after 147 s against 114 s without it, 687 MB),
and an operator who does not want it leaves it out.

**Smaller:** a failure reason no longer names aider's in-chat commands (`- Use /drop …`); the two
bridge tests that imported the aider venv's SDK (mcp 2.x, httpx2) under the runner's 1.x
environment, which is why the PR's runner job was red, stub those modules by name; aider's own
app icon is in the harness list.

**Verified unchanged:** the hard tool policy (Shell withheld: the model's `cat
/proc/sys/kernel/random/boot_id` was refused at the gate with the policy as its result and no
UUID in the answer; allowed: the UUID came back); cancel (a 60-function module task cancelled
mid-flight: `runner_killed: true`, no driver process left, session `cancelled`); the console at
1440 and 390 (settings page, task page with the edit card and the file card, no markup, no
overflow, no page errors).

**The columns on the review image (`pr211-a9e7a51`, hr-test, 2026-09-18).** Console scenario
matrix, 50 ids × first / follow-up / switch / artifact / recycle, connections as the console
routes them (TokenRouter for most, Vercel 6, Anthropic 2, Custom OpenAI 2, OpenRouter 1, Azure 1):

```
first 50/50   follow-up 47/50   switch 50/50   artifact 47/50   recycle 47/50   = 241/250
```

The nine: `claude-opus-5` three times, the provider's `finish_reason content_filter` on the
scenario's own words (the same id tripped the same way in the kimi review); `gemini-3.5-flash` and
`gemini-3.6-flash` on the follow-up, the reminder tail continued (upstream's, above);
`gpt-5.2` and `llama-3.3-70b` on the recycle recall, answering with a later word; `gpt-5.4` and
`gpt-5.4-mini` on the artifact after three literal-reply turns, answering `DONE` with no edit
block (the same prompt on a fresh session writes the file; measured twice). Two of these were
re-run three times and flipped both ways, so read them as what this run measured.

A pattern worth knowing about the base itself: aider answers with ONE response per turn, and a
reflection follows only when aider has something to feed back (a command's output, a file it
added). "Create the file, then run wc on it and tell me the count" therefore often ends after
the edit: the model writes the block, aider applies it, and no second pass happens unless the
model also proposed the command in the same response. Every other base loops on tool calls.

Conformance, run alone against an aider harness on gpt-5.4: 75/75 at full. A provider refusal
(a custom connection with a bogus key): the task fails with "The API provider is not able to
authenticate you. Check your API key." and nothing of aider's around it. Fresh volume on the final
image: healthy after 150 s, 687 MB venv, `aider-ready` reads 0.86.2.

**Richard's first manual task, and what it found (2026-09-19, `pr211-a30c77d`).** "improve the ppt
style" on a one-slide deck, gemini-3.8-flash: the model named `hello.pptx`, aider added it to the
chat, the UTF-8 read failed ("Use --encoding to set the unicode encoding"), the file was dropped
and added again on the next mention, an error and a reflection each time. Twelve commands and
fifteen minutes later the deck WAS restyled through officecli and `hello.md` edited, and the turn
read FAILED with the decode error, because any error had failed a turn; and the transcript showed
prose inside a code block, because each response's text was joined to the next without a break
and a closing fence ran into the next sentence. Fixed on the branch: a binary file is refused at
aider's own "Add file to the chat?" prompt (aider's ignore_mentions then holds it), and since
nobody is at that prompt to say what to do instead, the answer goes back as a reflection and the
turn goes on; the turn fails when an error was the LAST thing that happened; each response ends
with a paragraph break and its shell blocks render as cards only. Re-run of the same two turns:
the deck restyled in 53 s, DONE, five tool cards, no markup. The doc also says now that each line
of a bash block runs on its own (a multi-line `python3 -c "…"` ran line by line) and that binary
files are worked on with commands.

**After the first real tasks on the hosted service (2026-09-19, folded into open source).** "build a
1 pager ppt about SFO" on aider. A reply that announces work and does none ("I'll create a one-page
PowerPoint deck about SFO and save it in the workspace.", gpt-5.5, zero commands) ends the turn,
because aider reflects only on something to feed back; the driver now says "go ahead" once, only when
the reply reads as an announcement. A turn whose last response was an edit block and nothing else
gets the same note as one that ended on a command. The normaliser used to fail any turn that
recorded an error at any point: gpt-5.4 wrote an edit aider refused (a leading slash, "not in the
subpath"), was told, wrote it again, aider applied it, and the record said "did not conform to the
edit format"; the driver's verdict stands now. gpt-5.5 built the deck with officecli and then put
its closing answer inside a SEARCH/REPLACE block for the .pptx; aider read the binary as text and
died on its own None content; an edit block aimed at a binary is refused at aider's prompt like an
add, with the reflection that says to report instead. The stripper takes the file name inside the
fence, which gpt-5.5 writes. The notes say to name files by workspace-relative path.

What the base is, measured five times on that task: the gpt-5 family builds the deck through
officecli in about two runs of five (gpt-5.5, 29 s and 74 s, six commands) and otherwise writes
an outline .md and stops, treating the file as the deliverable under aider's coding prompt;
nemotron-3-super and claude-sonnet-4.6 built it every time on the hosted service (457 s and 428 s).
Not a harness defect: the prompt is aider's, the choice is the model's, and the record says which.



## The openhands backend: OpenHands V1 through its agent-server (2026-09-18/19)

PyPI `openhands` is OpenHands/openhands-cli, whose README opens with "This project is no longer
actively maintained". The product its vendor does maintain is the SDK's **agent-server**
(`openhands-agent-server` 1.49.2, MIT), a REST + WebSocket service, and that is what this base
drives. One server process per turn — cold start 3.3-4.1 s measured — so the one-process-per-turn
contract every other backend keeps is kept here too, and a conversation survives in the workspace
rather than in the process.

**The surface, as measured.**

- A turn is: start the server on a free port, `POST /api/conversations` (created once; a second
  create with a different tool list leaves the persisted agent as it was), then send the message
  and read the event WebSocket to EOF.
- The agent is FROZEN at the conversation's first creation, so the conversation id is a uuid5 over
  the tool policy AND the declared MCP servers: a changed policy has to be a different conversation
  or the change is silently dropped.
- The credential is never persisted: `base_state.json` holds the whole LLM spec with
  `api_key: None`, so the key rides the environment and a resumed turn gets it from there.
- The model id is sent with an `openai/` prefix. Without an explicit provider litellm infers one
  from the base url, and a relay url inferred as Vercel produced
  `Missing credentials … VERCEL_AI_GATEWAY_API_KEY` on a resumed turn.
- The answer can arrive as a `FinishAction` rather than a trailing assistant message; disabling a
  tool is enforced by OMISSION from the spec, not by a refusal.

**TMUX_TMPDIR, the defect that cost the most.** The terminal tool runs commands in tmux, and the
server defaults `TMUX_TMPDIR` to a directory inside the working directory. A workspace here is
`/data/workspaces/hsess<32 hex>`, so the socket landed at
`/data/workspaces/hsess…/tmp/openhands-agent-server-<pid>/tmux-<uid>/openhands` — 106 characters
against the 108-byte `sun_path` limit — and tmux answered `error connecting to … (File name too
long)`. The agent then retried the tool it could not start, which turned a 10 s turn into 235 s and
then into 4,000 s. Four wrong guesses came first (a tmux session leak, process exhaustion, a
Chromium preload, a blocking relay); none of them survived contact with the server's own output,
which at that point was going to `DEVNULL`. The server's stdout now goes to a FILE under
`.harness/`, and that single change is what ended the investigation. A driver run from a short cwd
never sees any of this.

**Columns.**

- **vercel** (49 of the 50 catalog ids runnable): 239 of 245 scenarios. qwen3.8-27b missed a recall
  after a switch and after a recycle (the model, not the wiring). mistral-medium-3.5 failed its
  other four scenarios; Vercel names its own fix in the refusal (`Assistant message must have
  either content`), the relay now stringifies assistant content for that route, and the re-run
  passed five of five. The section below rules out the litellm defect as a second cause.
- **google** (the eight gemini ids): 40 of 40 after the litellm pin below; 29 of 40 before it.
- **custom-harness**: openhands carries its own skill, script and tool policy, and reaches a
  declared MCP server (`https://mcp.deepwiki.com/mcp`, 19 s, all six claims).

## openhands: a follow-up dies of a field that two dependencies disagree about (2026-09-19)

Every gemini follow-up on the google column failed after 145-212 s with `the turn failed: the turn
ended error` and no reason of any kind. Eleven scenarios across five models, and never a FIRST
turn. The cause is neither the provider nor the request shape:

```
AttributeError: 'PromptTokensDetailsWrapper' object has no attribute 'cache_creation_tokens'
  openhands/sdk/llm/utils/telemetry.py:259, _cache_buckets
```

From litellm 1.95.0, `PromptTokensDetailsWrapper.__setattr__` mirrors an assignment between
`cache_write_tokens` and `cache_creation_tokens`, which puts BOTH names into `model_fields_set`,
and litellm then drops the unset attribute from `__dict__` as a construction-cost optimisation. The
SDK's telemetry uses `"cache_creation_tokens" in details.model_fields_set` as its existence test.
Each side is self-consistent; together they are not. Three lines reproduce it with no agent, no
provider and no network:

```
>>> PromptTokensDetailsWrapper(cached_tokens=123).model_fields_set
{'cache_creation_tokens', 'cached_tokens', 'cache_write_tokens'}
>>> hasattr(_, 'cache_creation_tokens')
False
```

`_cache_buckets` returns `(0, 0)` before reading anything when `prompt_tokens_details` is absent,
so the defect needs a response that carries it — which is why this reads as "follow-ups fail and
first turns do not". Vercel is immune for a reason worth recording: it reports
`cache_creation_input_tokens` on every response, litellm therefore SETS `cache_creation_tokens`
rather than leaving it None, the attribute genuinely exists, and the existence test agrees with it.
Measured through litellm 1.101.0 on the real streaming path — vercel/mistral-medium-3.5 and
vercel/gpt-5.4 both `hasattr=True`, both ok.

**Not yet pinned: what makes Google report the field.** Four shapes asked of Google directly (a
short prompt, a 4,008-token prefix sent twice, tools declared, and a follow-up carrying a tool
result) all came back with no `prompt_tokens_details` at all, so none of them reproduces the crash
from outside. The production turns that do crash go through the relay and carry the SDK's own large
system prompt; the necessary condition is established and the sufficient one is not. This does not
touch the fix, which was measured end to end.

1.49.2 is the newest SDK, so there is nothing to upgrade to; the SDK asks only for
`litellm>=1.93.0`, so the fix is to hold litellm below 1.95.0. The entrypoint pins 1.94.3 as a
fourth pin in the same single pip invocation and then asserts the DEFECT IS ABSENT rather than
asserting the version, so a future bump fails the image instead of failing every follow-up on a
provider that reports prompt caching.

**THE DEFECT IS INTERMITTENT, and that shapes what the evidence can carry.** Google populates
`prompt_tokens_details` only sometimes; a turn that does not get it passes on the broken pin too.
Captured from inside `_cache_buckets` on litellm 1.101.0, on a 7,410-token follow-up that passed:
`Usage(prompt_tokens=7410, …, prompt_tokens_details=None)`. In one five-scenario run on the broken
pin, follow-up, switch and artifact failed while recycle passed. So the single-model A/B below is
supporting evidence rather than proof — the column is the measurement that carries the claim:
**29 of 40 before the pin, 40 of 40 after**, same eight ids, same image otherwise.

**The A/B.** Same command, same image, same model (gemini-3-flash-preview), litellm the only
difference:

| scenario | litellm 1.101.0 | litellm 1.94.3 |
| --- | --- | --- |
| first | ok 10.71 s | ok 10.69 s |
| follow-up | **FAIL 145.01 s** | ok 10.70 s |
| switch | ok 34.80 s | ok 10.71 s |
| artifact | **FAIL 175.02 s** | ok 13.76 s |
| recycle | **FAIL 147.59 s** | ok 10.69 s |

**Why the record said nothing.** `event_service._run_and_publish` publishes an error event only
for an exception that is NOT a `ConversationRunError`, on the assumption that `run()/arun()` already
emitted its own — and an exception raised out of arun's error handling is exactly the case where
nobody did. The status flips to error, the WebSocket carries nothing else, and tenacity retries
five times with an 8→64 s backoff, which is the whole of the 145-212 s. The sentence existed only
in the server's log. The driver now falls back to that log's tail when a turn fails with no reason
on the wire, and sets `COLUMNS` so the log is wide enough for the sentence to survive in one piece.

**mistral-medium-3.5 on Vercel was a different defect, and this settles it.** Its four failures
share the shape and the duration band (144-208 s, never a first turn) of the litellm defect above,
which is reason enough to doubt the first attribution — a re-run passing five of five cannot rule
out a probabilistic cache-hit crash. It is ruled out by the probe instead: asked through litellm
1.101.0 on the real streaming path, vercel/mistral-medium-3.5 answers `hasattr=True`, so that turn
never reaches the missing attribute. The four failures were the assistant-content refusal Vercel
named in its own bytes, as first recorded.

## openhands, the review of PR #215 on hr-test (2026-09-19)

Reviewed on a derived image of the PR branch merged with main (0.19.0 plus #214 and #216), tmux
added to the image, every built-in skill installed as a fresh volume installs them. What the
review changed, each with the measurement that made it a defect.

**No served model and no usage on any turn.** The relay token lived only in the driver's argv;
`_relay_served_model` and `_relay_usage` find the turn's route by the placeholder bearer in the
turn's environment, so the record carried neither. The token now rides the environment as well.

**A conversation died after every deploy.** The agent's persisted spec carried the relay's
`base_url`, and the loopback relay binds a fresh port on every runner start: the first turn after
a restart dialled the old port (`Cannot connect to host 127.0.0.1:39265`). The base url rides the
environment like the key; measured across a swap, the follow-up answered from the history.

**A model switch was ignored.** The agent is frozen at the conversation's creation, its LLM spec
included, and the server offers no way to change it: a turn that asked for claude-sonnet-5 was
served gpt-5.4, the record naming the first and the relay the second. The turn's model is written
into the persisted state before the server loads the conversation, the same door the conversation
id uses; measured gpt-5.4, then claude-sonnet-5, then gpt-5.4 again, each served as asked. The
three muse switch failures in the first column (270-310 s of retries against a route that could
not serve the persisted id) were this.

**A disabled MCP tool was called.** The built-ins are withheld by omission from the spec; an MCP
tool is loaded from the server at agent start and was called all the same (`probe_sse` disabled,
its token in the answer). The SDK's own `filter_tools_regex` runs over every tool name after the
MCP tools are added; the disabled names are excluded there and are part of the conversation's
identity. Re-probed, the tool was not offered; the model then wrote its own SSE client in the
shell and dialled the public probe, which is the shell reaching a URL, the same reach `curl` has
on every base. The policy holds at the tool surface, as it does on kimi (Shell withheld, the
boot id read with the file tool) and here (Edit withheld, the file written with printf).

**A cancelled turn left its command running.** The terminal tool runs commands in tmux, whose
server daemonises with setsid, so the runner's process-group kill left the tmux server and the
agent's `sleep 240` alive and every turn's `/tmp/oh<port>` directory behind it (84 after an
hour). Every process a turn starts now carries `HR_TURN_ID` in its environment and the runner
sweeps what still carries it after the group kill, tmux directory included; the driver removes
its own on the normal path. And the directory is the turn's own (mkdtemp), not the port's: ports
are reused and turns run as different uids, and a directory left by an earlier turn answered
`Permission denied` on the next.

**litellm's own `max_tokens`.** For an id its registry knows as Anthropic's, the provider-native
`claude-haiku-4-5-20251001` a custom Anthropic connection resolves to, litellm sends both
`max_tokens` and `max_completion_tokens` (64,000 each) and Anthropic's OpenAI-compatible endpoint
refuses the pair. Captured with a sink inside the venv and against the live endpoint; every
other id carries the second field alone and every provider on the matrix takes it. The relay
drops the first on this backend's route, the kimi precedent.

**Retries in seconds.** The SDK's defaults (5 retries, 8 to 64 s waits) made a provider that
answered the same 503 every time a 270-310 s turn before the reason was reported. Two retries a
few seconds apart now, persisted with the agent.

**The driver's own ceiling.** An 1800 s deadline of the driver's own sat below the harness's
timeout (7200 s by default); it is the runner's global ceiling now, and a server that dies
mid-turn is noticed by asking the process rather than waiting it out.

**Cards.** The tool cards carried the SDK's registry names (`terminal`, `file_editor`,
`task_tracker`) and the raw observation record as JSON; they carry the catalog's names (Shell,
Edit, Todo), the action's arguments as the input and the observation's text as the output.

**In the default set**, for the reason aider is; the icon is OpenHands' own (MIT).

**The columns on the review image (`cand-a14761d`, hr-test, 2026-09-19).** Console scenario matrix,
50 ids × first / follow-up / switch / artifact / recycle, connections as the console routes them
(TokenRouter 38, Vercel 6, Anthropic 2, Custom OpenAI 2, Azure 1, OpenRouter 1):

```
first 50/50   follow-up 50/50   switch 49/50   artifact 49/50   recycle 49/50   = 247/250
```

The three: `gpt-5.4` on the switch to gpt-5.6-sol, TokenRouter's multi-account gpt-5 route
refusing a replayed encrypted reasoning item (the sentence the gateway already has for it);
`llama-3.3-70b` on the artifact after a switch, the server marking the conversation stuck once in
two runs (by hand it wrote the file in 24 s); `qwen3.8-27b` on the recycle recall, the model. The
first pass, on the branch as submitted plus the early fixes, was 237/246, and every miss between
the two was one of the defects above: the persisted model on the three muse switches, litellm's
`max_tokens` pair on claude-haiku through the Anthropic connection.

Plugin matrix 4/4 twice; `custom-harness.mjs` 4 of 5 (the miss the same encrypted-reasoning
refusal); conformance 75/75 alone against an openhands harness on gpt-5.4; fresh volume with
fourteen backends: the OpenHands venv installs in about a minute beside aider's. Cancel: nothing
of the turn survives the sweep. The agent doc reaches the model as context: asked, with no tool
allowed, for a secret word in the harness's instructions and the installed skills, it answered
both from the doc.
