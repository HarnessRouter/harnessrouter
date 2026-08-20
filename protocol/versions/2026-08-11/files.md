# Files

**Unified Harness Protocol, version `2026-08-11`**

An agent that can only return text is a chatbot. A harness edits files, writes reports, produces
diagrams. This chapter defines getting files in and artifacts out.

Conformance class **Extended**.

## 1. Sending files in

### 1.1 Inline

For small files, inline the bytes as a data URL:

```json
{
  "input": [
    { "role": "user", "content": [
        { "type": "input_text", "text": "Summarise this." },
        { "type": "input_file", "filename": "q3.pdf",
          "file_data": "data:application/pdf;base64,JVBERi0xLjQK…" }
    ]}
  ]
}
```

### 1.2 By upload

For anything larger, upload once and reference by id:

```http
POST /v1/files
Content-Type: multipart/form-data
```

```json
{ "id": "file_abc123", "object": "file", "filename": "q3.pdf", "bytes": 184320, "created_at": 1786400000 }
```

```json
{ "type": "input_file", "file_id": "file_abc123" }
```

A server MUST accept both forms. Inline avoids a round trip for a 4 KB file; upload avoids
base64-inflating a 40 MB one through every retry. A server MUST document its size limit and MUST
reject an oversized upload with `413` and `code: "file_too_large"` rather than truncating — a
silently truncated input produces a confident, wrong answer.

## 2. Getting artifacts out

Files an agent produces become artifacts of the session's container. They are reported in two
places.

### 2.1 On the response

Artifacts appear as annotations on the assistant message:

```json
{
  "type": "message",
  "content": [
    { "type": "output_text", "text": "I've written the report.",
      "annotations": [
        { "type": "container_file_citation",
          "container_id": "cntr_…",
          "file_id": "file_…",
          "filename": "report.md",
          "download_url": "https://server/v1/containers/cntr_…/files/file_…/content",
          "start_index": 0, "end_index": 24 }
      ]
    }
  ]
}
```

A client that renders only text still shows a correct answer; a client that reads annotations can
offer the file. That is the intended layering — artifacts are additive to the message, never a
replacement for it.

### 2.2 By listing the session

```http
GET /v1/sessions/{session_id}/files
```

```json
{ "files": [ { "id": "file_…", "container_id": "cntr_…", "filename": "report.md",
               "bytes": 2048, "created_at": 1786400240 } ] }
```

A server MUST list every artifact of the session, including files from earlier tasks. Restricting the
list to the most recent task would make a multi-step session's earlier outputs unreachable.

## 3. Downloading

```http
GET /v1/containers/{container_id}/files/{file_id}/content
```

Returns the raw bytes with the file's own `Content-Type`. A server MUST NOT wrap the bytes in JSON.

A server SHOULD send `Content-Disposition` with the original filename, and MUST set
`X-Content-Type-Options: nosniff`. Artifacts are attacker-influenced content — an agent can be
persuaded to write a file — so serving them without those headers turns an artifact into stored
XSS against the client's own origin.

### 3.1 Preview rendering

A server MAY offer a rendered preview of a document format:

```http
GET /v1/containers/{container_id}/files/{file_id}/pdf
```

If a server does not implement conversion it MUST return `501` with
`code: "preview_unavailable"`, not a broken or empty PDF. If conversion fails it MUST return `502`
with `code: "preview_failed"`. A client can then tell "this server never previews" from "this file
would not convert", and only the second is worth retrying.

## 4. Bulk download

```http
GET /v1/sessions/{session_id}/files/archive
```

Returns every artifact of the session as a single archive. A server SHOULD implement this: a session
that produced forty files should not require forty requests.

## 5. Retention and scope

- Artifacts live with their session. Deleting a session MUST make its artifacts unreachable.
- A server MUST scope file access to the owning principal. A `file_id` from another principal MUST
  return `404`, never the bytes.
- A server MUST NOT let a `container_id` / `file_id` pair traverse outside its container. Path
  traversal through artifact ids is the most likely serious vulnerability in a UHP implementation,
  and the conformance suite probes for it.
