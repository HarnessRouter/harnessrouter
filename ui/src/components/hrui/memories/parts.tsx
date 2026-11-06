'use client';
// The small pieces the Memories pages share: the design's icons, a type's coloured dot, the card's
// picture of a schema, and the reads more than one page makes.
import { IconByName } from './graph/graphIcons';
import { useCallback, useEffect, useState, type RefObject } from 'react';
import { listCustom } from '@/lib/harness';
import { listProviders, type Grant, type Provider } from '@/lib/memories';
import { inVendorOrder } from './vendors';
import { MM_ICONS, typeLabel, type LSchema } from './schemaModel';
import { withBuiltin, type BGraph } from './graph/builtin';
import { graphOf } from './graph/schemaDraft';

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

/** A memory's cover: its schema, small. What the provider makes itself (its concepts) and the types a person set, each
 *  named, with the links between them, as the Schema tab draws them. Nothing to draw: one dot a record, and an empty memory
 *  stays an empty ring. */
const ART_DOTS = 15, ART_COLS = 5, ART_NAMED = 9;
export function Art({ s, w, h, records = 0, provider = null }: { s: LSchema | null | undefined; w: number; h: number; records?: number; provider?: Provider | null }) {
  const g = withBuiltin(graphOf(s || { types: [], relations: [] }), provider) as BGraph;
  const V = (g.vertex_types || []).filter((v) => Number.isFinite(v.ui?.position?.x) && Number.isFinite(v.ui?.position?.y));
  if (!V.length && records > 0) {
    const n = Math.min(records, ART_DOTS), gap = 26;
    const rows = Math.ceil(n / ART_COLS), y0 = h / 2 - ((rows - 1) * gap) / 2;
    return (
      <svg className="mm-art-svg" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
        {Array.from({ length: n }, (_, i) => {
          const row = Math.floor(i / ART_COLS), inRow = Math.min(ART_COLS, n - row * ART_COLS);
          return <circle key={i} cx={w / 2 + ((i % ART_COLS) - (inRow - 1) / 2) * gap} cy={y0 + row * gap} r="4.5" fill="var(--faint)" />;
        })}
      </svg>
    );
  }
  if (!V.length) {
    return <svg className="mm-art-svg" viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><circle cx={w / 2} cy={h / 2} r="16" fill="none" stroke="var(--line)" strokeWidth="2" strokeDasharray="4 4" /></svg>;
  }
  const named = V.length <= ART_NAMED && w >= 120;
  const xs = V.map((v) => v.ui.position!.x), ys = V.map((v) => v.ui.position!.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const padX = named ? 40 : 22, padTop = 22, padBottom = named ? 34 : 22;
  const f = Math.min((w - 2 * padX) / Math.max(1, x1 - x0), (h - padTop - padBottom) / Math.max(1, y1 - y0), 0.5);
  const ox = (w - (x1 - x0) * f) / 2, oy = padTop + (h - padTop - padBottom - (y1 - y0) * f) / 2;
  const at = (label: string) => { const v = V.find((x) => x.label === label); return v ? [ox + (v.ui.position!.x - x0) * f, oy + (v.ui.position!.y - y0) * f] : null; };
  const r = w < 60 ? 3.6 : 9;
  const nameOf = (label: string) => { const t = g.titles?.[label] || typeLabel(label); return t.length > 14 ? `${t.slice(0, 13)}…` : t; };
  return (
    <svg className="mm-art-svg" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      {(g.edge_types || []).flatMap((e) => e.connections.map((c, i) => {
        const a = at(c.from_type), b = at(c.to_type);
        if (!a || !b) return null;
        if (c.from_type === c.to_type) return <circle key={`${e.label}-${i}`} cx={a[0] + r} cy={a[1] - r} r={r * 0.9} fill="none" stroke="var(--g-line)" strokeWidth="1.4" />;
        return <line key={`${e.label}-${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="var(--g-line)" strokeWidth="1.4" />;
      }))}
      {V.map((v) => {
        const q = at(v.label)!;
        return (
          <g key={v.label}>
            <circle cx={q[0]} cy={q[1]} r={r} fill={v.ui.color || 'var(--faint)'} stroke="var(--surface)" strokeWidth={w < 60 ? 1 : 3} />
            {named ? <text x={q[0]} y={q[1] + r + 13} textAnchor="middle" fontSize="11" fill="var(--muted)">{nameOf(v.label)}</text> : null}
          </g>
        );
      })}
    </svg>
  );
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
