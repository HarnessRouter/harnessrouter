# Roder

[Roder](https://github.com/RoderAI/roder) runs through its native `roder app-server`
JSON-RPC interface. Like Codex's app-server integration, each turn starts one process,
initializes it, creates or reads a thread, and starts a turn with an explicit model.
The process ends after `turn/completed`; thread history stays in the workspace.

## Connections

Use an OpenAI, Azure Foundry, OpenRouter, Vercel, LLMTR, TokenRouter, HarnessRouter,
or custom **Responses** connection. They are wired as Deep Agents Code's are. This
adapter uses Roder's custom Responses provider `hr`, preserving the requested model id.
The initial catalog contains only `gpt-6.1-sol`, pending live qualification. Anthropic
Messages and Chat Completions custom endpoints are not offered by this adapter.

Every provider call uses the existing loopback relay. Roder receives a relay
placeholder in `HR_RODER_KEY`; the provider key stays in the runner. The relay
collects provider-reported model and usage independently of the CLI.

Roder asks for `reasoning.encrypted_content` with `store: false` and replays it on
later turns. After a model switch, the new model cannot read what the previous one
produced, so the relay replays earlier turns as plain content (their reasoning items
are left out), as it does for Deep Agents Code. The earlier turns' messages and tool
calls still reach the model.

## Installation

Roder is opt-in until its live provider column is measured. Add `roder` to
`HR_BACKENDS` to install the MIT-licensed `roder/v0.4.8` release (about 102 MB on
x86_64). `HR_BACKENDS=roder` alone gives a Roder-only installation. The installer
checks the archive against a SHA256 committed in `docker/entrypoint.sh` for this
machine's architecture, then runs `roder --version` and keeps the binary only when it
reports the pinned version. It stamps successful installs and removes the binary if
an install fails.

To select another release, set `HR_RODER_VERSION` (a leading `v` is accepted) and
`HR_RODER_SHA256` to that architecture's trusted archive checksum. Without a checksum
the install proceeds and the start log says it is NOT verified, as for every other
release-asset base.

A base the catalog lists and this instance has not installed is reported as not
installed: the console does not offer it, and a turn on an existing harness built on
it is refused with that reason instead of failing after it starts.

`HR_RODER_BIN` can select an existing binary for development and process tests.

## Sessions, tools, and skills

- `RODER_CONFIG_DIR` and `RODER_DATA_DIR` point at `.harness/roder/`. Threads ride
  the normal checkpoint. `auth/` and the per-turn `config.toml` are excluded because
  CLI configuration and sign-in commands can write credentials there. The code index
  (`code-index/`), the tool discovery catalog (`discovery/`) and the models cache
  (`models-cache.json`) are rebuilt by Roder when missing, so checkpoints leave them
  out. Saved memories (`memory/`) and knowledge (`knowledge/`) are kept. The store
  changes on every turn, so it is kept out of the workspace's own git history.
- Every `turn/start` carries the requested model and provider, including resumed
  threads. Missing history emits `system/resume_lost` before starting a new thread.
- The harness instruction file is `AGENTS.md`; the driver sends its current contents
  once through `turn/start.developerContext`. The pinned app-server does not load
  AGENTS.md automatically. This volatile field is part of the
  [0.4.8 protocol](https://github.com/RoderAI/roder/blob/roder/v0.4.8/crates/roder-protocol/src/lib.rs#L979),
  and the process suite checks that the instruction reaches inference exactly once.
  Skills are installed under `.harness/home/.codex/skills`, Roder's user skill root,
  keeping bundles outside produced files.
- Tools: Roder 0.4.8 has 112 built-in tools. Each console switch covers every Roder
  tool that does the same job (`roder_backend.TOOLS`): Shell is `exec_command`,
  `shell`, `unified_exec` and `write_stdin`; File Edit is `apply_patch`, `edit`,
  `multi_edit` and `write_file`. Disabling a switch, or any one of its tool names,
  turns the whole switch off. Web Search is the provider's hosted search and is
  turned off through Roder's own `web_search` mode.
- The switches become Roder's runtime `tools.allowlist`, written to the config before
  the process starts, so they apply to resumed threads too. A tool that is off is not
  offered to the model, and a call to it is refused.
- Withheld on every turn and not offered, because they cannot run in this sandbox or
  would wait for a person (`roder_backend.WITHHELD`): the desktop browser tools
  (`chrome_*`), the Jev tab tools (`jev_*`), Webwright (`webwright.*`), the Zero
  language tools (`zerolang_*`), the media generators (their built-in provider is a
  test fake) with `media_attach` and `media_describe`, `echo`, `request_user_input`
  and `exit_plan_mode`.
- MCP supports stdio, SSE, and streamable HTTP through the existing MCP Python
  dependency. The driver publishes discovered tools as Roder `externalTools` and
  answers `thread/toolExecutionRequested` via `tools/resolve`. Unreachable servers
  produce `system/mcp_unavailable`. A stdio server starts from the turn's
  environment without the runner's `HR_` variables, plus its own declared `env`.
- Roder fixes a thread's external tools when the thread starts and has no call to
  replace them, so a follow-up keeps the tools its conversation started with. A tool
  among them whose server cannot be reached this turn, or that was switched off,
  answers its calls with an error and the turn goes on. Tools attached after the
  conversation started are named in a note on the reply; a new session has them.
- Timeout, cancellation, and step budgets use the runner's existing process-group
  controls. A turn stopped at its step budget ends as incomplete at its budget, as on
  every other base. A truncated stream fails even when its process exits zero.

## Verification

Run the unit and registration tests:

```sh
python -m pytest runner/tests/test_roder_backend.py runner/tests/test_roder_rpc.py
python -m pytest gateway/tests/test_roder_catalog.py gateway/tests/test_instruction_file_label.py
```

Qualify a real binary against a deterministic local Responses server:

```sh
HR_RODER_TEST_BIN=/path/to/roder python -m pytest runner/tests/test_roder_process.py
```

These process tests check streaming, follow-up history, model switching (through the
runner's relay too), process restart, lost-session reporting, the tool table against
the release's own tool list, tool policy and refused calls, provider errors, artifact
creation, stdio MCP execution, and a follow-up whose MCP server is gone, without
provider credentials or inference costs. They do **not** establish a live provider
support-matrix column, console artifact rendering parity, the family tour, or the
benchmark dimension. Run `scripts/support-matrix` and its custom-harness scenario on
an isolated instance before publishing a verified provider column. Roder is included
in that suite's base list; no existing provider results have been copied or marked
passing.

This new base targets the next minor release after live qualification, rather than
the 0.37.x maintenance line.
