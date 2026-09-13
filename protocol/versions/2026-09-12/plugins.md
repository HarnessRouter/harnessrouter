# Plugins

**Unified Harness Protocol, version `2026-09-12`**

A harness carries the tools and skills its agent can use ([Harnesses §4](harnesses.md#4-tools-and-skills)).
Until this version they could only be attached one at a time, to one harness. An operator who wanted
the same three MCP servers and two skills on a second harness, or in a different product, entered
them again. A **plugin** is those same components carried as one named, versioned package that
installs into any harness on any UHP server, and into any other client that reads the same package
format.

This chapter is the Harness Plugins sub-protocol. It is optional: a server advertises it with the
`plugins` capability, and a server that does not implement it is conformant at every class.

## 1. What a plugin is

UHP does not define a package format. A UHP plugin **is** an
[Agent Plugins](https://agent-plugins.org/specification) package, version 1.0.0: a folder with a
`plugin.json` manifest at its root, MCP servers declared in `mcp.json`, and skills under `skills/`,
each skill an [Agent Skills](https://agentskills.io/specification) folder with a `SKILL.md`.

Agent Plugins wraps Agent Skills without redefining them: it says where a skill lives inside the
package and defers the skill's own format to the Agent Skills specification. This chapter does the
same one layer up. It says how a package travels over UHP, how it is bound to a harness, and what a
hosted server owes it. Everything about the package's contents defers to Agent Plugins.

```
Agent Skills     SKILL.md and its folder               what one skill is
Agent Plugins    plugin.json + mcp.json + skills/      how skills and tools are packaged
UHP Plugins      this chapter                          how a package is installed into a hosted harness
```

A plugin carries three things, and the harness object already had a place for two of them:

| Part | Where in the package | What it becomes in the harness |
|---|---|---|
| Meta | `plugin.json` | The plugin's identity: `name`, `version`, `author`, `license`, … |
| Tools | `mcp.json` | MCP servers of the harness ([Harnesses §4.1](harnesses.md#41-mcp-servers)) |
| Skills | `skills/<name>/SKILL.md` | Skills of the harness ([Harnesses §4.2](harnesses.md#42-skills)) |

> **Why adopt a format rather than define one?**
> A package format is worth exactly the number of places it installs. Agent Plugins is maintained
> by a steering committee drawn from the major agent clients, so a plugin written for one of them
> installs into a UHP harness unchanged, and a plugin exported from a UHP harness ([§5](#5-exporting-a-harness-as-a-plugin))
> installs into them. A UHP-specific format would need converting at every boundary, and the
> conversion is where contents get lost.

## 2. The plugin object

```json
{
  "name": "contract-review",
  "enabled": true,
  "manifest": {
    "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
    "name": "contract-review",
    "version": "1.2.0",
    "description": "Clause extraction and a risk checklist for commercial agreements.",
    "author": { "name": "Example Legal Tools" },
    "license": "MIT"
  },
  "mcpServers": [
    { "name": "clauses", "transport": "http", "url": "https://mcp.example.com/clauses", "enabled": true },
    { "name": "redline", "transport": "stdio", "command": "./bin/redline",
      "args": ["--data", "${PLUGIN_DATA}"], "enabled": true }
  ],
  "skills": [
    { "name": "risk-checklist", "description": "Turn an agreement into a JSON risk checklist." }
  ],
  "skipped": [],
  "files": [
    { "path": "plugin.json", "content": "{ … }" },
    { "path": "mcp.json", "content": "{ … }" },
    { "path": "skills/risk-checklist/SKILL.md", "content": "---\nname: risk-checklist\n…" },
    { "path": "skills/risk-checklist/references/clauses.md", "content": "…" },
    { "path": "bin/redline", "content_b64": "f0VMRgIB…" }
  ]
}
```

| Field | Type | Written by | Meaning |
|---|---|---|---|
| `name` | string | either | The manifest's `name`; unique among the harness's plugins |
| `enabled` | boolean | client | Absent or `true` means installed and active |
| `files` | array | client | The package, as files relative to the plugin root |
| `blob` | string | server | Handle for a package the server stores out of line |
| `manifest` | object | server | `plugin.json`, parsed |
| `mcpServers` | array | server | The servers `mcp.json` declares, as plugin MCP server objects (`PluginMcpServer`) |
| `skills` | array | server | The skills found under `skills/`: `name` and `description` each |
| `skipped` | array | server | Components the server found and could not load, each with the reason |

The server-written fields are derived from the package on every write. A client MAY send them back
unchanged, which is what a client does when it `PUT`s what it read, and the server MUST recompute
them rather than store what was sent. A client MUST NOT rely on changing them: editing `mcpServers`
on a plugin changes nothing, because the package is the source and `mcp.json` is where the servers
are.

### 2.1 Files

The rules are the ones skills already follow ([Harnesses §4.2](harnesses.md#42-skills)):

- `files[].path` is relative to the plugin root and MUST support nested directories. A server MUST
  reject a path that escapes the root, or that names anything other than a regular file, with
  `plugin_invalid`.
- Text travels in `content`; binary in `content_b64`. A server MUST preserve both byte-for-byte.
- The package MUST contain `plugin.json` at its root. A server MUST reject one that does not, at
  configuration time rather than at run time.
- A server MUST materialise the **whole package** where the agent can read it. A plugin's skills
  carry references and scripts, and its stdio servers carry the executables they launch.
- A server MAY store the package out of line and return `blob` in place of `files`. It MUST then
  return the complete file list from
  `GET /v1/harnesses/{harness_id}/plugins/{plugin_name}/files` ([§3.1](#31-reading-the-files)).
- A server SHOULD cap package size, and MUST refuse an oversized one with `file_too_large`
  (`detail.max_bytes` states the limit) rather than truncating it.

### 2.2 What the server derives

On every write the server reads the package as an Agent Plugins client would, and records what it
found on the object.

**`manifest`.** The server MUST validate `plugin.json` against the rules of Agent Plugins §5 for the
version its `$schema` names. A `$schema` the server does not support is refused with
`unsupported_plugin_schema`; `detail.supported` lists the identifiers it does support. An unknown
top-level field, or a non-object `extensions`, is not fatal: the field is ignored and recorded in
`skipped`. Any other violation is fatal, and the write is refused with `plugin_invalid`.

**`mcpServers`.** From `mcp.json`, read as Agent Plugins §7.2 says. Each valid server entry becomes
one plugin MCP server object, mapped as follows. An invalid entry is recorded in `skipped` and the
rest still load. If `mcp.json` itself is invalid, or its `$schema` names a different Agent Plugins
version than `plugin.json`, every server in it is skipped with that reason.

| `mcp.json` `type` | UHP `transport` | Fields carried |
|---|---|---|
| `streamable-http` | `http` | `url`, `headers` |
| `sse` | `sse` | `url`, `headers` |
| `stdio` | `stdio` | `command`, `args`, `env`, `cwd` |

`${PLUGIN_ROOT}` and `${PLUGIN_DATA}` are reported exactly as written. A server MUST NOT expand them
in what it returns to a client: the expansion is a filesystem path inside the server's sandbox, which
is not the client's business and changes from turn to turn. `enabled` on each derived server is
always `true`; the plugin's own `enabled` is what turns them off, together.

A plugin MCP server object is the harness MCP server object of
[Harnesses §4.1](harnesses.md#41-mcp-servers) plus the `stdio` transport, with `command`, `args`,
`env` and `cwd` in place of `url`, `headers` and `auth`. `command` is one executable token, never a
shell string: a bare name, or a plugin-relative path beginning with `./`.

> **Why is `stdio` declared only inside a plugin?**
> A process needs somewhere to run from and somewhere to keep state, and a plugin is the object
> that provides both: `PLUGIN_ROOT` and `PLUGIN_DATA` are defined by the package, not by the
> harness. A stdio server on the harness's own list would need a second set of rules for a root
> it does not have, and it could not be exported, because its executable would not travel with
> it. So the harness's own list stays what it was in the previous version, remote servers only,
> and a process is two files away: a `plugin.json` and an `mcp.json` make a complete plugin. That
> keeps every object the previous version defined byte-for-byte unchanged, which is what lets a
> server serve both versions from one code path ([§4.1](#41-the-direct-fields-are-unchanged)).

**`skills`.** Each immediate child directory of `skills/` that contains a regular file named
`SKILL.md` is one skill, per Agent Plugins §7.1. A server MUST NOT search deeper. Each skill MUST
conform to Agent Skills, including the rule that its frontmatter `name` equals its directory name; a
skill that does not is recorded in `skipped` and the rest still load. The derived entry carries the
frontmatter `name` and `description`.

**`skipped`.** Each entry is `{ "path": …, "reason": … }`, where `path` locates the component in
the package (`skills/broken`, `mcp.json#/mcpServers/redline`, `plugin.json#/vendorField`) and
`reason` is one sentence. A server MUST return `skipped` on every plugin object, empty when nothing
was skipped, so a client can tell "nothing skipped" from "server does not report skips".

> **Why is a broken component recorded rather than refused?**
> Two rules meet here. [Harnesses §4.2](harnesses.md#42-skills) refuses a skill without a
> `SKILL.md` at configuration time, because a bundle that is stored and then silently ignored at
> run time is the hardest failure a user can be handed. Agent Plugins §11.3 requires the opposite
> inside a package: a failure isolated to one component MUST NOT stop the rest from loading,
> because a package is written by someone other than the person installing it, and one stale entry
> should not take the whole plugin down with it. Both are right about their own case. The
> reconciliation is the one [Tasks §1.1](tasks.md#11-request-fields) already makes for reserved
> fields: ignoring is allowed, silent ignoring is not. The package installs, and what did not load
> is written on the object, where the person configuring the harness can see it. The manifest is
> the exception. Without a valid manifest there is no plugin to isolate failures within, so a fatal
> manifest error refuses the write.

## 3. Installing a plugin

Plugins are part of the harness object and are set the way its other configuration is set
([Harnesses §5](harnesses.md#5-managing-harnesses)): conformance class **Full**, and the `plugins`
capability MUST be `true`.

```http
POST /v1/harnesses
```

```json
{
  "name": "Contract Review Agent",
  "base": "claude-code",
  "plugins": [
    { "files": [
        { "path": "plugin.json", "content": "{\"$schema\":\"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json\",\"name\":\"contract-review\"}" },
        { "path": "skills/risk-checklist/SKILL.md", "content": "---\nname: risk-checklist\ndescription: …\n---\n…" }
    ] }
  ]
}
```

- `name` on the write is OPTIONAL. If present it MUST equal the manifest's `name`; otherwise the
  write is refused with `plugin_invalid`. The manifest is the source of the name, so that a plugin
  renamed on install is still the plugin its author published.
- Two plugins with the same `name` in one harness MUST be refused with `plugin_conflict`.
- A refused write MUST leave the harness unchanged. A plugin is installed whole or not at all.
- `PUT /v1/harnesses/{harness_id}` replaces `plugins` as it replaces every other mutable field.
  Round-tripping a harness through `GET` and `PUT` MUST NOT lose package contents; a client that
  sends back `{ "name": "contract-review", "blob": "…" }` keeps the package it read.
- `enabled: false` keeps the plugin installed and inert. Nothing in it is materialised, and none of
  its MCP servers is contacted ([Harnesses §4.1](harnesses.md#41-mcp-servers)).

### 3.1 Reading the files

```http
GET /v1/harnesses/{harness_id}/plugins/{plugin_name}/files
```

```json
{ "files": [ { "path": "plugin.json", "content": "…" }, { "path": "bin/redline", "content_b64": "…" } ] }
```

The complete package, byte-for-byte, whether or not the server stores it out of line. `404` with
`plugin_not_found` when the harness has no plugin of that name.

## 4. Composition: what the agent gets

A harness's **effective configuration** is what its agent runs with. A server computes it from the
harness object for every turn:

- the effective MCP servers are the harness's enabled `mcpServers`, plus the `mcpServers` of every
  enabled plugin;
- the effective skills are the harness's enabled `skills`, plus the `skills` of every enabled plugin;
- `disabledTools` applies to all of them alike.

### 4.1 The direct fields are unchanged

`mcpServers` and `skills` on the harness keep exactly the meaning they had in the previous version.
They report what a client wrote there and nothing else. A plugin's components are reported on the
plugin and are never copied into the direct fields.

A harness with no plugins is what it was before this version, with `plugins` an empty array. Every
harness that exists today is a valid harness under this version, and every client written against
the previous version keeps working, by the client rules in [Versioning](../../VERSIONING.md): it
ignores `plugins` and sees a harness with fewer tools than the agent actually has, which is already
what it sees for tools the base provides on its own.

The converse holds too. Nothing this version defines changes the shape of an object the previous
version defined, so a server that implements plugins serves both versions from one code path: it
lists both in `versions`, answers a `2026-08-11` request with the same objects, and the `plugins`
field is simply one more field that version's clients ignore. A server that has not implemented
plugins keeps serving `2026-08-11`, reports the `plugins` capability `false`, and is conformant
at every class under this version's suite; the plugin checks skip, and a skip is never a pass.

> **Why not report the effective set in `mcpServers`?**
> Because of the round trip. A client that reads a harness and `PUT`s it back after an unrelated
> edit is the case [Harnesses §4.2](harnesses.md#42-skills) is designed around. If `mcpServers`
> carried plugin-derived servers, that `PUT` would write them into the direct list, and the harness
> would then carry every plugin server twice: once from the plugin and once as its own. Uninstalling
> the plugin would leave its servers behind. So the direct fields report what was written to them,
> and a client that wants the effective set takes the union, which this section makes a one-line
> computation with no server-specific rules in it.

### 4.2 One namespace, checked at configuration time

Within a harness, MCP server names MUST be unique across the direct list and every enabled plugin,
and skill names likewise. A write that would create a collision MUST be refused with `409` and
`plugin_conflict`; `detail.component` is `mcp_server` or `skill`, `detail.name` is the colliding
name, and `detail.between` names the two owners, each either `harness` or a plugin name.

> **Why refuse rather than prefix?**
> The agent sees one flat namespace: one MCP configuration, one skills directory. Whether a server
> could prefix a plugin's components with the plugin's name depends on the harness base, and for
> skills it cannot: Agent Skills requires a skill's `name` to equal its directory name, so renaming
> the directory breaks the skill. A rule the protocol cannot keep on every base is not a rule. So
> the ambiguity is refused at configuration time, where a person is present to resolve it, rather
> than resolved silently at run time, where nobody is. Disabling either side clears the conflict.

### 4.3 The direct fields are a plugin without a name

The direct `mcpServers` and `skills` of a harness are exactly the contents of a plugin: tools and
skills, with the harness standing in for the manifest. This is not an analogy. [§5](#5-exporting-a-harness-as-a-plugin)
makes it an operation.

## 5. Exporting a harness as a plugin

```http
GET /v1/harnesses/{harness_id}/plugin
```

Returns a plugin object whose `files` are an Agent Plugins package built from the harness's direct
configuration. The result installs into another harness by passing it to `plugins` unchanged, or
into any other Agent Plugins client by writing its files to disk.

| In the package | Built from |
|---|---|
| `plugin.json` | `$schema` for Agent Plugins 1.0.0 and `name` derived from the harness `name` |
| `mcp.json` | The enabled direct `mcpServers`; `http` becomes `streamable-http`, `sse` stays `sse` |
| `skills/<name>/…` | Each enabled direct skill, the whole folder |

- The derived `name` is the harness `name` lower-cased, with every run of characters outside
  `a-z`, `0-9` and `.` replaced by one `-`, leading and trailing `-` removed, and `..` collapsed to
  `.`. If nothing remains, the harness `id` is used the same way. The result satisfies Agent Plugins
  §5.5 by construction.
- `auth` and `headers` MUST be omitted from every server in `mcp.json`. They are credentials the
  operator entered for this harness, and a package travels. Each omission is recorded in
  `skipped`, with the server's path in `mcp.json`, so the person exporting knows what to re-enter.
- Installed plugins are not included. A plugin does not contain plugins; a client that wants one of
  them reads its files ([§3.1](#31-reading-the-files)).
- `systemPrompt`, `defaultModel`, `disabledTools` and `base` are not included. They describe the
  harness, not its tools and skills, and Agent Plugins has no portable place for them.
- A harness with nothing to export still returns a valid package: a manifest and nothing else.

## 6. Running with plugins

What a hosted server owes an installed, enabled plugin at run time:

- **Skills** are materialised as [Harnesses §4.2](harnesses.md#42-skills) requires: the whole folder,
  where the agent reads skills.
- **Remote MCP servers** (`http`, `sse`) are connected as [Harnesses §4.1](harnesses.md#41-mcp-servers)
  requires. Placeholder expansion MUST NOT be performed in `url` or `headers`.
- **stdio MCP servers** run inside the same sandbox as the agent, with the same privileges, and never
  anywhere else. A server MUST set `PLUGIN_ROOT` and `PLUGIN_DATA` in the subprocess environment,
  MUST expand `${PLUGIN_ROOT}` and `${PLUGIN_DATA}` in `args`, `env` and `cwd`, MUST NOT expand
  anything else, and MUST resolve `command` as Agent Plugins §7.2.1 says: a bare executable name, or
  a plugin-relative path beginning with `./`, with no expansion in `command` itself. The default
  working directory is the plugin root. The containment rules of Agent Plugins §4.1 apply: a
  `command` or `cwd` that resolves outside the plugin root (or, for `cwd`, outside `PLUGIN_DATA`)
  is an invalid entry.
- **`PLUGIN_DATA`** MUST exist and be writable before the first subprocess launches, and MUST persist
  for the life of the session ([Sessions](sessions.md)), which is the unit of workspace persistence
  in UHP. A server MAY keep it longer. Agent Plugins asks for persistence across plugin updates; on
  a hosted server the session is the boundary a client can reason about, so it is the one promised.
- **A server that cannot run a transport for a base** MUST refuse the write with
  `unsupported_transport`, naming the transport and the base in `detail`, rather than accept the
  plugin and skip the server at run time. The rule of Harnesses §4.1 holds: a server MUST NOT
  advertise MCP support it cannot deliver.
- **An MCP server that fails** MUST NOT fail the task, exactly as for a directly attached one. A
  stdio server that exits is the same event as a remote one that refuses the connection.
- **A disabled plugin** is not materialised and nothing in it is contacted or launched.

## 7. Discovery

A server that implements this chapter reports it in the discovery document
([Lifecycle §2](lifecycle.md#2-capability-discovery)):

```json
{
  "capabilities": { "harness_management": true, "plugins": true },
  "plugin_schemas": ["https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"]
}
```

`plugin_schemas` lists the Agent Plugins manifest schema identifiers the server accepts, and MUST be
present and non-empty when `plugins` is `true`. A client MUST check both before offering to install
a package, and MUST NOT offer a package whose `$schema` the server does not list.

A server that reports `plugins: true` MUST accept `plugins` on harness create and update, MUST serve
the files endpoint ([§3.1](#31-reading-the-files)), and MUST serve the export
([§5](#5-exporting-a-harness-as-a-plugin)). There is no partial form of the capability.

## 8. Relationship to Agent Plugins conformance

A UHP server with `plugins: true` is an Agent Plugins *client* in that specification's terms
(§11): it loads a package from a directory, validates the closed manifest, discovers both component
types from their fixed locations, and, when it launches subprocesses, provides the two environment
variables and expands them. This chapter adds to that, and never subtracts:

- what Agent Plugins §11.3 says a client SHOULD report, this chapter says a server MUST report, on
  the object, as `skipped`;
- placeholders are returned to clients unexpanded;
- `PLUGIN_DATA` persistence is promised for the life of a session;
- component names are unique within a harness, and a collision is refused at configuration time.

Agent Plugins itself is versioned by its schema identifiers (§10.1). A later Agent Plugins version
appears in UHP as a new entry in `plugin_schemas`, which is an additive change to a server and needs
no new UHP version.
