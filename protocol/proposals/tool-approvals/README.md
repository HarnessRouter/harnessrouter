# Durable tool approval — local proposal

Status: **draft, not implemented or advertised**. Base: UHP `2026-10-19`.
Tracking: [Hexa task Change](../../../docs/changes/CHG-task-centric-workflow/change-record.yaml).
This is a local proposal, not an accepted UEP or a new published UHP version.

## Problem

Current [input requests](../../versions/2026-10-19/tasks.md#32-asking-the-person) ask a person a question, including a general confirmation, and resume with a message. They do not bind consent to an exact tool invocation or guarantee interception before its side effect. A `function_call` event is observability, not an authorization boundary. A product cannot safely gate an action by merely pausing after that event.

## Proposal and ownership

Introduce optional `capabilities.tool_approvals`. Missing means false. Per-base and per-tool enforcement coverage MUST be returned by authenticated capability inspection; discovery MUST NOT expose principal-specific inventory. Servers MUST advertise true only for calls they can intercept before execution, durably suspend and resume without regenerating a different invocation. If a requested required-approval policy exceeds coverage, refuse **before starting** with `422 hexa_approval_unavailable`. Clients MUST inspect capability before submitting; older servers may ignore new request fields. Do not submit privileged work and infer enforcement from the response afterward.

Hexa owns workflow/workspace/agent policy, the human UI, task-scoped authorization and its audit record. Gateway owns effective capability resolution, interception, authoritative pending approvals and execution receipts. Runner/runtime owns native enforcement, sandbox and the durable continuation checkpoint. Authorization is the intersection of workflow, workspace, agent and native runtime restrictions, narrowed by this one approval. Approval never lifts a native deny. Skill instructions and plugin installation grant no permissions.

Reuse the existing [Plugin contract](../../versions/2026-10-19/plugins.md): Harness direct enabled MCP/skills plus enabled plugin-derived MCP/skills, with `disabledTools` applied to all. Record tool origin (`direct`, `plugin`, `builtin`, `runtime`); plugin identity/version/content digest; MCP server/tool identity; skill digest; enabled/skipped and effective composition digest. Never copy plugin files, headers, auth or secrets into a task snapshot. Disabled plugins stay installed but inactive; skipped components enter preflight diagnostics. `plugins` and `tool_approvals` are independent capabilities. stdio MCP remains in the agent sandbox with existing PLUGIN_ROOT/PLUGIN_DATA and containment semantics.

## Wire contract

The adjacent [JSON Schema](schema.json) defines the new fragments; [OpenAPI](openapi.yaml) defines inspection and decision endpoints. Both are proposal artifacts, separate from published schemas.

1. Before dispatch, create one durable `tool_approval_request` output item. Fields include approval ID, exact command ID, tool identity/origin, `request_hash`, policy/capability digests, safe preview and expiry. Persist before emitting. The model MUST NOT be able to manufacture approvals by generating an output item.
2. End the response with `status: incomplete`, `incomplete_details.reason: tool_approval_required`, using the existing `response.output_item.added/done` and terminal `response.incomplete` SSE events and consecutive sequence numbers. Include a plain-text explanation for older clients. No tool side effect occurs while pending. Approval state is separate from response status.
3. `GET /v1/responses/{response_id}/tool-approvals/{approval_id}` returns the durable record after disconnection or restart, scoped to the same principal and session.
4. `POST` to that path accepts one `tool_approval_response` decision plus **required** `Idempotency-Key`. This endpoint records/reserves the decision; it MUST NOT itself execute the tool. Return a receipt with the same `command_id` and hash. Identical replays return the same receipt; different payload with the same key returns `409 hexa_approval_conflict`.
5. Resume only through `POST /v1/responses` with `previous_response_id` and exactly one `tool_approval_response` input item, also carrying an idempotency key. The server verifies that its contents match the accepted decision. Do not combine it with `input_response`, `branch`, or unrelated messages. Atomically reserve the single continuation; concurrent alternatives conflict. No new tool can inherit this approval.

Use HTTP 404 for out-of-scope or unknown addressed objects. For an existing scoped record use 409 `hexa_approval_not_pending`, `hexa_approval_changed` or `hexa_approval_conflict`; expired requests return 410 `hexa_approval_expired`; malformed decisions return 422 `hexa_approval_invalid`. Error envelopes retain the existing UHP shape, and messages remain safe to display.

## Binding, lifetime and side effects

`request_hash` = SHA-256 of RFC 8785 canonical JSON of the server-held execution descriptor: command ID, exact argument bytes/configuration references, tool origin and version, workspace/session identity, policy/capability digests and permission-relevant environment references. Secret values MUST NOT appear in preview, schema examples, logs or public descriptors; use immutable version references or server-side keyed digests for secret-dependent binding. The public SHA-256 covers those references, never low-entropy secret plaintext. Store canonicalization version with the pending record.

Before execution, recompute binding and recheck ownership, revocation, expiry, native deny and exact continuation availability. Any changed argument, plugin, MCP config, skill, policy, workspace or referenced credential version invalidates the approval; ask anew. The client sends a hash, never replacement arguments. A request is valid for one invocation and only until its stated expiry; reject already expired or unbounded lifetimes. Cancellation, deletion or credential revocation voids pending/accepted approval and prevents later execution. Ordinary chat continuation MUST NOT silently pass over it or authorize the action.

Durable states: `pending → approved|denied|expired|voided`; approved may progress to a reserved execution with a unique command receipt. Denial/expiry never runs the tool, and is not interpreted as a successful tool result. Resuming a denial gives the runtime a denial fact so it can stop or choose a different permitted action.

Receipt `side_effect_state`: `not_started`, `started`, `completed`, `failed`, `unknown`. A crash after reservation or start MUST NOT auto-replay a possibly executed side effect. Set `reconciliation_required: true` for unknown outcomes; inspect native receipt/checkpoint first. An approved decision is not proof that the tool ran. Recovery of pending approvals must survive API/Gateway restart without changing IDs or hashes; a runtime that cannot restore the exact call cannot advertise coverage. No promise of exactly-once external effects is made.

## Compatibility and alternatives

Keep existing `input_required/input_response`, statuses, tools, plugin format and version header semantics. New opt-in capability, item types, endpoints and vendor-prefixed errors are additive under [VERSIONING](../../VERSIONING.md). Use a dated publication only when released; do not call this UHP v1.1. Do not advertise it in Gateway until implementation and live conformance pass together per [GOVERNANCE](../../GOVERNANCE.md).

Rejected alternatives: reusing a general confirm answer (no exact invocation binding); executing from Hexa based on a streamed call (races and duplicates); per-request plugins or privilege widening (violates existing security contract); holding a sandbox/SSE stream open indefinitely (no durable recovery).

## Acceptance and implementation sequence

| Check | Required observable outcome |
| --- | --- |
| A-01 | Unsupported base/policy rejected before execution; no silent bypass |
| A-02 | Pending record persists before stream; tool spy records zero calls |
| A-03 | Wrong principal cannot read/decide/resume; all return 404 |
| A-04 | Approve and resume exact call once under concurrent/replayed requests |
| A-05 | Deny, expiry, cancel and revocation produce zero tool effects |
| A-06 | Argument/plugin/skill/MCP/policy digest change invalidates consent |
| A-07 | Pending decision survives restart; crash after start becomes unknown, never blind replay |
| A-08 | Native deny remains effective; disabled/skipped plugin tools cannot execute |
| A-09 | SSE, read-back, schemas and receipts agree; secrets absent from every output |

Implement Gateway durable store and native interception first, then conformance against a real supported runtime, then Hexa snapshot/client and human UI. Schema tests validate shapes only; they do not satisfy A-01–A-09. This draft does not change the shipped Gateway or grant approval coverage to existing runtimes.
