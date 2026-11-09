// What a provider makes itself (capabilities.schema.builtin): its types and links, merged into a schema drawing and
// marked built in. The Schema tab draws it locked, and a memory's cover is that drawing. A type already drawn under the same
// name (a kind a memory holds) is marked rather than drawn twice. What's new is laid out among itself and set to the
// left of what already has a place.
import type { Provider } from '@/lib/memories';
import { builtinOf, relText } from '../caps';
import { kindInfo } from '../tree';
import type { EType, VGraph, VType } from './schemaDraft';

export type BConn = { from_type: string; to_type: string; builtin?: boolean };
export type BVType = VType & { builtin?: boolean };
export type BEType = Omit<EType, 'connections'> & { connections: BConn[]; builtin?: boolean };
export type BGraph = Omit<VGraph, 'vertex_types' | 'edge_types'> & { vertex_types: BVType[]; edge_types: BEType[] };

const andList = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

/** "Episode, Entity and Fact": what a provider makes, as a person reads it. */
export function builtinTitles(provider: Provider | null | undefined): string {
  return andList((builtinOf(provider)?.types || []).map((t) => kindInfo(t.name, null).one));
}

/** The corners of a regular figure of `n` types, each side long enough for a link's name between its two ends: an odd
 *  number with a point at the top, an even one lying flat, the first on the left. */
export function figure(n: number): { x: number; y: number }[] {
  if (n < 2) return [{ x: 0, y: 0 }].slice(0, n);
  const R = SIDE / 2 / Math.sin(Math.PI / n), start = n % 2 ? -Math.PI / 2 : Math.PI / 2 + Math.PI / n;
  return Array.from({ length: n }, (_, i) => {
    const a = start + (2 * Math.PI * i) / n;
    return { x: Math.round(R * Math.cos(a)) || 0, y: Math.round(R * Math.sin(a)) || 0 };
  });
}
/** A side of that figure: two types and the longest link name a provider has, with room. */
const SIDE = 260;

export function withBuiltin<G extends VGraph | BGraph | null>(graph: G, provider: Provider | null | undefined): G | BGraph {
  const b = builtinOf(provider);
  if (!graph || !b || !(b.types || []).length) return graph;
  const titles: Record<string, string> = { ...(graph.titles || {}) };
  const vts: BVType[] = (graph.vertex_types || []).map((v) => ({ ...v }));
  const fresh: BVType[] = [];
  for (const t of b.types) {
    const k = kindInfo(t.name, null);
    if (!titles[t.name]) titles[t.name] = k.one;
    const have = vts.find((v) => v.label === t.name);
    if (have) { have.builtin = true; have.description = have.description || t.description; continue; }
    const v: BVType = { label: t.name, description: t.description, properties: [], builtin: true, ui: { color: k.color, icon: k.icon, caption: 'title' } };
    vts.push(v);
    fresh.push(v);
  }
  const ets: BEType[] = (graph.edge_types || []).map((e) => ({ ...e, connections: [...(e.connections || [])] as BConn[] }));
  for (const r of b.relations || []) {
    const label = relText(r.name);
    let e = ets.find((x) => x.label === label);
    if (!e) { e = { label, description: r.description, connections: [], properties: [], ui: {} }; ets.push(e); }
    const at = e.connections.findIndex((c) => c.from_type === r.from && c.to_type === r.to);
    if (at >= 0) e.connections[at] = { ...e.connections[at], builtin: true };
    else e.connections.push({ from_type: r.from, to_type: r.to, builtin: true });
    if (!e.description) e.description = r.description;
  }
  for (const e of ets) if (e.connections.length && e.connections.every((c) => c.builtin)) e.builtin = true;
  if (fresh.length) {
    // What the provider makes is set out as a regular figure, one type on each corner (a triangle for three, the first
    // on top; two side by side, the first on the left): a link between two corners never passes under a third, and
    // each link's name has the side between them to itself. Never the force layout, which could put three in a line.
    const at = figure(fresh.length);
    const placed = vts.filter((v) => !fresh.includes(v) && v.ui && v.ui.position);
    const xs = at.map((q) => q.x), ys = at.map((q) => q.y);
    let dx = 0, dy = 0;
    if (placed.length) {
      const px = placed.map((v) => v.ui.position!.x), py = placed.map((v) => v.ui.position!.y);
      dx = Math.min(...px) - 280 - Math.max(...xs);
      dy = (Math.min(...py) + Math.max(...py)) / 2 - (Math.min(...ys) + Math.max(...ys)) / 2;
    }
    fresh.forEach((v, i) => { v.ui = { ...v.ui, position: { x: Math.round(at[i].x + dx), y: Math.round(at[i].y + dy) } }; });
  }
  return { ...graph, titles, vertex_types: vts, edge_types: ets };
}
