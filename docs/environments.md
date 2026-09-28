# Environments

A project's files and its installed dependencies, built once and read by every task session that
names it. This is the design of record for the self-hosted server (shipped in 0.26) and for the
hosted service (to be built to the same contract); the wire contract is the
[Environments chapter](../protocol/versions/2026-09-28/environments.md) of UHP `2026-09-28`.

## The problem it solves

A session's working directory is made for one conversation. It starts empty, is checkpointed after
every turn as a tarball with dependency directories excluded, and is restored before the next turn.
Everything a task needs is uploaded into it, and everything it installs is reinstalled the next
time. For a task that is a project, a content pipeline with scripts, assets, templates and a hundred
packages, opened by several people many times a day, that is the wrong shape (Spiral, SPI-001 to
SPI-004): every session paid the upload and the install again, and two sessions could not share
one copy.

## The contract a session sees

```
/env/content-studio            the environment: complete, READ-ONLY, shared by every session
  scripts/ assets/ data/ …     the project's files, as the owner put them in
  .venv/  node_modules/        installed once, when the environment was built
/data/workspaces/<sid>         the session's working directory: writable, private, checkpointed,
                               the only place artifacts come from (unchanged)
PROJECT_ROOT=/env/content-studio
PATH=/env/content-studio/.venv/bin:/env/content-studio/node_modules/.bin:…
PYTHONPATH=/env/content-studio   NODE_PATH=/env/content-studio/node_modules:…
```

The agent's instruction file carries a "Project environment" section (runner/environments.py,
`doc_section`): where the project is, that it is read-only and shared, that its dependencies are
installed, to write outputs to the working directory, to run scripts by absolute path, and the
owner's `entry` line when there is one. Richard's decision (2026-09-28): a fixed read-only path
with a private cwd, not a copy-on-write working directory inside the project; the reasons are in
the chapter's first note.

## Objects and operations

An environment (`henv_…`) belongs to an org and a workspace, like a harness. It has a **source**
(the files the owner edits: upload one by one, import an archive or a git repository, edit in the
console), **versions** (builds: the source copied, then `.venv` / `node_modules` installed from
`requirements.txt` / `pyproject.toml` / `package.json`, then `setup.sh`, then the tree made
read-only), and one **active** version, the one sessions read. A build that succeeds becomes
active; a failed one changes nothing; rollback is a pointer to an earlier build. A harness names
the environment its tasks read; a task can name another. A task on an environment with nothing
built is refused before it starts (`environment_not_ready`).

Routes: `/v1/environments`, `…/{id}`, `…/{id}/files[/{path}]`, `…/{id}/import`, `…/{id}/build`,
`…/{id}/builds/{n}`, `…/{id}/versions[/{n}/activate]`, `…/{id}/harnesses`; `environment` on the
harness object and on `POST /v1/responses`; `environment` on the session object.

## Self-hosted implementation (this repository)

- **Record**: the gateway (`gateway/app.py`, "Environments" section): an `Environment` vertex
  with org, workspace, name, slug, description, entry, status, active/latest version, the
  versions list and the active build's packages, refreshed from the runner on reads.
- **Bytes**: the runner (`runner/environments.py`) owns `/data/environments/<id>/`:
  `source/` (editable), `versions/<n>/` (a build, root-owned, `a+rX`, with `.hr-build.json`:
  status, log, packages, size), `active` → `versions/<n>`. The mount `/env/<slug>` is a link to
  `active`, on the container's rootfs, remade lazily after a restart. Builds run in a thread of
  the runner with the image's own `python3` and `npm`, caches in a scratch directory, a wall clock
  of `HR_ENV_BUILD_TIMEOUT` (1800 s). Dependency directories in the source are never copied.
- **Read-only**: the write-wall (`HR_SESSION_UIDS`): an agent runs as its session's uid, the layer
  is root's, `chmod 755/644`, so a write fails with EACCES. Without the wall (a development box)
  the permissions still hold for any non-root agent; root is the operator's own choice.
- **The turn**: the gateway resolves the environment (request field, else the harness's) before
  anything is allocated, passes `{id, slug, entry}` to the runner, stamps the session vertex with
  `environment` and the turn record with the version. The runner resolves the mount before writing
  the agent doc (a 409 there fails the turn before any process starts), then sets the variables.
- **Checkpoints** are unchanged: the environment is outside the workspace, so it is never in one.

## How the hosted service implements it

Reviewed with the hosted session on 2026-09-28; the corrections are theirs. The hosted service runs
one session per Azure Container Apps dynamic session out of the custom-container pool
(`harness-sessions-e2`: 1 vCPU, 2 GiB, about 4 GiB of ephemeral disk, a 1800 s cooldown after
which the container is recycled). There is no pool host to keep a cache on, no volume and no bind
mount a session can be given, and nothing in a sandbox may hold a blob credential. The same
contract is built like this:

1. **Record.** The same `Environment` vertex on the HR tenant, registered with the seed script
   (label and edges) before the gateway that writes it rolls, as the billing labels were: a write
   before the seed 400s. Same routes, same object, `mount` stays `/env/<slug>`.
2. **Source.** One blob per file (`environments/<id>/source/<path>`) plus a small index blob with
   the tree, so the console's editor reads and writes one file at a time. A build materialises
   `environments/<id>/versions/<n>/source.tgz` from them first, so the build's input is one
   immutable object: reproducible, one download.
3. **Build = a sandbox job, never a gateway thread.** A gateway replica has no toolchain, no disk
   and may restart. The build takes a sandbox from the pool under the identifier `env-<id>-<n>`
   (no colons; the charset is the pool's), the policy gate runs BEFORE the sandbox is allocated
   (deficit and plan refusals; a build counts as a task for the Free plan's concurrency), and the
   "one build at a time per environment" lock and the build's status live in the control store as
   a lease with a TTL, swept by the straggler sweep, exactly as turns are, so a replica restart
   orphans nothing. Inside the sandbox the same `runner/environments.py::_build` runs (the one
   function both sides call), with `source.tgz` as its input and a 1800 s wall clock. The build is
   metered as agent work under the org, with its own receipt line ("Environment build",
   `agent.active_second`, the per-task cost cap applied), not a new ledger unit.
4. **Blob access is the gateway's, in one shape.** The sandbox never sees the account key. For the
   layer, the gateway mints a per-blob, minutes-lived SAS (write-only for the build's output,
   read-only for a turn's input) and hands it in the build or turn body, so a layer of a few
   hundred MB does not pass through a gateway replica that has no disk. The build writes
   `layer.tgz` (zstd) and `.hr-build.json` (status, log, packages, sizes) with its write SAS; a
   turn's hydrate downloads `layer.tgz` with its read SAS. The source files and index are written
   only by the API (the gateway streams them itself, as it streams checkpoints).
5. **The mount = extract at hydrate.** This IS the hosted design, not a first slice: when a turn
   names an environment, `/hydrate` downloads the active version's `layer.tgz` and extracts it to
   `/env/<slug>` once per session lifetime (the container lives until the cooldown recycles it, so
   later turns of the session find it in place), root-owned with 755/644 as extracted, no
   `chmod -R` pass; the agent runs as the image's agent uid (10001), which is the same wall the
   self-hosted server uses. The turn record carries `env_hydrate_ms` so the cost is visible. If
   sharing a layer across sessions is ever needed, the ACA-native shape is a session pool whose
   image bakes the layer, a different product decision; a bind mount is not promised.
6. **Isolation.** The container is the boundary: one session cannot see another's container at
   all; the layer is root's and the agent is not; the source and the layers are written only by
   the API and the build's write SAS.
7. **Versions, rollback, retention.** `active_version` on the vertex is the pointer; the gateway
   passes `version` in the turn body so a hydrate is deterministic, and stamps the session with
   the version it started on, which later turns of that session keep. The active version plus the
   last three are kept; an environment's blobs are deleted with it; layers are counted in
   `/internal/storage-usage`.
8. **Sizes.** The ephemeral disk also holds the workspace, so the layer cap is a fraction of it, per
   plan, enforced at build time from the recorded size: a layer over the cap fails the build with
   the size in the log. Import 512 MiB and file 64 MiB stay the env-tunable caps; measure the disk
   with `df` in a session before writing the number into a plan.

## What is not in this slice

- Environment-level system packages (apt): the image provides `ffmpeg`, LibreOffice, Playwright;
  a project that needs more says so in `setup.sh`, which runs with the build's privileges.
- Cross-workspace sharing beyond the org's workspaces; a marketplace of environments.
- Controlled updates from inside a session (SPI-006): a session cannot write the environment; a
  "promote these files to the next version" flow is a later design with review and versioning.
