# Errors

**Unified Harness Protocol, version `2026-08-11`**

A client's error handling is only as good as the server's error reporting. This chapter defines one
envelope, a closed set of codes, and which failures are worth retrying.

## 1. The error envelope

Every non-2xx response MUST have this body:

```json
{
  "error": {
    "type": "invalid_request_error",
    "code": "harness_not_found",
    "message": "No harness with id 'chrn_deadbeef'.",
    "param": "metadata.harness_id",
    "detail": null
  }
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | string | yes | Broad class; see §2 |
| `code` | string | yes | Specific, machine-readable reason; see §3 |
| `message` | string | yes | Human-readable, one sentence, no stack trace |
| `param` | string \| null | yes | Dotted path to the offending field, when there is one |
| `detail` | object \| null | yes | Structured extra context, or `null` |

Rules:

- `message` MUST be safe to show a user. It MUST NOT contain credentials, internal hostnames, file
  paths, or stack traces.
- `code` MUST come from §3 where one applies. A server MAY define additional codes for conditions
  this specification does not cover, and MUST namespace them with a vendor prefix (`acme_…`) so a
  future version of this specification cannot collide with them.
- A server MUST NOT return `200` with an error inside. The failure of a *task* is reported as a
  response with `status: "failed"` and HTTP `200`, because the request succeeded; the failure of a
  *request* is a non-2xx with this envelope. Those are different events and MUST NOT be conflated.

> **Compatibility note.** A server MAY additionally include a top-level `detail` string alongside
> `error`, for clients written against implementations that predate this envelope. That field is
> deprecated, carries no information not in `error.message`, and will be removed in a future version.

## 2. Error types

| `type` | HTTP | Meaning |
|---|---|---|
| `invalid_request_error` | 400, 404, 409, 413, 422 | The request was wrong. Retrying it unchanged will fail again. |
| `authentication_error` | 401 | The credential is missing, malformed or unknown. |
| `permission_error` | 403 | Authenticated, but not allowed to do this. |
| `rate_limit_error` | 429 | Too many requests, or a quota is exhausted. |
| `harness_error` | 200 (in a failed response) | The harness ran and failed. |
| `server_error` | 500, 502, 503, 504 | The server failed. Retrying MAY succeed. |

## 3. Error codes

### 3.1 Request and routing

| Code | HTTP | Meaning |
|---|---|---|
| `unsupported_protocol_version` | 400 | `UHP-Version` names a version this server cannot serve. `detail.supported` lists what it can. |
| `invalid_input` | 400 | The body could not be parsed, or a field has the wrong type. |
| `harness_not_found` | 404 | No such harness in the caller's scope. |
| `response_not_found` | 404 | No such response in the caller's scope. |
| `session_not_found` | 404 | No such session in the caller's scope. |
| `file_not_found` | 404 | No such file in the caller's scope. |
| `session_expired` | 404 | The session existed but is past its retention. |
| `harness_mismatch` | 409 | The task named a different harness than the session it continues. |
| `session_busy` | 409 | A task is already running in this session. |
| `file_too_large` | 413 | The upload exceeds the server's limit. `detail.max_bytes` states it. |
| `model_unavailable` | 422 | The requested model cannot be served for this harness. |
| `unsupported_base` | 422 | The requested harness base is not supported by this server. |

### 3.2 Authentication and limits

| Code | HTTP | Meaning |
|---|---|---|
| `missing_credential` | 401 | No bearer token. |
| `invalid_credential` | 401 | The token is malformed, unknown, or revoked. |
| `insufficient_scope` | 403 | The credential cannot perform this operation. |
| `rate_limited` | 429 | Slow down. `Retry-After` SHOULD be set. |
| `quota_exhausted` | 429 | A budget is spent; retrying now will not help. |

### 3.3 Execution

| Code | Where | Meaning |
|---|---|---|
| `harness_error` | failed response | The harness ran and could not complete the work. |
| `harness_unavailable` | 503 | No capacity to run this harness right now. |
| `provider_error` | failed response | The upstream model provider refused or failed. |
| `timeout` | failed response | The task exceeded its wall-clock budget. |
| `cancelled` | cancelled response | The client cancelled it. |
| `preview_unavailable` | 501 | This server does not render previews. |
| `preview_failed` | 502 | Conversion of this file failed. |

## 4. Retrying

| Situation | Retry? |
|---|---|
| `server_error` (500, 502, 503, 504) | Yes, with exponential backoff and jitter |
| `rate_limited` | Yes, after `Retry-After` |
| `quota_exhausted` | No — nothing will change until the quota does |
| `session_busy` | Yes, once the in-flight task is terminal |
| Any `invalid_request_error` | No — fix the request |
| `authentication_error` | No — fix the credential |
| A task that reached `failed` | Only with the client's own judgment; it consumed real resources |

**Retries of `POST /v1/responses` MUST carry an `Idempotency-Key`.** Without one, a retry after a
timeout runs the task a second time — and the first may still be running, editing the same files.
This is the single most damaging mistake a UHP client can make; see [Tasks §6](tasks.md).

## 5. Timeouts

A client SHOULD set generous timeouts. Agent tasks routinely run for minutes; a 30-second HTTP
timeout will cancel healthy work.

- Streaming: no total timeout. Use an inactivity timeout instead — a server SHOULD emit a comment
  line (`: keep-alive`) at least every 30 seconds so the client can distinguish a working agent from
  a dead connection.
- Non-streaming: at least the task's `timeout_seconds`, plus margin.
- A client that gives up MUST NOT assume the task stopped. It has not. Cancel it explicitly.
