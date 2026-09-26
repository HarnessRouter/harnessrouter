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
  cheetahclaws: '/logos/cheetahclaws.png',   // CheetahClaws' own app icon (cheetahclaws/web/static/favicon.png in the Apache-2.0 SAIL-Research-Lab/cheetahclaws repository, shipped in the 3.5.88 wheel)
  systemone: '/logos/systemone.png',   // the System One Harness's own mark (the project has no vendor logo; Jev is TypeSafe's model, not the harness)
};

export function HarnessLogo({ id, size = 26 }: { id: string; size?: number }) {
  const src = LOGO[id];
  if (!src) return <span style={{ fontSize: size * 0.7 }}>◍</span>;
  return <img src={src} alt="" width={size} height={size}
              style={{ width: size, height: size, objectFit: 'contain', borderRadius: 6 }} />;
}
