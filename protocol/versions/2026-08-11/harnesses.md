# Harnesses

**Unified Harness Protocol, version `2026-08-11`**

Before a client can send work it needs to know what can run it, and with which models. This chapter
defines discovery, the harness object, and — at conformance class **Full** — how harnesses are
created and changed.

## 1. Discovering harnesses

```http
GET /v1/harnesses
```

```json
{
  "harnesses": [
    {
      "id": "chrn_08dae611630d467ab3e67ed792570ae5",
      "object": "harness",
      "name": "Research agent",
      "base": "claude-code",
      "baseLabel": "Claude Code",
      "defaultModel": "claude-sonnet-4.6",
      "systemPrompt": "",
      "mcpServers": [],
      "skills": [],
      "disabledTools": [],
      "maxStep": null,
      "timeoutSeconds": null,
      "createdAt": 1786403298205
    }
  ]
}
```

A server MUST return only harnesses within the caller's scope. The list MAY be empty — a server with
no configured harnesses is valid, and a client MUST handle that rather than assuming index `0`
exists.

```http
GET /v1/harnesses/{harness_id}
```

Returns one harness object, or `404` with `code: "harness_not_found"`.

## 2. The harness object

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | `chrn_`-prefixed |
| `object` | string | yes | Always `harness` |
| `name` | string | yes | Human-readable label; not an identifier |
| `base` | string | yes | Which harness runtime: `codex`, `claude-code`, `hermes`, … |
| `baseLabel` | string | no | Display name for `base` |
| `defaultModel` | string | no | Model used when a task omits `model` |
| `systemPrompt` | string | no | Additional standing instructions |
| `mcpServers` | array | no | MCP servers attached to this harness |
| `skills` | array | no | Skills available to this harness |
| `disabledTools` | string[] | no | Tools withheld from the agent |
| `maxStep` | integer \| null | no | Default step budget |
| `timeoutSeconds` | integer \| null | no | Default wall-clock budget |
| `createdAt` | integer | yes | Unix milliseconds |

`base` values are not enumerated by this specification. A server MAY support bases this document has
never heard of, and a client MUST treat `base` as an opaque string — anything else means the
protocol has to be revised every time a harness is released, which is exactly the coupling UHP
exists to remove.

## 3. Models

```http
GET /v1/models
```

```json
{
  "backends": {
    "claude": {
      "default": "claude-sonnet-4.6",
      "models": [
        { "id": "claude-sonnet-4.6", "label": "claude-sonnet-4.6", "backend": "claude",
          "available": true, "default": true }
      ]
    }
  }
}
```

```http
GET /v1/harnesses/{harness_id}/models
```

```json
{
  "harness_id": "chrn_…",
  "backend": "claude",
  "default": "claude-sonnet-4.6",
  "fallback": "claude-sonnet-4.6",
  "models": [ { "id": "claude-opus-5", "available": true, "default": false } ]
}
```

### 3.1 `available` is a promise

`available: true` means the server can serve that model for that harness **right now** — a
credential exists and the provider can reach it. `available: false` means a request for it will not
run as asked.

A server MUST compute `available`, not assert it. Listing a model as available and then failing the
task is the worst outcome for a client: it presents a choice to a user, the user picks it, and the
work fails after they have committed to it.

A client SHOULD present unavailable models as disabled rather than hiding them, so a user can see
that a model exists and is not configured, rather than wondering why it is missing.

## 4. Managing harnesses

Conformance class **Full** only. A client MUST check the `harness_management` capability first.

### 4.1 Create

```http
POST /v1/harnesses
```

```json
{ "name": "Research agent", "base": "claude-code", "default_model": "claude-sonnet-4.6" }
```

Returns the created harness object. `base` is REQUIRED and MUST be one the server supports;
otherwise `422` with `code: "unsupported_base"`.

### 4.2 Update

```http
PUT /v1/harnesses/{harness_id}
```

Replaces the mutable configuration. A server MUST NOT change `id`, `base`, or `createdAt`. Changing
the base of an existing harness would silently change the behaviour of every session already
attached to it; a client that wants a different base MUST create a different harness.

### 4.3 Delete

```http
DELETE /v1/harnesses/{harness_id}
```

A server MUST NOT delete the sessions or responses that used the harness. History that disappears
when configuration changes cannot be audited.

## 5. Choosing a harness

Non-normative, but the question every client faces:

| If the task is… | Consider |
|---|---|
| Code editing in a repository | A coding-specialised base (`codex`, `claude-code`) |
| Long-horizon multi-tool work | A base with an explicit step budget and strong tool use |
| Cheap, high-volume classification | The smallest model on any base |

The point of UHP is that this choice stays reversible. A product that speaks UHP can change base or
model with a configuration edit, and can A/B two harnesses against the same input without a second
integration.
