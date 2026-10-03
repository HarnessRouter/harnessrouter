# Pi Lab live verification — 2026-09-28

The re-run under `pi-lab` that [the 2026-09-25 records](../sol-pi-2026-09-25/README.md) point to, on
the branch rebased onto `main` at 51e420f (commit 79b18b1, after #285 was merged).

Environment: a fresh self-hosted container from that commit, lean image (`WITH_DOC_PREVIEW=0`,
`WITH_MEDIA=0`, `WITH_STARTER_KITS=0`, `WITH_BUILTIN_SKILLS=0`), `HR_BACKENDS=pi,pi-lab`, a new data
volume, and one custom OpenAI-format integration, `pi-lab-banban-acceptance`, serving
`deepseek-v4.1-flash`. Pinned Pi 0.85.1 and NVlabs SoL-Pi 1559b5cb12c72da4a485bc50fe326586b216fb19,
installed by the entrypoint with every source hash checked. This certifies a connection/model
combination, not the inherited full Pi catalog.

## Evidence

- `pilab-live.json`, `pilab-live.log`: unmodified support-matrix output. First turn, follow-up,
  artifact (the file card matches the stored file) and recycle-then-recall passed; the model switch is
  n/a with one model. Every turn ran on `integration:pi-lab-banban-acceptance` and served
  `deepseek-v4.1-flash`.
- `pilab-custom.json`: unmodified custom-harness result. The harness's own skill was reached and its
  script ran, the disabled `edit` stayed unused (the harness also stores `actionFusion: false`, which
  that setting requires), a file was produced, and the public DeepWiki MCP was called.
- The MCP call is the check that matters most for this rebase: `main` moved Pi to pi-mcp-adapter 3.x
  (`mcp-adapter.json`) while Pi Lab keeps its locked 2.37.0 and `mcp.json`, and the DeepWiki call shows
  Pi Lab still finds its server.

## Reproduction

Run the support-matrix suite with `HARNESSES=pi-lab`, `PROVIDER=banban`,
`MODELS=deepseek-v4.1-flash`, `PROVIDER_MODELS=deepseek-v4.1-flash` and
`EXPECT_CONNECTION=integration:pi-lab-banban-acceptance`; then `custom-harness.mjs` with
`BASES=pi-lab` and `MODEL=deepseek-v4.1-flash`. Supply `BASE` and the local login separately; provider
secrets stay in the instance's configuration and are not part of this record.
