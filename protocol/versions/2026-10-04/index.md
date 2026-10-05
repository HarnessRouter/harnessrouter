# Unified Harness Protocol — specification `2026-10-04`

An open standard for running complete agent harnesses as shared infrastructure.

This is the normative specification. For an introduction to what UHP is and why it exists, start at
the [protocol README](../../README.md).

## Chapters

| # | Chapter | Defines |
|---|---|---|
| 1 | [Architecture](architecture.md) | Roles, conformance classes, object model, transport, authentication, design principles |
| 2 | [Lifecycle](lifecycle.md) | Version negotiation, capability discovery, task and session states, concurrency |
| 3 | [Harnesses](harnesses.md) | Discovering, selecting, configuring and managing harnesses; models and availability |
| 4 | [Plugins](plugins.md) | Packages of tools and skills, in the Agent Plugins format, installed into a harness; composition; export |
| 5 | [Environments](environments.md) | A project's files and installed dependencies, built once, read-only in every session that names it; builds, versions, attachment |
| 6 | [Memories](memories.md) | Memory that outlasts a session: a tree of memories with access granted per node, records, recall, providers, and when a harness reaches them |
| 7 | [Tasks](tasks.md) | Running work, the response object, model substitution, idempotency |
| 8 | [Streaming](streaming.md) | The event vocabulary, ordering guarantees, reconnection |
| 9 | [Sessions](sessions.md) | Continuing, inspecting, cancelling, sharing, deleting |
| 10 | [Files](files.md) | File input, artifacts, download, retention and scope |
| 11 | [Errors](errors.md) | The error envelope, codes, retry rules, timeouts |
| 12 | [Security](security.md) | Credentials, object scope, artifacts, injection, exhaustion, plugins, environments, memories, error hygiene |
| 13 | [Schema](schema.md) | Machine-readable definitions and how to generate from them |

## Endpoint summary

| Method | Path | Class | Chapter |
|---|---|---|---|
| `GET` | `/v1/uhp` | Core | [Lifecycle](lifecycle.md) |
| `GET` | `/v1/harnesses` | Core | [Harnesses](harnesses.md) |
| `GET` | `/v1/harnesses/{id}` | Core | [Harnesses](harnesses.md) |
| `GET` | `/v1/models` | Core | [Harnesses](harnesses.md) |
| `GET` | `/v1/harnesses/{id}/models` | Core | [Harnesses](harnesses.md) |
| `POST` | `/v1/responses` | Core | [Tasks](tasks.md) |
| `GET` | `/v1/responses/{id}` | Core | [Tasks](tasks.md) |
| `GET` | `/v1/responses/{id}/input_items` | Core | [Tasks](tasks.md) |
| `POST` | `/v1/responses/{id}/cancel` | Core | [Sessions](sessions.md) |
| `DELETE` | `/v1/responses/{id}` | Core | [Tasks](tasks.md) |
| `POST` | `/v1/sessions/{id}/cancel` | Core | [Sessions](sessions.md) |
| `GET` | `/v1/sessions` | Extended | [Sessions](sessions.md) |
| `GET` | `/v1/sessions/{id}` | Extended | [Sessions](sessions.md) |
| `GET` | `/v1/sessions/{id}/turns` | Extended | [Sessions](sessions.md) |
| `POST` | `/v1/files` | Extended | [Files](files.md) |
| `GET` | `/v1/sessions/{id}/files` | Extended | [Files](files.md) |
| `GET` | `/v1/sessions/{id}/files/archive` | Extended | [Files](files.md) |
| `GET` | `/v1/containers/{cid}/files/{fid}/content` | Extended | [Files](files.md) |
| `GET` | `/v1/containers/{cid}/files/{fid}/pdf` | Extended | [Files](files.md) |
| `POST` | `/v1/harnesses` | Full | [Harnesses](harnesses.md) |
| `PUT` | `/v1/harnesses/{id}` | Full | [Harnesses](harnesses.md) |
| `DELETE` | `/v1/harnesses/{id}` | Full | [Harnesses](harnesses.md) |
| `GET` | `/v1/harnesses/{id}/skills/{name}/files` | Full | [Harnesses](harnesses.md) |
| `GET` | `/v1/harnesses/{id}/plugins/{name}/files` | Full, `plugins` | [Plugins](plugins.md) |
| `GET` | `/v1/harnesses/{id}/plugin` | Full, `plugins` | [Plugins](plugins.md) |
| `POST` | `/v1/sessions/{id}/share` | Full | [Sessions](sessions.md) |
| `GET` | `/v1/sessions/{id}/share` | Full | [Sessions](sessions.md) |
| `DELETE` | `/v1/sessions/{id}` | Full | [Sessions](sessions.md) |
| `DELETE` | `/v1/traces/{id}` | Full | [Sessions](sessions.md) (older path, same operation) |
| `GET` | `/v1/environments` | Full, capability `environments` | [Environments](environments.md) |
| `POST` | `/v1/environments` | Full, capability `environments` | [Environments](environments.md) |
| `GET` `PUT` `DELETE` | `/v1/environments/{id}` | Full, capability `environments` | [Environments](environments.md) |
| `GET` | `/v1/environments/{id}/files` | Full, capability `environments` | [Environments](environments.md) |
| `GET` `PUT` `DELETE` | `/v1/environments/{id}/files/{path}` | Full, capability `environments` | [Environments](environments.md) |
| `POST` | `/v1/environments/{id}/directories` | Full, capability `environments` | [Environments](environments.md) |
| `POST` | `/v1/environments/{id}/import` | Full, capability `environments` | [Environments](environments.md) |
| `GET` | `/v1/environments/runtimes` | Full, capability `environments` | [Environments](environments.md) |
| `POST` | `/v1/environments/{id}/build` | Full, capability `environments` | [Environments](environments.md) |
| `GET` | `/v1/environments/{id}/builds/{version}` | Full, capability `environments` | [Environments](environments.md) |
| `GET` | `/v1/environments/{id}/versions` | Full, capability `environments` | [Environments](environments.md) |
| `POST` | `/v1/environments/{id}/versions/{version}/activate` | Full, capability `environments` | [Environments](environments.md) |
| `GET` | `/v1/environments/{id}/harnesses` | Full, capability `environments` | [Environments](environments.md) |
| `GET` `POST` | `/v1/memories` | Full, capability `memories` | [Memories](memories.md) |
| `GET` `PUT` `DELETE` | `/v1/memories/{id}` | Full, capability `memories` | [Memories](memories.md) |
| `GET` `POST` | `/v1/memories/{id}/grants` | Full, capability `memories` | [Memories](memories.md) |
| `DELETE` | `/v1/memories/{id}/grants/{grant_id}` | Full, capability `memories` | [Memories](memories.md) |
| `POST` | `/v1/memories/{id}/observe` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/{id}/jobs/{job}` | Full, capability `memories` | [Memories](memories.md) |
| `GET` `POST` | `/v1/memories/{id}/records` | Full, capability `memories` | [Memories](memories.md) |
| `GET` `PATCH` `DELETE` | `/v1/memories/{id}/records/{rid}` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/{id}/records/{rid}/history` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/{id}/records/{rid}/content/{index}` | Full, capability `memories` | [Memories](memories.md) |
| `POST` | `/v1/memories/{id}/records/{rid}/operations/{name}` | Full, capability `memories` | [Memories](memories.md) |
| `POST` | `/v1/memories/{id}/recall` | Full, capability `memories` | [Memories](memories.md) |
| `POST` | `/v1/memories/{id}/graph` | Full, capability `memories` | [Memories](memories.md) |
| `POST` | `/v1/memories/{id}/erase` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/{id}/queries` | Full, capability `memories` | [Memories](memories.md) |
| `PUT` `POST` | `/v1/memories/{id}/queries/{name}` | Full, capability `memories` | [Memories](memories.md) |
| `POST` | `/v1/memories/{id}/query` | Full, capability `memories` | [Memories](memories.md) |
| `GET` `POST` | `/v1/memories/{id}/snapshots` | Full, capability `memories` | [Memories](memories.md) |
| `GET` `POST` | `/v1/memories/{id}/consolidations` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/{id}/consolidations/{run}` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/{id}/consolidations/{run}/changes` | Full, capability `memories` | [Memories](memories.md) |
| `POST` | `/v1/memories/{id}/consolidations/{run}/revert` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/providers` | Full, capability `memories` | [Memories](memories.md) |
| `GET` | `/v1/memories/types` | Full, capability `memories` | [Memories](memories.md) |
| `GET` `PUT` | `/v1/harnesses/{id}/memories` | Full, capability `memories` | [Memories](memories.md) |

The `plugins` column entries are served only by a server whose discovery document reports the
`plugins` capability; the capability is optional at every class.

The `memories` entries are served only by a server that reports the `memories` capability, which is
optional at every class as well; within it, named and free queries, types, the media a record may carry, snapshots,
consolidation runs and erase are declared per provider ([Memories §10.2](memories.md#102-the-capability-document)).

## What changed in this version

This version is additive to `2026-08-11`: every request and object that was valid then is valid
now, and a client written against the previous version keeps working against a server that serves
this one. It adds the [Plugins](plugins.md) chapter, with `stdio` MCP servers inside plugins, the
`plugins` capability, and five error codes. A server may serve both versions from one code path. The [changelog](../../CHANGELOG.md) has the full list.

## Conformance

A server is conformant at a class when it passes the [conformance suite](../../conformance/) at that
class. Nothing else is a conformance claim — not a self-assessment, not an implementation of the
endpoints, not passing "most" tests.

```bash
pip install -e protocol/conformance
uhp-conformance --base-url https://your-server --api-key "$KEY" --class extended
```

The suite is part of this specification. If the suite and this prose disagree, that is a bug in one
of them and MUST be resolved by changing whichever is wrong — never by leaving them inconsistent.

## Conventions

- MUST / SHOULD / MAY are used as defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and
  [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174).
- JSON examples are illustrative; the [schema](../../schema/) is authoritative for structure.
- Field names are `snake_case` on the task surface (inherited from the Responses-compatible shape)
  and `camelCase` on the harness object. This inconsistency is real, is called out here rather than
  hidden, and is retained because changing either would break existing clients for cosmetic gain.
  A future major version SHOULD unify them.
