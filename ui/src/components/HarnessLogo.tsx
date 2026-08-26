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
};

export function HarnessLogo({ id, size = 26 }: { id: string; size?: number }) {
  const src = LOGO[id];
  if (!src) return <span style={{ fontSize: size * 0.7 }}>◍</span>;
  return <img src={src} alt="" width={size} height={size}
              style={{ width: size, height: size, objectFit: 'contain', borderRadius: 6 }} />;
}
