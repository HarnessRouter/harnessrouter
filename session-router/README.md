# session-router — one gateway, many runners

The gateway addresses its runner through one base URL (`POOL_MGMT_ENDPOINT`) and carries the
session identifier as `?identifier=` on every call. The session-router holds that base URL,
keeps a registry of runners, and pins every identifier to the runner that owns it — so a
self-hosted cluster scales by adding runner containers instead of one runner's single machine.

Nothing in the gateway or the runner changes: the router is a transparent, affinity-pinning
proxy that speaks the runner's exact surface (`/turn`, `/hydrate`, `/checkpoint`, `/file`,
`/produced`, `/environments/...`), streamed both ways.

## Why affinity is the whole design

A session's workspace is a directory (and, behind the write-wall, a uid) on ONE runner's
volume. Two runners answering one session's calls would be two half-workspaces, so every call
for an identifier goes to its one owner:

- **Sticky**: the first call for an identifier assigns it to the least-loaded runner; every
  later call follows. The table is SQLite (`HR_ROUTER_DB`), so a router restart keeps every
  session on its runner.
- **Environment-pinned**: environments are built through the same proxy (`identifier=<env
  id>`), so a layer exists on one runner. The gateway passes `environment=<env id>` on
  `/hydrate`, placing the restored workspace there before `/turn`. A turn whose environment
  conflicts with its current owner is refused until hydrate restores it on the correct runner.
- **Self-healing**: a health sweep (`/healthz`, every `HR_HEALTH_INTERVAL_S`) marks runners
  stale after `HR_RUNNER_DEAD_S`; the next `/hydrate` reassigns a session to a live
  runner. Other session calls fail rather than moving to an empty workspace. The gateway's
  `/hydrate` restores the workspace from its checkpoint tarball there —
  that durable copy is what makes reassignment safe. A turn in flight on a runner that died is
  lost the way any machine loss loses it. Pending restores are persisted in SQLite, so a failed
  hydrate followed by a router restart still cannot checkpoint an unrestored workspace.
- **Fail-fast**: a connect failure answers 502 at once, which the gateway's retry ladder
  treats as transient; a subsequent hydrate can reassign after the sweep marks the owner stale.

## Run

For a complete gateway and two-runner deployment, configure `.env` and set
`HARNESS_INTERNAL_KEY`, then run from the repository root.

```bash
docker compose -f docker-compose.cluster.yml up -d --build
```

The four services use independent persistent volumes. Run one router replica with one worker.

```bash
cd session-router
docker build -t harnessrouter/session-router .
docker run -d --name session-router \
  -p 127.0.0.1:8090:8090 \
  -e HR_RUNNERS="r1=http://runner-1:8081,r2=http://runner-2:8081" \
  -e HR_ROUTER_KEY="$HARNESS_INTERNAL_KEY" \
  -v session-router-data:/data \
  harnessrouter/session-router
```

Point the gateway's `POOL_MGMT_ENDPOINT` at the router instead of at a runner:

```
POOL_MGMT_ENDPOINT=http://session-router:8090
```

Everything else — `HARNESS_GATEWAY_URL`, `HARNESS_INTERNAL_KEY`, `.env` — is unchanged: the
runner still dials the gateway directly for the model broker and MCP relay, and the gateway
still signs its calls with `X-Harness-Internal`, which the router forwards untouched.

## Configuration

Run one router replica with one worker and retain its entire data volume. All runners used for
environment recovery must have the same image, CPU architecture and `HR_ENV_ROOT` path, because
installed dependencies can contain absolute paths and native binaries.

Environment reads and successful edits capture a streamed snapshot under the router database's
adjacent `.snapshots` directory. Asynchronous builds are captured after they finish, including
when the client stops polling. An environment edit invalidates the previous snapshot before it
is forwarded. Until the replacement snapshot commits, recovery fails closed. Existing layers
need a read through this router on an updated runner to create their first snapshot. A failed
owner's environment is restored before its affinity changes. Preserve the router data volume
alongside the gateway's checkpoint volume.

For maintenance, call `POST /drain` with `{"name":"r1","draining":true,"capacity":4}` and the
internal key. Draining excludes new assignments and refuses new turns on that runner. Existing
requests, checkpoint writes and file reads can finish. Wait for `/runners` to report `active=0`,
then stop and replace the runner while preserving its data volume and name. Resume with
`{"name":"r1","draining":false,"capacity":4}`. A capacity of zero is unlimited. Policies survive
router restarts. The active count covers proxied requests through completion of their response
stream, including checkpoints. Coordinate maintenance with the gateway so checkpointing has
finished before stopping a runner.

`GET /healthz` reports process liveness. `GET /readyz` returns 503 when all runners are unavailable
or draining. The container health check uses readiness.

| Variable | Default | Meaning |
|---|---|---|
| `HR_RUNNERS` | — | Static registry, `name=url,name=url`, read at every start |
| `HR_ROUTER_KEY` | unset | When set, every proxied and register call must carry `X-Harness-Internal` with this value (use the gateway's `HARNESS_INTERNAL_KEY`) |
| `HR_ROUTER_DB` | `./session-router.db` | SQLite file: dynamic registry + affinity table (the image sets `/data/session-router.db`) |
| `HR_HEALTH_INTERVAL_S` | `10` | Seconds between health sweeps |
| `HR_RUNNER_DEAD_S` | `45` | A runner whose last good check is older than this is dead and its sessions reassign |

## Router surface

- `GET /healthz` — `{"ok", "runners", "alive", "reassigned"}`
- `GET /runners` — every runner, alive/stale, its session count and last error
- `POST /register` `{"name", "url"}` — dynamic registration (409 for a static runner; 400 for
  a bad URL); requires `HR_ROUTER_KEY` when set
- `POST /deregister` `{"name"}` — leaves its affinity rows in place: a replaced container
  re-registers under the same name and keeps its sessions; one that never returns reassigns
  them at their next hydrate (environment management calls retain their own reassignment policy)
- everything else — proxied to the owner of `?identifier=`

## Kubernetes / Swarm note

The router is a plain stateless-ish Deployment/Service (state = one SQLite file on a volume).
Runners are just reachable pods; a rolling runner replacement is deregister + re-register (or
a new name — old sessions reassign on their next call after `HR_RUNNER_DEAD_S`).

## Tests

```bash
pip install -r requirements.txt
python -m pytest test_router.py -q
```
