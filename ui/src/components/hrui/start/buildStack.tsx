'use client';
// The Agent stack beside a new setup's first task while it is saved (docs/uxuidesign/console-91:
// towerHtml with its drops and "Saving · your setup"): fed by the save's own answers (start/build.ts).
// When the setup is created, its agent harness, model, instructions and the parts HarnessRouter runs
// land, one after another so the eye can follow; each plugin lands when its attach answers and the
// skills a person's template brings with the record (never the agent harness's built-ins); the parts
// row counts what has landed ("Plugin · 1 added"). A brick lands
// once: its drop is let go when it has played.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { SetupRow } from '../setups';
import { SUBS, type Drops, type Tower } from '../tower';
import type { Build } from './build';
import { addedSkillsOf } from './Assembly';

const STAGGER_MS = 140;
const SUB_STAGGER_MS = 70;
const DROP_MS = 1400;
/** A save older than this has landed already (a page opened later): nothing drops. */
const FRESH_MS = 4000;

/** The parts the save has landed so far, by brick (skill, plugin). */
export function landedParts(b: Build | null): { skill: number; plugin: number } {
  const a = b?.asm;
  if (!a || a.savedAt == null) return { skill: 0, plugin: 0 };
  return { skill: addedSkillsOf(a.cfg).length, plugin: a.cfg.plugins.filter((p) => a.plugins[p.id] === 'on').length };
}

/** The tower with the save's landed parts on it (the record catches up when it is read again). */
export function withLanded(t: Tower, landed: { skill: number; plugin: number }): Tower {
  const parts = { ...t.parts, skill: Math.max(t.parts.skill, landed.skill), plugin: Math.max(t.parts.plugin, landed.plugin) };
  const st = { ...t.st };
  (['skill', 'plugin'] as const).forEach((k) => { if (parts[k] > 0 && st[k] !== 'run') st[k] = 'built'; });
  return { ...t, parts, st };
}

type Seen = { skill: number; plugin: number };
/** The bricks to land now: everything the save has landed, on the first sight of a fresh save
 *  (`prev` null); after that only a part that has just landed. */
export function dropsFor(prev: Seen | null, landed: Seen, fresh: boolean): Drops {
  const next: Drops = {};
  const late = 3 * STAGGER_MS + SUBS.length * SUB_STAGGER_MS;
  if (!prev && fresh) {
    ['b-runtime', 'model', 'task'].forEach((k, i) => { next[k] = i * STAGGER_MS; });
    SUBS.forEach(([k], i) => { next[k] = 3 * STAGGER_MS + i * SUB_STAGGER_MS; });
  }
  if (prev ? landed.skill > prev.skill : fresh && landed.skill > 0) next['part:skill'] = prev ? 0 : late;
  if (prev ? landed.plugin > prev.plugin : fresh && landed.plugin > 0) next['part:plugin'] = prev ? 0 : late + STAGGER_MS;
  return next;
}

export function useBuildStack<R extends SetupRow | null>(r: R, b: Build | null): { r: R; now: ReactNode | null; drops: Drops | null } {
  const landed = landedParts(b);
  const savedAt = b?.asm?.savedAt ?? null;
  // the first frame already carries the landing (a page opened on a fresh save draws its bricks
  // dropping from the start, never sitting a frame and then jumping)
  const seen = useRef<Seen | null>(savedAt != null ? { skill: landed.skill, plugin: landed.plugin } : null);
  const [drops, setDrops] = useState<Drops | null>(() => {
    if (savedAt == null) return null;
    const d = dropsFor(null, landed, Date.now() - savedAt < FRESH_MS);
    return Object.keys(d).length ? d : null;
  });
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const letGo = (d: Drops) => { clearTimeout(timer.current); timer.current = setTimeout(() => setDrops(null), DROP_MS + Math.max(...Object.values(d))); };
  useEffect(() => {
    if (drops) letGo(drops);
    return () => clearTimeout(timer.current);
  // the first frame's landing, let go once it has played
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!b || savedAt == null) return;
    const prev = seen.current;
    const next = dropsFor(prev, landed, Date.now() - savedAt < FRESH_MS);
    seen.current = { skill: landed.skill, plugin: landed.plugin };
    if (!Object.keys(next).length) return;
    setDrops(next);
    letGo(next);
  // when the save lands something
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [b, savedAt, landed.skill, landed.plugin]);
  if (!r || !b || !b.asm) return { r, now: null, drops: null };
  const row = (landed.skill || landed.plugin ? { ...r, tower: withLanded(r.tower, landed) } : r) as R;
  return { r: row, now: b.phase === 'saving' ? <><b>Saving</b> · your setup</> : null, drops };
}
