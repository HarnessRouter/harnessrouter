# Support matrix notes, self-hosted instance, 2026-09-06

The tables in [support-matrix.md](support-matrix.md) were produced by `scripts/support-matrix` against the self-hosted test instance (a single container, owner trust, the runner beside the gateway), one provider at a time, three workers with one harness each (one worker for the free-tier key), five scenarios per harness x model pair: first turn, follow-up, model switch inside the column, artifact, recycle. A row that failed was re-run once and the first try is kept in its notes; nothing was inherited from the hosted run.

## Versions

The run started on v0.13.5 and finished on v0.13.13. Every release between them came out of a finding below and was deployed on the instance behind a live-turn gate before the next column: 0.13.5 (local blob store lists by prefix), 0.13.6 (read caches, the word "refused" is not a key refusal), 0.13.7 (a Codex history kept whole under the same account, finished turns release their process handle), 0.13.8 (a Google key can be saved, qwen drops gpt-5.3-codex, a task reopened by URL keeps its model, the broker resends a Google request without the refused field, a self-hosted sandbox reaches the broker on loopback), 0.13.9 (opencode's base carries /v1), 0.13.10 (the relay's base carries its API version), 0.13.11 (the claude CLI strips it), 0.13.12 (a checkpoint that cannot be restored aborts the turn), 0.13.13 (owner trust normalises an Azure base like the broker).

## Claude Sonnet 5.5 (2026-09-30)

Added in 0.26.18 beside Sonnet 5 on every base that offers Sonnet 5, with every provider naming
its own id (Anthropic `claude-sonnet-5-5`, Bedrock `us.anthropic.claude-sonnet-5-5`, OpenRouter,
Vercel, TokenRouter and llmtr `anthropic/claude-sonnet-5.5`, all read off the vendors' lists that
day). Measured on hr-test (0.26.18-rc.1) through the console, on the instance's TokenRouter
connection, which is where the effective model map sends it:

- 13 of 13 bases pass all five scenarios (first turn, follow-up, model switch, artifact, recycle):
  claude-code, cline, dsh, hermes, opencode, pi, qwen, aider, kimi, openhands, cheetahclaws, goose,
  omp. Claude Code runs it on the CLI the image pins (2.1.280); no bump.
- Family tour on claude-code: one deck conversation handed from the base's default model into
  Sonnet 5.5 and on to Sonnet 5 completed both turns with the deck produced; the other families of
  the default list are not offered on Claude Code and were skipped as such.
- A finding about the switch partner, not about Sonnet 5.5: with the column's partner forced to
  `claude-opus-5`, omp's switch turn on TokenRouter failed with the provider's own sentence
  ("Claude Code 2.1.257 does not support this model; version 2.1.280 or newer is required"), the
  same channel limit Opus 5.5 met on 2026-09-22. Retested with Sonnet 5 as the partner, omp passes
  all five. Sonnet 5.5 itself served on every base.
- TokenRouter reports the served id in its dashed form (`claude-sonnet-5-5`) for a request of
  `claude-sonnet-5.5`; the runner marks that as a substitution by string, and it is the same model.

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

## systemone: the System One Harness as the fifteenth base (2026-09-19)

Not a coding CLI. The base runs the open-source System One Harness
(github.com/HarnessRouter/SystemOneHarness, Apache-2.0, pinned at v0.4.0 in `docker/entrypoint.sh`)
over TypeSafe's Jev, a decision model: it answers typed questions (a choice, a yes/no probability,
a score) with probabilities in one pass and writes no text. Every step is one request carrying
the next action as a choice over what the environment offers right now, every parameter of every
offered action, and a goal check; the harness gates the answer by the action's risk and executes.
The turn process is `runner/systemone_driver.py`; its events are claude's stream-json, so the
normaliser is the passthrough.

### Measured, 2026-09-19

- **Through the runner's own relay.** `_build_systemone` registers the route at the provider's API
  ROOT (`https://openrouter.ai/api`), because OpenRouter serves decisions at `/api/alpha/decisions`
  and a POST to `/api/v1/alpha/decisions` is a 404. The driver posts to `<relay>/v1/alpha/decisions`.
  One live turn on the built-in order desk: six actions, `success`, 1.44 s wall; the relay's taps
  read the served model `typesafe/jev-1.13-20260917` and usage 6304 in / 1410 out off the answer,
  and the driver's own result event said the same. Rule 2 of harness-verification.md holds the
  way it holds for cline and qwen: the base rides the relay.
- **The environment is the harness's MCP server** (the first one configured), its tools compiled to
  actions at the start of each turn; a tool that needs free text is named in the trace as not
  offered. With no server, the built-in order desk, so the base answers before anything is
  configured. `disabledTools` withholds an action from the question itself (hard, by omission).
- **`incomplete` is a runner status now.** A loop that stops because the model asked for help or a
  destructive action never cleared its confidence bar is neither a failure nor a step cap. The
  driver's result carries `subtype: incomplete` and a `reason`; `_status_from_result` returns
  `incomplete`, the poll body carries `reason`, and the gateway reports it as the task's
  `incomplete_details.reason` without retrying another connection. Pinned by
  `runner/tests/test_systemone_backend.py` and `gateway/tests/test_systemone_catalog.py`.
- **Continuation.** The desk's state and the loop's steps persist under
  `.harness/systemone/<session>/` in the workspace; a resumed turn carries on from where the last
  one stopped and the model sees the earlier steps as history (a two-step first turn followed by a
  continuation redid none of its picks).
- **What the five matrix scenarios mean here.** First turn, follow-up, switch and recycle apply as
  written; the artifact scenario's "create a file" prompt does not, because the desk produces one
  artifact of its own (`manifest.json`, on ship). The base is verified by its own loop rather than
  the coding prompts: the harness package's 35 tests, its UHP core conformance (40 of 40) and its
  benchmark (15 of 15 goals on the live model) are the record, in that repository.

### The models

Jev under the ids its two providers serve, and nothing across them. OpenRouter: `jev-1.13`
(`typesafe/jev-1.13`, resolving to typesafe/jev-1.13-20260917) and `jev-latest`
(`~typesafe/jev-latest`), added to OpenRouter's vendor table after the shared copy so no other
aggregator inherits an id it cannot serve. TypeSafe AI, the maker's own API (provider `typesafe`,
base `https://api.typesafe.ai/v1`, decisions at `/v1/systemone`, a key checked at `/v1/models`,
401 for a bad one): `jev-latest` (served as jev-1.13.0) and `jev-preview`; `jev-1.13` is "Unknown
model" there (measured 2026-09-20). The base's default is `jev-latest`, the one id both serve, so a
harness made on either connection runs. No chat model is listed on this base: the loop asks typed
questions a text model cannot answer.

**TypeSafe direct, measured 2026-09-20** on a derived image of 37a9159 with a fresh volume and a
native key: the console's integrations route stores the connection with its base filled in and the
key masked; `/v1/bases` shows jev-latest and jev-preview available and jev-1.13 unavailable without
an OpenRouter connection; an order-desk turn on jev-preview completes in 6 actions (6316 in / 1408
out), and on jev-latest the same; a turn on jev-1.13 with only a TypeSafe connection answers 400
`invalid_input`, "no provider configured for backend systemone". The harness alone (`s1 run` with
TYPESAFE_API_KEY) completes the order desk in 5 actions, 0.86 s wall.
### The dual loop (2026-09-21)

An outer harness calibrates an inner one through the platform's own API (docs/dual-loop.md in the
System One Harness repository, Appendix B). On this tree:

- **A harness that drives another one.** `calibrates` on a harness names the one harness it may
  drive. Every turn of such a harness is handed `HR_API_URL`, `HR_INNER_HARNESS` and
  `HR_CALIBRATION_TOKEN`, a credential signed like the broker's, scoped to that harness and good for
  the turn's wall-clock cap plus a margin. With it the turn starts that harness's runs, reads their
  sessions, turns and files, reads and publishes that harness's package (`PUT
  /v1/harnesses/{id}/plugin`, or `PUT /v1/harnesses/{id}` with `plugins`) and relaunches its kit;
  every other route answers 403, a session of another harness is not found, and the credential
  cannot change `calibrates`. Never an org key, never a provider key.
- **The package's configuration.** The driver reads `config.yaml` at the root of the package the
  environment's server runs from (the root is the `PLUGIN_ROOT` the runner's launcher exports): its
  instructions and gate replace the space's, its encoder settings shape the state, its version rides
  the trace, and the server gets the same file as `SYSTEMONE_CONFIG`. `trace.json` lands in the
  session workspace. A request's `metadata.systemone.script` selects a scripted provider, a probe.
- **The handoff.** A run that ends on a refusal or an escalation carries the branch on the result
  event, the status body and the response's `incomplete_details` beside its reason; the console says
  where it handed off and on what judgment. Null on every other ending.

Measured on hr-test, 2026-09-21, on a derived image of 851e4d1 with the harness at v0.4.0: a
Calibrator on the pi base read the Mario harness by name, listed its sessions, was refused on keys
and on the harness list, and started an inner run on it; a Mario run on the package's config v1
wrote `trace.json` with `config_version: 1` and 61 archived frames; a probe with a four-action
script ran on `script/s1` and finished. The calibration itself (baseline, one change, validation)
runs on a Calibrator on the claude base with the calibrate package.

## The cheetahclaws backend: CheetahClaws 3.5.88 (2026-09-24)

CheetahClaws (SAIL-Research-Lab/cheetahclaws, PyPI `cheetahclaws`, Apache-2.0), a Python
reimplementation of the Claude Code agent loop, as the sixteenth base (#229). The turn process is
`runner/cheetahclaws_driver.py` inside a pinned venv: the CLI's own agent loop
(`cheetahclaws.agent.run`, the generator its REPL and its headless bridge runner consume) is
driven in process and every event is re-emitted as it is yielded, `__hr_init` first and
`__hr_result` last, normalised by `_cheetahclaws_to_claude`.

### Behaviour measured before the column ran (3.5.88, against a stub and the live instance)

- **No event stream, and the session file is not one.** `cheetahclaws -p` prints the final answer
  and ANSI tool cards; `session_latest.json` is rewritten by `autosave_session` once per USER turn,
  after `run_query` returns, never between messages. Tailing it would give a silent turn and then
  everything at once. In process the loop's own events stream: conformance S-09 passed with "events
  spread over 5.1s", and the console renders text deltas and tool cards as they happen.
- **Provider failures are prose and exit 0.** Against a stub, `cheetahclaws -p` printed
  `[Failed — APIConnectionError: Connection error.. Hint: …]` (unreachable),
  `[Failed — AuthenticationError: Error code: 401 - {…}. Hint: Check your API key: /config …]`
  (bad key) and `[Retry 1/3 after 6s — rate_limit: …]` ×3 then `[Failed — RateLimitError: Error
  code: 429 …]`, exit 0 each time. The driver's verdict is the history's shape instead (the loop
  appends an assistant message only for a completion that came back); the `[Failed — …]` sentence is
  kept as the reason, minus a hint that names a slash command. Recorded, and pinned, in
  `runner/tests/fixtures/cheetahclaws/`. Live: a key the gateway refuses failed the turn with
  `Failed — BadRequestError: Error code: 400 - {… 'No connected db.' …}` (the gateway's own answer
  to an unknown key), 27 s.
- **A dead endpoint hung the turn.** The CLI builds its OpenAI client with the SDK's 600 s timeout
  and two retries of its own under the loop's three: a turn aimed at an address the instance's
  firewall drops was still `running` at 600 s with nothing in its record. The driver now gives every
  client a 300 s read timeout (`HR_CHEETAHCLAWS_TIMEOUT`, aider's budget) and no SDK retries, so the
  loop's ladder is the only one: the same turn failed at 581 s with `Failed — APIConnectionError:
  Connection error.`, and an endpoint that accepts and never answers fails in 23 s at a 2 s timeout
  (`Failed — APITimeoutError: Request timed out.`, pinned by a test).
- **Resume.** No resume flag: `-p` always starts from an empty state, and continuing is the REPL's
  `/resume`. The driver loads the session file (the CLI's own `_migrate_session`) when it names the
  requested id and writes it back with the CLI's own `autosave_session`, the id held fixed per
  session. `_resume_lost` asks the same file. Recycle through the API: two turns, the sandbox
  recycled (hydrated from the checkpoint), the session file identical, the recall turn answered
  `M1-tools-pool`.
- **Instructions and skills.** The CLI reads `CLAUDE.md` only (walking up from the cwd, plus
  `~/.claude/CLAUDE.md`); there is no AGENTS.md discovery in the package, so with both present only
  CLAUDE.md is loaded. It drops the whole file when a line matches its prompt-injection scan; the
  driver says so in the record. Skills land in the project-level `.cheetahclaws/skills/`, which the
  loader reads first; `.cheetahclaws/` is CLI state (its `tasks.json` tracker too) and never a
  produced file, and the tracker is not checkpointed.
- **Tool policy is hard, measured with a control.** The driver sets the CLI's `disabled_tools`: the
  tool leaves the schema the provider receives (stub capture) and a call to it is refused at
  execution. Live, with Bash, Write, Edit, NotebookEdit and Agent withheld, the model still called
  Bash and Write by name; each came back `Error: tool 'Bash' is not enabled by the 'full' tool
  profile for this turn.`, no file was written, and the answer said it had no write tool. The same
  request with nothing withheld wrote the file through Write. AskUserQuestion (it blocks on a
  terminal nobody is at), ReadEmail/SendEmail (no mailbox is configured) and the tools of optional
  extras the bare install lacks (WebBrowse, ReadPDF, ReadSpreadsheet, ReadImage) are withheld on
  every turn and not offered as toggles.
- **Served model and usage come from the relay's taps.** The session file carries gross prompt
  tokens with no cache split and no model. The CLI's `custom/` client streams without
  `stream_options`, so the relay asks for the usage chunk on this route (`stream_usage`, pinned
  against an upstream that sends usage only when asked); a live turn's Response carried
  `input_tokens` 9118 / `output_tokens` 31 off the relay, and conformance T-03 read the served
  model the same way.
- **MCP** connects in a background thread at import in `-p`, racing the first model call; the
  driver waits for it, and a server that does not connect becomes `mcp_unavailable`.

### Versions and the column

The column in `docs/support-matrix.md` is `cheetahclaws-tokenrouter`, measured on hr-test
(harnessrouter/harnessrouter:0.25.0, the release that carries this base; one container, the default
`HR_BACKENDS`, the live data volume) on 2026-09-26, after the author's own measurements on a lab
gateway (kept in the PR, #264). CheetahClaws 3.5.88 was installed by the entrypoint at boot (wheel
digest verified, import check passed). The instance's own connections served the turns: TokenRouter
for gpt-5.4 and claude-sonnet-5, and gpt-5.4-mini through the Custom OpenAI Chat connection with
TokenRouter behind the switch, as `fill-connection.py` stamped them.

- **Conformance** (`uhp-conformance` 2026.9.12.post2 from this tree, `--class full`, a harness on
  the base with `--model gpt-5.4`): 75/75, CONFORMANT (full).
- **Console column** (`run.mjs`, `HARNESSES=cheetahclaws`, three models): 3 pairs, 15 of 15
  scenario runs passed, first turn to recycle. Two rows are served as the provider's dated alias of
  the id asked for (`gpt-5.4-2026-03-05`, `gpt-5.4-mini-2026-03-17`), which the table notes and
  rule 2 does not count against the pair.
- **Custom harness** (`custom-harness.mjs`, `BASES=cheetahclaws`, the public MCP probe reachable
  from hr-test): the stamp skill read, its script run from the workspace, `stamp.txt` produced,
  WebSearch withheld and unused, MCP reached, 28 s.
- **Plugin matrix** (`plugins/run-matrix.py --bases cheetahclaws --mode all`): skills 1/1, stdio
  MCP 1/1, SSE 1/1 through the CLI's own client. Streamable HTTP 0/1 on 0.25.0: the CLI's own
  streamable-HTTP client (`mcp_client/client.py`, `HttpTransport`) is answered 400 on `initialize`
  by the probe, the same server its SSE end and the runner's bridge reach, so the turn ran without
  the server and said so. Since 0.25.1 a streamable-HTTP server reaches this base through the
  runner's stdio bridge (`_BRIDGED_TRANSPORTS`, the mechanism codex, dsh and goose use for SSE),
  the way every other base reaches it; the CLI's client keeps SSE and stdio. Measured on 0.25.1
  (hr-test, the same probe): skills 1/1, stdio 1/1, SSE 1/1, streamable HTTP 1/1
  (`PROBE-HTTP-ef8e44614954`, 11.1 s).
- **The family tour** (`family-tour.mjs`, 0.25.2, on Richard's own five-turn conversation, `SID=`
  continued, one model per family, three runs on 2026-09-26): 12 of 14 families passed, first
  edit to recycle of the same deck. gpt-5.4-mini 13 s, claude-sonnet-5 81 s, gemini-3.5-flash 20 s,
  grok-4.5 16 s, deepseek-v4-flash 155 s (served as v4.1-flash), kimi-k3 40 s, qwen3.8-flash 20 s,
  glm-5.3-flash 46 s, mistral-medium-3.5 20 s, step-3.7-flash 49 s, hunyuan-4-preview 33 s,
  nemotron-3.5-lightning 33 s. Two families fail on this base:
  - **muse-spark** (1.1 twice, 1.3 once): the CLI compacts the conversation for the model's smaller
    context, and after the compaction the model runs the one edit into a loop of ninety-odd tool
    calls (`ls`, `cat hello-world.md`, `TaskList`, re-deciding the original "convert the md to a
    deck" from the summary, "Auto-fanout" sub-summaries of every result), never finishes, and is
    stopped at the tour's ten-minute cap. No two calls are identical, so the CLI's loop guard does
    not fire. The line is excluded from the base's catalog with that note.
  - **llama-3.3-70b**: refused in 7 s, three times (the third on 0.25.3, where the relay logs the
    body the CLI cuts off): `400 "This model only supports single tool-calls at once!"` from
    CoreWeave, the provider serving the model. The conversation holds one assistant message with
    two tool calls (gpt-5.4-mini's Glob and Grep, issued together on the tour's first edit), and
    that endpoint refuses every later request that replays it. llama alone never writes such a
    message, so a fresh harness of the base completes in 11 s, as on pi. The model stays offered
    with this note; whether the relay should rewrite a parallel-call message into consecutive
    single-call ones for such a provider, or the catalog should drop the model on bases whose
    CLIs call tools in parallel, is Richard's call.
  - kimi-k3 and qwen3.8-flash failed the second run's rows without a defect: the edits repeated
    ones earlier families had made and both rightly wrote nothing. The tour stamps every edit
    since, and both pass.
- **In the browser** (the console on hr-test, the system harness, gpt-5.4): a task that writes a
  file and runs a command completed in 15 s with the file card and the byte count in the answer.
- **Not measured here:** the other provider columns (OpenRouter, Vercel, the hosted HarnessRouter
  API) beyond the three pairs above, so `_MODEL_CATALOG["cheetahclaws"]` stays offered, not
  measured, for the rest of its list; and a benchmark column.


## The loopback relay answers when the provider does not (2026-09-29)

The first family tour on the minimax base passed 7 of 14 families in one conversation: every family from kimi-k3
on was recorded `not settled in 600s, stopped (cancelled)` with **no served model, no tool call and
no reason** — except `glm-5.3-flash`, which passed in 12 s in the middle of the collapse. The
obvious reading was the blanket 200k context window (above): a history too large for a model's real
window. **It was not**, and two measurements say so. The conversation at its largest was 219 KB of
messages plus a 12 KB system prompt and 27 KB of tool schemas — about 65k tokens, under the real
window of every failing model — and the same families pass on that same session today, with a
longer history (kimi-k3, qwen3.8-flash and minimax-m3 each re-run by hand, all completed in
seconds). A conversation too long fails monotonically; this did not.

**It was the loopback relay answering nothing when the provider answered nothing**, in two ways,
both in `_forward`:

- The upstream call caught only `urllib.error.HTTPError`. A refused connection, one dropped
  mid-request, or a provider gone silent raised out of the handler; `ThreadingHTTPServer` printed a
  traceback and closed the client socket **with no HTTP response at all**. The instance's log holds
  ten of those (`http.client.RemoteDisconnected: Remote end closed connection without response`),
  two inside the tour's failing window.
- The relay's own wait was 600 s — the same as the cap above it — so a provider that accepted a
  request and then went silent could never be REPORTED by the relay: the cap always fired first and
  the turn was recorded as cancelled with nothing in it. That is the shape of six of the seven.

Both are fixed in `runner/server.py`: transport failures now answer **502** (refused or dropped) or
**504** (timed out) with `{"error":{"code":"upstream_unavailable",…}}` carrying the provider's own
failure; a bare drop before any byte is retried once and a timeout is never retried (the provider
may be generating, and a second request is a second bill); a stream that stops mid-answer carries
the reason as its own error event and is left unterminated, and a body that stops arriving is a 502
or 504, so neither reads as a complete answer; and `HR_RELAY_UPSTREAM_TIMEOUT_S` sets the wait.
Its default stays the 600 s this relay always waited (a reasoning model answering a non-streaming
call is silent for minutes), which is far under the runner's own turn cap; an instance with a
shorter cap of its own, such as one this suite measures with its 600 s per turn, runs with 180. Pinned by `runner/tests/test_relay_upstream_failure.py`, which
drives the real handler over a real socket against an upstream that drops, drops-then-answers,
refuses, and goes silent — the defect was in what reaches the client, not in parsing.

**Proven by re-running the tour twice** on a build of this branch, with the nine families around the
collapse (`kimi-k3, qwen3.8-flash, glm-5.3-flash, mistral-medium-3.5, step-3.7-flash,
hunyuan-4-preview, nemotron-3.5-lightning, minimax-m3, gpt-5.4-mini`): **8 of 9 both times, no turn
anywhere near the cap** — every previously-hanging family completed in 9-52 s with its served model
and the deck. The two non-passes were not hangs and were not the same family twice:

- run 1, `hunyuan-4-preview`: the turn **completed** with `tencent/hy4-preview` and `tour.pptx` — the
  tour read the record at the instant it said `done`, the gateway's own word for completed
  (`_RESP_STATUS_MAP`), which is not in the script's RUNNING list, so it settled early on a
  half-written record. A shared-script bug, below.
- run 2, `nemotron-3.5-lightning`: a real, reported failure in 113 s — `Runtime completed without a
  final assistant response`, and the CLI's transcript gives the mechanism: `stopReason: "length"`.
  The model hit the output cap with no usable final message. That is the blanket
  `max_completion_tokens: 16384` above, now with a named victim, and it is the same id the matrix
  found unstable on its own (run1 FIRST failed, run2 RECYCLE failed, run3 clean 5/5).

And the fixed path was exercised end to end on a real instance rather than only in tests: with the
connection's base URL pointed at a port nothing listens on, a turn fails in 22 s carrying
`502 the provider did not answer: URLError: <urlopen error [Errno 111] Connection refused>`.

## agentzero: the first matrix run, and the two defects it found (2026-09-28)

A local instance built from the branch (vercel, the 7 cross-harness ids) ran the matrix TWICE: 29/35
then 30/35. Every one of the 11 failures across 70 scenario executions was ARTIFACT or RECYCLE;
first / followup / switch were 70 for 70. The failing SCENARIOS were stable while the failing MODELS
drifted, which is the shape of a defect in the backend rather than model weakness — and both were.
custom-harness passed, the plugin matrix was 4/4, samemodel.py clean, connection integration:vercel
throughout.

**ARTIFACT — "no file card (files: none)" while the card said "Edited a file".** The driver has to
import Agent Zero from the per-workspace base, and it left the process cwd there. Agent Zero resolves
its OWN paths against that base, but a tool that takes a path FROM THE MODEL does not: text_editor
writes with a bare `open(path)` (plugins/_text_editor/helpers/file_ops.write_file), so
"hello-agentzero.txt" landed in `.harness/agentzero/base/` — inside the prefix /produced excludes.
The models that failed were the ones that passed a RELATIVE path; a model that passed an absolute one,
or that used the terminal (whose cwd Agent Zero sets itself), passed. Hence "intermittent". The turn
now runs with the workspace as its cwd. A/B against a scripted provider, same relative write: before,
the file is in the base and the workspace holds nothing; after, it is in the workspace root.

**RECYCLE — the recall answered the injected greeting.** Agent Zero opens every fresh conversation
with a FABRICATED exchange: agent_init adds a user message "Hello!"
(prompts/fw.initial_user_message.md) and an assistant greeting, so its web UI never starts empty. So
the transcript's first user message was one the person never sent, and "what exact word did I ask you
to reply with in my very first message" was answered — correctly, for that transcript — with "Hello",
"Hello!", "none" or "you did not ask me to reply with any specific word". THE HISTORY WAS NEVER LOST:
reproduced on a local runner with a real checkpoint + hydrate, the recall failed while `ctx_window`
(Agent Zero's own record of the prompt it sent) held both M1 and M2. The greeting is now overridden
through the framework's own mechanism — extension classes merge by FILE NAME, first occurrence
winning, and usr/extensions comes before the bundled ones — by a no-op `_10_initial_message.py`.
A pin bump that renames the bundled file silently restores the greeting, so the name is pinned by a
test.

**Proof of the fixes**, on the three models that failed reliably (claude-haiku-4.5, which failed
recycle in both runs; gemini-3.5-flash-lite and grok-4.20, which failed artifact in both): the five
scenarios through a local runner, with a real checkpoint and a real /hydrate that wipes the workspace
and restores it — 3 sequences each, **9 of 9 sequences and 45 of 45 scenarios green**, every artifact
written through text_editor (the path that used to deliver nothing) and every recall answering its own
M1 word.

**The disabled tool, measured against a REAL tool.** `disabled_tool_unused` passes vacuously on this
base as on the others (the shared dimension disables the fixed id `WebSearch`, which no new harness
has — a maintainer item, not patched around here). Measured directly instead, with
`code_execution_tool` disabled and a scripted provider that calls it anyway, at all three tool
sources:
- **directly**: the tool's whole section leaves the system prompt (23,140 -> 19,116 chars,
  `code_execution_tool` x7 -> x0), the call is refused before it executes, and no file is written.
  `input` goes with it (`### input:` present with the shell enabled, absent with it disabled) —
  it types into the same terminal.
- **through `parallel`**: the job is refused (`status: error`) and no file is written; enabled, the
  same job writes it.
- **through a subordinate** (`call_subordinate`, profile `developer`): refused, no file; enabled, the
  subordinate writes it. Asked of Agent Zero's own resolver, the policy the driver writes to
  usr/plugins/_tool_access/config.json reaches all six bundled profiles.
One honest limit, live on claude-haiku-4.5 with the shell disabled: it delegated to three subordinate
profiles and then ANSWERED "Darwin" anyway. Nothing ran — the gate above is what the deterministic
arms prove — the model fabricated the output. A withheld tool is withheld; it does not stop a model
from claiming its result.

**Cosmetic, fixed in the same pass**: the answer used to name the absolute sandbox path
(`/data/workspaces/hsess…/fib.py`) because the environment prompt gives the workdir absolutely. The
prompt now asks for paths relative to the working directory when the agent names a file to the reader;
on the same fib task the answer became "Created and ran `fib.py` in the workspace". A nudge, not a
guarantee.

## agentzero: the full catalog, and what the 16 failures were (2026-10-01)

The first full-catalog run (all 52 ids, vercel, stopped at 34 pairs after 25 hours) was 154 of 170
scenarios. The two earlier defects did not come back — nothing in the run has the artifact or
recycle shape. The 16 failures were two shapes, and NEITHER is in this backend's own code.

**Shape 2, the hangs (1,732-8,114 s, nine hours of wall clock between them), were the loopback
relay.** gemini-3.5-flash, gemini-3.5-flash-lite, gemini-3.1-pro-preview, grok-4.5, grok-4.20,
grok-build-0.1 and muse-spark-1.3 each lost one turn — several of them trivial ones ("Reply with
exactly: M2-…"). The instance's log says what happened: 16 handler escapes, ten
`urlopen(req, timeout=600)` and six `IncompleteRead` on `resp.read(4096)` — the relay reading an
upstream that stopped mid-stream — and NOT ONE `upstream_unavailable`. That is the defect fixed on
`feat/minimax-harness` in 6c477eb, which is not on main and was not in the build that ran; it is
cherry-picked here (see the relay section above). **Re-run on the fixed relay, all seven ids, the
five scenarios each through a local runner with a real checkpoint and hydrate: 35 of 35, every turn
between 3 and 26 s** — against 1,732-8,114 s for the same ids before. A turn that used to hang now
either completes or fails in seconds with the provider's own words.

**Shape 1 was the provider returning nothing, five times, and the message said so in the harness's
private words.** claude-fable-5-1, claude-opus-5 (twice) and muse-spark-1.2 ended with
`HandledException: Agent stopped after 5 consecutive unusable model responses to prevent further API
charges.` That is Agent Zero's own guard (extensions/python/message_loop_result/_20_empty_response.py):
it fires when a completion comes back with NEITHER content NOR reasoning, five times running. Correct
behaviour — it stops paying — but it names a counter nobody outside the harness can see.

The empty completion has two sources on this channel, and both are now visible instead of silent:

- **A refusal. Vercel spells it `content-filter`; the relay only knew `content_filter`.** Measured
  2026-10-01: `anthropic/claude-fable-5.1` and `anthropic/claude-opus-5` answered a short probe with
  two SSE events, no content, no reasoning and `"finish_reason":"content-filter"`. `_FINISH_RE`
  admitted `[a-z_]` only, so on Vercel the field never matched, `last_finish` stayed empty, and the
  check that turns a refusal into a stated reason — in the runner since the goose column — could
  never fire there. A dead check reports success. The pattern now takes both spellings and
  normalises to one, and a turn that FAILED while the relay saw a content filter reports the
  provider's refusal rather than the harness's sentence (the slot `_failure_reason` already keeps
  for a provider's refusal). End to end against an upstream that declines: the same turn that said
  "Agent stopped after 5 consecutive unusable model responses" now says **"the provider declined the
  request (finish_reason content_filter)"** in 3 s, with the served model and the 10,000 input tokens
  those five calls cost both on the record.
- **A stream that ended with nothing** — the relay defect of shape 2, which leaves the client a
  truncated body and the harness an empty answer. One of the four, muse-spark-1.2's artifact turn
  (799 s), has a relay escape inside its own window.

**Not reproduced on the fixed build, and said plainly:** claude-fable-5.1 ran all five scenarios
green, and claude-opus-5 answered BOTH of its failing payloads — the real system prompt and the real
transcript, replayed raw — with `finish_reason: stop`. So the refusal is something the provider does
some of the time, not a property of these scenarios; the fixes above make the next one readable
rather than preventing it. `max_consecutive_unusable_responses` is deliberately left at upstream's 5:
the same counter also covers the misformat loop, where another try is often what repairs the turn.

Measured cost of this pass, from the gateway's own credits endpoint before and after: **$1.50**.


## The agentzero backend: Agent Zero v2.13 (2026-09-27) — behaviour measured, NO column yet

Agent Zero (agent0ai/agent-zero, MIT) is a framework shipped as a Docker image with a web UI: no CLI,
no headless mode, no PyPI package, no release assets. `runner/agentzero_driver.py` imports it from
the tagged source tree (digest-pinned in `install_agentzero`) and runs one message per turn through
its own `AgentContext.communicate`, the path its `/api_message` endpoint takes. No support-matrix
column has run on this base; the catalog is openhands' list, offered so the matrix can measure it.

Measured on the pinned v2.13 (macOS for the driver, Linux arm64 `python:3.12-slim` for the install):

- **Provider failures are structural.** A wrong key (401) and a dead base url each raised out of the
  loop (`HandledException`), with an `error` log item and no response-tool text; no error prose ever
  reaches the answer, so no prefix regex exists. Through a local runner the wrong-key turn failed in
  6 s with litellm's sentence as the reason.
- **An endpoint that never answers held a turn past 900 s** (Agent Zero sets no provider timeout).
  The driver passes `timeout`/`stream_timeout` 300 s (`HR_AGENTZERO_TIMEOUT`) and collapses three
  nested retry ladders (the OpenAI client's 2, Agent Zero's 2 transient, its `_error_retry` 1) to
  four attempts: at a 5 s timeout, 110 s before the reason became 29 s.
- **The model id reaches the provider unchanged** (loopback recorder): `openai/gpt-6-sol`, `gpt-5.4`,
  `google/gemini-3.1-flash-lite`, `anthropic/claude-sonnet-4.6` each arrived as sent — the openhands
  double-strip (#296) does not happen here. One provider call per trivial turn once the
  always-enabled `_chat_naming` plugin's automatic naming is switched off (it was a second call).
  The system prompt of a one-word turn is about 25.7 KB; relay usage on the first real turn:
  13,425 input tokens.
- **Tool policy is hard**, by Agent Zero's own `_tool_access` plugin (prompt filter + execution gate,
  which `parallel` goes through too). `input` types into the terminal, so it is withheld with
  `code_execution_tool`. A disabled MCP tool rides the server's own `disabled_tools`: withheld,
  asked for anyway, the model answered CANNOT and the token never appeared.
- **Cancel.** The terminal is a pty bash spawned with `start_new_session=True`; a `nohup … &` it
  started outlived a group kill until the driver kept the shell in its own group (A/B at a
  scripted recorder).
- **Not offered, because they cannot run here:** search_engine (SearXNG only its image runs),
  document_query and memory (FAISS, local embeddings/torch), browser, scheduler, notify_user,
  a2a_chat, the A0-connector remote tools. The nodejs runtime of code_execution_tool calls
  `/exe/node_eval.js`, which exists only in upstream's image — a model that picks it gets an error.
- **Install**: 83 s, venv 569 MB + source 69 MB (Linux arm64). Over the 300 MB bar and in the default
  `HR_BACKENDS` all the same — the call aider's review already made (see above): the console offers
  every base the catalogue lists, so a base outside the default install is a base whose first task
  fails, and the operator's switch is `HR_BACKENDS` itself.
- **End to end through a local runner** (Vercel, gemini-3.1-flash-lite, 2026-09-27): a shell call +
  AGENTS.md codeword, a no-tool recall of the first turn, a skill loaded by `skills_tool` whose
  script ran, a turn with the shell withheld; every result carried `model` =
  `google/gemini-3.1-flash-lite` and non-zero relay usage, and neither the key nor the relay token
  was in the workspace or the turn record.

<!-- Carried onto this branch by cherry-picking 6c477eb from feat/minimax-harness: the relay is
shared by every backend on that path, and the agentzero full-catalog run of 2026-09-30 hit the same
defect (ten urlopen timeouts escaping the handler, six truncated chunked reads, no
upstream_unavailable anywhere in the log). The section below is that commit's own write-up; what it
changed for this base is under the agentzero heading further down. -->

## agentzero: the "model switch hangs the turn" report, and what the instance actually shows (2026-10-01)

A family tour on a local instance of this branch was 0 of 13 — the first turn completed in 18.3 s and
every family after it, each a switch to the next family, was `not settled in 600s` with no served
model, no tool call and no error — and a hand-made three-turn repro (two turns on gpt-5.4-mini, then
one on claude-sonnet-5) had its third turn still running at 635 s. Read as "a model switch hangs the
turn".

**On the same instance, same build, same harness, a switch does not hang.** Six shapes, all through
the product API against mx-agentzero, every one complete in seconds:

| what was driven | result |
|---|---|
| trivial turn, same model twice, then a cross-family switch (gpt-5.4-mini -> claude-sonnet-5) | 4.0 / 3.8 / 3.8 s |
| same-FAMILY switch then cross-family (gpt-5.4-mini -> gpt-5.4 -> claude-sonnet-5) | all completed |
| the tour's own first turn (build tour.pptx) then a cross-family switch asking for its first edit | 15.0 s then 16.1 s |
| a turn cancelled mid-flight, then a cross-family switch in the same session | 5.0 s |
| the CONSOLE's own request shape (stream:true, metadata.model + session_id, backend), two switches | 5.1 / 3.8 / 3.7 s |
| a second turn started while another is still in flight in the same session | 3.9 s |

So the question the report asks — any switch, or only a cross-family one — is answered: **neither
hangs**. Whatever stalled those turns is not the model id changing.

**What the hung turns left behind says where they stopped.** The tour workspace's console log — the
file this driver points Agent Zero's own stdout and stderr at — is **0 bytes, with its mtime at the
start of the last hung turn**. The driver got as far as opening that file and then printed nothing:
no framework banner, no init event, no provider call. Import measured from that same workspace, as
that session's uid, today: **1.7 s**. So the stall is before the agent loop, which also fits the cost
— the whole 13-family tour, every turn capped at 600 s, cost $0.4153.

**One lifecycle hazard was found, and it is real.** The gateway starts the next turn of a session
without stopping a turn still in flight: measured here, a second turn completed in 3.9 s while the
first was still running its shell, the session's status moved on to the newcomer, and the orphan was
still alive 164 s later (it runs to the runner's own `MAX_TURN_SECONDS`). Two Agent Zero processes
then share one workspace — and both write this base's per-turn files. Made safe on this branch
rather than left to chance: every per-turn file is now written to a temp name and renamed (a
truncate-then-write let the other process import an EMPTY extension module and lose that turn's tool
cards without a word), and the console log is per turn PROCESS rather than one shared name opened
with O_TRUNC — which is how a hung turn comes to leave a 0-byte log behind.

**Not established, and not claimed:** what the driver was waiting on during those 600 s. The
instrument for the next occurrence is in place and costs nothing: the per-turn console log, plus
`ps` inside the container while the turn is still hung. One agentzero turn is **275 MB RSS** (peak,
measured on a 4 GB container), which bounds how many can usefully run at once.

## The gpt-6 line: sol and luna beside astra (2026-09-27)

Richard asked whether gpt-6-sol was available and for the line to be expanded at list price on every
harness that can run it. Read the same day: OpenAI's pricing page names gpt-6-astra, gpt-6-sol and
gpt-6-luna and no terra; Azure's catalog has sol and luna at model version 2026-09-22 (deployed on
our resource that day, GlobalStandard, beside astra's 2026-09-03 deployment); OpenRouter, TokenRouter,
Vercel and llmtr list both as `openai/<id>` (OpenRouter and TokenRouter added them on 2026-09-22).
List prices per 1M tokens, no markup: sol $2 in, $0.20 cached, $2.50 cache write, $10 out; luna
$0.10, $0.01, $0.125, $0.50; astra $10, $1, $12.50, $50; above 272k prompt tokens input and cached
input double and output is 1.5x, the rule the gpt-5.x line carries. Batch and Flex are half, fast
mode double.

**What decides which bases offer them.** OpenAI refuses function tools on /v1/chat/completions for
the whole line unless `reasoning_effort` is `none` ("Function tools with reasoning_effort are not
supported for gpt-6-sol in /v1/chat/completions. To use function tools, use /v1/responses or set
reasoning_effort to 'none'", TokenRouter, 2026-09-27). sol and luna take `none` and then answer with
a tool call (2.8 s and 1.8 s); the runner's relay already retries on exactly that sentence and
remembers the fix per model, so the chat-only bases (aider, kimi, openhands, cheetahclaws, qwen,
cline) run them the way they run the gpt-5.6 line. astra does not take `none` ("Supported values
are: 'low', 'medium', 'high', and 'xhigh'"), so it stays on the Responses bases alone. Both sol and
luna describe a red PNG as "Red", so hermes's vision auditing may use them. 0.25.4 carries all of
it (#295); a model-support extension is a patch release, Richard's rule.

**The columns.** One per connection on hr-test, the four ids routed at that connection through the
model map and put back afterwards, twelve bases (codex, hermes, dsh, opencode, pi, omp, aider, kimi,
openhands, cheetahclaws, qwen, cline; goose waits for cline's rows, which are what its list mirrors;
systemone never), all five scenarios, `EXPECT_CONNECTION` set so a turn served elsewhere is a finding.
cheetahclaws is wired to OpenRouter, TokenRouter and Vercel only, so its OpenAI and Azure rows are
not run by design.

**Results (0.25.4, one retest of every miss on the 0.25.5 candidate, the same code as 0.25.5):**
146 pairs, 727 of 730 scenario runs.

| Column | Pairs | After the retest | First run | What missed the first time |
|---|---|---|---|---|
| tokenrouter | 30 | 150 of 150 | 136 of 142 | openhands on both ids (the prefix defect below); gpt-6-luna's recycle recall on codex, hermes and qwen; gpt-6-luna's artifact on aider |
| openrouter | 30 | 149 of 150 | 149 of 150 | aider x gpt-6-sol recycle, reproduced |
| vercel | 30 | 150 of 150 | 148 of 150 | gpt-6-luna's recycle recall on codex and on aider |
| openai | 28 | 139 of 140 | 139 of 140 | codex x gpt-6-luna recycle, reproduced |
| azure-e2 | 28 | 139 of 140 | 138 of 140 | gpt-6-luna's recycle recall on codex (passed the retest) and on aider (reproduced) |

Every gpt-6-astra pair passes on the six Responses bases on all five connections (30 pairs). Every
gpt-6-sol and gpt-6-luna first, follow-up, switch and artifact scenario passes on every base and
connection that ran; the three misses that stand are all the recycle recall, below. openhands
passed on all five connections after the fix, rerun through the agent server, not the recorder.
cheetahclaws has no OpenAI or Azure rows: the map's fall-through served its turns on a TokenRouter
integration when the column's connection cannot drive it, and a pair served elsewhere is not a
row for that column, so the bullet says not wired. Azure serves the ids as `gpt-6-sol-2026-09-22`
and the aggregators as `openai/<id>`; both are the provider's alias of the same model, noted, not
substitutions.

- **openhands sent a bare id to TokenRouter** (fixed in 0.25.5). The builder prefixed the model
  with `openai/`, and that prefix is taken off twice between the job and the wire (OpenHands' LLM
  and litellm 1.94.3 each strip one), so an aggregator's `openai/gpt-6-sol` reached TokenRouter as
  `gpt-6-sol`, refused with `503 model_not_found: No available channel for model gpt-6-sol under
  group default`. OpenRouter and Vercel resolve a bare OpenAI id, which is why the earlier Vercel
  column and this run's OpenRouter and Vercel rows passed, and openhands had never been measured
  on TokenRouter. Measured against a loopback recorder in the openhands venv: `litellm_proxy/<id>`
  is taken off once and the rest sent as it is, so the builder uses that prefix; and because
  litellm's proxy provider reads LITELLM_PROXY_API_BASE and LITELLM_PROXY_API_KEY (its Responses
  path does not fall back to the OpenAI pair: "api_base not set for LiteLLM Proxy responses API",
  the first hosted turn on gpt-5.4, whose api_mode resolves to responses), the driver hands it
  that pair and no other. Same fix on hosted (56308ad9), where openhands then passed the family
  tour on the platform channel with receipts at list price.
- **gpt-6-luna's recall after a recycle on codex.** The recycle scenario asks, after the sandbox
  is recycled and the thread resumed, for the codeword of the task's first message; luna answered
  the harness's completion phrase ("CODEX DONE") instead, first time on four of five connections,
  twice on OpenAI direct, and passed the retest on TokenRouter, Vercel and Azure. hermes and qwen
  did it once each on TokenRouter and passed the retest. The turn completes and the thread is
  intact (the same question on gpt-6-sol and astra is answered everywhere), so this is the
  cheapest tier's recall, recorded as FAIL where it reproduced and the model stays offered.
- **aider answers nothing after the restore, sometimes.** aider's recycle resumes with its own
  chat history; on the gpt-6 line it answered the recall with no text at all ("AIDER None") on
  gpt-6-sol twice on OpenRouter, on gpt-6-luna twice on Azure, and once each on TokenRouter and
  Vercel (passed the retest). Every other aider scenario passes on every connection. An open item
  on aider's restore path with this line, not a catalog change.
- **The console opened on a placeholder default** (fixed in 0.25.5, hosted b71f427b ported):
  the placeholder lists and defaults in the console are regenerated from the gateway's catalog
  byte for byte, the default helper reads the server's answer before the placeholder and never a
  list's first entry, and a test fails the suite when the lists drift. Measured on the candidate:
  a fresh page on codex, hermes, claude-code, omp, openhands, aider, kimi and dsh opens on the
  gateway's default.
- The 0.25.5 candidate was built from the branch so the openhands rerun could be measured end to
  end before the tag; 0.25.5 is the same code from main, and the candidate's image and tag were
  removed after the swap.

**goose (0.25.6).** goose's list is the set of paths cline's rows earned, and cline passed both ids
on every connection, so 0.25.6 lists gpt-6-sol and gpt-6-luna on goose and its own ten pairs ran
the same way: 50 of 50 after one retest (first run 48 of 50: gpt-6-luna's recycle recall on
Vercel and gpt-6-sol's on OpenAI, both answering "GOOSE DONE", both passing the retest). The
same recall flake as above, on the base that resumes through the relay like cline does.

## The browser column (2026-09-27)

Every base but System One drives the browser plugin on one task in plain words: "Open
https://example.com/ in the browser, click the only link on that page, and reply with the URL and
the title of the page you land on." A base passes when the task completed, the trace shows the
browser navigating and clicking, the answer names iana.org (where the link goes), and the browser
session was stopped and billed. Runner: `scripts/support-matrix/plugs/browser.py`; the table is
the Browser section of support-matrix.md, rendered from docs/browser-column.json.

**Result: 15 of 15 on 0.25.7-rc.17, first try, 27 to 52 seconds a base, one browser minute each.**

The baseline on rc.14, before any change, was 5 of 15 (codex, claude-code, pi, omp, dsh), and
three defects stood between it and the result, each measured on its own build:

1. **A Browser section in the agent's doc (rc.15).** Codex 0.154 keeps MCP tools behind its tool
   search and opened a page with web search and curl while the console's Browser card stayed
   empty; hermes fetched the page its own way, and cheetahclaws and opencode obeyed the prompt's
   "do not visit any other site" instead of following the link (which leads to iana.org). A
   harness that includes the browser plugin now gets a Browser section in AGENTS.md / CLAUDE.md,
   the file its own instructions go to: the tools by name, that the person is watching, never
   curl or a web search instead, look the tools up if they are deferred. The prompt lost the ban
   and names "the only link" rather than its wording, which example.com changes ("More
   information..." one week, "Learn more" the next). On rc.15 the seven bases that already had
   the tools passed 7 of 7.
2. **One header helper for every MCP writer (rc.16).** goose, opencode, aider, kimi, qwen,
   gemini, openhands and cline had no browser at all: their MCP writers passed a server's
   declared headers and dropped its `auth`, so the plugs server, whose credential the gateway
   mints per turn, answered 401 (openhands said so; kimi said the server could not be reached;
   the rest said they had no browser). claude, codex, pi, omp and hermes each carried their own
   copy of the auth handling and worked. `_mcp_headers` in runner/server.py is now the one place
   a server's headers come from, for every writer and the bridge. 14 of 15 on rc.16.
3. **Tool names are `plug_tool` (rc.17).** openhands reached the browser and the turn died on the
   Responses API's "Invalid 'input[3].name': string does not match pattern '^[a-zA-Z0-9_-]+$'":
   the plugs server named its tools browser.navigate, github.get_file_contents and so on. Claude
   Code, Codex and pi rewrite an MCP tool's name before offering it; OpenHands passes it through,
   and neither OpenAI's nor Anthropic's function-name rule allows a dot. 15 of 15 on rc.17.

Tools seen per base differ by style, not by ability: some snapshot before clicking, some read the
URL after, cline waits for the load; every one navigated and clicked through the plugin.

## The bugfix round of 2026-09-28: 0.25.13 to 0.25.15

Three releases carried the contributor PRs and what verifying them on hr-test turned up. 0.25.13
(c0ebe8c) is #265, #270, #285, #286, #290, #291, #292, #312 and #314; 0.25.14 is the Starter Kits
page from the console design (#313); 0.25.15 is #315 and #316, the two fixes below. Every release
was swapped onto hr-test with the fresh-volume check and the checks here were run against the
container by the API and the console.

**openhands x claude-opus-5 still failed on 0.25.13, with #312 in it.** The turn ended in 16 s
with TokenRouter's refusal of the thinking shape ('"thinking.type: enabled" is not supported for
this model. Use "thinking.type: adaptive"'). #312 put the retry in the broker, which is the path
brokered traffic takes; a self-hosted install in owner trust sends the sandbox's request through
the runner RELAY (`[relay] provider refused ...` in the container log), which has its own ladder of
"the provider named the fix" retries and had no rung for this one. #315 adds it: the relay drops
`reasoning_effort` for that model on that route, remembers it, and sends again at the model's own
default. On 0.25.15 the same turn completes in 16 s.

**The aider row of the browser column failed four times on 0.25.13, with #314 in it.** Each trace
was a reply that announced work and did none, which is what the driver's once-per-turn nudge is
for, and each slipped past it: "I’ll open the page in the browser" (gpt-5.4 writes the
typographic apostrophe; the regex knew only the straight one), "I need to use the browser for
this, not edit any files" (a need stated instead of met), and "To complete the task, I still need
to click the link" as a paragraph after the first browser output. A fourth run clicked with a
selector that timed out and navigated to the destination instead, which the column does not count
as a click. #316 lets the nudge match either apostrophe and a stated need, and adds the
stops-short paragraph. On 0.25.15 aider passes in 27 s and openhands in 34 s (open, navigate,
click, get_url; the answer names the iana.org page; the session's stop row is billed). goose (28 s)
and openhands (40 s) had passed on 0.25.13 as well, and the CSV preview of #292 was checked there
through the console: three logical rows, a quoted comma, a doubled quote and a newline kept in one
cell.

**Reading a failed row.** `plugs/browser.py --bases <base> --keep --out row.json` leaves the harness
in place and writes the session id; `GET /v1/traces/{sid}/all?compact=0` is the trace, one JSON
object per line, and `GET /v1/sessions?limit=N` lists the recent sessions when the id was not
kept. A hosted install has the broker path only; the relay finding is the self-hosted image's.

## Environments column (2026-09-29, 0.26.11 and 0.26.12)

`scripts/support-matrix/environments/column.py`: every base but System One runs three tasks on one
environment (`proof-studio-57543`: tabulate from pip, qrcode from npm, jq from apt, built once), each
task in its base's default model, judged by the server's record: the turn completed, the trace holds
no install command, the answer shows the package used from the environment (its path under the mount
or the store, the command's output), and the session names the environment.

| base | pip (tabulate) | npm (qrcode) | apt (jq) | install commands | seconds |
|---|---|---|---|---:|---:|
| codex | pass | pass | pass | 0 | 54 |
| claude-code | pass | pass | pass | 0 | 43 |
| hermes | pass | pass | pass | 0 | 98 |
| pi | pass | pass | pass | 0 | 37 |
| omp | pass | pass | pass | 0 | 75 |
| dsh | pass | pass | pass | 0 | 97 |
| goose | pass | pass | pass | 0 | 53 |
| opencode | pass | pass | pass | 0 | 54 |
| aider | pass | pass | pass | 0 | 53 |
| kimi | pass | pass | pass | 0 | 72 |
| openhands | pass | pass | pass | 0 | 78 |
| cheetahclaws | pass | pass | pass | 0 | 53 |
| qwen | pass | pass | pass | 0 | 48 |
| gemini | pass | pass | pass | 0 | 47 |
| cline | pass | pass | pass | 0 | 37 |

15 of 15 bases; 45 of 45 tasks; every task one command, no install anywhere. The
first pass judged three answers by their labels rather than their evidence (aider paraphrases the
printed lines; omp's shell reports `jq --version` as jaq while `which jq` and the sorted output are the
environment's); the judges now read the evidence, and the two bases rerun clean on 0.26.12.

## gpt-6.1-sol (2026-10-02, 0.28.7)

Richard asked for GPT-6.1 Sol on every harness that can run it, in the matrix, at list price, on both
trees. Read the same day: OpenAI's pricing page names gpt-6.1-sol (released 2026-09-29; no 6.1 astra or
luna yet) at $2 in / $10 out per 1M, cached input $0.10 (half of gpt-6-sol's $0.20), cache write $2.50,
and above 272k prompt tokens $4 / $15 (cached $0.20, write $5); 1,050,000 context, 128k output.
OpenRouter, TokenRouter, Vercel and llmtr list it as `openai/gpt-6.1-sol` (OpenRouter also a `-pro`,
Vercel also a `-fast`; neither is carried); Azure's catalog names it at model version 2026-09-29. It is
offered wherever gpt-6-sol is, newest first in the OpenAI family, and it sees images.

**Where it runs.** Unlike gpt-6-sol and gpt-6-luna it refuses `reasoning_effort: "none"` ("Supported
values are: 'low', 'medium', 'high', and 'xhigh'"), so the relay's none-retry that lets the chat-only
bases call function tools on /v1/chat/completions does not help it. What decides is the channel: a
connection that passes chat/completions through refuses the first turn on the chat-only bases, while an
aggregator that translates chat completions with tools into OpenAI's Responses API upstream serves every
base, and aider (no function tools) runs it everywhere. openhands reaches OpenAI direct and Azure through
litellm's Responses path and fails only on TokenRouter. As with the gpt-5.6 line on qwen and cline, a
row measured working on a path stays listed and the catalog comment names the connections that refuse
it; no base refused it on every connection, so none left the catalog. It is not Responses-only (aider
runs it), so RESPONSES_ONLY_MODELS is unchanged.

**Measured** (0.28.7-rc.1 and rc.2 on hr-test, Playwright through the console, one column per
connection, five scenarios per pair: first, follow-up, switch to gpt-6-sol on the same connection,
artifact, recall after recycle; the console's switch partner stays on the column's connection):

| connection | bases listed | pairs | scenario runs | refused the first turn |
|---|---:|---:|---:|---|
| TokenRouter (sponsorship) | 13 | 8 of 13 | 40 of 40 on the passing pairs | kimi, openhands, cheetahclaws, qwen, cline |
| OpenRouter | 13 | 13 of 13 | 65 of 65 | none |
| Vercel AI Gateway | 13 | 13 of 13 | 65 of 65 | none |
| OpenAI (direct) | 12 (cheetahclaws not wired) | 9 of 12 | 45 of 45 on the passing pairs | kimi, qwen, cline |
| Azure OpenAI | 12 (cheetahclaws not wired) | 9 of 12 | 45 of 45 on the passing pairs | kimi, qwen, cline |

goose, measured on its own pairs as it was for gpt-6-sol (rc.2, goose in the catalog): five of five connections, 25 of 25 scenario runs, TokenRouter included, so goose carries it.

Runner failures, not model results: four workers lost their headless browser mid-run ("Target page,
context or browser has been closed": qwen on TokenRouter at its first turn, hermes at its follow-up and
kimi on Vercel, the Azure worker after aider); each pair was re-measured one worker at a time and the
table carries the re-measurement (hermes on Vercel: "the session never opened a turn in 120 s" on the
crashed worker, five of five on the rerun).

**Family tour** (`FAMILIES=gpt-6.1-sol,gpt-6-sol`: one deck conversation per base handed into
gpt-6.1-sol and on to gpt-6-sol, under the OpenRouter route): codex, hermes, pi, omp, dsh, opencode, kimi,
openhands, cheetahclaws, qwen and cline passed, 2 of 2 families each in one conversation; aider aborted
its own first turn twice (13 s, no deck before any switch, its trait since 2026-09-30 and the same on hosted that day); its pair rows pass five of five on every connection, so the model stays listed on aider and the tour's aider first turn stays the open aider item it was.

**Finding, not this model's.** codex, dsh, omp and cline turns carry no `served_model` on this box on any
connection (a probe on codex with gpt-6-sol answers unlabelled too), so their rows read "turn(s)
unlabelled" by the rule of 2026-09-30; aider, opencode, pi, openhands, hermes (on three of five
connections), kimi, qwen and cheetahclaws label theirs. The relay's label is not read on those bases'
paths: a follow-up, outside this column.

**The record store.** The gpt-6 line's columns (#297, #299) were rendered from records never committed,
so the Claude Sonnet 5.5 column's regeneration (#351) dropped 175 of their rows from the table. The 149
rows the store lacked are restored from the document as it stood at #297, marked `reconstructed`, so
the table says again what was measured then.

**Hosted cross-check** (the HarnessRouter session, same day): on the platform channel the seven
Responses-capable bases plus aider passed 35 of 35 with the five chat-only bases' first-turn 400 kept
as evidence; OpenRouter 12 of 12, 48 of 48; Vercel 7 of 7, 35 of 35; tours pass on codex, hermes, dsh,
pi, omp and opencode (third attempt, a sandbox carry flake), aider aborts on its own first turn as
before. The hosted platform then took OpenRouter as the route for this model, so its catalog lists the
same twelve bases as this one; its comment keeps the TokenRouter and direct-OpenAI refusal for
organizations that bring such a key, the rule the self-hosted catalog states.

## The minimax backend: MiniMax Code 0.5.4 — behaviour measured, columns NOT yet run (2026-09-26/27)

No `minimax` column exists in `docs/support-matrix.md`: a column needs a deployed instance running
one provider at a time. What was measured, on the 0.5.4 release archive (`mcode --version` = 0.5.4):

- **Through a local runner** (this branch, macOS arm64, real providers): minimax-m3 and gpt-5.4-mini
  on Vercel, gemini-3.5-flash-lite on Google, each served as itself per the relay (`minimax/minimax-m3`,
  `openai/gpt-5.4-mini`, `gemini-3.5-flash-lite`), relay usage non-zero on every turn; a bash tool call
  rendered as tool_use/tool_result; a follow-up recalled a number from the first turn through
  `--session`; the harness instructions (global `AGENTS.md`) reached the model; a stdio MCP server's
  tool was called with bash disabled and bash absent; a cancel during `sleep 241` left no process
  behind; no provider key in the CLI's argv, the agent shell's environment or the workspace.
- **Provider failures are structural** (invalid key, 401/503 at a stub and a real Vercel 401):
  `turn.failed` with the provider's sentence, exit 4, nothing narrated as assistant text.
- **The retry storm has no off switch, and that was established by walking the surface, not assumed.**
  0.5.4 retries EVERY error class five times — 6 upstream requests, measured at a stub for 401, 429 and
  503 — so a bad key is reported after 20-28 s. `DEFAULT_LLM_RETRY_POLICY` is
  `{maxRetries 5, baseDelayMs 1000, maxDelayMs 30000, maxRetryElapsedMs 120000}`, and the elapsed cap
  bounds the worst case: a 429 answered with `Retry-After: 90` still ended in 23 s, because
  `retryDelayMs` clamps Retry-After to `maxDelayMs` and the loop stops once the next delay would pass
  the 120 s window. What was checked, so nobody redoes it: (1) the config schema —
  `packages/config/src/config.ts`'s top-level parse is a whitelist of `parse*` calls that IGNORES
  unknown keys, and the only retry/timeout-ish keys in the whole schema are
  `goal.{subagent,evaluator}.{timeoutSeconds,maxRetries}` (goal-mode evaluation, not LLM transport),
  `permission.classifierTimeoutMs`, `tui.*.timeoutMs` and `ProviderOptions.{timeout,chunkTimeout}`,
  whose consumer is not in the published tree; (2) the 131 `process.env.*` names in the shipped
  bundle — none retry-, backoff- or timeout-related; (3) every flag of every subcommand on the pinned
  binary — only `exec --timeout`, a whole-run cap; (4) the code path — `withLLMRetry(inner, {policy?})`
  is the single hook and BOTH hosts pass no policy (`resolveLlmRetry: () => ({ observer })`,
  local-runtime-v2 `services.ts`; `llmRetry: { observer }`, local-runtime `host.ts`), so the default
  always applies and `policy` is reachable only by an embedder. Measured negatives: a top-level
  `llmRetry: {maxRetries: 0}`, `custom_provider.<id>.options.maxRetries: 0` and
  `options.{timeout,chunkTimeout}` each left the count at 6 requests.
  **`exec --timeout` is NOT used to bound it**, and that is deliberate: `--timeout 8s` against the 401
  stub did cut the run to 4 requests, but the record became `status: timeout` with an EMPTY error
  message — the provider's 401 sentence was gone. A bounded turn that cannot say why it failed is
  worse than a slow one that can.
- **Cost channel:** a trivial first turn is ~9k input tokens on minimax-m3 (most cached on Vercel) and
  ~17k on Google (no cache there). MCP tools, bundled skills, web search and website deploy are off
  or withheld, which halved the system prompt measured at a stub (14.7k -> 7.8k characters).
- The CLI fetches a public model catalog once per run (`models.dev`, with `MAVIS_REGION=en`); no
  login, telemetry or update check happens in `exec`.
### The browser column's `0 of 1` is the instance's missing key, not the base (2026-09-29)

`plugs/browser.py` reported `0 of 1 bases drive the browser` for minimax, twice, with
`no browser navigate/click in the trace (no browser tool at all)`. Every link of the chain was
checked on a build of this branch rather than inferred from that sentence, and **every one of them
works**:

- the runner wrote the `plugs` server into `$MINIMAX_DATA_DIR/mcp.json` as `type: http` with the
  per-turn bearer in `Authorization`;
- the gateway's Browser section reached the agent's doc (the global `AGENTS.md` this base uses),
  naming all thirteen tools;
- the CLI connected and **the request carried all thirteen** `mcp__plugs__browser_*` tools
  (its own `llm-call.json`);
- **the model called them** — `browser_navigate` then `browser_get_url` (its own transcript).

What came back: `"The browser service is not set up on this deployment. Tell the person."`, which is
`gateway/app.py`'s own refusal when `browser_plane.configured()` is false — the instance has no
`BROWSER_USE_API_KEY`, exactly as `plugs/browser.py`'s docstring says ("without it every base
reports the refusal it got"). The model then told the person, which is the right answer to a browser
that is not there.

**Established before anything else, because a column with one base cannot say whose defect it is:**
a second base on the same build, instance and model — `qwen`, one of the fifteen that passed this
column 15 of 15 on rc.17 — fails **identically**, with the same refusal in its answer. So this is not
this base's defect and not this PR's.

The trace had the evidence all along: two `plug` rows, `outcome: refused`, `error: "not configured"`,
for `navigate` and `get_url`. The column counts only rows whose outcome is `ok`, so it rendered two
refused calls as *"no browser tool at all"* — the opposite of what happened, and the reason two people
went looking for a missing-tools defect. A maintainer item, below.

Separately, and because a copy that agrees today drifts tomorrow: this base's MCP writer now takes a
server's headers from `_mcp_headers`, the one helper every writer and the bridge share, instead of
its own inline copy of the same three lines. Its own copy was correct — the bearer is in the file and
the server accepted it — but eight writers that kept their own copy are why the browser column was
5 of 15 before rc.16.

### The family tour's seven silent failures were the relay, not the context window (2026-09-29)

The first tour on this base passed 7 of 14 families in one conversation: every family from kimi-k3
on was recorded `not settled in 600s, stopped (cancelled)` with **no served model, no tool call and
no reason** — except `glm-5.3-flash`, which passed in 12 s in the middle of the collapse. The
obvious reading was the blanket 200k context window (above): a history too large for a model's real
window. **It was not**, and two measurements say so. The conversation at its largest was 219 KB of
messages plus a 12 KB system prompt and 27 KB of tool schemas — about 65k tokens, under the real
window of every failing model — and the same families pass on that same session today, with a
longer history (kimi-k3, qwen3.8-flash and minimax-m3 each re-run by hand, all completed in
seconds). A conversation too long fails monotonically; this did not.

**It was the loopback relay answering nothing when the provider answered nothing**, in two ways,
both in `_forward`:

- The upstream call caught only `urllib.error.HTTPError`. A refused connection, one dropped
  mid-request, or a provider gone silent raised out of the handler; `ThreadingHTTPServer` printed a
  traceback and closed the client socket **with no HTTP response at all**. The instance's log holds
  ten of those (`http.client.RemoteDisconnected: Remote end closed connection without response`),
  two inside the tour's failing window.
- The relay's own wait was 600 s — the same as the cap above it — so a provider that accepted a
  request and then went silent could never be REPORTED by the relay: the cap always fired first and
  the turn was recorded as cancelled with nothing in it. That is the shape of six of the seven.

Both are fixed in `runner/server.py`: transport failures now answer **502** (refused or dropped) or
**504** (timed out) with `{"error":{"code":"upstream_unavailable",…}}` carrying the provider's own
failure; a bare drop before any byte is retried once and a timeout is never retried (the provider
may be generating, and a second request is a second bill); a stream that stops mid-answer carries
the reason as its own error event and is left unterminated, and a body that stops arriving is a 502
or 504, so neither reads as a complete answer; and `HR_RELAY_UPSTREAM_TIMEOUT_S` sets the wait.
Its default stays the 600 s this relay always waited (a reasoning model answering a non-streaming
call is silent for minutes), which is far under the runner's own turn cap; an instance with a
shorter cap of its own, such as one this suite measures with its 600 s per turn, runs with 180. Pinned by `runner/tests/test_relay_upstream_failure.py`, which
drives the real handler over a real socket against an upstream that drops, drops-then-answers,
refuses, and goes silent — the defect was in what reaches the client, not in parsing.

**Proven by re-running the tour twice** on a build of this branch, with the nine families around the
collapse (`kimi-k3, qwen3.8-flash, glm-5.3-flash, mistral-medium-3.5, step-3.7-flash,
hunyuan-4-preview, nemotron-3.5-lightning, minimax-m3, gpt-5.4-mini`): **8 of 9 both times, no turn
anywhere near the cap** — every previously-hanging family completed in 9-52 s with its served model
and the deck. The two non-passes were not hangs and were not the same family twice:

- run 1, `hunyuan-4-preview`: the turn **completed** with `tencent/hy4-preview` and `tour.pptx` — the
  tour read the record at the instant it said `done`, the gateway's own word for completed
  (`_RESP_STATUS_MAP`), which is not in the script's RUNNING list, so it settled early on a
  half-written record. A shared-script bug, below.
- run 2, `nemotron-3.5-lightning`: a real, reported failure in 113 s — `Runtime completed without a
  final assistant response`, and the CLI's transcript gives the mechanism: `stopReason: "length"`.
  The model hit the output cap with no usable final message. That is the blanket
  `max_completion_tokens: 16384` above, now with a named victim, and it is the same id the matrix
  found unstable on its own (run1 FIRST failed, run2 RECYCLE failed, run3 clean 5/5).

And the fixed path was exercised end to end on a real instance rather than only in tests: with the
connection's base URL pointed at a port nothing listens on, a turn fails in 22 s carrying
`502 the provider did not answer: URLError: <urlopen error [Errno 111] Connection refused>`.

### The disabled-tool claim, measured against `bash` (2026-09-28)

`disabled_tool_unused` passes VACUOUSLY on this base, as it does on kilo, qwen, gemini, cline, kimi
and aider: the shared dimension disables the fixed id `WebSearch` and none of them has a tool by that
name. So it was measured directly instead, with an oracle no answer can fake — `HR_MX_STAMP` set in
the TURN'S ENVIRONMENT and never in the prompt, the task being to write that value into a file. Only
a process that ran with the turn's environment can produce it.

- **Control** (all tools): `bash` called, the stamp lands in the file. **Treatment** (`bash`
  disabled): the CLI sends 11 tools with no shell among them — `edit get_goal glob grep read skill
  task_stop todowrite update_goal web_fetch write`, read off its own `llm-call.json` — and the stamp
  appears in NO file in the workspace. Repeated on `minimax-m3` and on `gpt-5.4-mini` under explicit
  pressure to try every tool, delegate and spawn.
- **BOTH ERROR DIRECTIONS.** Neither model came back empty-handed: one wrote `proof.txt` containing
  `HR_MX_STAMP: <unavailable>`, the other `<unresolved>`. A file-existence oracle would have reported
  a shell escape that never happened. Disabling `bash` withholds EXECUTION; it does not withhold file
  writing (`write`/`edit` stay) and it does not withhold network egress (`web_fetch` stays — it even
  answered a loopback HTTP beacon in the treatment arm, which is why a beacon is not a sound witness
  of "a shell ran" and the env stamp is).
- **The subagent is a genuine second door, and closing it is load-bearing.** With `bash` withheld but
  `features.delegation` left ON, the agent called `task`, the subagent had a shell, and the file came
  back holding the env stamp. So a subagent does not inherit the main agent's denial: withholding the
  named tool alone would have left `tool_enforcement: "hard"` false. That is why the runner turns
  delegation off whenever anything is withheld — a positive control for the line, not decoration.
  (In that run the model's prose denied having env access while the stamp sat in the file: narration
  is not evidence in either direction.)
- **"The script actually ran" is fakeable.** A skill whose `SKILL.md` says to run `scripts/stamp.py`,
  the script holding its own token and writing `$HR_MX_STAMP`: with the shell withheld the agent read
  the script and hand-wrote `stamp.txt` as `SKILLTOK-8842QF|<no-env>`. The bundle's token is there, so
  a claim keyed on it passes with no execution; the env stamp is absent, which is what proves nothing
  ran. This settles the question the kimi work left open — as judged today that claim is judged by
  something an agent can fake, and an env stamp is the cheapest form it cannot.

- **The output cap and the context window DO have a hook, unlike the retries.** Every request carries
  `max_completion_tokens: 16384` and an unknown model's window defaults to 200,000 — the CLI's
  unknown-model defaults, since the runner sets neither per id (kimi's `KIMI_CONTEXT_WINDOW` question).
  Measured: with `custom_provider.<id>.models.<model>.limit: {context: 32768, output: 4096}` the same
  request carried `max_completion_tokens: 4096`, so a per-id table would work whenever there are
  measured windows to put in it.

## The kilo backend: Kilo CLI 7.8.1 (2026-09-26/27) — behaviour measured, NO column yet

Kilo CLI (Kilo-Org/kilocode, MIT) is an opencode fork (its README says so; `packages/opencode` in
the monorepo), and the runner treats it as one: opencode's `run --format json` events, provider
block, MCP map and `skills.paths` are unchanged at 7.8.1, so `_build_kilo` reuses opencode's package
choice, MCP translation and normaliser. There is **no matrix column**: this backend has not been run
on a deployed instance. What follows was measured on the pinned binary (darwin-arm64 build of the
same release for the local runs, `kilo --version` = `7.8.1`), against a logging stub and, for three
turns, through a locally started runner on Vercel.

**Where it differs from opencode, each measured:**

- **It phones home unless told not to.** A turn whose provider was on 127.0.0.1 made CONNECTs to
  `us.i.posthog.com` (telemetry, x2), `models.dev` (catalog, x1) and `api.kilo.ai` (Kilo's gateway
  provider, x2), logged at a refusing proxy. `KILO_TELEMETRY_LEVEL=off` and
  `KILO_DISABLE_MODELS_FETCH=1` removed the first two; `"enabled_providers": ["hr"]` in the config
  removed the third — zero egress besides the provider. The control arm (defaults) is what shows the
  proxy sees these calls at all. No Kilo login is needed for anything the runner does.
- **Scheduling tools that promise a later turn** (`schedule_wakeup`, `cancel_wakeup`, `cron_*`,
  `goal`: "the harness resumes this session with the prompt you give it"). Every turn here is one
  process the gateway starts, so the runner denies them on every turn.
- **`write` and `apply_patch` are gated by the `edit` key.** Measured at the stub: denying `write`
  left `write` and `apply_patch` in the request; denying `edit` removed all three. The catalog offers
  `edit` only ("Edit / Write"). opencode shares this code (`permission.disabled`), so the opencode
  base's separate `write` switch is very likely a no-op too — not changed here, flagged.
- **Two doors to the shell.** With `bash` denied, `background_process` (which takes a `command`) was
  still offered, so the runner denies both when bash is switched off.
- **A dead endpoint never fails.** Kilo's "offline guard" parks a turn whose connection drops, probes
  connectivity, declares the network restored and retries — the retry budget resets on every retry.
  Measured on the bare CLI: a refused connection ran ten minutes with a retry every five seconds and
  no output; a server that accepts and drops the connection, 29 "session offline" cycles in 150 s.
  Through the relay the same thing happened whenever the relay itself dropped the socket (it did not
  catch `URLError`). The relay now answers an unreachable upstream with a 502 and the reason, which
  every client reports: through a local runner the dead-URL turn failed in 76 s (the ai-sdk's retries
  of a 5xx) with `upstream unreachable: [Errno 61] Connection refused`. A Messages-shape turn does not
  ride the relay and is only bounded by the runner's turn ceiling.

**Failure reporting (checklist #8), free probes:** a 401 is one structural `error` event (APIError,
`data.message`, `statusCode`) and exit 1 in 4 s; a 503 is retried 6 times over 73 s and then the same
event. Kilo never narrates a provider failure as assistant text, so no prefix is stripped, and an
answer that starts "Error: …" stays an answer (both pinned in runner/tests/test_kilo_backend.py). An
invalid Vercel key through the runner: `failed` in 6 s with Vercel's own sentence.

**Resume.** SQLite `$HOME/.local/share/kilo/kilo.db`, table `session(id TEXT PRIMARY KEY, ...)`; an
unknown `--session` exits 1 with nothing on stdout. The builder asks the table (read-only) before
passing `--session`; a missing session starts fresh and the reply carries the resume_lost note
(measured through the runner).

**Local E2E through a runner, 2026-09-27 (Vercel, three paid turns, one session):**

| turn | model | result | served_model (relay) | usage (in / out / cache read / cache write) |
|---|---|---|---|---|
| 1: remember a word, write hello.py, run it | gpt-5.4-mini | `PELICAN-42: 42`, tools glob, write, bash; hello.py produced | `openai/gpt-5.4-mini` | 11,311 / 636 / 32,256 / 0 |
| 2: "what was the word?" (resumed) | gpt-5.4-mini | `PELICAN-42` | `openai/gpt-5.4-mini` | 2,265 / 40 / 8,704 / 0 |
| 3: switch model, bash disabled, run echo | claude-haiku-4.5 | `NO-SHELL. Code word: PELICAN-42`; its bash call refused as "unavailable tool" | **none** | 118 / 81 / 13,154 / 13,406 |

The real key was not in the kilo process's argv or environment on the relay turns (the relay's
placeholder was), and not in any file under the workspace afterwards. Turn 3 was the gap that the
next section closes: a claude id on an aggregator spoke Anthropic Messages, which opencode's rule
keeps OFF the relay, so nothing reported a served model. The cost channel: a one-word follow-up is
~11k input tokens (system prompt ~14.7k characters plus 22 tool schemas).

### The claude rows had no served model, and the package choice was why (2026-09-28)

Measured twice, in one session on integration:vercel, per turn: `gpt-5.4-mini` recorded
`served_model='openai/gpt-5.4-mini'` and `claude-haiku-4.5` recorded `served_model=None`. So matrix
rule 2 — served AS the model asked for — could not be evaluated for the claude row at all, and that
row's five green scenarios said nothing about which model ran. **Usage was NOT lost**: the same
session recorded 24,404 input / 13 output tokens (and an earlier one 14,124 / 640 / 48,672 cache
read). That figure is the session aggregate over a gpt turn and a claude turn — the turns endpoint
carries no per-turn usage — while `served_model` IS per turn, which is how the gap was isolated.

The cause is one clause of the package choice `_opencode_npm`, inherited: a claude id on an
aggregator connection (`tokenrouter`, which is how vercel, llmtr, tokenrouter and the hosted door
are all wired) is served by `@ai-sdk/anthropic`, and an Anthropic-shape turn cannot ride the
loopback relay because the relay finds a route by the placeholder BEARER it handed out while a
Messages client sends `x-api-key`. No relay, no served model.

It is not a protocol limit: an aggregator serves those ids over chat/completions perfectly well
(cline and qwen reach every claude id that way, and the minimax backend measured
`anthropic/claude-haiku-4.5` on this same provider and id through the relay on the same day). So
kilo now makes its own choice (`_kilo_npm`): Messages only for a DIRECT Anthropic connection
(provider `anthropic`, or a custom endpoint declared `anthropic`), chat/completions for the
aggregators. Re-measured on the same rig, same session shape: `claude-haiku-4.5` records
`served_model='anthropic/claude-haiku-4.5'`, which `_same_model` reads as the id asked for.

**The broker question, answered.** Nobody had run an Anthropic-shape turn through the broker in
self-hosted loopback mode. Run now, with the pre-fix code and `HR_SANDBOX_TRUST` off owner: the CLI
posted `/v1/llm/v1/messages` (the ai-sdk appends its own `/v1/messages` to the broker base) and the
broker answered 200 — `_broker_token` accepts `x-api-key`, so the turn completed with a brokered
credential and the provider key never reached the sandbox. **But `served_model` was still null**,
because nothing on the broker path stamps it: the gateway only ever takes a served model from the
runner's result event, which is the CLI's own report or the relay's stamp. So the gap was the relay
bypass and not a trust mode, and the fix repairs both modes — after it, the same claude turn in
broker mode goes `/v1/llm/chat/completions` through the relay and records
`anthropic/claude-haiku-4.5`.

### The two rows the full column failed, chased on 2026-10-01/02

The full column (55 pairs, 271/275 scenarios, served model on every row, zero substitutions) failed
two rows and both reproduced on a retest. Neither is a defect in this backend, and neither is fixed
here; what follows is what was measured.

**`claude-opus-5`, ARTIFACT and RECYCLE.** `run ended without an assistant message; the model
returned no output` — kilo's own words for a completion with no content — at 156/180 s and 147 s,
twice, while first, follow-up and switch passed both times with `served_model=anthropic/claude-opus-5`.
The two failing scenarios are the ones that run AFTER the switch, which is the shape the repo already
records for this exact id: once a session holds a turn by another model, Anthropic answers further
opus-5 requests with an empty stream and `finish_reason content_filter`, and the aggregators forward
that answer unchanged (fdba6ed, measured 2026-09-12 against Anthropic directly; goose keeps the id
off its list for it).

Chased today at four levels, and NOT reproduced at any of them:
- the CLI alone, real workspace and config, artifact prompt: tool call then `DONE`, exit 0, two
  provider calls;
- the wire, kilo's captured 14,689-character system prompt and all 22 tools: `finish_reason
  tool_calls`, 21,392 input tokens;
- the wire, a tool round trip with the assistant's reasoning signature carried back and stripped:
  both arms answered;
- the product, on the live instance, first → switch → artifact in the matrix's own order, with the
  switch on `gpt-5.4-mini` and again on `gpt-6-astra` (what the column used): all three turns
  completed both times, the artifact turn writing the file and replying `DONE`.

So the provider was healthy for this shape on 2026-10-02 and the failure is not deterministic. What
the column's two runs and the repo's September measurement share is the model and the post-switch
position; what my reproduction could not match is the column's full four-turn history (first,
follow-up, switch away, switch back) and its moment in time. Recorded as a provider-side limitation,
with the id left in the catalog: removing it on evidence I could not reproduce would be a guess in
the other direction. If a later column fails it again, goose's precedent (`_NOT_OFFERED`) is the
remedy, and that is the maintainer's call rather than mine.

**What IS fixed:** the relay now reads Vercel's hyphenated spelling of a refusal. `_FINISH_RE`
admitted `[a-z_]` only, so `content-filter` never matched on that channel, `last_finish` stayed
empty, and the check that turns a declined request into a stated reason never ran — the person got
whatever the CLI made of an empty answer, which on kilo is the sentence above. Picked up from the
agent-zero branch (07c650f), where the same empty-stream class was measured on
`anthropic/claude-opus-5` and `anthropic/claude-fable-5.1`. If the column's failure is that refusal,
the turn now says `the provider declined the request (finish_reason content_filter)` instead of
kilo's private sentence.

**`hunyuan-4-preview`.** ARTIFACT failed at 1073 s on the first run; on the retest the FIRST turn
failed at 478 s with the tail stuck at `Working…` and no turn record at all. The provider is not the
cause: `tencent/hy4-preview` (the id Vercel's own map serves for this canonical name) answered kilo's
real request shape — the same 14,689-character system prompt and 22 tools — in 7.7 s for 14,436
input tokens and $0.012, `finish_reason stop`, the exact text asked for.

What was captured while the pair hung is a LIFECYCLE failure, and it is not this backend's: the
session read `status=running` with `running_response_id: None`, no CLI process existed in the
container at all, the relay's traceback was a `ConnectionResetError` writing a chunk back to a client
that had gone, and it was still `running` at 993 s — past the runner's `MAX_TURN_SECONDS=900`. A
cancel cleared it. Two mechanisms fit and neither was reproducible on demand: a descendant that
escaped the process group still holding the CLI's stdout pipe, so the runner's reader loop never sees
EOF and the record never leaves `running` (the trap `_kill_proc_tree` and `_sweep_turn_processes`
were written for, and kilo's `background_process` is a tool that daemonises by design); or the
gateway's owner task renewing the session heartbeat while polling a turn that can no longer finish,
which keeps `_reconcile_session` from ever treating it as stale.

One concrete misalignment, verified on the instance: the runner's ceiling is `MAX_TURN_SECONDS`
(set to 900 there) while the gateway's backstop is `HARNESS_MAX_TURN_S`, which is unset and defaults
to 21600. An operator who lowers the runner's cap still waits six hours for the gateway to settle a
turn the runner has already given up on. Reported, not changed here: both are shared surfaces.

### Tool enforcement, measured against `bash` (2026-09-28)

`disabled_tool_unused` in the shared custom-harness dimension disables the fixed id `WebSearch`,
which matches nothing on kilo (nor on qwen, gemini, cline, aider, kimi), so that claim passes
VACUOUSLY here. Measured directly instead, on a live instance, gpt-5.4-mini on vercel, with an
oracle no answer can fake: the file the command would write must contain a stamp that exists only
in the turn's shell environment (a harness `env` variable, never in the prompt).

| arm | bash | prompt | shell ran? | evidence |
|---|---|---|---|---|
| control | allowed | run the command | **yes** | `bash` called, proof.txt = the stamp |
| control | allowed | use `background_process` | **yes** | `background_process` (monitor) called, proof.txt = the stamp |
| deny | disabled | run the command | no | no tool calls, answer `NO-SHELL`, no file |
| deny | disabled | use `background_process` | no | no tool calls, answer `NO-SHELL`, no file |
| deny | disabled | use a subagent | no | no tool calls, answer `NO-SHELL`, no file |
| deny | disabled | "you MUST call `task`" | no | `task` called, subagent answered `NO-SHELL`, no file |

So the deny is inherited by a subagent (the permission map is kilo's own config, which the child
session reads too), and `background_process` really is a second door to the same shell — it ran the
command in the control arm — which is why the runner denies it together with `bash`. With both off
the model is offered: agent_manager_models, apply_patch, board_post, board_read, glob, grep,
kilo_local_recall, link_pr, read, skill, task, todowrite, webfetch, write.

**Why the oracle is the stamp and not the file.** In one deny arm the model routed around the
missing shell by having a subagent create `proof.txt` with `apply_patch` — the file existed and was
EMPTY. A file-existence oracle would have recorded that as a shell escape and overturned the
enforcement claim wrongly; the stamp says plainly that no shell ran. Disabling `bash` withholds
execution, not file writing: `write` and `apply_patch` are separate switches, and a harness that
wants neither must disable `edit` as well.

## Four bases in one release: kilo, minimax, grok, agentzero (2026-10-03, 0.29.0)

Kilo CLI 7.8.1, MiniMax Code 0.5.4, Grok Build 1.0.41 and Agent Zero v2.13 arrived as four pull requests
with a fifth for the suite and the relay (#362 to #366). They were merged onto one branch, reviewed, and
measured together on hr-test from release candidates (rc.2 to rc.5), every scenario driven through the
console with Playwright. The sections above are the authors' own measurements on their instance; this
one is the maintainer's, and it is what the columns in `docs/support-matrix.md` (`kilo-default`,
`minimax-default`, `grok-default`, `agentzero-default`) were rendered from. "default" is the instance's
own routing: each id ran on the connection the instance serves it with (TokenRouter for most, Vercel,
OpenRouter, the direct Anthropic, OpenAI and Google connections and two custom endpoints for the rest),
and each row names it. gpt-6.1-sol, the switch partner of most rows, was routed at OpenRouter as in its
own column.

**The columns** (full catalog, five scenarios per pair, failed pairs retested once on rc.4):

| base | pairs | scenario runs, first pass | after the retest |
|---|---:|---:|---:|
| kilo | 59 | 287 of 295 | 291 of 295 |
| minimax | 57 | 282 of 285 | 283 of 285 |
| grok | 56 | 273 of 280 | 279 of 280 |
| agentzero | 56 | 266 of 280 | 267 of 280 |

**The other dimensions, all four bases:** family tour kilo 13 of 13, minimax 14 of 14, grok 14 of 14,
agentzero 14 of 14 (one conversation each, rc.5; on rc.4 grok passed 7 of 14 and kilo 13 of 14, see
below); plugin matrix skills, stdio, SSE and streamable HTTP 4 of 4 each; custom-harness 4 of 4 with
MCP; browser column 4 of 4.

**What the measurement found, and what was done about each.**

- **A tool schema with a combinator at its root is refused by OpenAI as well as Anthropic.** grok's
  `use_tool` on gpt-6.1-sol through TokenRouter: `Invalid schema for function 'use_tool': schema must
  have type 'object' and not have 'oneOf'/'anyOf'/'allOf'/… at the top level`, on every turn. The repair
  was gated on the claude family; it runs for every model now. It also dropped the root's own
  `required` and every `allOf` branch's; `required` is the root's, plus every allOf branch's, plus what
  all alternatives share.
- **grok on kimi-k3 failed after the answer had arrived.** Moonshot through TokenRouter ends a stream
  with `"prompt_tokens_details":{"audio_tokens":null,…}`; Grok Build parses token counts as u32
  (`serialization error: invalid type: null, expected u32`). The relay writes a null count inside usage
  as 0 on grok's route. Five of five on the retest.
- **kilo's claude rows on a direct Anthropic connection carried no served model** (claude-sonnet-4.6,
  claude-haiku-4.5, claude-sonnet-5.5-direct: 4 unlabelled turns each). A Messages-shape turn kept its
  direct base, which also left the connection's real key in the CLI's environment. The relay has read
  x-api-key since #352, so every keyed opencode and kilo turn rides it now; the three pairs are
  labelled and five of five on the retest.
- **What one model leaves in a conversation ended it for the next.** The tour on rc.4, grok 7 of 14:
  the first turn's model screenshots the slide and reads the PNG, the client replays that tool result
  to every later model, and an aggregator's Anthropic translation, Moonshot, and OpenRouter's llama,
  hunyuan and nemotron endpoints each refused the request for the image in it; a tool call one family
  streamed with an empty id was refused by Mistral and StepFun (`tool messages must include a non-empty
  string tool_call_id`); and on kilo, two parallel calls with one id were refused by Mistral
  (`Duplicate tool call id in assistant message`). The relay now names a refused image in words for
  that model, fills an empty id, and renames a duplicate once a provider says so
  (`runner/tests/test_relay_conversation_repairs.py`). grok 14 of 14 and kilo 13 of 13 on rc.5.
- **Agent Zero had no browser because it never sent the plugs server its credential.** Its MCP writer
  copied a server's `headers` and dropped `auth`; it takes them from `_mcp_headers` like every other
  writer. Browser column pass on rc.4. The job no longer rides argv (readable by every session uid in
  the container; it named the relay route's token and each MCP server's credentials).
- **Review findings fixed before the columns ran:** a stream that stalled mid-answer was ended as a
  complete, empty answer; a non-streaming body that stopped arriving became 200 with no content; a
  dropped connection was resent twice; kilo.json (and opencode.json, Claude Code's mcp.json and the
  bridge launchers, which had the same hole) carried MCP credentials into checkpoints; a character
  outside the BMP made grok's config.toml invalid; Agent Zero's dependencies resolved freely on every
  fresh volume (they install under `runner/agentzero-constraints.txt`, frozen from the measured venv).
  The relay's upstream wait keeps its 600 s default; hr-test, whose suite caps a turn at 600 s, ran
  with `HR_RELAY_UPSTREAM_TIMEOUT_S=180`.

**Not offered after two failures of the same kind** (`_NOT_OFFERED`, the reason beside each):

- kilo x llama-3.3-70b (OpenRouter): a runaway of Webfetch calls on the first turn, then the write call
  printed as text instead of made.
- minimax x gpt-5.6-terra: answers DONE without writing the file. minimax x gemini-3.5-flash-lite: the
  artifact turn ends `Conversation history could not be safely updated. Please retry.`
- grok x deepseek-v4-pro: the artifact turn ends `empty response from model (reasoning_only)`.
- agentzero x claude-fable-5 and claude-fable-5-1: the provider declines the first turn
  (`finish_reason content_filter`) with Agent Zero's system prompt; kilo, minimax and grok run both ids.

**Left listed, with the row saying FAIL:** claude-opus-5's artifact and recycle turns on kilo and
agentzero are declined by the provider's safety policy at the scenario's own words, the same two
misses kimi's column recorded, and both pass on minimax and grok; agentzero x gemini-3-flash-preview
answers the recall after a recycle with the previous turn's word twice, the recall trait recorded for
gpt-6-luna on codex. kilo x gpt-5.3-codex has no switch partner on its connection.

**Open, not this release's:** the console showed three file cards against one in the record on
minimax x llama-3.3-70b's first artifact turn (it passed on the retest); a display mismatch to chase
with a kept session. The withheld-tool claim of custom-harness is still judged on a tool the fixture
never asks for (review of #362), so it cannot fail; the env-stamp oracle described under the minimax
and kilo sections is the judge to move it to.

## A list of free-form objects reached the tool empty (2026-10-05, 0.29.3 and 0.29.4)

Reported from the hosted service: an agent asked a tool to insert rows and the tool received
`[{}, {}]` or `[]`. The rows were in the model's plan and gone from its tool call.

**The mechanism.** One tool whose argument is a list of objects, the model asked to pass two
specific rows, one call per cell, the item's schema written four ways:

| `items` | what the tool received |
|---|---|
| `{"type":"object"}` | the rows, in every cell |
| `{"type":"object","properties":{}}` | `[{}, {}]` from OpenAI models through Vercel and through OpenRouter; `[]` from kimi-k3 through Vercel and through TokenRouter |
| `{"type":"object","properties":{},"additionalProperties":true}` | `[{}, {}]` from OpenAI models through OpenRouter; the rows elsewhere |
| `{"type":"object","additionalProperties":true}` | the rows, in every cell |

The cells were eleven model families on Vercel and on TokenRouter, OpenAI models on OpenRouter, and
OpenAI, Azure and Google AI Studio directly. A tool's author writes the first row. hermes, opencode,
kilo and goose add the empty `properties` to every object node themselves, and Codex does for an MCP
tool. With the key present a route may hand the model an object it can put nothing in; without it
none did.

**The repair (0.29.3, #394).** The relay drops an empty `properties` from every nested object node of
a function tool's schema, for every model, and leaves the root `parameters` node as it is. A function
tool sits in four places, and the repair walks all of them: `tools[].function.parameters` (Chat
Completions), `tools[].parameters` (the Responses API), the `tools` of a `{"type":"namespace"}` entry
(Codex groups a server's MCP tools that way), and the `tools` of an item in `input` (a tool search's
answer). The first candidate covered the first place alone and left gpt-5.4 on Vercel at 14 of 17:
with an OpenAI model on an aggregator, hermes (`codex_responses`), opencode and kilo
(`@ai-sdk/openai`) speak the Responses API. hermes on an OpenRouter connection also called
OpenRouter directly, with the connection's key in its environment; it takes a relay route now, like
hermes's other connections.

**The judge.** The plugin matrix has a `rows` column (`plugins/run-matrix.py --mode rows`): the
fixture's second tool answers `PLUGIN_ROWS_OK` only when both rows arrive with their fields and says
what it received otherwise. The tool is the judge; an agent's own record of its call is not (one base
writes arguments through a file, and an answer can be cut short).

**Measured**, every base that lists the model, through hr-test's side container:

| model, connection | 0.29.2 | candidates of 0.29.3 |
|---|---|---|
| gpt-5.4, Vercel | 14 of 17: hermes, opencode, kilo | 17 of 17 |
| gpt-5.4, OpenRouter | 16 of 17: hermes | 17 of 17 |
| kimi-k3, TokenRouter | 14 of 16: hermes, goose | 15 of 16 |

The remaining miss is aider with kimi-k3 answering with the model's reasoning and calling nothing,
about one turn in three, before and after (#395). On the last candidate: the plugin matrix's five
columns on six bases at their default models, 30 of 30, and hermes on OpenRouter through the console,
four models by five scenarios, 20 of 20.

**Codex (0.29.4).** 0.29.3 did not reach Codex: it was handed the connection's base and key and never
passed through the relay. Codex 0.154.0 with gpt-6-luna, two runs per connection: the rows on
TokenRouter, OpenRouter, OpenAI and Azure; `[{}]` and `[{}, {}]` on Vercel, and the same there with
gpt-6.1-sol. gpt-5.4, gpt-5.4-mini, gpt-5.5, gpt-5.6-sol and gpt-6-astra passed on Vercel. For
gpt-5.4 the hosted service captured why: Codex sends `{"type":"tool_search"}` and no MCP schema in
the first request, so there is no empty `properties` to act on. That the other four pass for the
same reason is inferred, not captured. Now every Codex
connection that is not OpenAI's own or Azure's takes a relay route. The route keeps the connection's
base exactly as stored, since Codex called `<base>/responses` whatever the base looked like; the CLI
gets a loopback URL and a placeholder, so the connection's key is out of its environment; and the
account fingerprint that decides whether a resumed history is replayed as content is still taken from
the connection, because a route is new on every turn.

With the route, Codex on Vercel: gpt-6-luna three of three, gpt-6.1-sol two of two, gpt-6-sol one of
one, and on the built candidate gpt-6-luna twice and gpt-6.1-sol once.

**Codex's columns with the route** (the branch's runner in a side container, through the console, one
worker):

| connection | models | scenarios passed | what did not |
|---|---|---|---|
| Vercel | 12 | 58 of 59 | gpt-5.6-luna's recall after a recycle |
| TokenRouter | 12 | 57 of 59 | gpt-5.4's switch into gpt-6.1-sol; one artifact turn on gpt-5.4 |
| OpenRouter | 3 | 15 of 15 | |
| a custom Responses endpoint | 2 | 8 of 8 | |
| OpenAI direct (route unchanged) | 2 | 10 of 10 | |
| Azure (route unchanged) | 2 | 10 of 10 | |

gpt-5.3-codex has no switch partner on Vercel or TokenRouter, nor has either model on the custom
endpoint, so those rows count four scenarios. Each miss was run again with and without the route:

- gpt-5.4's switch into gpt-6.1-sol on TokenRouter is refused with "cannot continue this task's
  earlier reasoning through this provider" three of three with the route and two of two without it,
  in the same time (132 to 173 s against 135 and 151 s). It is the condition recorded on 2026-09-10
  for that route: its upstream accounts cannot open each other's encrypted reasoning. The relay
  logged the provider's 400 once per turn.
- The artifact turn on gpt-5.4 that produced no file passed two of two on the retest with the route,
  and two of two without it.
- gpt-5.6-luna's recall after a recycle answered the completion phrase three of three with the route
  and two of three without it: the luna tier's recall recorded under the gpt-6 line.

Also with the route: the family tour (one conversation, 1 of 1), the plugin matrix's five columns,
the custom harness and the browser column, all on codex. On the built candidate (0.29.4-rc.1): three
models on Vercel 15 of 15, two on TokenRouter 10 of 10, two on the custom endpoint 8 of 8, the plugin
columns 5 of 5.

**Not measured.** A Codex turn whose provider stays silent past the relay's wait: the relay ends such a
call with its reason, as for every other base, and Codex was not driven into that case here.

## How much a model thinks (2026-10-05)

A turn can ask for a thinking level: `reasoning: {"effort": ...}` on a task, `reasoning_effort` on a
harness, one of none, minimal, low, medium, high, xhigh. This section is what was measured to make
that true, and it is the source of the table in `runner/reasoning.py`.

**Method.** One question with a short answer, sent with no setting and then once per setting, straight
at each provider through a connection of hr-test (`scripts/support-matrix/thinking/probe.py`, run as a
shell command of a turn so no key leaves the instance). Judged by the provider's own usage:
`reasoning_tokens`, with output tokens and elapsed time where a provider gives no such count. Seven
routes (Vercel, TokenRouter, OpenRouter, OpenAI, Azure, Google AI Studio, and Anthropic's Messages API
as TokenRouter passes it through), 66 model ids, three API shapes, about 900 calls. One sample per
cell: the direction is the finding, not the number.

**What it showed.** No field means the same thing everywhere, and a level a model lacks is refused
with a 400, not ignored.

`reasoning_effort` on Chat Completions:

| models | Vercel | TokenRouter | OpenRouter | the vendor directly |
|---|---|---|---|---|
| gpt-5.2, 5.3-codex, 5.4, 5.4-mini | none, low to xhigh; `minimal` 400 | the same | all six | OpenAI and Azure: none, low to xhigh |
| gpt-5.5, 5.6 line, 6-luna, 6-sol | all six | all six | all six | none, low to xhigh |
| gpt-6.1-sol, gpt-6-astra | `none` accepted, not honoured | `none` 400 | `none` 400 | `none` 400 |
| Claude, 4.5 to 5.5 | all six move it; opus-5.5 ignores `none` | accepted; the usage carries no count | the 5.5 line: `none` 400 | (Messages, below) |
| Gemini 3 line | only `low` differs; `none` and `minimal` read as MORE | ignored | minimal, low, medium, high; `none` 400 | Google: none to high; `xhigh` 400 |
| Grok 4.3, 4.5, 4.6 | two tiers; `none` reads as low | minimal to xhigh, in order; `none` 400 | the same; `none` 400 | |
| DeepSeek v4 flash, v4.1 flash, v4 pro | `none` is off, the rest is on | the same; v4-pro `none` 400 | the same | |
| Kimi k3 | `none` off; levels | `none` off | `none` off | |
| Qwen 3.7-max, 3.8-flash | `none` off, the rest on | the same; low and medium 400 against the token cap | the same | |
| Mistral medium 3.5 | none and high; minimal, low, medium 400 | none and every level | the same | |
| Step 3.7 flash | minimal to xhigh, in order; `none` reads as more | the same | `none` 400 | |
| MiniMax m3, Ling 3.0 flash, Nemotron 3.5 lightning, Hunyuan 3 | `none` off, the rest on | | the same | |
| GLM 5.3, Kimi k2.7-code, Llama, Nemotron 3 super | nothing moved it, or it does not think | | | |

The Responses API (`reasoning.effort`, OpenAI models only): as the first three rows, and `minimal` is
a 400 on every route for every model tried, so `minimal` is never sent to an OpenAI model.

Gemini needs Google's own setting where the field fails, and each aggregator keeps it under its own
key. Through Vercel, `providerOptions.google.thinkingConfig` with `thinkingBudget: 0` for off and
`thinkingLevel` for minimal, low, medium and high: gemini-3.5-flash 1,302 thinking tokens with no
setting, 0 at a zero budget, about 600 at low, about 1,900 at high. Through TokenRouter the same
setting under `extra_body.google.thinking_config` moves gemini-3.5-flash (0, 605, 1,636, 2,001) and
nothing else: 3.6, 3.7, 3.8 flash and the lite models answered to no setting there. Per model: the
pro model and the 3.7 and 3.8 flash models refuse a zero budget and `minimal` ("only works in
thinking mode", "Thinking level MINIMAL is not supported"); the lite models do not think unless
asked, and Google refuses `none` for them, so `none` there sends nothing.

Anthropic's Messages API, read through TokenRouter's pass-through (the API's own refusals came back
with their request ids):

| model | off | a level |
|---|---|---|
| claude-haiku-4.5 | `thinking: disabled` | a budget (`enabled`, `budget_tokens`); adaptive and effort are 400 |
| claude-sonnet-4.6 | `disabled` | adaptive with `output_config.effort` low, medium, high, max; `xhigh` 400 |
| claude-opus-4.8 | `disabled` | adaptive with an effort; `enabled` 400 |
| claude-sonnet-5, claude-opus-5 | `disabled` | adaptive with an effort |
| claude-sonnet-5.5 | `between_tools`, the API's own word; `disabled` 400 | adaptive with an effort, xhigh and max included |
| claude-fable-5.1 | cannot be turned off (both spellings 400) | adaptive with an effort |

**The rules that follow from it** (`runner/reasoning.py`):

- A level is sent only where a row above showed it accepted. A model that lacks the level asked for
  gets the nearest one it has; `none` is given only to a turn that asked for it, and a model that
  cannot be turned off gets its lowest level instead.
- A model or a route that was not measured gets nothing sent and the turn's record says
  `"applied": "default"`. A route is known by its host; a custom endpoint is not measured.
- A level must never be what fails a call. If the provider answers 400 or 422 to a body the relay
  wrote a level into, the body goes again as the client wrote it; if that is answered, the level is
  dropped for that model for the rest of the turn.
- One place by wire shape: the relay writes the level into Chat Completions, Responses, Messages and
  Google's own bodies, for every base whose calls pass it. Three bases set it their own way: Claude
  Code (`CLAUDE_CODE_EFFORT_LEVEL`, and `MAX_THINKING_TOKENS` for off and for the model that takes a
  budget), Codex (`model_reasoning_effort`, which also holds on OpenAI's own endpoint and Azure's),
  and the DeepSeek Harness driver, whose own relay calls the same functions.
- The record: `reasoning: {"effort": asked, "applied": level}` on the response, and the provider's
  count under `usage.output_tokens_details.reasoning_tokens`. The count is read where the relay reads
  usage and kept apart from the usage that prices a turn, which is unchanged.
- A turn and a harness that set no level send what they sent before: no route flag, no field, and
  the tests compare the bytes.

**Not measured, and said so in the table by absence:** Anthropic's API directly (the instance's key
was refused that day; its rows come from the pass-through and are taken to hold), Bedrock and Vertex,
any custom endpoint, and these ids: grok-4.20, grok-build-0.1, the other Qwen and Muse models,
hunyuan-4-preview, claude-fable-5 (taken to be as fable-5.1). The direct OpenAI and Azure Chat
Completions cells gave erratic counts for some models at some levels (zero where the Responses API
gave a normal figure for the same level); the levels are accepted there, and the bases that reach
those endpoints with OpenAI models speak the Responses API.

**The column, every base** (`scripts/support-matrix/thinking/run-column.py`): one harness per base, the
same task with no level and at none, low and high, through hr-test's connections (TokenRouter for
these models), judged from the turn's record and the provider's count of thinking tokens. gpt-5.4
wherever the base lists it. Run in a side container on the branch's runner, five bases at a time.

| base | model | no level | none | low | high |
|---|---|---:|---:|---:|---:|
| codex | gpt-5.4 | 270 | 0 | 248 | 516 |
| hermes | gpt-5.4 | 63 | 0 | 40 | 516 |
| opencode | gpt-5.4 | 393 | 0 | 313 | 921 |
| kilo | gpt-5.4 | 478 | 0 | 215 | 513 |
| openhands | gpt-5.4 | 677 | 0 | 287 | 650 |
| pi | gpt-5.4 | 0 | 0 | 230 | 485 |
| omp | gpt-5.4 | 0 | 0 | 262 | 640 |
| qwen | gpt-5.4 | 0 | 0 | 276 | 1,019 |
| cline | gpt-5.4 | 0 | 0 | 298 | 778 |
| kimi | gpt-5.4 | 0 | 0 | 242 | 666 |
| minimax | gpt-5.4 | 0 | 0 | 192 | 512 |
| grok | gpt-5.4 | 0 | 0 | 44 | 100 |
| aider | gpt-5.4 | 0 | 0 | 313 | 512 |
| agentzero | gpt-5.4 | 0 | 0 | 314 | 638 |
| cheetahclaws | gpt-5.4 | 0 | 0 | 402 | 797 |
| gemini | gemini-3.5-flash | 3,158 | no count | 2,531 | 4,125 |
| goose | gpt-5.4 | 12 out | 12 out | 302 out | 652 out |
| dsh | gpt-5.4 | 12 out | 12 out | 321 out | 698 out |
| claude-code | claude-haiku-4.5 | 7,678 out | 859 out | 2,145 out | 7,757 out |

19 of 19 bases that have a model with levels pass: every level asked is recorded as applied, none
spends no thinking tokens, low spends fewer than high, and a turn with no level carries no
`reasoning` on its record. System One has no model with levels and offers none. "out" is output
tokens, where the turn has no thinking count: goose's and the DeepSeek Harness driver's calls do not
give the relay one, and Anthropic gives none. On Gemini the provider left the count out of the answer
that spent none (605 output tokens against 13 at the other levels: the answer written out).

Claude Code's row is the weakest judge in the table and is read that way. Anthropic gives no thinking
count, the level reaches the model as a budget (a ceiling, not a target) and the answer is written
out at length, so one sample per level can cross: on Anthropic's own endpoint, three samples per level
gave 791, 810 and 622 output tokens at none, 2,402, 1,700 and 2,128 at low, and 5,195, 2,838 and
1,863 at high. Off is unmistakable; low below high holds on the sums (6,230 against 9,896) and not on
every pair. The row above is the first run, through TokenRouter.

**The same build, checked through the console and the API** (the candidate's image with the branch's
runner and gateway, the day's last code):

- The Thinking control on a harness's settings page, at 1440, 1024, 768 and 390 wide: in view, no
  sideways scroll. Its options are the model's own (gpt-5.4: Model default, Off, Low, Medium, High,
  Extra high; gpt-6.1-sol: the same without Off). Saved, reopened, still High. A level kept from
  another model stays selected and the form says its tasks get the nearest one.
- A task on that harness with no level of its own: `{"effort": "high", "applied": "high"}`, 15
  thinking tokens. The same task asking for `none` itself: applied none. A value that is not a level:
  400 "reasoning.effort must be one of: none, minimal, low, medium, high, xhigh".
- hermes with gpt-5.4, asked to write a 9,000 word file as its first action: completed after 619 s
  with 13,340 output tokens, where 0.29.4 stopped it at 93 s.
- CheetahClaws: 4 of 4 plain turns carry their usage.
- A task sent with `backend: "claude-code"` completes, as with `backend: "claude"`.

What "no level" means differs by base on the same model, which the column shows for the first time:
gpt-5.4 does not think unless asked, and eleven bases leave it so; Codex asks for medium itself (its
own config default), OpenHands asks for high for every model, and hermes, opencode and kilo ask for
something of their own. A level set on the harness or the turn replaces all of these.

**Three defects the column and the hosted service found, fixed with it:**

- *A turn's record read "default" for a level that had been applied.* pi and omp keep their relay
  placeholder in a file, not the environment, and the record was read through the environment: pi with
  gpt-5.4 spent 12, 252 and 441 output tokens at none, low and high and recorded default three times.
  A turn now keeps the routes it registered and reads its record off them.
- *CheetahClaws turns had no usage at all.* The relay added a streamed call's usage to the route when
  the stream ended, which is when the provider closes it, not when its last event passes; a client
  that is done at `[DONE]` read the route before its own call was on it. On the published 0.29.4,
  8 of 8 plain CheetahClaws turns came back with no usage; with each chunk's figures folded in before
  the chunk is forwarded, 0 of 6. When this began was not measured (the relay has forwarded streams
  as they arrive since 0.29.1, which is the likely start).
- *hermes stopped a turn whose first answer was long.* hermes writes a message into its database only
  when it is complete, so a first answer that streamed for more than 90 s looked like a hung call and
  was stopped (found on the hosted service; on 0.29.4 here, hermes with gpt-5.4 asked to write a
  9,000 word file as its first action ended `incomplete` after 93 s with nothing written). The guard
  now also asks when a provider last sent an event on the turn's route; the CLI that hangs after its
  provider answered is still caught.

Also from the hosted service: `backend` on POST /v1/responses took a base's id ("claude-code") as the
backend, matched no model, and refused every model as having no provider there. It names the base's
backend now.

## Where a turn's fixed seconds went (2026-10-05, 0.30.1)

Two changes ported from the hosted service, where both were found and first measured, and measured
again here through a streamed task (`stream: true`, timed at the client): when the first text
arrives, in how many steps the answer grows (text arriving after a pause of 0.1 s or more), and how
long after the last text the task says it is complete. Warm turns of one session, medians.

**The gateway asked for a turn's events every 1.2 s.** So the first text waited up to that long, a
streamed answer grew in jumps of that size, and the end was heard at the next ask. The runner now
holds the request (`GET /turn/{id}?wait=`) until it has an event, the turn is done, or the wait has
passed, and says `held`; the gateway asks again at once, writes the durable trace once per interval
instead of once per answer, and paces itself the old way when an answer does not say held (an older
runner) or a request failed. The duties that counted polls (the lease, the heartbeat, the durable
cancel check) count the clock. `HARNESS_RESP_HOLD_S` sets the hold (3 s; 0 asks the old way). The
hold waits on the runner's event loop, not on a worker thread: one runner serves every session of an
instance, and 120 turns held at once answer together in the test.

**A checkpoint carried what a CLI rebuilds for itself.** omp's two native binaries, Codex's plugin
catalogue and the DeepSeek Harness's unpacked packages travelled in the workspace's archive after
every turn. They are left out now (`_REBUILT_CACHES`). opencode's npm cache is deliberately not:
rebuilding it cost a turn 20 s on the hosted service.

| base, model | | 0.30.0 | with the hold | with the hold and the smaller checkpoint |
|---|---|---:|---:|---:|
| pi, deepseek-v4-flash | first text | 2.71 s | 2.68 s | 2.88 s |
| | steps | 2 | 5.5 | 7.5 |
| | last text to complete | 0.20 s | 0.18 s | 0.15 s |
| codex, gpt-5.4 | first text | 4.13 s | 3.79 s | 3.98 s |
| | steps | 3 | 7 | 8 |
| | last text to complete | 3.72 s | 3.19 s | 0.22 s |
| | whole turn | 10.4 s | 8.9 s | 6.0 s |
| omp, gpt-5.4 | steps | | 7 to 9 | 10.5 |
| | last text to complete | | 7.5 s | 0.37 s |
| | whole turn | | 15.4 s | 9.6 s |
| claude-code, claude-haiku-4.5 | first text | 3.99 s | 4.22 s | |
| | steps | 1 | 1 | |
| hermes, gpt-5.4 | first text | 28.7 s | 23.7 s | |
| | steps | 1 | 1 | |

Read with their sizes: four to eight turns per cell, and the model's own time is most of "first
text". What moved beyond noise is the number of steps a streamed answer grows in (pi 2 to 7.5, Codex
3 to 8) and the end of a turn on the two bases whose checkpoint shrank (Codex 3.7 s to 0.2 s, omp
7.5 s to 0.4 s). Claude Code and hermes hand over whole messages, so their answers arrive in one step
either way; hermes's first text is its whole answer and its difference here is the model's.

Not ported, with the reason: the hosted change that lets a turn's record writes run beside the loop
(each write costs about 0.4 s there; here the store is a local file), and the per-turn timing log
line that found these.

## The thinking level behind a broker (2026-10-06, 0.30.2)

The hosted service took the thinking level from 0.30.0 and ran the same column against it, and its
port found what the owner-trust measurement here could not: in broker trust the gateway's own broker
sits between the agent and the provider, and it removes the thinking controls (`thinking`,
`context_management`, `output_config.effort`) from every Anthropic-shape request. That rule exists
for what Claude Code sends by itself, which some model versions refuse. A level the turn had asked
for was removed with it: the turn ran at the model's default and its record said the level had been
applied. This tree has the same broker and the same rule.

Fixed the way the hosted service fixed it: the per-turn credential the agent is handed carries the
level as a fourth field, only when the turn asked for one, and the broker keeps the thinking controls
of a request that arrives under such a credential. A turn that asked for nothing carries the
credential it always did and its requests lose the controls as before. On the OpenAI shapes the
broker never removed anything of the thinking group (`reasoning_effort`, `providerOptions`,
`extra_body` all pass), which the hosted service pinned in a test and showed live: a Gemini model at
`none` spent 0 thinking tokens through its broker and TokenRouter.

Measured here in broker trust (a side container with `HR_SANDBOX_TRUST=broker`; the image's
default is owner trust, where the agent holds the key and no broker is in the way). Claude Code with
claude-haiku-4.5 through the broker and TokenRouter, output tokens of three runs per level:

| | none | low | high |
|---|---|---|---|
| 0.30.1 | 690, 726, 768 | 838, 782, 689 | 931, 774, 712 |
| with the fix | 730, 538, 824 | 2,277, 2,256, 1,686 | 2,284, 2,754, 3,801 |

On 0.30.1 every turn recorded its level as applied and all nine spent what a turn with no level
spends. hermes, pi and Codex with gpt-5.4 passed the column in broker trust before and after (their
level rides `reasoning_effort` through the relay and the broker, which the gateway makes possible by
naming the route): the first end-to-end run of the level behind this tree's own broker.

The column's judge passed the 0.30.1 row: on output tokens "low below high" held by noise (2,309
against 2,417). It now also asks, where output tokens stand in for a missing count, that low spend
at least half again what none does; the 0.30.1 row fails it and every earlier pass still passes.

The hosted column, as that session reported it (`run-column.py` from 915c834, one run per level,
gpt-5.4 unless said; thinking tokens at none, low, high):

| base | none | low | high | |
|---|---:|---:|---:|---|
| hermes | 0 | 62 | 403 | |
| goose | 0 | 278 | 831 | |
| cheetahclaws | 0 | 302 | 471 | |
| kimi | 0 | 224 | 516 | |
| qwen | 0 | 434 | 779 | |
| codex | 12 out | 271 out | 501 out | no count: its calls go to the broker without passing a relay there |
| claude-code, claude-haiku-4.5 | 721 out | 1,964 out | 2,248 out | with the broker keeping the controls |
| opencode | | | | recorded default at every level on the first image |

7 of 8. opencode, pi and omp talk to the broker directly on the hosted service (they ride the relay
here for every keyed turn), so the relay never saw their calls; there they now take the relay for a
turn that asks for a level. That difference between the trees is the hosted one's and is recorded
here because the column is shared.

With that change the hosted session ran the column again and reported 11 of 11, these rows among
them (thinking tokens at none, low, high):

| base | none | low | high | |
|---|---:|---:|---:|---|
| pi | 0 | 243 | 516 | |
| omp | 0 | 252 | 456 | |
| opencode | 0 | 272 | 804 | |
| codex | 12 out | 233 out | 530 out | output tokens, as above |

Not run on the hosted service at the time of writing: the Gemini CLI base, and most bases at more
than one model.

## How long a thinking model says nothing, and the relay's wait (2026-10-06, 0.31.0 and 0.31.1)

The relay ends a model call that sends no event for `HR_RELAY_UPSTREAM_TIMEOUT_S`. The default was
600 s and is 180 s from 0.31.0, the value the hosted service runs. Before changing it the cost was
measured, because the old default had been chosen for it: a model that thinks without sending
anything looks, on the wire, like a provider that has stopped.

One hard three-part counting problem, streamed, at each model's highest thinking level, straight at
the provider through a connection of hr-test, with the relay's own wait raised to 1,200 s so it could
not interfere. An event is a `data:` line; a keep-alive comment line is not one, here as in the relay.
One sample per cell. The longest run with no event:

| model, level | TokenRouter | Vercel |
|---|---:|---:|
| gpt-5.5, xhigh, Chat Completions | 201 s | 11 s |
| gpt-5.5, xhigh, Responses | 30 s | 61 s |
| gpt-6.1-sol, xhigh | 19 s (Responses) | 15 s (Chat Completions) |
| gpt-6-sol, xhigh, Chat Completions | no answer in 1,200 s | |
| gemini-3.1-pro-preview, high | 205 s | 4.5 s |
| claude-opus-5, xhigh | 35 s | |
| claude-opus-5.5, xhigh | | 211 s |
| grok-4.6, xhigh | 13 s | 12 s |
| deepseek-v4-pro, xhigh | 2 s | |
| kimi-k3, high | | 0.7 s |
| qwen3.7-max, high | | 2 s |

Whether thinking shows on the wire is a property of the route and the request shape, not of the
model. Where a route forwards reasoning as it happens the stream is never quiet for long, and that
was 13 of the 16 cells. Three were silent for over 200 s and then answered: OpenAI's Chat Completions
through TokenRouter sends nothing until the first token of the answer (the same model on the
Responses API, or through Vercel, streams throughout), TokenRouter's Gemini channel likewise, and
Claude Opus 5.5 through Vercel sent one event and then keep-alive lines for 211 s. One call never
answered at all.

So the two waits buy different things. At 600 s the three silent answers complete and the call that
never answers holds its turn for ten minutes. At 180 s that call ends in three minutes and the three
answers are cut off as "the provider did not answer". Richard chose 180 s for both the hosted service
and this default with these numbers in front of him. An operator who runs such models at such levels
on such routes raises the variable; the bases that speak the Responses API to OpenAI models (Codex,
hermes, opencode, kilo) were not exposed in any cell.

**The decision was reversed the same day (0.31.1): the default is 600 s again.** Asked to find a way
to make the three silent cells speak, a second measurement found the silence was not three cells. The
same problem and levels, each call watched for 430 s, now also straight at the vendors and through
OpenRouter, and with every request field that might ask a route to show its thinking:

| Chat Completions, longest run with no event | TokenRouter | Vercel | OpenRouter | the vendor itself |
|---|---:|---:|---:|---:|
| gpt-5.5, xhigh | over 430 s (3 of 3) | 11 s | 61 s | OpenAI over 430 s; Azure over 430 s |
| gemini-3.1-pro-preview, high | 187 s, 234 s | 4.5 s | 4.8 s | Google 141 s |
| claude-opus-5.5, xhigh | | 211 s | 10.6 s | not measured |

- **OpenAI's Chat Completions API sends nothing while a reasoning model thinks**, and that is the
  API, not a reseller: five calls of five passed 430 s without an event, direct, on Azure and through
  TokenRouter (where even the status line waits for the first token: headers at 201 s in the first
  measurement). `stream_options.include_usage` and `include_reasoning` change nothing; `reasoning` is
  refused as an unknown parameter. On the Responses API the same model sent an event at least every
  30 s on all three, and about every 13 s with `reasoning.summary: "auto"`.
- **Gemini** on Google's own endpoint speaks when asked with
  `extra_body.google.thinking_config.include_thoughts: true` (longest gap 4.6 s), but the thoughts
  arrive inside `delta.content` as `<thought>...</thought>`, with the answer after the closing tag in
  the same chunk, so a base would show them as its answer. Through TokenRouter the field does nothing.
- **Claude Opus 5.5 through Vercel** speaks when asked with `providerOptions.anthropic.thinking:
  {"type": "adaptive", "display": "summarized"}`: a 255 s think with a longest gap of 6.8 s, in
  `delta.reasoning` and `reasoning_details`, not in the content. `reasoning: {"enabled": true}` and
  `include_reasoning` do nothing (195 s and 209 s of keep-alive lines).
- OpenRouter spoke on all three models, and Vercel on OpenAI's and Google's.

So at 180 s every base that speaks Chat Completions to an OpenAI model was exposed at a high level on
a hard problem, and that is most bases. On those routes a call that is thinking and a call that is
stuck look the same on the wire. Richard was offered the two request-field fixes and a longer wait
for OpenAI's chat calls alone, and chose the old wait for everything. Neither fix was built; the
fields above are recorded for whoever wants a shorter wait later. One sample per cell unless said,
and how long a model thinks on one problem varies widely (the same Claude call took 29 s and 211 s).

The same problem as a real task on the 0.31.1 candidate (pi, gemini-3.1-pro-preview through
TokenRouter, thinking level high). With the wait set to 180 s, as 0.31.0 shipped it: the relay cut the
model call four times, 183 s apart, pi retried each time, and the task failed after 737 s with "the
provider did not answer". At the default, five runs: all five completed, after 28, 125, 179, 212 and
494 s, with no cut; gpt-5.5 at xhigh straight at OpenAI completed after 128 s. So the shorter wait did
not end a slow task sooner: it turned a task that finishes into one that fails four waits later.

## An Azure connection that signs in with Microsoft Entra (2026-10-06, 0.31.0)

For an organization that issues no API keys for its Azure resources: the connection is an application
in the organization's own Entra directory (tenant ID, client ID, client secret), and the gateway's
broker asks Entra for a token by the client-credentials grant and presents it as the bearer where a
key connection sends `api-key`. Built on the hosted service and taken from there with its tests.

What this tree adds is one rule. In owner trust, the image's default, a connection's key is handed
to the agent. This connection has no key to hand, only a secret that buys a token good for about an
hour, and a turn may run for six. So a connection of this kind goes through the gateway's broker in
every trust mode, and the broker asks again as the token ages.

Measured on the release's candidates in side containers on the test VM, in owner trust, with a test
application in our own directory holding the "Cognitive Services OpenAI User" role on one Azure
OpenAI resource and one Foundry resource:

- **Four bases completed on the Entra connection**: pi and goose and hermes with gpt-5.4-mini, Codex
  with gpt-5.4, each served by that connection. The gateway signed in once for all four
  (`[entra] signed in as application ••••1234; asking again in 3299 s`, one line per sign-in).
- **The agent holds neither the secret nor a token.** Checked while a pi turn was running a shell
  command: none of the container's processes (the agent's and its shell's among them, read with the
  rights to read every process's environment and command line) and none of 5,995 workspace files
  held the client secret or an access token for Azure. The secret itself is not readable as text
  anywhere on the data volume.
- **The sign-in is renewed inside a running turn.** A token is good for 3,599 s and the gateway asks
  again 300 s before that. One pi turn with gpt-5.4 was started 119 s before a sign-in was due for
  renewal and ran six 85 s shell commands, one model call after each: 04:40:39 to 04:49:17 UTC. The
  sign-in it began on was made at 03:47:37 (due again at 04:42:36, dead at 04:47:36). Its first two
  model calls went out on that token; the third, at 04:43:32, made the gateway sign in again (the
  log's line is at 04:43:32.7); the last two came after the first token's own expiry. The turn
  completed with six tool calls and the six times. Before that, with the instance idle for an hour
  and forty minutes past a token's expiry, the next turn signed in again by itself and completed.
- **No role on the resource**: the same application pointed at a resource it has no role on. Azure's
  own 401 reaches the turn: `Your azure connection was refused: ... {"code":"PermissionDenied",
  "message":"The principal ... lacks the required data action
  Microsoft.CognitiveServices/accounts/OpenAI/responses/write ..."}`.
- **A directory Entra does not know**: the turn fails in 2 s on pi with `Your azure connection was
  refused: ... Microsoft Entra refused this connection's sign-in: AADSTS90002: Tenant '...' not
  found. ...`. Nothing is remembered of a refusal: the next call asks again.
- **A key connection is untouched**: pi and Codex on the same Azure resource by API key completed,
  handed the key as before.
- **The form** on the Integrations page at 1440, 1024, 768 and 390 wide: "Sign in with" offers API
  key and Microsoft Entra, the fields change to the directory ID, the application ID and the client
  secret, a directory written as a name is refused with the field's own label, a saved connection
  comes back with the secret masked and no key.

Two defects came out of the measuring and are fixed in the release, here and on the hosted service:

1. A sign-in Entra refuses came back from the broker as a 502. Codex reconnected five times before
   giving up (28 s), and a 502 is not a refusal to the gateway, so the turn was free to try its next
   connection, which is what the refused-key rule exists to prevent. A sign-in Entra answers with
   400, 401 or 403 is now a 401 from the broker, as a refused API key is. Codex still makes its
   reconnect attempts on a 401, as it does on a refused key, and now fails in 8 s. Entra throttling
   or failing stays a 502.
2. The turn said "Your azure key was refused" on a connection that has no key. It says "connection".

Not measured here:

- **A completed turn on a Foundry resource.** This tree's catalog has no model that the one Foundry
  resource we could use has deployed, and only a custom connection may name a model outside the
  catalog. What was observed is the next thing down: a catalog model asked of that resource came back
  `404 DeploymentNotFound`, not a refusal, so the resource accepted the application's token. The
  hosted service completed a pi turn on that resource through the same code.
- A sovereign cloud (`HR_ENTRA_AUTHORITY`), and a client secret that expires or is rotated while a
  turn runs.

## A build said ready before its version was active (2026-10-06, 0.31.0)

Issue #401: `test_the_turn_gets_the_path_the_variables_and_the_instructions` failed once in CI with
"409: the environment has no built version" and passed on the rerun. It was not a flake. A build
wrote its record as `ready` and made the version active in the next statement, and the record is what
every reader waits on: the test, the console's build view, a script polling the API. A turn started
in between was refused. On a normal disk the window is too short to meet; a slow CI disk met it.

The version is now made active, and its mount made, before the record is written, and if any of the
three steps fails the active version goes back to what it was (a failed build never becomes active,
as before). A test asks the question at the instant the ready record is written and fails on the old
order. On the candidate: an environment with a pip, an npm and an apt package built in 9 s, a turn
started in the same instant its record read ready completed using the environment's package, and the
environments column passed on pi, Codex and Claude Code, 9 of 9 tasks.

## Who may run a harness (2026-10-06, 0.31.2)

Until this release the harness id alone was what ran a harness: a comment in the code called it
"the run capability", written for a marketplace in which callers run a harness and its owner pays.
Anyone who knew an id (console links carry it) could start a task on the harness, with the owner's
connected plugs and database, on the owner's connections. Richard's rule, made on the hosted service
first and the same here: "a harness can run by id and workspace's API key".

The caller's organization must be the harness's; a caller narrowed to a workspace runs that
workspace's harnesses, a harness from before workspaces counting as the Default Workspace's; a key
for the whole organization runs any of its harnesses; a built-in base has no owner. The refusal is
`404 harness_not_found`, what every other route answers for a harness that is not the caller's. It
is the same test the harness list already applied, so what a key lists, it runs, and a harness made
with a key is stamped with that key's workspace, so what a key makes, it runs.

Candidate `0.31.2-rc.1` in a side container on the test VM, on a copy of an instance with 77 harnesses (36 stamped with the Default Workspace, 41 from before workspaces). Keys were minted for two workspaces and for the whole organization, and a harness was made with workspace one's key:

| Caller | Result |
|---|---|
| Workspace one's key, its own harness | completed |
| Workspace two's key, that harness | `404 harness_not_found`, and the harness is not in its list |
| A key for the whole organization | completed |
| Workspace two's key, a built-in base | completed |
| Another organization (the gateway's internal door, another organization named) | `404 harness_not_found`, also when it names the right workspace |
| The console in workspace one | completed |
| The console in workspace two, and in the Default Workspace | `404 harness_not_found` |
| The Default Workspace's key, a harness made before workspaces | completed |

Through the console itself (Playwright): a harness created and run on pi, with its skill, script and tool policy. Claude Code tasks complete, and all plugin checks pass on Claude Code, Codex and pi, each of which makes its own harness and runs it.

## The built-in image skill in front of the media tools (2026-10-06, 0.31.3)

The built-in `imagegen` skill works only through a turn's image credential. With none its script
refuses: "image generation is not configured for this Harness. An operator needs to add an integration
that serves an image model". On the hosted service a pi agent whose harness also carried the media
tools read the skill first, took the sentence as final and told the person images were unavailable,
two runs of three, with `media_generate_image` one call away. This tree has the same skill, mounted by
default, and the same two ways to make an image, resolved from different tables: the skill's credential
from the image model map, the media tools' providers from the integrations by kind. So a turn can have
the second without the first: image models switched off, or broker trust without `HR_BROKER_IMAGES`.

On such a turn the built-in is now dropped and suppressed. Where the turn has no other way to make an
image the skill stays, which is where this tree differs from the hosted one: here the person asking is
the operator, and the refusal is what says what to add.

Candidate `0.31.3-rc.1` in a side container on the test VM, on a copy of an instance whose Videos kit harness carries the media tools. One request each ("make one image, then say MADE or CANNOT"):

| The turn | The image skill in the session | What the agent did |
|---|---|---|
| Media tools, an image credential (Claude Code) | present | made the image with the media tool |
| Media tools, no image credential (Claude Code) | absent | made the image with the media tool |
| No media tools, no image credential (pi) | present | ran the skill and answered "CANNOT image generation not configured" |

The image credential was removed by switching the instance's image models off on the Integrations document. Not reproduced here: the agent giving up in front of a working media tool. That was seen on the hosted service with a pi agent; Claude Code on this harness chose the media tool either way. What is shown here is that the skill is no longer offered in that state. Claude Code tasks complete, and all plugin checks pass on Claude Code, Codex and pi (the skill checks among them).


## Hermes: a refusal from a tool is not its server failing (2026-10-06, 0.31.4)

`hermes-agent` 0.19.0 keeps a circuit breaker per MCP server and bumps it on every error answer,
including one a live server gave on purpose: a tool result marked `isError`, "no such document".
Three in a row open the breaker, and for 60 s every tool of that server is refused with "MCP server
... is unreachable after 3 consecutive failures". On the hosted service an agent that had read three
wrong ids could then not use any tool of that server and told its person the service was down.

The patch (`runner/patches/hermes_mcp_breaker.py`, the hosted one) marks the error answers that came
from the server's own tool result and resets the breaker for those. Hermes is installed on an
instance's first start, not in the image, so the entrypoint applies it to the installed copy on every
start, which also repairs a volume installed before it existed.

A small tool server was run inside the side container, with one tool that refuses on purpose (`get_document` of an id that does not exist is an error answer) and one that always answers (`list_documents`). One Hermes task with gpt-5.4: four refused `get_document` calls, then `list_documents`.

| The instance | What `list_documents` returned |
|---|---|
| Published 0.31.3 | "MCP server 'company' is unreachable after 3 consecutive failures. Auto-retry available in ~50s." The server was up and answering. |
| Candidate `0.31.4-rc.1`, started on the volume 0.31.3 had installed Hermes into | `["doc-1"]` |
| Candidate, on a fresh volume (Hermes installed on that first start) | `["doc-1"]` |

On both candidate starts the log has one line, "Hermes: a tool's own error answer no longer counts against its MCP server", and Hermes's module holds the two marks. A restart applied nothing again and logged nothing. A plain Hermes task completes. An instance started without Hermes starts, logs nothing about it, and passes the usual checks (pi and Claude Code tasks, all plugin checks on Claude Code, Codex and pi).

The patch was run against the real `hermes-agent` 0.19.0 file: it changes two places and the result compiles (the test for this needs the file at hand and is skipped in CI, since Hermes is not in the image).

Not shown live: a server that cannot be reached still opening the breaker. When the tool server was stopped mid-task Hermes dropped its tools ("Unknown tool") before the breaker came into it. That half is covered by the test of the patched check, where an error that did not come from a tool's own answer still counts.
