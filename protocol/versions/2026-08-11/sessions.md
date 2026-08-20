# Sessions

**Unified Harness Protocol, version `2026-08-11`**

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

> **Why chain on the response id rather than the session id?**
> Because the response id is what the client already has: it comes back from the task it just ran.
> Chaining on it also names an exact point in the conversation, which leaves room for a server to
> branch from an earlier response later without changing the request shape.

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
POST /v1/sessions/{session_id}/share
GET  /v1/sessions/{session_id}/share
```

If implemented:

- the shared view MUST be read-only — it MUST NOT permit continuing, cancelling, or uploading;
- the server MUST allow revocation;
- the server MUST NOT expose provider credentials, tokens, or another principal's data through it.

## 6. Deleting

```http
DELETE /v1/traces/{session_id}
```

Deletes the session and its stored history. A server MUST cancel any in-flight task in the session
first, and MUST make the session unreadable afterwards. Deletion is the one place where cancel and
delete are legitimately coupled, because the alternative is a running task writing into storage that
no longer has an owner.
