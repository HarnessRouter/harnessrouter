# Sessions

**Unified Harness Protocol, version `2026-10-19`**

A session is what makes a second task cheaper than the first: the conversation is still there, and
so is the working directory. This chapter defines continuing a session, inspecting one, and stopping
work in one.

## 1. Continuing a session

Send the next task with `previous_response_id`:

```json
{
  "input": "Now add tests for the function you just wrote.",
  "previous_response_id": "resp_a1b2c3"
}
```

The server MUST:

- run the new task in the same session, with the same working directory and its files;
- give the harness the conversational context of the earlier tasks;
- use the same configured harness;
- report the same `metadata.session_id`.

`model` MAY differ between tasks in a session. A server MUST honour a per-task model change, because
switching to a cheaper model for a follow-up is a common and legitimate pattern.

If `previous_response_id` names an unknown response, the server MUST fail with `404` and
`code: "response_not_found"`. If the session it referred to has expired, `404` with
`code: "session_expired"` — a client can retry the first from scratch, and should not retry the
second.

A task chained on a response that ended on a question for the person
([Tasks §3.2](tasks.md#32-asking-the-person)) carries either the answer, as an `input_response`
item, or anything else, which passes the question over; the server says which happened.

> **Why chain on the response id rather than the session id?**
> Because the response id is what the client already has: it comes back from the task it just ran.
> Chaining on it also names an exact point in the conversation, which leaves room for a server to
> branch from an earlier response later without changing the request shape.

## 1.1. Branching from an earlier response

A server claiming conformance class **Full** MUST support an explicit branch; other servers MAY:

```json
{
  "input": "Try a different approach from here.",
  "previous_response_id": "resp_first",
  "branch": true
}
```

`branch` is a top-level request field, beside `previous_response_id`. With `true` and a
previous response, the server MUST create a **new** session from that response's committed
user files and the transcript up to and including it. The original session, its working files,
and its transcript MUST remain unchanged. A session hint does not replace the branch point.
Without `branch: true`, continuation is unchanged. `branch` is `true`, `false`, `null` or absent; `null` is the same as absent. Any
other value, and `true` without `previous_response_id`, MUST be refused with `400`,
`code: "invalid_input"`, `param: "branch"`. A request that asked for a branch never runs some
other way: with a session hint it would otherwise run as a new turn of the session the client
asked to leave alone.

The response MUST carry a new `metadata.session_id` and
`metadata.branched_from: "resp_first"`, identically for synchronous, streaming, background,
and subsequently retrieved responses. Only that response carries it: a later response in the new
session continues it like any other and has no `branched_from`. The session's own detail keeps
the origin (§3). A branch restores the user's files, **not installed
dependencies or native CLI state**. The conversation is supplied as its transcript, so a
branch does not require any base's native fork or resume feature. Imported history is kept
in full; inference prompt limits do not truncate the stored transcript.

A response still running cannot be a branch point. A server MUST return `409` with
`code: "branch_unavailable"` when that response has no recorded checkpoint, its commit is
no longer in the session's history, or the committed files cannot be restored. This includes
older responses whose checkpoint position was never recorded. `store: false` alone does not
make a response ineligible: the same response-record and checkpoint availability checks apply. It MUST NOT substitute the
latest workspace. Unknown or inaccessible sessions follow the ordinary `404` scope rules;
transient preparation failures are retryable `503` errors. Preparation failures are HTTP
errors in every response mode, before a background acknowledgment or stream is accepted.
An `input_response` together with `branch` is `400 invalid_input` (`param: "branch"`):
branching neither answers nor voids the original question, which stays pending in the original
session.

The reference implementation copies committed files from Git into a fresh session repository. The reference regenerates non-secret file-root metadata for
bases whose user workspace is a subdirectory; it does not copy their native conversation state.
It excludes Git internals, `.harness/` (CLI home and per-turn configuration), ignored files,
checkpoint-excluded credentials and scratch paths (rooted configuration patterns stay rooted;
unanchored scratch patterns apply at any depth), and dependency directories `node_modules`,
`.venv`, `venv`, `__pycache__`, and `.cache` at any depth. A submodule or an escaping symlink
makes that checkpoint unavailable; it is never restored partially. The source's Git configuration,
hooks, alternate object stores and native CLI credentials are never imported. A successful branch
has its own durable checkpoint, so it can continue after a gateway or sandbox restart.
Imported workspace-file citations resolve against the new session. Captured artifact bytes are
copied into its storage, so deleting the source does not break those imported artifacts. A citation
already missing before the branch remains unavailable. References into excluded state, credential
or dependency paths remain unavailable in the branch. Imported transcript-only turns have no
checkpoint of their own and return `branch_unavailable` when selected as a branch point.

**Compatibility:** an older server may ignore `branch` and continue the original session.
A client MUST check both the new session id and `metadata.branched_from` before treating a
response as a branch. Such a check detects old-server behavior; it cannot undo a task that an
old server already ran. Use branching only with an implementation known to support it.

## 2. Listing sessions

Conformance class **Extended**.

```http
GET /v1/sessions?limit=20&cursor=&harness=chrn_…
```

```json
{
  "sessions": [
    {
      "id": "hsess7e78…",
      "object": "session",
      "harness_id": "chrn_…",
      "title": "Summarise README.md",
      "status": "completed",
      "created_at": 1786400000,
      "updated_at": 1786400240
    }
  ],
  "next_cursor": null
}
```

Pagination is cursor-based. A server MUST return `next_cursor: null` on the last page, and MUST NOT
require a client to detect the end by receiving fewer items than it asked for — that heuristic is
wrong whenever a page is exactly full.

## 3. Inspecting a session

```http
GET /v1/sessions/{session_id}
GET /v1/sessions/{session_id}/turns
```

`/turns` returns the ordered task history of the session, so a client can rebuild a transcript it did
not store. Each turn identifies its response id, so a client can fetch the full response for any of
them.

Each item in `turns` MUST carry at least:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | The response id of the turn, usable with `GET /v1/responses/{id}`. |
| `status` | string | The turn's status, in the response-status vocabulary of [Tasks §1](tasks.md). |

and SHOULD carry, when the server has them: `user` (string, the user message), `assistant` (string,
the assistant's final text), `tools` (array, the tool calls of the turn), and `files` (array, the
files the turn produced). A server MAY add fields; a client MUST ignore fields it does not
understand. This was previously an object with no stated shape, which meant no conformance check
could assert anything past the status code, and every client that rebuilt a transcript did so
against one implementation's habits.

A server with the `input_history` capability marks each turn a session was started with
([Tasks §2.1](tasks.md#21-earlier-turns)) `imported: true`, and every turn that ran `imported: false`.

Each turn SHOULD also carry `created_at`, when it began, and `completed_at`, when it ended, both
integers in Unix seconds like the Response's `created_at` ([Tasks §3](tasks.md#3-the-response-object)).
`completed_at` is `null` while the turn is running and when the server does not know when it ended.
An imported turn carries the time it was imported for both, so a client reading a session's history
never has to fetch each turn's response to learn when it happened.

A session whose turns read an environment carries `environment`, the environment's id, so a client
can tell which project a conversation worked in ([Environments §6](environments.md#6-what-a-session-sees)).

A branched session's detail carries `branched_from: {"response_id": "resp_first",
"session_id": "hsess_original", "turn": 1}`. `turn`, when the server records it, is where that
response stood in its session, counting from 1, so a client can draw where on the original line the
branch starts without reading either transcript. Its copied turns are `imported: true`, with new response ids and zero imported
cost. Git commit ids are internal checkpoint details.

## 4. Cancelling

Two scopes, deliberately distinct:

```http
POST /v1/responses/{response_id}/cancel     # stop this task
POST /v1/sessions/{session_id}/cancel       # stop whatever is running in this session
```

Semantics:

- Cancellation is a request, not a guarantee of immediacy. A server MUST stop the work as soon as it
  can and MUST reach a terminal state.
- A cancelled task MUST end with `status: "cancelled"`, never `failed`.
- Output produced before cancellation MUST be retained.
- Cancelling an already-terminal task MUST succeed and change nothing. A client retrying a cancel
  after a dropped connection should not receive an error for having succeeded twice.
- Cancelling MUST NOT delete the session. The conversation remains continuable.

A server SHOULD respond to cancel within one second even if the harness takes longer to wind down.
The client is usually a user interface, and a Stop button that does nothing visible for thirty
seconds reads as broken.

## 5. Session sharing

Conformance class **Full**. A server MAY let a client publish a read-only view of a session.

```http
POST   /v1/sessions/{session_id}/share      # publish (a body is OPTIONAL; no body means publish)
GET    /v1/sessions/{session_id}/share      # read the share back
DELETE /v1/sessions/{session_id}/share      # revoke
```

If implemented, the share object returned by `POST` and `GET` MUST carry:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | The share's identity. |
| `url` | string | Where the shared view is served. May be relative, in which case it resolves against the base URL the caller is already using — a server behind a proxy cannot know its public origin, and a base-relative path survives every fronting. |

`object` SHOULD be `"session.share"`. A server MAY carry additional fields (the reference also
returns an `enabled` toggle and accepts `{"enabled": bool}` bodies); a client MUST ignore fields it
does not understand. A second `POST` MAY return the existing share or mint a new one, but
revocation MUST reach every link minted for the session — revoking only the newest tells an
operator the session is private while somebody still holds a working link.

The rules, unchanged:

- the shared view MUST be read-only — it MUST NOT permit continuing, cancelling, or uploading;
- `GET` on the published `url` MUST serve the view to a holder of the link with no other
  credential — a view only its creator can open has not been published to anyone;
- after `DELETE`, and after the session itself is deleted (§6), the published `url` MUST stop
  resolving (404 or 410);
- the share's id MUST NOT function as a credential for the rest of the API;
- the server MUST NOT expose provider credentials, tokens, or another principal's data through the
  view.

These were previously behaviors the conformance suite had to discover by probing (the endpoints and
the object had no stated shape, so a portable check could only guess at paths and skip when the
guesses missed). They are codified from the shapes the reference implementation demonstrates and
the R-series measures; the suite now asserts them.

## 6. Deleting

```http
DELETE /v1/sessions/{session_id}
```

Deletes the session and its stored history: the transcript, the trace, and the working folder the
session's tasks wrote. Afterwards the session MUST NOT count toward any storage or memory allowance
the server enforces, because deletion is how a client makes room. A server MUST answer `2xx`, and a
later `GET /v1/sessions/{session_id}` MUST return `404`.

`DELETE /v1/traces/{session_id}` is the older path for the same operation. It predates the session
vocabulary; a server MAY keep serving it (the reference implementation does, as the same handler),
but the path above is the one the protocol names and the one clients SHOULD use.

A server MUST cancel any in-flight task in the session first, and MUST make the session
unreadable afterwards. Deletion is the one place where cancel and
delete are legitimately coupled, because the alternative is a running task writing into storage that
no longer has an owner.
