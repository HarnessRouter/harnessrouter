# Environments

**Unified Harness Protocol, version `2026-10-04`**

A session's working directory ([Architecture §3](architecture.md#3-object-model)) is made for one
conversation: it is created empty, kept across turns, and everything the agent needs is put there
again for every session that needs it. That is the right shape for a task's own files and the wrong
shape for a project: a content pipeline with its scripts, assets, templates and a hundred installed
packages, opened by many people, many times a day. Installed into a working directory it is
installed once per session, uploaded once per session, and a session's checkpoint carries none of
it forward.

An **environment** is that project as one object: its files and its installed dependencies, built
once, and read by every session that names it. A session sees it at a fixed path, read-only, beside
its own working directory, which stays writable, private, and the only place artifacts come from.

This chapter is the Environments sub-protocol. It is optional: a server advertises it with the
`environments` capability, and a server that does not implement it is conformant at every class.

## 1. What an environment is

```
/env/content-studio          the environment: complete, read-only, shared     (this chapter)
  scripts/  assets/  data/   the project's files, as the owner put them in
  .venv/  node_modules/      its dependencies, installed once when it was built
<working directory>          the session's own: writable, private, checkpointed   (Files chapter)
```

Three rules make it one thing rather than a shared folder:

- **It is built, not copied.** The owner puts files in ([§3](#3-files)); a build ([§4](#4-builds-and-versions))
  snapshots them into a version and installs what the project's manifests declare, in the server's
  own toolchain. Dependency directories that arrive with the files are not what a session gets;
  what the build installed is. A virtualenv made on a laptop does not run in a container, and the
  build is what makes the promise "no reinstall" true.
- **A session reads the active version and cannot write it.** Two sessions on one environment share
  every byte of it and none of each other's working directory. A server MUST refuse writes into the
  environment from a session: the path is read-only, not merely described as such.
- **The path is fixed.** The server tells the client where the environment is mounted (`mount`) and
  tells the agent the same, so a project's scripts can be run by absolute path from any working
  directory, and their outputs land where the user sees them.

> **Why not let the session start inside the project?**
> A working directory that *is* the project, copy-on-write, reads well until two facts collide:
> artifacts and project files are then the same directory, so the server can no longer say which
> files a task produced, and every write must be layered by a mechanism (overlay filesystems,
> per-session copies) that not every sandbox has. Two paths, one of them read-only, keeps both
> answers simple: what the task produced is in the working directory, what the project is stays in
> the environment.

## 2. The environment object

```json
{
  "id": "henv_2f1c9d4e8a7b4c3d9e6f5a4b3c2d1e0f",
  "object": "environment",
  "name": "Content Studio",
  "slug": "content-studio",
  "description": "The teaser pipeline: episodes in, teasers and thumbnails out.",
  "entry": "python3 run.py --episode <id>",
  "status": "ready",
  "mount": "/env/content-studio",
  "version": 3,
  "latestVersion": 3,
  "files": { "count": 16, "bytes": 48213 },
  "packages": [ { "manager": "pip", "name": "moviepy", "version": "2.1.1" },
                { "manager": "npm", "name": "sharp", "version": "0.33.5" } ],
  "versions": [ { "version": 3, "status": "ready", "started_at": 1790570000, "finished_at": 1790570094, "packages": 10 } ],
  "build": { "version": 3, "status": "ready", "started_at": 1790570000, "finished_at": 1790570094, "error": "" },
  "createdAt": 1790560000000,
  "updatedAt": 1790570094000
}
```

| Field | Type | Written by | Meaning |
|---|---|---|---|
| `id` | string | server | `henv_`-prefixed ([Architecture §3](architecture.md#3-object-model)) |
| `name` | string | client | Human-readable; must begin with a letter or digit |
| `slug` | string | server | The path segment sessions see, derived from the name at creation. It never changes: a session's instructions name it |
| `description` | string | client | |
| `entry` | string | client | How the project is run, in the owner's words. Repeated to the agent verbatim ([§6](#6-what-a-session-sees)) |
| `status` | string | server | `empty` (nothing built), `building` (a build is running, whichever version is active: a task keeps reading the active one), `ready` (a version is active), `failed` (the latest build failed and none is active) |
| `mount` | string | server | Where a session finds it, read-only. `/env/<slug>` on the reference server; a server MAY choose another root, and MUST keep it constant for the environment's lifetime |
| `version` | integer or null | server | The active build, the one sessions read |
| `latestVersion` | integer or null | server | The newest build, active or not |
| `files` | object | server | The source's size: what the owner put in, before any build |
| `packages` | array | server | What the active build installed, as the package managers report it: `manager`, `name`, `version` |
| `declared` | object | client | What the owner declared, per manager, as spec strings the build installs beside the project's manifests: `pip` (`moviepy==2.1.1`), `npm` (`sharp@0.33.5`), `apt` (`ffmpeg`); read back with each spec's `name` and `version` |
| `runtime` | object | client | `python`: the interpreter a build makes the virtual environment with, one of `GET /v1/environments/runtimes`; empty for the server's default |
| `versions` | array | server | Every build: `version`, `status`, times, `error`, size |
| `build` | object or null | server | The latest build's status, and its `stage` while it runs |

Environments are scoped like harnesses: a caller sees the environments of its own scope
([Architecture §5](architecture.md#5-authentication)), and a harness may name only an environment
of the same scope.

```http
POST   /v1/environments                     create (name, description, entry)
GET    /v1/environments                     list
GET    /v1/environments/{id}                one, with its versions
PUT    /v1/environments/{id}                rename; description; entry
DELETE /v1/environments/{id}                delete every version
```

`POST` refuses a name that yields no path segment with `environment_invalid`, and a slug another
environment already occupies with `environment_exists`: the mount path is a place, and two
environments cannot be in it. `DELETE` refuses while a build runs (`environment_busy`). A harness
that named a deleted environment keeps the reference; its next task is refused with
`environment_not_found` ([§5](#5-attaching-an-environment)).

## 3. Files

The source is edited by path, the way a plugin's package is ([Plugins §2.1](plugins.md#21-files)),
but one file per request, because a project is larger than a package:

```http
GET    /v1/environments/{id}/files                 the tree: every file and directory, with sizes
GET    /v1/environments/{id}/files/{path}          one file's bytes, with its content type
PUT    /v1/environments/{id}/files/{path}          write one file (the body is its bytes; its directories are made)
POST   /v1/environments/{id}/directories           make an empty directory: {"path": "assets/brand"}
DELETE /v1/environments/{id}/files/{path}          remove a file or a directory tree
POST   /v1/environments/{id}/import                a whole project at once
```

- `path` is relative to the environment's root. A server MUST refuse a path that escapes the root,
  or names anything other than a regular file or directory, with `environment_invalid`.
- A server MUST preserve bytes as sent, and MUST refuse an oversized file with `file_too_large`
  (`detail.max_bytes` states the limit) rather than truncating it.
- Writing the source changes nothing a session sees until the next build ([§4](#4-builds-and-versions)).

### 3.1 Import

A project arrives as one thing. `POST /v1/environments/{id}/import` takes either an archive (a zip
or a tar, as the request body with any content type but `application/json`) or a JSON body naming
a git repository:

```json
{ "git": { "url": "https://github.com/example/content-studio", "ref": "main" }, "replace": true }
```

The tree is kept as it is in the archive or repository. A single directory wrapping everything (the
shape of a repository archive) is stripped, so the project's root is the environment's root.
Members that must not land, links and paths that escape the root, are dropped and counted in
`skipped`, never written. `replace` clears the source first; without it the import lands over what
is there. Dependency directories in an archive (`node_modules`, `.venv`) are not copied into a
build; the build installs from the manifests ([§4](#4-builds-and-versions)).

## 4. Builds and versions

```http
GET  /v1/environments/runtimes                          what a build can be made with here: Python minors, Node major, the OS
GET  /v1/environments/packages/check?manager=&spec=     what the manager's registry says about a spec, before any build (MAY)
POST /v1/environments/{id}/build                        start a build: the next version
GET  /v1/environments/{id}/builds/{version}             its record: status, log, packages, size
GET  /v1/environments/{id}/versions                     every build, and which one is active
POST /v1/environments/{id}/versions/{version}/activate  make a finished build the active one
```

A build snapshots the source into a new version and installs what the project declares:

| Manifest at the root | What the build runs |
|---|---|
| declared `pip` | the same virtual environment (made with `runtime.python` when the server has it), then `pip install` of each spec |
| declared `npm` | `npm install` of each spec into `node_modules` |
| declared `apt` | the named packages and the dependencies the image lacks, downloaded by apt and unpacked with dpkg under `apt/` in the version, which a session gets on `PATH` and `LD_LIBRARY_PATH`; nothing is installed into the server |
| `requirements.txt` | a Python virtual environment at `.venv`, then `pip install -r requirements.txt` |
| `pyproject.toml` | the same virtual environment, then `pip install .` |
| `package.json` | `npm ci` when a lockfile is present, else `npm install`, into `node_modules` |
| `setup.sh` | run last, in the version's directory, for what the manifests cannot say |

A server MAY support other manifests and MUST document which it runs. Installs happen in the
server's own toolchain, the one sessions run in, so what the build installed runs where the
session runs. Nothing else is written into the version after the build: the layer is made
read-only and stays so.

`POST …/build` returns at once with the version number; the record at `…/builds/{version}` says
`building`, then `ready` or `failed`, with the installers' own output as `log` and the failure's
reason as `error`. While it builds, the record says which step is running as `stage` (on the
reference server: `copying files`, `python packages`, `node packages`, `system packages`,
`setup.sh`, `finishing`) and carries the log so far, so a client can show progress rather than a
spinner; a server MUST write the record as steps end, not only at the end of the build. The
environment's `status` is `building` meanwhile, even when a version is active, and a task on it
keeps reading the active version. One build runs at a time per environment (`environment_busy`).
When a build
succeeds it becomes the active version: the next session to start reads it. A session that started
earlier keeps the version it started with for the rest of its turn; a server SHOULD let it keep
that version for later turns too, and MUST say which version a turn read ([§6](#6-what-a-session-sees)).

A failed build changes nothing: the previous active version stays active, and `status` says
`failed` only when no version is active at all. Rolling back is `POST …/versions/{n}/activate` on
an earlier finished build; nothing is rebuilt, and a version that never finished cannot be
activated (`environment_not_ready`).

A server MAY answer `GET /v1/environments/packages/check?manager=&spec=` with what the manager's
registry says about a spec before any build: whether the name exists, its latest version, and
whether an exact pin is published (`EnvironmentPackageCheck`: `manager`, `name`, `spec`, `exists`
true, false, or null when the registry could not be asked, `latest`, `version` for a published
pin, `error` in words). A client that offers it refuses a typo where it is typed instead of
failing a build minutes later; a client MUST NOT require it, and a server without it answers
`404`. The reference server asks PyPI, the npm registry, and its own apt lists.

> **Why versions rather than a rebuild in place?**
> A rebuild in place would change a layer that sessions are reading at that moment, and a
> failed one would leave them nothing. Versions make a build atomic from the session's side:
> the old layer is whole until the new one is, and the switch is one pointer.

## 5. Attaching an environment

A harness names the environment its tasks read, and a task may name a different one:

```json
{ "name": "Teaser cutter", "base": "codex", "environment": "henv_2f1c9d4e8a7b4c3d9e6f5a4b3c2d1e0f" }
```

```json
{ "input": "Render the teaser for episode 12.",
  "metadata": { "harness_id": "chrn_…", "environment": "henv_2f1c9d4e8a7b4c3d9e6f5a4b3c2d1e0f" } }
```

- `environment` on a harness ([Harnesses §2](harnesses.md#2-the-harness-object)) is the default
  for every task of that harness; `metadata.environment` on a task overrides it for that task.
  The response reports the environment the task read as `metadata.environment`, beside
  `metadata.session_id`.

> **Why is the task's environment in `metadata` rather than a top-level field?**
> For the reason the harness is ([Tasks §1.2](tasks.md#12-selecting-the-harness)): the task surface
> is a Responses request, and `metadata` is the extension point that surface defines for
> caller-supplied context. A harness and a session are this protocol's own objects, so on them
> `environment` is an ordinary field; a task request is not, so on it the environment travels
> where the harness does. Every Responses SDK can send it today.
- A server MUST refuse a harness write that names an environment outside the caller's scope, or
  none at all, with `environment_not_found`.
- A server MUST refuse a task whose environment is not `ready` **before the task starts**:
  `environment_not_found` for one that is not there, `environment_not_ready` for one with nothing
  built. A task that fails minutes later for want of its project is the outcome this rule exists
  to prevent.
- `GET /v1/environments/{id}/harnesses` lists the harnesses that name it, so an owner sees what a
  rebuild will reach.

## 6. What a session sees

For a task that runs with an environment, a server MUST:

1. mount the active version at `mount`, read-only, before the agent starts;
2. keep the session's working directory as it was: writable, private to the session, the source of
   its artifacts ([Files §2](files.md#2-getting-artifacts-out)), and unchanged in how it is
   checkpointed. The environment is never part of a checkpoint;
3. make the environment's installed dependencies the ones the agent's shell runs: on the reference
   server `PATH` begins with the version's `.venv/bin` and `node_modules/.bin`, `PYTHONPATH` and
   `NODE_PATH` begin with the environment, `PROJECT_ROOT` names `mount`;
4. tell the agent, in its instructions, where the project is, that it is read-only and shared, that
   its dependencies are installed, where to write, and the `entry` when the owner gave one;
5. record which environment and version the turn read: the response carries
   `metadata.environment`, the session object carries `environment`
   ([Sessions §3](sessions.md#3-inspecting-a-session)), and the turn's record the version.

Two sessions on one environment MUST NOT be able to read each other's working directory or write
the environment. A session MUST NOT be able to read an environment its task did not name, nor to
enumerate the environments a server holds. How a server enforces that is its own business: a
per-session container with a read-only mount, a per-session user and a per-environment group
without write permission on a shared directory, or a copy made read-only. What a client may rely
on is the outcome.

## 7. Discovery

```json
{ "capabilities": { "environments": true } }
```

A server that reports `environments: true` implements every endpoint in this chapter. One that
does not implement the chapter reports `false` or omits it, and MUST answer the endpoints with
`404`, never with a partial implementation.

## 8. Errors

| Code | Status | When |
|---|---|---|
| `environment_not_found` | 404 | No such environment in the caller's scope; on a harness write or a task, the referenced one |
| `environment_not_ready` | 409 | A task on an environment with no active version; activating a version that never finished |
| `environment_busy` | 409 | A build is running: a second build, or a delete |
| `environment_exists` | 409 | The name's slug is another environment's mount |
| `environment_invalid` | 422 | A name that is no path segment; a file path that escapes the root; an import that is neither archive nor repository |
| `environment_unavailable` | 502 or 503 | The server's build or storage backend did not answer |
| `file_too_large` | 413 | A file or an import over the server's limit ([Files §1](files.md#1-sending-files-in)) |

## 9. Security

- The build runs the project's own manifests and `setup.sh` with the server's toolchain and network.
  A server MUST run it with no more privilege than a task gets, and MUST NOT let it read another
  environment or any session. On a single-tenant self-hosted server the owner is the only author;
  a multi-tenant server treats a build as a task of the tenant that owns the environment.
- Read-only is enforced, not described ([§6](#6-what-a-session-sees)). An agent told not to write
  will still try; the write must fail.
- A file path is confined to the environment's root at every endpoint ([§3](#3-files)), and an
  imported archive's members are confined the same way: links out of the root and absolute paths
  are dropped, never followed.
- Environments are scoped with the harnesses that use them; a harness cannot name an environment
  of another scope ([§5](#5-attaching-an-environment)).
