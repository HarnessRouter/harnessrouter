# UHP conformance suite

**Passing this suite is what "UHP conformant" means.** Not implementing the endpoints, not a
self-assessment, not passing most of it. The suite is in this repository, it runs against any server
over HTTP, and anyone can run it against anyone's implementation.

## Running it

```bash
pip install -e protocol/conformance

uhp-conformance \
  --base-url https://your-uhp-server \
  --api-key "$UHP_API_KEY" \
  --class full \
  --json report.json
```

| Option | Meaning |
|---|---|
| `--base-url` | Server root. The suite appends `/v1/...` itself. |
| `--api-key` | Bearer token, or set `UHP_API_KEY`. |
| `--class` | `core`, `extended` or `full`. Cumulative — `full` runs everything. |
| `--harness-id` | Run tasks against a specific harness instead of the first one listed. |
| `--model` | Run tasks with a specific model. |
| `--task-timeout` | Seconds to allow one agent task. Default 300. |
| `--only` | Comma-separated check ids, for iterating on one failure. |
| `--json` | Write a machine-readable report. |
| `--plain` | No ANSI colour, for CI logs. |

Exit code is `0` when nothing failed and `1` otherwise, so it drops into CI unchanged.

**The suite runs real agent tasks.** It sends about six of them, which costs real model tokens and a
few minutes. That is deliberate: the defects worth catching — a stream that never flushes, a
cancellation that never terminates, an artifact that cannot be downloaded — are invisible to
anything that only inspects a schema.

## What it checks

47 checks across three classes.

| Class | Checks | Covers |
|---|---|---|
| **Core** | 37 | Discovery, version negotiation, authentication, the error envelope, harnesses, models, task execution (streaming and not), the event stream, sessions, cancellation |
| **Extended** | +8 | Session listing and inspection, file input, artifacts, download headers, path-traversal probes |
| **Full** | +2 | Harness create / update / delete, and refusal of an unsupported base |

Every check names the section of the specification it enforces, so a failure points at the sentence
it violates rather than at a test name.

A few of them are worth calling out, because they catch things a schema check never will:

- **S-04** — `sequence_number` is gapless and monotonic. Without it a client cannot tell a dropped
  event from a server that simply skips numbers.
- **S-09** — the stream is progressive. It measures the spread of event arrival times and fails a
  server that buffers everything and flushes at the end. That is the single most common UHP
  deployment error, it is usually a proxy setting, and it is indistinguishable from a slow agent
  unless something measures it.
- **C-03** — a running task really stops. It starts long work, cancels it, and waits for a terminal
  state. A cancel endpoint that returns `200` and leaves the agent running passes every other kind
  of test.
- **X-07** — artifacts download with `X-Content-Type-Options: nosniff`. Artifacts are
  attacker-influenceable content; served without it, an artifact is stored XSS against the client's
  own origin.
- **X-08** — artifact ids do not traverse out of their container. Probes for `../` and its
  percent-encoded form.

## Outcomes

| Outcome | Meaning |
|---|---|
| **PASS** | The required behaviour was observed. |
| **FAIL** | The behaviour was observed to be wrong. A conformance defect. |
| **SKIP** | The check could not run, with the reason recorded. |
| **ERROR** | The check itself broke — a bug in the suite. |

**A skip is never a pass.** The report states skips separately and repeats that they were not
verified, because a suite that hides unrun checks behind a green summary is how a suite starts
lying about the thing it exists to establish.

## Reference implementation results

HarnessRouter Community Edition 0.3.0, the reference implementation in this repository, run against
a live instance on 2026-08-11:

```
  Summary
    47/47 passed · 0 failed · 0 skipped · 0 errored
    CONFORMANT — UHP 2026-08-11 (full)
```

The suite is developed against that implementation, which is exactly why the specification says
conformance is defined by the suite and not by the implementation: anything the reference does that
the suite does not require is a HarnessRouter behaviour, not a UHP requirement, and another
implementation is free to do it differently.

Writing and running the suite found four real defects, three in the reference implementation and one
in the suite itself:

1. No capability discovery at all — a client had to guess or learn from a `404`.
2. No protocol version on the wire.
3. Failures returned a bare human string, so a client had to match on prose to decide whether to
   retry.
4. `POST /v1/harnesses` accepted a base the server could not run, deferring the failure to the first
   task — after the client had committed to it. Caught by **F-02** on the first full run.

## Adding a check

A check is a function that asserts one requirement:

```python
@check("T-08", "Tasks reject an empty input", "core", f"{SPEC}/tasks.md#2-input")
def t08(ctx):
    r = ctx.client.post("/v1/responses", body={"input": ""})
    assert r.status == 400, f"empty input returned HTTP {r.status}, expected 400"
```

Rules for a good check:

- **Assert what the specification says, not what the reference implementation does.** Where the
  specification allows latitude, the check must allow it too — otherwise the suite enforces one
  implementation's preferences and every other implementation fails for being different rather than
  for being wrong.
- **Fail with the evidence.** The message should say what was expected, what happened, and why it
  matters. `assert r.status == 200` tells a maintainer nothing.
- **Skip loudly, never silently.** If a precondition is missing, `raise Skip("reason")`.
- **Clean up.** A check that creates a harness deletes it, including when it fails.

Per [GOVERNANCE.md](../GOVERNANCE.md), a specification change is not complete until a check enforces
it — a rule nothing tests is a wish.
