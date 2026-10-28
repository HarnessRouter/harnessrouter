// Official brand marks for the default (OOB) harnesses, served from /public/logos.
// claude-code -> claude.png (Anthropic), codex -> codex.png, pi -> pi.png,
// hermes -> hermes.png, dsh -> deepseek.png, opencode -> opencode.png (the square mark from
// opencode.ai, its apple-touch icon). A base with none draws no mark.

const LOGO: Record<string, string> = {
  'claude-code': '/logos/claude.png',
  codex: '/logos/codex.png',
  pi: '/logos/pi.png',
  omp: '/logos/omp.png',
  hermes: '/logos/hermes.png',
  dsh: '/logos/deepseek.png',
  opencode: '/logos/opencode.png',
  qwen: '/logos/qwen.png',
  cline: '/logos/cline.png',
  gemini: '/logos/gemini.png',   // the mark Richard chose (2026-09-07), 512 px with transparent corners
  goose: '/logos/goose.png',
  openhands: '/logos/openhands.png',   // OpenHands' own app icon (public/apple-touch-icon.png in the MIT OpenHands/OpenHands repository)
  cheetahclaws: '/logos/cheetahclaws.png',   // the head and shoulders of CheetahClaws' own logo (docs/media/logos/logo-5.png in the Apache-2.0 SAIL-Research-Lab/cheetahclaws repository), cut square; Richard picked it 2026-09-26
  kilo: '/logos/kilo.png',       // Kilo Code's own app icon (packages/kilo-docs/public/favicon/apple-touch-icon.png in the MIT Kilo-Org/kilocode repository)
  minimax: '/logos/minimax.png', // MiniMax's own mark (the MiniMax-AI organization's avatar on GitHub, the publisher of minimax-code)
  grok: '/logos/grok.png',       // Grok's own app icon (grok.com/icon-512x512.png, scaled to 192 px)
  agentzero: '/logos/agentzero.png',   // Agent Zero's own mark (docs/res/favicon_round.png in the MIT agent0ai/agent-zero repository, scaled to 192 px)
  systemone: '/logos/systemone.png',   // the System One Harness's own mark (the project has no vendor logo; Jev is TypeSafe's model, not the harness)
  // The five bases of open source 0.33.0, with the marks it ships (each one's source is noted there)
  qoder: '/logos/qoder.png',     // Qoder's own app icon (the apple-touch icon qoder.com serves, scaled to 192 px)
  jcode: '/logos/jcode.png',     // jcode's own app icon (MIT 1jehuang/jcode); a black mark on transparency, upstream ships no light variant
  opensquilla: '/logos/opensquilla.png',   // the OpenSquilla mark (Apache-2.0 TokenRhythm/opensquilla)
  nanobot: '/logos/nanobot.svg',   // the nanobot mark (MIT HKUDS/nanobot)
  vibe: '/logos/vibe.svg',   // Vibe's own mark (distribution/zed/icons/mistral_vibe.svg in the Apache-2.0 mistralai/mistral-vibe repository), the glyph Mistral ships for editor surfaces. Like jcode's it is a BLACK mark on transparency and upstream ships no light variant, so it carries no contrast on a dark surface
  // ZeroClaw's own mark, the ice crab: the zeroclaw-labs organization's avatar on GitHub, cut square
  // and scaled to 192 px (open source 0.34.0). The armored crab in its v0.8.5 dashboard is an older mark.
  zeroclaw: '/logos/zeroclaw.png',
  mimo: '/logos/mimo.png',       // Xiaomi MiMo's square mark, drawn at 192 px from the wordmark mimo.xiaomi.com/coder serves
  aider: '/logos/aider.png',   // aider's own app icon (aider.chat/assets/icons/apple-touch-icon.png, from the Apache-2.0 repo's website assets)
  kimi: '/logos/kimi.png',     // the official Kimi mark (the K app icon from kimi.ai/code), supplied by Richard 2026-09-17
  // The batch-4 bases of open source 0.37.0, each the mark its own repository publishes (Richard asked for them 2026-10-25)
  'docker-agent': '/logos/docker-agent.svg',   // the Docker mark as the Apache-2.0 docker/docker-agent repository ships it (docs/assets/docker-mark.svg)
  'fast-agent': '/logos/fast-agent.svg',       // fast-agent's own icon, the amber chevron (docs/docs/assets/brand/fast-agent-icon.svg in the Apache-2.0 evalstate/fast-agent repository)
  dcode: '/logos/dcode.svg',                   // the square icon of the Deep Agents logo (.github/images/logo-light.svg in the MIT langchain-ai/deepagents repository), cut from its wordmark
};
// No entry for vtcode: that base is not in this tree at all (its headless mode drops a harness's
// MCP servers — docs/support-matrix-notes.md), so neither its mark nor its row is carried here.

// The bases whose backend is named apart from the base: a setup saved through the API can carry the backend
// (`claude`) as its base, and draws the base's mark all the same (harness-base-alias.test.ts holds this to the OOB table).
export const BACKEND_BASE: Record<string, string> = { claude: 'claude-code' };

/** The base harness's mark file, by its id or its backend, or '' when it has none. */
export const harnessLogoSrc = (id: string): string => LOGO[id] || LOGO[BACKEND_BASE[id] || ''] || '';
