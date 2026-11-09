'use client';
// A memory's cover (Richard 11-09): the picture its card shows. Where its engine draws a graph (types joined by at least
// one relation: the provider's own concepts, or a schema a person set), it is that graph exactly as the Schema tab draws
// it, made once and kept by the service, and a card only loads it. Where there is no graph (Mem0's lone "Fact", a list
// of labels) the card shows the memory's brick from the agent stack instead, drawn here with no read at all.
//
// The Schema tab makes the cover when it has the schema, and again after a change to it; the Memories page makes the
// ones still missing, one at a time, once the page has settled. Each is named by `coverSig`, a short hash of what the
// drawing shows, so a picture is made again only when the drawing changes. Only someone who may write the memory keeps
// one; anyone else sees the one made here, for this visit.
import { useEffect, useRef } from 'react';
import { putCover, type BuiltinSchema, type Memory, type Provider } from '@/lib/memories';
import { builtinOf, hasRelations, hasSchema, schemaGuides } from './caps';
import type { LSchema } from './schemaModel';
import { graphOf, type VGraph } from './graph/schemaDraft';
import { withBuiltin, type BGraph } from './graph/builtin';

export type CoverGraph = VGraph | BGraph;

/** What a memory's cover draws: its schema with what its provider makes itself, as the Schema tab draws them. */
export const coverGraphOf = (schema: LSchema | null | undefined, provider: Provider | null | undefined): CoverGraph =>
  withBuiltin(graphOf(schema || { types: [], relations: [] }), provider) as CoverGraph;

/** A graph: types joined by at least one relation between two of them. One type alone, or names that relate to
 *  nothing (labels), is not. */
export function isGraph(g: CoverGraph | null | undefined): boolean {
  if (!g) return false;
  const types = new Set((g.vertex_types || []).map((v) => v.label));
  return (g.edge_types || []).some((e) => (e.connections || []).some((c) => c.from_type !== c.to_type && types.has(c.from_type) && types.has(c.to_type)));
}
const builtinIsGraph = (b: BuiltinSchema | null | undefined) => !!b && (b.relations || []).some((r) => r.from !== r.to
  && b.types.some((t) => t.name === r.from) && b.types.some((t) => t.name === r.to));

/** What a card shows, from the list alone: the kept `cover`; for a memory whose provider's own concepts are a graph,
 *  its picture once it is made (`graph`); `maybe` where only its schema can say (a provider whose types a person can
 *  relate); else its `brick`. `p` is the provider as the memory's own workspace reaches it. */
export type PicKind = 'cover' | 'graph' | 'maybe' | 'brick';
export function picKindOf(m: Pick<Memory, 'cover_at'>, p: Provider | null | undefined): PicKind {
  if (m.cover_at) return 'cover';
  if (builtinIsGraph(builtinOf(p))) return 'graph';
  if (schemaGuides(p) && hasRelations(p)) return 'maybe';
  return 'brick';
}

/** The drawing's own version: a change to how a cover is drawn (its layout, framing or sizes) bumps it, and every cover
 *  made before is made again (see coverState). */
export const DRAW_VERSION = 2;
/** A short name for what a drawing shows: `c<version><b|s>_<hash>`, `b` where it is only what the provider makes itself
 *  (so the Memories page can tell, from the provider list alone, whether it is still right), `s` where a person's own
 *  types are in it; the hash covers every type (name, title, colour, icon, place) and every relation (name, colour,
 *  ends). The same drawing always has the same name. */
export function coverSig(g: CoverGraph): string {
  const titles = (g as BGraph).titles || {};
  const v = (g.vertex_types || []).map((t) => [t.label, titles[t.label] || '', t.ui?.color || '', t.ui?.icon || '',
    Math.round(t.ui?.position?.x ?? 0), Math.round(t.ui?.position?.y ?? 0), (t as { builtin?: boolean }).builtin ? 1 : 0].join('|')).sort();
  const e = (g.edge_types || []).flatMap((x) => (x.connections || []).map((c) => [x.label, x.ui?.color || '', c.from_type, c.to_type].join('|'))).sort();
  const own = (g.vertex_types || []).some((t) => !(t as { builtin?: boolean }).builtin);
  return `c${DRAW_VERSION}${own ? 's' : 'b'}_${hash53(`${v.join('\n')}\n--\n${e.join('\n')}`)}`;
}
const SIG = /^c(\d+)([bs])_/;

/** What the Memories page does about a kept cover: nothing (`fresh`, or one with a person's own types, which only its
 *  Schema tab makes again); draw again what the provider makes (`builtin`, no read: the list says it); or read the
 *  schema once to find out (`read`: a cover made before drawings said which they were, for a provider that reads one). */
export type CoverState = 'fresh' | 'builtin' | 'read';
export function coverState(m: Pick<Memory, 'cover_at' | 'cover_sig'>, p: Provider | null | undefined): CoverState {
  if (!m.cover_at) return 'fresh';
  const said = SIG.exec(m.cover_sig || '');
  if (!said) return hasSchema(p) ? 'read' : 'builtin';
  if (said[2] === 's') return 'fresh';
  const now = coverGraphOf(null, p);
  return !isGraph(now) || coverSig(now) === m.cover_sig ? 'fresh' : 'builtin';
}

/** cyrb53: 53 bits of a string, in base 36. */
function hash53(s: string): string {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761); h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

/** Whether this browser can draw a cover (a canvas to draw on, a picture to show). */
export const canDraw = () => typeof window !== 'undefined' && typeof (window as { CanvasRenderingContext2D?: unknown }).CanvasRenderingContext2D !== 'undefined'
  && typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function';

/** A cover drawn in this visit: what it shows, and where the browser holds it. It is the newest the page knows of, so a
 *  card shows it over the one the list named. */
export interface Drawn { sig: string; url: string }
const drawn = new Map<string, Drawn>();
/** The cover drawn for this memory in this visit, if any. */
export const drawnCover = (mid: string): Drawn | null => drawn.get(mid) || null;

// One drawing at a time, whoever asks: the page's and the Schema tab's never run at once.
let line: Promise<unknown> = Promise.resolve();
function inLine<T>(fn: () => Promise<T>): Promise<T> {
  const p = line.then(fn, fn);
  line = p.catch(() => undefined);
  return p;
}

/** Make `m`'s cover from `g` unless the one kept (or one made in this visit) already shows it, and keep it where `keep`
 *  (the person may write the memory). The picture is shown from here at once either way; a keep that fails is tried
 *  again on the next visit. Null where there is nothing to draw. */
export async function keepCover(m: Pick<Memory, 'id' | 'cover_at' | 'cover_sig'>, g: CoverGraph, keep: boolean): Promise<Drawn | null> {
  if (!isGraph(g) || !canDraw()) return null;
  const sig = coverSig(g);
  const have = drawn.get(m.id);
  if (have?.sig === sig) return have;
  if (m.cover_at && m.cover_sig === sig) return null;
  return inLine(async () => {
    const again = drawn.get(m.id);
    if (again?.sig === sig) return again;
    const { drawCover } = await import('./graph/coverShot');
    const pic: Blob = await drawCover(g);
    if (keep) { try { await putCover(m.id, pic, sig); } catch { /* shown from here; kept on a later visit */ } }
    const out = { sig, url: URL.createObjectURL(pic) };
    drawn.set(m.id, out);
    return out;
  });
}

/** How long the Schema tab waits after its schema settles before it makes the cover. */
const SETTLE_MS = 1200;
/** The Schema tab's part: once the schema is read (`ready`) and again after each change has settled, the cover is made
 *  where the drawing differs from the one kept, by someone who may write the memory. Nothing is drawn otherwise. */
export function useCoverKeeper(m: Pick<Memory, 'id' | 'cover_at' | 'cover_sig' | 'privileges'> | null | undefined, g: CoverGraph | null | undefined, ready: boolean) {
  const sig = g && isGraph(g) ? coverSig(g) : '';
  const may = !!m?.privileges?.includes('write');
  const at = useRef({ m, g });
  at.current = { m, g };
  const id = m?.id || '', coverAt = m?.cover_at || 0, coverSigNow = m?.cover_sig || '';
  useEffect(() => {
    if (!id || !sig || !ready || !may || !canDraw()) return undefined;
    if (coverAt && coverSigNow === sig) return undefined;
    const t = setTimeout(() => {
      const { m: mm, g: gg } = at.current;
      if (mm && gg) void keepCover(mm, gg, true).catch(() => undefined);
    }, SETTLE_MS);
    return () => clearTimeout(t);
  }, [id, coverAt, coverSigNow, sig, ready, may]);
}
