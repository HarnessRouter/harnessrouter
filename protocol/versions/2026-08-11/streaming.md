# Streaming

**Unified Harness Protocol, version `2026-08-11`**

Agent tasks take minutes. Without a stream, a product can only show a spinner and hope. This chapter
defines how a server reports progress while work is happening.

## 1. Opening a stream

Set `"stream": true` on `POST /v1/responses`. The server MUST respond with:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
```

Each event is a Server-Sent Events message whose `data` is one JSON object:

```
data: {"type":"response.created","sequence_number":0,"response":{…}}

data: {"type":"response.output_text.delta","sequence_number":7,"item_id":"msg_1","output_index":0,"content_index":0,"delta":"Sum"}

data: {"type":"response.completed","sequence_number":42,"response":{…}}

```

Rules:

- Every event MUST carry `type` and `sequence_number`.
- `sequence_number` MUST start at `0` and increase by exactly 1 per event within a stream. A client
  can therefore detect a dropped event rather than silently rendering a gap.
- The stream MUST end with exactly one terminal event (§4).
- A server MUST NOT buffer the stream to completion before sending it. A stream delivered all at once
  at the end is not a stream, and a client cannot tell the difference between that and a hang.
- Servers behind a proxy MUST disable response buffering. This is the single most common deployment
  error for UHP servers; it looks exactly like the harness being slow.

## 2. Event vocabulary

Events describe *what happened*. They never describe how to display it.

### 2.1 Response lifecycle

| Event | When |
|---|---|
| `response.created` | The task was accepted. Carries the initial `response` with `status: in_progress`. |
| `response.in_progress` | Work has started. |
| `response.completed` | Terminal — success. Carries the final `response`. |
| `response.incomplete` | Terminal — a budget stopped the work. Carries the final `response`. |
| `response.failed` | Terminal — failure. Carries the final `response`, whose `error` is non-null. |

### 2.2 Output items

| Event | When |
|---|---|
| `response.output_item.added` | A new item begins. Carries `output_index` and a shell `item`. |
| `response.output_item.done` | That item is final. Carries the complete `item`. |

### 2.3 Assistant text

| Event | Payload |
|---|---|
| `response.content_part.added` | An empty `output_text` part opens |
| `response.output_text.delta` | `delta`: the next fragment of text |
| `response.output_text.done` | `text`: the complete text of the part |
| `response.content_part.done` | `part`: the finished part |
| `response.output_text.annotation.added` | `annotation`: an artifact citation (see [Files](files.md)) |

Text deltas are fragments, not lines or tokens. A client MUST concatenate them in `sequence_number`
order and MUST NOT assume any particular chunking.

### 2.4 Reasoning

| Event | Payload |
|---|---|
| `response.reasoning_summary_part.added` | An empty summary part opens |
| `response.reasoning_summary_text.delta` | `delta`: the next fragment of the summary |
| `response.reasoning_summary_part.done` | `part`: the finished summary part |

Reasoning is a *summary*, not a verbatim chain of thought. A server MUST NOT be required to expose
raw model reasoning, and a client MUST treat reasoning as optional — many harness and model
combinations produce none, and a client that requires it will break on those.

### 2.5 Tool use

| Event | Payload |
|---|---|
| `response.function_call_arguments.delta` | `delta`: fragment of the JSON arguments |
| `response.function_call_arguments.done` | `arguments`: the complete JSON string |

The tool call itself arrives as an `output_item` of type `function_call`, and its result as
`function_call_output` matched by `call_id`.

### 2.6 Errors

| Event | Payload |
|---|---|
| `error` | `code`, `message`, `param` — an error that did not end the task |

An `error` event MUST be followed by a terminal event. A stream that emits `error` and then stops
without a terminal event is malformed: the client cannot tell whether the task died or the
connection did.

## 3. Ordering guarantees

A server MUST guarantee:

1. `response.created` is the first event.
2. Exactly one terminal event is the last.
3. For any item, `output_item.added` precedes every event referring to it, and `output_item.done`
   follows them all.
4. `sequence_number` is strictly monotonic with no gaps.

A server MUST NOT guarantee, and a client MUST NOT assume:

- that items complete in the order they were added (a long tool call may finish after later text);
- that text arrives in any particular chunk size;
- that any optional event type appears at all.

## 4. Terminal events

Exactly one of `response.completed`, `response.incomplete`, `response.failed`. Each carries the
complete final `response` object — a client that missed intermediate events can rely on this one
alone to render the result. This redundancy is deliberate: a dropped connection mid-stream should
cost latency, not correctness.

A cancelled task terminates with `response.failed` carrying `status: "cancelled"` in the response
object. The status field, not the event name, is authoritative.

## 5. Reconnecting

A dropped connection MUST NOT abort the task. The work continues server-side.

To follow a task after a disconnect, a client re-reads it:

```http
GET /v1/responses/{response_id}
```

or, for a live event feed of a harness's sessions:

```http
GET /v1/harnesses/{harness_id}/events
```

A server MAY additionally support SSE `Last-Event-ID` resumption. If it does, it MUST resume from
the event *after* the given `sequence_number` and MUST NOT replay events the client already saw.

> A client SHOULD treat the stream as an optimisation and the stored response as the source of
> truth. Products written the other way round — where the stream is the only place a result exists —
> lose work every time a load balancer recycles a connection.

## 6. Non-streaming

With `"stream": false` (the default), the server returns a single response object when the task
reaches a terminal state, with the same `output` array the stream would have assembled. The two
paths MUST produce identical results for identical input. A server that assembles a different
`output` for streaming than for non-streaming has two implementations of its own protocol, and one
of them is wrong.
