# Implement a server

How to put an agent harness behind the Unified Harness Protocol — what a server must
answer, in what order to build it, and how to prove it works. This guide is the
practical companion to the [specification](versions/2026-08-11/index.md); where the two
disagree, the specification wins.

## What a UHP server is

A UHP server is any HTTP server that answers the requests in the specification with the
responses in the specification. It may run agents in containers, in subprocesses, on a
queue, or on someone else's infrastructure. Nothing in the wire format requires a hosted
service, an account, a licence key, or a call home.

Two shapes of server exist, and the contract is identical for both:

- A **runner** puts existing harnesses — Codex, Claude Code, Hermes — behind the
  contract and advertises them as its catalog.
- A **native harness** speaks UHP itself: one harness, served directly, no adapter in
  between. If you maintain a harness, this is the shape that makes every UHP client
  yours at once.

## The contract, in build order

Build in the order the conformance suite tests, because each stage is testable on its
own:

1. **Discovery** — advertise the harnesses you run and the models they accept.
   [Harnesses chapter](versions/2026-08-11/harnesses.md).
2. **Tasks** — accept one unit of work, run it, return the result. The task surface is
   deliberately shaped like a responses API, plus what a harness needs and a model
   endpoint has no concept of. [Tasks chapter](versions/2026-08-11/tasks.md).
3. **Streaming** — report progress while long tasks run, and survive a dropped
   connection. [Streaming chapter](versions/2026-08-11/streaming.md).
4. **Sessions** — let a task continue where a previous one left off.
   [Sessions chapter](versions/2026-08-11/sessions.md).
5. **Files** — take files in, hand artifacts back.
   [Files chapter](versions/2026-08-11/files.md).
6. **Cancellation and errors** — stop running work cleanly and fail in the documented
   taxonomy. [Errors chapter](versions/2026-08-11/errors.md).

The [schema chapter](versions/2026-08-11/schema.md) publishes OpenAPI 3.1 and JSON
Schema 2020-12 for every version — generate your types instead of writing them.

## Prove it

Run the conformance suite against your server from day one; it is designed to be a
development tool, not a final exam:

    pip install -e protocol/conformance
    uhp-conformance --base-url https://your-server --api-key "$KEY" --class core

Classes are cumulative: `core` is the contract every server must answer, `extended` and
`full` add the surfaces above it. `--only` reruns a single failing check while you fix
it, and every failure cites the specification sentence it violates. The suite runs real
agent tasks — that is deliberate, because the defects worth catching only appear when
real work runs.

## Get listed

When the suite passes at any class, add your server to the
[examples](IMPLEMENTATIONS.md) page by pull request, with the report JSON as
evidence. Listing is not certification, and the page says so — but a row with a
reproducible report is how every ecosystem entry starts.

Questions the specification does not answer belong in
[GitHub discussions](https://github.com/HarnessRouter/harnessrouter/discussions);
changes you need belong in [governance](GOVERNANCE.md), prose first.
