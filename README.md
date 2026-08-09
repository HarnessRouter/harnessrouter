# HarnessRouter

**Run agentic coding harnesses on your own machine.** One container, your own API keys, your
own data. Configure a harness, give it work, watch it run — no account, no cloud, no telemetry.

```bash
cp .env.example .env      # add your provider key
docker compose up -d
open http://localhost:3000
```

That's the whole install. State is SQLite and files on one Docker volume.

---

## What it is

A *harness* is a configured agent: a backend runtime, a model, instructions, and limits. A
*task* is one run of that harness — a real conversation against a real POSIX workspace with
bash and git, streamed back as it happens.

HarnessRouter gives you the full protocol for both: an OpenAI **Responses-compatible** API for
running turns, harness CRUD, sessions, streaming, cancellation, and idempotency. The console is
a thin client over that API — anything the UI does, you can do from `curl`.

**Backends:** Claude Code, OpenAI Codex, and Hermes. They are installed on first run rather than
shipped in the image — Claude Code is distributed under Anthropic's own terms and hermes-agent
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

## Moving to the hosted service

When a harness is working the way you want, **Harnesses → Push to cloud** copies it into a
hosted HarnessRouter account with your hosted API key.

This is deliberately one-way. Local is where you iterate; once promoted, the hosted copy is the
source of truth. There is no "pull from cloud", so a harness can never be live in two places
each claiming to be current. Your hosted key is used for that one request and is never stored.

## Architecture

```
┌─ container ────────────────────────────────────────────┐
│  UI (Next.js)  :3000  ← the only published port        │
│      │ same-origin proxy                               │
│  Gateway       :8080  Responses API, harness CRUD       │
│      │ loopback                                        │
│  Runner        :8081  spawns the agent CLI on /workspace│
└────────────────────────┬───────────────────────────────┘
                    /data (volume): SQLite, blobs, secrets
```

Storage sits behind a small adapter interface (graph / blob / secret). This repo ships the local
implementations; the hosted deployment overlays its own against the same interface. That seam is
why this is genuinely the same codebase rather than a fork that drifts.

## License

MIT — see [LICENSE](LICENSE). Third-party notices are in [NOTICE](NOTICE).

The agent CLIs are **not** redistributed here; they are installed on first run under their own
licenses. Review them before enabling a backend.
