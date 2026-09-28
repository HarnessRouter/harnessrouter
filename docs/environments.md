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

The hosted service runs one Hyper-V container per session out of a warm pool, restores the
workspace from a tarball in blob storage (`_hydrate`) and checkpoints it back (`_checkpoint`);
there is no shared filesystem between the gateway, the pool hosts and the sandboxes. The same
contract is built like this:

1. **Record**: the same `Environment` vertex on the HR tenant (register the label in the graph
   seed as `Harness` is). Same routes, same object; `mount` stays `/env/<slug>`.
2. **Source bytes**: blob storage, `environments/<id>/source/<path>` per file plus a small index
   blob with the tree, or one `source.tgz` rewritten on each write the way `CheckpointWorkspaceFiles`
   rewrites a checkpoint. Per-file blobs are simpler for the console's editor; the index makes the
   tree one read.
3. **Build**: a build is a sandbox job, not a gateway thread. The gateway takes a sandbox from the
   pool under the identifier `env:<id>:<n>`, streams the source into it, runs the same steps the
   self-hosted runner runs (`runner/environments.py::_build`, factored so both call one function),
   tars the finished version (`layer.tgz`, sizes recorded) into blob storage at
   `environments/<id>/versions/<n>/layer.tgz` with `.hr-build.json` beside it, and releases the
   sandbox. The build has the tenant's credentials and nothing else; it is billed as a task of the
   environment's org (a `build` unit on the ledger, priced by sandbox-seconds like a turn).
4. **The mount**: at `/hydrate`, when the turn names an environment, the runner in the sandbox
   fetches `layer.tgz` for the active version and extracts it to `/env/<slug>` before restoring the
   workspace, then `chmod -R a-w` it. That already meets the contract (no reinstall, read-only per
   sandbox, the outcome the chapter requires) and is the first slice. The second slice removes the
   copy: the pool host keeps `/var/cache/hr-env/<id>/<n>/` (fetched once per host, LRU by bytes)
   and starts the session's container with a read-only bind mount of it at `/env/<slug>`. Then a
   session starts in the time it takes to mount, and a hundred sessions on one host share one copy.
5. **Isolation**: the container is the boundary. One session cannot see another's container at
   all; the bind mount is read-only; the source and the layers in blob storage are written only by
   the gateway and the build job. Nothing in the sandbox holds a blob credential (the credential
   broker rule stands).
6. **Versions and rollback**: the vertex's `active_version` is the pointer; the runner reads it in
   the turn body (the gateway passes `version` too, so a hydrate is deterministic). A session that
   started on version 3 keeps 3 for later turns unless the gateway is told otherwise; the trace
   records the version per turn.
7. **Limits and metering**: import 512 MiB, file 64 MiB (the same env-tunable caps), a layer size
   cap per plan, and storage metered like checkpoints (`/internal/storage-usage`).

What the hosted twin must not do: build in the gateway's own process (it has no toolchain and no
disk), keep a layer inside a session's checkpoint (it would be excluded anyway), or let the source
be written from inside a sandbox (the only writers are the API and the build).

## What is not in this slice

- Environment-level system packages (apt): the image provides `ffmpeg`, LibreOffice, Playwright;
  a project that needs more says so in `setup.sh`, which runs with the build's privileges.
- Cross-workspace sharing beyond the org's workspaces; a marketplace of environments.
- Controlled updates from inside a session (SPI-006): a session cannot write the environment; a
  "promote these files to the next version" flow is a later design with review and versioning.
