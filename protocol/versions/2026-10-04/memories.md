# Memories

**Unified Harness Protocol, version `2026-10-04`**

An agent forgets. A session's conversation ends when the session ends ([Sessions](sessions.md)),
and a harness's instructions are written once by its owner and do not change as the agent works.
So whatever an agent learns along the way is lost: that a customer prefers email, what the team
decided last week, which procedure worked last time.

Until this version the protocol had nowhere to keep those things. A product that wanted memory
attached a memory service to one harness, through that service's own API, with that service's own
idea of whose memory it was, and with no way to say who may read what.

A **memory** is where they are kept. It is a named container of **records**: a fact, a note, a
procedure. Memories are arranged in a tree, the way folders are, so one memory can hold what a whole
company knows and another, beneath it, what is known about one customer. Access is granted per
memory, and a memory's children inherit it.

A harness is attached to the memories its agent should start from. During a task the agent searches
them and adds to them with tools. What it may read and where it may write is decided by the server,
from what the harness was granted, and never by the agent itself.

This chapter is the Harness Memories sub-protocol. It is optional: a server advertises it with the
`memories` capability, and a server that does not implement it is conformant at every class.

## 1. What a memory is

UHP does not define how memory is derived. Extraction, ranking, consolidation and storage belong to
the system behind the memory, the **provider**: a vendor's memory service, a graph database, a
folder of files. This chapter defines the three things a harness and a provider must agree on, and
nothing else:

```
the provider     its own store and intelligence    how memory is derived and kept
UHP Memories     this chapter                      what a memory is, who may reach it,
                                                   and when a harness calls it
MCP              the tools an agent holds          how the agent calls it during a turn
```

- **The object.** A memory is a node in a tree. It holds **records** and may have child memories.
- **The access.** A grant gives a principal privileges on a node; the node's descendants inherit it.
- **The seam.** A harness reaches memory at four moments of a session's life ([§9.1](#91-what-a-session-does)),
  and only two of them are the agent's choice.

> **Why a tree and not a fixed set of scopes?**
> Memory products each name their own levels (user, agent, run, app, team, project) and none of the
> lists agree. A level is a meaning an implementation gives to a place in a tree: the protocol
> carries the tree and the inheritance, and a server is free to say that one node is an
> organization and the one under it a customer. A node exists where access differs, and nowhere
> else: a session's memory needs no node of its own when it is read by exactly the principals that
> read its parent.

## 2. The memory object

```json
{
  "id": "hmem_7c1e4b9a2d3f4e5a8b6c7d8e9f0a1b2c",
  "object": "memory",
  "name": "Sales",
  "description": "What the sales team knows: accounts, objections that came up, pricing decisions.",
  "parent_id": "hmem_0a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "ancestors": ["hmem_0a1b2c3d4e5f60718293a4b5c6d7e8f9"],
  "restricted": false,
  "provider": "example",
  "privileges": ["read", "write"],
  "records": { "count": 412 },
  "children": { "count": 3 },
  "createdAt": 1790560000000,
  "updatedAt": 1790570094000
}
```

| Field | Type | Written by | Meaning |
|---|---|---|---|
| `id` | string | server | `hmem_`-prefixed |
| `name` | string | client | Human-readable |
| `description` | string | client | What this memory holds, in a sentence or two. An agent reads it to decide whether to look inside ([§6.1](#61-reading-is-a-walk)), so it is content, not decoration |
| `parent_id` | string or null | client | The containing memory; `null` on a root |
| `ancestors` | array | server | The ids from the root down to the parent, as far up as the caller may see. Placement only: reading a memory never reads an ancestor's records |
| `restricted` | boolean | client | When `true`, grants on ancestors stop here ([§3.2](#32-the-cutoff)) |
| `provider` | string | client | Which provider keeps this memory's records ([§10](#10-providers)). Set at creation, inherited from the parent when omitted; a server MAY refuse to change it |
| `privileges` | array | server | The caller's effective privileges on this node |
| `records`, `children` | object | server | Counts, for a caller deciding where to look |

```http
POST   /v1/memories                          create (name, description, parent_id, restricted, provider)
GET    /v1/memories?parent={id}              the direct children of a memory (or the roots), paginated
GET    /v1/memories/{id}                     one memory
PUT    /v1/memories/{id}                     rename; description; restricted; move (parent_id)
DELETE /v1/memories/{id}                     delete the memory, its records and its descendants
```

A listing is one level. Without `parent` it answers where the caller enters the tree: every memory
it holds a privilege on whose parent it cannot see, so a caller granted one branch enters at that
branch. A client that wants a subtree asks level by level, or passes `ancestor={id}` for every
descendant it may read. A server MUST NOT return a memory on which the
caller has no effective privilege, and MUST NOT reveal that one exists.

## 3. Access

### 3.1 Grants and inheritance

A **grant** gives one principal a set of privileges on one memory. A principal's effective
privileges on a memory are the union of its grants on that memory and on every ancestor. Access is
additive: there is no deny, and no grant means no access. Whoever creates a memory holds all four
privileges on it, an implicit grant that flows down like any other.

| Privilege | Permits |
|---|---|
| `read` | `recall`, `get`, `list`, `history`, running a named query marked `read` |
| `write` | `observe`, `remember`, `revise`, `forget`, defining a named query |
| `create` | Creating a child memory |
| `delete` | `erase`, deleting the memory, changing its grants |

```http
GET    /v1/memories/{id}/grants              who holds what, and on which node each grant sits
POST   /v1/memories/{id}/grants              { principal, privileges }
DELETE /v1/memories/{id}/grants/{grant_id}
```

A **principal** is an opaque typed identifier the server resolves: a harness, a credential, a
person, a group. The protocol does not define principals beyond that; a server documents the kinds
it accepts.

### 3.2 The cutoff

A memory with `restricted: true` stops inheritance: grants on its ancestors do not reach it or its
descendants, and its own grants flow down as usual. It is the only override. A server SHOULD create
a memory that holds one person's private records as restricted.

### 3.3 Enforcement

Access is enforced by the server on every operation and cannot be chosen, widened or bypassed by a
model. A provider isolates memories either by keeping each in a container of its own or by a
condition the server adds to every read and write; it declares which ([§10.2](#102-the-capability-document)).
A filter applied by the agent, or one a query the agent wrote could omit, is not enforcement.

## 4. Records

A record is one thing a memory holds. Its `id` is the provider's and opaque to a client.

```json
{
  "id": "hrec_3b9f2a71c4d84e0f9a6b5c4d3e2f1a0b",
  "object": "memory.record",
  "memory_id": "hmem_7c1e4b9a2d3f4e5a8b6c7d8e9f0a1b2c",
  "type": "fact",
  "content": "Acme renews in March and wants the annual discount kept.",
  "attributes": { "account": "acme" },
  "version": 2,
  "status": "active",
  "supersedes": "hrec_11aa22bb33cc44dd55ee66ff77889900",
  "time": {
    "valid_from": "2026-09-30T00:00:00Z", "valid_to": null,
    "written_at": "2026-10-01T17:02:11Z", "invalidated_at": null
  },
  "written_by": { "kind": "harness", "id": "chrn_41c0" },
  "references": [ { "rel": "derived_from", "memory_id": "hmem_…", "record_id": "hrec_…" } ],
  "trust": "untrusted"
}
```

| Field | Meaning |
|---|---|
| `type` | What kind of record ([§4.1](#41-types)) |
| `content` | Text, or a file reference `{ "file": { "id", "name", "bytes", "media_type", "version" } }` |
| `attributes` | Structured fields. Free-form for core types; the type's schema for extension types ([§8](#8-types)) |
| `version`, `status`, `supersedes` | A change appends a version and closes the one before it ([§5.3](#53-nothing-is-overwritten)). `status` is `active`, `superseded` or `forgotten` |
| `time` | When it was true in the world (`valid_*`) and when the memory held it (`written_at`, `invalidated_at`). A provider without validity leaves `valid_*` null |
| `written_by` | Stamped by the server from the authenticated caller. A client cannot supply it |
| `references` | Other records this one points at ([§4.2](#42-references)) |
| `trust` | Always `untrusted` on a read: what a memory returns is data, never instructions ([§13](#13-security)) |

### 4.1 Types

The core types every server understands:

| `type` | What it is |
|---|---|
| `episode` | Raw experience as it arrived: a turn, a transcript, an action and its result, a document. Append-only |
| `fact` | One thing worth remembering, as it was said |
| `note` | A document an agent or a person wrote and maintains |
| `procedure` | A how-to with the situation it applies to |
| `link` | A pointer to something kept elsewhere: an address and a description, no content of its own |

Any other type is an extension ([§8](#8-types)). A server MUST carry a record of a type it does not
understand unchanged, and MUST NOT refuse a read because of it.

### 4.2 References

A reference names a record by `memory_id` and `record_id`. The two ends need not be in the same
memory, or with the same provider.

- A reference is resolved when it is **read**, with the reader's privileges. A reader without `read`
  on the target memory receives `{ "memory_id", "record_id", "available": false }` and nothing
  else.
- Writing a reference does not require `read` on its target. A record promoted from a private
  memory into a shared one keeps its source, and only those who may read the source can follow it.

## 5. Operations

```http
POST   /v1/memories/{id}/observe             append episodes; the provider decides what to derive
GET    /v1/memories/{id}/jobs/{job}          what an observe that answered 202 has written since
POST   /v1/memories/{id}/records             remember: write one record as stated
POST   /v1/memories/{id}/recall              retrieve (§6)
GET    /v1/memories/{id}/records             list, paginated; filters; as_of
GET    /v1/memories/{id}/records/{rid}       one record; as_of
PATCH  /v1/memories/{id}/records/{rid}       revise: a new version
DELETE /v1/memories/{id}/records/{rid}       forget: close it, keep the trace
POST   /v1/memories/{id}/erase               remove content for good; reports what it could not reach
GET    /v1/memories/{id}/records/{rid}/history
```

### 5.1 Two ways to write

`observe` and `remember` differ in who decides.

- **`observe`** hands the provider raw episodes and nothing more. Whether a fact is extracted from
  them, when, and by what, is the provider's business. It is what a server calls after a turn
  ([§9.1](#91-what-a-session-does)). When the provider derives after it answers, `observe` answers
  `202` with `job: { id, status }` and no records yet; the job, read at its own route, carries
  `status` (`pending`, `completed`, `failed`) and the records it produced. A provider is not
  required to keep the episode itself as a record: one that keeps only what it derived says so
  ([§10.2](#102-the-capability-document)), and a client that needs the raw input later keeps it.
- **`remember`** writes the record the caller states, as stated. It is what an agent calls when it
  decides something is worth keeping.

A provider declares when its derivation runs: `write_time`, `background`, `agent`, or `none`
([§10.2](#102-the-capability-document)).

Every write accepts an `Idempotency-Key` ([Tasks](tasks.md)).

### 5.2 Two ways to remove

- **`forget`** closes a record: `status` becomes `forgotten`, it leaves every read that does not ask
  for history, and its place in the version chain remains. It needs `write`.
- **`erase`** removes content so that it cannot be read again, from the record and from what was
  derived from it. It needs `delete`, is never offered to an agent as a tool, and answers with the
  ids erased and an `unreachable` list of derived copies the provider could not remove. An empty
  `unreachable` is a guarantee; a provider that cannot give one says so.

### 5.3 Nothing is overwritten

A change to a record appends a version and closes the previous one. `history` returns the chain,
each version with its writer and time. `as_of` on `recall`, `get` and `list` reads the memory as it
stood at that instant.

A **snapshot** is a name for an instant: `POST /v1/memories/{id}/snapshots { name, message }`. It
copies nothing; reading `as_of` a snapshot's time is the same read.

A provider declares how much of this it keeps, for content and for structure separately:
`versions` (every version), `snapshots` (only between named points), or `none`.

## 6. Recall

### 6.1 Reading is a walk

`recall`, `list` and `get` act on the one memory named in the path. They read neither its
descendants nor its ancestors. A response carries where the caller can go from here: the memory's
`parent` and its direct `children`, each with its `name`, `description` and counts, and only those
the caller may read. An agent chooses where to look next, up or down, and reads there. The tree is
walked in both directions by the agent's own decisions, never by the server on its behalf.

A caller that wants several levels below at once passes `depth`; a server MAY cap it and MUST
report a cap it applied in `degraded`.

> **Why not search the whole subtree by default?**
> A subtree can hold one node per customer. A read that fans out across all of them is slow, costs
> in proportion to data the question never needed, and returns results the caller cannot place. An
> agent that reads a node's description and then decides is doing what a person does with folders.

### 6.2 The request

```json
{
  "query": "what did Acme say about renewal?",
  "text": "renewal",
  "filters": { "and": [ { "field": "attributes.account", "op": "eq", "value": "acme" } ] },
  "types": ["fact", "note"],
  "as_of": null,
  "include": "active",
  "limit": 8
}
```

| Field | Signal |
|---|---|
| `query` | Meaning: similarity to a question in natural language |
| `text` | Words: full-text match |
| `filters` | Fields: equality, range and membership over `type`, `attributes.*` and `time.*` |

Any one may be given alone. Given together, the provider fuses them into one ranking.

### 6.3 The response

```json
{
  "results": [
    { "record": { "id": "hrec_…", "type": "fact", "content": "…", "trust": "untrusted" },
      "score": 0.91, "why": ["query", "filters"] }
  ],
  "parent": { "id": "hmem_…", "name": "Company", "description": "…", "records": { "count": 97 } },
  "children": [ { "id": "hmem_…", "name": "Acme", "description": "…", "records": { "count": 58 } } ],
  "degraded": [],
  "abstain": false
}
```

- `why` names the signals that produced each result.
- `degraded` lists what the request asked for and the provider did not do (`"text:not_supported"`,
  `"depth:capped_at_2"`). A server MUST NOT ignore part of a request silently.
- `parent` is absent on a root, and equally absent when the caller may not read the parent: the two
  cases look the same.
- `abstain` is `true` when the provider judges that nothing it returned answers the question. A
  memory that cannot say "I do not know" will be believed when it should not be.

### 6.4 Named queries

What the three signals cannot express, the owner of a memory defines once, in the provider's own
language, as a **named query** with typed parameters:

```json
{
  "name": "open_deals_for",
  "description": "Deals not yet closed for one account.",
  "params": { "type": "object", "properties": { "account": { "type": "string" } }, "required": ["account"] },
  "requires": "read",
  "language": "cypher",
  "body": "…"
}
```

```http
GET    /v1/memories/{id}/queries
PUT    /v1/memories/{id}/queries/{name}      define or replace; needs write
POST   /v1/memories/{id}/queries/{name}      run with params; answers in the shape of §6.3
```

`language` and `body` are opaque to the protocol. A named query is offered to an agent as a tool
with `params` as its input schema. The server MUST run it within what the caller may read.

### 6.5 Free queries

A provider MAY also let a caller, an agent included, write a query and run it:

```http
POST /v1/memories/{id}/query        { "language": "cypher", "statement": "…", "params": { } }
```

It is optional and provider-dependent: the provider declares `queries.free` with the languages it
accepts ([§10.2](#102-the-capability-document)), and an agent is offered it as the tool
`memory_query`, whose description names the language and the memory's schema. The answer has the
shape of [§6.3](#63-the-response) where the result is records, and the provider's own rows otherwise.

Freedom over the statement is not freedom over the reach. A statement written by a model can leave
out the condition that confines it, so the confinement cannot be in the statement:

- The provider MUST run a free query within what the caller may read, by a means the statement
  cannot undo: a container the query cannot leave, or a scope the provider applies outside the
  statement. A provider that cannot do this MUST NOT declare `queries.free`.
- A free query reads. A provider that lets one write declares `queries.free.write`, needs `write`
  from the caller, and stamps `written_by` as on any other write.
- The server MAY bound a free query's time and result size and reports a bound it applied in
  `degraded`.

## 7. Files

A record's `content` may be a file. The server returns a reference with an opaque `version`; a
revision with new bytes is a new version of the record, and the earlier bytes remain readable
through `history` and `as_of` for as long as the provider keeps history.

```http
GET /v1/memories/{id}/records/{rid}/content[?version=…]
```

Upload follows [Files](files.md): the bytes are sent with `POST /v1/files` and the
record names the file's id.

## 8. Types

A provider may hold more than the core types: a calendar, a task board, a table, a workflow. Each is
a **type** the provider registers and describes.

```http
GET /v1/memories/types
```

```json
{ "data": [ {
  "type": "x.calendar.event",
  "description": "A meeting or a block of time.",
  "schema": { "type": "object", "properties": { "starts_at": { "type": "string" }, "attendees": { "type": "array" } } },
  "text": "title, attendees and time as one line, for recall",
  "operations": [
    { "name": "reschedule", "description": "Move to a new time.", "input": { "…": "…" }, "requires": "write" },
    { "name": "free_slots", "description": "Open time around this event.", "input": { "…": "…" }, "requires": "read" }
  ] } ] }
```

A record of an extension type is a record: it has an address, sits under its memory's access, is
versioned, can be referenced, and is found by `recall` through its text projection. The type adds
its fields and its **operations**:

```http
POST /v1/memories/{id}/records/{rid}/operations/{name}
```

Each operation states the privilege it needs and is offered to an agent as a tool. The protocol sets
no limit on type names (beyond the `x.` prefix for types it does not define), fields or operations.
A provider that registers none reports `types: false` and answers the listing with the core types.

## 9. Attaching memories to a harness

A harness names the memories it works with:

```http
PUT /v1/harnesses/{id}/memories          replace the list; an empty list detaches every memory
GET /v1/harnesses/{id}/memories
```

```json
{ "memories": [
    { "memory_id": "hmem_0a1b…", "access": "read" },
    { "memory_id": "hmem_7c1e…", "access": "write", "default": true }
] }
```

- Attaching is granting. Access has one source, the grants ([§3](#3-access)): an entry the
  harness already holds is attached as it is; one it does not hold is granted by the same call when
  the caller may change that memory's grants (`delete`), and refused otherwise, when the harness is
  written and not at run time. Detaching removes a starting point and leaves the grant, which is
  revoked where grants are.
- `access` narrows; it never widens. `read` on a memory the harness may also write gives the agent
  read tools only, on that memory and on whatever it walks to from it.
- One entry MAY be marked `default`: where `observe` and an unaddressed `remember` go.
- A task MAY name one more memory in `metadata.memory` on the request, where `harness_id` and
  `environment` already travel ([Tasks §1.2](tasks.md#12-selecting-the-harness)): the memory of
  the person this task is for, say. It is added to the harness's for the session the task starts,
  it is where that session writes by default when the harness may write it, and it is checked
  against the harness's privileges exactly as an attached memory is: a task naming a memory the
  harness holds nothing on is refused with `memory_not_found` before it starts. A memory is always
  named by its id. The server does not derive a node from anything else in a request, and creating
  a person's memory is the caller's act, done before the task with `POST /v1/memories`.

### 9.1 What a session does

| Moment | Called by | What happens |
|---|---|---|
| **Prime** | server, at session start and after the conversation is compacted | The server reads what the provider marks as always-relevant in each attached memory and places it, with each memory's `name`, `description` and children, in the agent's instructions |
| **Tools** | agent, during a turn | `memory_list`, `memory_recall`, `memory_get`, `memory_remember`, `memory_revise`, `memory_forget`, `memory_run_query` for the named queries a memory lists, `memory_operate` for a type's operations, and `memory_query` where a provider offers free queries. Write tools are offered only to a harness attached somewhere to write. The attached memories are where the agent starts; from each it may walk to the parent and the children a response names, and on from there, as far as the harness's own privileges reach. The server checks every step |
| **Observe** | server, when a turn ends | The turn (what was asked, what was answered, which tools ran) is sent to the default memory as episodes. No model is involved on the server's side |
| **Consolidate** | server, on a schedule or when idle | The server asks the provider to do its background work. What that is belongs to the provider |

How much a provider returns for priming is the provider's decision. The server records what it
placed, per memory, in tokens, with the turn, so
the cost is visible even where it is not set by the client.

Priming is not repeated every turn. Instructions that change every turn defeat prompt caching, and
retrieval during a turn is what the tools are for.

A server MUST tell the person who attaches a memory whose provider is outside the server that every
turn will be sent to it.

### 9.2 Consolidation runs

Background work that rewrites what a memory holds is visible, bounded and reversible, or it is not
trusted. A provider that consolidates through the protocol exposes each pass as a **run**:

```http
POST   /v1/memories/{id}/consolidations              start one now (budget optional)
GET    /v1/memories/{id}/consolidations              runs, newest first
GET    /v1/memories/{id}/consolidations/{run}        one run
GET    /v1/memories/{id}/consolidations/{run}/changes   the records it wrote, superseded or forgot
POST   /v1/memories/{id}/consolidations/{run}/revert
```

```json
{
  "id": "hcon_5d2e…", "object": "memory.consolidation", "memory_id": "hmem_7c1e…",
  "status": "completed",
  "trigger": "schedule",
  "started_at": 1790570000, "finished_at": 1790570094,
  "read": { "episodes": 240, "through": "2026-10-03T08:00:00Z" },
  "changes": { "created": 31, "superseded": 6, "forgotten": 2 },
  "usage": { "input_tokens": 182000, "output_tokens": 9100 },
  "budget": { "limit": 250000, "unit": "tokens", "exhausted": false },
  "written_by": { "kind": "consolidator", "id": "native" },
  "error": ""
}
```

- `status` is `queued`, `running`, `completed`, `stopped` (the budget ran out; what was done stays
  done and the next run resumes after `read.through`) or `failed`.
- Every record a run writes carries the run's `written_by`, so a reader can tell what a person or
  an agent stated from what consolidation concluded.
- `revert` appends: each record the run superseded or forgot becomes current again as a new
  version, and each record it created is forgotten. History keeps both the run and its reversal.
- A provider declares `consolidate` as `runs` (this section), `trigger` (it can be started and
  nothing more is reported), or `false`.

## 10. Providers

### 10.1 The contract

A provider implements the operations of [§5](#5-operations) and [§6](#6-recall) for the memories
bound to it. Everything above the provider, the tree, the grants, the cutoff, references across
memories, belongs to the server and is the same whichever provider keeps the records.

A server keeps no memory of its own: a deployment has memories once it is connected to a provider,
with a credential that belongs to whoever connected it and is held as every other credential is
([Security](security.md)). How a server is connected to a provider is the server's own surface.

How a provider derives memory is not visible here. A provider that runs an agent of its own to
decide what to keep is a provider like any other and declares `derivation: agent`.

### 10.2 The capability document

```http
GET /v1/memories/providers
```

```json
{ "data": [ {
  "id": "example",
  "isolation": "container",
  "derivation": "background",
  "observe": { "keeps_episodes": true, "answers": "records" },
  "recall": { "signals": ["query", "text", "filters"], "abstain": true, "max_depth": 3 },
  "history": { "content": "versions", "structure": "versions" },
  "revise": "native", "forget": "native", "erase": { "unreachable": "reported" },
  "prime": true, "consolidate": "runs",
  "queries": { "named": true, "free": { "languages": ["cypher"], "write": false } },
  "types": true, "files": true
} ] }
```

- **`isolation`** is `container` or `enforced_filter` ([§3.3](#33-enforcement)); **`derivation`** is
  when the provider turns episodes into records: `write_time`, `background`, `agent`, or `none`.
- **Emulation is declared.** An operation the provider lacks and the adapter supplies itself is
  reported as `emulated`, never as `native`.
- **A gap is declared.** A provider without full-text reports `signals` without `text`, and a
  request that names it is answered with `degraded`.

### 10.3 What an adapter owes

An adapter maps this chapter onto one provider's own interface. The capability document is where
the differences are said, and three rules keep it honest:

- A memory is one unit the provider can keep apart from every other. Where the provider has no
  such unit, the adapter adds the memory's identity to every read and write itself and checks it
  on every record fetched by id, and declares `enforced_filter`.
- What the provider cannot do is answered as [§12](#12-errors) says (`memory_unsupported`) or, for
  part of a request, in `degraded`. It is never approximated in silence.
- `erase` reports honestly. A provider that still serves a removed record's history, or whose
  derived copies cannot be reached, is reported in `unreachable` for every id it applies to.

## 11. Discovery

```json
{ "capabilities": { "memories": true } }
```

A server that reports `memories: true` implements [§2](#2-the-memory-object) to [§6.3](#63-the-response)
and [§9](#9-attaching-memories-to-a-harness). Named and free queries, types, files, snapshots, consolidation runs and erase are
reported per provider ([§10.2](#102-the-capability-document)). A server that does not implement the
chapter reports `false` or omits it and answers its endpoints with `404`.

## 12. Errors

| Code | Status | When |
|---|---|---|
| `memory_not_found` | 404 | No such memory, or one the caller may not see |
| `memory_forbidden` | 403 | The caller sees the memory and lacks the privilege the operation needs |
| `memory_record_not_found` | 404 | No such record in this memory, including a record of another memory asked for through this one |
| `memories_not_attached` | 404 | The harness has no memories attached |
| `memory_invalid` | 422 | A parent that would make a cycle; a default on two entries; a query whose params do not match |
| `memory_unsupported` | 422 | An operation the memory's provider does not implement at all (a partial answer is `degraded`, not this) |
| `memory_busy` | 409 | A move or a delete while a consolidation runs |
| `memory_unavailable` | 502 or 503 | The provider did not answer, or is not connected |

## 13. Security

- **What a memory returns is untrusted.** A record written in one session is read in another, by
  another agent, for another person. A server MUST present recalled content to the agent as data,
  fenced from instructions, and MUST carry `written_by` with it.
- **The agent chooses its path, never its reach.** An agent may walk up and down the tree from the
  memories its harness attaches. What it can reach is every memory the harness holds a privilege
  on, no more, checked by the server on every call. A harness that should see one branch and
  nothing above it is granted that branch and nothing above it.
- **Provenance is stamped, not supplied.** `written_by` and `written_at` come from the authenticated
  caller and the server's clock.
- **Unknown is indistinguishable from forbidden** on reads of memories and of reference targets.
- **A provider's credential is the server's**, held as every other credential is
  ([Security](security.md)); an agent never holds it.
- **Erase is a person's act.** It is not a tool.

## 14. Conformance

The suite's `memories` checks (ME-01 onward) run against a server that reports the capability and
has a provider connected, and drive this chapter through the public surface on that provider: the
tree and its listing, a stated record and its stamped writer, recall on one memory with the parent
and children it names, each signal against the provider's own capability document (a signal the
provider lacks must be reported in `degraded`, never ignored), revision and history, a record's id
refused through a memory it is not in, forgetting and erasing, moving and deleting. The suite runs
with one credential, so what one principal may not read of another's is not yet checked by it.

An interface that passes says nothing about whether a memory is any good. That is a separate
measurement, outside this suite: one harness and one model asking the same long-conversation
questions of each provider through this chapter's operations. A published result of that kind
SHOULD report the questions a memory ought to decline alongside the ones it ought to answer, and
what each answer cost.
