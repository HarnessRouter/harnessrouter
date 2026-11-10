'use client';
// A memory's picture on its card and in its list row (cover.ts says which): the cover the service keeps, loaded as it
// comes near the screen and from the browser's own cache after that; the one made here in this visit; a quiet shape of
// the same size while one is still to be made; or the memory's brick from the agent stack where there is no graph.
// The only read a card makes is its cover. Small (a list row) is `mm-small`, never `mini`: that is Studio's own class,
// with a margin of its own that pushed the picture off its box.
import { useEffect, useRef, useState } from 'react';
import { readCover, type Memory } from '@/lib/memories';
import { Markup } from '../Markup';
import { brickSvg } from '../tower';
import type { Drawn, PicKind } from './cover';

// the Memory brick as the agent stack draws it: built, alone, on its shadow (geometry only, no data in it)
const BRICK = brickSvg('memory', 'built');

export function MemoryBrick({ mini }: { mini?: boolean }) {
  return <Markup className={`mm-brick${mini ? ' mm-small' : ''}`} html={BRICK} />;
}

/** Where a picture will be, until it is: the same size, and quiet. */
export function CoverWait({ mini }: { mini?: boolean }) {
  return <span className={`mm-cv-wait${mini ? ' mm-small' : ''}`} aria-hidden="true" />;
}

// One watcher for every card: a cover is read when its card comes within a screen of being seen.
const waiting = new Map<Element, () => void>();
let watcher: IntersectionObserver | null = null;
function whenNear(el: Element, go: () => void): () => void {
  if (typeof IntersectionObserver === 'undefined') { go(); return () => undefined; }
  watcher = watcher || new IntersectionObserver((seen) => {
    for (const e of seen) {
      if (!e.isIntersecting) continue;
      const fn = waiting.get(e.target);
      waiting.delete(e.target);
      watcher?.unobserve(e.target);
      fn?.();
    }
  }, { rootMargin: '600px 0px' });
  waiting.set(el, go);
  watcher.observe(el);
  return () => { waiting.delete(el); watcher?.unobserve(el); };
}

function Picture({ src, mini }: { src: string; mini?: boolean }) {
  return <span className={`mm-cv${mini ? ' mm-small' : ''}`}><img className="mm-cover" src={src} alt="" loading="lazy" decoding="async" /></span>;
}

/** The kept cover, read with the sign-in when it comes near the screen. Until it has come, and if it can't be read,
 *  the quiet shape stays. */
export function CoverImg({ id, at, mini }: { id: string; at: number; mini?: boolean }) {
  const box = useRef<HTMLSpanElement | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    let live = true, obj = '';
    const stop = whenNear(el, () => {
      readCover(id, at).then((b) => {
        if (!live) return;
        obj = URL.createObjectURL(b);
        setSrc(obj);
      }).catch(() => { /* the quiet shape stays */ });
    });
    return () => { live = false; stop(); if (obj) URL.revokeObjectURL(obj); };
  }, [id, at]);
  return (
    <span ref={box} className={`mm-cv${mini ? ' mm-small' : ''}`}>
      {src ? <img className="mm-cover" src={src} alt="" loading="lazy" decoding="async" /> : <CoverWait mini={mini} />}
    </span>
  );
}

/** A memory's picture: `kind` from the list (cover.ts picKindOf), and `drawn`, one made here in this visit. */
export function MemoryArt({ m, kind, drawn, mini }: { m: Pick<Memory, 'id' | 'cover_at' | 'cover_sig'>; kind: PicKind; drawn?: Drawn | null; mini?: boolean }) {
  if (drawn) return <Picture src={drawn.url} mini={mini} />;
  if (kind === 'cover' && m.cover_at) return <CoverImg id={m.id} at={m.cover_at} mini={mini} />;
  if (kind === 'brick') return <MemoryBrick mini={mini} />;
  return <CoverWait mini={mini} />;
}
