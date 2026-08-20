# Architecture

**Unified Harness Protocol, version `2026-08-11`**

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and
OPTIONAL in this specification are to be interpreted as described in [RFC 2119][rfc2119] and
[RFC 8174][rfc8174] when, and only when, they appear in all capitals.

[rfc2119]: https://www.rfc-editor.org/rfc/rfc2119
[rfc8174]: https://www.rfc-editor.org/rfc/rfc8174

## 1. Roles

```
┌──────────┐   UHP over HTTP   ┌──────────┐   implementation-defined   ┌──────────┐
│  Client  │ ────────────────▶ │  Server  │ ─────────────────────────▶ │ Harness  │
└──────────┘                   └──────────┘                            └──────────┘
```

**Client** — an application that wants work done: a product backend, a CLI, a CI job, another agent.
A client speaks only UHP. It MUST NOT be required to know which harness implementation runs behind
the server, nor how the server executes it.

**Server** — implements this specification. It accepts tasks, drives one or more harnesses, and
reports progress and results in the vocabulary defined here. Everything about *how* it runs a
harness — containers, subprocesses, queues, remote workers — is out of scope for this specification
and MUST NOT leak into the wire format.

**Harness** — a complete agent runtime with its own loop, tools and session state. UHP does not
specify the harness itself; it specifies how a client drives one through a server. Harnesses are
identified by a **base**: a stable string such as `codex`, `claude-code` or `hermes`.

A **configured harness** is a base plus configuration — default model, system prompt, tool
restrictions, skills, MCP servers, step and time budgets. It is the unit a client selects when it
sends work, and it is addressed by a server-assigned id.

> **Why a configured harness, and not just a base?**
> The same base behaves very differently with a different system prompt, a different model, or a
> different tool set. Making the configuration a first-class, addressable object means a product can
> change how its agent behaves without redeploying its backend, and means two products can share a
> server without sharing behaviour.

## 2. Conformance classes

A server declares which class it implements. Each class is cumulative: **Extended** includes
**Core**, **Full** includes **Extended**.

| Class | A server at this class MUST implement |
|---|---|
| **Core** | Capability discovery, harness discovery, non-streaming and streaming task execution, session continuation, cancellation, and the error model. |
| **Extended** | Core, plus file input, artifact retrieval, and session listing/inspection. |
| **Full** | Extended, plus harness lifecycle management (create, update, delete) and session sharing. |

A client MUST NOT assume any capability above **Core** without checking capability discovery
(see [Lifecycle §2](lifecycle.md)). A server MUST NOT advertise a capability it does not implement —
advertising is a promise, and a client that trusts it and receives a `404` has been lied to in a way
it cannot recover from.

The [conformance suite](../../conformance/) tests each class separately and reports per class. A
server that passes at a class MAY describe itself as "UHP 2026-08-11 conformant (<class>)". No
other use of the term "conformant" is meaningful.

## 3. Object model

Six object types. Every one carries an `object` field naming its type, and an `id` with a
type-distinguishing prefix so an identifier is never ambiguous about what it points at.

| Object | `object` value | Id prefix | Lifetime |
|---|---|---|---|
| Harness | `harness` | `chrn_` | Until deleted |
| Response | `response` | `resp_` | Retained per server policy |
| Session | `session` | `hsess` | Until deleted |
| File | `file` | `file_` | With its container |
| Container | `container` | `cntr_` | With its session |
| Event | *(none — events carry `type`)* | — | Streamed, and replayable |

Their relationships:

```
Harness ──┐
          ├──▶ Session ──┬──▶ Response ──▶ Response ──▶ …    (one per task, chained)
Model  ───┘              └──▶ Container ──▶ File, File, …    (artifacts)
```

- A **response** is one task: one request in, one result out. It is the atomic unit of work.
- A **session** is a chain of responses that share conversational context and a working directory.
  A session is created implicitly by the first task and extended by `previous_response_id`.
- A **container** is the file namespace of a session. Files the agent writes become artifacts in it.

> **Why is the session implicit?**
> Requiring `POST /sessions` before any work could be done would add a round trip, a failure mode,
> and an object to clean up — for a concept most first tasks never need. A client that only ever
> sends one-shot tasks never learns the word "session"; a client that needs continuity gets it by
> quoting the id it already has.

## 4. Transport

- All requests MUST be HTTP/1.1 or later over TLS, except for loopback development where a server
  MAY accept plaintext.
- Request and response bodies are `application/json; charset=utf-8`, except file upload
  (`multipart/form-data`) and file download (the file's own media type).
- Streaming uses Server-Sent Events (`text/event-stream`) as described in
  [Streaming](streaming.md).
- Servers MUST accept requests with an absent `Accept` header and default to JSON.

## 5. Authentication

A client authenticates with a bearer token:

```http
Authorization: Bearer <token>
```

How tokens are issued is out of scope. A server MUST reject an absent, malformed, or unknown token
with `401` and the error model in [Errors](errors.md), and MUST NOT distinguish "no such token"
from "token not permitted here" in a way that lets a caller enumerate valid tokens.

A server MUST scope every object to the principal that created it. A client MUST NOT be able to
read, continue, cancel or delete another principal's response, session, or file — including by
guessing an id. Servers MUST return `404`, not `403`, for objects outside the caller's scope, so
that an id's existence is not disclosed.

## 6. Design principles

These are the rules the specification holds itself to. They are included because they explain the
shape of what follows, and because a future change that violates one is probably a mistake.

1. **The client should not be able to tell which harness ran the work** — except by asking. Every
   difference between harnesses that a client can observe is a leak, and each leak is a place where
   swapping harnesses breaks a product.
2. **Progress is a stream of facts, not a rendering.** Events describe what happened — text, a tool
   call, a file — never how to display it.
3. **A field means one thing.** Where UHP extends a borrowed surface, it adds fields; it never
   redefines one.
4. **Absent is not empty, and empty is not zero.** A server that does not know a value omits it. It
   MUST NOT invent a placeholder, an estimate, or a zero.
5. **Failure is a first-class result.** Every failure is reportable in the same envelope as success,
   with a machine-readable code. A client should never have to parse prose to find out what to do.
6. **The specification, the reference implementation and the conformance suite move together.** A
   sentence here that no test enforces is a wish, not a standard.
