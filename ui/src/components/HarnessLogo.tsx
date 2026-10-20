// Official brand marks for the default (OOB) harnesses, served from /public/logos.
// claude-code -> claude.png (Anthropic), codex -> codex.png, pi -> pi.png,
// hermes -> hermes.png, dsh -> deepseek.png, opencode -> opencode.png (the square mark from
// opencode.ai, its apple-touch icon). Custom harnesses fall back to a generic glyph.
import React from 'react';

const LOGO: Record<string, string> = {
  'claude-code': '/logos/claude.png',
  codex: '/logos/codex.png',
  pi: '/logos/pi.png',
  hermes: '/logos/hermes.png',
  dsh: '/logos/deepseek.png',
  opencode: '/logos/opencode.png',
  qwen: '/logos/qwen.png',
  cline: '/logos/cline.png',
  gemini: '/logos/gemini.png',
  omp: '/logos/omp.png',
  goose: '/logos/goose.png',   // the flying goose from goose-docs.ai (logo_light.png, cropped to the mark)
  kimi: '/logos/kimi.png',     // the official Kimi mark (the K app icon from kimi.ai/code), supplied by Richard 2026-09-17
  aider: '/logos/aider.png',   // aider's own app icon (aider.chat/assets/icons/apple-touch-icon.png, from the Apache-2.0 repo's website assets)
  openhands: '/logos/openhands.png',   // OpenHands' own app icon (public/apple-touch-icon.png in the MIT OpenHands/OpenHands repository)
  cheetahclaws: '/logos/cheetahclaws.png',   // the head and shoulders of CheetahClaws' own logo (docs/media/logos/logo-5.png in the Apache-2.0 SAIL-Research-Lab/cheetahclaws repository), cut square so it reads at 26 px; the app icon drew the whole running cheetah as a thin band and rendered as a sliver (Richard, 2026-09-27)
  kilo: '/logos/kilo.png',       // Kilo Code's own app icon (packages/kilo-docs/public/favicon/apple-touch-icon.png in the MIT Kilo-Org/kilocode repository)
  minimax: '/logos/minimax.png', // MiniMax's own mark (the MiniMax-AI organization's avatar on GitHub, the publisher of minimax-code)
  grok: '/logos/grok.png',       // Grok's own app icon (grok.com/icon-512x512.png, scaled to 192 px)
  agentzero: '/logos/agentzero.png',   // Agent Zero's own mark (docs/res/favicon_round.png in the MIT agent0ai/agent-zero repository, scaled to 192 px)
  systemone: '/logos/systemone.png',   // the System One Harness's own mark (the project has no vendor logo; Jev is TypeSafe's model, not the harness)
  qoder: '/logos/qoder.png',     // Qoder's own app icon (the apple-touch icon qoder.com serves, 412 px, scaled to 192 px)
  jcode: '/logos/jcode.png',   // jcode's own app icon (assets/app-icons/Jcode.icns in the MIT 1jehuang/jcode repository), the 1024 px face resized. It is a BLACK mark on transparency, so it carries no contrast on a dark surface — upstream ships no light variant
  opensquilla: '/logos/opensquilla.png',   // the OpenSquilla mark (assets/opensquilla-mark.png in the Apache-2.0 TokenRhythm/opensquilla repository), already square
  nanobot: '/logos/nanobot.svg',   // the nanobot mark (images/nanobot_mark.svg in the MIT HKUDS/nanobot repository); an SVG like cursor.svg, which this map already serves
  vibe: '/logos/vibe.svg',   // Vibe's own mark (distribution/zed/icons/mistral_vibe.svg in the Apache-2.0 mistralai/mistral-vibe repository), the glyph Mistral ships for editor surfaces. Like jcode's it is a BLACK mark on transparency and upstream ships no light variant, so it carries no contrast on a dark surface
  zeroclaw: '/logos/zeroclaw.png', // ZeroClaw's own mark, the ice crab: the zeroclaw-labs organization's avatar on GitHub (the same mascot leads its README and zeroclaw.com), cut square above its name band and scaled to 192 px so it reads at 26 px. The armored crab in the v0.8.5 dashboard (web/dist/logo.png) is an older mark (Richard, 2026-10-14)
  mimo: '/logos/mimo.png',   // Xiaomi MiMo's own square mark: the site icon of mimo.xiaomi.com (the "Xiaomi" over "MiMO" wordmark, white on black) is 32 px only, so it is drawn again at 192 px from the full-size wordmark that mimo.xiaomi.com/coder serves (coder/assets/logo.png), in the same layout (Richard, 2026-10-12)
};
// No entry for fast-agent either: its repository ships no mark (the two files with "logo" in the
// name are design sketches in plan/), so the generic glyph is the honest fallback.
// No entry for docker-agent: its repository ships no mark of its own, and the Docker whale is
// Docker's trademark rather than the project's icon — so it falls back to the generic glyph, as
// mimo does, instead of this map pointing at a file that is not ours to redistribute.
// No entry for vtcode: that base is not in this tree at all (its headless mode drops a harness's
// MCP servers — docs/support-matrix-notes.md), so neither its mark nor its row is carried here.
// No entry for dcode either: langchain-ai/deepagents ships no mark for the CLI (its README leads
// with LangChain's own wordmark, which is LangChain's trademark and not this project's icon), so
// the generic glyph is the honest fallback here too.

export function HarnessLogo({ id, size = 26 }: { id: string; size?: number }) {
  const src = LOGO[id];
  if (!src) return <span style={{ fontSize: size * 0.7 }}>◍</span>;
  return <img src={src} alt="" width={size} height={size}
              style={{ width: size, height: size, objectFit: 'contain', borderRadius: 6 }} />;
}
