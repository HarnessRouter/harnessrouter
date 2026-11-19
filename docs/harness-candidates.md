# Reviewed, not supported — why, and what would change it

The catalog on https://harnessrouter.ai/harnesses lists 51 harnesses and runs 30 of them. This page
is the other 21, plus durable-harness, reviewed later and added on 2026-11-18: what each one is,
why it is not a base here, and the one concrete thing that would reopen it. A row is closed when
the reason is a property of the product rather than a version of it, and open when a named artifact
or flag would clear it.

Checked 2026-11-03 against each upstream's current release. Licenses and activity are read from the
repository itself (GitHub's own license field, `pushed_at`, release assets and npm metadata), not
from a landing page. Where a reason says a flag or a surface exists, that is what the upstream
documents or its source says — the step before a column, not a substitute for one (see
[harness-verification.md](harness-verification.md)). **One row was then probed for real**: the
OpenClaw section below separates what was measured on 2026-11-03 from what was only read, and the
measurement reversed two things the documentation had implied. Every other row on this page is
desk work, which is what it is worth.

## License and upstream activity

Read on 2026-11-03 from the repository the catalog's own review cites. "Pushed" is GitHub's
`pushed_at`. The proprietary rows have no repository to read, and their liveness does not decide
anything: they fail on terms or on routing.

| Harness | License | Upstream repo | Stars | Last push | Alive? |
|---|---|---|---|---|---|
| OpenClaw | MIT | openclaw/openclaw | 393.8k | 2026-11-03 | yes, daily |
| QwenPaw | Apache-2.0 | agentscope-ai/QwenPaw | 37.3k | 2026-11-03 | yes, daily |
| Continue | Apache-2.0 | continuedev/continue | 36.4k | 2026-11-03 | repo yes; `extensions/cli` last touched 2026-06-18 |
| Crush | FSL-1.1-MIT | charmbracelet/crush | 28.9k | 2026-11-03 | yes, daily |
| Roo Code | Apache-2.0 | RooCodeInc/Roo-Code | 24.3k | 2026-05-15 | no — archived 2026-05-15 |
| Skyvern | AGPL-3.0 | Skyvern-AI/skyvern | 23.3k | 2026-11-03 | yes, daily |
| Codebuff / Freebuff | Apache-2.0 | CodebuffAI/codebuff | 13.9k | 2026-11-03 | yes, daily |
| Z Code | Apache-2.0 | zai-org/ZCode | 8.4k | 2026-10-30 | yes (v3.17.1) |
| stagewise | AGPL-3.0 | stagewise-io/stagewise | 6.8k | 2026-11-02 | yes |
| Command Code | none at all | CommandCodeAI/command-code | 4.2k | 2026-10-23 | yes |
| Gajae Code | MIT | Yeachan-Heo/gajae-code | 3.1k | 2026-11-03 | yes, daily (0.19.2) |
| Zoo Code | Apache-2.0 | Zoo-Code-Org/Zoo-Code | 2.1k | 2026-11-03 | yes (v3.94.0) |
| pool | proprietary EULA | poolsideai/pool (releases) | 441 | 2026-08-18 | releases yes (1.0.16) |
| PostQode | contradictory | none (support/community only) | — | — | unclear; npm package pulled at 1.0.3 |
| Ottili Coder | proprietary | `Ottili-ONE/coder-cli` → 404 | — | — | the CLI is gone |
| Swades Agent | claimed OSS | `Electroiscoding/Xerv` → 404 | — | — | nothing public |
| TeleClaw | proprietary | none (third-party repos only) | — | — | APK ships (v2.1.1) |
| Cursor | proprietary | none | — | — | product shipping |
| Junie | proprietary | none | — | — | product shipping (CLI in EAP) |
| Factory Droid | proprietary | none | — | — | product shipping |
| Verdent | proprietary | none | — | — | product shipping |

Seven clear both halves of "permissive license and a living upstream": OpenClaw, QwenPaw, Continue,
Codebuff/Freebuff, Z Code, Gajae Code and Zoo Code — plus Roo Code, which has the license and is
archived. Six of the seven are closed below on something other than license or liveness.

## The bar a candidate has to clear

Four requirements decide most of these rows, and three of them come straight from the verification
rules:

1. **The model is ours to route.** A turn runs on the connection and the model id the caller asked
   for, through the relay. A CLI that only talks to its vendor's backend cannot satisfy rules 1 and
   2 of [harness-verification.md](harness-verification.md), whatever else it does well.
2. **A headless surface with continuity.** One-shot invocation, a machine-readable result, and a
   session that a follow-up can continue.
3. **An installable Linux artifact, pinned.** One binary or one wheel per platform with a digest to
   compare, as every entry in `docker/entrypoint.sh` has. A build of a monorepo inside the image is
   a different kind of entry and costs a maintainer decision.
4. **A license this repository can carry**, and an upstream that is alive.

## Closed: the model cannot be routed here

These have good headless surfaces. They serve their own models, so the product's own promise cannot
be kept on them.

| Harness | License | Upstream | Why it is closed |
|---|---|---|---|
| **Cursor** | proprietary | active | `cursor-agent -p` with `--output-format json\|stream-json`, `--resume [chatId]` and `--model` is a complete headless surface, but the only credential is `CURSOR_API_KEY` and no custom base URL or BYOK provider is documented: the turn runs on Cursor's backend. |
| **Junie** | proprietary (JetBrains) | active, CLI in EAP | Headless runs take a JetBrains token (`junie --auth=…`); no custom provider, base URL or own key is documented. Models are JetBrains AI's. |
| **Codebuff / Freebuff** | Apache-2.0 (repo), ads-funded service | active | Two reasons, both re-checked today. There is still no headless mode: `cli/src/cli-args.ts` offers `--continue [conversation-id]`, `--cwd`, `--agent`, `--lite/--max/--plan`, `--trust-agents` — no print mode and no JSON. And the `@codebuff/sdk` path, which does carry events and continues a run with `previousRun`, needs a Codebuff API key and runs the model on Codebuff's backend. Ads (`gravity_index`) and telemetry cannot be turned off. First measured 2026-09-26 (batch 2, phase 1), shelved 2026-09-27. |

## Closed: license

| Harness | License | Upstream | Why it is closed |
|---|---|---|---|
| **Crush** | FSL-1.1-MIT | very active (28.9k★) | The Functional Source License is not MIT today; each release converts to MIT two years after it ships. A release old enough to be MIT is not a release worth offering. |
| **Skyvern** | AGPL-3.0 | very active | Outside what this repository carries. It is also an MCP-and-API browser-automation product rather than a coding harness over a workspace. |
| **stagewise** | AGPL-3.0 | very active | Same license answer. It is an agentic IDE; the review found no public machine interface. |
| **Command Code** | **none** | active (4.2k★) | The repository ships no LICENSE file at all, so every right is reserved by default. Nothing can be vendored or installed from it until the owner publishes terms. |
| **PostQode** | contradictory | unclear | The npm package declares Apache-2.0 while its own README and terms say the software is proprietary to ElevenXN, all rights reserved, licensed and not sold; the package was pulled from the registry at 1.0.3. A contradictory license is a no. |
| **Ottili Coder** | proprietary | the CLI is gone | `Ottili-ONE/coder-cli`, the repository the review cited, now answers 404; the org publishes an `ottili-proprietary-license` repository instead. |
| **pool** (poolside) | proprietary EULA | active | `LICENSE.md` is "© Poolside. All rights reserved", under the EULA at poolside.ai/eula. See the licensing call below: technically this is the strongest of the proprietary set. |
| **Verdent** | proprietary | active | A desktop product (Mac download, trial sign-up). No public machine interface was documented at the review, and none since. |

## Closed: no product to drive

| Harness | Why it is closed |
|---|---|
| **TeleClaw** | An Android application (teleclaw.info, v2.1.1, 27 MB APK) that turns a phone into an agent host. There is no server-side headless interface to drive, and the product's own source is not published; the repositories that carry the name on GitHub are third-party. |
| **Swades Agent** | The review cited `Electroiscoding/Xerv` beside xerv.netlify.app. That repository answers 404 today, so the claim of open source has nothing public behind it. |
| **durable-harness** | Apache-2.0, alive (vercel-labs/durable-harness, 320 stars, pushed 2026-11-11), and not an agent: it is a durability and orchestration layer around the CLIs this product already runs — its own description names Claude Code, Codex, OpenCode, Pi and fx, and four of those are in `HR_BACKENDS`. Reviewed at `durable-harness@0.0.2` (2026-11-18). Its one published bin takes `vercel-json` and `sandbox prepare` and nothing else, so a turn is started by calling a TypeScript API from inside a Next.js/Node app; the Claude-family harnesses run only in a Vercel Sandbox (`sandbox_required` otherwise); the model is fixed on the agent at module scope and neither `StartOptions` nor `SendOptions` carries one, so the switch scenario has no API to drive; and there is no skill loader, no instruction-file convention (`settingSources: []` on purpose) and no per-invocation MCP configuration. This is QwenPaw's reason — it drives other agents rather than being one — plus a hosted dependency. **Reopens on:** a one-shot turn subcommand on its own published bin, `durable-harness run --session <id> --model <gateway-id>` writing NDJSON to stdout, on a `virtual()` workspace under `WORKFLOW_TARGET_WORLD=local`. Even then it would be a durability variant of the claude, codex, opencode and pi rows rather than a new base. |
| **Roo Code** | Apache-2.0 and the artifact is exactly the shape we want — `cli-v0.1.17` (2026-03-04) ships `roo-cli-linux-x64.tar.gz` and `-arm64` with `.sha256` beside each. But the repository was **archived on 2026-05-15**: the upstream is dead. Its live fork is Zoo Code, below. |

## Open, with a named re-check trigger

Each of these is Apache-2.0 or MIT with a living upstream. The reason is a missing artifact or a
missing flag, so it is worth looking again when that one thing appears — and not before.

### Zoo Code — public now; still no CLI artifact

Zoo-Code-Org/Zoo-Code, Apache-2.0, 2.1k★, pushed daily. [PR #541](https://github.com/HarnessRouter/harnessrouter/pull/541)
closed it as "a roo-code fork whose CLI is private". **Half of that has changed**: the monorepo is
public and `apps/cli` is in the tree — `@roo-code/cli` 0.1.17, bin `roo`, with `-p/--print`,
`--session-id`, `--oneshot` and its own NDJSON event schema. What has not changed is the artifact:
the package is `"private": true` with no npm publish, and every release ships only
`zoo-code-<version>.vsix`. Its own `apps/cli/install.sh` looks for `cli-v*` releases of
`RooCodeInc/Roo-Code` — the archived upstream — so it does not install this fork's CLI either.

**Re-check when:** Zoo Code publishes a `cli-v*` release with platform tarballs, or publishes the
CLI to npm. Until then the cost is a pnpm build of a 275 MB monorepo plus the extension bundle the
CLI loads with `-e <path>`, which is requirement 3 above and a maintainer decision.

### Z Code — the headless surface is real, the Linux artifact is not

zai-org/ZCode, Apache-2.0, 8.4k★, pushed 2026-10-30. PR #541's reason holds at **v3.17.1**: the
release assets are `ZCode-3.17.1-mac-{arm64,x64}.{dmg,zip}` and `-win-{arm64,x64}.exe`, with no Linux
package and nothing on npm (`@zcode/cli`, `zcode-cli` and `@zai-org/zcode-cli` are all absent or
unrelated). The CLI itself is in the tree at `apps/zcode-cli` (private package `@zcode/cli`, with
`build:sea` and `cli:upload-sea` scripts, so a single-file executable is built somewhere and not
published), and the headless surface PR #541 described — `zcode --prompt` with
`--output-format stream-json`, a provider configuration file we can point at the relay — is intact.

**Re-check when:** a Linux artifact or an npm package appears. PR #541's one cheap probe is still
unspent: the Linux desktop package on zcode.z.ai may carry the `zcode` CLI inside it, which would
turn this into a download-and-extract like the others.

### QwenPaw — one hardcoded session id

agentscope-ai/QwenPaw, Apache-2.0, 37k★, pushed daily. PR #541 closed it for having no session id
and no resume. **Unchanged in current main**: `src/qwenpaw/cli/task_cmd.py` still passes
`session_id="headless-task"` in both places it builds a request, and the flags are `--instruction`,
`--model`, `--max-iters`, `--timeout`, `--no-guard`, `--skills-dir`, `--output-dir`, `--agent-id` —
there is no `--session-id` and no continuation. The other two reasons also stand: `pip install
qwenpaw` pulls playwright, transformers, onnxruntime and four messaging SDKs, far past the 300 MB
rule, and the project has its own `harnesses/` directory, so it drives other agents rather than
being one.

**Re-check when:** the task command takes a session id. Continuity would otherwise need an
in-process driver over `qwenpaw.runtime.builder.AgentBuilder`, the shape openhands, agentzero and
nanobot already have here — buildable, but it buys a runtime that is pointed the other way.

### Continue — the CLI is dormant, and that was the decision

continuedev/continue, Apache-2.0, 36.4k★, repository pushed daily. The maintainer's decision of
2026-09-13 was explicit: **no PR; keep the notes; revisit on a next release or a usage signal.** The
investigation behind it had already cleared the hub-login blocker (`cn -p --config <local file>` made
zero requests to Continue, verified against a logging stub) and documented the traps: `--exclude` is
a no-op under `--auto`, `usage.model` is the requested id rather than the served one, `session.usage`
reads `cache_read_tokens` and zeroes cache reads, and there is no event stream.

The release has not happened. **No commit has touched `extensions/cli` since 2026-06-18**, and
`@continuedev/cli` was last published the same day — four and a half months in which the rest of the
repository shipped daily. There is no separate CLI repository in the org. The usage on our own
catalog (#23, 60.1B tokens, 1.2M requests over 30 days) is Continue overall, which is mostly the IDE
extension, not the CLI, so it is not the signal the decision asked for.

**Re-check when:** `@continuedev/cli` publishes again.

### Gajae Code — not a defect, and not a version

Yeachan-Heo/gajae-code, MIT, 3.1k★, pushed daily, now 0.19.2. Removed from the tree whole in PR #541
after being carried as "implemented and NOT offered" since 2026-10-06. The blocker is ours, not
theirs: gjc's native lock helper refuses to trust path resolution and opens **every ancestor** of the
path it locks with `O_RDONLY|O_DIRECTORY|O_NOFOLLOW`, which needs read on each one, and `/data` and
`/data/workspaces` are `751` — traversable by sessions, neither listable nor writable. A session uid
gets EACCES and the turn dies before its first model call. Measured both ways on a live instance
(2026-10-03): at `755` a turn completed in 4.6 s, back at `751` it failed again.

Nothing in 0.19.x speaks to this — the project publishes no changelog, and the lock lives in its Rust
crates. **Re-check when:** either upstream stops walking ancestors, or the maintainer decides to
relax those two modes, which gives up "neither listable" but not "nor writable". That trade is
written out in `docs/support-matrix-notes.md`.

One housekeeping note from the PR #541 review: the parked branch `parked/vtcode-and-gajae` is local
only and exists on neither remote, so a restore cannot start from it as the notes claim.

## The one opening worth acting on: OpenClaw

openclaw/openclaw, **MIT**, 393k★, pushed today, stewarded by a 501(c)(3) foundation, with
`openclaw` on npm (bin `openclaw`) and an install script for macOS, Linux and Windows.

The catalog's own review, dated 2026-08-24, says "no public machine interface was documented". That
is what the record showed then and it is out of date now. **Probed on 2026-11-03** against npm
`openclaw@2026.10.10` on darwin-arm64, with a local OpenAI-compatible stub standing in for the
relay; the two documented entry points came out the opposite way round from what the docs suggest.

**`agent exec` cannot carry a conversation, though it is the documented headless entry point.** Two
runs against one `--state-dir` produced two session ids, and turn 2's request to the stub carried no
trace of turn 1 (three messages, the codeword absent). The state is genuinely retained — both
sessions and the codeword are in its sqlite — but `exec` has no `--session-id` and no `--resume`, so
a stored session cannot be selected. Its own help calls it "one **isolated** turn".

**`openclaw agent --local --session-id` carries all five scenarios, and needs no daemon.** With
`gateway status` refusing on 18789 throughout, a follow-up replayed history 3 → 6 messages, a switch
to a second model kept the thread including the earlier tool call, a scripted `write` produced a real
file, and a state directory **copied to a different path** resumed with an 11-message history
intact. So the "a gateway daemon per session" cost this page assumed does not exist. The real cost is
different: that path takes no `--cwd` and works inside `$OPENCLAW_STATE_DIR/workspace`, which
openclaw scaffolds with its own `AGENTS.md`, `BOOTSTRAP.md`, `IDENTITY.md`, `SOUL.md`, `USER.md` and
a `.git` — a driver would have to answer for all of it against this product's workspace contract.

**Routing works, with a sensitivity control.** Against a live stub the turn arrived as
`POST /v1/chat/completions` with the model id asked for, the configured bearer, and 11 tools. A dead
port gave `ECONNREFUSED` with `rotations=0 next=none` and the live stub's log untouched; a 401 gave
`reason=auth next=none` carrying the provider's own sentence. Nothing ever rotated to a vendor
default. Across 13 requests it never called `GET /v1/models`, so a relay need only serve
chat/completions.

**Rule 2 needs the relay.** The stub answered every chunk as a different model than the request
asked for, and both envelope shapes still reported the *requested* id: the envelope echoes the
request and discards what was served. openclaw belongs with goose, cline and qwen — the served model
has to come from `_relay_served_model`.

What would block a base, in order:

1. **Node.** `engines.node` is `">=24.16.0 <25 || >=26.1.0"`; the image installs **Node 22**
   (`Dockerfile`, `setup_22.x` — "22, not 20: pi's engine floor is >=22.19"), still below that
   floor, and `docker/entrypoint.sh` provisions no newer Node for any base. Below the floor openclaw's entry
   point prompts `Update NodeJS: Y/N [N]:` on stdin and, with stdin closed, takes N and fails — it
   neither hangs nor works. This is an image change, not a per-base one.
2. **637 MB installed**, a little over twice the ~300 MB line. On the record: that is darwin-arm64,
   and `2026.10.10` carries 84 mostly per-platform optional dependencies, so **linux-x64 was not
   measured** and nobody should argue the number until it is.
3. **Question (a), which makes the other two moot if the answer is "client".** OpenClaw's own framing
   is that "models and agent harnesses (Claude, Codex, local models) are plugins you can swap" — it
   drives other harnesses, the direction issue #589 (Commonly as a UHP client) belongs to. The
   embedded agent is real and routes correctly, but ~90 provider docs, 30 delivery channels and a
   system prompt that opens "You are a personal assistant running inside OpenClaw" point at #589.
   The counter is that OpenSquilla, already a base here, is openclaw/hermes lineage. A product call.

Nothing in the headless, routing or continuity story blocks a base: those were this page's named
risks and they measured out fine. Installing from npm alone works with no onboarding even with npm
blocking all four install scripts, and no browser, OAuth or device-code flow was offered or attempted
anywhere in the probe.

Four upstream defects fell out of the probe and are worth filing whichever way question (a) goes:
`ECONNREFUSED` reported as `"status": "timeout"` with the documented timeout exit code; failure
envelopes with `model` and `provider` null and UI prose where the reason belongs, everything
actionable on stderr only; the retry ladder running to 67.7 s under `--timeout 60`; and
`--state-dir`'s "retain sessions" promise being true but unusable.

Per [CONTRIBUTING.md](../CONTRIBUTING.md) this opens as an issue describing the problem, the
proposal and the expected impact, before any implementation.

## Two licensing calls, if proprietary upstreams stay acceptable

Claude Code and Qoder Cloud Agent are already bases here, so "proprietary" is not by itself a
disqualification — the model routing is. Two of the closed rows above clear the routing bar and fail
only on their terms, and both are a maintainer decision rather than a technical one:

- **pool** (poolside). Public release tarballs for `linux-amd64` and `linux-arm64` with a
  `checksums.txt` beside them — requirement 3, exactly as the other installers want it. `pool exec`
  takes `-p`, `--prompt-file` or stdin with `-o json` (newline-delimited), `--continue <run-id>`
  continues a run, and `pool acp` serves the Agent Client Protocol over stdio with an experimental
  Streamable HTTP mode — the shape zeroclaw and dcode are already driven over. Crucially, login
  offers "connect an OpenAI-compatible provider" with a base URL, and
  `POOLSIDE_STANDALONE_BASE_URL` overrides the endpoint, so the relay fits. Blocked only by the
  EULA. Last release 1.0.16 (2026-08-14).
- **Factory Droid**. `droid exec` is one-shot with `-o json` (one object at the end, carrying
  `session_id`), `-s/--session-id` continues a session, `--fork` branches one, `-m/--model` picks the
  model per run, and `customModels` in `~/.factory/settings.json` takes `baseUrl`, `apiKey` and
  `provider: generic-chat-completion-api` — a custom model is then selected as
  `--model "custom:<Display-Name>-0"`. It still requires a `FACTORY_API_KEY` for the CLI itself, and
  the binary is proprietary.

## What the maintainer has already said, and that applies to all of this

- **A missing capability is a bridge before it is a verdict** (2026-09-13). When a CLI lacks
  something the matrix claims, the backend gets that capability through a bridge built from a
  well-known open-source component, and the matrix measures it for real; "unsupported" is the
  fallback and comes back to the maintainer first. Precedent: dsh's MCP client, and the mcptools pin
  for aider.
- **No base puts a provider key in the CLI's environment** ([PR #448 review](https://github.com/HarnessRouter/harnessrouter/pull/448)).
  Every keyed turn rides the relay, on every connection shape the base is offered on, and a test
  proves the key appears in no environment value, argument or file.
- **Licenses and pinned digests are checked on review** ([PR #541 review](https://github.com/HarnessRouter/harnessrouter/pull/541)).
  A new base arrives with each artifact's sha256 compared against what the registry publishes.
- **The console is on hold for UI changes** (same review) while it is rebuilt from the new design, so
  a new base's `ui/src/lib/harness.ts` entry and logo need a maintainer decision of their own. The
  API serves a base from `_BASE_CATALOG` without the console, but `test_console_placeholders.py`
  holds the two together.

## Summary

| Verdict | Harnesses |
|---|---|
| Closed — model cannot be routed | Cursor, Junie, Codebuff/Freebuff |
| Closed — license | Crush, Skyvern, stagewise, Command Code, PostQode, Ottili Coder, pool, Verdent |
| Closed — nothing to drive | TeleClaw, Swades Agent, Roo Code (archived), durable-harness (a durability layer around the CLIs already run here) |
| Open on a named trigger | Zoo Code (a `cli-v*` or npm release), Z Code (a Linux artifact), QwenPaw (a session id), Continue (a CLI release), Gajae Code (the `/data` modes, or upstream's lock) |
| Propose now | OpenClaw — headless, routing and continuity measured working on `agent --local --session-id`; gated on the image's Node floor, its install size on linux, and whether it is a base or a UHP client |
| Licensing call | pool, Factory Droid |
