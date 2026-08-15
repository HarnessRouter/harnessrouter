<div align="center">
  <a href="https://harnessrouter.ai">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/images/logo-dark.png">
      <source media="(prefers-color-scheme: light)" srcset=".github/images/logo-light.png">
      <img alt="HarnessRouter" src=".github/images/logo-light.png" width="55%">
    </picture>
  </a>
</div>

<div align="center">
  <h3>Run agent harnesses on your own machine.</h3>
</div>

<div align="center">

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/harnessrouter/harnessrouter?logo=docker&logoColor=white)](https://hub.docker.com/r/harnessrouter/harnessrouter)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/nPcbwqVPb2)
[![X](https://img.shields.io/badge/Follow-%40HARNESSROUTER-000000?logo=x&logoColor=white)](https://x.com/HARNESSROUTER)
[![UHP conformance](https://img.shields.io/badge/UHP-class%20Full-brightgreen)](protocol/conformance/)

</div>

<br>

**Run agent harnesses on your own machine.** One container, your own API keys, your
own data. Configure a harness, give it work, watch it run, with no account, no cloud, and no telemetry. Community Edition implements the [Unified Harness Protocol (UHP)](https://unifiedharnessprotocol.org), the open standard the hosted service implements too.

> [!TIP]
> New here? Start with [What it is](#what-it-is), or read the protocol at [unifiedharnessprotocol.org](https://unifiedharnessprotocol.org).

## Quickstart

```bash
docker run -d -p 3000:3000 -v harnessrouter:/data \
  -e HR_SECRET_GLOBAL_HARNESS_CONN_ANTHROPIC='{"name":"anthropic","provider":"anthropic","api_key":"sk-ant-…"}' \
  -e HR_SECRET_GLOBAL_HARNESS_POLICY_CLAUDE='{"chain":["anthropic"]}' \
  harnessrouter/harnessrouter
open http://localhost:3000
```

Or `cp .env.example .env`, put your key in it, and `docker compose up -d`.

That's the whole install. State is SQLite and files on one Docker volume.

---

## What it is

An *agent harness* is the runtime layer around a model; Codex, Claude Code, and Hermes are harnesses. In this repo's API you also create *harness* objects: a saved configuration whose `base` is one of those runtimes, plus a model, instructions, and limits. A *task* is one run of that configuration, a real conversation against a real POSIX workspace with bash and git, streamed back as it happens.

HarnessRouter Community Edition implements UHP for both: an OpenAI **Responses-compatible** API for
running turns, harness CRUD, sessions, streaming, cancellation, and idempotency. The console is
a thin client over that API; anything the UI does, you can do from `curl`.

**The console is the hosted product's console.** Not a cut-down rebuild: the same pages, the
same components, the same API client. Surfaces that need a service a single box doesn't have,
such as accounts, billing, and marketplace, are simply not shown.

**Supported harnesses:** Codex, Claude Code, and Hermes. They are installed on first run rather than
shipped in the image. Claude Code is distributed under Anthropic's own terms and hermes-agent
declares no license, so neither can be redistributed. Set `HR_BACKENDS` to choose which you want,
and review each tool's license before enabling it.

**Bring your own key.** Your provider credentials are read from the environment at start-up and
handed to the agent directly. They are never written into the image, never committed, and never
sent anywhere but your provider.

## Why self-host

- **Your keys, your bills, your data.** Nothing leaves the box except calls to your model provider.
- **Real workspaces.** Agents get bash, git, and a filesystem — their native environment, not a
  sandbox emulation.
- **The same API as the hosted product.** Not a reduced fork: the same `/v1` surface, so anything
  you build against it keeps working if you later move to the hosted service.
- **Actually self-contained.** No control plane to phone home to, no managed database, no vault.

## The Unified Harness Protocol

This repository is both an implementation and a standard. The protocol the gateway speaks is
specified, versioned and testable in [`protocol/`](protocol/), and documented at
[unifiedharnessprotocol.org](https://unifiedharnessprotocol.org):

| | |
|---|---|
| [Specification](protocol/versions/2026-08-11/) | Ten normative chapters, version `2026-08-11` |
| [Machine-readable](protocol/schema/) | OpenAPI 3.1 + JSON Schema 2020-12, generated from one source |
| [Conformance suite](protocol/conformance/) | 47 runnable checks; passing it is what "conformant" means, and what earns the right to the UHP name |
| [Governance](protocol/GOVERNANCE.md) | How the standard changes, and the naming and conformance policy |

This edition is the reference implementation and
[passes at class Full](protocol/conformance/reports/harnessrouter-ce-0.3.0.json). **The standard can
be implemented without HarnessRouter Cloud** — it is an HTTP contract, and nothing in it requires a
hosted service. Run the suite against your own server:

```bash
pip install -e protocol/conformance
uhp-conformance --base-url https://your-server --api-key "$KEY" --class full
```

## Configuration

Everything is configured for self-hosting out of the box. The only thing you must supply is a
provider key:

```bash
# .env
HR_SECRET_GLOBAL_HARNESS_CONN_ANTHROPIC={"name":"anthropic","provider":"anthropic","api_key":"sk-ant-…"}
HR_SECRET_GLOBAL_HARNESS_POLICY_CLAUDE={"chain":["anthropic"]}
```

A *connection* names a provider and its credential; a *policy* says which connection a backend
uses. Any OpenAI-compatible endpoint works — aggregators, local models, or your own inference
server — by setting `provider: "openai-api"` and a `base_url`.

<details>
<summary>Connecting a database</summary>

An agent can be given a PostgreSQL or MySQL database to read — that is how the dashboard kit
works. Two things to know before you connect one.

**Set `HR_SECRET_KEY`.** Connection strings are encrypted at rest under a key derived from it,
and without it the server refuses to store one rather than writing your production credential to
disk in plaintext:

```bash
HR_SECRET_KEY=a-long-random-passphrase
```

Keep it. Change it and the stored connections can no longer be decrypted, and you reconnect them.

**Use a read-only database account.** Every statement is checked and only `SELECT` is allowed —
non-`SELECT`, multiple statements and data-modifying CTEs are refused, and on PostgreSQL the
query additionally runs in a `READ ONLY` transaction. That check is a parser, and a parser is a
thing that can be wrong. An account that has been granted `SELECT` and nothing else is a second
defence that does not depend on ours being right:

```sql
CREATE USER dashboards WITH PASSWORD '…';
GRANT CONNECT ON DATABASE shop TO dashboards;
GRANT USAGE ON SCHEMA public TO dashboards;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboards;
```

The connection string is resolved inside the gateway at the moment a query runs. The agent's
sandbox never receives it — it gets a tool that runs `SELECT`s — and neither does the browser.

**Sample rows** are a per-connection switch, on by default: the agent sees a few real rows per
table so it can tell a status column from a category one. Turn it off and it sees table and
column names and types and no values at all.
</details>

<details>
<summary>Choosing backends, and building with a browser</summary>

Backends are chosen at run time, because they are installed into your data volume rather than
baked into the image:

```bash
docker run -e HR_BACKENDS=claude,codex,hermes ...   # default
docker run -e HR_BACKENDS=claude ...                # just Claude Code
```

The first start installs them (once per volume). Chromium is genuinely an image layer, so it
stays a build flag:

```bash
docker build -t harnessrouter --build-arg WITH_BROWSER=1 .
```
</details>

<details>
<summary>What the entrypoint sets for you</summary>

| Variable | Default | Why |
|---|---|---|
| `HR_BACKING` | `local` | SQLite + files on `/data`. No external storage. |
| `HR_IDENTITY_MODE` | `off` | Single-tenant box; login would be ceremony with nothing behind it. |
| `HR_CREDIT_GATE` | `off` | Metering is a hosted concern. |
| `POOL_MGMT_ENDPOINT` | `http://127.0.0.1:8081` | The runner is in this container. |
| `HR_POOL_AUTH` | `none` | No cloud identity to present to a loopback runner. |
| `HR_SANDBOX_TRUST` | `owner` | You own the box, the agent and the key, so the key is handed over directly rather than brokered. |
| `HARNESS_WORKSPACE` | `/data/workspaces` | One directory per session, on the volume — so a restart doesn't discard work in flight. |
| `HR_WORKSPACE_TTL_HOURS` | `72` | Idle session workspaces are removed after this. They rehydrate from their checkpoint, so this costs time, not work. `0` keeps them forever. |
| `HARNESS_INTERNAL_KEY` | generated | Per-container; never leaves the process tree. |

</details>

## Using the API

The console is optional. The gateway speaks the Responses API:

```bash
curl http://localhost:3000/api/gw/v1/responses \
  -H 'content-type: application/json' \
  -H 'x-harness-org: local' \
  -d '{"input":"List the files and summarise this repo",
       "metadata":{"harness_id":"YOUR_HARNESS_ID"},
       "stream":true}'
```

Harness CRUD (`/v1/harnesses`), the model catalog (`/v1/models`), sessions
(`/v1/sessions/{id}/turns`, `/cancel`) and task listing (`/v1/traces`) are all available on the
same surface.

## Putting it on a public URL

The console can create harnesses, read every task transcript, and run an agent with your
provider key. So it ships with a login, on by default, covering the pages and the API alike:

| | |
|---|---|
| `HR_AUTH_USER` | `harnessrouter` |
| `HR_AUTH_PASSWORD` | `harnessrouter` |

> [!WARNING]
> **Change the password before anyone else can reach the instance.** The defaults are printed
> right here, which makes them a placeholder, not a secret; the container warns on every start
> while the default is still in place. `HR_AUTH_DISABLED=1` removes the gate entirely, which is
> only reasonable on a machine nobody else can reach.

You can also change the username and password from **Profile**, in the account menu at the top
right. Those are stored on the data volume (`/data/selfhost-auth.json`, a salted hash — never the
password) and take precedence over the environment from then on, so an `HR_AUTH_PASSWORD` set at
`docker run` months ago cannot quietly undo a password change.

Changing them signs out every other browser and restarts the console, which takes about a second.
The gate runs in Next.js middleware on the Edge runtime, which reads its signing key once at
start-up and cannot be told about a change in place; restarting is what makes "signed out
everywhere" true rather than merely displayed. The gateway and runner are left alone, so a task
that is mid-turn runs straight through it.

Forgot the password? There is no reset email to send, so delete `/data/selfhost-auth.json` and
restart — the instance falls back to `HR_AUTH_USER` / `HR_AUTH_PASSWORD`.

For TLS, keep the console on loopback and put a terminating proxy in front. With Caddy that is
one file and a real certificate, automatically:

```caddyfile
console.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:3000 {
        flush_interval -1      # agent turns stream for minutes; never buffer them
    }
}
```

```bash
docker run -d -p 127.0.0.1:3000:3000 -v harnessrouter:/data \
  -e HR_AUTH_PASSWORD='something only you know' harnessrouter/harnessrouter:0.3.0
```

Pin the tag. `0.3.0` is the first release with the sign-in gate; `0.1.x` and `0.2.0` have none, so
an instance running them is open to anyone who can reach the port.

The `flush_interval -1` matters: without it a proxy buffers the event stream and the console
looks frozen until the turn ends.

## Moving to the hosted service

When a harness is working the way you want, **Harnesses → Push to cloud** copies it into a
hosted HarnessRouter account with your hosted API key.

This is deliberately one-way. Local is where you iterate; once promoted, the hosted copy is the
source of truth. There is no "pull from cloud", so a harness can never be live in two places
each claiming to be current. Your hosted key is used for that one request and is never stored.

## Architecture

```
┌─ container ─────────────────────────────────────────────┐
│  UI (Next.js)  :3000  ← the only published port         │
│      │ same-origin proxy                                │
│  Gateway       :8080  Responses API, harness CRUD        │
│      │ loopback                                         │
│  Runner        :8081  one agent CLI per session          │
└─────────────────────────┬───────────────────────────────┘
       /data (volume): SQLite, blobs, secrets, workspaces
```

Sessions run concurrently and are isolated: each gets its own workspace directory, its own
conversation state, and its own checkpoint. Turn concurrency defaults to the machine's core
count — this box cannot scale sandboxes on demand the way the hosted deployment does, so the
limit is what it can actually run. Publish the port to loopback (`-p 127.0.0.1:3000:3000`) if
the host is reachable from anywhere you don't control: there is no login to stop a visitor.

Storage sits behind a small adapter interface (graph / blob / secret). This repo ships the local
implementations; the hosted deployment overlays its own against the same interface. That seam is
why this is genuinely the same codebase rather than a fork that drifts.

## Resources

- **[Documentation and Cloud](https://harnessrouter.ai)** — hosted service, guides, and pricing.
- **[Unified Harness Protocol](https://unifiedharnessprotocol.org)** — the open standard this repository implements.
- **[Starter Kit](https://github.com/HarnessRouter/starter-kit)** — runnable example applications built on Community Edition.
- **[Discord](https://discord.gg/nPcbwqVPb2)** — community for questions, integrations, and proposals.
- **[Contributing](CONTRIBUTING.md)** and **[Security](SECURITY.md)** — how to propose changes and report vulnerabilities.

## License

Apache-2.0, see [LICENSE](LICENSE). Third-party notices are in [NOTICE](NOTICE).

The agent CLIs are **not** redistributed here; they are installed on first run under their own
licenses. Review them before enabling a backend.
