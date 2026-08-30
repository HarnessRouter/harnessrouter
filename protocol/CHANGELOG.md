# Changelog

All notable changes to the Unified Harness Protocol.

## Unreleased — additive to 2026-08-11

### Clarified

- **`tools` and `include` are reserved and ignored** ([Tasks §1.4](versions/2026-08-11/tasks.md#14-reserved-fields-tools-and-include)).
  Both arrived with the OpenAI Responses wire shape this version stays compatible with, and neither
  ever had defined semantics in UHP. A server accepts them and does not act on them.

  `tools` cannot mean what it means in the Responses API, where the *client* executes tools and
  returns the result as input: UHP puts both the call and its result in `output`, so there is no
  input path for the return leg and the loop the field implies cannot be completed. The other
  plausible reading — per-request MCP servers — is already covered by
  [Harnesses §4.1](versions/2026-08-11/harnesses.md#41-mcp-servers), and would be an escalation
  primitive besides: it would let any caller point the agent at an endpoint of their choosing,
  executed with the harness owner's credentials and workspace. The rule underneath, stated so it
  can be applied again: **narrowing is safe, widening is escalation.**

- **`metadata.ignored_fields` is specified** ([Tasks §1.1](versions/2026-08-11/tasks.md#11-request-fields)),
  and required when a request carries a reserved field. Ignoring has to be observable, for the same
  reason model substitution is reported in §1.3: a silently dropped field is indistinguishable from
  an honoured one.

- **GOVERNANCE.md records "a declined field is not a pending one"** — the general rule these two
  fields are the worked example of. Due to @aenawi in
  [#42](https://github.com/HarnessRouter/harnessrouter/issues/42).

Nothing is removed and no client breaks: a request sending either field was already accepted and
already had no effect. Removal is a question for the next version.

### Conformance

Three checks at class Core, in both directions, where the suite previously sent neither field:
**T-08** a request carrying them is accepted, **T-09** they are reported in
`metadata.ignored_fields`, **T-10** a request that sent neither is not told one was ignored. Core
goes from 37 checks to 40.

## 2026-08-11 — first published version

The initial specification, extracted from the shipping HarnessRouter implementation rather than
designed in the abstract. Every endpoint and event described here was already running in production
before it was specified; the work was to write down the contract precisely, close the gaps that
writing it down revealed, and make the result testable.

### Defined

- **Architecture** — client / server / harness roles, three conformance classes (Core, Extended,
  Full), the six-object model, transport and authentication.
- **Lifecycle** — `UHP-Version` negotiation, the `GET /v1/uhp` discovery document, task states
  (`in_progress`, `completed`, `failed`, `incomplete`, `cancelled`), session lifecycle, concurrency
  rules.
- **Harnesses** — discovery, the harness object, model catalogues, computed `available`, and
  harness management at class Full.
- **Tasks** — `POST /v1/responses`, the response object, harness selection via `metadata.harness_id`,
  model substitution reporting, idempotency.
- **Streaming** — the SSE event vocabulary, `sequence_number` ordering guarantees, reconnection.
- **Sessions** — continuation via `previous_response_id`, listing, inspection, cancellation, sharing.
- **Files** — inline and uploaded input, artifact annotations, download, preview, retention.
- **Errors** — a single error envelope, a closed set of codes, retry rules.

### Gaps this closed in the reference implementation

Writing the specification exposed three places where the implementation had no defined behaviour:

- **No capability discovery.** A client had to guess what the server supported, or discover it from
  a 404. Added `GET /v1/uhp`.
- **No protocol version on the wire.** Nothing identified which contract a response was written to.
  Added the `UHP-Version` header on every response.
- **Unstructured errors.** Failures returned a bare human-readable string, so a client had to match
  on prose to decide whether to retry. Added the structured error envelope, with the previous string
  retained as a deprecated alias so existing clients keep working.

### Known compromises

Recorded in [VERSIONING.md](VERSIONING.md#the-current-versions-known-compromises): mixed field
casing between the task and harness surfaces, and session deletion living at `/v1/traces/{id}`. Both
are kept for compatibility and marked for a future major version.
