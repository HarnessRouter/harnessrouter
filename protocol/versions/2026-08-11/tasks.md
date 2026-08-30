# Tasks

**Unified Harness Protocol, version `2026-08-11`**

A task is one unit of work: input in, a result out. It is the endpoint most clients spend all their
time in.

## 1. Run a task

```http
POST /v1/responses
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "input": "Summarise README.md in three bullets.",
  "model": "claude-sonnet-4.6",
  "metadata": { "harness_id": "chrn_08dae611630d467ab3e67ed792570ae5" },
  "stream": true
}
```

### 1.1 Request fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `input` | string \| item[] | yes | The work. A bare string is shorthand for one user message. See §2. |
| `model` | string | no | Canonical model id. Omitted means the harness's default. |
| `metadata` | object | no | Client metadata. `harness_id` selects the configured harness. See §1.2. |
| `stream` | boolean | no | `true` streams Server-Sent Events; default `false` returns one JSON object. |
| `previous_response_id` | string | no | Continue the session that produced that response. See [Sessions](sessions.md). |
| `instructions` | string | no | Additional system guidance for this task only. |
| `store` | boolean | no | Whether the server retains the response for later reads. Default `true`. |
| `max_output_tokens` | integer | no | Upper bound on generated tokens. |
| `max_step` | integer | no | Upper bound on agent steps (tool-call rounds) for this task. |
| `timeout_seconds` | integer | no | Wall-clock budget for this task. |
| `tools` | array | no | **Reserved and ignored.** Accepted, never acted on. See §1.4. |
| `include` | string[] | no | **Reserved and ignored.** Accepted, never acted on. See §1.4. |
| `background` | boolean | no | Return as soon as the task is accepted; follow it with the events endpoint. |

A server MUST ignore request fields it does not understand rather than rejecting the request. A
client MUST NOT rely on an unknown field having an effect.

Ignoring MUST be observable. When a server does not act on a field the request carried, it MUST
name that field in `metadata.ignored_fields` on the response — an array of request-field names, in
any order. This is the same principle as model substitution in §1.3: where the server did not do
what the request literally said, the response says so. A silently ignored field is
indistinguishable from an honoured one, and a client cannot tell which it got.

`tools` and `include` are reserved and ignored (§1.4), so a server MUST name them in
`metadata.ignored_fields` whenever a request carries them. A server MUST NOT reject a request for
carrying either.

`max_step` and `timeout_seconds` are budgets, not guarantees of precision: a server MUST stop the
task at or after the budget, MUST report `incomplete`, and MUST NOT report `completed` for work it
truncated.

### 1.2 Selecting the harness

The configured harness is selected by `metadata.harness_id`:

```json
{ "metadata": { "harness_id": "chrn_…" } }
```

- If `harness_id` is absent, the server MUST use a default harness and MUST report which one it used
  in the response `metadata`.
- If `harness_id` names an unknown harness, or one outside the caller's scope, the server MUST fail
  with `404` and `code: "harness_not_found"`.
- If both `previous_response_id` and `harness_id` are present and disagree, the server MUST fail with
  `409` and `code: "harness_mismatch"` (see [Lifecycle §4](lifecycle.md)).

> **Why is the harness in `metadata` rather than a top-level field?**
> Because the task surface is deliberately Responses-compatible (see the
> [README](../../README.md)), and `metadata` is the extension point that surface already defines for
> caller-supplied context. A top-level `harness` field would be a second, conflicting convention for
> the same idea, and every existing Responses SDK would have to be patched to send it.

### 1.3 Model selection and substitution

`model` names a canonical model id, not a provider-specific one. Canonical ids are stable across
providers, so the same request works whether the server reaches a model directly or through an
aggregator.

If the requested model cannot be served for the selected harness, a server MUST NOT fail silently
and MUST NOT pretend it ran what was asked. It MUST do exactly one of:

1. **Fail** with `422` and `code: "model_unavailable"`; or
2. **Substitute** the harness's authorized default, and record the substitution in the response:

```json
{
  "model": "gpt-5.4",
  "metadata": {
    "requested_model": "gpt-5.6-sol",
    "model_fallback": true,
    "model_fallback_reason": "model 'gpt-5.6-sol' is not available for this harness's backend"
  }
}
```

A client can therefore always answer "did the model I asked for actually run?" by comparing `model`
with `metadata.requested_model`.

> This rule exists because its absence is expensive. A server that substitutes silently makes every
> measurement downstream wrong — benchmarks, cost attribution, quality comparisons — and the client
> has no way to detect it. Reporting the substitution costs two fields.

### 1.4 Reserved fields: `tools` and `include`

Both fields arrived with the OpenAI Responses wire shape this version stays compatible with. Neither
was designed for UHP, and neither has ever had defined semantics here. They are **reserved**: a
server accepts them, never acts on them, and reports them under `metadata.ignored_fields` (§1.1).

This is a decision rather than a gap left open, so implementers can stop carrying them as unfinished
work and client authors can stop building on them.

**`tools` cannot mean what it means in the Responses API.** There, the field exists because the
*client* executes tools: the model emits a `function_call`, the client runs it, and returns a
`function_call_output` as input on the next request. UHP puts both of those in `output` (§3.1). The
harness invokes and executes tools itself and reports them as observability. There is no input path
for a tool result, so the loop `tools` implies cannot be completed by a conformant server — not
because implementations are immature, but because the object model has no place for the return leg.

**`tools` also cannot mean "MCP servers for this task", which is the other plausible reading.**
[Harnesses](harnesses.md) §4.1 already specifies MCP servers on the harness, with a
field table and the semantics that matter: a disabled entry MUST NOT be contacted, an unreachable
server MUST NOT fail the task. A request-level form would be a second mechanism for one behaviour.

More importantly, it would be an **escalation primitive**. If a request can attach an MCP server,
anyone holding an API key can point the agent at an endpoint of their choosing, and the agent
executes tools server-side with the harness's credentials and workspace access. The harness owner
and the API caller are routinely different parties — a product configures a harness, and its end
users drive tasks against it. Request-level declaration silently moves a capability decision from
the accountable party to any caller. The configured harness is a first-class object precisely so
that decision is made once, deliberately, by whoever owns the consequences.

The durable rule underneath, which applies beyond this field: **narrowing is safe, widening is
escalation.** A future version could reasonably add a typed per-request tool *disable* list. It
should never add a per-request *grant*.

**`include` has no vocabulary.** It is `array of string` with no enumerated values, so any string a
server recognises is one that server named itself. Recognising a value would be inventing a
vocabulary no other implementation shares.

**How an agent gets tools:** configure them on the harness. See
[Harnesses](harnesses.md) §4.1 for MCP servers and §4.2 for skills.

Removal is a question for the next version. This one is additive-only and cannot drop a field, so
the honest form here is to say plainly that these two do nothing.

## 2. Input

`input` is either a string or an array of items.

```json
{ "input": "Summarise README.md" }
```

```json
{
  "input": [
    { "role": "user", "content": [
        { "type": "input_text", "text": "Summarise this report." },
        { "type": "input_file", "filename": "q3.pdf", "file_data": "data:application/pdf;base64,…" }
    ]}
  ]
}
```

| Item type | Purpose |
|---|---|
| `input_text` | Text |
| `input_file` | A file, inline as a data URL in `file_data`, or by `file_id` from a prior upload |
| `input_image` | An image, inline or by `file_id` |

A server at conformance class **Core** MUST accept `input_text`. A server at **Extended** MUST also
accept `input_file` and `input_image`. See [Files](files.md).

## 3. The response object

```json
{
  "id": "resp_a1b2c3",
  "object": "response",
  "created_at": 1786400000,
  "status": "completed",
  "error": null,
  "incomplete_details": null,
  "previous_response_id": null,
  "model": "claude-sonnet-4.6",
  "output": [
    { "id": "rs_1", "type": "reasoning", "summary": [ { "type": "summary_text", "text": "…" } ], "status": "completed" },
    { "id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "read_file",
      "arguments": "{\"path\":\"README.md\"}", "status": "completed" },
    { "id": "fco_1", "type": "function_call_output", "call_id": "call_1", "output": "…", "status": "completed" },
    { "id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
      "content": [ { "type": "output_text", "text": "- …\n- …\n- …", "annotations": [] } ] }
  ],
  "store": true,
  "usage": { "input_tokens": 5120, "output_tokens": 240, "total_tokens": 5360 },
  "metadata": { "session_id": "hsess7e78…" }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | `resp_`-prefixed |
| `object` | string | yes | Always `response` |
| `created_at` | integer | yes | Unix seconds |
| `status` | string | yes | See [Lifecycle §3](lifecycle.md) |
| `error` | object \| null | yes | Present and non-null only when `status` is `failed` |
| `output` | item[] | yes | Ordered; MAY be empty for a task that produced nothing |
| `model` | string | yes | The model that actually ran |
| `usage` | object \| null | yes | `null` when the server cannot account for usage — never a fabricated zero |
| `metadata` | object | yes | MUST include `session_id`; see §1.3 for substitution fields |
| `previous_response_id` | string \| null | yes | The response this one continues, if any |
| `store` | boolean | yes | Whether this response was retained |

### 3.1 Output items

| `type` | Meaning |
|---|---|
| `message` | Assistant text, in `content[].text`, with `annotations` for artifacts |
| `reasoning` | The agent's summarised thinking, in `summary[].text` |
| `function_call` | A tool the agent invoked, with `arguments` as a JSON string |
| `function_call_output` | The result of that tool call, matched by `call_id` |

A client MUST tolerate output item types it does not recognise, and MUST NOT assume any ordering
beyond the array order given. A client that renders only `message` items and ignores the rest is a
valid client.

## 4. Reading a task back

```http
GET /v1/responses/{response_id}
```

Returns the same response object. A server that retained the response (`store: true`) MUST return it
after completion; a server MAY return `404` with `code: "response_not_found"` for a response created
with `store: false`.

```http
GET /v1/responses/{response_id}/input_items
```

Returns the input the task was created with, for clients that need to reconstruct a transcript
without having stored it themselves.

## 5. Cancelling

```http
POST /v1/responses/{response_id}/cancel
```

See [Sessions §4](sessions.md).

## 6. Idempotency

A client MAY send an idempotency key:

```http
Idempotency-Key: <client-generated-unique-string>
```

A server that advertises `idempotency` MUST, for a repeated key:

- return the result of the **first** request, and
- **not** start a second execution.

If the first request is still running, the server MUST wait for it and return its result rather than
returning a partial or a conflict. Agent tasks are expensive and side-effecting: a retry that runs
the work twice is worse than a slow answer.

Idempotency keys SHOULD be retained for at least 24 hours.

## 7. Deleting

```http
DELETE /v1/responses/{response_id}
```

Deletes the stored response. A server MUST NOT let this cancel a running task — cancellation and
deletion are different intentions, and conflating them means a client cannot clean up history
without stopping work.
