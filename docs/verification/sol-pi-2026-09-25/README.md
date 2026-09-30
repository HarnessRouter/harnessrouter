# SoL-Pi local verification — 2026-09-25

These records were taken before the backend was renamed from `sol-pi` to `pi-lab`
([Pi Lab](../../pi-lab.md)). They are kept as recorded, with the old id, harness
and path names; the re-run under `pi-lab` is [pi-lab-2026-09-28](../pi-lab-2026-09-28/README.md).

Environment: dedicated self-hosted local gateway/runner/console, only one provider
integration, pinned Pi 0.85.1 and NVlabs SoL-Pi 1559b5cb12c72da4a485bc50fe326586b216fb19.
This certifies a connection/model combination, not the inherited full Pi catalog.

## Evidence

- `solpi-live.json`: unchanged support-matrix output. The invocation omitted the
  `integration:` prefix from EXPECT_CONNECTION, producing a false foreign stamp.
- `solpi-live-reviewed.json`: the same scenario records, with `foreign` recomputed
  against the exact expected `integration:sol-pi-banban-acceptance` stamp. Every
  recorded connection was checked; no test outcome was changed. This is the input
  to the initial local rendering; the published column uses the later container run.
- `solpi-custom.json`: unchanged custom-harness suite result; explicit Flash
  default, bundled script, disabled `edit`, and public DeepWiki MCP.
- `solpi-usage.json`: six stored response usage records, totals and an estimate
  using the user's rates, assuming CNY per million tokens. Not a billing receipt.
- `solpi-container-live.json`, `solpi-container-custom.json`: unmodified final
  container results, including correct exact connection checks.
- `solpi-container-usage.json`, `usage-summary.json`: container usage and totals
  across both successful runs (12 turns).
- `responsive-builtin.log`, `responsive-custom-and-baseline.log`: unmodified
  repository audit at all 15 widths, 390–1440 px. Both SoL-Pi surfaces show only the
  same sidebar +4 px finding as the ordinary Pi baseline; no settings-content or
  page overflow. These are not zero-finding audit runs.

## Reproduction

Run the repository support-matrix suite with HARNESSES=sol-pi, PROVIDER=banban,
MODELS=deepseek-v4.1-flash, PROVIDER_MODELS=deepseek-v4.1-flash and
EXPECT_CONNECTION=integration:sol-pi-banban-acceptance. For custom-harness.mjs,
use BASES=sol-pi and MODEL=deepseek-v4.1-flash. Supply BASE and local login separately;
provider secrets must be configured locally, never added to this record.

The four applicable routing scenarios passed. Cross-model switch is n/a because
only one paid model was authorized; scripted switch/back is separate evidence.
Settings browser smoke passed independent base, default switches, save/reload,
zero cache ratio, reducer model and read-only built-in defaults.

Full image/self-host result is recorded in ../../pi-lab.md. No benchmark quality,
long-context quality or speed claim is made by this acceptance run.

## Container details

Image: `sha256:e0922459ea06e5202e6551708212091b94fda6079c97c3b35da29071f8077697`.
Runtime manifest digest: `67fa814f03599c50b76b8adcc525bcddd88fbd5a6fa594556c29b7bf407efbc3`.
Flags: WITH_DOC_PREVIEW=0, WITH_MEDIA=0, WITH_STARTER_KITS=0,
WITH_BUILTIN_SKILLS=0; default WITH_BROWSER=0. Fresh volume; HR_BACKENDS=sol-pi.
Final health: healthy. Version: 0.85.1, executable by uid 20000, not writable by it.
Resetting the runtime root to 0700 then reusing the installer repaired access.

An earlier container attempt failed before a model call with
`spawn: [Errno 13] Permission denied: /data/agent-tools/sol-pi-runtime/bin/pi`.
It was stopped and the installer fixed; final results come from a fresh volume.
This was an actual acceptance finding, not a provider error or a passing row.
