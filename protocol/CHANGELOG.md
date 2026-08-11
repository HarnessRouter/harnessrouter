# Changelog

All notable changes to the Unified Harness Protocol.

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
