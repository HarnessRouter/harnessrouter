# Unified Harness Protocol (UHP)

**An open standard for running complete agent harnesses as shared infrastructure.**

A *harness* is a complete agent runtime — a loop that plans, calls tools, edits files, and reports
back. Codex, Claude Code and Hermes are harnesses. Each one already knows how to do the work; what
none of them agree on is how a product should *drive* one: how to start a task, follow its
progress, continue the conversation, cancel it, get the files it produced, and understand why it
failed.

Today every product answers those questions again, per harness. UHP answers them once.

```
   your product ──▶ UHP ──▶ ┌── Codex
                            ├── Claude Code
                            ├── Hermes
                            └── the harness that ships next year
```

UHP is not a model API and does not replace one. Model APIs give you a *turn*: messages in, tokens
out, tools you have to run yourself. UHP gives you a *task*: work in, and a running agent that uses
its own tools, keeps its own session, and hands back results and files. The unit of exchange is a
job, not a completion.

## Status of this document

| | |
|---|---|
| **Current version** | `2026-08-11` |
| **Status** | Draft standard — stable enough to build on, versioned so it can change safely |
| **Specification** | [`versions/2026-08-11/`](versions/2026-08-11/) |
| **Machine-readable** | [`schema/`](schema/) — OpenAPI 3.1 + JSON Schema 2020-12 |
| **Conformance suite** | [`conformance/`](conformance/) — runnable, and the definition of "conformant" |
| **Change process** | [`GOVERNANCE.md`](GOVERNANCE.md) |
| **Versioning rules** | [`VERSIONING.md`](VERSIONING.md) |
| **License** | Apache-2.0, same as the repository |

## No hosted service required

UHP is an HTTP contract. A conformant server is any server that answers the requests in this
specification with the responses in this specification. It may run agents in containers, in
subprocesses, on a queue, or on someone else's infrastructure. Nothing in the wire format requires
a hosted service, an account, a licence key, or a call home — a conformant server can run wholly on
your own machine, on your own provider keys, storing everything on a volume you own.

A client written against this specification works with any server that passes the conformance
suite, whoever built it. The [examples](IMPLEMENTATIONS.md) page lists the servers and clients
built against UHP so far. If you find a behaviour the specification does not describe but
your client depends on, that is a specification bug — please
[open an issue](https://github.com/HarnessRouter/harnessrouter/issues).

## What the protocol covers

| Chapter | What it defines |
|---|---|
| [Architecture](versions/2026-08-11/architecture.md) | Roles, conformance classes, and the object model |
| [Lifecycle](versions/2026-08-11/lifecycle.md) | Version negotiation, capability discovery, task lifecycle |
| [Harnesses](versions/2026-08-11/harnesses.md) | Discovering, selecting and configuring a harness |
| [Tasks](versions/2026-08-11/tasks.md) | Sending work and receiving a result |
| [Streaming](versions/2026-08-11/streaming.md) | Following progress as it happens |
| [Sessions](versions/2026-08-11/sessions.md) | Continuing a conversation, and cancelling one |
| [Files](versions/2026-08-11/files.md) | Sending files in, getting artifacts out |
| [Errors](versions/2026-08-11/errors.md) | Failure taxonomy, retries and idempotency |
| [Security](versions/2026-08-11/security.md) | What an implementer must get right, collected in one place |
| [Schema](versions/2026-08-11/schema.md) | The machine-readable definitions and how to use them |

## Quick shape of it

Discover what a server can run, run something, and follow it:

```bash
curl -s https://your-uhp-server/v1/harnesses -H "Authorization: Bearer $KEY"

curl -s -N https://your-uhp-server/v1/responses \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
        "input": "Summarise README.md in three bullets.",
        "model": "claude-sonnet-4.6",
        "metadata": { "harness_id": "chrn_…" },
        "stream": true
      }'
```

The stream is Server-Sent Events. The last event carries the finished `response` object, including
any files the agent produced. To continue the same conversation, send the next request with
`previous_response_id` set to the id you just received.

Full walk-through: [Tasks](versions/2026-08-11/tasks.md).

## Relationship to the OpenAI Responses API

UHP's task surface is deliberately shaped like the OpenAI Responses API, and a conformant server
MUST accept the subset of that request body described in [Tasks](versions/2026-08-11/tasks.md) and
emit the event vocabulary described in [Streaming](versions/2026-08-11/streaming.md).

This is a compatibility decision, not an accident. Products already have code that speaks Responses;
existing SDKs, streaming parsers, and UI components work against a UHP server with no changes. What
UHP adds is everything a *harness* needs and a model endpoint has no concept of: which harness runs
the work, its tools and skills, the session that survives between tasks, the files that come back,
and the cancellation of work that is already running.

Where UHP extends the Responses surface it does so in documented, additive places — `metadata`, a
small number of extra request fields, and additional object types — never by changing the meaning
of an existing field. A client that ignores every UHP extension still gets a working task.

## Implementing UHP

1. Read [Architecture](versions/2026-08-11/architecture.md) and pick a conformance class.
2. Generate types from [`schema/uhp-2026-08-11.openapi.yaml`](schema/uhp-2026-08-11.openapi.yaml).
3. Run the [conformance suite](conformance/) against your server while you build:
   ```bash
   pip install -e protocol/conformance
   uhp-conformance --base-url https://your-server --api-key "$KEY"
   ```
4. Publish your report. A server that passes at a class MAY describe itself as
   "UHP 2026-08-11 conformant (<class>)".

Two role-specific guides walk through this in order:
[Implement a client](CONNECTING.md) — discovery, task submission, event handling, and
artifact retrieval — and [Implement a server](SERVING.md) — the operations a server answers
and how it connects one or more harnesses.

## Contributing

Changes to this specification follow [`GOVERNANCE.md`](GOVERNANCE.md). The short version: propose in
prose first, and no change lands unless the specification, the reference implementation and the
conformance suite move together.

## Background

For the story behind the name, the alternatives weighed and why *Unified* won the letters UHP, see
[Background: the naming of UHP](naming).
