# Pi Lab

Pi Lab (`pi-lab`) is a base and runner backend for harness experiments: Pi with
mechanisms that are switched on and off per harness, so a benchmark column can vary
one mechanism at a time against plain Pi. Its first four mechanisms come from
[NVIDIA SoL-Pi](https://github.com/NVlabs/SoL-Pi). Later mechanisms are added
beside them as further switches.

Pi Lab reuses Pi's provider transport but has its own pinned runtime,
configuration, extension entrypoint and session/skill directory. Existing `pi`
harnesses load none of this, so plain Pi stays the control arm.

## Installation

For the self-hosted container, include `pi-lab` in `HR_BACKENDS` (included in this
branch's default). On startup the installer places it in
`$TOOLS/pi-lab-runtime`, separately from ordinary Pi. The runtime uses Pi 0.85.1 and
[NVlabs/SoL-Pi commit 1559b5c](https://github.com/NVlabs/SoL-Pi/tree/1559b5cb12c72da4a485bc50fe326586b216fb19).
Both are MIT licensed. The normal Pi installation is not upgraded or replaced.
`docker/pi-lab/package-lock.json` locks the complete npm dependency graph, including
MCP adapter 2.37.0. Registry artifacts carry SHA-512 integrity; the upstream SoL-Pi
commit is fixed and its 23 extension source files are checked against
`docker/pi-lab/source.sha256`. The runtime is installed into a staging directory and
moved into place once it has passed that check; a later start with the same lockfile
and checksums reuses it. Isolated session users can read and run it, not write it.
The CI runtime job runs the same installer and CLI smoke test without a provider key.

For a separately managed runner, install the same dependencies and set:

```sh
export HR_PI_LAB_BIN=/opt/pi-lab/bin/pi
export HR_PI_LAB_SOL_PI_ENTRY=/opt/pi-lab/lib/node_modules/sol-pi/src/sol-pi/index.ts
export HR_PI_LAB_MCP_EXT=/opt/pi-lab/lib/node_modules/pi-mcp-adapter
```

The runner starts Pi Lab's own pinned `pi`, never the ordinary one on `PATH`.

## Create and configure

Choose **Pi Lab** to inspect the built-in defaults. Use **Fork and Customize** to
create an editable agent, then use **Mechanisms** in its settings.
Each switch is independent. All four default to enabled on this base;
explicit `false` disables a mechanism. Ordinary Pi has no mechanism settings.

The custom harness API accepts this implementation-specific extension:

```json
{
  "name": "Pi Lab experiment",
  "base": "pi-lab",
  "default_model": "deepseek-v4.1-flash",
  "pi_lab": {
    "actionFusion": true,
    "observationPack": true,
    "evidencePreservingReducer": true,
    "onlineContextCompact": true,
    "cacheWriteReadRatio": 12.5
  }
}
```

POST `/v1/harnesses` creates it; PUT `/v1/harnesses/{id}` updates it. Reads return
`piLab` alongside `base: "pi-lab"`. Task execution uses the returned harness id
as usual. A built-in `/pi-lab/v1/responses` run uses all four defaults; create a
custom agent to change them. This is a local implementation extension, not a UHP
standard change. The settings take effect on the next process/turn.

| Setting | Source | Effect |
| --- | --- | --- |
| `actionFusion` | SoL-Pi | Add `then_run` to `write` and `edit` |
| `observationPack` | SoL-Pi | Archive large observations and expose `obs_recall` |
| `evidencePreservingReducer` | SoL-Pi | Delegate diagnostic-log extraction with exact evidence verification |
| `onlineContextCompact` | SoL-Pi | Expose `update_plan` and evaluate native compaction at completed steps |
| `cacheWriteReadRatio` | SoL-Pi | Finite non-negative ratio for the compaction gate; zero is valid |
| `reducerModel` | SoL-Pi | Optional model on the same provider/API connection; absent uses the Task model |

Set the cache ratio for the provider actually used; 12.5 is the SoL-Pi default,
not a claim about DeepSeek pricing. A custom reducer model must speak the same
API format and be accessible through the same connection. For custom endpoints,
its model metadata currently inherits the main model's registration. No separate
API key or upstream default reducer route is silently introduced.

Action Fusion cannot be enabled while `bash`, `edit` or `write` is disabled.
ObservationPack requires `obs_recall`; context compaction requires `update_plan`.
Contradictory policies fail before the model starts.

## State, traces and accounting

Pi Lab sessions and skills live under `.harness/home/.pi-lab/agent`. Pi retains
`.harness/home/.pi/agent`. The runner writes a managed wrapper that supplies the
effective configuration through SoL-Pi's public registration API, so a
`.pi/sol-pi.json` inside a task cannot override agent switches. Effective settings
are saved in `.harness/pi-lab/effective-config.json`. These paths are inside the
normal session checkpoint and excluded from user-produced file cards. `auth.json`,
`models.json` and `mcp.json` under the Pi Lab agent directory are excluded from
snapshots; they can carry provider keys or MCP credentials. The runner rebuilds
connection settings on the next turn. Resume works as for plain Pi (`--session-id`),
and MCP tools are registered directly on the agent, as for plain Pi.

Pi Lab emits its terminal result only when the process settles, including turns
automatically continued after compaction. Reducer decisions and tagged model usage
are preserved as `system/pi_lab_reducer` trace events. The result and turn record
carry `pi_lab.auxiliary_usage`, separate from main-model usage. **Existing cost
widgets report main-model cost, not total Pi Lab cost**: analysis must price this
additional usage by reducer model. Native Pi compaction accounting retains the
upstream behavior. Benchmark cost comparisons require auditing both before use.

## Verification

```sh
python -m pytest runner/tests/test_pi_lab.py runner/tests/test_pi_normalize.py -q
python -m pytest gateway/tests/test_pi_lab_backend.py -q
python scripts/pi-lab/check-lock.py
python scripts/pi-lab/smoke.py
```

The smoke test uses a local scripted provider and the installed, unmodified Pi and
SoL-Pi packages. It verifies tool schemas with switches on/off, actual fused file
write and shell execution, output artifacts, conversation resume and model switch.
It also triggers the real reducer, verifies safe fallback on invalid evidence,
and checks that auxiliary-model usage is recorded once. It deletes and restores
the workspace through a credential-excluding archive and verifies that the next
CLI process retains history, including switching back to the original model.
It does not measure task quality or replace live-provider support-matrix checks.
Use `scripts/support-matrix` for provider/model-specific acceptance before deployment.

For the settings smoke check, start a local UI build on port 3187, sign in using a
Playwright CLI browser session, then run `playwright-cli run-code --filename
scripts/pi-lab/ui-smoke.js` in that session. It uses browser-local API fixtures and
checks defaults, toggling, a zero cache ratio, reducer model, serialization and reload.

Run the Python suites from a path without spaces: an existing MCP bridge assertion
(`test_uhp_plugins.py`) assumes an unquoted path.

### Validation record

Offline, on upstream `main` at `384bd75` with this branch applied, after the rename
(2026-09-26):

- Gateway and runner: 1,199 passed, 19 skipped.
- Console: type-check and production build passed. Jest contains no tests; the
  settings panel's browser smoke passed on 2026-09-25 under the old id and was not
  re-run after the rename.
- `check-lock.py` verified 427 locked packages and the upstream commit. A fresh
  `install.sh` verified all 23 SoL-Pi source hashes, and a second run reused it; `smoke.py` passed all-on,
  all-off and reducer configurations (fusion, artifacts, reducer fallback and
  auxiliary usage, resume and model switch/back, checkpoint restore) against a
  scripted endpoint. These are not live model-quality measurements.
- Entrypoint and installer shell syntax checks passed.


The live records in
[verification/sol-pi-2026-09-25](verification/sol-pi-2026-09-25/README.md) were
taken on 2026-09-25, before this backend was renamed from `sol-pi` to `pi-lab`;
they name the old id. They cover one connection/model pair on a local instance and
a fresh core container:

- Dedicated Banban connection, DeepSeek V4.1 Flash: first turn, follow-up, artifact
  cards versus stored files, and forced recycle/history recall passed (4/4).
  Live model switch is n/a because only one model was authorized.
- Custom harness: stored skill and tool policy, hidden script token, produced
  `stamp.txt`, disabled `edit` unused, and a recorded DeepWiki MCP call all passed.
- 12 successful real turns used 39,636 uncached input, 1,252 output and 44,160
  cached input tokens. Assuming the user's rates are CNY per million, estimated
  cost is CNY 0.0068; this is not a provider invoice.

The matrix column certifies only this connection/model. The broader catalog
inherits Pi's transport coverage, not a measured compatibility claim for every
model. Forced online compaction and long-context archive/recall quality have not
been measured against a paid provider.

The core container built and passed first-start installation, login, runtime version,
non-owner execution/non-writability, health check, and the same real routing/custom
harness suites. Build flags: `WITH_DOC_PREVIEW=0`, `WITH_MEDIA=0`,
`WITH_STARTER_KITS=0`, `WITH_BUILTIN_SKILLS=0` (browser defaults to 0).
The default all-feature image was not certified: enabling bundled OfficeCLI while
turning off document preview exposed a missing ICU dependency in that existing
optional-feature combination. No claim is made about office/media starter bundles.

The container run found and fixed a real installer bug: `mktemp` left the
published runtime root at 0700, preventing a session uid from executing Pi.
A fresh installation now passes with uid 20000; CI also checks
execution/non-writability as a different user. Windows builds also
needed recursive dependency exclusions and LF enforcement for Docker shell scripts.

Responsive audit covered built-in and custom settings at 15 widths (390–1440 px).
Only the existing sidebar +4 px finding appeared, reproduced on ordinary Pi; no
new settings-content or page overflow was found. This is not a zero-finding audit.
