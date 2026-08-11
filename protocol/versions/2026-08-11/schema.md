# Schema

**Unified Harness Protocol, version `2026-08-11`**

The machine-readable definitions are normative for structure. Where this prose and the schema
disagree about the shape of an object, the schema wins; where they disagree about behaviour, the
prose wins, because behaviour is not expressible in JSON Schema.

## Files

| File | Format | Use |
|---|---|---|
| [`uhp-2026-08-11.openapi.yaml`](../../schema/uhp-2026-08-11.openapi.yaml) | OpenAPI 3.1 | Generate clients and servers; browse the API |
| [`uhp-2026-08-11.schema.json`](../../schema/uhp-2026-08-11.schema.json) | JSON Schema 2020-12 | Validate objects and streamed events |

Both are versioned by filename. A published version is immutable: fixing a schema means publishing a
new version, never editing one clients may already have generated from.

## Generating a client

```bash
# TypeScript
npx openapi-typescript protocol/schema/uhp-2026-08-11.openapi.yaml -o uhp.d.ts

# Python
openapi-python-client generate --path protocol/schema/uhp-2026-08-11.openapi.yaml

# Go
oapi-codegen -package uhp protocol/schema/uhp-2026-08-11.openapi.yaml > uhp.gen.go
```

## Validating events

Every streamed event validates against the `Event` definition, which is a discriminated union on
`type`:

```python
import json, jsonschema

schema = json.load(open("protocol/schema/uhp-2026-08-11.schema.json"))
validator = jsonschema.Draft202012Validator(
    {"$ref": "#/$defs/Event", **schema})

for line in stream:
    if line.startswith("data: "):
        validator.validate(json.loads(line[6:]))
```

The conformance suite does exactly this against a live server, so a schema change that the reference
implementation does not satisfy fails CI rather than shipping.

## Extension points

A server MAY add fields anywhere the schema allows additional properties:

- `metadata` on a request or response — the intended place for client and server context.
- `detail` on an error — structured context for a specific failure.
- Additional output item types, and additional event types.

A server MUST NOT redefine the meaning of a specified field, and MUST NOT add a required field: a
client written against this version has to keep working. Vendor-specific fields SHOULD carry a
vendor prefix so that a later version of this specification cannot collide with them.
