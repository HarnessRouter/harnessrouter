# Roder

[Roder](https://github.com/RoderAI/roder) runs through its native `roder app-server`
JSON-RPC interface. Like Codex's app-server integration, each turn starts a process,
initializes it, creates or reads a thread, and starts a turn with an explicit model.
The process ends after `turn/completed`; thread history stays in the workspace.

## Connections

Use an OpenAI, Azure Foundry, TokenRouter, HarnessRouter, or custom **Responses**
connection. This adapter uses Roder's custom Responses provider `hr`, preserving
the requested model id. It does not select Roder's Codex OAuth provider. The initial
catalog contains `gpt-5.4` and `gpt-5.2`; it does not inherit another harness's
verified model list. Anthropic Messages and Chat Completions custom endpoints are
not offered by this adapter.

Every provider call uses the existing loopback relay. Roder receives a relay
placeholder in `HR_RODER_KEY`; the provider key stays in the runner. The relay
collects provider-reported model and usage independently of the CLI.

## Installation

Include `roder` in `HR_BACKENDS` (it is included by default). The entrypoint installs
the Linux binary from Roder's release channel. Both target SHA256 digests are pinned
in `docker/entrypoint.sh`; a replaced upstream asset fails verification. Because
upstream publishes binary assets under a mutable `latest` tag, a later release
requires updating those digests. No auto-update runs inside a turn.

`HR_RODER_BIN` can select an existing binary for development and process tests.

## Sessions, tools, and skills

- `RODER_CONFIG_DIR` and `RODER_DATA_DIR` point at `.harness/roder/`. Persisted
  threads ride the normal checkpoint; `auth/` and the per-turn `config.toml` are
  excluded because CLI configuration/auth commands can write credentials there.
- Every `turn/start` carries the requested model and provider, including resumed
  threads. Missing history emits `system/resume_lost` before starting a new thread.
- The harness instruction file is `AGENTS.md`; the driver sends its current contents
  as `turn/start.developerContext` on every turn. Skills are installed under
  `.harness/home/.codex/skills`, Roder's user skill root, keeping bundles outside
  produced files.
- Disabled native tools are withheld using Roder's runtime `tools.allowlist` on
  every process, including resumes. A short discovery process obtains the tools
  for the requested model before the turn process starts. Disabling one tool does
  not disable other tools that can accomplish the same task.
- MCP supports stdio, SSE, and streamable HTTP through the existing MCP Python
  dependency. The driver publishes discovered tools as Roder `externalTools` and
  answers `thread/toolExecutionRequested` via `tools/resolve`. Unreachable servers
  produce `system/mcp_unavailable`. An attachment/schema change on an existing
  thread is refused with an instruction to start a new session: Roder persists
  external tools at thread creation and has no API to replace them.
- Timeout, cancellation, and step budgets use the runner's existing process-group
  controls. A truncated stream fails even when its process exits zero.

## Verification

Run the unit and registration tests:

```sh
python -m pytest runner/tests/test_roder_backend.py
python -m pytest gateway/tests/test_roder_catalog.py gateway/tests/test_instruction_file_label.py
```

Qualify a real binary against a deterministic local Responses server:

```sh
HR_RODER_TEST_BIN=/path/to/roder python -m pytest runner/tests/test_roder_process.py
```

These process tests check streaming, follow-up history, model switching, process
restart, lost-session reporting, native tool policy, provider errors, artifact
creation, and stdio MCP execution without provider credentials or inference costs.
They do **not** establish a live provider support-matrix column, console artifact
rendering parity, the family tour, or the benchmark dimension. Run
`scripts/support-matrix` and its custom-harness scenario on an isolated instance
before publishing a verified provider column. Roder is included in that suite's
base list; no existing provider results have been copied or marked passing.
