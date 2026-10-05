# Changelog

All notable changes to the Unified Harness Protocol.

## 2026-10-04 (patched the same day)

Additive to `2026-09-28`: every request and object valid under the previous version is valid here.

**Patch of 2026-10-04, same version.** A record's `content` is an ordered list of parts, always, on
every read ([Memories §4.3](versions/2026-10-04/memories.md#43-content)). The chapter as first
published that morning said `content` was text or one file reference, which could not hold a
picture beside what it shows, or a conversation turn with a file in it. Two kinds of part are
defined, `text` and `file`; a modality is a media type of a file part, not a kind of part, so a new
one needs no change here, and any other kind is `x.`-prefixed and carried unchanged. A file part
may carry the words that stand for it (`text`, with `text_source`), which is what recall by words
finds; a part may carry the `role` that said it, so a turn is observed in this same shape. A string
remains shorthand for one text part on a write. A file part's bytes are read at
`GET /v1/memories/{id}/records/{rid}/content/{index}` (was `/content`). A provider's capability
document says what it keeps in `content` (`media`, `bytes`, `describes`), replacing the `files`
flag, and a write of a media type the provider does not keep is refused with `memory_unsupported`,
never stored without its file. Schema: `MemoryContentPart`; `MemoryRecord.content` is an array.
Suite `2026.10.4.post1`: ME-02 expects the list, ME-09 exercises parts, order, refusals, and a file
part kept with its description and read back byte for byte, or refused, as the provider declares.
No implementation had shipped against the morning's text.

**Second patch of 2026-10-04, same version.** A memory's `id` is opaque. The schema had required
the `hmem_` prefix, which a server whose memories are a tree it already keeps (its own workspaces,
its own folders) could meet only with a second id space and a lookup between the two. `hmem_`
remains the prefix of a server that mints its own ids. Schema: the pattern is gone from `Memory.id`,
the path parameter and a harness's entry. Suite `2026.10.4.post2`: ME-01 no longer asserts the prefix.

**Third patch of 2026-10-04, same version.** `recall` searches the memory **and everything below it
the caller may read**; the morning's text had it act on one memory. A search is how a caller finds
where something is kept, so each result now carries `memory` (`id`, `name`): the place to walk
from. It never searches an ancestor. `depth` narrows it (`0` is the memory alone; it used to widen,
from a default of one memory). A server MAY cap the memories one question covers and says so in
`degraded`. `list`, `get`, `history` and the queries still act on one memory. The provider
capability `recall.max_depth` is gone: the subtree is the server's to compose. Schema:
`MemoryRecall.results[].memory` is required. Suite `2026.10.4.post3`: ME-03 rewritten.

- **Memories** ([Memories](versions/2026-10-04/memories.md)), the Harness Memories sub-protocol,
  optional at every class behind the `memories` capability. A memory is a named node in a tree:
  it holds records and may have child memories. A grant gives a principal privileges (`read`,
  `write`, `create`, `delete`) on a node and the node's descendants inherit it, up to a
  `restricted` node; what a caller may not read is answered exactly as what does not exist.
- Records are written two ways (`observe`: raw episodes, the provider decides what to derive, and
  may answer `202` with a job; `remember`: one record as stated) and removed two ways (`forget`:
  closed, trace kept; `erase`: content gone, with a list of what could not be reached). A change
  appends a version; `history`, `as_of` and named snapshots read the past.
- `recall` acts on one memory, by meaning, words and fields, and answers with the parent and
  children the caller may read, so an agent walks the tree itself, up or down. What a provider did
  not do is said in `degraded`; `abstain` says that nothing returned answers the question. Named
  queries, and free queries where a provider offers them, run in the provider's own language,
  confined to what the caller may read by a means the statement cannot undo.
- A server keeps no memory of its own: records are kept by a **provider** the server is connected
  to, behind one contract, and each provider says what it does in a capability document
  (`GET /v1/memories/providers`): isolation, derivation, signals, history, erase, queries, types.
- A harness is attached to memories at `PUT /v1/harnesses/{id}/memories`; attaching is granting.
  A task names one more in `metadata.memory`. A session reaches memory at four moments: priming,
  the agent's tools, observation after a turn, and consolidation, whose runs are visible, bounded
  and reversible.
- Extension record types carry their own schema and operations, for resources that are more than text.
- New objects in the schema: `Memory`, `MemoryRecord`, `MemoryRecall`, `MemoryGrant`,
  `MemoryProvider`, `MemoryConsolidation` and their requests; 23 paths under `/v1/memories` and
  `/v1/harnesses/{id}/memories`. New error codes: `memory_not_found`, `memory_forbidden`,
  `memory_record_not_found`, `memories_not_attached`, `memory_invalid`, `memory_unsupported`,
  `memory_busy`, `memory_unavailable`.
- Conformance suite `2026.10.4`: ME-01 to ME-08 drive the tree, records, recall and the provider's
  capability document on a server that reports the capability and has a provider connected; a
  server without the capability skips them. They pass, 8 of 8, on a build of the reference server
  with a hosted memory service as the provider. The suite runs with one credential, so isolation
  between principals is not yet checked by it.

## 2026-09-28 (patched 2026-09-29)

Additive to `2026-09-12`: every request and object valid under the previous version is valid here.

**Patch of 2026-09-29, same version.** The task-side reference to an environment is
`metadata.environment`, not a top-level request field: the task surface is a Responses request
and `metadata` is its extension point, where `harness_id` already travels
([Tasks §1.2](versions/2026-09-28/tasks.md#12-selecting-the-harness),
[Environments §5](versions/2026-09-28/environments.md#5-attaching-an-environment)). The response
reports `metadata.environment` beside `session_id`. The harness and session objects keep
`environment` as an ordinary field. The published chapter had carried the field at the top level
for one day; the schema, the conformance suite (`2026.9.28.post1`: EN-05 sends it in `metadata`,
EN-07 asserts the response echo; `post2`: EN-02 compares the returned bytes, which `post1` could not
read) and the reference server (0.26.7) changed together. The reference server passes the full
class, 84 of 84, on `post2`.

**Patch of 2026-09-29, second, same version.** A build's record says which step is running
(`stage`) and carries its log while it runs, and a server MUST write it as steps end, so a client
can show progress ([Environments §4](versions/2026-09-28/environments.md#4-builds-and-versions)).
An optional `GET /v1/environments/packages/check` answers what the manager's registry says about a
spec before any build (`EnvironmentPackageCheck`), so a client can refuse a typo where it is
typed. The environment's `status` is `building` while a build runs, whichever version is active;
a task keeps reading the active version meanwhile. Suite `2026.9.28.post3`: EN-09 exercises the
check on a server that offers it; reference server 0.26.10.

- **Environments** ([Environments](versions/2026-09-28/environments.md)), the Environments
  sub-protocol, optional at every class behind the `environments` capability. An environment is a
  project's files and installed dependencies, built once and mounted read-only at a fixed path in
  every session that names it, beside the session's own writable working directory. The chapter
  defines the object (`henv_`), files by path and whole-project import, builds and versions with
  an active pointer and rollback, the `environment` field on the harness object and
  `metadata.environment` on a task,
  what a session sees (the mount, the variables, the instruction, the record), and the errors.
- The session object carries `environment` ([Sessions §3](versions/2026-09-28/sessions.md#3-inspecting-a-session)).
- New error codes: `environment_not_found`, `environment_not_ready`, `environment_busy`,
  `environment_exists`, `environment_invalid`, `environment_unavailable`.
- Conformance suite `2026.9.28`: checks EN-01 to EN-08 (EN-07 runs one task that reads the
  environment and tries to write it), skipped on a server without the capability.

## Conformance suite 2026.9.12.post4 (2026-09-27)

- The public fixture answers at `https://uhp-fixture.harnessrouter.ai/mcp`, the suite's new default;
  post3 pointed at the container's own address.

## Conformance suite 2026.9.12.post3 (2026-09-27)

The protocol is unchanged; the suite that measures it is.

- The plugin checks point a plugin at a server that resolves and answers. A host may refuse an
  MCP server it cannot reach at configuration time and record that in `skipped`; with the
  unresolvable placeholder the checks used before, such a host failed P-02, P-04, P-06 and P-07
  for refusing the placeholder rather than for anything about plugins (the hosted HarnessRouter,
  2026-09-27). The suite ships the server (`uhp-conformance-fixture`, `pip install
  "uhp-conformance[fixture]"`), defaults to a public copy of it, and takes `--plugin-mcp-url`
  for a copy the host under test can reach.
- **P-11**, new: a plugin's MCP server answers the agent's tool call. The agent is asked to call
  the fixture's tool with a nonce and the fixture's answer, a function of the nonce, must come
  back. It is the only plugin check that runs a task, and the only one that shows an agent
  reaching a plugin's server rather than a server deriving and refusing correctly.
- Measured implementations are re-measured under this suite before their badges are shown again.

## 2026-09-12

Additive to `2026-08-11`: every request and object valid under the previous version is valid
here, and a client written against it keeps working against a server that serves this one. The
previous version stays published at its own address and a server SHOULD keep serving it.

### Added

- **Plugins** ([Plugins](versions/2026-09-12/plugins.md)), the Harness Plugins sub-protocol. A
  plugin is an [Agent Plugins](https://agent-plugins.org/specification) 1.0.0 package, carried as
  files and installed into a harness through a new `plugins` array on the harness object. The
  server derives `manifest`, `mcpServers`, `skills` and `skipped` from the package on every write;
  the package's servers and skills join the harness's own for every turn. UHP defines no package
  format of its own: as Agent Plugins wraps Agent Skills by saying where a skill lives and deferring
  the skill's format, this chapter wraps Agent Plugins by saying how a package travels, binds and
  runs, and defers the package's contents.

- **The composition rule** ([Plugins §4](versions/2026-09-12/plugins.md#4-composition-what-the-agent-gets)).
  A harness's own `mcpServers` and `skills` keep exactly the meaning they had: what a client wrote
  there, never a plugin's components copied in. This is what makes the version additive. A harness
  configured before this version is byte-for-byte a valid harness now, with `plugins` empty, and a
  client that reads a harness and writes it back cannot install a plugin's servers twice.
  Component names are unique within a harness across the direct lists and every enabled plugin;
  a collision is refused at configuration time with `plugin_conflict` rather than resolved
  silently at run time.

- **Export** ([Plugins §5](versions/2026-09-12/plugins.md#5-exporting-a-harness-as-a-plugin)):
  `GET /v1/harnesses/{id}/plugin` returns the harness's own tools and skills as an Agent Plugins
  package, credentials omitted and each omission recorded, that installs into another harness or
  any other Agent Plugins client unchanged. The direct fields were always the contents of a plugin
  without a name; this makes that an operation.

- **`stdio` MCP servers, inside plugins** ([Plugins §2.2](versions/2026-09-12/plugins.md#22-what-the-server-derives)):
  a plugin's `mcp.json` may declare a process (`command`, `args`, `env`, `cwd`), reported on the
  plugin as a `PluginMcpServer`. The harness's own `mcpServers` list stays remote-only and
  byte-for-byte what it was, because a process needs the root and data directory only a package
  provides. A server whose base cannot run a transport refuses the plugin with
  `unsupported_transport`.

- **Discovery**: the `plugins` capability, optional at every class, and `plugin_schemas`, the
  Agent Plugins manifest schemas the server installs
  ([Lifecycle §2](versions/2026-09-12/lifecycle.md#2-capability-discovery)).

- **Error codes**: `plugin_invalid` (422), `unsupported_plugin_schema` (422),
  `unsupported_transport` (422), `plugin_conflict` (409), `plugin_not_found` (404)
  ([Errors §3](versions/2026-09-12/errors.md#3-error-codes)).

- **Security §9, plugins are third-party code** ([Security](versions/2026-09-12/security.md#9-plugins-are-third-party-code)):
  stdio servers run inside the agent's sandbox and nowhere else, only the two placeholders are
  ever expanded, plugins are installed by whoever manages the harness and never per request.

- **Schema**: `Plugin`, `PluginManifest`, `PluginSkill`, `PluginSkipped`, `FileList`; the skill
  files endpoint, which the prose named and the OpenAPI document omitted, is now in both.

### Conformance

- **P-01 to P-10**, class Full, gated on the `plugins` capability: the schema list, package round
  trip and derivation, refusal of a package without a manifest, refusal of a name collision,
  survival of an unrelated edit, export that installs again without credentials, skipped
  components recorded, `enabled: false` preserved, refusal of an unsupported manifest schema,
  refusal of duplicate plugin names. Each is proven against a defect stub carrying one mistake at
  a time, the way the R-series is. That made the suite 74 checks.

- **X-09**, class Extended: a file uploaded through `POST /v1/files` is accepted and can be
  sent as task input by id ([Files §1.2](versions/2026-09-12/files.md#12-by-upload)). X-05 sends
  its file inline and never reaches the upload endpoint, so a server whose uploads all failed
  passed the chapter (HarnessRouter CE 0.17.3, #198). Proven against a defect stub: an upload
  that fails outright, one that answers without an id, and one that truncates each fail X-09
  alone while X-05 stays green. The suite is now 75 checks.

## 2026-08-11, additive clarifications

These were published as additive changes to `2026-08-11` before `2026-09-12` and are carried
into it unchanged.


### Clarified

- **Session deletion is named** ([Sessions §6](versions/2026-08-11/sessions.md#6-deleting)):
  `DELETE /v1/sessions/{id}` is the protocol's session delete, with the semantics the old path
  always had (transcript, trace and working folder go; the session stops counting toward any
  allowance; a later `GET` is `404`). `DELETE /v1/traces/{id}` stays as an alias a server MAY keep,
  which is what the reference implementation does with one handler behind both paths.

- **Session sharing is codified** ([Sessions §5](versions/2026-08-11/sessions.md#5-session-sharing)),
  closing the four gaps of [#44](https://github.com/HarnessRouter/harnessrouter/issues/44): the
  share object is schema'd (`SessionShare`: `id` and `url` required, `url` may be base-relative),
  `DELETE /v1/sessions/{id}/share` is the named revocation endpoint (other forms MAY be kept), a
  bodyless `POST` publishes, and revocation MUST reach every link minted. Sharing itself remains a
  MAY. These are the shapes the reference implementation already demonstrates and the R-series
  already measures; the suite now asserts them instead of probing for them.

- **Turn items have a shape** ([Sessions §3](versions/2026-08-11/sessions.md#3-inspecting-a-session)):
  each item of `GET /v1/sessions/{id}/turns` MUST carry `id` (the response id) and `status`, and
  SHOULD carry `user` / `assistant` / `tools` / `files`. Previously `additionalProperties: true`
  and nothing else, which held X-04 at "the endpoint answered 200".

### Conformance

- `R-01`/`R-02` validate the share object against the schema and FAIL (no longer skip) when it
  carries no `url`; `R-06` asserts the named `DELETE` revocation endpoint and FAILs (no longer
  skips) when it does not work; `X-04` validates every turn item. New defect stub mode:
  a server whose revocation exists only as a toggle now fails `R-06`.

- **`R-08`: a bodyless `POST` publishes.** The sentence was written into §5 above and left
  unenforced, named as a known gap rather than hidden. The rest of the R-series mints through a
  helper that retries a 400/422 with `{"enabled": true}` — the retry is what lets the series
  measure a toggle-dialect server at all, and it is also what let this sentence go untested: such
  a server passes `R-01`…`R-07` on a request §5 does not require anyone to accept, while refusing
  the one it does. `R-08` is the one check that does not retry. New defect stub mode,
  `bodyless_rejected`, is what the reference implementation was before this series existed; the
  matrix proves `R-08` is the only check that reddens on it. No specification or schema change:
  this enforces a sentence that is already written.


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
