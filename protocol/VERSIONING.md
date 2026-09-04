# Versioning and compatibility

## The scheme

UHP versions are dates — `YYYY-MM-DD`, the day the version was published. `2026-08-11` is the
current version.

Dates were chosen over semantic versioning deliberately. SemVer's promise is that a major bump means
"expect breakage" and a minor bump means "safe" — a promise that is only as good as the discipline
of whoever assigns the numbers, and one that is routinely broken in practice. A date claims nothing
it cannot keep. It says when the version was published, it sorts, and it makes an implementation's
age obvious at a glance.

## What may change within a version

A published version is **immutable in structure**. Within a version, a server MAY:

- add optional request fields;
- add fields to response objects;
- add new event types;
- add new error codes with a vendor prefix;
- relax a constraint (accept input it previously rejected).

A server MUST NOT, within a version:

- remove or rename a field;
- change the type or meaning of a field;
- add a required request field;
- remove an event type or error code;
- tighten a constraint (reject input it previously accepted).

Anything in the second list requires a new version.

## Client rules

A conformant client MUST:

1. **Ignore unknown fields.** Not warn, not error — ignore.
2. **Ignore unknown event types.** Skip and continue reading the stream.
3. **Ignore unknown output item types.** Render what it understands.
4. **Treat unknown error codes as their `type`.** An unrecognised `code` with
   `type: "server_error"` is still retryable.

A client that follows these four rules keeps working across every additive change within a version,
which is the entire point of writing them down.

## Server rules

A server MUST:

1. Report the version it served in the `UHP-Version` response header.
2. Reject an unsupported requested version with `unsupported_protocol_version` rather than serving a
   different one.
3. Support at least one full version at a time, and SHOULD support the previous version for at least
   six months after a new one is published.

## Deprecation

A field or endpoint is deprecated by:

1. marking it deprecated in the specification and the OpenAPI document, with the reason and the
   replacement;
2. keeping it working for at least two published versions;
3. removing it no earlier than the second version after the announcement.

Nothing is removed without a working replacement having existed first.

## The current version's known compromises

Recorded here because a specification that hides its own rough edges cannot be trusted about the
smooth ones.

- **Mixed field casing.** The task surface is `snake_case`; the harness object is `camelCase`. Both
  are load-bearing in shipped clients. A future major version should unify them.
- **Session deletion also lives at `/v1/traces/{id}`.** The path predates the session vocabulary.
  The protocol now names `DELETE /v1/sessions/{id}` and keeps the old path as an alias rather than
  renaming it, because renaming would break existing clients for a cosmetic gain. A future major
  version may retire the old path through the process above.
