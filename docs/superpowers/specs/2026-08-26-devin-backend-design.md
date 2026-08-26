# Design: Devin backend for HarnessRouter runner

**Date:** 2026-08-26  
**Status:** Design / awaiting implementation plan  
**Approach:** ACP-first, one `devin acp` process per turn, normalizer to the canonical claude stream-json event format.

## Context

HarnessRouter Community Edition is a self-hosted UHP (Unified Harness Protocol) server. The runner in `runner/server.py` already supports `claude`, `codex`, `hermes`, `pi`, `dsh`, and `opencode` as first-class backends. `opencode` is MIT-licensed, already installed via the Docker entrypoint, and already has a normalizer and tests.

The goal of this work is to add **Devin** as another first-class backend. Devin is different from the existing backends:

- Devin CLI is proprietary (Cognition AI, Inc.) and ships as a prebuilt binary.
- It does not speak a JSONL stream like OpenCode/Codex/Claude Code.
- It does expose an **Agent Client Protocol (ACP)** server mode: `devin acp` speaks JSON-RPC over stdio.
- It requires a Devin/Windsurf account and API key, not a raw model-provider key.

This design adds Devin as a runner backend by running `devin acp` once per turn and having the runner act as the ACP client.

## Goals

- Add a `devin` base harness that can be selected in the console.
- Run a Devin turn inside a real `/workspace` git directory, just like the other backends.
- Stream progress to the UI through the existing UHP event stream.
- Support turn cancellation and timeout.
- Do not ship the proprietary binary inside the open-source Docker image.

## Non-goals

- Running Devin in the cloud / via handoff (that is a separate cloud-connector feature).
- Replacing or extending OpenCode (OpenCode is already present and out of scope for this spec).
- Adding Devin as an MCP tool or subagent.
- Supporting Devin Desktop UI features (browser previews, video recordings) beyond what ACP exposes.

## Research summary

- `devin acp` is launched as a subprocess and speaks JSON-RPC over stdio.
- Credentials: `WINDSURF_API_KEY` env, or credentials from `devin auth login`, or an ACP `authenticate` request.
- Flags: `devin acp --model <model>` sets the default model per ACP session.
- ACP flow: `initialize` → `session/new` (or `session/resume`/`session/load`) → `session/prompt` → `session/update` notifications → `session/cancel` if needed.
- Devin CLI is installed via `curl -fsSL https://cli.devin.ai/install.sh | bash`. The install script writes version bundles to `$XDG_DATA_HOME/devin/cli/_versions` and links `devin` into `$HOME/.local/bin`.
- ACP docs: <https://agentclientprotocol.com/protocol/>
- Devin CLI docs: <https://docs.devin.ai/cli/reference/commands>

## Decision

Use the ACP-per-turn approach:

- Runner spawns `devin acp --model <model>` for each turn.
- A new ACP client thread in the runner drives `initialize`, `session/new`, `session/prompt`, and reads `session/update` notifications.
- A new `_devin_to_claude` normalizer maps ACP events to the canonical claude stream-json events the rest of the system already consumes.

## Pattern alignment with existing backends

The closest existing implementation is the **Codex app-server driver** (`_run_codex_appserver_bg`). It already spawns a CLI, sends `initialize`, `thread/resume`/`thread/start`, `turn/start`, reads JSON-RPC notifications, extracts usage, and kills the process after one turn. The Devin driver should reuse that exact shape, but with ACP method names (`session/*` instead of `thread/*`/`turn/*`).

- Like **Hermes** and the **Codex app-server**, `devin` should have a custom runner function (`_run_devin_acp_bg`) and likely register `normalize: None` in `BACKENDS`, because the driver calls the normalizer directly.
- Like **OpenCode**, Devin is installed at runtime and needs a per-session `HOME`/`XDG_DATA_HOME` redirect so state and credentials live on the data volume.
- Like **Claude Code**, **Codex**, and **Hermes**, a resume must be guarded: only call `session/resume` if the previous session artifact is actually present in the workspace/data dir.
- Like **OpenCode** and **Claude Code**, tool restrictions can be enforced at the wire level (ACP `request_permission` responses), so `tool_enforcement` is "hard".

## Architecture

```
UHP client / console
        │
        ▼
    Gateway (FastAPI)  ←  adds "devin" to /v1/bases, /v1/models, routes provider → WINDSURF_API_KEY
        │
        ▼
    Runner /turn
        │
        ├── _build_devin(...) → ["devin", "acp", "--model", <model>]
        │
        ├── _run_devin_acp_bg(...)  ← ACP JSON-RPC client
        │       │
        │       ├── send initialize
        │       ├── send session/new (or session/resume)
        │       ├── send session/prompt
        │       ├── read session/update notifications
        │       └── send session/cancel on stop
        │
        └── _devin_to_claude(...) → canonical events
```

## Components

### 1. Runner backend registry and dispatch

Add `devin` to `BACKENDS` in `runner/server.py`:

```python
BACKENDS = {
    ...
    "devin": {
        "providers": sorted(DEVIN_PROVIDERS),
        "default_model": DEVIN_DEFAULT_MODEL,
        # The driver calls _devin_to_claude directly, like _run_hermes_bg and _run_codex_appserver_bg.
        "normalize": None,
    },
}
```

In `turn()`, add a dispatch branch before the fallback to `_run_turn_bg`:

```python
elif backend == "devin":
    model = model or DEVIN_DEFAULT_MODEL
    threading.Thread(target=_run_devin_acp_bg,
                     args=(turn_id, cwd, env, model, req.prompt,
                           req.resume_session_id, req.timeout_seconds,
                           req.mcp_servers, req.tools_disabled),
                     daemon=True).start()
```

This mirrors the existing `codex` app-server and `hermes` branches.

### 2. Devin env / argv helper

Called inside `_run_devin_acp_bg` before `subprocess.Popen`:

- `cmd = ["devin", "acp", "--model", model]`
- Sets `WINDSURF_API_KEY` from the harness connection auth.
- Sets `DEVIN_MODEL` for redundancy.
- Sets `HOME` to `<cwd>/.harness/home` (existing pattern) and `XDG_DATA_HOME` to a path inside the data volume so Devin credentials and session state persist.
- Prepares the disabled-tools list so the driver can respond to ACP `request_permission` notifications.

### 3. ACP client `_run_devin_acp_bg`

A new background thread, modeled on `_run_codex_appserver_bg` (JSON-RPC over stdio) rather than `_run_turn_bg` (one-way JSONL stdout):

1. Spawn `devin acp`.
2. Send `initialize` with protocol version and client capabilities.
3. On `initialize` response, send `initialized` notification (ACP handshake) or rely on `WINDSURF_API_KEY` in env.
4. **Resume guard:** if `resume_session_id` is set, check for the Devin session artifact under `XDG_DATA_HOME/devin/cli/sessions` (or equivalent). If it exists, call `session/resume`; otherwise call `session/new` and log `resume_lost` like Hermes/Claude/Codex.
5. Send `session/prompt` with the prompt as a text content array.
6. Read `stdout` line-by-line for JSON-RPC responses and `session/update` notifications.
7. For each `session/update`, call `_devin_to_claude` and append events to the turn record.
8. On `request_permission`, send `session/respond` (or the ACP equivalent) with `approve`/`deny` based on the harness `tools_disabled` list.
9. On `session/prompt` response with `stopReason`, or on `turn/failed`/`error` notifications, finalize the turn.
10. On gateway `cancel`, send `session/cancel` and kill the process group.
11. On timeout, send `session/cancel` and kill.
12. Close with `session/close` if supported and the process is still alive.

### 4. Normalizer `_devin_to_claude`

Maps ACP `session/update` notifications to canonical UHP events:

| ACP update | UHP event |
| ------------ | ----------- |
| `agent_message_chunk` (text) | `assistant` with `output_text` |
| `agent_message_chunk` (reasoning) | `assistant` with `thinking` |
| `tool_call` | `assistant` with `tool_use` |
| `tool_call_update` | update tool status (in progress / completed / error) |
| `plan` | `system` plan event or `thinking` |
| `user_message_chunk` | ignored or logged as system echo |
| `request_permission` | auto-approve / deny based on harness `tools_disabled` |
| `state_update` with `stopReason` | turn finalization (`completed`, `cancelled`, `max_tokens`) |

The normalizer is chunk-level, not token-level, so Devin does not advertise fine-grained token streaming. Usage is extracted from `stopReason` or any usage payload in the final update.

### 5. Gateway changes

- Add `devin` to `_BASE_CATALOG` (label, backend, system prompt, tools, `tool_enforcement: "hard"`).
- Add `devin` to `_MODEL_CATALOG` with Devin's own default model and supported model list (not inherited from pi/opencode).
- Add `devin` to `_SUPPORTED_BASES` (derived automatically from `_BASE_CATALOG`).
- Add a `devin` entry to `_PROVIDER_CATALOG` with `secret: "api_key"` and no default `base_url`.
- Add `("devin", "devin"): "devin"` to `_INTEGRATION_WIRING`.
- In `_route_backend`, either add a Devin heuristic or rely on `_backend_of_builtin` (which already uses `_BASE_CATALOG` for built-in harnesses).

### 6. UI changes

- Add `devin` to `OobHarness` in `ui/src/lib/harness.ts`.
- Add `devin` to the backend type union.
- Add a Devin logo mapping in `ui/src/components/HarnessLogo.tsx`.

### 7. Docker install

- Add `devin` to `HR_BACKENDS` default and `backend_bin` in `docker/entrypoint.sh`.
- Add an `install_devin` function that installs the binary at first run, not at image build time. It should mirror `install_opencode` in structure:
  - Determine arch (`x86_64` → `x86_64-unknown-linux`, `aarch64` → `aarch64-unknown-linux`).
  - Download the manifest from `https://static.devin.ai/cli/current/manifest.json`.
  - Verify the SHA-256 checksum.
  - Extract the matching bundle into a versioned directory under `$DATA_DIR/agent-tools/devin`.
  - Symlink `devin` into `$DATA_DIR/agent-tools/bin/devin`.
- Set `HOME` and `XDG_DATA_HOME` so Devin writes credentials/session state under the data volume, not the image's root home.
- Print a clear license/source warning, mirroring the existing Claude Code and Hermes install messages.

## Authentication

Devin CLI ACP mode accepts credentials in this order:

1. `WINDSURF_API_KEY` env var.
2. Credentials stored by `devin auth login`.
3. ACP `authenticate` request.

For a headless server the only viable option is `WINDSURF_API_KEY`. The user adds a `devin` integration in the console; the gateway stores the key and passes it to the runner as `Auth.api_key`, which the driver maps to `WINDSURF_API_KEY`.

`devin` is a new provider type. In the default self-hosted mode (`HR_SANDBOX_TRUST=owner`) the raw key is passed through to the runner, just like the other backends. In a hosted/brokered deployment, `devin` should be omitted from `_BROKERABLE_PROVIDERS` because the credential is a Devin account key and cannot be safely brokered.

## Session continuity

Devin must support `session/resume` across a fresh `devin acp` process. If it does:

- Runner stores the ACP `sessionId` as the UHP `resume_session_id`.
- Next turn calls `session/resume` with that id and the same `cwd`.

If Devin does **not** support resume across fresh processes, the design must fall back to `session/new` each turn, losing conversational context between turns (same as a one-shot backend). A follow-up spike should verify this behavior before full implementation.

## Error handling

| Failure | UHP behavior |
| --------- | -------------- |
| `devin` binary not installed | `invalid_request_error` / `backend_not_found` with install instructions |
| `WINDSURF_API_KEY` missing | `invalid_request_error` / `invalid_credential` |
| ACP `initialize` fails | `server_error` / `upstream_error` |
| ACP `auth_required` | `authentication_error` |
| ACP `session/prompt` error or non-zero exit | `server_error` / `devin_error` with the error message from ACP |
| User cancel | send `session/cancel`, kill process, mark `cancelled` |
| Timeout | send `session/cancel`, kill process, mark `timeout` |

## Testing

- `runner/tests/test_devin_normalize.py`: unit tests for `_devin_to_claude` against captured ACP notification JSON.
- A fake ACP server script in `runner/tests/` so `_run_devin_acp_bg` can be exercised without a real Devin account.
- `uhp-conformance` run against the local gateway to verify `/v1/bases`, `/v1/models`, `/v1/responses` work with the new backend.
- Manual test with a real `WINDSURF_API_KEY` after implementation.

## Risks and open questions

1. **Resume across fresh processes.** This must be tested. If it fails, the per-turn ACP design loses session continuity.
2. **XDG paths and isolation.** Devin stores versions and credentials in `XDG_DATA_HOME` and the binary link in `$HOME/.local/bin`. The runner must set these to paths inside the data volume or session workspace to keep state checkpointed and isolated.
3. **Proprietary license.** The binary cannot be redistributed. The project must download it at runtime under the end user’s terms, with clear warnings.
4. **Credential model.** This is the first backend that requires a vendor API key (Devin/Windsurf) rather than a model-provider key. It changes the self-host narrative from “your model key only” to “your Devin account key”.
5. **Permission requests.** ACP may send `request_permission` notifications. The runner must either auto-approve based on harness config or respond with a deny. Without a UI, the safest default is to deny and let the harness instruction tell Devin not to ask.

## Alternatives considered

- **Batch `devin -p` + ATIF**: simpler, but no live events and poor UX.
- **Devin as MCP tool / subagent**: keeps Devin outside the first-class harness list; depends on a bridge.
- **Devin Cloud / Outpost API**: requires cloud, conflicts with CE self-host goals.
- **Long-lived ACP sidecar per session**: avoids resume risk, but adds process-lifecycle complexity to the runner.

## Next step

Once this design is approved, the implementation plan will break this into:

1. Runner ACP client + `_build_devin` + normalizer.
2. Gateway catalog and provider mapping.
3. UI harness entry and logo.
4. Docker entrypoint install step.
5. Tests and conformance verification.
