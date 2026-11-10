'use client';
// The small pieces the Memories pages share: the design's icons, a type's coloured dot, the card's
// picture of a schema, and the reads more than one page makes.
import { IconByName } from './graph/graphIcons';
import { useCallback, useEffect, useState, type RefObject } from 'react';
import { listCustom } from '@/lib/harness';
import { listProviders, type Grant, type Memory, type Provider } from '@/lib/memories';
import { inVendorOrder } from './vendors';
import { MM_ICONS } from './schemaModel';

export function MmIco({ k, size = 16, color }: { k: string; size?: number; color?: string }) {
  if (k && !MM_ICONS[k]) return <IconByName name={k} size={size} color={color} />;   // any icon a schema names, from the full catalogue
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke={color || 'currentColor'} strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={MM_ICONS[k] || MM_ICONS.note} />
    </svg>
  );
}
const Line = ({ d, size = 16, w = 1.9 }: { d: string; size?: number; w?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={w} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
export const BACK_IC = <Line d="M15 6l-6 6 6 6" size={18} w={2} />;
export const PLUS = <Line d="M12 5v14M5 12h14" size={15} w={2.2} />;
export const X = <Line d="M6 6l12 12M18 6L6 18" w={2} />;
export const COPY = <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></svg>;
export const FOLDER = <Line d="M3 6h6l2 2h10v11H3z" size={15} w={1.8} />;
export const FOLDER_OPEN = <Line d="M3 19V6h6l2 2h8v3M3 19l2.5-8H22l-2.5 8z" size={15} w={1.8} />;
export const SEARCH = <Line d="M20 20l-3.5-3.5M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0z" size={14} w={2} />;
export const HISTORY = <Line d="M3.5 12a8.5 8.5 0 1 0 2.5-6M3.5 4v4h4M12 7.5V12l3 2" />;
export const FILTER = <Line d="M4 6h16M7 12h10M10 18h4" size={15} w={2} />;
export const ARROW = <Line d="M4 12h14M13 6l6 6-6 6" size={18} w={2} />;
export const DOTS = <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></svg>;
export const RELATE = <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" aria-hidden="true"><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M8 8l8 8" /></svg>;
export const ARRANGE = <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="8" /><circle cx="12" cy="4" r="1.5" fill="currentColor" /><circle cx="19" cy="15" r="1.5" fill="currentColor" /><circle cx="5" cy="15" r="1.5" fill="currentColor" /></svg>;
export const BADGE = <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden="true"><circle cx="6" cy="7" r="2.4" /><circle cx="18" cy="7" r="2.4" /><circle cx="12" cy="17.5" r="2.4" /><path d="M8.4 7h7.2M7.3 9.1l3.4 6.2M16.7 9.1l-3.4 6.2" /></svg>;

export function Dot({ color, icon, size = 11 }: { color: string; icon: string; size?: number }) {
  return <span className="mm-dot" style={{ background: color }}><MmIco k={icon} size={size} color="#fff" /></span>;
}

/** A menu that closes on a press outside it or Escape. */
export function useDismiss(open: boolean, ref: RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key); };
  }, [open, ref, onClose]);
}

/** Every provider and what it can do, as this workspace reaches it. */
export function useProviders() {
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [failed, setFailed] = useState(false);
  const reload = useCallback(async () => {
    setFailed(false);
    try { const d = inVendorOrder(await listProviders()); setProviders(d); return d; } catch { setFailed(true); return null; }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  return { providers, failed, reload };
}

/** The workspace's setups by id; null until read, or when they could not be read. */
export function useSetupNames(): Map<string, string> | null {
  const [names, setNames] = useState<Map<string, string> | null>(null);
  useEffect(() => {
    let live = true;
    listCustom().then((l) => { if (live) setNames(new Map(l.map((h) => [h.id, h.name]))); }).catch(() => {});
    return () => { live = false; };
  }, []);
  return names;
}

/** The setup a grant is to: a harness is the principal `member:<harness id>`. */
export const setupIdOf = (principal: string) => (/^member:(chrn_.+)$/.exec(principal) || [])[1] || '';
/** The setups a memory's grants reach, those the workspace still has. */
export function setupsOf(grants: Grant[], names: Map<string, string> | null): { id: string; name: string; grant: Grant }[] {
  return grants.flatMap((g) => {
    const id = setupIdOf(g.principal);
    return id && names?.has(id) ? [{ id, name: names.get(id) as string, grant: g }] : [];
  });
}
/** Runs `fn` over the items, at most `n` at a time. */
export async function pool<T>(items: T[], n: number, fn: (x: T) => Promise<void>): Promise<void> {
  let at = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (at < items.length) await fn(items[at++]);
  }));
}
export const memoriesWord = (n: number) => `${n} ${n === 1 ? 'memory' : 'memories'}`;
export const whenOf = (iso: string | null | undefined) => { const t = iso ? Date.parse(iso) : NaN; return Number.isFinite(t) ? t : null; };
/** A time the service gives as ISO text, epoch seconds or epoch ms, in ms; null when it gives none. */
export const msOf = (v: string | number | null | undefined): number | null => {
  if (typeof v === 'number') return Number.isFinite(v) && v > 0 ? (v < 1e12 ? v * 1000 : v) : null;
  return whenOf(v || null);
};
export { engineOf, shownName, userOf } from '@/lib/memories';
/** A sentence the service wrote, carried on after a word of ours ("Mem0, it serves people"): its first letter lowered,
 *  unless the word it begins is a name or an acronym. */
export const after = (s: string) => (/^[A-Z][a-z]/.test(s) && !/^(I|I['’][a-z]+)\b/.test(s) ? s[0].toLowerCase() + s.slice(1) : s);
