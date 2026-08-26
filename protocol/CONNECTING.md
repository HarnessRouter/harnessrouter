# Implement a client

A UHP [client](versions/2026-08-11/architecture.md#1-roles) discovers the harnesses a server
runs, submits a task, receives progress events, and retrieves the resulting files. It speaks
only UHP over HTTP and does not need to know which harness runs behind the server. This guide
is the procedure; the [Architecture chapter](versions/2026-08-11/architecture.md#1-roles) is
the definition.

For the other role — a server that runs harnesses behind the contract — see [Implement a server](SERVING.md).

## What a client does

A client is a product, CLI, CI job, or another agent that wants work done. It does not run
the harness; it drives a server that does. The full definitions of client, server, and
harness are in the [Architecture chapter](versions/2026-08-11/architecture.md#1-roles) — this guide is
the procedure, not the definition.

Integration is deliberately light. The task surface is shaped like a responses API, so most
of the work is ordinary HTTP plus reading an event stream.

## Generate the client

Do not hand-write types. Every version publishes OpenAPI 3.1 and JSON Schema 2020-12 in the
[schema chapter](versions/2026-08-11/schema.md) — generate a typed client for your language from it and
you have the request and response shapes for free.

## The integration, step by step

1. **Discover the catalog.** Ask the server which harnesses it runs and which models each
   accepts. A client selects a *configured harness* — a base plus its configuration — by the
   server-assigned id. [Harnesses chapter](versions/2026-08-11/harnesses.md).
2. **Submit a task.** One unit of work: input in, result out. Name the configured harness and
   send the request. [Tasks chapter](versions/2026-08-11/tasks.md).
3. **Consume the stream.** Read the event stream to follow progress while the task runs, and
   reconnect if the connection drops — the protocol defines how to resume without losing
   events. [Streaming chapter](versions/2026-08-11/streaming.md).
4. **Continue in a session.** To pick up where a task left off, carry the session forward
   instead of starting cold. [Sessions chapter](versions/2026-08-11/sessions.md).
5. **Take the artifacts.** Download the files the run produced. [Files chapter](versions/2026-08-11/files.md).
6. **Cancel and handle errors.** Stop work cleanly, and read failures from the documented
   error taxonomy rather than guessing from status codes. [Errors chapter](versions/2026-08-11/errors.md).

## A minimal end-to-end shape

A client that submits one task and reads its result touches only the core surface:

    POST /v1/tasks            → submit against a configured harness
    GET  /v1/tasks/{id}/events → stream progress to completion
    GET  /v1/tasks/{id}        → read the result
    GET  /v1/files/{id}        → download an artifact

Generate the exact request and response bodies from the [schema](versions/2026-08-11/schema.md); the
[conformance suite](conformance/README.md) shows the same calls run against a real server.

## Next

For the server role, see [Implement a server](SERVING.md). Questions the specification does not answer belong in
[GitHub discussions](https://github.com/HarnessRouter/harnessrouter/discussions).
