# Memories

**Unified Harness Protocol, DRAFT 0.1 (2026-10-03). Not part of any published version.**

> Status: a working draft for discussion. Section 14 lists what is decided, what is proposed and
> not yet confirmed, and what is open. Nothing here is implemented.

A session's conversation ([Sessions](../versions/2026-09-28/sessions.md)) ends with the session, and
a harness's instructions are written once by its owner. What an agent learns between those two, the
facts about the people it works for, the decisions a team made, the procedure that worked last time,
has had no place in the protocol: every product that wanted it bolted a memory vendor onto one
harness, with that vendor's API, its own idea of scope, and no way to say who may read what.

A **memory** is that place as one object: a named node in a tree, holding records, with access
granted per node and inherited downward. A harness names the memories it works with; the server
decides, from the harness's grants, what it may read and where it may write.

This chapter is the Harness Memories sub-protocol. It is optional: a server advertises it with the
`memories` capability, and a server that does not implement it is conformant at every class.

## 1. What a memory is

UHP does not define how memory is derived. Extraction, ranking, consolidation and storage belong to
the system behind the memory, the **provider**: a vendor's memory service, a graph database, a
folder of files. This chapter defines the three things a harness and a provider must agree on, and
nothing else:

```
the provider         its own store and its own intelligence     how memory is derived and kept
UHP Memories         this chapter                               what a memory is, who may reach it,
                                                                and when a harness calls it
MCP                  the tools an agent holds                   how the agent calls it during a turn
```

- **The object.** A memory is a node in a tree. It holds **records** and may have child memories.
- **The access.** A grant gives a principal privileges on a node; the node's descendants inherit it.
- **The seam.** A harness reaches memory at four moments of a session's life ([§9](#91-what-a-session-does)),
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
  "provider": "native",
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
| `provider` | string | client | Which provider keeps this memory's records ([§10](#10-providers)). Set at creation; a server MAY refuse to change it |
| `privileges` | array | server | The caller's effective privileges on this node |
| `records`, `children` | object | server | Counts, for a caller deciding where to look |

```http
POST   /v1/memories                          create (name, description, parent_id, restricted, provider)
GET    /v1/memories?parent={id}              the direct children of a memory (or the roots), paginated
GET    /v1/memories/{id}                     one memory
PUT    /v1/memories/{id}                     rename; description; restricted; move (parent_id)
DELETE /v1/memories/{id}                     delete the memory, its records and its descendants
```

A listing is one level. A client that wants a subtree asks level by level, or passes
`ancestor={id}` for every descendant it may read. A server MUST NOT return a memory on which the
caller has no effective privilege, and MUST NOT reveal that one exists.

## 3. Access

### 3.1 Grants and inheritance

A **grant** gives one principal a set of privileges on one memory. A principal's effective
privileges on a memory are the union of its grants on that memory and on every ancestor. Access is
additive: there is no deny, and no grant means no access.

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

A record is one thing a memory holds.

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
  ([§9](#91-what-a-session-does)). It MAY answer `202` with a job the client can poll.
- **`remember`** writes the record the caller states, as stated. It is what an agent calls when it
  decides something is worth keeping.

A provider declares when its derivation runs: `write_time`, `background`, `agent`, or `none`
([§10.2](#102-the-capability-document)).

Every write accepts an `Idempotency-Key` ([Tasks](../versions/2026-09-28/tasks.md)).

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
  "language": "gremlin++",
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
POST /v1/memories/{id}/query        { "language": "gremlin++", "statement": "…", "params": { } }
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

Upload follows [Files](../versions/2026-09-28/files.md): the bytes are sent with `POST /v1/files` and the
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

```json
{ "memories": [
    { "memory_id": "hmem_0a1b…", "access": "read" },
    { "memory_id": "hmem_7c1e…", "access": "write", "default": true },
    { "memory_id": "hmem_user_{subject}", "access": "write" }
] }
```

- The server checks each entry against the harness's effective privileges when the harness is
  written. An entry the harness has no grant for is refused then, not at run time.
- `access` narrows; it never widens. `read` on a memory the harness may also write gives the agent
  read tools only, on that memory and on whatever it walks to from it.
- One entry MAY be marked `default`: where `observe` and an unaddressed `remember` go.
- An entry MAY name a memory by a template the server resolves per task from
  `metadata.memory` on the request ([Tasks](../versions/2026-09-28/tasks.md)), creating it under a
  parent the harness has `create` on. How a server maps a task to a node is its own convention.

### 9.1 What a session does

| Moment | Called by | What happens |
|---|---|---|
| **Prime** | server, at session start and after the conversation is compacted | The server reads what the provider marks as always-relevant in each attached memory and places it, with each memory's `name`, `description` and children, in the agent's instructions |
| **Tools** | agent, during a turn | `memory_list`, `memory_recall`, `memory_get`, `memory_remember`, `memory_revise`, `memory_forget`, plus one tool per named query and per type operation, and `memory_query` where the provider offers free queries. The attached memories are where the agent starts; from each it may walk to the parent and the children a response names, and on from there, as far as the harness's own privileges reach. The server checks every step |
| **Observe** | server, when a turn ends | The turn (what was asked, what was answered, which tools ran) is sent to the default memory as episodes. No model is involved on the server's side |
| **Consolidate** | server, on a schedule or when idle | The server asks the provider to do its background work. What that is belongs to the provider |

Priming is not repeated every turn. Instructions that change every turn defeat prompt caching, and
retrieval during a turn is what the tools are for.

A server MUST tell the person who attaches a memory whose provider is outside the server that every
turn will be sent to it.

## 10. Providers

### 10.1 The contract

A provider implements the operations of [§5](#5-operations) and [§6](#6-recall) for the memories
bound to it. Everything above the provider, the tree, the grants, the cutoff, references across
memories, belongs to the server and is the same whichever provider keeps the records.

How a provider derives memory is not visible here. A provider that runs an agent of its own to
decide what to keep is a provider like any other and declares `derivation: agent`.

### 10.2 The capability document

```http
GET /v1/memories/providers
```

```json
{ "data": [ {
  "id": "native",
  "isolation": "container",
  "derivation": "background",
  "recall": { "signals": ["query", "text", "filters"], "abstain": true, "max_depth": 3 },
  "history": { "content": "versions", "structure": "versions" },
  "revise": "native", "forget": "native", "erase": { "unreachable": "reported" },
  "prime": true, "consolidate": true,
  "queries": { "named": true, "free": { "languages": ["gremlin++"], "write": false } },
  "types": true, "files": true
} ] }
```

- **Emulation is declared.** An operation the provider lacks and the adapter supplies itself is
  reported as `emulated`, never as `native`.
- **A gap is declared.** A provider without full-text reports `signals` without `text`, and a
  request that names it is answered with `degraded`.

### 10.3 Mapping the first providers

| | Kept as | `observe` | `remember` | `recall` signals | History | Isolation |
|---|---|---|---|---|---|---|
| ContextualGraph (reference) | A graph per memory; documents and files beside it | Episode nodes; background consolidation | Fact with subject, attribute, value | query, text, filters | versions | container |
| mem0 | Extracted facts | `add(messages)` | `add(infer=false)` | query, filters | native per record | filter by its scope ids |
| Zep | Temporal graph | thread messages, `graph.add` | `graph.add` text or JSON | query, text, filters | bi-temporal edges | container (a graph) |
| Letta | Files and blocks kept by its own agent | messages to its agent | file or passage write | query | commit log | container (an agent or a shared block) |
| Cognee | Document-derived graph | `remember` / `add` + `cognify` | `add` | query, text | emulated | container (a dataset) |
| Files (built in) | Markdown files in a folder | appended transcript | a file | text | versions | container (a folder) |

This table is the plan, not a measurement. Each row is replaced by what conformance finds.

## 11. Discovery

```json
{ "capabilities": { "memories": true } }
```

A server that reports `memories: true` implements [§2](#2-the-memory-object) to [§6.3](#63-the-response)
and [§9](#9-attaching-memories-to-a-harness). Named and free queries, types, files, snapshots and erase are
reported per provider ([§10.2](#102-the-capability-document)). A server that does not implement the
chapter reports `false` or omits it and answers its endpoints with `404`.

## 12. Errors

| Code | Status | When |
|---|---|---|
| `memory_not_found` | 404 | No such memory, or one the caller may not see |
| `memory_forbidden` | 403 | The caller sees the memory and lacks the privilege the operation needs |
| `memory_record_not_found` | 404 | No such record in this memory |
| `memory_invalid` | 422 | A parent that would make a cycle; a default on two entries; a query whose params do not match |
| `memory_unsupported` | 422 | An operation the memory's provider does not implement at all (a partial answer is `degraded`, not this) |
| `memory_busy` | 409 | A move or a delete while a consolidation runs |
| `memory_unavailable` | 502 or 503 | The provider did not answer |

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
  ([Security](../versions/2026-09-28/security.md)); an agent never holds it.
- **Erase is a person's act.** It is not a tool.

## 14. Status of this draft

**Decided**

1. The whole sub-protocol lives in UHP as one chapter, named as Plugins and Environments are.
2. A memory is a node in a generic tree; levels have no fixed meaning. Access is granted per node
   and inherited downward, with a restricted cutoff: the Spaces model.
3. A node exists only where access differs. A session has no node of its own.
4. Reads act on one node. The agent walks the tree itself, up to a parent or down to a child,
   within what its harness may read. Subtree reads are opt-in.
5. `observe` is on by default for an attached memory.
6. A provider's internals are invisible; Letta is a provider like any other.
7. Other resources (calendar, tasks, tables) enter as extension types with operations; optional.
8. Recall has fixed signals (meaning, words, fields), named queries in the provider's language, and,
   where a provider offers them, free queries an agent writes itself. The provider confines a free
   query to what the caller may read by a means the statement cannot undo.
9. References cross the tree freely and resolve with the reader's privileges.
10. On the hosted service, a memory is a Space: the same vertex, tree and grants, with no migration.
11. Isolation is "enforced by the server": a container per memory and a condition the server adds
    to every operation are both conformant ([§3.3](#33-enforcement)).

**Accepted for now, to revisit**

- History is append-and-close for content and structure alike; file bytes are kept by content
  address, a snapshot is a named instant, and no git repository is involved ([§5.3](#53-nothing-is-overwritten)).

**Open**

- How `metadata.memory` names the per-task node, and whether the protocol should say more than
  "the server's convention" ([§9](#9-attaching-memories-to-a-harness)).
- Whether `prime` needs a budget the client sets, and how its size is reported.
- Whether consolidation deserves a visible object (runs, their cost, what they changed) or stays
  entirely inside the provider.
- The second round of providers (Hindsight, Mastra Observational Memory, OMEGA, Supermemory, the
  cloud vendors' services): each needs its own reading of first-hand documentation before a row is
  written for it.
- Export and import between providers, and alignment with an existing archive format.
- Conformance: the fixture, and the shared recall evaluation (LoCoMo with all five categories,
  LongMemEval with abstention broken out) run on one harness across providers.
