'use client';
// The small pieces a kit is drawn with (docs/uxuidesign/console-79: kitCard's icon tile, kcMeta,
// pieces, metaLine): the kit's mark in its own colour, what it runs on, and its parts.
import type { ReactNode } from 'react';
import { harnessLogoSrc } from '@/components/HarnessLogo';
import { partIcon } from '../bricks';
import { Iso } from '../Iso';
import type { Kit } from './kits';

// The design's white marks (KIT_IC), one per kit it draws, and the same hand for the two it does not.
// A kit the console has no mark for shows its own icon file, else its first letter.
const sv = (children: ReactNode, cap = true) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2} strokeLinecap={cap ? 'round' : undefined} strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const KIT_IC: Record<string, ReactNode> = {
  dashboard: sv(<><rect x="4" y="4" width="16" height="16" rx="2.5" /><path d="M8.5 15.5v-3M12 15.5v-7M15.5 15.5v-5" /></>),
  video: sv(<><rect x="4" y="5" width="16" height="14" rx="2.5" /><path d="M10.5 9.5v5l4-2.5z" fill="#fff" stroke="none" /></>, false),
  mario: sv(<><path d="M7.5 8.5h9a4.5 4.5 0 0 1 4.4 5.4l-.3 1.5a2.6 2.6 0 0 1-4.6 1.1L14.5 15h-5L8 16.5a2.6 2.6 0 0 1-4.6-1.1l-.3-1.5a4.5 4.5 0 0 1 4.4-5.4z" /><path d="M8.5 11v3M7 12.5h3" /><circle cx="15.5" cy="12" r=".6" fill="#fff" /><circle cx="17" cy="13.5" r=".6" fill="#fff" /></>),
  workplace: sv(<><circle cx="9" cy="9" r="3" /><circle cx="16.5" cy="9.5" r="2.3" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0M14.5 19a4 4 0 0 1 6.5-3" /></>),
  slides: sv(<><rect x="3.5" y="4.5" width="17" height="12" rx="2.5" /><path d="M12 16.5V20M8.5 20h7M7.5 8.5h9M7.5 12h5" /></>),
  sheets: sv(<><rect x="4" y="4" width="16" height="16" rx="2.5" /><path d="M4 9.5h16M4 14.5h16M9.5 9.5V20" /></>),
};

/** The kit's icon tile (`.kc-ic`): its mark on its own accent colour. */
export function KitIc({ kit, as = 'div' }: { kit: Kit; as?: 'div' | 'span' }) {
  const Tag = as;
  const mark = KIT_IC[kit.id];
  if (mark) return <Tag className="kc-ic" style={{ background: kit.accent || 'var(--fg)' }}>{mark}</Tag>;
  if (kit.iconUrl) {
    return (
      <Tag className="kc-ic" style={{ background: 'var(--bg)', overflow: 'hidden' }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- the kit's own mark, served beside its app */}
        <img src={kit.iconUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
      </Tag>
    );
  }
  return <Tag className="kc-ic" style={{ background: kit.accent || 'var(--fg)' }}><b>{(kit.title || kit.id).charAt(0).toUpperCase()}</b></Tag>;
}

export function HLogo({ base }: { base: string }) {
  const src = harnessLogoSrc(base);
  // eslint-disable-next-line @next/next/no-img-element -- a static brand mark
  return src ? <img className="h-logo" src={src} alt="" /> : null;
}

/** One chip per part (`.kc-pieces .kp`): a small brick in the part's colour, its kind and value. */
const PIECE_FAM: Record<string, string> = { harness: 'backend', model: 'backend', skill: 'skill', plugin: 'plugin', database: 'tool', tool: 'tool' };
export function Pieces({ parts }: { parts: [string, string][] }) {
  return (
    <div className="kc-pieces">
      {parts.map(([t, v]) => (
        <span key={t + v} className="kp" title={t}>
          <Iso svg={partIcon('built', PIECE_FAM[t] || 'parts')} />
          <span><i>{t}</i>{v}</span>
        </span>
      ))}
    </div>
  );
}
