# Harness Router

A new product built on AgentStudio. "Build agent features into your app without building the
backend. One API routes your app to harnesses like Codex, Claude Code, OpenClaw, and Hermes."

Separate frontend app, on its own subdomain (`harnessrouter.epsilla.com`, DNS pointed by the
owner), reusing AgentStudio's design tokens + UI components + auth + Traces. Backed by a new
VectorGraph tenant (schema TBD, iterated with the owner).

## Locked decisions (2026-06-22, with the owner)
- **MVP = core loop first**: Harnesses (clone) → Workbench Config&Preview with LIVE chat → Traces,
  then API tab + landing. Marketplace, MCP/Skills "Add", OpenClaw/Hermes stubbed.
- **Auth = reuse AgentStudio** (same engine, JWT, orgs). Own login form on the subdomain; a Harness
  Router user IS an AgentStudio member. (Separate localStorage origin, so its own session.)
- **Backends v1 = Codex + Claude Code real** (gateway/runner), **OpenClaw + Hermes "coming soon"**.
- **Headline routing API in v1 = yes**, a minimal public key-auth invoke (pick harness → session →
  turn → poll). The value prop ("one API") must be real.
- Brand = deep iris `#42309C` (override the mock's brighter blue). MCP/Skills shown but "Add" disabled
  in v1 (network MCP blocked by sandbox egress; skills wiring undefined). Marketplace/Docs = placeholders.
  Clone = independent copy; Discard = revert unsaved; Save = applies to next run. Per-org API keys.

## Architecture
- `harnessrouter/` is a 2nd Next 15 app (monorepo sibling of `frontend/`), deploy as its own unit on
  the subdomain. Copies the studio design system (`src/studio/styles` tokens, `src/components/ui`,
  `src/studio/lib` dialog/icons, `src/studio/traces`) verbatim for v1 (extract a shared package later).
- BFF proxies: `/api/engine` → workflow-engine (auth), `/api/harness` → harness-gateway (sessions/turn/
  traces). Auth via the copied `src/lib/auth.ts` (login/getSession/authFetch).
- Data: out-of-box catalog is static in `src/lib/harness.ts` (will read runner `/backends`). Custom
  harnesses persist client-side for the skeleton; `src/lib/harness.ts` CRUD is the single seam to swap
  for the VectorGraph-tenant API.

## Status (done)
- App scaffold builds clean + screenshot-verified: landing (deep iris), login, auth-gated shell with
  top nav, Harnesses page (matches wireframe: Codex/Claude Code clonable, OpenClaw/Hermes "soon",
  custom create/clone/delete), Workbench skeleton (Config&Preview 3-pane + API tab + Traces tab),
  Marketplace/Docs/Pricing. Committed.

## Next phases
1. **Deploy** to the VM (systemd service + nginx server block for harnessrouter.epsilla.com); owner points DNS.
2. **VectorGraph tenant** + `CustomHarness` schema + CRUD; swap `src/lib/harness.ts` to the real API.
3. **Live chat** in Workbench: `POST /api/harness/sessions` → `/turn` → poll; inject default model +
   system prompt. SPIKE FIRST: system-prompt injection mechanism (Claude Code has no flag) — the one
   real technical risk.
4. **Traces tab**: tag sessions with harness_id at create; reuse `TracesMain` scoped to the harness.
5. **Public invoke API** + API-key mint/revoke (per-org); the API tab docs reflect it.
6. **"Harness Router" Space** under Epsilla's org with this spec + the wireframes for ops.
