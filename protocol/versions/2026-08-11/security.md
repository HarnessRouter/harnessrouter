# Security considerations

**Unified Harness Protocol, version `2026-08-11`**

A UHP server runs an agent that executes tools, writes files, and holds a provider credential, on
behalf of a caller it has never met. That is a larger blast radius than a model endpoint, and the
requirements here are collected in one place so an implementer can check them off rather than
rediscover them.

Requirements stated in other chapters are repeated here rather than only cross-referenced. A
security rule a reader has to assemble from six chapters is a rule that gets missed.

## 1. Credentials

- A server MUST authenticate every endpoint except `GET /v1/uhp`
  ([Lifecycle §2](lifecycle.md)).
- A server MUST NOT distinguish "no such token" from "token not permitted here" in a way that lets a
  caller enumerate valid tokens.
- A server MUST NOT echo a credential — the caller's or a provider's — in any response body, error
  message, event, log line, or artifact.
- A server SHOULD support revoking a credential, and revocation MUST take effect for new requests
  immediately.

### 1.1 Provider credentials

The credential a server uses to reach a model provider is the most valuable secret in the system,
and the agent's own sandbox is the least trustworthy place in it: an agent can be induced to read
its environment and print it.

- A server SHOULD NOT place a provider credential where the agent's tools can read it.
- A server that must give a harness a credential SHOULD issue a short-lived, single-session one, and
  MUST be able to revoke it independently of the underlying key.
- A server MUST NOT accept a caller-supplied upstream URL for a brokered request without validating
  it against a configured allow-list. An unvalidated upstream turns the server into an SSRF proxy
  with its own credential attached.

## 2. Object scope

- Every object — harness, response, session, container, file — MUST be scoped to the principal that
  created it.
- A request for an object outside the caller's scope MUST return `404`, never `403`. `403` confirms
  the id exists, which is exactly what an enumerating attacker wants
  ([Architecture §5](architecture.md)).
- Scope MUST be enforced on every operation, not only on read. Cancel, delete, continue and download
  are all object access.

> The conformance suite cannot fully verify this with one credential. An implementer SHOULD run the
> equivalent check with two principals: create an object as A, then attempt every operation on it as
> B, and confirm each returns `404`.

## 3. Artifacts are attacker-influenced content

An agent can be persuaded to write a file with chosen content and a chosen name. Everything that
serves artifacts MUST treat them as hostile.

- Artifact downloads MUST be served with `X-Content-Type-Options: nosniff`. Without it, an artifact
  named `x.html` becomes stored XSS against the client's own origin
  ([Files §3](files.md)).
- Artifacts SHOULD be served from a different origin than the console or application UI, so that a
  successful injection cannot reach first-party cookies or storage.
- A server MUST NOT allow a `container_id` / `file_id` pair to address anything outside its
  container. Path traversal through artifact ids is the most likely serious vulnerability in a UHP
  implementation; the conformance suite probes for it (X-08), and passing that probe is a floor, not
  proof.
- A server SHOULD cap artifact size and count per session.

## 4. Prompt injection is in scope for the client

A harness that reads a web page, a repository, or an uploaded file may encounter instructions
addressed to it. UHP cannot prevent this, and a specification that pretended otherwise would be
worse than one that says so plainly.

What the protocol does provide, and a client SHOULD use:

- **`disabledTools`** on a configured harness — the smallest tool set that can do the job is the
  smallest injection surface.
- **`max_step` and `timeout_seconds`** — a bounded task cannot be induced into an unbounded one.
- **Separate harnesses for separate trust levels.** A harness that reads untrusted input SHOULD NOT
  be the same configured harness that holds privileged tools or MCP servers.
- **The event stream.** Tool calls are visible as they happen; a client can surface or gate them.

A server MUST NOT claim that any of this makes an agent safe to point at untrusted input.

## 5. Resource exhaustion

- A server MUST bound task duration, and MUST report `incomplete` rather than `completed` when a
  budget stopped the work ([Lifecycle §3](lifecycle.md)).
- A server MUST refuse a second concurrent task in the same session (`session_busy`) — two agents in
  one working directory is not a defined state, and is also a cheap way to multiply cost.
- A server SHOULD rate-limit task creation per principal and SHOULD expose remaining budget through
  `rate_limit_error` responses rather than by failing opaquely.
- A server MUST bound upload size and reject with `file_too_large` rather than truncating. A silently
  truncated input produces a confident, wrong answer.

## 6. Data handling

- Session artifacts and transcripts MUST be unreachable after the session is deleted.
- A server SHOULD document its retention period. "Indefinite" is an answer; silence is not.
- Session sharing, where implemented, MUST be read-only and revocable, and MUST NOT expose
  credentials or another principal's data ([Sessions §5](sessions.md)).

## 7. Transport

- TLS MUST be used except on loopback.
- A server SHOULD send `Strict-Transport-Security`.
- A server serving any HTML MUST send `X-Frame-Options: DENY` or an equivalent
  `frame-ancestors 'none'` policy.

## 8. Error hygiene

- `error.message` MUST be safe to show a user: no credentials, internal hostnames, file paths, or
  stack traces ([Errors §1](errors.md)).
- A server SHOULD log the detail it withholds, with a correlation id it returns in `error.detail`,
  so an operator can diagnose what a caller cannot see.

## 9. Reporting a vulnerability

Vulnerabilities in the reference implementation or in this specification follow private disclosure,
not a public issue. See the repository's security policy. A specification bug that makes a secure
implementation impossible is treated as a vulnerability, not as a documentation defect.
