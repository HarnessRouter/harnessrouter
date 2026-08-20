# Lifecycle

**Unified Harness Protocol, version `2026-08-11`**

This chapter defines how a client and server agree on a protocol version, how a client learns what
a server can do, and the states a task moves through from submission to result.

## 1. Version negotiation

UHP versions are dates: `YYYY-MM-DD`, the day the version was published. Dates sort, do not imply a
compatibility promise that semantic versioning would imply and not keep, and make the age of an
implementation obvious. See [VERSIONING.md](../../VERSIONING.md) for the compatibility rules.

A client MAY declare the version it was written against:

```http
UHP-Version: 2026-08-11
```

- If the header is absent, the server MUST assume its own default version and MUST state that
  version in the response header. A client that omits the header is asking for the server's choice,
  and gets it.
- If the header names a version the server supports, the server MUST honour it for that request.
- If the header names a version the server does not support, the server MUST fail the request with
  `400` and `code: "unsupported_protocol_version"`, and the error `detail` MUST list the versions it
  does support. It MUST NOT silently serve a different version — a client that asked for a version
  it can parse should not receive one it cannot.

Every response, including errors, MUST carry the version actually used:

```http
UHP-Version: 2026-08-11
```

## 2. Capability discovery

```http
GET /v1/uhp
```

Unauthenticated or authenticated — a server MUST serve this endpoint without a bearer token, because
a client needs to know whether it is talking to a UHP server *before* it can sensibly present
credentials. The document MUST NOT contain anything principal-specific.

```json
{
  "object": "uhp.discovery",
  "protocol": "uhp",
  "versions": ["2026-08-11"],
  "default_version": "2026-08-11",
  "conformance_class": "full",
  "capabilities": {
    "streaming": true,
    "sessions": true,
    "cancellation": true,
    "files_input": true,
    "files_output": true,
    "session_listing": true,
    "harness_management": true,
    "session_sharing": true,
    "idempotency": true
  },
  "implementation": { "name": "HarnessRouter Community Edition", "version": "0.3.0" }
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `object` | string | yes | Always `uhp.discovery` |
| `protocol` | string | yes | Always `uhp` — lets a client distinguish UHP from a lookalike |
| `versions` | string[] | yes | Every version this server can serve; MUST be non-empty |
| `default_version` | string | yes | Used when the client sends no `UHP-Version`; MUST appear in `versions` |
| `conformance_class` | string | yes | `core`, `extended` or `full` |
| `capabilities` | object | yes | Named booleans; see below |
| `implementation` | object | no | Free-form identification, for debugging and bug reports |

A server MUST report `false` for a capability it does not implement, rather than omitting it, so
that a client can tell "not supported" from "server is older than this field". A client MUST treat
an absent capability key as `false`.

`conformance_class` MUST be consistent with `capabilities`: a server claiming `extended` MUST report
`files_input`, `files_output` and `session_listing` as `true`. The conformance suite checks this,
because a class claim that contradicts the capability list tells a client two different things.

## 3. Task lifecycle

A task moves through these states. `status` on the response object carries the current one.

```
                    ┌──────────────┐
   POST /responses  │              │
   ────────────────▶│ in_progress  │
                    │              │
                    └──────┬───────┘
                           │
        ┌──────────────────┼──────────────────┬───────────────────┐
        ▼                  ▼                  ▼                   ▼
   ┌──────────┐      ┌──────────┐      ┌────────────┐      ┌───────────┐
   │completed │      │  failed  │      │ incomplete │      │ cancelled │
   └──────────┘      └──────────┘      └────────────┘      └───────────┘
```

| Status | Meaning | Terminal |
|---|---|---|
| `in_progress` | Accepted and running | no |
| `completed` | The harness finished the work and produced a result | yes |
| `failed` | The task could not be completed; `error` explains why | yes |
| `incomplete` | The harness stopped at a budget — step limit or time limit — with partial output | yes |
| `cancelled` | The client cancelled it; partial output MAY be present | yes |

Rules:

- A server MUST NOT transition out of a terminal state. Once a client has seen `completed`, later
  reads of that response MUST return `completed`.
- `incomplete` MUST be used when a budget stopped the work, and MUST NOT be used for errors. The
  distinction matters to a client: `incomplete` is usually worth continuing, `failed` usually is not.
- A `cancelled` task MUST report `cancelled`, not `failed`. A client that asked for a stop did not
  experience an error.
- Terminal responses MUST retain whatever output was produced before they became terminal. Discarding
  partial work because a task later failed destroys the only evidence of what went wrong.

## 4. Session lifecycle

```
first task ──▶ session created implicitly ──▶ session active ──▶ deleted (client) or expired (server policy)
                                                    ▲    │
                                                    └────┘
                                          each continued task extends it
```

- A session is created by the server when the first task of a chain runs. Its id MUST be reported in
  the response's `metadata.session_id`.
- A session MUST preserve, across tasks in the chain: conversational context, the working directory
  and its files, and the configured harness.
- A session MUST NOT be extended by a task that names a different configured harness. A server MUST
  fail such a request with `409` and `code: "harness_mismatch"` rather than silently starting a new
  session — continuing a conversation with a different agent is a different conversation, and doing
  it quietly loses work the client believed it had.
- Session expiry is server policy. A server that expires sessions MUST report `404` with
  `code: "session_expired"` on continuation, distinguishable from `session_not_found`.

## 5. Concurrency

- A server MUST accept concurrent tasks in *different* sessions.
- A server MUST NOT run two tasks concurrently in the *same* session: a session has one working
  directory and one conversation, and two agents writing to both is not a defined state. A second
  task for a busy session MUST fail with `409` and `code: "session_busy"`.
- A client that receives `session_busy` SHOULD wait for the in-flight task to reach a terminal state
  and retry. Servers SHOULD include `retry_after_ms` in the error `detail` when they can estimate it,
  and MUST omit it when they cannot rather than guessing.
