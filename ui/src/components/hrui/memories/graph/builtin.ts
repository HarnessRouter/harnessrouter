// What a provider makes itself (capabilities.schema.builtin): its types and links, merged into a schema drawing and
// marked built in. The Schema tab draws it locked; a memory's card draws it small. A type already drawn under the same
// name (a kind a memory holds) is marked rather than drawn twice. What's new is laid out among itself and set to the
// left of what already has a place.
import type { Provider } from '@/lib/memories';
import { builtinOf, relText } from '../caps';
import { kindInfo } from '../tree';
import { footprint, initialLayout } from './layout';
import type { LRel, LSchema, LType } from '../schemaModel';
import { graphOf, type EType, type VGraph, type VType } from './schemaDraft';

export type BConn = { from_type: string; to_type: string; builtin?: boolean };
export type BVType = VType & { builtin?: boolean };
export type BEType = Omit<EType, 'connections'> & { connections: BConn[]; builtin?: boolean };
export type BGraph = Omit<VGraph, 'vertex_types' | 'edge_types'> & { vertex_types: BVType[]; edge_types: BEType[] };

const andList = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

/** "Episode, Entity and Fact": what a provider makes, as a person reads it. */
export function builtinTitles(provider: Provider | null | undefined): string {
  return andList((builtinOf(provider)?.types || []).map((t) => kindInfo(t.name, null).one));
}

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
    const ids = new Set(fresh.map((v) => v.label));
    const nodes = fresh.map((v) => ({ id: v.label, ...footprint(`${titles[v.label]}\nBuilt in · 00 records`, 38) }));
    const links = (b.relations || []).filter((r) => ids.has(r.from) && ids.has(r.to) && r.from !== r.to).map((r) => ({ source: r.from, target: r.to }));
    const { pos } = initialLayout(nodes, links, { spread: 1.7 });
    const placed = vts.filter((v) => !ids.has(v.label) && v.ui && v.ui.position);
    const xs = [...pos.values()].map((q) => q.x), ys = [...pos.values()].map((q) => q.y);
    let dx = 0, dy = 0;
    if (placed.length) {
      const px = placed.map((v) => v.ui.position!.x), py = placed.map((v) => v.ui.position!.y);
      dx = Math.min(...px) - 280 - Math.max(...xs);
      dy = (Math.min(...py) + Math.max(...py)) / 2 - (Math.min(...ys) + Math.max(...ys)) / 2;
    }
    for (const v of fresh) { const q = pos.get(v.label)!; v.ui = { ...v.ui, position: { x: Math.round(q.x + dx), y: Math.round(q.y + dy) } }; }
  }
  return { ...graph, titles, vertex_types: vts, edge_types: ets };
}

/** A memory's schema as its card draws it (Richard 11-06: the vendor's concepts where nobody set a schema, in Vivian's
 *  drawing): what the provider makes itself and the types a person set, with the links between them, in the schema's
 *  own shape. A provider that declares nothing gives back what was set. */
export function concepts(s: LSchema | null | undefined, provider: Provider | null | undefined): LSchema | null {
  if (!builtinOf(provider)?.types.length) return s ?? null;
  const g = withBuiltin(graphOf(s || { types: [], relations: [] }), provider) as BGraph;
  const placed = g.vertex_types;
  const ids = new Map(placed.map((v) => [v.label, v.id || v.label]));
  // A card is small: the types go evenly around a circle (three a triangle, six a hexagon), so none sits on another or on
  // a line between two others, whatever the canvas layout put where. An even number lies flat, wider than tall like the
  // card, with the first type on the left (two read left to right: Fact, about, Entity); an odd one has a point at the
  // top. The radius gives a link's name room between its two ends at the card's scale.
  const n = Math.max(1, placed.length);
  const R = n <= 3 ? 110 : 60 * n / Math.PI, start = n % 2 ? -Math.PI / 2 : Math.PI / 2 + Math.PI / n;
  // what the provider makes is drawn by its title (Fact, Episode); a person's own type by its name
  const types: LType[] = placed.map((v, i) => {
    const a = start + (2 * Math.PI * i) / n;
    return {
      id: ids.get(v.label) as string, name: v.builtin && g.titles?.[v.label] ? g.titles[v.label] : v.label, description: v.description,
      properties: [], color: v.ui.color || '', icon: v.ui.icon || '', x: Math.round(R * Math.cos(a)), y: Math.round(R * Math.sin(a)), caption: v.ui.caption || 'title',
    };
  });
  const idOf = (label: string) => ids.get(label) || label;
  const relations: LRel[] = g.edge_types.flatMap((e) => e.connections.map((c, i) => ({
    id: `${e.label}:${i}`, name: e.label, description: e.description, from: idOf(c.from_type), to: idOf(c.to_type), color: e.ui.color,
  })));
  return { types, relations };
}
