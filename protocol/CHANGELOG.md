# Changelog

All notable changes to the Unified Harness Protocol.

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

- **`stdio` MCP transport** ([Harnesses §4.1](versions/2026-09-12/harnesses.md#41-mcp-servers)):
  `command`, `args`, `env` and `cwd`, with the rules of the Agent Plugins `mcp.json` format, so a
  server declared in a plugin and one attached directly are the same object. `url` is required
  only for `http` and `sse`. A server whose base cannot run a transport refuses the configuration
  with `unsupported_transport`.

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
  a time, the way the R-series is. The suite is now 74 checks.

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
